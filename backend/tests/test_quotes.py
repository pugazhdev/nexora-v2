import pytest

from app.research.quotes import normalise_text, quote_in_page


def test_normalise_text():
    assert normalise_text("Rs.  2.10 /  Piece") == "₹2.10 / piece"
    assert normalise_text("15 INR") == "15 ₹"
    assert normalise_text("hours Rs1.53") == "hours ₹1.53"


def test_quote_found_despite_spacing():
    assert quote_in_page("₹ 2.10 / Piece", "Price: Rs 2.10  /  piece")


def test_quote_found_in_fused_text():
    assert quote_in_page("₹ 2.10 / Piece", "Price₹2.10/Piece")


def test_quote_found_in_split_text():
    assert quote_in_page("₹2.10", "Price ₹ 2 . 10 only")


def test_quote_not_found():
    assert not quote_in_page("₹1.10", "Price ₹2.10")


def test_quote_one_digit_differs():
    assert not quote_in_page("₹ 2.10 / Piece", "Price₹2.11/Piece")


@pytest.mark.parametrize("q,page", [
    ("₹2.1", "Price ₹2.10"),      # truncated number
    ("₹1.10", "Price ₹11.10"),
    ("2.10", "Price 12.10"),
    ("₹2", "Price ₹2.10"),
])
def test_quote_not_a_partial_number(q, page):
    assert not quote_in_page(q, page)


@pytest.mark.parametrize("q", [None, "", "   "])
def test_empty_quote_is_false(q):
    assert not quote_in_page(q, "anything")


@pytest.mark.parametrize("q,page", [
    ("₹2100", "Price: ₹ 2\n100 Pieces/Box"),
    ("₹210", "₹ 2 10 pcs"),
])
def test_separate_cells_never_fuse_into_a_number(q, page):
    assert not quote_in_page(q, page)


def test_dot_then_space_still_matches():
    assert quote_in_page("2.10", "Rs 2. 10")
    assert quote_in_page("Price 12", "Price12")
