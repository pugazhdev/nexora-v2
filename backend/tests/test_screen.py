from app.intake.schemas import IntakeAnalysis, IntakeItem, KnownAttribute, QuantityHint, Question
from app.intake.screen import screen_items


def q(key="size", **kw):
    d = dict(key=key, label=key, help=None, kind="text", options=[], unit=None, min=None, max=None,
             default=None, required=False, price_relevant=False)
    return Question(**{**d, **kw})


def item(name="Gloves", category="consumable", attrs=(), quantity=None, questions=()):
    return IntakeItem(
        name=name, category=category,
        known_attributes=[KnownAttribute(key=k, label=k, value=v, evidence="inferred") for k, v in attrs],
        quantity=quantity, questions=list(questions), splittable=False, parts=[], image_region_hint="")


def run(items, quality="ok", max_items=10):
    return screen_items(IntakeAnalysis(items=items, input_quality=quality, notes=""), max_items=max_items)


def test_not_medical_dropped():
    r = run([item("Chair", "not_medical"), item("Syringe")])
    assert [s.item.name for s in r.items] == ["Syringe"]


def test_medicine_kept_unticked_with_reason():
    r = run([item("Paracetamol", "medicine"), item("Monitor", "equipment"), item("Gloves")])
    med, eq, gl = r.items
    assert (med.in_scope, med.selected, med.scope_reason) == (False, False, "Medicines are out of scope")
    assert (eq.in_scope, eq.selected, eq.scope_reason) == (False, False, "Equipment, not a consumable")
    assert (gl.in_scope, gl.selected, gl.scope_reason) == (True, True, None)


def test_duplicates_merged():
    r = run([item("Gloves", attrs=[("size", "M"), ("mat", "Latex")]),
             item("  gloves ", attrs=[("mat", " latex"), ("size", "m")]),
             item("Gloves", attrs=[("size", "L")])])
    assert len(r.items) == 2


def test_cap_at_max_items_with_note():
    r = run([item(f"Item {i}") for i in range(5)], max_items=3)
    assert len(r.items) == 3
    assert r.message == "Showing the first 3 items"


def test_quantity_question_always_present():
    r = run([item(questions=[q("quantity", label="How many", default=5.0)]), item("Mask")])
    for s in r.items:
        qs = [x for x in s.item.questions if x.key == "quantity"]
        assert len(qs) == 1
        x = qs[0]
        assert (x.label, x.kind, x.unit, x.min, x.max, x.required, x.price_relevant) == \
            ("Quantity", "number", "units", 1, None, True, False)
    assert r.items[0].item.questions[0].default == 5.0
    assert r.items[1].item.questions[0].default is None


def test_quantity_prefilled_from_hint():
    r = run([item(quantity=QuantityHint(value=500, unit="pcs"))])
    assert r.items[0].item.questions[0].default == 500


def test_boxes_without_size_adds_basis_question():
    r = run([item(quantity=QuantityHint(value=10, unit="boxes"))])
    b = [x for x in r.items[0].item.questions if x.key == "unit_basis"]
    assert len(b) == 1 and b[0].label == "Pieces per box" and b[0].kind == "number"
    r = run([item(quantity=QuantityHint(value=500, unit="pcs"))])
    assert not [x for x in r.items[0].item.questions if x.key == "unit_basis"]


def test_invalid_question_dropped():
    bad = Question.model_construct(key="bad", label="Bad", help=None, kind="single", options=[], unit=None,
                                   min=None, max=None, default=None, required=False, price_relevant=False)
    it = item().model_copy(update={"questions": [bad, q("size"), q("size", label="dup")]})
    r = screen_items(IntakeAnalysis.model_construct(items=[it], input_quality="ok", notes=""), max_items=10)
    keys = [x.key for x in r.items[0].item.questions]
    assert keys == ["quantity", "size"]
    assert r.items[0].item.questions[1].label == "size"


def test_blurry_with_no_items_message():
    assert run([], "blurry").message == "The photo is too blurry to read. Retake it or paste the requirement as text."
    assert run([], "too_dark").message == "The photo is too dark to read. Retake it or paste the requirement as text."
    nf = "No hospital consumable found. Try another photo or paste the requirement as text."
    for qual in ("no_product", "ok", "partial"):
        assert run([], qual).message == nf
    assert run([item("Chair", "not_medical")], "ok").message == nf


def _qty(r):
    return r.items[0].item.questions[0].default


def test_quantity_default_normalised_by_unit():
    assert _qty(run([item(quantity=QuantityHint(value=1, unit="lakh"))])) == 100000
    assert _qty(run([item(quantity=QuantityHint(value=2, unit="crore"))])) == 20000000
    assert _qty(run([item(quantity=QuantityHint(value=10, unit="boxes of 100"))])) == 1000


def test_boxes_hint_default_none_with_basis_question():
    r = run([item(quantity=QuantityHint(value=10, unit="boxes"))])
    assert _qty(r) is None
    assert any(x.key == "unit_basis" for x in r.items[0].item.questions)


def test_invalid_quantity_defaults_become_none():
    for v in (0, -5):
        assert _qty(run([item(quantity=QuantityHint(value=v, unit="pcs"))])) is None
    assert _qty(run([item(questions=[q("quantity", default="abc")])])) is None
    assert _qty(run([item(questions=[q("quantity", default=True)])])) is None


def test_quantity_is_number_of_boxes_when_basis_is_asked():
    # I5: the backend multiplies quantity x unit_basis, so quantity must be asked in boxes
    q = run([item(quantity=QuantityHint(value=10, unit="boxes"))]).items[0].item.questions[0]
    assert (q.key, q.label, q.unit) == ("quantity", "Number of boxes", "boxes")
    q = run([item(quantity=QuantityHint(value=500, unit="pcs"))]).items[0].item.questions[0]
    assert (q.label, q.unit) == ("Quantity", "units")
