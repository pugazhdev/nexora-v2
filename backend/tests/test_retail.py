"""Retail price lookup: verified rows only, per-unit price, MRP vs selling price, one row per retailer,
budget, and the service never letting retail change or fail the item."""
import asyncio
from decimal import Decimal
from pathlib import Path

from alembic.config import Config
from sqlalchemy import inspect

from alembic import command
from app.clients.tavily import SearchHit
from app.config import Settings
from app.db import Database
from app.errors import AppError
from app.fetch.pages import Page
from app.research.budget import Budget
from app.research.deps import Cancelled, ResearchDeps
from app.research.retail import RETAILERS, _rows, run_retail
from app.research.schemas import (
    ItemResult,
    ResearchSpec,
    RetailExtraction,
    RetailListing,
    RetailResult,
)
from tests.fakes import FakeFetcher, FakeTavily
from tests.helpers import ITEM, SPEC, seeded_item
from tests.test_runs import finish, mk_item, seed, service
from tests.test_split import done_item, finish_split, make_fn

RSPEC = ResearchSpec(name="Disposable syringe", attributes={"capacity": "2 mL"}, quantity=100,
                     title="Disposable syringe, 2 mL", must_match=["capacity"], primary_key="capacity")
Q1, Q2 = "Disposable syringe, 2 mL price", "Disposable syringe, 2 mL buy online"


class PageLLM:
    """Returns the extraction for the page URL named in the text (pages are read concurrently)."""

    def __init__(self, by_url: dict[str, list[RetailListing]]):
        self.by_url, self.calls = by_url, 0

    def is_configured(self) -> bool:
        return True

    async def parse(self, schema, *, instructions, text, image=None):
        self.calls += 1
        url = next(u for u in self.by_url if f"Page URL: {u}\n" in text)
        return RetailExtraction(listings=self.by_url[url])


def listing(title="Dispovan 2 ml Syringe", price="₹150", pack="Pack of 10", currency="INR", attrs=()):
    return RetailListing(product_title=title, attributes=list(attrs), price_quote=price, pack_quote=pack,
                         currency=currency)


def deps_for(repo, pages: dict[str, str], by_url: dict, hits=None, limits=None):
    run = repo.create_run(seeded_item(repo, [ITEM]), {}, SPEC)
    hits = hits if hits is not None else {Q1: [SearchHit(u, "t", "s") for u in pages]}
    budget = Budget(limits or {"retail_search": 4, "retail_pages": 8, "retail_llm": 8}, 180)
    tav = FakeTavily(hits)
    fetch = FakeFetcher({u: Page(u, t, "direct") for u, t in pages.items()})
    return ResearchDeps(Settings(_env_file=None), PageLLM(by_url), tav, fetch, repo, run, budget,
                        asyncio.Event()), tav


ONEMG = "https://www.1mg.com/otc/dispovan-syringe-2ml"
TEXT = "Dispovan 2 ml Syringe. Pack of 10. MRP ₹200 ₹150 (25% off). Inclusive of all taxes."


async def test_verified_row_with_per_unit_price(repo):
    deps, tav = deps_for(repo, {ONEMG: TEXT}, {ONEMG: [listing()]})
    res = await run_retail(deps, RSPEC)
    (row,) = res.rows
    assert (row.retailer, row.url, row.title) == ("Tata 1mg", ONEMG, "Dispovan 2 ml Syringe")
    assert row.pack_size == 10 and row.pack_price == Decimal("150") and row.unit_price == Decimal("15.00")
    assert res.queries == [Q1, Q2]
    assert tav.queries == [Q1, Q2]


def test_mrp_quote_rejected_selling_price_kept():
    def got(price):
        return [r.pack_price for r in _rows([listing(price=price)], ONEMG, TEXT, RSPEC)]
    assert got("MRP ₹200 ₹150") == []  # a quote naming the MRP is never the price
    assert got("₹200") == []  # bare struck MRP: preceded by MRP, a lower amount follows
    assert got("₹150") == [Decimal("150")]
    dotted = "Dispovan 2 ml Syringe. Pack of 10. M.R.P. ₹200 ₹150 (25% off)."
    assert [r.pack_price for r in _rows([listing(price="₹200")], ONEMG, dotted, RSPEC)] == []
    assert [r.pack_price for r in _rows([listing(price="M.R.P. ₹200")], ONEMG, dotted, RSPEC)] == []
    assert [r.pack_price for r in _rows([listing(price="₹150")], ONEMG, dotted, RSPEC)] == [Decimal("150")]


