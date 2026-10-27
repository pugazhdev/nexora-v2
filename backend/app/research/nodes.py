"""Research graph nodes (spec 6.3): offer branch, cost branch and the cross-branch sanity check.

Every node starts with guard(deps) and checks the budget before each external call. Failures of a
source or a budget stop become a note, never an exception, so one source cannot fail the run.
"""
import asyncio
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import chain, zip_longest
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from langchain_core.runnables import RunnableConfig
from langgraph.types import Send

from app.clients.errors import (
    LLMAuthError,
    LLMError,
    LLMQuotaError,
    LLMTimeoutError,
    SearchError,
    SearchTemporaryError,
)
from app.errors import AppError
from app.research.cost import compute_cost
from app.research.deps import ResearchDeps, deps_of, emit, guard
from app.research.domains import build_denylist, keep_candidate, platform_of
from app.research.prices import apply_gst, gst_rate, parse_price, to_unit_price
from app.research.prompts import (
    BROADEN_INSTRUCTIONS,
    COST_REFINE_INSTRUCTIONS,
    EXTRACT_INSTRUCTIONS,
    MATERIAL_PRICE_INSTRUCTIONS,
    PART_PLAN_NOTE,
    PLAN_INSTRUCTIONS,
    WEB_SEARCH_INSTRUCTIONS,
)
from app.research.quotes import _squash, normalise_text, quote_in_page
from app.research.sanity import apply_sanity
from app.research.schemas import (
    BomLine,
    Candidate,
    CostPlanRefinement,
    ExtractedOffer,
    GstPrefill,
    ItemResult,
    MaterialPrice,
    MaterialPriceExtraction,
    Offer,
    PageExtraction,
    PageOffers,
    ResearchPlan,
    ResearchSpec,
    Tier,
    WebSearchListings,
    attributes_dict,
)
from app.research.sellers import classify_seller, merge_by_manufacturer, normalise_company
from app.research.spec import match_keys, primary_key_of, type_matches, type_terms_of
from app.research.state import ResearchState
from app.research.tiers import price_at, purchase_range

_BUDGET_NOTE = {k: f"Stopped early: {v} budget reached" for k, v in
                {"tavily": "search", "web": "web search", "pages": "page", "llm": "AI extraction"}.items()}
_BUDGET_NOTE |= {k: f"Cost estimate: stopped early, {v} budget reached" for k, v in
                 {"cost_search": "search", "cost_pages": "source", "cost_llm": "AI extraction"}.items()}
_NO_TAVILY_NOTE = "Search is using OpenAI web search only; material costs are estimates."
_PLATFORM_DOMAINS = {"indiamart": "indiamart.com", "tradeindia": "tradeindia.com",
                     "exportersindia": "exportersindia.com"}
_TRACKING = {"gclid", "fbclid"}
_TRANSIENT = (SearchTemporaryError, LLMTimeoutError, httpx.TimeoutException)
EXCLUDING_FLAGS = frozenset({"price_on_request", "basis_unclear", "incl_gst_rate_unknown", "spec_unstated",
                             "ambiguous_variants", "older_listing"})


# ---- shared helpers -------------------------------------------------------------------------

async def _retry_once(call):
    """Run an external call; on a transient failure run it once more (the budget is charged by the caller once)."""
    try:
        return await call()
    except _TRANSIENT:
        return await call()


async def _note(deps: ResearchDeps, phase: str, message: str) -> dict:
    await emit(deps, phase, message, "warn")
    return {"notes": [message]}


def _hard(exc: LLMError) -> dict:
    """G3: a quota or key failure is recorded so finalise can fail the run when no offer was built."""
    return {"provider_errors": [exc.message]} if isinstance(exc, LLMQuotaError | LLMAuthError) else {}


async def _take(deps: ResearchDeps, kind: str, phase: str) -> dict | None:
    """None when the call may go ahead; otherwise the update to return (one note per kind, then silence)."""
    b = deps.budget
    if b.expired():
        # "time" shares the exhausted set so the note is written once per run
        if "time" in b.exhausted:
            return {}
        b.exhausted.add("time")
        return await _note(deps, phase, "Stopped early: time limit reached")
    if kind in b.exhausted:
        return {}
    if b.take(kind):
        return None
    return await _note(deps, phase, _BUDGET_NOTE[kind])


def _spec_text(spec: ResearchSpec) -> str:
    return (f"Product: {spec.title}\nAttributes: {json.dumps(spec.attributes, ensure_ascii=False)}\n"
            f"must_match: {', '.join(spec.must_match) or 'none'}\nQuantity: {spec.quantity}")


def _host(url: str) -> str:
    return urlsplit(url).hostname or url


# ---- plan + discover ------------------------------------------------------------------------

