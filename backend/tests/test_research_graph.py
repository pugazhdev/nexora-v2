"""Research graph (offer branch) end to end with fakes, plus finalise unit tests."""
import asyncio
from decimal import Decimal

import pytest

from app.clients.errors import (
    LLMAuthError,
    LLMBadResponseError,
    LLMQuotaError,
    SearchTemporaryError,
)
from app.clients.tavily import SearchHit
from app.config import Settings
from app.errors import AppError
from app.fetch.pages import Page
from app.research import nodes
from app.research.budget import Budget
from app.research.cost import compute_cost
from app.research.deps import Cancelled, ResearchDeps
from app.research.graph import run_research
from app.research.prices import gst_rate
from app.research.schemas import (
    BomLine,
    CostPlanRefinement,
    ListingRef,
    MaterialPrice,
    MaterialPriceExtraction,
    Offer,
    PageExtraction,
    PageOffers,
    ProcessLine,
    RefinedBomLine,
    RefinedProcessLine,
    ResearchPlan,
    ResearchSpec,
    Tier,
    WebSearchListings,
)
from tests.fakes import FakeFetcher, FakeLLM, FakeTavily
from tests.helpers import ITEM, seeded_item
from tests.helpers import SPEC as RUN_SPEC
from tests.test_nodes_offers import build, offer

SPEC = ResearchSpec(name="Disposable syringe", attributes={"capacity": "2 mL"}, quantity=5000,
                    title="Disposable syringe, 2 mL", must_match=["capacity"])
URL = "https://acme.in/syringe"
TEXT = ("Acme Syringes Pvt Ltd, Ahmedabad. Business Type: Manufacturer. 2 ml disposable syringe. "
        "Price: Rs 2.24 per piece (inclusive of 12% GST).")
GOOD = dict(seller_name="Acme Syringes Pvt Ltd", seller_city="Ahmedabad",
            seller_type_quote="Business Type: Manufacturer", product_title="2 ml disposable syringe",
            attributes=[], price_quote="Rs 2.24 per piece", price_basis_quote="per piece",
            gst_quote="inclusive of 12% GST", moq_quote=None, moq_value=None)


def plan(queries=("q1",), prompts=()):
    return ResearchPlan(queries=list(queries), web_prompts=list(prompts), hsn_code=None,
                        bill_of_materials=[], process=[], type_terms=[])


def setup(repo, llm, tavily=None, limits=None, **settings):
    run = repo.create_run(seeded_item(repo, [ITEM]), {}, RUN_SPEC)
    budget = Budget({"cost_search": 6, "cost_pages": 8, "cost_llm": 8} | (limits or {"tavily": 12, "web": 2, "pages": 30, "llm": 30}), 180)
    tav = tavily or FakeTavily({"q1": [SearchHit(URL, "Acme", "s")]})
    deps = ResearchDeps(Settings(_env_file=None, **settings), llm, tav,
                        FakeFetcher({URL: Page(URL, TEXT, "direct")}), repo, run, budget, asyncio.Event())
    return deps, run