TWO = "Romsons 2 ml Syringe Pack of 10 ₹150 Dispovan 2 ml Syringe Pack of 100 ₹1,450"
A = dict(title="Romsons 2 ml Syringe")
B = listing(title="Dispovan 2 ml Syringe", price="₹1,450", pack="Pack of 100")


def test_two_listing_page_values_stay_with_their_own_listing():
    def units(a):
        return {r.title: r.unit_price for r in _rows([a, B], ONEMG, TWO, RSPEC)}
    both = units(listing(**A, price="₹150", pack="Pack of 10"))
    assert both == {"Romsons 2 ml Syringe": Decimal("15.00"), "Dispovan 2 ml Syringe": Decimal("14.50")}
    assert units(listing(**A, price="₹1,450", pack="Pack of 10")) == {"Dispovan 2 ml Syringe": Decimal("14.50")}
    assert units(listing(**A, price="₹150", pack="Pack of 100")) == {"Dispovan 2 ml Syringe": Decimal("14.50")}


def test_title_inside_another_title_does_not_take_its_values():
    page = "Syringe 2 ml Pack of 10 ₹150 Romsons Syringe 2 ml Pack of 100 ₹1,450"
    other = listing(title="Romsons Syringe 2 ml", price="₹1,450", pack="Pack of 100")

    def units(a, b=other):
        return {r.title: r.unit_price for r in _rows([a, b], ONEMG, page, RSPEC)}
    short = {"title": "Syringe 2 ml"}
    assert units(listing(**short, price="₹150", pack="Pack of 10")) == {
        "Syringe 2 ml": Decimal("15.00"), "Romsons Syringe 2 ml": Decimal("14.50")}
    assert units(listing(**short, price="₹1,450", pack="Pack of 10")) == {"Romsons Syringe 2 ml": Decimal("14.50")}
    assert units(listing(**short, price="₹150", pack="Pack of 100")) == {"Romsons Syringe 2 ml": Decimal("14.50")}
    # "Pack of 10" inside "Pack of 100" is not the longer listing's pack
    assert units(listing(**short, price="₹150", pack="Pack of 10"),
                 listing(title="Romsons Syringe 2 ml", price="₹1,450", pack="Pack of 10")) == {
        "Syringe 2 ml": Decimal("15.00")}
    page2 = "Dispovan Syringe 2 ml Pack of 10 ₹150 Dispovan Syringe 2 ml Sterile Pack of 100 ₹1,450"
    rows = _rows([listing(title="Dispovan Syringe 2 ml", price="₹1,450", pack="Pack of 100"),
                  listing(title="Dispovan Syringe 2 ml Sterile", price="₹1,450", pack="Pack of 100")],
                 ONEMG, page2, RSPEC)
    assert [r.title for r in rows] == ["Dispovan Syringe 2 ml Sterile"]


def test_price_is_the_first_amount_after_the_title_r54():
    page = "Dispovan 2 ml Syringe 1 Unit MRP ₹12 ₹9 BD Emerald 5 ml Syringe Pack of 100 ₹1,450"
    title = "Dispovan 2 ml Syringe"

    def rows(price, pack):
        return [(r.pack_price, r.pack_size) for r in _rows([listing(title=title, price=price, pack=pack)],
                                                            ONEMG, page, RSPEC)]
    assert rows("₹9", "1 Unit") == [(Decimal("9"), 1)]  # the struck MRP ₹12 before it is skipped
    assert rows("₹1,450", "Pack of 100") == []
    assert rows("₹1,450", "1 Unit") == []
    assert rows("₹9", "Pack of 100") == []  # pack after another product's title, not next to the price


def test_pack_right_after_the_price_counts_r54():
    page = "Syringe 2 ml ₹150 / Pack of 10 Romsons Syringe 2 ml Pack of 100 ₹1,450"
    rows = _rows([listing(title="Syringe 2 ml", price="₹150", pack="Pack of 10")], ONEMG, page, RSPEC)
    assert [(r.unit_price, r.pack_size) for r in rows] == [(Decimal("15.00"), 10)]
    assert _rows([listing(title="Syringe 2 ml", price="₹150", pack="Pack of 100")], ONEMG, page, RSPEC) == []


