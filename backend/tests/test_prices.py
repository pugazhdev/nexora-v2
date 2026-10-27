from decimal import Decimal

import pytest

from app.research.prices import PriceParse, apply_gst, pack_size, parse_price, to_unit_price

D = Decimal


@pytest.mark.parametrize("q,val,high,cur", [
    ("₹ 2.10 / Piece", "2.10", None, "INR"),
    ("Rs. 1,250/Box", "1250", None, "INR"),
    ("INR 1,00,000", "100000", None, "INR"),
    ("₹1.80 - 2.20", "1.80", "2.20", "INR"),
    ("$0.05", "0.05", None, "other"),
    # real strings from phase0-findings
    ("₹ 150/ Box", "150", None, "INR"),
    ("₹ 9.10 / Piece", "9.10", None, "INR"),
    ("₹ 1.50/Piece", "1.50", None, "INR"),
    ("Price: 15 INR / Piece Get Latest Price Minimum Order Quantity : 100 Piece", "15", None, "INR"),
    ("Price: 100 INR MOQ - 500 Piece/Pieces", "100", None, "INR"),
    ("Price: 1.75 INR/Piece Get Best Quote MOQ 2000 Piece/Pieces", "1.75", None, "INR"),
    ("Price: 1600 INR Get Best Quote MOQ 1 Pack of 1000", "1600", None, "INR"),
    ("1.75 INR (Approx.)", "1.75", None, "INR"),
    ("Price: 1.75 - 2.50 / Piece Minimum Order Quantity : 1000 Piece", "1.75", "2.50", "INR"),
    ("₹ 1.75 - ₹ 2.50 / Piece", "1.75", "2.50", "INR"),
    ("Price: 6.50 - 9 / Piece MOQ : 10000 Piece", "6.50", "9", "INR"),
    ("₹1.80 to ₹2.20", "1.80", "2.20", "INR"),
    ("₹1.80 \u2013 2.20", "1.80", "2.20", "INR"),
    ("Rs 1.53  / Piece Price on Request Minimum Order Quantity: 2000 Piece", "1.53", None, "INR"),
    ("Rs 155  / Box ... Minimum Order Quantity: 100 Box", "155", None, "INR"),
    ("₹ 2.10 MOQ 500 Piece", "2.10", None, "INR"),
])
def test_parse_price(q, val, high, cur):
    p = parse_price(q)
    assert p == PriceParse(D(val), D(high) if high else None, cur)
    assert isinstance(p.value, Decimal)


@pytest.mark.parametrize("q", [
    "Get Latest Price", "Ask for price", "Price on request", "", "MOQ 500 Piece",
    "Get Best Quote MOQ 2000 Piece", "6.50 / Piece",
])
def test_parse_price_none(q):
    assert parse_price(q) is None


@pytest.mark.parametrize("basis,title,n", [
    ("Pack of 100", "", 100), ("Box of 100 pieces", "", 100), ("100 Pcs/Box", "", 100),
    ("Per Piece", "", 1), ("1 Carton (2400 pcs)", "", 2400), ("Per Box", "Syringe 2ml box", None),
    ("/ Piece", "", 1), ("Unit", "", 1), ("1 Pack of 1000", "", 1000),
    ("Per Box", "Gloves box of 50", 50), ("Per Box", "", None), (None, "Syringe", None),
    ("10 Boxes of 100 pcs", "", None), ("Per Piece", "Pack of 100 gloves", 1),
])
def test_pack_size(basis, title, n):
    assert pack_size(basis, title) == n


def test_box_price_without_count_is_flagged():
    assert to_unit_price(D("250"), "Per Box", "Syringe") == (None, "basis_unclear")


def test_no_basis_is_flagged():
    assert to_unit_price(D("250"), None, "Syringe") == (None, "basis_unclear")


def test_box_price_with_count_divides():
    assert to_unit_price(D("250"), "Pack of 100", "")[0] == D("2.50")


def test_unit_price_rounds_half_up():
    assert to_unit_price(D("1"), "Pack of 8", "") == (D("0.13"), None)
    assert to_unit_price(D("9.10"), "Piece", "") == (D("9.10"), None)


@pytest.mark.parametrize("q", ["Inclusive of 12% GST", "incl. 12% GST", "GST included @12%"])
def test_gst_inclusive_with_rate(q):
    assert apply_gst(D("112"), q) == (D("100.00"), None)


def test_gst_other_rates():
    assert apply_gst(D("105"), "incl. 5% GST") == (D("100.00"), None)
    assert apply_gst(D("118"), "Inclusive of 18% GST") == (D("100.00"), None)


@pytest.mark.parametrize("q", ["Incl. GST", "inclusive of all taxes"])
def test_gst_inclusive_without_rate(q):
    assert apply_gst(D("112"), q) == (D("112"), "incl_gst_rate_unknown")