async def test_happy_path_returns_offers_with_links(repo):
    llm = FakeLLM({ResearchPlan: [plan()], PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm)
    res = await run_research(deps, SPEC, "item")
    (o,) = res.offers
    assert o.url == URL and o.classification == "manufacturer" and o.tiers[0].unit_price == Decimal("2.00")
    assert res.queries == ["q1"] and res.notes == [] and res.cost is None
    assert res.gst and res.gst.rate_pct == Decimal(12) and res.gst.source_url == URL


async def test_no_offers_broadens_then_returns_empty_with_queries(repo):
    llm = FakeLLM({ResearchPlan: [plan(), plan(["q2"])], PageExtraction: [PageExtraction(offers=[])]})
    deps, _ = setup(repo, llm)
    res = await run_research(deps, SPEC, "item")
    assert res.offers == [] and res.queries == ["q1", "q2"] and res.gst is None
    assert len(llm.calls) == 3


async def test_one_source_down_still_completes(repo):
    llm = FakeLLM({ResearchPlan: [plan(prompts=["p1"])], PageExtraction: [PageExtraction(offers=[offer(**GOOD)])],
                   WebSearchListings: [LLMBadResponseError("no cited sources")]})
    deps, _ = setup(repo, llm)
    res = await run_research(deps, SPEC, "item")
    assert len(res.offers) == 1 and res.notes == ["OpenAI web search unavailable, continuing"]


async def test_web_search_candidates_are_fetched(repo):
    llm = FakeLLM({ResearchPlan: [plan(queries=[], prompts=["p1"])],
                   WebSearchListings: [WebSearchListings(listings=[ListingRef(url=URL, title="Acme")])],
                   PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm, FakeTavily({}))
    assert len((await run_research(deps, SPEC, "item")).offers) == 1


async def test_tavily_not_configured_runs_on_web_search_only(repo):
    tav = FakeTavily({"q1": [SearchHit("https://other.in/x", "Other", "s")]})
    tav.is_configured = lambda: False
    llm = FakeLLM({ResearchPlan: [plan(prompts=["p1"])],
                   WebSearchListings: [WebSearchListings(listings=[ListingRef(url=URL, title="Acme")])],
                   PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm, tav)
    res = await run_research(deps, SPEC, "item")
    assert tav.queries == [] and [o.url for o in res.offers] == [URL]


async def test_both_search_sources_down_fails_with_provider_message(repo):
    """G2: every search call failed and no offer was built, so the run fails (Retry) with the provider's message."""
    class DownTavily(FakeTavily):
        async def search(self, query, **kw):
            raise SearchTemporaryError("Tavily search is temporarily unavailable.")

    llm = FakeLLM({ResearchPlan: [plan(prompts=["p1"])],
                   WebSearchListings: [LLMBadResponseError("down")]})
    deps, _ = setup(repo, llm, DownTavily({}), broaden_retries=0)
    with pytest.raises(AppError) as err:
        await run_research(deps, SPEC, "item")
    assert err.value.message == "Tavily search is temporarily unavailable."


async def test_llm_quota_mid_research_fails_with_quota_message(repo):
    """G3: search worked but the extraction hit the OpenAI quota; no offer was built, so the run fails."""
    quota = LLMQuotaError("OpenAI quota exceeded. Add credit and retry.")
    llm = FakeLLM({ResearchPlan: [plan()], PageExtraction: [quota, quota]})
    deps, _ = setup(repo, llm, broaden_retries=0)
    with pytest.raises(AppError) as err:
        await run_research(deps, SPEC, "item")
    assert err.value.message == "OpenAI quota exceeded. Add credit and retry."


async def test_llm_auth_error_with_offers_still_finishes(repo):
    """G3: a hard provider error only fails the run when no offer was built."""
    llm = FakeLLM({ResearchPlan: [plan(prompts=["p1"])],
                   WebSearchListings: [LLMAuthError("OpenAI rejected the configured API key.")],
                   PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm)
    res = await run_research(deps, SPEC, "item")
    assert len(res.offers) == 1


async def test_tavily_not_configured_writes_estimate_note(repo):
    """G1: without Tavily the run says search is OpenAI-only and material costs are estimates."""
    tav = FakeTavily({})
    tav.is_configured = lambda: False
    llm = FakeLLM({ResearchPlan: [plan(prompts=["p1"])],
                   WebSearchListings: [WebSearchListings(listings=[ListingRef(url=URL, title="Acme")])],
                   PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm, tav)
    res = await run_research(deps, SPEC, "item")
    assert "Search is using OpenAI web search only; material costs are estimates." in res.notes


async def test_budget_exhausted_finishes_with_note(repo):
    llm = FakeLLM({ResearchPlan: [plan()]})
    deps, _ = setup(repo, llm, limits={"tavily": 12, "web": 2, "pages": 0, "llm": 30}, broaden_retries=0)
    res = await run_research(deps, SPEC, "item")
    assert res.offers == [] and res.notes == ["Stopped early: page budget reached"]


async def test_cancel_raises_cancelled(repo):
    deps, _ = setup(repo, FakeLLM({ResearchPlan: [plan()]}))
    deps.cancel.set()
    with pytest.raises(Cancelled):
        await run_research(deps, SPEC, "item")


async def test_manufacturers_persisted(repo):
    llm = FakeLLM({ResearchPlan: [plan()], PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm)
    await run_research(deps, SPEC, "item")
    (m,) = repo.list_manufacturers()
    assert m["normalised_name"] == "acme syringes" and m["city"] == "Ahmedabad"


# ---- finalise ----------------------------------------------------------------------------------

def mk(id, cls="manufacturer", tiers=((1, "5"),), gst=None, url="https://x.in/a"):
    return Offer(id=id, manufacturer=f"Maker {id}", city="Pune", state=None, platform="Maker site", url=url,
                 classification=cls, tiers=[Tier(min_qty=q, unit_price=Decimal(p)) for q, p in tiers], moq=None,
                 in_range=True, flags=[], extra_links=[], price_quote="q", spec_match="match", observed_at=None,
                 gst_rate_pct=None if gst is None else Decimal(gst))


async def fin(repo, offers, **state):
    deps, _ = setup(repo, FakeLLM({}))
    out = await nodes.finalise({"spec": SPEC, "offers": offers, **state}, {"configurable": {"deps": deps}})
    return out["result"]


async def test_finalise_sorts_by_price_at_quantity_and_persists_non_excluded(repo):
    offers = [mk("c", tiers=((10000, "1"),)), mk("b", tiers=((1, "4"), (1000, "3"))), mk("a", tiers=((1, "4"),)),
              mk("t", cls="excluded", tiers=((1, "1"),))]
    res = await fin(repo, offers)
    assert [o.id for o in res.offers] == ["t", "b", "a", "c"]
    assert sorted(m["display_name"] for m in repo.list_manufacturers()) == ["Maker a", "Maker b", "Maker c"]


async def test_finalise_notes_and_queries_deduped(repo):
    deps, _ = setup(repo, FakeLLM({}))
    deps.budget.exhausted.update({"pages", "llm"})
    out = await nodes.finalise({"spec": SPEC, "offers": [], "queries_used": ["a", "b", "a"],
                                "notes": ["x", "Stopped early: page budget reached", "x"]},
                               {"configurable": {"deps": deps}})
    r = out["result"]
    assert r.queries == ["a", "b"]
    assert r.notes == ["x", "Stopped early: page budget reached", "Stopped early: AI extraction budget reached"]


async def test_finalise_gst_most_common_tie_lowest(repo):
    res = await fin(repo, [mk("a", gst="12", url="u1"), mk("b", gst="18", url="u2"), mk("c", gst="18", url="u3")])
    assert (res.gst.rate_pct, res.gst.source_url) == (Decimal(18), "u2")
    res = await fin(repo, [mk("a", gst="18", url="u1"), mk("b", gst="12", url="u2")])
    assert res.gst.rate_pct == Decimal(12)
    assert (await fin(repo, [mk("a")])).gst is None


def test_gst_rate_only_valid_slabs():
    assert gst_rate("inclusive of 12% GST") == Decimal(12)
    assert gst_rate("GST @ 18%") == Decimal(18)
    assert gst_rate("GST 13%") is None and gst_rate("Inclusive of GST") is None and gst_rate(None) is None


async def test_build_offers_records_gst_rate():
    offers, _ = await build([PageOffers(url=URL, page_text=TEXT, offers=[offer(**GOOD)])])
    assert offers[0].gst_rate_pct == Decimal(12)


async def test_plan_type_terms_gate_offers(repo):
    wrong = plan().model_copy(update={"type_terms": ["needle"]})
    llm = FakeLLM({ResearchPlan: [wrong, wrong], PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm)
    res = await run_research(deps, SPEC, "item")
    assert res.offers == []  # "2 ml disposable syringe" is not a needle listing


# ---- cost branch (Task 20) ---------------------------------------------------------------------

MURL = "https://plastics.example/pp-price"
MTEXT = "Polypropylene homopolymer granules. Today: Rs 110 per kg, ex-Mumbai."
BOM = [BomLine(component="barrel", material="PP", mass_g=3.1, basis="weighed", estimate_inr=0.4),
       BomLine(component="needle", material="SS 304", mass_g=0.2, basis="guess", estimate_inr=0.3)]
PROC = [ProcessLine(step="moulding", basis="machine rate", estimate_inr=0.2)]


def cost_plan():
    return plan().model_copy(update={"bill_of_materials": BOM, "process": PROC})


def refinement(scale=1.0):
    return CostPlanRefinement(
        bill_of_materials=[RefinedBomLine(component=b.component, mass_g=b.mass_g, estimate_inr=b.estimate_inr * scale)
                           for b in BOM],
        process=[RefinedProcessLine(step=p.step, estimate_inr=p.estimate_inr * scale) for p in PROC])


def cost_setup(repo, extraction, refined=None):
    llm = FakeLLM({ResearchPlan: [cost_plan()], PageExtraction: [PageExtraction(offers=[offer(**GOOD)])],
                   MaterialPriceExtraction: [extraction], CostPlanRefinement: [refined or refinement()]})
    tav = FakeTavily({"q1": [SearchHit(URL, "Acme", "s")], "PP price per kg India": [SearchHit(MURL, "PP", "s")]})
    deps, _ = setup(repo, llm, tav)
    deps.fetcher.pages[MURL] = Page(MURL, MTEXT, "direct")
    return deps, llm, tav


async def test_item_graph_runs_cost_branch_after_offers(repo, monkeypatch):
    runs = []
    real = nodes.compute_cost_node

    async def counted(state, config):
        runs.append(1)
        return await real(state, config)

    monkeypatch.setattr(nodes, "compute_cost_node", counted)
    deps, llm, tav = cost_setup(repo, MaterialPriceExtraction(quote="Rs 110 per kg", inr_per_kg=110))
    res = await run_research(deps, SPEC, "item")
    assert len(res.offers) == 1 and res.offers[0].url == URL
    assert runs == [1]  # two price_material sends converge on one compute_cost run
    schemas = [c[0] for c in llm.calls]
    # the cost branch starts after the offers are built, and the refine call sees the market lowest
    assert schemas.index(PageExtraction) < schemas.index(CostPlanRefinement) < schemas.index(MaterialPriceExtraction)
    assert "Market: lowest Rs 2.00 per piece, highest Rs 2.00 per piece" in llm.calls[schemas.index(CostPlanRefinement)][2]
    assert tav.queries[0] == "q1"
    assert set(tav.queries) == {"q1", "PP price per kg India", "SS 304 price per kg India"}  # R32: no process search
    barrel, needle, moulding, overhead = res.cost.lines
    assert (barrel.label, barrel.amount, barrel.estimated, barrel.source_ids) == ("barrel", Decimal("0.34"), False, [1])
    assert barrel.quote == "Rs 110 per kg" and needle.quote is None and moulding.quote is None  # R34
    assert needle.estimated and moulding.estimated and moulding.amount == Decimal("0.20")
    assert res.cost.sources[0].url == MURL and res.cost.confidence == "low"


async def test_material_price_without_quote_is_estimate(repo):
    deps, _, _ = cost_setup(repo, MaterialPriceExtraction(quote=None, inr_per_kg=110))
    res = await run_research(deps, SPEC, "item")
    assert res.cost.lines[0].estimated and res.cost.lines[0].amount == Decimal("0.40") and res.cost.sources == []


async def test_material_price_number_must_come_from_quote(repo):
    # quote is on the page but the number is not the one in it: no price
    deps, _, _ = cost_setup(repo, MaterialPriceExtraction(quote="Rs 110 per kg", inr_per_kg=95))
    assert (await run_research(deps, SPEC, "item")).cost.lines[0].estimated


async def test_part_mode_has_no_cost(repo):
    deps, llm, tav = cost_setup(repo, MaterialPriceExtraction(quote="Rs 110 per kg", inr_per_kg=110))
    res = await run_research(deps, SPEC, "part")
    assert res.cost is None and len(res.offers) == 1
    assert tav.queries == ["q1"] and {MaterialPriceExtraction, CostPlanRefinement}.isdisjoint(c[0] for c in llm.calls)


async def test_item_without_bom_still_joins(repo):
    llm = FakeLLM({ResearchPlan: [plan()], PageExtraction: [PageExtraction(offers=[offer(**GOOD)])]})
    deps, _ = setup(repo, llm)
    res = await run_research(deps, SPEC, "item")
    assert res.cost is None and len(res.offers) == 1


async def test_check_sanity_flags_offer_against_cost(repo):
    deps, _ = setup(repo, FakeLLM({}))
    cost = compute_cost(BOM[:1], [], [], {"barrel": Decimal("5")}, overhead_pct=Decimal(10), mass_pct=Decimal(15))
    out = await nodes.check_sanity({"spec": SPEC, "offers": [mk("a", tiers=((1, "2"),))], "cost": cost},
                                   {"configurable": {"deps": deps}})
    assert out["offers"][0].flags == ["unusually_low"]


async def test_cost_branch_budget_leaves_offer_budget_untouched(repo):
    # R31: the cost branch has its own budget kinds
    deps, llm, _ = cost_setup(repo, MaterialPriceExtraction(quote="Rs 110 per kg", inr_per_kg=110))
    deps.budget.limits.update({"cost_search": 1, "cost_pages": 1, "cost_llm": 1})
    res = await run_research(deps, SPEC, "item")
    u = deps.budget.used
    assert u["cost_search"] == 1
    assert (u["tavily"], u["pages"], u["llm"]) == (1, 1, 2)  # q1, the offer page, plan + extraction only
    assert "Cost estimate: stopped early, search budget reached" in res.notes
    assert not any(n.startswith("Stopped early") for n in res.notes)


async def test_cost_above_lowest_market_price_is_low_confidence(repo):
    # R33: making cost Rs 5.50 is above the lowest in-range offer (Rs 2): rough, low confidence
    deps, _ = setup(repo, FakeLLM({}))
    pp = MaterialPrice(label="barrel", material="PP", inr_per_kg=Decimal(1000), source_url=MURL, quote="q")
    cost = compute_cost(BOM[:1], [], [pp], {}, overhead_pct=Decimal(10), mass_pct=Decimal(15))
    assert cost.confidence == "high"
    state = {"spec": SPEC, "offers": [mk("a", tiers=((1, "2"),)), mk("b", tiers=((1, "4"),))], "cost": cost}
    out = await nodes.check_sanity(state, {"configurable": {"deps": deps}})
    assert out["cost"].confidence == "low" and out["cost"].per_unit == cost.per_unit
    assert out["notes"] == ["Estimated making cost is above the lowest market price; treat it as rough."]
    out = await nodes.check_sanity({**state, "offers": [mk("a", tiers=((1, "9"),))]}, {"configurable": {"deps": deps}})
    assert "notes" not in out and "cost" not in out


async def test_cost_guard_uses_displayed_range_and_low_confidence_keeps_high_offers(repo):
    deps, _ = setup(repo, FakeLLM({}))
    pp = MaterialPrice(label="barrel", material="PP", inr_per_kg=Decimal(1000), source_url=MURL, quote="q")
    cost = compute_cost(BOM[:1], [], [pp], {}, overhead_pct=Decimal(10), mass_pct=Decimal(15))  # Rs 3.41
    cfg = {"configurable": {"deps": deps}}
    # R33b: the range uses the manufacturer (Rs 9), not the cheaper unconfirmed seller (Rs 2)
    offers = [mk("u", cls="unconfirmed", tiers=((1, "2"),)), mk("m", tiers=((1, "9"),))]
    out = await nodes.check_sanity({"spec": SPEC, "offers": offers, "cost": cost}, cfg)
    assert "notes" not in out and "cost" not in out
    # R37: cost above the range lowest (Rs 2) -> low confidence, so Rs 40 is flagged but stays in range
    offers = [mk("a", tiers=((1, "2"),)), mk("b", tiers=((1, "40"),))]
    out = await nodes.check_sanity({"spec": SPEC, "offers": offers, "cost": cost}, cfg)
    b = {o.id: o for o in out["offers"]}["b"]
    assert out["cost"].confidence == "low" and b.flags == ["unusually_high"] and b.in_range


async def test_refine_replaces_plan_estimates(repo):
    # the market says Rs 2: the refined (halved) estimates are what compute_cost uses
    deps, _, _ = cost_setup(repo, MaterialPriceExtraction(quote=None, inr_per_kg=None), refined=refinement(0.5))
    res = await run_research(deps, SPEC, "item")
    barrel, needle, moulding, _ = res.cost.lines
    assert (barrel.amount, needle.amount, moulding.amount) == (Decimal("0.20"), Decimal("0.15"), Decimal("0.10"))


async def test_refine_without_in_range_offers_says_no_market_price(repo):
    llm = FakeLLM({ResearchPlan: [cost_plan(), plan(["q2"])], PageExtraction: [PageExtraction(offers=[])],
                   CostPlanRefinement: [refinement()]})
    deps, _ = setup(repo, llm, FakeTavily({}))
    res = await run_research(deps, SPEC, "item")
    (call,) = [c for c in llm.calls if c[0] is CostPlanRefinement]
    assert "Market: no market price found" in call[2] and res.offers == [] and res.cost is not None


async def test_refine_llm_failure_keeps_original_plan_with_note(repo):
    deps, _, _ = cost_setup(repo, MaterialPriceExtraction(quote=None, inr_per_kg=None),
                            refined=LLMBadResponseError("bad"))
    res = await run_research(deps, SPEC, "item")
    assert "Cost estimate: could not check it against market prices, using the first estimate" in res.notes
    assert [ln.amount for ln in res.cost.lines[:3]] == [Decimal("0.40"), Decimal("0.30"), Decimal("0.20")]


async def refine_once(repo, refined):
    deps, _ = setup(repo, FakeLLM({CostPlanRefinement: [refined]}))
    return await nodes.refine_cost_plan({"plan": cost_plan(), "spec": SPEC, "offers": []},
                                        {"configurable": {"deps": deps}})


def _bom(*names, mass=1.0, inr=0.1):
    return [RefinedBomLine(component=n, mass_g=mass, estimate_inr=inr) for n in names]


@pytest.mark.parametrize("bom", [
    _bom("barrel", "plunger"),            # renamed
    _bom("barrel"),                       # dropped
    _bom("barrel", "needle", "needle"),   # duplicated
    _bom("barrel", "needle", inr=-0.1),   # fails the guard
    _bom("barrel", "needle", mass=0),     # fails the guard
])
async def test_refine_mismatch_keeps_whole_original_plan_with_note(repo, bom):
    proc = [RefinedProcessLine(step="moulding", estimate_inr=0.1)]
    out = await refine_once(repo, CostPlanRefinement(bill_of_materials=bom, process=proc))
    assert "plan" not in out
    assert out["notes"] == ["Cost estimate: could not check it against market prices, using the first estimate"]


async def test_refine_process_name_mismatch_keeps_original_plan(repo):
    proc = [RefinedProcessLine(step="assembly", estimate_inr=0.1)]
    out = await refine_once(repo, CostPlanRefinement(bill_of_materials=_bom("barrel", "needle"), process=proc))
    assert "plan" not in out and len(out["notes"]) == 1


async def test_refine_keeps_weighed_mass(repo):
    proc = [RefinedProcessLine(step="moulding", estimate_inr=0.1)]
    out = await refine_once(repo, CostPlanRefinement(bill_of_materials=_bom("needle", "barrel", mass=9.0, inr=0.25),
                                                     process=proc))
    barrel, needle = out["plan"].bill_of_materials  # barrel basis "weighed", needle basis "guess"
    assert (barrel.mass_g, barrel.estimate_inr) == (3.1, 0.25)
    assert (needle.mass_g, needle.estimate_inr) == (9.0, 0.25)
    assert out["plan"].process[0].estimate_inr == 0.1
