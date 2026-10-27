"""Cross-branch sanity checks (spec 6.3 join + check_sanity, Ruling R29)."""
from decimal import Decimal as D

from app.research.sanity import apply_sanity
from app.research.schemas import CostEstimate, Offer, Tier


def mk(id, price, in_range=True):
    return Offer(id=id, manufacturer=f"Maker {id}", city=None, state=None, platform="Maker site", url=f"u{id}",
                 classification="manufacturer", tiers=[Tier(min_qty=1, unit_price=D(price))], moq=None,
                 in_range=in_range, flags=[], extra_links=[], price_quote="q", spec_match="match", observed_at=None)


def cost(low, high):
    return CostEstimate(per_unit=(D(low) + D(high)) / 2, low=D(low), high=D(high), confidence="high",
                        lines=[], sources=[])


def run(offers, c=None):
    return {o.id: o for o in apply_sanity(offers, c, 100, low_factor=D("0.6"), outlier_factor=D(3))}


def test_unusually_low_flag():
    got = run([mk("a", "0.50"), mk("b", "1.00")], cost("1.00", "2.00"))
    assert got["a"].flags == ["unusually_low"] and got["a"].in_range  # a warning only
    assert got["b"].flags == []


def test_high_outlier_removed_from_range():
    got = run([mk("a", "2"), mk("b", "2.5"), mk("c", "3"), mk("d", "40")])
    assert got["d"].flags == ["outlier"] and not got["d"].in_range
    assert all(got[k].in_range and got[k].flags == [] for k in "abc")


def test_median_needs_three_offers():
    got = run([mk("a", "2"), mk("b", "40")])
    assert got["b"].in_range and got["b"].flags == []
    # out-of-range offers do not count towards the median
    got = run([mk("a", "2"), mk("b", "40"), mk("c", "1", in_range=False)])
    assert got["b"].in_range


def test_unusually_high_against_cost_with_two_offers():
    # R29: Run 2 syringe, Rs 400 box price against a Rs 1 to 2 cost estimate, only 2 offers
    got = run([mk("a", "4"), mk("b", "400")], cost("1.00", "2.00"))
    assert got["b"].flags == ["unusually_high"] and not got["b"].in_range
    assert got["a"].in_range and got["a"].flags == []
    got = run([mk("b", "400", in_range=False)], cost("1.00", "2.00"))
    assert got["b"].flags == []  # only in-range offers are checked against the cost


def test_no_cost_no_cost_flags():
    got = run([mk("a", "1"), mk("b", "20")])
    assert all(o.flags == [] and o.in_range for o in got.values())


def test_unusually_high_is_a_warning_when_cost_confidence_is_low():
    # R37: a low-confidence cost cannot take an offer out of the range
    low = cost("1.00", "2.00").model_copy(update={"confidence": "low"})
    got = {o.id: o for o in apply_sanity([mk("a", "4"), mk("b", "40")], low, 100, low_factor=D("0.6"),
                                         outlier_factor=D(3))}
    assert got["b"].flags == ["unusually_high"] and got["b"].in_range
    medium = cost("1.00", "2.00").model_copy(update={"confidence": "medium"})
    assert not apply_sanity([mk("b", "400")], medium, 100, low_factor=D("0.6"), outlier_factor=D(3))[0].in_range



RUN5_SYRINGE = [("a", "1.75"), ("b", "1.80"), ("c", "105"), ("d", "120"), ("e", "220"), ("f", "516")]


def test_pack_prices_cut_by_cost_whatever_its_confidence():
    # R40: Run 5 syringe pool against a low-confidence cost high of Rs 1.38 (30 x 1.38 = 41.40)
    c = CostEstimate(per_unit=D("1.25"), low=D("1.14"), high=D("1.38"), confidence="low", lines=[], sources=[])
    got = run([mk(i, p) for i, p in RUN5_SYRINGE], c)
    assert [k for k in "abcdef" if got[k].in_range] == ["a", "b"]
    assert all("unusually_high" in got[k].flags for k in "cdef")


def test_no_floor_cut_without_cost():
    # C1: without a cost estimate the 30x floor cut is skipped; only the median rule applies (516 > 3 x 112.5)
    got = run([mk(i, p) for i, p in RUN5_SYRINGE])
    assert [k for k in "abcdef" if got[k].in_range] == ["a", "b", "c", "d", "e"]
    assert got["f"].flags == ["outlier"] and all(got[k].flags == [] for k in "abcde")


def test_one_mis_scaled_cheap_price_does_not_remove_genuine_offers_without_cost():
    # C1: a per-piece price wrongly divided by 100 (0.02) must not cut every genuine Rs 2 offer
    got = run([mk("a", "0.02"), mk("b", "2.10"), mk("c", "2.40")])
    assert all(got[k].in_range and got[k].flags == [] for k in "abc")


def test_floor_skips_unusually_low_offer():
    c = cost("1.00", "2.00").model_copy(update={"confidence": "low"})
    pool = [("a", "0.01"), ("b", "1.00"), ("c", "35"), ("d", "40"), ("e", "45")]  # median 35: no outlier
    got = run([mk(i, p) for i, p in pool], c)
    assert got["a"].in_range and got["a"].flags == ["unusually_low"]
    assert got["b"].in_range and got["b"].flags == []  # the floor is 1.00, not 0.01
    assert all(not got[k].in_range and got[k].flags == ["unusually_high"] for k in "cde")  # above 30 x 1.00
