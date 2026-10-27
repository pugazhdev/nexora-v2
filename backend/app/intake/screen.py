"""Deterministic clean-up of the LLM's IntakeAnalysis before the user sees it."""
import math
from dataclasses import dataclass

from pydantic import ValidationError

from app.intake.quantity import parse_quantity
from app.intake.schemas import IntakeAnalysis, IntakeItem, Question

_REASONS = {"medicine": "Medicines are out of scope", "equipment": "Equipment, not a consumable"}
_NOT_FOUND = "No hospital consumable found. Try another photo or paste the requirement as text."
_EMPTY = {
    "blurry": "The photo is too blurry to read. Retake it or paste the requirement as text.",
    "too_dark": "The photo is too dark to read. Retake it or paste the requirement as text.",
}


@dataclass
class ScreenedItem:
    item: IntakeItem
    in_scope: bool
    scope_reason: str | None
    selected: bool


@dataclass
class Screened:
    items: list[ScreenedItem]
    message: str | None


def _number_q(key: str, label: str, unit: str | None, default, required: bool) -> Question:
    return Question(key=key, label=label, help=None, kind="number", options=[], unit=unit, min=1, max=None,
                    default=default, required=required, price_relevant=False)


def _valid(q: Question) -> bool:
    try:
        Question.model_validate(q.model_dump())
        return True
    except ValidationError:
        return False


def _questions(item: IntakeItem) -> list[Question]:
    seen: set[str] = set()
    kept = []
    for q in item.questions:
        if q.key in seen or not _valid(q):
            continue
        seen.add(q.key)
        kept.append(q)
    llm_qty = next((q for q in kept if q.key == "quantity"), None)
    p = parse_quantity(f"{item.quantity.value:g} {item.quantity.unit}") if item.quantity else None
    if p and p.value is not None:
        default = p.value
    elif p and p.needs_basis:
        default = None
    else:
        default = llm_qty.default if llm_qty else None
    if isinstance(default, bool) or not isinstance(default, int | float) or not default >= 1 or default == math.inf:
        default = None
    rest = [q for q in kept if q.key != "quantity"]
    if p and p.needs_basis and "unit_basis" not in seen:
        rest.append(_number_q("unit_basis", "Pieces per box", "pieces", None, True))
    # I5: with a pieces-per-box question the run multiplies quantity x unit_basis, so ask for boxes
    boxes = any(q.key == "unit_basis" for q in rest)
    label, unit = ("Number of boxes", "boxes") if boxes else ("Quantity", "units")
    return [_number_q("quantity", label, unit, default, True), *rest]


def _sig(item: IntakeItem):
    norm = lambda s: " ".join(s.lower().split())  # noqa: E731
    return norm(item.name), frozenset((a.key, norm(a.value)) for a in item.known_attributes)


def screen_items(analysis: IntakeAnalysis, *, max_items: int) -> Screened:
    merged: dict = {}
    for it in analysis.items:
        if it.category != "not_medical":
            merged.setdefault(_sig(it), it)
    items = list(merged.values())
    if not items:
        return Screened([], _EMPTY.get(analysis.input_quality, _NOT_FOUND))
    message = None
    if len(items) > max_items:
        items, message = items[:max_items], f"Showing the first {max_items} items"
    out = []
    for it in items:
        it = it.model_copy(update={"questions": _questions(it)})
        reason = _REASONS.get(it.category)
        out.append(ScreenedItem(it, reason is None, reason, reason is None))
    return Screened(out, message)
