"""Cross-branch sanity checks on offers (spec 6.3 check_sanity, Rulings R29, R37, R40). Deterministic."""
from decimal import Decimal
from statistics import median

from app.research.schemas import CostEstimate, Offer
from app.research.tiers import price_at


def apply_sanity(offers: list[Offer], cost: CostEstimate | None, qty: int, *,
                 low_factor: Decimal, outlier_factor: Decimal) -> list[Offer]:
    units = [price_at(o.tiers, qty) for o in offers]
    in_range = [u for o, u in zip(offers, units, strict=True) if o.in_range and u is not None]
    mid = median(in_range) if len(in_range) >= 3 else None
    big = 10 * outlier_factor  # R40: an order of magnitude beyond the outlier band (a pack price per piece)
    rows = []
    for o, u in zip(offers, units, strict=True):
        flags, keep = [], o.in_range
        if u is not None:
            if cost and u < low_factor * cost.low:
                flags.append("unusually_low")  # a warning only: check the unit basis
            if cost and keep and u > outlier_factor * cost.high:
                flags.append("unusually_high")
                # R37: a rough (low confidence) cost only warns, except beyond the R40 cut
                keep = cost.confidence == "low" and u <= big * cost.high
            if mid is not None and keep and u > outlier_factor * mid:
                flags.append("outlier")
                keep = False
        rows.append([o, u, flags, keep])
    # R40 floor cut, after the median rule: far above the cheapest believable in-range price.
    # C1: needs a cost estimate, so one mis-scaled cheap price cannot remove every genuine offer
    live = [r for r in rows if r[3] and r[1] is not None]
    floor = (min((r[1] for r in live if "unusually_low" not in r[2]), default=None)
             if cost and len(live) >= 2 else None)
    for r in live:
        if floor is not None and r[1] > big * floor:
            r[2] += [] if "unusually_high" in r[2] else ["unusually_high"]
            r[3] = False
    return [o.model_copy(update={"flags": [*o.flags, *flags], "in_range": keep})
            if flags or keep != o.in_range else o for o, _, flags, keep in rows]
