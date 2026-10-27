"""SSRF protection and a safe page fetcher (public http(s) only, per-hop validation, size caps)."""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx

Resolver = Callable[[str], Awaitable[list[str]]]
BLOCKED_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home", ".corp")
ALLOWED_PORTS = {None, 80, 443}
ALLOWED_CONTENT = ("text/html", "application/xhtml+xml", "application/json", "text/plain")


class UnsafeURLError(Exception):
    pass


class FetchBlockedError(Exception):
    """Fetch refused by robots policy or content restrictions."""


class FetchError(Exception):
    pass


async def default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return list({i[4][0] for i in infos})


def _ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not addr.is_multicast


async def validate_public_url(url: str, resolver: Resolver = default_resolver) -> list[str]:
    """Return the resolved public IPs, or raise UnsafeURLError."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Malformed URL.") from exc
    if parts.scheme not in ("http", "https"):
        raise UnsafeURLError("Only http(s) URLs are allowed.")
    if parts.username or parts.password:
        raise UnsafeURLError("URLs with credentials are not allowed.")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeURLError("URL has no host.")
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError("Non-standard ports are not allowed.")
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        raise UnsafeURLError("Internal hostnames are not allowed.")
    try:
        ipaddress.ip_address(host)
        ips = [host]
    except ValueError:
        try:
            ips = await resolver(host)
        except OSError as exc:
            raise UnsafeURLError("Host could not be resolved.") from exc
    if not ips:
        raise UnsafeURLError("Host could not be resolved.")
    for ip in ips:
        if not _ip_is_public(ip):
            raise UnsafeURLError("Destination resolves to a non-public address.")
    return ips


@dataclass
class FetchResult:
    url: str
    status: int
    content_type: str
    body: bytes
    truncated: bool


class SafeFetcher:
    """Fetch with: validation of every redirect hop, DNS pinning (no rebinding), size cap, robots.txt."""

    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_bytes: int = 1_500_000,
        user_agent: str = "PharmaSourceBot/0.1",
        respect_robots: bool = True,
        resolver: Resolver = default_resolver,
        transport: httpx.AsyncBaseTransport | None = None,
        max_redirects: int = 3,
    ):
        self._timeout = timeout
        self._max_bytes = max_bytes
        self._ua = user_agent
        self._robots_on = respect_robots
        self._resolver = resolver
        self._transport = transport
        self._max_redirects = max_redirects
        self._robots: dict[str, RobotFileParser | None] = {}

    async def _request(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        ips = await validate_public_url(url, self._resolver)
        parts = urlsplit(url)
        host = parts.hostname or ""
        try:
            ipaddress.ip_address(host)
            target = url
            extensions: dict = {}
            headers = {"User-Agent": self._ua}
        except ValueError:
            ip = ips[0]
            netloc = f"[{ip}]" if ":" in ip else ip
            if parts.port:
                netloc += f":{parts.port}"
            target = parts._replace(netloc=netloc).geturl()
            extensions = {"sni_hostname": host}
            headers = {"User-Agent": self._ua, "Host": parts.netloc}
        req = client.build_request("GET", target, headers=headers, extensions=extensions)
        return await client.send(req, stream=True)

    async def _read(self, resp: httpx.Response) -> tuple[bytes, bool]:
        chunks, size, truncated = [], 0, False
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > self._max_bytes:
                chunks.append(chunk[: len(chunk) - (size - self._max_bytes)])
                truncated = True
                break
            chunks.append(chunk)
        await resp.aclose()
        return b"".join(chunks), truncated

    async def _robots_allows(self, client: httpx.AsyncClient, url: str) -> bool:
        if not self._robots_on:
            return True
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: RobotFileParser | None = RobotFileParser()
            try:
                resp = await self._request(client, f"{origin}/robots.txt")
                body, _ = await self._read(resp)
                if resp.status_code == 200:
                    parser.parse(body.decode("utf-8", "replace").splitlines())  # type: ignore[union-attr]
                elif resp.status_code in (401, 403):
                    parser.disallow_all = True  # type: ignore[union-attr]
                else:
                    parser.allow_all = True  # type: ignore[union-attr]
            except (httpx.HTTPError, UnsafeURLError):
                parser = None  # robots unreachable: be conservative below
            self._robots[origin] = parser
        parser = self._robots[origin]
        if parser is None:
            return False
        return parser.can_fetch(self._ua, url)

    async def fetch(self, url: str) -> FetchResult:
        async with httpx.AsyncClient(
            timeout=self._timeout, follow_redirects=False, transport=self._transport
        ) as client:
            current = url
            for _ in range(self._max_redirects + 1):
                await validate_public_url(current, self._resolver)
                if not await self._robots_allows(client, current):
                    raise FetchBlockedError("Blocked by robots.txt.")
                try:
                    resp = await self._request(client, current)
                except httpx.HTTPError as exc:
                    raise FetchError(f"Request failed: {type(exc).__name__}") from exc
                if resp.is_redirect and resp.headers.get("location"):
                    nxt = urljoin(current, resp.headers["location"])
                    await resp.aclose()
                    current = nxt
                    continue
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if ctype and not ctype.startswith(ALLOWED_CONTENT):
                    await resp.aclose()
                    raise FetchBlockedError(f"Unsupported content type: {ctype}")
                body, truncated = await self._read(resp)
                return FetchResult(current, resp.status_code, ctype, body, truncated)
            raise FetchError("Too many redirects.")
