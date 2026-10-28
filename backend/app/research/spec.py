"""Deterministic spec building and variant matching (anti-goal: a 5 mL listing is never the answer for 2 mL)."""
import re
from typing import Literal

from app.research.schemas import ResearchSpec

_SKIP = {"quantity", "unit_basis"}
_KEYISH = {"capacity", "volume", "size", "ply", "material", "gauge", "length", "diameter"}
_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
          "eight": "8", "nine": "9", "ten": "10"}
_SIZES = {"small": "s", "medium": "m", "large": "l", "extra large": "xl", "x large": "xl",
          "extra small": "xs", "x small": "xs", "2xl": "xxl", "3xl": "xxxl"}

# (pattern, replacement) applied in order after lower-casing
_RULES = [
    (r"\b(" + "|".join(_WORDS) + r")(?=[ -]?ply\b)", lambda m: _WORDS[m[1]]),
    (r"(\d)\s*(?:ml|cc)\b", r"\1 ml"),
    (r"(\d)\s*(?:ltr|litre|liter|l)\b", r"\1 l"),
    (r"(\d)\s*(?:mm|millimet(?:re|er)s?)\b", r"\1 mm"),
    (r"(\d)\s*(?:cm|centimet(?:re|er)s?)\b", r"\1 cm"),
    (r"(\d)\s*(?:m|mtr|metres?|meters?)\b", r"\1 m"),
    (r"(\d)\s*(?:inches|inch|\"|″)(?!\w)", r"\1 inch"),
    (r"(\d+)\s*(?:g|gauge)\b", r"\1g"),
    (r"(\d+)\s*-?\s*ply\b", r"\1 ply"),
]
_NUM = r"(?<![\w.])\d+(?:\.\d+)?"
# value "kind" finders on normalised text
_KINDS = {
    "capacity": _NUM + r" (?:ml|l)(?!\w)",
    "length": _NUM + r" (?:mm|cm|m|inch)(?!\w)",
    "gauge": _NUM + r"g(?!\w)",
    "ply": _NUM + r" ply(?!\w)",
}
_RANGE = (r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?:-|to|/)\s*(\d+(?:\.\d+)?)"
          r"( (?:ml|l|mm|cm|m|inch|ply)|g)(?!\w)")
_SIZE_RE = r"xs|s|m|l|xl|xxl|xxxl"
_NUMERIC_KEYS = {"capacity", "volume", "length", "diameter", "gauge"}
_SIZE_TITLE = (r"(?<![\w\-.])(?<!\d )"
               r"(extra[\s-]large|x[\s-]large|extra[\s-]small|x[\s-]small|3xl|xxxl|2xl|xxl|xl|xs|m|l|small|medium|large)(?![\w\-.])"
               r"(?! (?:duty|weight|density|grade|pack|quantity))")
# ponytail: bare "s" is not searched in titles (too many false hits); add if listings use "S" alone.


def _clean(v: str) -> str:
    v = v.lower().replace("~", "-")
    for d in (0x2012, 0x2013, 0x2014):
        v = v.replace(chr(d), "-")
    return re.sub(r"\s+", " ", v).strip()


def _size_word(v: str) -> str:
    return re.sub(r"[\s\-]+", " ", v)


def normalise_value(value: str) -> str:
    v = _clean(value)
    if (k := _size_word(v)) in _SIZES:
        return _SIZES[k]
    if re.fullmatch(_SIZE_RE, v):
        return v
    for pat, rep in _RULES:
        v = re.sub(pat, rep, v)
    return v


def _key(k: str) -> str:
    return re.sub(r"[\s\-_]+", "_", k.strip().lower())


def _kind(key: str, want: str) -> str | None:
    for name, pat in _KINDS.items():
        if re.fullmatch(pat, want):
            return name
    return "size" if "size" in _key(key) and re.fullmatch(_SIZE_RE, want) else None


def _found(text: str, kind: str, title: bool) -> set[str]:
    if kind == "size" and title:
        return {_SIZES.get(_size_word(s), s) for s in re.findall(_SIZE_TITLE, text.lower())}
    if kind == "size":  # attribute value: one size, or a list of sizes ("S, M, L, XL")
        parts = {normalise_value(p) for p in re.split(r"[,/;|]|and", text) if p.strip()}
        return parts if all(re.fullmatch(_SIZE_RE, p) for p in parts) else set()
    n = normalise_value(text)
    n = re.sub(_RANGE, r"\1\3, \2\3", n)  # "2-5 ml" lists both ends
    return set(re.findall(_KINDS[kind], n))


