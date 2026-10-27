import pytest

from app.research.domains import DEFAULT_DENYLIST, build_denylist, keep_candidate, platform_of


def test_denylist_subdomain():
    assert not keep_candidate("https://m.1mg.com/x", DEFAULT_DENYLIST)
    assert not keep_candidate("https://www.amazon.in/dp/1", DEFAULT_DENYLIST)
    assert keep_candidate("https://acme-medical.com/p", DEFAULT_DENYLIST)
    assert keep_candidate("https://notamazon.in/p", DEFAULT_DENYLIST)


def test_keep_candidate_rules():
    d = DEFAULT_DENYLIST
    assert not keep_candidate("ftp://acme.com/p", d)
    assert not keep_candidate("https://acme.com/list.PDF", d)
    assert not keep_candidate("not a url", d)
    assert keep_candidate("http://acme.com/p", d)


def test_build_denylist():
    d = build_denylist(" Foo.com, ,bar.in")
    assert {"foo.com", "bar.in", "1mg.com"} <= d
    assert not keep_candidate("https://shop.foo.com/", d)
    assert build_denylist("") == DEFAULT_DENYLIST


@pytest.mark.parametrize("url,want", [
    ("https://www.indiamart.com/p", "IndiaMART"),
    ("https://dir.indiamart.com/x", "IndiaMART"),
    ("https://m.indiamart.com/x", "IndiaMART"),
    ("https://export.indiamart.com/x", "IndiaMART"),
    ("https://www.tradeindia.com/x", "TradeIndia"),
    ("https://www.exportersindia.com/x", "ExportersIndia"),
    ("https://acme.com/x", "Maker site"),
    ("https://notindiamart.com/x", "Maker site"),
])
def test_platform_of(url, want):
    assert platform_of(url) == want