async def plan_research(state: ResearchState, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    spec, part = state["spec"], state.get("mode") == "part"
    fallback = ResearchPlan(queries=[f"{spec.title} manufacturer", f"{spec.title} manufacturer price per piece"],
                            web_prompts=[], hsn_code=None, bill_of_materials=[], process=[], type_terms=[])
    # G1: without Tavily, discovery is OpenAI web search only and material prices are the planner's estimates
    notes = [] if deps.tavily.is_configured() else (await _note(deps, "plan", _NO_TAVILY_NOTE))["notes"]
    if (stop := await _take(deps, "llm", "plan")) is not None:
        return {**stop, "notes": notes + stop.get("notes", []), "plan": fallback}
    instructions = f"{PLAN_INSTRUCTIONS}\n{PART_PLAN_NOTE}" if part else PLAN_INSTRUCTIONS
    try:
        plan = await deps.llm.parse(ResearchPlan, instructions=instructions, text=_spec_text(spec))
    except LLMError as exc:
        failed = await _note(deps, "plan", "Planning failed, using basic searches")
        return {**_hard(exc), "notes": notes + failed["notes"], "plan": fallback}
    if part:
        plan = plan.model_copy(update={"bill_of_materials": [], "process": []})
    await emit(deps, "plan", f"Planned {len(plan.queries) + len(plan.web_prompts)} searches")
    terms = [t.strip().lower() for t in plan.type_terms if t.strip()]
    return {"plan": plan, "notes": notes,
            **({"spec": spec.model_copy(update={"type_terms": terms})} if terms else {})}


def route_discover(state: ResearchState, config: RunnableConfig) -> list[Send] | list[str]:
    deps = deps_of(config)
    plan, used = state["plan"], set(state.get("queries_used") or [])
    sends = []
    if deps.tavily.is_configured():
        sends += [Send("tavily_search", {"query": q}) for q in dict.fromkeys(plan.queries) if q not in used]
    b = deps.budget
    if deps.llm.is_configured() and b.limits.get("web", 0) - b.used.get("web", 0) > 0:
        sends += [Send("web_search", {"prompt": p}) for p in dict.fromkeys(plan.web_prompts) if p not in used]
    return sends or ["merge_candidates"]


async def tavily_search(state: dict, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    q = state["query"]
    if (stop := await _take(deps, "tavily", "search")) is not None:
        return stop
    domains = [d for name, d in _PLATFORM_DOMAINS.items() if name in q.lower()] or None
    try:
        hits = await _retry_once(lambda: deps.tavily.search(
            q, max_results=deps.settings.tavily_max_results, include_domains=domains))
    except SearchError as exc:
        return {**await _note(deps, "search", "Tavily search unavailable, continuing"), "queries_used": [q],
                "search_failures": [exc.message]}
    return {"candidates": [Candidate(url=h.url, title=h.title, source="tavily") for h in hits],
            "queries_used": [q], "searches_ok": 1}


async def web_search(state: dict, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    p = state["prompt"]
    if (stop := await _take(deps, "web", "search")) is not None:
        return stop
    try:
        # the client builds listings from cited URLs only; any price in the answer is ignored
        found = await _retry_once(lambda: deps.llm.web_search(
            WebSearchListings, instructions=WEB_SEARCH_INSTRUCTIONS, prompt=p))
    except LLMError as exc:
        return {**await _note(deps, "search", "OpenAI web search unavailable, continuing"), "queries_used": [p],
                "search_failures": [exc.message], **_hard(exc)}
    cands = [Candidate(url=x.url, title=x.title[:300], source="web_search") for x in found.listings
             if x.url.lower().startswith(("http://", "https://"))]
    return {"candidates": cands, "queries_used": [p], "searches_ok": 1}


# ---- merge + fetch --------------------------------------------------------------------------

def canonical_url(url: str) -> str | None:
    try:
        p = urlsplit(url.strip())
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_") and k.lower() not in _TRACKING]
    except ValueError:
        return None
    path = p.path.rstrip("/") or "/"
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, urlencode(query), ""))


def _merged(state: ResearchState, deps: ResearchDeps, skip: frozenset[str] = frozenset()) -> list[Candidate]:
    """Deterministic: canonical, deduped, allowed, capped round-robin across platforms in first-seen order.

    URLs in skip (already extracted) are removed before the cap, so the cap limits each pass's new candidates."""
    deny = build_denylist(deps.settings.extra_denylist)
    seen: dict[str, Candidate] = {}
    for c in state.get("candidates") or []:
        u = canonical_url(c.url)
        if u and u not in seen and u not in skip and keep_candidate(u, deny):
            seen[u] = c.model_copy(update={"url": u})
    groups: dict[str, list[Candidate]] = {}
    for c in seen.values():
        groups.setdefault(platform_of(c.url), []).append(c)
    interleaved = [c for c in chain.from_iterable(zip_longest(*groups.values())) if c is not None]
    return interleaved[:deps.settings.max_candidates]


async def merge_candidates(state: ResearchState, config: RunnableConfig) -> dict:
    # candidates is an append-only channel, so the merged list is recomputed by route_fetch, not stored
    deps = deps_of(config)
    guard(deps)
    merged = _merged(state, deps)
    n = {k: 0 for k in ("IndiaMART", "TradeIndia", "ExportersIndia", "Maker site")}
    for c in merged:
        n[platform_of(c.url)] += 1
    ei = f", ExportersIndia {n['ExportersIndia']}" if n["ExportersIndia"] else ""
    await emit(deps, "search", f"Found {len(merged)} listings (IndiaMART {n['IndiaMART']}, "
                               f"TradeIndia {n['TradeIndia']}{ei}, maker sites {n['Maker site']})")
    return {}


def route_fetch(state: ResearchState, config: RunnableConfig) -> list[Send] | list[str]:
    deps = deps_of(config)
    # ponytail: pages that failed to fetch are retried after broadening; the page budget bounds it
    done = {p.url for p in state.get("extracted") or []}
    sends = [Send("fetch_extract", {"candidate": c, "spec": state.get("spec")})
             for c in _merged(state, deps, frozenset(done))]
    return sends or ["build_offers"]


def _page_block(text: str) -> str:
    return "<page_data>\n" + re.sub(r"<\s*/?\s*page_data[^>]*>", "", text, flags=re.I) + "\n</page_data>"


async def fetch_extract(state: dict, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    c: Candidate = state["candidate"]
    if (stop := await _take(deps, "pages", "read")) is not None:
        return stop
    try:
        page = await _retry_once(lambda: deps.fetcher.fetch(c.url))
    except httpx.TimeoutException:
        page = None
    if page is None:
        return await _note(deps, "read", f"Could not read {_host(c.url)}")
    guard(deps)
    if (stop := await _take(deps, "llm", "read")) is not None:
        return stop
    spec = state.get("spec")
    text = (_spec_text(spec) + "\n\n" if spec else "") + f"Page URL: {c.url}\n" + _page_block(page.text)
    try:
        ext = await _retry_once(lambda: deps.llm.parse(PageExtraction, instructions=EXTRACT_INSTRUCTIONS, text=text))
    except LLMError as exc:
        return {**await _note(deps, "read", f"Could not extract offers from {_host(c.url)}"), **_hard(exc)}
    return {"extracted": [PageOffers(url=c.url, page_text=page.text, offers=ext.offers)]}


# ---- build_offers: verify, normalise, classify, match ---------------------------------------

_DATE = re.compile(r"(?:last\s+updated|updated\s+on|posted\s+on|date\s*modified|date\s*published)[\"'\s:]*"
                   r"(\d{4}-\d{2}-\d{2}|[a-z]+ \d{1,2}, \d{4})", re.I)
_NEAR = 400  # a seller-type quote counts only this close (squashed chars) to the seller's name
_QTY = re.compile(r"(?<![\d.,])\d[\d,]*(?:\.\d+)?")
_PIECES = re.compile(r"(?:pcs?|pieces?|nos?|units?|numbers?)\.?", re.I)


def _parse_date(s: str) -> date | None:
    try:
        return date.fromisoformat(s) if s[0].isdigit() else datetime.strptime(s.title(), "%B %d, %Y").date()
    except ValueError:
        return None


def _observed_at(page_text: str) -> date | None:
    """Most recent labelled date on the page (dateModified beats datePublished); future dates ignored."""
    # ponytail: page-level date applied to every listing on the page; a per-listing date needs extraction
    latest = date.today() + timedelta(days=1)
    found = [d for m in _DATE.finditer(page_text) if (d := _parse_date(m.group(1))) and d <= latest]
    return max(found, default=None)


def _starts(needle: str, hay: str) -> list[int]:
    out, i = [], hay.find(needle)
    while needle and i != -1:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def _seller_quotes(o: ExtractedOffer, text: str) -> list[str]:
    """Seller-type evidence only when the quote sits near the (already verified) seller name."""
    if not o.seller_type_quote:
        return []
    page, name, quote = _squash(text), _squash(o.seller_name), _squash(o.seller_type_quote)
    names = _starts(name, page)
    near = any(abs(q - n) <= _NEAR for q in _starts(quote, page) for n in names)
    return [o.seller_type_quote] if near else []


def _quantities(quote: str) -> list[int]:
    """Whole numbers in the quote, skipping decimals and numbers right after a currency marker."""
    q = _squash(quote)  # keeps the space between separate digit cells, maps rs/inr to the rupee sign
    return [int(m.group().rstrip(",").replace(",", "")) for m in _QTY.finditer(q)
            if "." not in m.group() and "₹" not in q[max(0, m.start() - 3):m.start()]]


def _tier_ok(t, text: str) -> bool:
    qtys = _quantities(t.quote)
    return quote_in_page(t.quote, text) and bool(qtys) and qtys[0] == t.min_qty


def _glued(v: str, page: str, p: int) -> bool:
    """The occurrence at p is part of a longer number ("20ml" inside "120ml" or "1.20ml")."""
    before, after = page[p - 1] if p else "", page[p + len(v):p + len(v) + 2]
    decimal = before == "." and page[p - 2:p - 1].isdigit()  # "1.20ml", but not a sentence end "x. 20ml"
    return (v[0].isdigit() and (before.isdigit() or decimal)) or (
        v[-1].isdigit() and (after[:1].isdigit() or (after[:1] in ".," and after[1:2].isdigit())))


def _near_listing(value: str, text: str, me: str, price: str | None, cards: list[tuple[str, str | None]]) -> bool:
    """R26c: an occurrence of value counts for this offer only when it is a whole value (not glued) and the
    nearest card anchor (by span gap, within _NEAR) belongs to this offer's card alone. Cards are the page's
    offers, labelled by index. A priced offer anchors on each card's verified price quote (seller name for a
    price-on-request card); a price-on-request offer anchors on seller names. Cards sharing a price string (or
    a name, for name anchors) share spans and tie. A name anchor yields to a price anchor at an equal gap
    ("Alpha Rs 4.65 18G | Beta Ask for price"). With a single card the anchors are this name and price."""
    if not quote_in_page(value, text):
        return False
    page, v, own = _squash(text), _squash(value), (me, price)
    if len(cards) <= 1 and set(cards) <= {own}:
        cards, mine = [own], {0}
        anchors = [(0, 0, me), *([(0, 0, price)] if price else [])]
    else:
        mine = {i for i, c in enumerate(cards) if c == own}
        anchors = [(i, 0, q) if price and q else (i, 1, s) for i, (s, q) in enumerate(cards)]
    if len(mine) != 1:
        return False  # own card missing or duplicated: not attributable
    spans = [(i, i + len(q), c, k) for c, k, q in {(c, k, _squash(a)) for c, k, a in anchors} for i in _starts(q, page)]
    for p in _starts(v, page):
        if _glued(v, page, p):
            continue
        e = p + len(v)
        gaps = [((max(0, a - e, p - b), k), c) for a, b, c, k in spans]
        best = min((g for g, _ in gaps), default=(_NEAR + 1, 0))
        if best[0] <= _NEAR and {c for g, c in gaps if g == best} == mine:
            return True
    return False


_TREND = tuple(_squash(t) for t in ("price trend", "market price", "average price", "price range in india"))


def _trend_price(quote: str, text: str) -> bool:
    """R39: every occurrence of the quote is (or sits within 60 chars after) a trend/average label, not an offer."""
    page, q = _squash(text), _squash(quote)
    starts = _starts(q, page)
    return bool(starts) and all(any(t in page[max(0, s - 60):s + len(q)] for t in _TREND) for s in starts)


def _verified(o: ExtractedOffer, text: str, cards: list[tuple[str, str | None]]) -> ExtractedOffer | None:
    """Null every quote not found on the page; drop the offer when its price quote or seller name is not found."""
    def ok(q: str | None) -> str | None:
        return q if q and quote_in_page(q, text) else None

    price_quote, moq_quote = ok(o.price_quote), ok(o.moq_quote)
    if price_quote and _trend_price(price_quote, text):
        price_quote = None
    if (price_quote is None and not o.price_on_request) or not quote_in_page(o.seller_name, text):
        return None  # never show an unsourced price or seller name
    def near(value: str) -> bool:
        return _near_listing(value, text, o.seller_name, price_quote, cards)

    return o.model_copy(update={
        "price_quote": price_quote, "price_value": o.price_value if price_quote else None,
        "seller_type_quote": ok(o.seller_type_quote), "price_basis_quote": ok(o.price_basis_quote),
        "gst_quote": ok(o.gst_quote), "moq_quote": moq_quote,
        "moq_value": o.moq_value if moq_quote else None, "moq_unit": o.moq_unit if moq_quote else None,
        "tiers": [t for t in o.tiers if _tier_ok(t, text)],
        "product_title": o.product_title if near(o.product_title) else "",
        "attributes": [a for a in o.attributes if near(a.value)],
    })


def _unit_price(quote: str, o: ExtractedOffer) -> tuple[Decimal | None, str | None] | None:
    """(ex-GST unit price or None, flag); None when the quote is not an INR price."""
    parsed = parse_price(quote)
    if parsed is None or parsed.currency != "INR":
        return None
    unit, flag = to_unit_price(parsed.value, o.price_basis_quote or o.price_quote, o.product_title, quote)
    if unit is None:
        return None, flag
    return apply_gst(unit, o.gst_quote)


def _moq(o: ExtractedOffer) -> int | None:
    if not o.moq_value or o.moq_value < 1 or (o.moq_unit and not _PIECES.fullmatch(o.moq_unit.strip())):
        return None
    return int(o.moq_value)


def _tiers(o: ExtractedOffer, unit: Decimal, base_qty: int) -> list[Tier]:
    tiers: dict[int, Decimal] = {}
    for t in o.tiers:
        got = _unit_price(t.quote, o)
        if got and got[0] is not None and t.min_qty >= 1:
            tiers.setdefault(t.min_qty, got[0])
    if not tiers:
        tiers[base_qty] = unit  # no verified tiers: the headline price is the only tier
    return [Tier(min_qty=q, unit_price=p) for q, p in sorted(tiers.items())]


def _offer_id(url: str, seller: str, quote: str) -> str:
    return hashlib.sha256(f"{url}|{seller}|{quote}".encode()).hexdigest()[:16]


def _build_one(o: ExtractedOffer, page: PageOffers, spec: ResearchSpec, observed: date | None,
               max_age: int, cards: list[tuple[str, str | None]]) -> Offer | None:
    v = _verified(o, page.page_text, cards)
    if v is None:
        return None
    attrs = attributes_dict(v.attributes)
    if not type_matches(type_terms_of(spec), v.product_title, attrs):
        return None  # wrong product type (R24)
    keys = match_keys(spec, attrs, v.product_title)
    found = set(keys.values())
    if "mismatch" in found:
        return None
    primary = spec.primary_key or primary_key_of(spec.must_match, spec.attributes)
    verdict = ("ambiguous" if "ambiguous" in found else "unstated" if keys.get(primary) == "unstated"
               else "match")
    flags: list[str] = []
    tiers: list[Tier] = []
    if v.price_on_request:
        flags.append("price_on_request")
    if v.price_quote:
        got = _unit_price(v.price_quote, v)
        if got is None:
            return None  # not an INR price
        unit, flag = got
        flags += [flag] if flag else []
        if unit is not None:
            tiers = _tiers(v, unit, _moq(v) or 1)
    flags += {"unstated": ["spec_unstated"], "ambiguous": ["ambiguous_variants"]}.get(verdict, [])
    if verdict == "match" and "unstated" in found:
        flags.append("spec_partly_confirmed")  # a secondary detail is not stated; still in range, labelled
    if observed and (date.today() - observed).days > max_age:
        flags.append("older_listing")
    classification = classify_seller(_seller_quotes(v, page.page_text))
    seller = v.seller_name.strip()
    return Offer(
        id=_offer_id(page.url, seller, v.price_quote or ""), manufacturer=seller, city=v.seller_city,
        state=v.seller_state, platform=platform_of(page.url), url=page.url, classification=classification,
        tiers=tiers, moq=_moq(v), flags=flags, extra_links=[], price_quote=v.price_quote or "",
        spec_match=verdict, observed_at=observed,
        gst_rate_pct=gst_rate(v.gst_quote),
        in_range=verdict == "match" and classification != "excluded" and not EXCLUDING_FLAGS & set(flags),
    )


def _collapse_duplicates(offers: list[ExtractedOffer], text: str) -> list[ExtractedOffer]:
    """R30: offers sharing (seller, price quote) whose price string occurs once on the page are one card
    extracted twice; keep the first. A price string seen more often may be real cards, so they stay (and tie)."""
    page, seen, out = _squash(text), set(), []
    for o in offers:
        key = (o.seller_name, o.price_quote)
        if o.price_quote and key in seen and len(_starts(_squash(o.price_quote), page)) == 1:
            continue
        seen.add(key)
        out.append(o)
    return out


def _same_listing(offers: list[Offer]) -> list[Offer]:
    """Keep the first of offers with the same id, or the same seller, price text, tiers and MOQ (one listing
    syndicated on several directory pages, its city read on some pages only); other URLs go to extra_links."""
    kept: dict = {}
    for o in offers:
        key = (normalise_company(o.manufacturer), o.price_quote, tuple((t.min_qty, t.unit_price) for t in o.tiers), o.moq) if o.price_quote else o.id
        first = kept.get(o.id) or kept.get(key)
        if first is None:
            kept[o.id] = kept[key] = o
        elif o.url != first.url and o.url not in first.extra_links:
            first.extra_links.append(o.url)
    return list({id(o): o for o in kept.values()}.values())


async def build_offers(state: ResearchState, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    spec, max_age = state["spec"], deps.settings.offer_max_age_days
    offers = []
    for page in state.get("extracted") or []:
        observed = _observed_at(page.page_text)
        text = page.page_text  # card anchors: every verified seller with its verified price quote (R26c)
        extracted = _collapse_duplicates(page.offers, text)
        cards = [(o.seller_name, o.price_quote if o.price_quote and quote_in_page(o.price_quote, text) else None)
                 for o in extracted if quote_in_page(o.seller_name, text)]
        offers += [x for o in extracted if (x := _build_one(o, page, spec, observed, max_age, cards))]
    merged = merge_by_manufacturer(_same_listing(offers))
    kept = sum(o.classification == "manufacturer" for o in merged)
    dropped = sum(o.classification == "excluded" for o in merged)
    await emit(deps, "verify", f"Kept {kept} manufacturers, dropped {dropped} traders")
    return {"offers": merged}


# ---- after offers ---------------------------------------------------------------------------

def route_after_offers(state: ResearchState, config: RunnableConfig) -> Literal["broaden_queries", "offers_done"]:
    deps = deps_of(config)
    if any(o.in_range for o in state.get("offers") or []):
        return "offers_done"
    if state.get("retries_left", 0) > 0 and not deps.budget.expired():
        return "broaden_queries"
    return "offers_done"


async def broaden_queries(state: ResearchState, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    retries = {"retries_left": state.get("retries_left", 0) - 1}
    if (stop := await _take(deps, "llm", "plan")) is not None:
        return {**stop, **retries}
    used = "\n".join(f"- {q}" for q in state.get("queries_used") or [])
    text = f"{_spec_text(state['spec'])}\n\nQueries already used:\n{used or '- none'}"
    try:
        new = await deps.llm.parse(ResearchPlan, instructions=BROADEN_INSTRUCTIONS, text=text)
    except LLMError as exc:
        return {**await _note(deps, "plan", "Broader search failed, continuing"), **retries, **_hard(exc)}
    # only the searches change; the bill of materials feeds the cost branch and stays as planned
    plan = state["plan"].model_copy(update={"queries": new.queries, "web_prompts": new.web_prompts})
    await emit(deps, "plan", f"Broadened to {len(new.queries) + len(new.web_prompts)} searches")
    return {"plan": plan, **retries}


async def offers_done(state: ResearchState, config: RunnableConfig) -> dict:
    return {}


# ---- cost branch (item mode only, after the offer branch) -----------------------------------

_REFINE_FAILED = "Cost estimate: could not check it against market prices, using the first estimate"


def _market_context(offers: list[Offer], qty: int) -> str:
    r = purchase_range(offers, qty)
    if r.lowest_unit is None:
        return "Market: no market price found"
    return f"Market: lowest Rs {r.lowest_unit} per piece, highest Rs {r.highest_unit} per piece"


async def refine_cost_plan(state: ResearchState, config: RunnableConfig) -> dict:
    """One LLM call re-estimating the plan's per-piece BOM and process lines with the market prices in view.
    Only mass_g and estimate_inr change, matched by line name; on a budget stop or LLM error the plan stays."""
    deps = deps_of(config)
    guard(deps)
    plan, spec = state["plan"], state["spec"]
    if not plan.bill_of_materials and not plan.process:
        return {}
    if (stop := await _take(deps, "cost_llm", "verify")) is not None:
        return stop
    lines = {"bill_of_materials": [b.model_dump(include={"component", "material", "mass_g", "estimate_inr"})
                                   for b in plan.bill_of_materials],
             "process": [p.model_dump(include={"step", "estimate_inr"}) for p in plan.process]}
    market = _market_context(state.get("offers") or [], spec.quantity)
    text = (f"Product: {spec.title}\nQuantity: {spec.quantity}\n{market}\n"
            f"First estimate: {json.dumps(lines, ensure_ascii=False)}")
    try:
        ref = await deps.llm.parse(CostPlanRefinement, instructions=COST_REFINE_INSTRUCTIONS, text=text)
    except LLMError as exc:
        return {**await _note(deps, "verify", _REFINE_FAILED), **_hard(exc)}
    # all or nothing: a renamed, dropped or duplicated line, or a value that is not a per-piece cost, would
    # mix refined and first-estimate lines into an inconsistent total, so the whole first estimate stays
    same = (Counter(r.component for r in ref.bill_of_materials) == Counter(b.component for b in plan.bill_of_materials)
            and Counter(r.step for r in ref.process) == Counter(p.step for p in plan.process))
    sane = all(r.mass_g > 0 and r.estimate_inr >= 0 for r in ref.bill_of_materials) \
        and all(r.estimate_inr >= 0 for r in ref.process)
    if not (same and sane):
        return await _note(deps, "verify", _REFINE_FAILED)
    bom = {r.component: r for r in ref.bill_of_materials}
    proc = {r.step: r for r in ref.process}
    # a weighed mass is a measurement, not an estimate: only its cost may change
    plan = plan.model_copy(update={
        "bill_of_materials": [b.model_copy(update={"estimate_inr": bom[b.component].estimate_inr}
                                           | ({} if "weighed" in b.basis.lower()
                                              else {"mass_g": bom[b.component].mass_g}))
                              for b in plan.bill_of_materials],
        "process": [p.model_copy(update={"estimate_inr": proc[p.step].estimate_inr}) for p in plan.process]})
    await emit(deps, "verify", "Checked the cost estimate against market prices")
    return {"plan": plan}


_COST_ABOVE_MARKET = "Estimated making cost is above the lowest market price; treat it as rough."
_N = r"(\d[\d,]*(?:\.\d+)?)"
# a rupee price with the per-kg unit attached: "₹110/kg", "₹105-120 per kg", "₹195 to ₹250 per kg",
# "300.00 ₹ / kilograms"; only "1" may sit between "per" and the unit
_PER_KG = re.compile(r"(?:₹\s*" + _N + r"(?:\s*(?:-|to)\s*₹?\s*\d[\d,]*(?:\.\d+)?)?|" + _N
                     + r"(?:\s*(?:-|to)\s*\d[\d,]*(?:\.\d+)?)?\s*₹)\s*(?:/|per)\s*(?:1\s*)?"
                     r"(?:kgs?|kilos?|kilograms?)(?![a-z])")
_OTHER_AMOUNT = re.compile(r"₹\s*\d|\d\s*₹|[×=+]|\d\s*x\s*\d")
_GENERIC = {"grade", "material", "materials", "price", "india", "medical", "raw", "quality", "for", "of", "and",
            "the", "with", "type", "high", "low"}
_ALIAS = {"pp": "polypropylene", "pe": "polyethylene", "ss": "stainless", "pvc": "polyvinyl", "gi": "galvanized"}
_ALIAS |= {v: k for k, v in _ALIAS.items()}
# R38: a page naming a different variant of the same family near the quote is not this material's price
_FAMILY_VARIANTS = [
    ({"rubber"}, {"natural", "synthetic", "silicone", "bromobutyl", "nitrile", "latex"}),
    ({"steel", "stainless", "ss", "wire", "iron", "gi"}, {"pipe", "pipes", "chain", "sheet", "sheets", "plate",
                                                          "fencing", "barbed"}),
    ({"nonwoven", "spunbond", "meltblown", "spunlace"}, {"spunbond", "meltblown", "spunlace", "sms"}),
]


def _per_kg(quote: str) -> Decimal | None:
    """The INR per kg number of a quote whose unit is attached to the price and that states nothing else
    (no second amount, no arithmetic); else None."""
    q = normalise_text(quote)
    m = _PER_KG.search(q)
    if not m or _OTHER_AMOUNT.search(q[:m.start()] + " " + q[m.end():]) or re.search(r"[×=+]", m.group()):
        return None
    return Decimal((m.group(1) or m.group(2)).replace(",", ""))


def _near_quote(quote: str, text: str, pad: int = 150) -> str | None:
    """The normalised page text within pad squashed chars of the quote (spaces kept for word matching)."""
    n = normalise_text(text)
    keep = [i for i, ch in enumerate(n) if not ch.isspace() or (0 < i < len(n) - 1 and n[i - 1].isdigit()
                                                                and n[i + 1].isdigit())]
    q = _squash(quote)
    p = "".join(n[i] for i in keep).find(q)
    if p < 0 or not q:
        return None
    return n[keep[max(0, p - pad)]:keep[min(len(keep) - 1, p + len(q) + pad - 1)] + 1]


def _tokens(s: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9]+", normalise_text(s).replace("-", ""))) - _GENERIC
    return words | {_ALIAS[w] for w in words if w in _ALIAS}


def _right_material(material: str, near: str) -> bool:
    """R38: a token of the material name is near the quote, and no other variant of its family is."""
    mine, there = _tokens(material), _tokens(near)
    if not mine & there:
        return False
    return not any(mine & fam and (variants & there) - mine for fam, variants in _FAMILY_VARIANTS)


def route_materials(state: ResearchState) -> list[Send]:
    """One price search per distinct BOM material (its components share the price). Process steps are never
    searched (R32): public "rates" are finished-product prices, so process lines use the plan's estimate.
    Nothing to search: compute_cost still runs, so the join always fires (R4); it costs the process lines."""
    plan = state["plan"]
    by_material: dict[str, list[BomLine]] = {}
    for b in plan.bill_of_materials:
        by_material.setdefault(b.material.strip().lower(), []).append(b)
    sends = [Send("price_material", {"line": g[0], "labels": [b.component for b in g]}) for g in by_material.values()]
    return sends or [Send("compute_cost_node", {"plan": plan} if plan.process else {})]


def _cited_price(ext: MaterialPriceExtraction, pages: list, material: str) -> tuple[Decimal, str] | None:
    """(INR per kg, source URL) when the quote is on a fetched page, states a per kg rupee price whose number is
    the claimed one, and the page names this material near it (R38); else None."""
    if not ext.quote or ext.inr_per_kg is None:
        return None
    value = _per_kg(ext.quote)
    if value is None or value <= 0 or value != Decimal(str(ext.inr_per_kg)):
        return None
    for p in pages:
        if quote_in_page(ext.quote, p.text) and (near := _near_quote(ext.quote, p.text)) \
                and _right_material(material, near):
            return value, p.url
    return None


async def price_material(state: dict, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    line: BomLine = state["line"]
    name = line.material
    if not deps.tavily.is_configured():
        return {}
    if (stop := await _take(deps, "cost_search", "search")) is not None:
        return stop
    query = f"{name} price per kg India"
    try:
        hits = await _retry_once(lambda: deps.tavily.search(query, max_results=5))
    except SearchError:
        return await _note(deps, "search", f"Price search for {name} unavailable, using estimate")
    deny = build_denylist(deps.settings.extra_denylist)
    urls = list(dict.fromkeys(u for h in hits if (u := canonical_url(h.url)) and keep_candidate(u, deny)))[:2]
    # R36: the second result is read only when the first gives no verified price
    for url in urls:
        guard(deps)
        if (stop := await _take(deps, "cost_pages", "read")) is not None:
            return stop
        try:
            page = await _retry_once(lambda u=url: deps.fetcher.fetch(u))
        except httpx.TimeoutException:
            page = None
        if page is None:
            continue
        guard(deps)
        if (stop := await _take(deps, "cost_llm", "read")) is not None:
            return stop
        text = f"Material: {name}\n\nPage URL: {page.url}\n{_page_block(page.text)}"
        try:
            ext = await _retry_once(lambda t=text: deps.llm.parse(
                MaterialPriceExtraction, instructions=MATERIAL_PRICE_INSTRUCTIONS, text=t))
        except LLMError as exc:
            return {**await _note(deps, "read", f"Could not read a price for {name}, using estimate"), **_hard(exc)}
        if cited := _cited_price(ext, [page], name):
            value, src = cited
            return {"material_prices": [
                MaterialPrice(label=lb, material=name, quote=ext.quote, source_url=src, inr_per_kg=value)
                for lb in state["labels"]]}
    return {}  # no verified price: compute_cost uses the planner's estimate, labelled as such


async def compute_cost_node(state: ResearchState, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    plan, s = state.get("plan"), deps.settings
    if plan is None:  # R4: reached by Send with no lines to cost
        return {"cost": None}
    est = {b.component: Decimal(str(b.estimate_inr)) for b in plan.bill_of_materials}
    est |= {p.step: Decimal(str(p.estimate_inr)) for p in plan.process}
    # R32: process lines are never cited, only material prices are passed in
    prices = [m for m in state.get("material_prices") or [] if m.inr_per_kg is not None]
    cost = compute_cost(plan.bill_of_materials, plan.process, prices, est,
                        overhead_pct=Decimal(str(s.overhead_pct)), mass_pct=Decimal(str(s.mass_uncertainty_pct)))
    if cost:
        cited = sum(not ln.estimated for ln in cost.lines)
        await emit(deps, "verify", f"Estimated making cost Rs {cost.per_unit} per unit "
                                   f"({cited} of {len(cost.lines) - 1} lines cited)")
    return {"cost": cost}


async def check_sanity(state: ResearchState, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    s, before = deps.settings, state.get("offers") or []
    cost, qty = state.get("cost"), state["spec"].quantity
    factors = {"low_factor": Decimal(str(s.unusually_low_factor)), "outlier_factor": Decimal(str(s.outlier_factor))}
    offers = apply_sanity(before, cost, qty, **factors)
    out: dict = {}
    # R33b: compare with the displayed range; R29 only removes high offers, so its lowest is final
    lowest = purchase_range(offers, qty).lowest_unit
    if cost and lowest is not None and cost.per_unit > lowest:
        out["notes"] = [_COST_ABOVE_MARKET]
        await emit(deps, "verify", _COST_ABOVE_MARKET, "warn")
        if cost.confidence != "low":
            cost = out["cost"] = cost.model_copy(update={"confidence": "low"})
            offers = apply_sanity(before, cost, qty, **factors)  # R37: a low-confidence cost only warns
    if n := sum(a is not b for a, b in zip(before, offers, strict=True)):
        await emit(deps, "verify", f"Sanity check flagged {n} offers")
    return {"offers": offers, **out}


# ---- finalise -------------------------------------------------------------------------------

def _sort_key(o: Offer, qty: int):
    p = price_at(o.tiers, qty)
    if p is not None:
        return 0, p, o.id
    return 1, min((t.unit_price for t in o.tiers), default=Decimal("Infinity")), o.id


def _gst_prefill(offers: list[Offer]) -> GstPrefill | None:
    rated = [o for o in offers if o.gst_rate_pct is not None]
    if not rated:
        return None
    counts = Counter(o.gst_rate_pct for o in rated)
    rate = min(counts, key=lambda r: (-counts[r], r))  # most common, tie -> lowest
    return GstPrefill(rate_pct=rate, source_url=next(o.url for o in rated if o.gst_rate_pct == rate))


def _persist(deps: ResearchDeps, offers: list[Offer], qty: int) -> None:
    for o in offers:
        if o.classification == "excluded":
            continue
        mid = deps.repo.upsert_manufacturer(o.manufacturer, normalise_company(o.manufacturer), o.city, o.state, None)
        price = price_at(o.tiers, qty)
        deps.repo.add_listing(mid, deps.run_id, {
            "url": o.url, "platform": o.platform, "unit_price": float(price) if price is not None else None,
            "tiers": [{"min_qty": t.min_qty, "unit_price": str(t.unit_price)} for t in o.tiers], "moq": o.moq,
            "classification": o.classification, "spec_match": o.spec_match})


async def finalise(state: ResearchState, config: RunnableConfig) -> dict:
    deps = deps_of(config)
    guard(deps)
    spec = state["spec"]
    if not state.get("offers"):
        # G2/G3: nothing was built because a provider failed, so fail the run (Retry) with its message
        if hard := state.get("provider_errors"):
            raise AppError(hard[0])
        if (failed := state.get("search_failures")) and not state.get("searches_ok"):
            raise AppError(failed[0])
    offers = sorted(state.get("offers") or [], key=lambda o: _sort_key(o, spec.quantity))
    await asyncio.to_thread(_persist, deps, offers, spec.quantity)
    b = deps.budget
    notes = list(state.get("notes") or [])
    notes += [_BUDGET_NOTE[k] for k in _BUDGET_NOTE if k in b.exhausted]
    if b.expired():
        notes.append("Stopped early: time limit reached")
    result = ItemResult(spec_title=spec.title, quantity=spec.quantity, cost=state.get("cost"), offers=offers, gst=_gst_prefill(offers),
                        notes=list(dict.fromkeys(notes)), queries=list(dict.fromkeys(state.get("queries_used") or [])))
    return {"result": result}
