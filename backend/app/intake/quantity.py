import re
from dataclasses import dataclass

_MULT = {"k": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
         "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000}
_UNITS = r"(?:pcs?|nos?|units?|pieces?|numbers?)"
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_PLAIN = re.compile(rf"{_NUM}\s*({'|'.join(_MULT)})?(?:\s*{_UNITS})?")
_PACK = r"(?:boxes|box|packs?|cartons?)"
_PACKED = re.compile(rf"{_NUM}\s*{_PACK}\s+of\s+{_NUM}(?:\s*{_UNITS})?")
_PACK_ONLY = re.compile(rf"{_NUM}\s*{_PACK}")


@dataclass(frozen=True)
class QuantityParse:
    value: int | None
    needs_basis: bool


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def parse_quantity(text: str) -> QuantityParse:
    t = text.strip().lower()
    if m := _PACKED.fullmatch(t):
        return QuantityParse(round(_n(m[1]) * _n(m[2])), False)
    if _PACK_ONLY.fullmatch(t):
        return QuantityParse(None, True)  # box size unknown
    if m := _PLAIN.fullmatch(t):
        return QuantityParse(round(_n(m[1]) * _MULT.get(m[2], 1)), False)
    return QuantityParse(None, False)
