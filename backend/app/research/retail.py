"""Retail price lookup (Indian pharmacies and marketplaces), run beside the factory research by RunService.

Reference only: it never touches offers, cost, the manufacturer directory or the range. The checks are the
ones build_offers uses: quotes verified on the page, INR only, per-unit price from a stated pack size, the
product type gate and the variant rules. Seller classification does not apply. It has its own budget
(retail_*); every stop is a "Retail:" note, never an exception."""
import asyncio
import re
from itertools import chain, zip_longest

import httpx

from app.clients.errors import LLMError, SearchError
from app.research.deps import ResearchDeps, emit, guard
from app.research.domains import _host, _in, keep_candidate
from app.research.nodes import (
    _NEAR,
    _glued,
    _near_listing,
    _page_block,
    _retry_once,
    _spec_text,
    _starts,
    _trend_price,
    canonical_url,
)
from app.research.prices import pack_size, parse_price, to_unit_price
from app.research.prompts import RETAIL_EXTRACT_INSTRUCTIONS
from app.research.quotes import _squash, normalise_text, quote_in_page
from app.research.schemas import (
    ResearchSpec,
    RetailExtraction,
    RetailListing,
    RetailResult,
    RetailRow,
    attributes_dict,
)
from app.research.spec import match_keys, primary_key_of, type_matches, type_terms_of

RETAILERS = {"1mg.com": "Tata 1mg", "pharmeasy.in": "PharmEasy", "netmeds.com": "Netmeds",
             "apollopharmacy.in": "Apollo Pharmacy", "medplusmart.com": "MedPlus",
             "amazon.in": "Amazon India", "flipkart.com": "Flipkart"}
PER_RETAILER = 2  # product pages read per retailer
MAX_ROWS = 5
_STOP = {"retail_search": "search", "retail_pages": "page", "retail_llm": "AI extraction"}


async def _note(deps: ResearchDeps, notes: list[str], msg: str) -> None:
    if msg not in notes:  # appended before the await, so concurrent pages note it once
        notes.append(msg)
        await emit(deps, "retail", msg, "warn")


async def _take(deps: ResearchDeps, kind: str, notes: list[str]) -> bool:
    b = deps.budget
    if b.expired():
        await _note(deps, notes, "Retail: stopped early, time limit reached")
        return False
    if kind in b.exhausted:
        return False
    if b.take(kind):
        return True
    await _note(deps, notes, f"Retail: stopped early, {_STOP[kind]} budget reached")
    return False


def _candidates(hits) -> list[str]:
    """Up to PER_RETAILER product URLs per retailer, interleaved so every retailer is read first."""
    by_dom: dict[str, list[str]] = {}
    for h in hits:
        u = canonical_url(h.url)
        dom = u and keep_candidate(u, frozenset()) and _in(_host(u), RETAILERS)
        if dom and u not in (got := by_dom.setdefault(dom, [])) and len(got) < PER_RETAILER:
            got.append(u)
    return [u for u in chain.from_iterable(zip_longest(*by_dom.values())) if u]


def _struck_mrp(quote: str, text: str) -> bool:
    """The quote names the MRP, or every occurrence of it on the page is "MRP <quote>" followed within 20
    squashed chars by a lower rupee amount (the struck price before the selling price)."""
    if "mrp" in normalise_text(quote).replace(".", ""):  # "MRP", "M.R.P."
        return True
    page, q, value = _squash(text), _squash(quote), parse_price(quote).value
    starts = _starts(q, page)
    return bool(starts) and all(_struck_at(page, s, s + len(q), value) for s in starts)


_AMOUNT = re.compile(r"₹\d[\d,]*(?:\.\d+)?")
_PACK_SEP = re.compile(r"(?:[/:,\-]|per|for)*")  # squashed text between a price and its pack ("₹150 / pack of 10")


def _struck_at(page: str, s: int, e: int, value) -> bool:
    """The amount at page[s:e] is labelled MRP and a lower rupee amount follows within 20 squashed chars."""
    lower = parse_price(page[e:e + 20])
    label = page[max(0, s - 8):s].replace(".", "").rstrip(":")
    return label.endswith("mrp") and lower is not None and lower.value < value


def _anchors(x: RetailListing, others: set[str], page: str) -> list[tuple[int, int, int]]:
    """R54: (title end, price start, price end) for every place the price quote is this listing's own price.

    From an occurrence of the listing's own title (not one inside another listing's longer title, "Syringe 2 ml"
    in "Romsons Syringe 2 ml"), the price must be the first rupee amount after it, skipping only struck MRP
    amounts, within _NEAR squashed chars, with no other extracted title in between. A glued occurrence ("₹15"
    in "₹150") never counts. The boundary does not depend on what else the extractor returned."""
    q, t = _squash(x.price_quote or ""), _squash(x.product_title)
    if not q or not t:
        return []
    spans = [(s, s + len(o)) for o in others for s in _starts(o, page)]
    ends = [ts + len(t) for ts in _starts(t, page)
            if not any(a <= ts and ts + len(t) <= b and b - a > len(t) for a, b in spans)]
    out = []
    for te in ends:
        for qs in _starts(q, page):
            if _glued(q, page, qs) or not te <= qs <= te + _NEAR or any(te <= a < qs for a, _ in spans):
                continue
            between = list(_AMOUNT.finditer(page, te, qs))
            if all(_struck_at(page, m.start(), m.end(), parse_price(m.group()).value) for m in between):
                out.append((te, qs, qs + len(q)))
    return out


