"""Intake contract between the LLM, the API and the UI. Passed to OpenAI strict structured output."""
import math
from typing import Literal

from pydantic import BaseModel, model_validator


class Option(BaseModel):
    value: str
    label: str


class Question(BaseModel):
    key: str
    label: str
    help: str | None
    kind: Literal["single", "multi", "number", "text", "boolean"]
    options: list[Option]
    unit: str | None
    min: float | None
    max: float | None
    default: str | float | bool | list[str] | None
    required: bool
    price_relevant: bool

    @model_validator(mode="after")
    def _options_count(self):
        # validator, not a schema constraint, so OpenAI strict mode stays happy
        if self.kind in ("single", "multi") and not 2 <= len(self.options) <= 8:
            raise ValueError("single/multi questions need 2 to 8 options")
        return self


class QuestionDraft(BaseModel):
    """Validator-free mirror of Question, so one malformed LLM question cannot fail the whole parse."""

    key: str
    label: str
    help: str | None
    kind: Literal["single", "multi", "number", "text", "boolean"]
    options: list[Option]
    unit: str | None
    min: float | None
    max: float | None
    default: str | float | bool | list[str] | None
    required: bool
    price_relevant: bool


class KnownAttribute(BaseModel):
    key: str
    label: str
    value: str
    evidence: Literal["visible on pack", "stated in text", "inferred"]


class Part(BaseModel):
    name: str
    typical_material: str
    count_per_unit: int


class QuantityHint(BaseModel):
    value: float
    unit: str


class IntakeItem(BaseModel):
    name: str
    category: Literal["consumable", "medicine", "equipment", "not_medical", "unclear"]
    known_attributes: list[KnownAttribute]
    quantity: QuantityHint | None
    questions: list[Question]
    splittable: bool
    parts: list[Part]
    image_region_hint: str


class IntakeItemDraft(BaseModel):
    name: str
    category: Literal["consumable", "medicine", "equipment", "not_medical", "unclear"]
    known_attributes: list[KnownAttribute]
    quantity: QuantityHint | None
    questions: list[QuestionDraft]
    splittable: bool
    parts: list[Part]
    image_region_hint: str


class IntakeAnalysisDraft(BaseModel):
    items: list[IntakeItemDraft]
    input_quality: Literal["ok", "blurry", "too_dark", "no_product", "partial"]
    notes: str


class IntakeAnalysis(BaseModel):
    items: list[IntakeItem]
    input_quality: Literal["ok", "blurry", "too_dark", "no_product", "partial"]
    notes: str


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        n = float(v.strip().replace(",", "")) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _check(q: Question, v) -> str | None:
    if q.kind == "single":
        return None if isinstance(v, str) and v in {o.value for o in q.options} else "pick one of the listed options"
    if q.kind == "multi":
        ok = isinstance(v, list) and all(isinstance(x, str) for x in v)
        if not ok or not set(v) <= {o.value for o in q.options}:
            return "pick only from the listed options"
    elif q.kind == "number":
        n = _num(v)
        if n is None:
            return "enter a number"
        if q.min is not None and n < q.min:
            return f"must be at least {q.min:g}"
        if q.max is not None and n > q.max:
            return f"must be at most {q.max:g}"
    elif q.kind == "boolean":
        return None if isinstance(v, bool) else "must be true or false"
    elif q.kind == "text":
        return None if isinstance(v, str) else "enter text"
    return None


def validate_answers(questions: list[Question], answers: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    for q in questions:
        v = answers.get(q.key)
        blank = v is None or (isinstance(v, str) and not v.strip()) or v == []
        if blank:
            if q.required:
                errors[q.key] = f"{q.label} is required"
            continue
        if err := _check(q, v):
            errors[q.key] = err
    return errors
