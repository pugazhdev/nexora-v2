from pathlib import Path

from app.fetch.pages import MAX_CHARS, Page, PageFetcher
from app.fetch.text import html_to_text
from app.fetch.url_safety import FetchBlockedError, FetchError, FetchResult, UnsafeURLError
from tests.fakes import FakeFetcher, FakeTavily

URL = "https://example.com/p"
LONG = "<html><body><p>" + "Price 12 INR per piece. " * 60 + "</p></body></html>"


class StubSafe:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, 0

    async def fetch(self, url):
        self.calls += 1
        if self.exc:
            raise self.exc
        return self.result


def ok(body=LONG, status=200):
    return FetchResult(URL, status, "text/html", body.encode(), False)


def make(repo, safe, tavily=None):
    return PageFetcher(safe, tavily or FakeTavily({}), repo, 24)


def test_html_to_text_drops_scripts_keeps_jsonld():
    html = (
        "<html><head><style>.x{}</style><script>var a=1;</script>"
        '<script type="application/ld+json">{"price": "99"}</script></head>'
        "<body><nav>MENU</nav><h1>Syringe</h1><p>Rs 5</p><footer>FOOT</footer></body></html>"
    )
    out = html_to_text(html)
    assert "Syringe" in out and "Rs 5" in out and '{"price": "99"}' in out
    assert "var a" not in out and "MENU" not in out and "FOOT" not in out and ".x{}" not in out
    assert "Syringe\nRs 5" in out


def test_html_to_text_on_saved_pages():
    for f in Path(__file__).parent.joinpath("fixtures/pages").glob("*.html"):
        out = html_to_text(f.read_text(encoding="utf-8", errors="replace"))
        assert out.strip() and "<script" not in out


async def test_cache_hit_skips_network(repo):
    repo.cache_put(URL, "cached text", "direct", 200)
    safe = StubSafe(ok())
    page = await make(repo, safe).fetch(URL)
    assert page == Page(URL, "cached text", "cache") and safe.calls == 0


async def test_403_falls_back_to_tavily_extract(repo):
    t = FakeTavily({}, pages={URL: "extracted"})
    page = await make(repo, StubSafe(ok("denied", 403)), t).fetch(URL)
    assert page == Page(URL, "extracted", "tavily_extract")


async def test_robots_block_and_503_fall_back(repo):
    t = FakeTavily({}, pages={URL: "extracted", URL + "2": "extracted"})
    assert (await make(repo, StubSafe(exc=FetchBlockedError()), t).fetch(URL)).via == "tavily_extract"
    assert (await make(repo, StubSafe(ok("x", 503)), t).fetch(URL + "2")).via == "tavily_extract"


async def test_short_js_shell_falls_back(repo):
    t = FakeTavily({}, pages={URL: "real content"})
    page = await make(repo, StubSafe(ok("<html><body><div id=app></div></body></html>")), t).fetch(URL)
    assert page.via == "tavily_extract"


async def test_captcha_falls_back(repo):
    body = "<html><body><p>Please solve the CAPTCHA</p>" + "<p>filler text here</p>" * 100 + "</body></html>"
    t = FakeTavily({}, pages={URL: "real content"})
    assert (await make(repo, StubSafe(ok(body)), t).fetch(URL)).via == "tavily_extract"


async def test_unsafe_url_returns_none_without_fallback(repo):
    t = FakeTavily({}, pages={URL: "extracted"})
    assert await make(repo, StubSafe(exc=UnsafeURLError("no")), t).fetch(URL) is None


async def test_both_fail_returns_none(repo):
    assert await make(repo, StubSafe(ok("denied", 403))).fetch(URL) is None


async def test_successful_fetch_is_cached(repo):
    safe = StubSafe(ok())
    f = make(repo, safe)
    first = await f.fetch(URL)
    second = await f.fetch(URL)
    assert first.via == "direct" and second.via == "cache" and second.text == first.text
    assert safe.calls == 1


async def test_text_is_capped(repo):
    big = "<p>" + "a" * 100_000 + "</p>"
    assert len((await make(repo, StubSafe(ok(big))).fetch(URL)).text) == MAX_CHARS
    t = FakeTavily({}, pages={URL: "b" * 100_000})
    page = await make(repo, StubSafe(ok("x", 403)), t).fetch(URL)
    assert len(page.text) == MAX_CHARS


async def test_fake_fetcher():
    f = FakeFetcher({URL: Page(URL, "t", "direct")})
    assert (await f.fetch(URL)).text == "t" and await f.fetch("x") is None


async def test_jsonld_survives_cap_on_long_page(repo):
    html = (
        '<html><head><script type="application/ld+json">{"price": "4242"}</script></head>'
        "<body><p>" + "visible " * 20_000 + "</p></body></html>"
    )
    page = await make(repo, StubSafe(ok(html))).fetch(URL)
    assert '{"price": "4242"}' in page.text and len(page.text) <= MAX_CHARS


async def test_network_error_falls_back_to_tavily_extract(repo):
    t = FakeTavily({}, pages={URL: "extracted"})
    page = await make(repo, StubSafe(exc=FetchError("boom")), t).fetch(URL)
    assert page == Page(URL, "extracted", "tavily_extract")
