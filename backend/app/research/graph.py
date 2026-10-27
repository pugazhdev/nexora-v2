"""Research graph (spec 6.3). Item mode runs the offer branch, then the cost branch (so the cost estimate
sees the market prices), then check_sanity; part mode runs the offer branch only."""
from typing import Literal

from langgraph.graph import END, START, StateGraph

from app.research import nodes
from app.research.deps import ResearchDeps
from app.research.schemas import ItemResult, ResearchSpec
from app.research.state import ResearchState

_DISCOVER = ["tavily_search", "web_search", "merge_candidates"]


def build_research_graph(mode: Literal["item", "part"]):
    g = StateGraph(ResearchState)
    g.add_node("plan_research", nodes.plan_research)
    g.add_node("tavily_search", nodes.tavily_search)
    g.add_node("web_search", nodes.web_search)
    g.add_node("merge_candidates", nodes.merge_candidates)
    g.add_node("fetch_extract", nodes.fetch_extract)
    g.add_node("build_offers", nodes.build_offers)
    g.add_node("broaden_queries", nodes.broaden_queries)
    g.add_node("offers_done", nodes.offers_done)
    g.add_node("finalise", nodes.finalise)
    g.add_edge(START, "plan_research")
    g.add_conditional_edges("plan_research", nodes.route_discover, _DISCOVER)
    g.add_edge("tavily_search", "merge_candidates")
    g.add_edge("web_search", "merge_candidates")
    g.add_conditional_edges("merge_candidates", nodes.route_fetch, ["fetch_extract", "build_offers"])
    g.add_edge("fetch_extract", "build_offers")
    g.add_conditional_edges("build_offers", nodes.route_after_offers, ["broaden_queries", "offers_done"])
    g.add_conditional_edges("broaden_queries", nodes.route_discover, _DISCOVER)
    if mode == "item":
        g.add_node("refine_cost_plan", nodes.refine_cost_plan)
        g.add_node("price_material", nodes.price_material)
        g.add_node("compute_cost_node", nodes.compute_cost_node)
        g.add_node("check_sanity", nodes.check_sanity)
        g.add_edge("offers_done", "refine_cost_plan")
        g.add_conditional_edges("refine_cost_plan", nodes.route_materials, ["price_material", "compute_cost_node"])
        # every price_material send of one step converges on a single compute_cost run
        g.add_edge("price_material", "compute_cost_node")
        g.add_edge("compute_cost_node", "check_sanity")
        g.add_edge("check_sanity", "finalise")
    else:
        g.add_edge("offers_done", "finalise")
    g.add_edge("finalise", END)
    return g.compile()


async def run_research(deps: ResearchDeps, spec: ResearchSpec, mode: Literal["item", "part"]) -> ItemResult:
    out = await build_research_graph(mode).ainvoke(
        {"mode": mode, "spec": spec, "retries_left": deps.settings.broaden_retries},
        config={"configurable": {"deps": deps}},
    )
    return out["result"]
