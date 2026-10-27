from datetime import date
from decimal import Decimal

import pytest

from app.research.schemas import Offer, Tier
from app.research.sellers import classify_seller, merge_by_manufacturer, normalise_company


@pytest.mark.parametrize("quotes,want", [
    (["Manufacturer"], "manufacturer"),
    (["Manufacturer & Exporter"], "manufacturer"),
    (["Manufacturer, Supplier"], "manufacturer"),
    (["Manufacturer and Exporter"], "manufacturer"),
    (["Business Type: Supplier | Manufacturer"], "manufacturer"),
    (["We run our own manufacturing plant in Baddi"], "manufacturer"),
    (["Our manufacturing unit is in Vapi"], "manufacturer"),
    (["ISO 13485 certified"], "manufacturer"),
    (["CDSCO manufacturing licence no. 123"], "manufacturer"),
    (["Trader"], "excluded"),
    (["Distributor"], "excluded"),
    (["Retailer"], "excluded"),
    (["Wholesaler"], "excluded"),
    (["Importer"], "excluded"),
    (["Nature of business Trader - Retailer"], "excluded"),
    (["Nature of business Wholesaler/Distributor"], "excluded"),
    (["Business Type: Supplier | Trading Company"], "excluded"),
    (["Business Type: Distributor | Supplier"], "excluded"),
    (["Trader & Manufacturer"], "unconfirmed"),
    (["Manufacturer and Trader"], "unconfirmed"),
    (["Wholesaler and Manufacturer"], "unconfirmed"),
    (["Business Type Manufacturer Exporter Wholesaler Retailer"], "unconfirmed"),
    (["Business Type: Supplier | Exporter"], "unconfirmed"),
    ([], "unconfirmed"),
    ([""], "unconfirmed"),
    (["Manufacturers' representative"], "unconfirmed"),
    (["Authorised distributor of Acme manufacturer"], "excluded"),
    (["Manufacturing of goods is outsourced"], "unconfirmed"),
    (["Nonmanufacturer"], "unconfirmed"),
    (["Not a manufacturer"], "unconfirmed"),
    (["We are not manufacturers"], "unconfirmed"),
    (["Top manufacturers list"], "unconfirmed"),
    (["We source from manufacturers"], "unconfirmed"),
    (["Manufacturers & suppliers directory"], "unconfirmed"),
    (["Marketing partner of manufacturer"], "unconfirmed"),
    (["Third party manufacturer"], "unconfirmed"),
    (["We manufacture surgical gloves"], "manufacturer"),
    (["We manufacture nothing, we trade"], "excluded"),
    (["Never in-house manufacturing"], "unconfirmed"),
    (["No in-house manufacturing"], "unconfirmed"),
    (["We trade in surgical gloves"], "excluded"),
    (["Nature of Business: Manufacturer / Exporter / Supplier"], "manufacturer"),
])
def test_classify_seller(quotes, want):
    assert classify_seller(quotes) == want


def test_normalise_company():
    assert normalise_company("Medisafe Disposables Pvt. Ltd.") == normalise_company("MEDISAFE DISPOSABLES PRIVATE LIMITED")
    assert normalise_company("Medisafe Disposables Pvt. Ltd.") == "medisafe disposables"
    assert normalise_company("The Alpha & Beta Co.") == "alpha beta"


def _o(id, name, price, url, city="Delhi", cls="manufacturer", extra=None):
    return Offer(id=id, manufacturer=name, city=city, state=None, platform="IndiaMART", url=url,
                 classification=cls, tiers=[Tier(min_qty=1, unit_price=Decimal(price))], moq=None,
                 in_range=True, flags=[], extra_links=extra or [], price_quote="q", spec_match="match",
                 observed_at=date(2026, 1, 1))


def test_merge_keeps_cheapest_and_links_others():
    a = _o("a", "Medisafe Pvt Ltd", "2", "http://a", extra=["http://old"])
    b = _o("b", "MEDISAFE PRIVATE LIMITED", "1", "http://b", city="DELHI")
    c = _o("c", "Medisafe Ltd", "1", "http://a")
    d = _o("d", "Other Co", "5", "http://d")
    out = merge_by_manufacturer([a, b, c, d])
    assert [o.id for o in out] == ["b", "d"]
    assert out[0].extra_links == ["http://a"]
    assert a.extra_links == ["http://old"] and out[0] is not b


def test_merge_preserves_existing_extra_links_and_ties_keep_earlier():
    a = _o("a", "X Ltd", "1", "http://a", extra=["http://old"])
    b = _o("b", "X Ltd", "1", "http://b")
    out = merge_by_manufacturer([a, b])
    assert [o.id for o in out] == ["a"]
    assert out[0].extra_links == ["http://old", "http://b"]


def test_merge_city_none_only_with_none():
    out = merge_by_manufacturer([_o("a", "X", "1", "u1", city=None), _o("b", "X", "1", "u2"),
                                 _o("c", "X", "2", "u3", city=None)])
    assert sorted(o.id for o in out) == ["a", "b"]


def test_merge_classification_conflicts():
    m = _o("a", "X", "1", "u1", cls="manufacturer")
    u = _o("b", "X", "2", "u2", cls="unconfirmed")
    assert merge_by_manufacturer([m, u])[0].classification == "unconfirmed"
    e = _o("c", "X", "3", "u3", cls="excluded")
    out = merge_by_manufacturer([m, e])[0]
    # R15b: any excluded member makes the merged seller unconfirmed (spec section 2)
    assert out.classification == "unconfirmed" and "conflicting_seller_type" in out.flags
    assert m.flags == []


def test_merge_three_type_group():
    m = _o("a", "X", "1", "u1", cls="manufacturer")
    u = _o("b", "X", "2", "u2", cls="unconfirmed")
    e = _o("c", "X", "3", "u3", cls="excluded")
    out = merge_by_manufacturer([m, u, e])[0]
    assert out.classification == "unconfirmed" and out.flags == ["conflicting_seller_type"]


def _ranged(o, in_range):
    return o.model_copy(update={"in_range": in_range})


def test_merge_prefers_in_range_member_over_cheaper_out_of_range():
    # I1: a matching manufacturer listing must not hide behind a cheaper non-matching one
    cheap = _ranged(_o("a", "X", "1", "u1"), False)
    match = _o("b", "X", "2", "u2")
    out = merge_by_manufacturer([cheap, match])
    assert [o.id for o in out] == ["b"] and out[0].in_range and out[0].extra_links == ["u1"]


def test_merge_prefers_non_excluded_member():
    e = _o("a", "X", "1", "u1", cls="excluded")
    m = _o("b", "X", "2", "u2")
    out = merge_by_manufacturer([e, m])[0]
    assert out.id == "b" and out.classification == "unconfirmed" and out.flags == ["conflicting_seller_type"]
