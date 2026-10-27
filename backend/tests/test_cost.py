from decimal import Decimal as D

from app.research.cost import compute_cost
from app.research.schemas import BomLine, MaterialPrice, ProcessLine

BOM = [BomLine(component="barrel", material="PP", mass_g=3.1, basis="weighed", estimate_inr=0)]
PROC = [ProcessLine(step="moulding", basis="machine rate", estimate_inr=0)]


def kg(label, price, url="https://a.example/pp"):
    return MaterialPrice(label=label, material="PP", inr_per_kg=D(price), source_url=url, quote="q")


def unit(label, price, url="https://b.example/mould"):
    return MaterialPrice(label=label, material="mould", inr_per_unit=D(price), source_url=url, quote="q")


def run(bom=BOM, proc=PROC, prices=(), est=None):
    return compute_cost(bom, proc, list(prices), est or {}, overhead_pct=D(10), mass_pct=D(15))


def test_material_line():
    c = run(proc=[], prices=[kg("barrel", "110")])
    assert c.lines[0].amount == D("0.34")
    assert c.lines[0].source_ids == [1] and not c.lines[0].estimated


def test_overhead_line_added():
    c = run(proc=[], prices=[kg("barrel", "1000")])
    assert c.lines[-1].label == "Overhead and scrap"
    assert c.lines[0].amount == D("3.10") and c.lines[-1].amount == D("0.31")
    assert c.per_unit == D("3.41")


def test_confidence_levels():
    both = [kg("barrel", "110"), unit("moulding", "1")]
    assert run(prices=both).confidence == "high"
    assert run(prices=both[:1], est={"moulding": D("1")}).confidence == "medium"
    assert run(prices=both[1:], est={"barrel": D("1")}).confidence == "low"
    assert run(prices=both[:1]).confidence == "low"  # process line omitted


def test_range_applies_mass_uncertainty():
    c = run(proc=[], prices=[kg("barrel", "1000")])
    assert (c.low, c.high) == (D("2.90"), D("3.93"))


def test_several_sources_use_min_max_median():
    c = run(proc=[], prices=[kg("barrel", "1000", "u1"), kg("barrel", "2000", "u2"), kg("barrel", "3000", "u3")])
    assert c.lines[0].amount == D("6.20") and c.lines[0].source_ids == [1, 2, 3]
    assert c.low == D("2.90") and c.high == D("11.77")


def test_uncited_line_marked_estimated():
    c = run(prices=[kg("barrel", "110")], est={"moulding": D("0.5")})
    m = c.lines[1]
    assert m.estimated and m.source_ids == [] and m.amount == D("0.50")
    assert c.lines[0].estimated is False


def test_process_estimate_has_no_invented_range():
    c = run(bom=[], est={"moulding": D("1")})
    assert (c.per_unit, c.low, c.high) == (D("1.10"), D("1.10"), D("1.10"))


def test_sources_deduped_and_numbered():
    bom = BOM + [BomLine(component="plunger", material="PP", mass_g=1, basis="x", estimate_inr=0)]
    c = run(bom=bom, proc=PROC, prices=[kg("barrel", "110"), kg("plunger", "110"), unit("moulding", "1", "https://c.example/x")])
    assert [s.id for s in c.sources] == [1, 2]
    assert c.lines[0].source_ids == [1] and c.lines[1].source_ids == [1] and c.lines[2].source_ids == [2]


def test_nothing_to_cost_returns_none():
    assert run(bom=[], proc=[]) is None


def test_totals_equal_sum_of_displayed_lines():
    # 3.44 g at 100/kg = 0.344 each: rounds to 0.34, three lines would drift if totals were rounded once
    bom = [BomLine(component=c, material="PP", mass_g=3.44, basis="x", estimate_inr=0) for c in ("a", "b", "c")]
    c = run(bom=bom, proc=[], prices=[kg(x, "100") for x in ("a", "b", "c")])
    assert c.per_unit == sum(ln.amount for ln in c.lines) == D("1.12")
    # lows 3 x 0.29 + 0.09, highs 3 x 0.40 + 0.12
    assert (c.low, c.high) == (D("0.87") + D("0.09"), D("1.20") + D("0.12"))


def test_cited_line_carries_quote():
    c = run(proc=[], prices=[kg("barrel", "110").model_copy(update={"quote": "Rs 110/kg"})])
    assert c.lines[0].quote == "Rs 110/kg" and c.lines[-1].quote is None
    assert run(proc=[], est={"barrel": D("0.5")}).lines[0].quote is None
