"""Domain rules: retail/marketplace denylist and platform detection."""
from urllib.parse import urlparse

DEFAULT_DENYLIST = frozenset({
    "1mg.com", "pharmeasy.in", "netmeds.com", "apollopharmacy.in", "medplusmart.com", "amazon.in",
    "amazon.com", "flipkart.com", "meesho.com", "jiomart.com", "smartmedicalbuyer.com",
})
_PLATFORMS = (("indiamart.com", "IndiaMART"), ("tradeindia.com", "TradeIndia"),
              ("exportersindia.com", "ExportersIndia"))


def build_denylist(extra: str) -> frozenset[str]:
    return DEFAULT_DENYLIST | {d.strip().lower() for d in extra.split(",") if d.strip()}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _in(host: str, domains) -> str | None:
    return next((d for d in domains if host == d or host.endswith("." + d)), None)


def platform_of(url: str) -> str:
    host = _host(url)
    return next((name for d, name in _PLATFORMS if _in(host, [d])), "Maker site")


def keep_candidate(url: str, denylist: frozenset[str]) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return (p.scheme in ("http", "https") and bool(host) and not _in(host, denylist)
            and not p.path.lower().endswith(".pdf"))
