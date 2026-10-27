"""Turn Indian price text into a per-unit INR price. Decimal only, never float."""

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.research.quotes import normalise_text

_RUPEE = "₹"
_CENT = Decimal("0.01")
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_SEP = r"\s*(?:-|to|\u2013)\s*"
_RANGE = r"(?:" + _SEP + r"{cur}?\s*" + _NUM + r")?"
_FOREIGN = r"(?:us\$|\$|usd|euro|eur|€|gbp|£|aed|cny|rmb)"
_PREFIX = re.compile(_RUPEE + r"\s*" + _NUM + _RANGE.format(cur=_RUPEE))
_POSTFIX = re.compile(_NUM + r"(?:" + _SEP + _NUM + r")?\s*" + _RUPEE)
_F_PREFIX = re.compile(_FOREIGN + r"\s*" + _NUM + _RANGE.format(cur=_FOREIGN))
_F_POSTFIX = re.compile(_NUM + r"(?:" + _SEP + _NUM + r")?\s*" + _FOREIGN + r"(?![a-z])")
_BARE = re.compile(r"price\s*:\s*" + _NUM + r"(?:" + _SEP + _NUM + r")?")
_HIGH_IS_QTY = re.compile(r"\s*(?:pcs?|pieces?|nos|units?|boxes|box|packs?)\b")


@dataclass
class PriceParse:
    value: Decimal
    high: Decimal | None
    currency: Literal["INR", "other"]


def _dec(s: str) -> Decimal:
    return Decimal(s.replace(",", "").rstrip("."))


def _build(m: re.Match, currency: Literal["INR", "other"]) -> PriceParse:
    lo = _dec(m.group(1))
    hi = _dec(m.group(2)) if m.lastindex and m.lastindex > 1 and m.group(2) else None
    # a "high" that is really a quantity ("2.10 - 5000 Pcs") is dropped
    if hi is not None and (hi > 10 * lo or _HIGH_IS_QTY.match(m.string, m.end())):
        hi = None
    return PriceParse(lo, hi, currency)


def parse_price(quote: str) -> PriceParse | None:
    q = normalise_text(quote or "")
    # the number attached to the currency marker, never a quantity/MOQ elsewhere in the string
    for pat in (_PREFIX, _POSTFIX):
        ms = list(pat.finditer(q))
        between = q[ms[0].end() : ms[1].start()] if len(ms) == 2 else ""
        if len(ms) == 2 and not (ms[0].group(2) or ms[1].group(2)) and not re.search(r"[a-z]", between):
            # "₹2.10 ₹1.90 / piece": struck MRP, then the offer price. Words in between
            # ("min order value", "moq worth") mean the second amount is not the price.
            return _build(ms[1], "INR")
        if ms:
            return _build(ms[0], "INR")
    for pat in (_F_PREFIX, _F_POSTFIX):
        if m := pat.search(q):
            return _build(m, "other")
    if re.search(_FOREIGN, q):
        return None  # foreign marker but no number attached to it: never guess INR
    # ponytail: a bare "Price: 6.50 - 9" label (TradeIndia style) is assumed INR; Indian marketplaces only
    if m := _BARE.search(q):
        return _build(m, "INR")
    return None


_UNIT = r"(?:pcs?|pieces?|nos|units?)"
_PACK = r"(?:pack|box|carton|case|set|packet|bag|roll|strip|kit|dozen)(?:s|es)?"
_PER_UNIT = re.compile(r"\b(?:piece|pc|pcs|unit|nos)s?\b")
_COUNT_PCS = re.compile(r"(\d[\d,]*)\s*" + _UNIT + r"\b")
_PACK_OF = re.compile(r"\b" + _PACK + r"\s+of\s+(\d[\d,]*)")
_MULTI_PACK = re.compile(r"^\s*(\d+)\s*" + _PACK + r"\b")
_MOQ = re.compile(r"\b(?:moq|minimum order quantity|min\.? order)")
_PER_PIECE = re.compile(r"(?:/|\bper\b)\s*" + _PER_UNIT.pattern)


def pack_size(basis_quote: str | None, title: str) -> int | None:
    """Pieces per priced unit, or None when it cannot be determined safely."""
    # the MOQ clause (label to end) is a purchase quantity, not the price basis
    b = _MOQ.split(normalise_text(basis_quote or ""))[0]
    if not b.strip():
        return None
    if (m := _MULTI_PACK.match(b)) and int(m.group(1)) != 1:
        return None  # "10 boxes of 100 pcs": the count is not per priced unit
    has_pack = bool(re.search(r"\b" + _PACK + r"\b", b))
    if _PER_PIECE.search(b):
        return None if has_pack else 1  # "per piece, 100 pcs per box": which unit is priced is unclear
    found = {int(x.replace(",", "")) for p in (_COUNT_PCS, _PACK_OF) for x in p.findall(b)}
    if len(found) == 1:
        return found.pop() or None
    if found:
        return None  # conflicting counts
    if not has_pack:
        return 1 if _PER_UNIT.search(b) else None
    if m := _PACK_OF.search(normalise_text(title)):
        return int(m.group(1).replace(",", "")) or None
    return None


def to_unit_price(price: Decimal, basis_quote: str | None, title: str,
                  price_quote: str | None = None) -> tuple[Decimal | None, str | None]:
    n = pack_size(basis_quote, title)
    # C1: a price stated per piece is never divided by a pack count found in the basis
    if n is None or (n > 1 and _PER_PIECE.search(normalise_text(price_quote or ""))):
        return None, "basis_unclear"
    unit = (price / n).quantize(_CENT, rounding=ROUND_HALF_UP)
    if unit <= 0:
        return None, "basis_unclear"  # a free unit price means the basis was misread
    return unit, None


_N = r"(\d+(?:\.\d+)?)"
_EXCL = re.compile(
    r"\bexcl\w*\.?\s*(?:of\s+)?(?:all\s+)?(?:taxes|gst)"
    r"|\bgst\b[^,;]*\b(?:extra|excl\w*|additional)\b"
    r"|\bextra\s+gst"
    r"|(?:\+|\bplus\b)\s*(?:" + _N + r"\s*%\s*)?gst"
)
_INCL = re.compile(r"\bincl")
_RATE = re.compile(_N + r"\s*%\s*gst|\bgst\s*(?:incl\w*\.?\s*)?(?:@|of|:)?\s*" + _N + r"\s*%")
_SLABS = {Decimal(x) for x in (0, 5, 12, 18, 28)}


def gst_rate(quote: str | None) -> Decimal | None:
    """The GST slab rate (0, 5, 12, 18, 28) stated next to "gst" in the quote, else None."""
    m = _RATE.search(normalise_text(quote or ""))
    rate = Decimal(m.group(1) or m.group(2)) if m else None
    return rate if rate in _SLABS else None


def apply_gst(price: Decimal, gst_quote: str | None) -> tuple[Decimal | None, str | None]:
    q = normalise_text(gst_quote or "")
    if not q or _EXCL.search(q) or not _INCL.search(q):
        return price, None
    rate = gst_rate(q)
    if rate is None:
        return price, "incl_gst_rate_unknown"
    if rate == 0:
        return price, None
    return (price / (1 + rate / 100)).quantize(_CENT, rounding=ROUND_HALF_UP), None
