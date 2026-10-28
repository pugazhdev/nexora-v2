import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest
from langgraph.graph import END, START, StateGraph
from openai.lib._pydantic import to_strict_json_schema

from app.config import Settings
from app.research.budget import Budget
from app.research.deps import Cancelled, ResearchDeps, deps_of, emit, guard
from app.research.schemas import (
    BomLine,
    CostEstimate,
    ExtractedOffer,
    ListingRef,
    MaterialPriceExtraction,
    PageExtraction,
    ProcessLine,
    ResearchPlan,
    RetailExtraction,
    RetailListing,
    WebSearchListings,
)
from app.research.state import ResearchState
from tests.test_spec import _has_default


def test_take_until_limit():
    b = Budget({"llm": 2}, 10)
    assert b.take("llm") and b.take("llm")
    assert not b.take("llm")


def test_exhausted_records_kind():
    b = Budget({"pages": 3, "llm": 1}, 10)
    assert not b.take("pages", 4)
    assert b.exhausted == {"pages"}
    assert b.take("pages", 3)  # refusal did not consume
    with pytest.raises(ValueError):
        b.take("nope")


def test_expired_uses_clock():
    t = [0.0]
    b = Budget({}, 5, clock=lambda: t[0])
    assert not b.expired()
    t[0] = 5.0
    assert b.expired()


def test_from_settings():
    b = Budget.from_settings(Settings(), clock=lambda: 0.0)
    assert b.limits == {"tavily": 12, "web": 2, "pages": 30, "llm": 30,
                        "cost_search": 6, "cost_pages": 8, "cost_llm": 8,
                        "retail_search": 4, "retail_pages": 8, "retail_llm": 8}
    assert b.seconds == 180.0


@pytest.mark.parametrize("model", [
    ResearchPlan, BomLine, ProcessLine, WebSearchListings, ListingRef, PageExtraction, ExtractedOffer, MaterialPriceExtraction,
    RetailExtraction, RetailListing])
def test_llm_models_strict(model):
    assert not _has_default(to_strict_json_schema(model))


def test_state_reducer_fan_out():
    def a(s):
        return {"notes": ["a"]}

    def b(s):
        return {"notes": ["b"]}

    g = StateGraph(ResearchState)
    g.add_node("a", a)
    g.add_node("b", b)
    g.add_edge(START, "a")
    g.add_edge(START, "b")
    g.add_edge("a", END)
    g.add_edge("b", END)
    assert sorted(g.compile().invoke({"notes": []})["notes"]) == ["a", "b"]


def test_cost_estimate_decimal():
    c = CostEstimate(per_unit=Decimal("1.5"), low=Decimal(1), high=Decimal(2),
                     confidence="low", lines=[], sources=[])
    assert c.per_unit == Decimal("1.5")


async def test_emit_guard_deps_of():
    calls = []
    repo = SimpleNamespace(add_event=lambda *a: calls.append(a))
    cancel = asyncio.Event()
    deps = ResearchDeps(None, None, None, None, repo, "r1", Budget({}, 1), cancel)
    await emit(deps, "plan", "x" * 500)
    assert calls[0][:2] == ("r1", "plan") and len(calls[0][2]) == 300 and calls[0][3] == "info"
    guard(deps)
    cancel.set()
    with pytest.raises(Cancelled):
        guard(deps)
    assert deps_of({"configurable": {"deps": deps}}) is deps
    with pytest.raises(RuntimeError):
        deps_of({"configurable": {}})