def _free_ahead(rest: str) -> bool:
    clause = re.split(r"[,;]", rest, maxsplit=1)[0]
    words = re.findall(r"[\w\-]+", clause)[:4]
    return any(w == "free" or w.endswith("-free") for w in words)


def _word_in_title(want: str, title: str) -> str:
    t = title.lower()
    w = re.escape(want)
    if re.search(r"(?<![\w.])(?:non|un)" + w + r"(?![\w\-])", t):
        return "mismatch"
    out = "unstated"
    for m in re.finditer(r"(?<![\w.])" + w + r"(?!\w)(?!-(?!free\b))", t):
        pre = t[:m.start()]
        if (re.search(r"(?:non|un|not)[\s\-]*$", pre) or _free_ahead(t[m.end():])
                or {"without", "no", "not", "non"} & set(re.findall(r"[\w\-]+", pre)[-3:])):
            return "mismatch"
        if not pre.endswith("-"):
            out = "match"
    return out


def _verdict_for_key(k: str, want: str, attrs: dict[str, str], title: str) -> str:
    val = attrs.get(_key(k))
    val = val if val and val.strip() else None
    if re.fullmatch(r"\d+(?:\.\d+)?", want):
        if _key(k) == "ply":
            want = f"{want} ply"
        elif _key(k) in _NUMERIC_KEYS:
            return "unstated"
    kind = _kind(k, want)
    if kind:
        sources = [x for x in ((_found(val, kind, False) if val else set()), _found(title, kind, True)) if x]
        if kind == "size":  # R24: a size list that includes the requested size counts as a match
            return "mismatch" if any(want not in x for x in sources) else "match" if sources else "unstated"
        if any(len(x) == 1 and want not in x for x in sources):
            return "mismatch"
        if any(len(x) > 1 for x in sources):
            return "ambiguous"
        return "match" if sources else "unstated"
    res = {_word_in_title(want, title)}
    if val:
        res.add("match" if normalise_value(val) == want else "mismatch")
    return "mismatch" if "mismatch" in res else "match" if "match" in res else "unstated"


Verdict = Literal["match", "mismatch", "unstated", "ambiguous"]


def match_keys(spec: ResearchSpec, attributes: dict[str, str], title: str) -> dict[str, Verdict]:
    """Per must_match key verdict (keys without a wanted value are skipped)."""
    title = _clean(title)
    attrs = {_key(k): _clean(v) for k, v in attributes.items()}
    return {k: _verdict_for_key(k, want, attrs, title)
            for k in spec.must_match if (want := normalise_value(spec.attributes.get(k, "")))}


def match_spec(spec: ResearchSpec, attributes: dict[str, str], title: str) -> Verdict:
    """Overall verdict: mismatch, then ambiguous, then unstated, else match."""
    verdicts = set(match_keys(spec, attributes, title).values())
    for v in ("mismatch", "ambiguous", "unstated"):
        if v in verdicts:
            return v
    return "match"


def _singular(w: str) -> str:
    if re.search(r"(?:ss|x|z|ch|sh)es$", w):
        return w[:-2]
    return w[:-1] if w.endswith("s") and not w.endswith("ss") else w


_NOT_TYPE = {"ml", "mm", "cm", "kg", "inch", "ply", "size", "free", "powder", "sterile", "disposable",
             "xs", "xl", "xxl", "small", "medium", "large"}


def type_terms_of(spec: ResearchSpec) -> list[str]:
    """The plan's type terms, else the singularised last product word of the name: the part before the first
    "," or "(", alphabetic words only, skipping single letters, units and qualifiers ("Urine bag 2000 mL")."""
    if spec.type_terms:
        return spec.type_terms
    head = re.split(r"[,(]", _clean(spec.name), maxsplit=1)[0]
    words = [w for w in re.findall(r"\w+", head) if w.isalpha() and len(w) > 1 and w not in _NOT_TYPE]
    return [_singular(words[-1])] if words else []


def type_matches(type_terms: list[str], title: str, attributes: dict[str, str]) -> bool:
    """R24 product type gate: every word of one phrase appears in the title as a whole word (plural s/es ok).

    attributes are not used: the gate checks the verified title only, so an attribute cannot rescue a wrong product.
    """
    t = _clean(title)
    phrases = [p.split() for p in map(_clean, type_terms) if p]
    if not phrases:
        return True
    return any(all(re.search(r"(?<!\w)" + re.escape(w) + r"(?:s|es)?(?!\w)", t) for w in p) for p in phrases)


