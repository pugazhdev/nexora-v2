"""Graph state for the research LangGraph. List fields append across fan-out branches."""
import operator
from typing import Annotated, Literal, TypedDict

from app.fetch.pages import Page
from app.research.schemas import (
    Candidate,
    CostEstimate,
    ItemResult,
    MaterialPrice,
    Offer,
    PageOffers,
    ResearchPlan,
    ResearchSpec,
)


class ResearchState(TypedDict, total=False):
    mode: Literal["item", "part"]
    spec: ResearchSpec
    plan: ResearchPlan
    queries_used: Annotated[list[str], operator.add]
    candidates: Annotated[list[Candidate], operator.add]
    pages: Annotated[list[Page], operator.add]
    extracted: Annotated[list[PageOffers], operator.add]
    offers: list[Offer]
    material_prices: Annotated[list[MaterialPrice], operator.add]
    cost: CostEstimate | None
    retries_left: int
    notes: Annotated[list[str], operator.add]
    search_failures: Annotated[list[str], operator.add]  # provider message per failed search call
    searches_ok: Annotated[int, operator.add]
    provider_errors: Annotated[list[str], operator.add]  # quota / key failures (G3)
    result: ItemResult
