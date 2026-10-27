import httpx
import pytest

from app.fetch.url_safety import (
    FetchBlockedError,
    SafeFetcher,
    UnsafeURLError,
    validate_public_url,
)

PUBLIC = "93.184.216.34"


def resolver_for(mapping):
    async def _r(host):
        if host not in mapping:
            raise OSError("nxdomain")
        return mapping[host]

    return _r


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://0.0.0.0/",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://printer.local/",
        "ftp://example.com/file",
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://user:pw@example.com/",
        "http://example.com:8080/",
        "http://example.com:22/",
        "http:///nohost",
    ],
)
async def test_unsafe_urls_rejected(url):
    with pytest.raises(UnsafeURLError):
        await validate_public_url(url, resolver_for({"example.com": [PUBLIC]}))


async def test_public_url_allowed():
    ips = await validate_public_url(
        "https://example.com/p", resolver_for({"example.com": [PUBLIC]})
    )
    assert ips == [PUBLIC]


async def test_hostname_resolving_to_private_ip_rejected():
    with pytest.raises(UnsafeURLError):
        await validate_public_url("https://evil.test/", resolver_for({"evil.test": ["10.1.2.3"]}))


async def test_any_private_address_among_many_rejected():
    with pytest.raises(UnsafeURLError):
        await validate_public_url(
            "https://mixed.test/", resolver_for({"mixed.test": [PUBLIC, "127.0.0.1"]})
        )


async def test_unresolvable_host_rejected():
    with pytest.raises(UnsafeURLError):
        await validate_public_url("https://nope.test/", resolver_for({}))


def fetcher(handler, mapping=None, **kw):
    return SafeFetcher(
        resolver=resolver_for(mapping or {"shop.example": [PUBLIC], "other.example": [PUBLIC]}),
        transport=httpx.MockTransport(handler),
        **kw,
    )


async def test_fetch_ok_and_robots_allow():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html"})

    r = await fetcher(handler).fetch("https://shop.example/p")
    assert r.status == 200 and b"ok" in r.body


async def test_fetch_connects_to_pinned_ip_with_host_header():
    seen = []

    def handler(req):
        seen.append((req.url.host, req.headers.get("host")))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="x", headers={"content-type": "text/html"})

    await fetcher(handler).fetch("https://shop.example/p")
    assert all(host == PUBLIC and h == "shop.example" for host, h in seen)


async def test_robots_disallow_blocks():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /p")
        return httpx.Response(200, text="x", headers={"content-type": "text/html"})

    with pytest.raises(FetchBlockedError):
        await fetcher(handler).fetch("https://shop.example/p")


async def test_robots_forbidden_blocks_and_unreachable_robots_is_conservative():
    def forbidden(req):
        return httpx.Response(403)

    with pytest.raises(FetchBlockedError):
        await fetcher(forbidden).fetch("https://shop.example/p")

    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(FetchBlockedError):
        await fetcher(boom).fetch("https://shop.example/p")


async def test_redirect_to_private_address_blocked():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})

    with pytest.raises(UnsafeURLError):
        await fetcher(handler).fetch("https://shop.example/p")


async def test_redirect_to_other_public_host_followed_and_validated():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.headers.get("host") == "shop.example":
            return httpx.Response(301, headers={"location": "https://other.example/q"})
        return httpx.Response(200, text="final", headers={"content-type": "text/html"})

    r = await fetcher(handler).fetch("https://shop.example/p")
    assert r.url == "https://other.example/q" and r.body == b"final"


async def test_redirect_loop_limited():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "https://shop.example/p"})

    from app.fetch.url_safety import FetchError

    with pytest.raises(FetchError):
        await fetcher(handler).fetch("https://shop.example/p")


async def test_response_size_capped():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=b"a" * 5000, headers={"content-type": "text/html"})

    r = await fetcher(handler, max_bytes=1000).fetch("https://shop.example/p")
    assert len(r.body) == 1000 and r.truncated


async def test_binary_content_type_blocked():
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, content=b"MZ", headers={"content-type": "application/octet-stream"}
        )

    with pytest.raises(FetchBlockedError):
        await fetcher(handler).fetch("https://shop.example/p")
