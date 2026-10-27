"""Seller classification and per-manufacturer offer merging. Unclear evidence is never Manufacturer."""
import re
from typing import Literal

from app.research.schemas import Offer

Classification = Literal["manufacturer", "unconfirmed", "excluded"]

_TOKENS = ("oem manufacturer|manufacturer|exporter|supplier|trader|wholesaler|retailer|distributor|importer"
           "|service provider|trading company")
_LABEL = re.compile(r"^(?:business type|nature of business|seller type|company type|supply type)\s*:?\s*")
_TYPE_ONLY = re.compile(rf"(?:{_TOKENS})(?:[\s,&/|-]+(?:and\s+)?(?:{_TOKENS}))*")
_OWN = re.compile(r"\bour\s+(?:own\s+)?manufacturing\s+(?:plant|unit|facilit(?:y|ies))\b"
                  r"|\bwe\s+manufacture\b|\bwe\s+are\s+manufacturers?\s+of\b|\bin-house\s+manufacturing\b"
                  r"|\biso\s*13485\b|\bcdsco\b[^,;.|]*\bmanufactur\w*\s+licen[cs]e\b")
_NEGATED = re.compile(r"\b(?:not|non|nothing|never|third[ -]party|outsourced|source from|partner of|on behalf of)\b"
                      r"|\bno\b(?!\.?\s*[:#]?\s*\d)")  # "no", but not "licence no. 123"
_TRADE = re.compile(r"\b(?:trader|traders|trading|distributor|retailer|wholesaler|reseller|dealer|stockist|importer)s?\b"
                    r"|\bwe\s+trade\b")


def _maker_claim(quote: str) -> bool:
    q = quote.lower().strip()
    if _NEGATED.search(q):
        return False
    label = _LABEL.sub("", q).strip()
    if _TYPE_ONLY.fullmatch(label) and "manufacturer" in label:
        return True
    return bool(_OWN.search(q))


def classify_seller(quotes: list[str]) -> Classification:
    text = " ".join(q.lower() for q in quotes)
    maker = any(_maker_claim(q) for q in quotes)
    trade = bool(_TRADE.search(text))
    if maker and trade:
        return "unconfirmed"
    return "manufacturer" if maker else "excluded" if trade else "unconfirmed"


_NOISE = {"pvt", "private", "ltd", "limited", "llp", "inc", "co", "company", "corporation", "corp", "the", "and"}


def normalise_company(name: str) -> str:
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _NOISE)


def merge_by_manufacturer(offers: list[Offer]) -> list[Offer]:
    groups: dict[tuple, list[Offer]] = {}
    for o in offers:
        key = (normalise_company(o.manufacturer), o.city.lower() if o.city else None)
        groups.setdefault(key, []).append(o)
    out = []
    for group in groups.values():
        # I1: an in-range, non-excluded listing wins over a cheaper one that is neither;
        # min() returns the first minimal element, so ties keep the earlier offer
        keep = min(group, key=lambda o: (not o.in_range, o.classification == "excluded",
                                         o.tiers[0].unit_price if o.tiers else float("inf")))
        links = list(keep.extra_links)
        for o in group:
            if o is not keep and o.url != keep.url and o.url not in links:
                links.append(o.url)
        update: dict = {"extra_links": links}
        kinds = {o.classification for o in group}
        if "excluded" in kinds and "conflicting_seller_type" not in keep.flags:
            update["flags"] = [*keep.flags, "conflicting_seller_type"]
        # R15b: any excluded or unconfirmed member makes a non-excluded winner unconfirmed
        if keep.classification != "excluded" and kinds & {"unconfirmed", "excluded"}:
            update["classification"] = "unconfirmed"
        out.append(keep.model_copy(update=update, deep=True))
    return out
