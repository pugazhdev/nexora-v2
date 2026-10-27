"""Deterministic manufacturing cost model (no LLM, no network).

Rounding: each line's amount, low and high are rounded to 2 places ROUND_HALF_UP first.
The overhead line is computed from the sum of the rounded other lines and rounded too.
Totals (per_unit, low, high) are the plain sums of the rounded line values, so the
displayed numbers add up exactly.
"""
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.research.schemas import BomLine, CostEstimate, CostLine, MaterialPrice, ProcessLine, Source

OVERHEAD_LABEL = "Overhead and scrap"


def _r(x: Decimal) -> Decimal:
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_cost(
    bom: list[BomLine],
    process: list[ProcessLine],
    prices: list[MaterialPrice],
    estimates: dict[str, Decimal],
    *,
    overhead_pct: Decimal,
    mass_pct: Decimal,
) -> CostEstimate | None:
    if not bom and not process:
        return None
    lo_f, hi_f = 1 - mass_pct / 100, 1 + mass_pct / 100
    sources: dict[str, Source] = {}
    # (label, basis, point, low, high, urls, estimated, quote)
    rows: list[tuple[str, str, Decimal, Decimal, Decimal, list[str], bool, str | None]] = []
    all_cited = mats_cited = True
    omitted = False

    def add(label: str, basis: str, amounts: list[Decimal], urls: list[str], is_material: bool, material: str,
            quote: str | None = None):
        nonlocal all_cited, mats_cited, omitted
        if amounts:
            point, low, high = median(amounts), min(amounts), max(amounts)
            for u in urls:
                sources.setdefault(u, Source(id=len(sources) + 1, url=u, title=material or label))
            estimated = False
        elif label in estimates:
            point = low = high = estimates[label]
            urls, estimated, quote = [], True, None
        else:
            all_cited = mats_cited = False
            omitted = True
            return
        if is_material:
            low, high = low * lo_f, high * hi_f
        if estimated:
            all_cited = False
            if is_material:
                mats_cited = False
        rows.append((label, basis, point, low, high, urls, estimated, quote))

    for b in bom:
        ps = [p for p in prices if p.label == b.component and p.inr_per_kg is not None and p.source_url]
        mass = Decimal(str(b.mass_g))
        add(b.component, b.basis, [mass * p.inr_per_kg / 1000 for p in ps], [p.source_url for p in ps], True, b.material,
            ps[0].quote if ps else None)
    for s in process:
        ps = [p for p in prices if p.label == s.step and p.inr_per_unit is not None and p.source_url]
        add(s.step, s.basis, [p.inr_per_unit for p in ps], [p.source_url for p in ps], False, s.step)

    # a source's title comes from its first citing line; ids follow line order
    lines = [
        CostLine(label=lb, amount=_r(pt), basis=bs, source_ids=sorted({sources[u].id for u in us}), estimated=est,
                 quote=q)
        for lb, bs, pt, _, _, us, est, q in rows
    ]
    k = overhead_pct / 100
    rr = [(_r(r[2]), _r(r[3]), _r(r[4])) for r in rows]
    sub = [sum(x[i] for x in rr) for i in range(3)]
    oh = tuple(_r(v * k) for v in sub)
    lines.append(CostLine(
        label=OVERHEAD_LABEL, amount=oh[0], source_ids=[], estimated=True,
        basis=f"{overhead_pct.normalize():f}% of materials and process",
    ))
    per_unit, low, high = (sub[i] + oh[i] for i in range(3))
    confidence = "high" if all_cited else "medium" if mats_cited and not omitted else "low"
    return CostEstimate(per_unit=per_unit, low=low, high=high, confidence=confidence, lines=lines,
                        sources=list(sources.values()))