def test_single_listing_price_must_follow_its_own_title():
    page = "Dispovan 2 ml Syringe ₹1,450 Romsons 2 ml Syringe Pack of 10"
    assert _rows([listing(title="Romsons 2 ml Syringe", price="₹1,450")], ONEMG, page, RSPEC) == []
    assert _rows([listing(title="Romsons 2 ml Syringe", price="₹150")], ONEMG, page + " ₹150", RSPEC)


async def test_unverified_quotes_and_bad_rows_are_dropped(repo):
    bad = [
        listing(price="₹99"),  # price not on the page
        listing(title="Dispovan 2 ml Syringe Super"),  # title not on the page
        listing(title="Dispovan 5 ml Syringe", price="₹180"),  # wrong variant
        listing(title="Dispovan 2 ml Needle", price="₹120"),  # wrong product type
        listing(price="$3", currency="other"),  # not INR
        listing(pack=None, title="Romsons 2 ml Syringe", price="₹40"),  # pack size unknown
    ]
    text = TEXT + " Dispovan 5 ml Syringe ₹180. Dispovan 2 ml Needle ₹120. $3. Romsons 2 ml Syringe ₹40."
    deps, _ = deps_for(repo, {ONEMG: text}, {ONEMG: bad})
    res = await run_retail(deps, RSPEC)
    assert res.rows == []


async def test_unstated_primary_dropped_secondary_allowed(repo):
    spec = RSPEC.model_copy(update={"attributes": {"capacity": "2 mL", "brand": "dispovan"},
                                    "must_match": ["capacity", "brand"]})
    text = "Syringe for injection. Pack of 10 ₹90. Romsons 2 ml Syringe. Pack of 5 ₹60."
    rows = [listing(title="Syringe for injection", price="₹90"),
            listing(title="Romsons 2 ml Syringe", price="₹60", pack="Pack of 5")]
    deps, _ = deps_for(repo, {ONEMG: text}, {ONEMG: rows})
    (row,) = (await run_retail(deps, spec)).rows
    assert row.title == "Romsons 2 ml Syringe" and row.unit_price == Decimal("12.00")


async def test_one_row_per_retailer_cheapest_max_five_sorted(repo):
    pages, by_url = {}, {}
    for i, dom in enumerate(RETAILERS):
        price = 100 + 10 * i
        for k, extra in enumerate((0, 5)):  # two listings per retailer: the cheaper one wins
            url = f"https://www.{dom}/p/{k}"
            pages[url] = f"Dispovan 2 ml Syringe Pack of 10 ₹{price + extra}"
            by_url[url] = [listing(price=f"₹{price + extra}")]
    deps, _ = deps_for(repo, pages, by_url, limits={"retail_search": 4, "retail_pages": 20, "retail_llm": 20})
    res = await run_retail(deps, RSPEC)
    assert len(res.rows) == 5
    assert [r.unit_price for r in res.rows] == [Decimal(x) for x in ("10.00", "11.00", "12.00", "13.00", "14.00")]
    assert len({r.retailer for r in res.rows}) == 5


async def test_non_retail_hits_ignored_and_search_limited_to_retail_domains(repo):
    other = "https://www.indiamart.com/proddetail/syringe.html"
    deps, tav = deps_for(repo, {other: TEXT}, {other: [listing()]})
    res = await run_retail(deps, RSPEC)
    assert res.rows == [] and deps.fetcher.urls == []


async def test_budget_exhaustion_is_a_retail_note(repo):
    deps, _ = deps_for(repo, {ONEMG: TEXT}, {ONEMG: [listing()]},
                       limits={"retail_search": 4, "retail_pages": 0, "retail_llm": 8})
    res = await run_retail(deps, RSPEC)
    assert res.rows == [] and any(n.startswith("Retail:") for n in res.notes)


# ---- service ---------------------------------------------------------------------------------

def _res(spec):
    return ItemResult(spec_title=spec.title, quantity=spec.quantity, notes=["ok"])