@pytest.mark.parametrize("q", ["+ 12% GST", "exclusive of GST", "GST extra", None])
def test_gst_unchanged(q):
    assert apply_gst(D("100"), q) == (D("100"), None)


@pytest.mark.parametrize("basis,n", [
    ("/ Piece Minimum Order Quantity : 100 Piece", 1),
    ("Piece MOQ 500 Piece", 1),
    ("INR/Unit Get Best Quote MOQ 3000000 Unit/Units", 1),
    ("1.75 INR/Piece Get Best Quote MOQ 2000 Piece/Pieces", 1),
    ("Price: 1600 INR Get Best Quote MOQ 1 Pack of 1000", None),
    ("Per Box (each)", None),
    ("Per Box, no returns", None),
    ("Per Bag", None),
])
def test_pack_size_ignores_moq_and_loose_words(basis, n):
    assert pack_size(basis, "") == n


def test_unit_price_zero_is_flagged():
    assert to_unit_price(D("2.25"), "INR/Unit MOQ 3000000 Unit/Units", "") == (D("2.25"), None)
    assert to_unit_price(D("0.04"), "Pack of 100", "") == (None, "basis_unclear")


@pytest.mark.parametrize("q,val,high", [
    ("Price: 0.5 USD ($)/Piece", "0.5", None),
    ("Price: 5 - 10 USD / Piece", "5", "10"),
])
def test_foreign_currency_after_number_is_other(q, val, high):
    assert parse_price(q) == PriceParse(D(val), D(high) if high else None, "other")


def test_foreign_marker_without_attached_number_is_none():
    assert parse_price("Price: usd") is None


def test_range_high_that_is_a_quantity_is_dropped():
    assert parse_price("₹ 2.10 - 5000 Pcs").high is None
    assert parse_price("₹ 2.10 - 5000 Pcs").value == D("2.10")
    assert parse_price("₹ 2.10 - 50000").high is None


def test_gst_rate_must_be_adjacent_and_a_slab():
    assert apply_gst(D("118"), "Inclusive of GST, 2% cash discount") == (D("118"), "incl_gst_rate_unknown")
    assert apply_gst(D("110"), "Incl. 10% GST") == (D("110"), "incl_gst_rate_unknown")
    assert apply_gst(D("128"), "incl. GST @ 28%") == (D("100.00"), None)
    assert apply_gst(D("112"), "Incl. GST 12%") == (D("100.00"), None)


def test_gst_exclusive_must_refer_to_gst():
    assert apply_gst(D("112"), "Incl. GST, freight extra") == (D("112"), "incl_gst_rate_unknown")
    assert apply_gst(D("100"), "excl. GST") == (D("100"), None)
    assert apply_gst(D("100"), "+ GST") == (D("100"), None)


@pytest.mark.parametrize("quote,basis", [
    ("₹ 2.10 / Piece", "Pack of 100"),
    ("₹ 2.10 / Piece", "Packing: 100 Pieces per box"),
    ("₹ 2.10 per piece", "Box of 50"),
])
def test_per_piece_quote_is_never_divided_by_a_pack_count(quote, basis):
    # C1: a per-piece price next to a pack count is ambiguous, never 2.10 / 100
    assert to_unit_price(D("2.10"), basis, "", quote) == (None, "basis_unclear")


def test_per_piece_quote_with_single_unit_basis_is_kept():
    assert to_unit_price(D("2.10"), "Per Piece", "", "₹ 2.10 / Piece") == (D("2.10"), None)
    assert to_unit_price(D("250"), "Pack of 100", "", "₹ 250 / Pack") == (D("2.50"), None)


def test_pack_size_per_piece_with_pack_count_is_unclear():
    assert pack_size("per piece, 100 pcs per box", "") is None


def test_parse_price_struck_mrp_then_offer_takes_last():
    # T11: "₹2.10 ₹1.90 / Piece" is a struck MRP followed by the offer price
    assert parse_price("₹2.10 ₹1.90 / Piece") == PriceParse(D("1.90"), None, "INR")


@pytest.mark.parametrize(
    "quote,expected",
    [
        ("₹ 2.10 / Piece (Min order value ₹ 5,000)", "2.10"),
        ("₹ 2.10 / Piece, MOQ worth ₹ 5000", "2.10"),
        ("Rs 3.50 per piece, order value Rs 10,000", "3.50"),
        ("₹2.10 ₹1.90 / Piece", "1.90"),
        ("MRP ₹2.10, ₹1.90 / Piece", "1.90"),
    ],
)
def test_second_amount_only_when_adjacent(quote, expected):
    # the second of two amounts is the offer only when nothing but spacing separates them
    assert parse_price(quote).value == D(expected)