_PRIMARY_NAMES = [("capacity", "volume"), ("ply",), ("gauge",), ("material",), ("length", "diameter"), ("size",)]
_PRIMARY_KINDS = {"capacity": 0, "ply": 1, "gauge": 2, "length": 4, "size": 5}


def _primary_rank(k: str, value: str) -> int:
    kk = _key(k)
    for i, names in enumerate(_PRIMARY_NAMES):
        if any(n in kk for n in names):
            return i
    return _PRIMARY_KINDS.get(_kind(k, normalise_value(value)) or "", len(_PRIMARY_NAMES))


def primary_key_of(must_match: list[str], attributes: dict[str, str]) -> str | None:
    """R24: the defining must_match key by kind order, ties by question order (min keeps the first)."""
    keys = [k for k in must_match if attributes.get(k)]
    return min(keys, key=lambda k: _primary_rank(k, attributes[k]), default=None)


def _bool_label(label: str) -> str:
    s = re.sub(r"\?\s*$", "", label.strip())
    return re.sub(r"^(?:is it|is the|does it have)\s+", "", s, flags=re.I)


def _display(q: dict, v) -> str | None:
    kind = q["kind"]
    if kind == "boolean":
        return _bool_label(q["label"]) if v is True else None
    if kind in ("single", "multi"):
        labels = {o["value"]: o["label"] for o in q["options"]}
        vals = v if isinstance(v, list) else [v]
        return "/".join(labels.get(x, str(x)) for x in vals) or None
    if kind == "number":
        n = f"{float(v):g}"
        return f"{n} {q['unit']}" if q.get("unit") else n
    s = str(v).strip()
    return s or None


def build_spec(item: dict, answers: dict, quantity: int) -> ResearchSpec:
    analysis = item.get("analysis") or {}
    known = {a["key"]: a for a in item.get("known_attributes", analysis.get("known_attributes", []))}
    attrs: dict[str, str] = {}
    parts: list[str] = []
    must: list[str] = []
    for q in item["questions"]:
        if q["key"] in _SKIP:
            continue
        v = answers.get(q["key"])
        blank = v is None or v == [] or (isinstance(v, str) and not v.strip())
        shown = None if blank else _display(q, v)
        if shown:
            parts.append(shown)
        if not blank:
            attrs[q["key"]] = shown or "no"
        if q.get("price_relevant") and q["kind"] != "boolean" and q["key"] not in must:
            must.append(q["key"])
    asked = {q["key"] for q in item["questions"]}
    for k, a in known.items():
        if k in asked or k in _SKIP:
            continue
        attrs[k] = a["value"]
        parts.append(a["value"])
        # ponytail: analysis has no per-attribute price flag, so key names stand in for it
        if a.get("evidence") in ("visible on pack", "stated in text") and (
                _key(k) in _KEYISH or _primary_rank(k, a["value"]) < len(_PRIMARY_NAMES)):
            must.append(k)
    name = item["name"]
    # R35: a kind value written in the name ("3-ply", "2 mL", "20G") is a defining attribute unless a
    # must_match attribute of that kind already exists
    covered = {_kind(k, normalise_value(attrs[k])) for k in must if attrs.get(k)}
    for kind in ("capacity", "ply", "gauge", "length"):
        found = _found(name, kind, False)
        if kind not in covered and len(found) == 1 and kind not in attrs:
            attrs[kind] = found.pop()
            must.append(kind)
    return ResearchSpec(name=name, attributes=attrs, quantity=quantity,
                        title=", ".join([name, *parts]), must_match=must, primary_key=primary_key_of(must, attrs))


def build_part_spec(parent: ResearchSpec, part: dict) -> ResearchSpec:
    """Spec for one part of a split product (spec 6.3).

    attributes: the part's typical_material as "material" (searched, not matched: listings word materials
    too differently for an exact check), plus one parent size: the gauge for needle/cannula parts, else the
    capacity. Only that size is must_match. quantity = parent quantity x count_per_unit.
    """
    name = part["name"]
    want = "gauge" if re.search(r"needle|cannula", name, re.I) else "capacity"
    attrs: dict[str, str] = {}
    if part.get("typical_material"):
        attrs["material"] = part["typical_material"]
    must: list[str] = []
    for k, v in parent.attributes.items():
        if _kind(k, normalise_value(v)) == want:
            attrs[k] = v
            must.append(k)
            break
    low = _clean(name)
    return ResearchSpec(name=name, attributes=attrs, quantity=parent.quantity * max(1, part.get("count_per_unit", 1)),
                        title=", ".join([name, *attrs.values()]), must_match=must,
                        type_terms=list(dict.fromkeys([low, _singular(low)])),
                        primary_key=primary_key_of(must, attrs))
