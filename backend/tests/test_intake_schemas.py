import json

import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import ValidationError

from app.intake.schemas import IntakeAnalysis, IntakeAnalysisDraft, Option, validate_answers
from app.intake.schemas import Question as _Question


def Question(**kw):
    base = dict(help=None, options=[], unit=None, min=None, max=None, default=None, price_relevant=False)
    return _Question(**{**base, **kw})


OPTS = [Option(value="5", label="5 mL"), Option(value="10", label="10 mL")]
CAP_Q = Question(key="capacity", label="Capacity", kind="single", options=OPTS, required=True)
NUM_Q = Question(key="qty", label="Qty", kind="number", unit="units", min=1, max=100, required=True)
MULTI_Q = Question(key="sizes", label="Sizes", kind="multi", options=OPTS, required=False)


def test_validate_required_missing():
    assert "capacity" in validate_answers([CAP_Q], {})


def test_validate_single_rejects_unknown_option():
    assert "capacity" in validate_answers([CAP_Q], {"capacity": "99"})
    assert validate_answers([CAP_Q], {"capacity": "5"}) == {}


@pytest.mark.parametrize("v", [0, 101, "abc", True])
def test_validate_number_range(v):
    assert "qty" in validate_answers([NUM_Q], {"qty": v})


def test_validate_number_ok():
    assert validate_answers([NUM_Q], {"qty": 50}) == {}


def test_validate_multi_accepts_subset():
    assert validate_answers([MULTI_Q], {"sizes": ["5"]}) == {}
    assert "sizes" in validate_answers([MULTI_Q], {"sizes": ["5", "7"]})
    assert "sizes" in validate_answers([MULTI_Q], {"sizes": "5"})


def test_validate_optional_blank_ok_and_boolean_text():
    qs = [Question(key="s", label="S", kind="boolean", required=False),
          Question(key="t", label="T", kind="text", required=True)]
    assert validate_answers(qs, {"t": "x"}) == {}
    assert "s" in validate_answers(qs, {"t": "x", "s": "yes"})
    assert "t" in validate_answers(qs, {"t": "  "})


@pytest.mark.parametrize("n", [0, 1, 9])
def test_question_rejects_bad_option_count(n):
    opts = [Option(value=str(i), label=str(i)) for i in range(n)]
    with pytest.raises(ValidationError):
        Question(key="k", label="K", kind="single", options=opts, required=True)


def test_question_rejects_unknown_kind():
    with pytest.raises(ValidationError):
        Question(key="k", label="K", kind="slider", required=True)


def test_strict_schema_ok():
    to_strict_json_schema(IntakeAnalysis)
    to_strict_json_schema(IntakeAnalysisDraft)


def _default_keywords(node, in_properties=False):
    """Schema `default` keywords, ignoring a property that is merely named "default"."""
    if isinstance(node, list):
        return sum(_default_keywords(n) for n in node)
    if not isinstance(node, dict):
        return 0
    n = 0 if in_properties else int("default" in node)
    return n + sum(_default_keywords(v, k == "properties" and not in_properties) for k, v in node.items())


@pytest.mark.parametrize("model", [IntakeAnalysis, IntakeAnalysisDraft])
def test_strict_schema_has_no_defaults(model):
    schema = to_strict_json_schema(model)
    assert _default_keywords(schema) == 0
    assert '"default": []' not in json.dumps(schema)
    assert '"default": false' not in json.dumps(schema)


@pytest.mark.parametrize("v", ["nan", "inf", "-inf", float("nan"), float("inf")])
def test_validate_number_rejects_non_finite(v):
    assert "qty" in validate_answers([NUM_Q], {"qty": v})