def _pack_ok(pack: str, anchors: list[tuple[int, int, int]], page: str) -> bool:
    """R54: the pack quote lies between the title and the end of its accepted price, or right after the price
    separated only by "/", ":", ",", "-", "per" or "for"."""
    p = _squash(pack)
    for ps in (s for s in _starts(p, page) if p and not _glued(p, page, s)):
        pe = ps + len(p)
        if any(te <= ps and pe <= qe or (ps >= qe and _PACK_SEP.fullmatch(page[qe:ps])) for te, _, qe in anchors):
            return True
    return False


def _row(x: RetailListing, url: str, text: str, spec: ResearchSpec,
         cards: list[tuple[str, str | None]], others: set[str]) -> RetailRow | None:
    """others: the other listings' squashed titles on the page (empty for a single listing)."""
    anchors = _anchors(x, others, _squash(text))
    if not (x.price_quote and quote_in_page(x.price_quote, text) and not _trend_price(x.price_quote, text)
            and quote_in_page(x.product_title, text) and anchors):
        return None  # no verified price or title of its own: never shown
    price = parse_price(x.price_quote)
    if price is None or price.currency != "INR" or _struck_mrp(x.price_quote, text):
        return None
    attrs = attributes_dict([a for a in x.attributes
                             if _near_listing(a.value, text, x.product_title, x.price_quote, cards)])
    if not type_matches(type_terms_of(spec), x.product_title, attrs):
        return None
    keys = match_keys(spec, attrs, x.product_title)
    primary = spec.primary_key or primary_key_of(spec.must_match, spec.attributes)
    if {"mismatch", "ambiguous"} & set(keys.values()) or keys.get(primary) == "unstated":
        return None  # an unstated secondary detail is allowed, as for factory offers
    ok_pack = x.pack_quote and quote_in_page(x.pack_quote, text) and _pack_ok(x.pack_quote, anchors, _squash(text))
    basis = x.pack_quote if ok_pack else x.product_title
    unit, _ = to_unit_price(price.value, basis, x.product_title, x.price_quote)
    n = pack_size(basis, x.product_title)
    if unit is None or n is None:
        return None  # unknown pack size
    return RetailRow(retailer=RETAILERS[_in(_host(url), RETAILERS)], title=x.product_title.strip(), url=url,
                     pack_size=n, unit_price=unit, pack_price=price.value, price_quote=x.price_quote)


async def _read(deps: ResearchDeps, url: str, spec: ResearchSpec, notes: list[str]) -> list[RetailRow]:
    guard(deps)
    if not await _take(deps, "retail_pages", notes):
        return []
    try:
        page = await _retry_once(lambda: deps.fetcher.fetch(url))
    except httpx.TimeoutException:
        page = None
    if page is None:
        return []
    guard(deps)
    if not await _take(deps, "retail_llm", notes):
        return []
    text = f"{_spec_text(spec)}\n\nPage URL: {url}\n{_page_block(page.text)}"
    try:
        ext = await _retry_once(lambda: deps.llm.parse(
            RetailExtraction, instructions=RETAIL_EXTRACT_INSTRUCTIONS, text=text))
    except LLMError:
        await _note(deps, notes, f"Retail: could not read {_host(url)}")
        return []
    return _rows(ext.listings, url, page.text, spec)


def _rows(listings: list[RetailListing], url: str, t: str, spec: ResearchSpec) -> list[RetailRow]:
    cards = [(x.product_title, x.price_quote if x.price_quote and quote_in_page(x.price_quote, t) else None)
             for x in listings if quote_in_page(x.product_title, t)]
    titles = {_squash(x.product_title) for x in listings} - {""}

    return [r for x in listings if (r := _row(x, url, t, spec, cards, titles - {_squash(x.product_title)}))]


async def run_retail(deps: ResearchDeps, spec: ResearchSpec) -> RetailResult:
    if not (deps.tavily.is_configured() and deps.llm.is_configured()):
        return RetailResult(notes=["Retail: search is not configured"])
    guard(deps)
    await emit(deps, "retail", "Finding retail prices")
    notes: list[str] = []
    queries: list[str] = []
    hits: list = []
    for q in (f"{spec.title} price", f"{spec.title} buy online"):
        if not await _take(deps, "retail_search", notes):
            break
        queries.append(q)
        try:
            hits += await _retry_once(lambda q=q: deps.tavily.search(
                q, max_results=20, include_domains=list(RETAILERS)))
        except SearchError:
            await _note(deps, notes, "Retail: search unavailable")
    found = await asyncio.gather(*(_read(deps, u, spec, notes) for u in _candidates(hits)),
                                 return_exceptions=True)
    guard(deps)  # every page task has finished; a cancel seen by one stops the lookup here
    if errors := [f for f in found if isinstance(f, BaseException)]:
        raise errors[0]
    best: dict[str, RetailRow] = {}  # one row per retailer: its cheapest verified listing
    for r in chain.from_iterable(found):
        if r.retailer not in best or r.unit_price < best[r.retailer].unit_price:
            best[r.retailer] = r
    rows = sorted(best.values(), key=lambda r: (r.unit_price, r.retailer))[:MAX_ROWS]
    await emit(deps, "retail", f"Found {len(rows)} retail prices" if rows else "No retail price found")
    return RetailResult(rows=rows, notes=notes, queries=queries)
