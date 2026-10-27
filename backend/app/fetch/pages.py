"""Page fetcher: cache, then direct fetch, then Tavily extract on blocks or thin pages."""

from dataclasses import dataclass
from typing import Literal

from app.clients.tavily import Tavily
from app.fetch.text import html_to_text
from app.fetch.url_safety import FetchBlockedError, FetchError, SafeFetcher, UnsafeURLError
from app.repo import Repository

MAX_CHARS = 60_000
MIN_VISIBLE = 500
FALLBACK_STATUSES = {401, 403, 429, 503}


@dataclass
class Page:
    url: str
    text: str
    via: Literal["direct", "tavily_extract", "cache"]


def _needs_fallback(text: str) -> bool:
    head = text[:2000].lower()
    return len(text.strip()) < MIN_VISIBLE or "captcha" in head or "access denied" in head


class PageFetcher:
    def __init__(self, safe: SafeFetcher, tavily: Tavily, repo: Repository, cache_hours: int):
        self._safe, self._tavily, self._repo, self._hours = safe, tavily, repo, cache_hours

    async def fetch(self, url: str) -> Page | None:
        hit = self._repo.cache_get(url, self._hours)
        if hit:
            return Page(url, hit["text"], "cache")
        try:
            res = await self._safe.fetch(url)
        except UnsafeURLError:
            return None
        except (FetchBlockedError, FetchError):
            return await self._extract(url)
        if res.status in FALLBACK_STATUSES:
            return await self._extract(url)
        if res.status >= 400:
            return None
        text = html_to_text(res.body.decode("utf-8", "replace"))[:MAX_CHARS]
        if _needs_fallback(text):
            return await self._extract(url)
        self._repo.cache_put(url, text, "direct", res.status)
        return Page(url, text, "direct")

    async def _extract(self, url: str) -> Page | None:
        raw = await self._tavily.extract(url)
        if not raw:
            return None
        text = raw[:MAX_CHARS]
        self._repo.cache_put(url, text, "tavily_extract", 200)
        return Page(url, text, "tavily_extract")
