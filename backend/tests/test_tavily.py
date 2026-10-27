import json

import httpx
import pytest

from app.clients.errors import SearchAuthError, SearchTemporaryError
from app.clients.tavily import Tavily


def client(handler):
    return Tavily("key", 5.0, transport=httpx.MockTransport(handler))


def reply(status=200, body=None):
    return lambda req: httpx.Response(status, json=body or {})


async def test_search_parses_hits_and_dedupes_urls():
    body = {"results": [
        {"url": "https://a.com/x", "title": "A", "content": "z" * 1000},
        {"url": "https://a.com/x", "title": "dup", "content": "d"},
        {"url": "ftp://bad", "title": "B", "content": "b"},
        {"url": "https://b.com/y", "title": "B", "content": "b"},
    ]}
    hits = await client(reply(200, body)).search("q", max_results=5)
    assert [h.url for h in hits] == ["https://a.com/x", "https://b.com/y"]
    assert len(hits[0].snippet) == 600


async def test_search_sends_country_and_domains():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["auth"] = req.headers["authorization"]
        return httpx.Response(200, json={"results": []})

    await client(handler).search("q", max_results=3, include_domains=["indiamart.com"])
    assert seen["auth"] == "Bearer key"
    assert seen["body"]["country"] == "india"
    assert seen["body"]["search_depth"] == "advanced"
    assert seen["body"]["max_results"] == 3
    assert seen["body"]["include_domains"] == ["indiamart.com"]


async def test_401_is_auth_error():
    with pytest.raises(SearchAuthError):
        await client(reply(401)).search("q", max_results=1)


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_429_and_5xx_are_temporary(status):
    with pytest.raises(SearchTemporaryError):
        await client(reply(status)).search("q", max_results=1)


async def test_timeout_is_temporary():
    def handler(req):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(SearchTemporaryError):
        await client(handler).search("q", max_results=1)


async def test_extract_returns_raw_content():
    body = {"results": [{"url": "https://a.com", "raw_content": "page text"}], "failed_results": []}
    assert await client(reply(200, body)).extract("https://a.com") == "page text"


async def test_extract_failure_returns_none():
    body = {"results": [], "failed_results": [{"url": "https://a.com", "error": "x"}]}
    assert await client(reply(200, body)).extract("https://a.com") is None
    assert await client(reply(500)).extract("https://a.com") is None
