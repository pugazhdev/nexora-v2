"""Test doubles shared across node tests."""

from typing import Any


class FakeLLM:
    """Pops queued outputs (or raises queued exceptions) per schema class, recording every call."""

    def __init__(self, outputs: dict[type, list[Any]]):
        self.outputs = {k: list(v) for k, v in outputs.items()}
        self.calls: list[tuple] = []

    def is_configured(self) -> bool:
        return True

    def _next(self, schema, instructions, text, image):
        self.calls.append((schema, instructions, text, image))
        item = self.outputs[schema].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def parse(self, schema, *, instructions, text, image=None):
        return self._next(schema, instructions, text, image)

    async def web_search(self, schema, *, instructions, prompt):
        return self._next(schema, instructions, prompt, None)


class FakeTavily:
    """Canned search hits keyed by query and page text keyed by URL."""

    def __init__(self, hits: dict[str, list], pages: dict[str, str] | None = None):
        self.hits = hits
        self.pages = pages or {}
        self.queries: list[str] = []

    def is_configured(self) -> bool:
        return True

    async def search(self, query, *, max_results, include_domains=None):
        self.queries.append(query)
        return self.hits.get(query, [])[:max_results]

    async def extract(self, url):
        return self.pages.get(url)


class FakeFetcher:
    """Canned pages keyed by URL (stands in for PageFetcher)."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.urls: list[str] = []

    async def fetch(self, url):
        self.urls.append(url)
        return self.pages.get(url)
