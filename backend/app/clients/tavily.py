"""Tavily search (supplier discovery) and extract (page-fetch fallback). Snippets are untrusted data."""

from dataclasses import dataclass

import httpx

from app.clients.errors import SearchAuthError, SearchError, SearchTemporaryError

BASE = "https://api.tavily.com"
SNIPPET_MAX = 600


@dataclass(frozen=True)
class SearchHit:
    url: str
    title: str
    snippet: str


class Tavily:
    def __init__(self, api_key: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        self._key = api_key
        self._timeout = timeout
        self._transport = transport

    def is_configured(self) -> bool:
        return bool(self._key.strip())

    async def _post(self, path: str, body: dict) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                resp = await c.post(BASE + path, json=body, headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException as exc:
            raise SearchTemporaryError("Tavily request timed out.") from exc
        except httpx.HTTPError as exc:
            raise SearchTemporaryError("Could not reach Tavily.") from exc
        if resp.status_code in (401, 403):
            raise SearchAuthError("Tavily rejected the configured API key.")
        if resp.status_code == 429 or resp.status_code >= 500:
            raise SearchTemporaryError(f"Tavily returned HTTP {resp.status_code}.")
        if resp.status_code >= 400:
            raise SearchError(f"Tavily returned HTTP {resp.status_code}.")
        try:
            data = resp.json()
        except ValueError as exc:
            raise SearchError("Tavily returned invalid JSON.") from exc
        return data if isinstance(data, dict) else {}

    async def search(
        self, query: str, *, max_results: int, include_domains: list[str] | None = None
    ) -> list[SearchHit]:
        body: dict = {
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "country": "india",
            "include_answer": False,
            "include_raw_content": False,
        }
        if include_domains:
            body["include_domains"] = include_domains
        data = await self._post("/search", body)
        hits: list[SearchHit] = []
        seen: set[str] = set()
        for r in data.get("results") or []:
            url = r.get("url")
            if not isinstance(url, str) or not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            hits.append(SearchHit(url, str(r.get("title") or "")[:300], str(r.get("content") or "")[:SNIPPET_MAX]))
        return hits

    async def extract(self, url: str) -> str | None:
        """Fallback fetch; any failure means no content (caller already has a primary path)."""
        try:
            data = await self._post("/extract", {"urls": [url]})
        except SearchError:
            return None
        results = data.get("results") or []
        content = results[0].get("raw_content") if results else None
        return content if isinstance(content, str) and content else None
