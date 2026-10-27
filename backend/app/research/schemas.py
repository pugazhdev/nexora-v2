"""Research contracts. ExtractedOffer goes to OpenAI strict structured output: all fields required, no defaults."""
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class ResearchSpec(BaseModel):
    name: str
    attributes: dict[str, str]
    quantity: int
    title: str
    must_match: list[str]
    type_terms: list[str] = []  # set by plan_research; empty means fall back to the name
    primary_key: str | None = None


class AttributePair(BaseModel):
    key: str
    value: str


class ExtractedTier(BaseModel):
    min_qty: int
    price_value: float
    quote: str


class ExtractedOffer(BaseModel):
    seller_name: str
    seller_city: str | None
    seller_state: str | None
    seller_type_claim: Literal["manufacturer", "trader", "distributor", "retailer", "exporter", "unknown"]
    seller_type_quote: str | None
    product_title: str
    attributes: list[AttributePair]
    price_quote: str | None
    price_value: float | None
    currency: Literal["INR", "other"]
    price_basis_quote: str | None
    tiers: list[ExtractedTier]
    moq_quote: str | None
    moq_value: float | None
    moq_unit: str | None
    gst_quote: str | None
    price_on_request: bool


def attributes_dict(pairs: list[AttributePair]) -> dict[str, str]:
    return {p.key: p.value for p in pairs}


class Tier(BaseModel):
    min_qty: int
    unit_price: Decimal


class Offer(BaseModel):
    id: str
    manufacturer: str
    city: str | None
    state: str | None
    platform: str
    url: str
    classification: Literal["manufacturer", "unconfirmed", "excluded"]
    tiers: list[Tier]
    moq: int | None
    in_range: bool
    flags: list[str]
    extra_links: list[str]
    price_quote: str
    spec_match: Literal["match", "mismatch", "unstated", "ambiguous"]
    observed_at: date | None
    gst_rate_pct: Decimal | None = None


class BomLine(BaseModel):
    component: str
    material: str
    mass_g: float
    basis: str
    estimate_inr: float  # the planner's estimate of this line's cost per finished unit, used when no price is cited


class ProcessLine(BaseModel):
    step: str
    basis: str
    estimate_inr: float


class ResearchPlan(BaseModel):
    queries: list[str]
    web_prompts: list[str]
    hsn_code: str | None
    bill_of_materials: list[BomLine]
    process: list[ProcessLine]
    type_terms: list[str]


class RefinedBomLine(BaseModel):
    component: str
    mass_g: float
    estimate_inr: float


class RefinedProcessLine(BaseModel):
    step: str
    estimate_inr: float


class CostPlanRefinement(BaseModel):
    """LLM-facing: per-piece mass and estimate of every plan line, re-estimated against market prices."""
    bill_of_materials: list[RefinedBomLine]
    process: list[RefinedProcessLine]


class ListingRef(BaseModel):
    url: str
    title: str


class WebSearchListings(BaseModel):
    listings: list[ListingRef]


class PageExtraction(BaseModel):
    offers: list[ExtractedOffer]


class MaterialPriceExtraction(BaseModel):
    """LLM-facing: one cited price for a material in INR per kg."""
    quote: str | None
    inr_per_kg: float | None


# Internal models below: Decimal and defaults allowed.
class Candidate(BaseModel):
    url: str
    title: str
    source: Literal["tavily", "web_search"]


class PageOffers(BaseModel):
    url: str
    page_text: str
    offers: list[ExtractedOffer]


class MaterialPrice(BaseModel):
    label: str
    material: str
    inr_per_kg: Decimal | None = None
    inr_per_unit: Decimal | None = None
    quote: str | None = None
    source_url: str | None = None


class CostLine(BaseModel):
    label: str
    amount: Decimal
    basis: str
    source_ids: list[int]
    estimated: bool
    quote: str | None = None  # the verified source text of a cited line


class Source(BaseModel):
    id: int
    url: str
    title: str


class CostEstimate(BaseModel):
    per_unit: Decimal
    low: Decimal
    high: Decimal
    confidence: Literal["high", "medium", "low"]
    lines: list[CostLine]
    sources: list[Source]


class GstPrefill(BaseModel):
    rate_pct: Decimal
    source_url: str


class ItemResult(BaseModel):
    spec_title: str
    quantity: int
    cost: CostEstimate | None = None
    offers: list[Offer] = []
    gst: GstPrefill | None = None
    notes: list[str] = []
    queries: list[str] = []


class PartResult(BaseModel):
    part: str
    count_per_unit: int
    offer: Offer | None
    notes: list[str] = []


class SplitResult(BaseModel):
    parts: list[PartResult]
    parts_total: Decimal | None
    finished_lowest: Decimal | None
    complete: bool
