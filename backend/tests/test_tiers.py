import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.research.schemas import Offer, Tier
from app.research.tiers import purchase_range, total

SHARED = Path(__file__).resolve().parents[2] / "shared"
CASES = json.loads((SHARED / "calculator_cases.json").read_text())
TOTAL_CASES = json.loads((SHARED / "total_cases.json").read_text())


def _offer(d: dict) -> Offer:
    return Offer(
        id=d["id"], manufacturer="x", city=None, state=None, platform="Maker site",
        url=f"https://example.com/{d['id']}", classification=d["classification"],
        tiers=[Tier(min_qty=t["min_qty"], unit_price=Decimal(t["unit_price"])) for t in d["tiers"]],
        moq=d["moq"], in_range=d["in_range"], flags=[], extra_links=[], price_quote="",
        spec_match="match", observed_at=None,
    )


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_calculator_cases(case):
    r = purchase_range([_offer(o) for o in case["offers"]], case["quantity"])
    exp = case["expected"]
    money = lambda v: None if v is None else Decimal(v)  # noqa: E731
    assert r.lowest_id == exp["lowest_id"]
    assert r.lowest_unit == money(exp["lowest_unit"])
    assert r.highest_id == exp["highest_id"]
    assert r.highest_unit == money(exp["highest_unit"])
    assert r.fallback_all_moq == exp["fallback_all_moq"]
    assert r.unconfirmed_only == exp["unconfirmed_only"]


def test_total_with_gst_and_freight():
    assert total(Decimal("1.85"), 50000, Decimal("5"), Decimal("1500")) == Decimal("98625")


@pytest.mark.parametrize("c", TOTAL_CASES, ids=[f"{c['unit']}x{c['qty']}" for c in TOTAL_CASES])
def test_total_cases(c):
    assert total(Decimal(c["unit"]), c["qty"], Decimal(c["gst_pct"]), Decimal(c["freight"])) == Decimal(c["expected"])
