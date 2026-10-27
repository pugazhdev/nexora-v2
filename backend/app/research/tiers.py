"""Tier pricing and purchase range. Mirrored in TypeScript; both run shared/calculator_cases.json."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.research.schemas import Offer, Tier


@dataclass
class RangeResult:
    lowest_id: str | None
    lowest_unit: Decimal | None
    highest_id: str | None
    highest_unit: Decimal | None
    fallback_all_moq: bool
    unconfirmed_only: bool


def price_at(tiers: list[Tier], qty: int) -> Decimal | None:
    hit = [t for t in sorted(tiers, key=lambda t: t.min_qty) if t.min_qty <= qty]
    return hit[-1].unit_price if hit else None


def purchase_range(offers: list[Offer], qty: int) -> RangeResult:
    in_range = [o for o in offers if o.in_range]
    pool = [o for o in in_range if o.classification == "manufacturer"]
    unconfirmed_only = False
    if not pool:
        pool = [o for o in in_range if o.classification == "unconfirmed"]
        unconfirmed_only = bool(pool)
    priced = [
        (o.id, p) for o in pool
        if (o.moq is None or o.moq <= qty) and (p := price_at(o.tiers, qty)) is not None
    ]
    fallback = not priced and bool(pool)
    if fallback:
        priced = [(o.id, min(o.tiers, key=lambda t: t.min_qty).unit_price) for o in pool if o.tiers]
    if not priced:
        return RangeResult(None, None, None, None, False, unconfirmed_only)
    lo = min(priced, key=lambda x: (x[1], x[0]))
    hi = min(priced, key=lambda x: (-x[1], x[0]))
    return RangeResult(lo[0], lo[1], hi[0], hi[1], fallback, unconfirmed_only)


def total(unit: Decimal, qty: int, gst_pct: Decimal, freight: Decimal) -> Decimal:
    amount = unit * qty * (1 + gst_pct / 100) + freight
    return amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