async def test_retail_runs_concurrently_and_is_stored_apart(repo):
    both = asyncio.Event()
    started = []

    async def research(deps, spec, mode):
        started.append("research")
        await asyncio.wait_for(both.wait(), 1)  # only finishes if retail started meanwhile
        return _res(spec)

    async def retail(deps, spec):
        started.append("retail")
        both.set()
        return RetailResult(rows=[], notes=["x"], queries=["q"])

    rid, (iid,) = seed(repo, mk_item("Syringe"))
    svc = service(repo, research)
    svc.retail_fn = retail
    await svc.start(rid)
    await finish(svc)
    run = repo.runs_for_item(iid)[0]
    assert run["status"] == "done" and set(started) == {"research", "retail"}
    assert run["result"]["notes"] == ["ok"] and "retail" not in run["result"]
    assert run["retail"] == {"rows": [], "notes": ["x"], "queries": ["q"]}


async def test_retail_failure_never_fails_or_changes_the_item(repo):
    async def research(deps, spec, mode):
        return _res(spec)

    async def retail(deps, spec):
        raise RuntimeError("retail exploded")

    rid, (iid,) = seed(repo, mk_item("Syringe"))
    svc = service(repo, research)
    svc.retail_fn = retail
    await svc.start(rid)
    await finish(svc)
    run = repo.runs_for_item(iid)[0]
    assert run["status"] == "done" and run["result"]["notes"] == ["ok"]
    assert run["retail"]["rows"] == [] and run["retail"]["notes"][0].startswith("Retail:")


def _slow_retail(log):
    async def retail(deps, spec):
        log.append("start")
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            log.append("cancelled")
            raise
        return RetailResult(notes=["late"])
    return retail


async def _settle(cond):
    for _ in range(200):
        if cond():
            return
        await asyncio.sleep(0.005)


async def test_research_failure_or_cancel_cancels_retail_and_writes_nothing(repo):
    for exc in (AppError("boom"), Cancelled()):
        log = []

        async def research(deps, spec, mode, exc=exc):
            await asyncio.sleep(0.02)
            raise exc

        rid, (iid,) = seed(repo, mk_item("Syringe"))
        svc = service(repo, research)
        svc.retail_fn = _slow_retail(log)
        await svc.start(rid)
        await finish(svc)
        await _settle(lambda log=log: "cancelled" in log)
        run = repo.runs_for_item(iid)[0]
        assert log == ["start", "cancelled"] and run["retail"] is None
        assert run["status"] in ("failed", "cancelled")


async def test_retail_timeout_is_stored_as_lookup_failed(repo):
    async def research(deps, spec, mode):
        return _res(spec)

    rid, (iid,) = seed(repo, mk_item("Syringe"))
    svc = service(repo, research, grace=0.05, item_timeout_seconds=0)
    svc.retail_fn = _slow_retail([])
    await svc.start(rid)
    await finish(svc)
    run = repo.runs_for_item(iid)[0]
    assert run["status"] == "done" and run["retail"]["notes"] == ["Retail: lookup failed"]


async def test_cancel_inside_retail_stops_leftover_pages(repo):
    pages = {f"https://www.{d}/p": TEXT for d in RETAILERS}
    deps, _ = deps_for(repo, pages, {u: [listing()] for u in pages})
    slow, started, done = deps.fetcher.fetch, [], []

    async def fetch(url):
        started.append(url)
        await asyncio.sleep(0.05 if "1mg" not in url else 0)
        if "1mg" in url:
            deps.cancel.set()  # the first page to arrive sees the cancel; no page is extracted
        done.append(url)
        return await slow(url)

    deps.fetcher.fetch = fetch
    try:
        await run_retail(deps, RSPEC)
        raise AssertionError("expected Cancelled")
    except Cancelled:
        pass
    assert deps.llm.calls == 0 and len(started) == len(pages)
    assert sorted(done) == sorted(started)  # no page task left running after the lookup stopped


async def test_part_mode_skips_retail(repo):
    calls = []

    async def retail(deps, spec):
        calls.append(spec.name)
        return RetailResult()

    svc, iid = await done_item(repo, make_fn({"Barrel": "1"}))
    svc.retail_fn = retail
    await svc.split(iid)
    await finish_split(repo, iid)
    assert calls == []


def test_migration_adds_retail_column(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, database_url=f"sqlite:///{tmp_path / 'm.db'}")
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    command.upgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "head")
    cols = {c["name"] for c in inspect(Database(settings.database_url).engine).get_columns("item_run")}
    assert "retail" in cols
    command.downgrade(Config(str(Path(__file__).parents[1] / "alembic.ini")), "0001")
    cols = {c["name"] for c in inspect(Database(settings.database_url).engine).get_columns("item_run")}
    assert "retail" not in cols
