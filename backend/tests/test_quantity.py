import pytest

from app.intake.quantity import parse_quantity


@pytest.mark.parametrize("text,value,basis", [
    ("50,000", 50000, False), ("1,00,000", 100000, False), ("1 lakh", 100000, False),
    ("2.5 lakh pcs", 250000, False), ("1 crore", 10000000, False), ("50k", 50000, False),
    ("10 boxes of 100", 1000, False), ("10 boxes", None, True), ("", None, False), ("abc", None, False),
    ("2 lac", 200000, False), ("3 Lakhs units", 300000, False), ("1.5 cr", 15000000, False),
    ("500 nos", 500, False), ("5 cartons of 20 pieces", 100, False),
])
def test_parse_quantity(text, value, basis):
    q = parse_quantity(text)
    assert (q.value, q.needs_basis) == (value, basis)
