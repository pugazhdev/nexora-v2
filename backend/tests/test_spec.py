import pytest
from openai.lib._pydantic import to_strict_json_schema

from app.research.schemas import AttributePair, ExtractedOffer, attributes_dict
from app.research.spec import build_spec, match_spec, normalise_value


def _q(key, label, kind="text", options=(), unit=None, pr=False):
    return {"key": key, "label": label, "kind": kind, "unit": unit, "price_relevant": pr,
            "options": [{"value": v, "label": lab} for v, lab in options]}


def _spec():
    item = {
        "name": "Disposable syringe",
        "analysis": {"known_attributes": [
            {"key": "gauge", "label": "Gauge", "value": "24G", "evidence": "visible on pack"},
            {"key": "colour", "label": "Colour", "value": "clear", "evidence": "visible on pack"},
        ]},
        "questions": [
            _q("quantity", "Quantity", "number"),
            _q("capacity", "Capacity", "single", [("2", "2 mL"), ("5", "5 mL")], pr=True),
            _q("needle", "Needle", "single", [("with", "with needle"), ("without", "without needle")]),
            _q("sterile", "Sterile", "boolean"),
            _q("coated", "Coated", "boolean"),
            _q("unit_basis", "Pieces per box", "number"),
        ],
    }
    answers = {"quantity": 500, "capacity": "2", "needle": "with", "sterile": True, "coated": False, "unit_basis": 100}
    return build_spec(item, answers, 500)


def test_normalise_units():
    assert len({normalise_value(v) for v in ["2 ml", "2ml", "2 mL", "2cc"]}) == 1
    assert len({normalise_value(v) for v in ["3 ply", "3-ply", "three ply", "3ply"]}) == 1
    assert len({normalise_value(v) for v in ["24G", "24 g", "24 gauge"]}) == 1
    assert normalise_value("M") == normalise_value("Medium") == "m"
    assert normalise_value("2 l") == "2 l" and normalise_value("2 Litre") == "2 l"


def test_build_spec_title_and_must_match():
    s = _spec()
    assert s.title == "Disposable syringe, 2 mL, with needle, Sterile, 24G, clear"
    assert s.must_match == ["capacity", "gauge"]
    assert s.quantity == 500 and "quantity" not in s.attributes and "coated" not in s.title


def test_match():
    assert match_spec(_spec(), {"Capacity": "2cc", "gauge": "24 G"}, "Syringe") == "match"
    assert match_spec(_spec(), {}, "Syringe 2 ml 24 gauge") == "match"


def test_mismatch_5ml_vs_2ml():
    assert match_spec(_spec(), {"capacity": "5 ml", "gauge": "24g"}, "Syringe") == "mismatch"
    assert match_spec(_spec(), {}, "5ml Disposable Syringe 24G") == "mismatch"


def test_unstated_when_missing():
    assert match_spec(_spec(), {"gauge": "24g"}, "Disposable Syringe") == "unstated"


def test_ambiguous_when_title_lists_several_capacities():
    assert match_spec(_spec(), {"gauge": "24g"}, "1 ml, 2 ml, 5 ml Disposable Syringe") == "ambiguous"


def test_mismatch_beats_ambiguous():
    assert match_spec(_spec(), {"gauge": "22g"}, "1 ml, 2 ml Syringe") == "mismatch"


def _has_default(node):
    if isinstance(node, dict):
        props = node.get("properties")
        if "default" in node and not isinstance(props, dict):
            return True
        return any(_has_default(v) for k, v in node.items() if k != "properties") or (
            isinstance(props, dict) and any(_has_default(v) for v in props.values()))
    if isinstance(node, list):
        return any(_has_default(v) for v in node)
    return False


def test_extracted_offer_strict_schema_has_no_defaults():
    assert not _has_default(to_strict_json_schema(ExtractedOffer))
    assert _has_default({"properties": {"x": {"default": 1}}})
    assert not _has_default({"properties": {"default": {"type": "string"}}})
    assert attributes_dict([AttributePair(key="a", value="b")]) == {"a": "b"}


def _mk(**attrs):
    from app.research.schemas import ResearchSpec
    return ResearchSpec(name="x", attributes=attrs, quantity=1, title="x", must_match=list(attrs))


def test_length_and_negation():
    assert match_spec(_mk(length="5 cm"), {}, "Tube 2.5 cm") == "mismatch"
    assert match_spec(_mk(length="5 cm"), {}, "Tube 50 mm") == "mismatch"
    assert match_spec(_mk(length="5 cm"), {}, "Tube 5cm") == "match"
    assert match_spec(_mk(sterile="Sterile"), {}, "Non-sterile gloves") == "mismatch"
    assert match_spec(_mk(sterile="Sterile"), {}, "not sterile gloves") == "mismatch"
    assert match_spec(_mk(sterile="Sterile"), {}, "Sterile gloves") == "match"
    assert match_spec(_mk(material="pvc"), {}, "Non-PVC tube") == "mismatch"


def test_bare_number_never_matches():
    assert match_spec(_mk(capacity="2"), {}, "Syringe 5 ml 2 ply") == "unstated"
    assert match_spec(_mk(capacity="2"), {"capacity": "2 ml"}, "Syringe") == "unstated"
    assert match_spec(_mk(ply="3"), {}, "Mask 3 ply") == "match"


def test_number_question_keeps_unit():
    item = {"name": "Syringe", "questions": [{**_q("capacity", "Capacity", "number", unit="ml", pr=True)}]}
    s = build_spec(item, {"capacity": 2}, 1)
    assert s.attributes["capacity"] == "2 ml"
    assert match_spec(s, {}, "Syringe 5 ml") == "mismatch"
    assert match_spec(s, {}, "Syringe 2 ml") == "match"


def test_capacity_near_misses():
    assert match_spec(_mk(capacity="1 ml"), {}, "Syringe 10 ml") == "mismatch"
    assert match_spec(_mk(capacity="2 ml"), {}, "Syringe 12 ml") == "mismatch"
    assert match_spec(_mk(capacity="2 ml"), {}, "Syringe 2.5 ml") == "mismatch"
    assert match_spec(_mk(capacity="2 ml"), {"capacity": "2 l"}, "Syringe") == "mismatch"
    assert match_spec(_mk(capacity="2 ml"), {}, "Bottle 2 litre") == "mismatch"
    assert match_spec(_mk(capacity="2 l"), {}, "Bottle 2 ltr") == "match"


def test_attribute_vs_title_conflict():
    assert match_spec(_mk(capacity="2 ml"), {"capacity": "2 ml"}, "Syringe 5 ml") == "mismatch"
    assert match_spec(_mk(capacity="2 ml"), {"capacity": "2 ml"}, "Syringe 1 ml, 2 ml") == "ambiguous"
    assert match_spec(_mk(capacity="2 ml"), {"capacity": "2 ml"}, "Syringe 2 ml") == "match"


def test_size_matching():
    assert match_spec(_mk(size="M"), {"size": "XL"}, "Gloves") == "mismatch"
    assert match_spec(_mk(size="M"), {}, "Gloves XL") == "mismatch"
    assert match_spec(_mk(size="M"), {}, "Gloves size M") == "match"
    assert match_spec(_mk(size="M"), {}, "Medium Duty Gloves") == "unstated"
    assert match_spec(_mk(size="M"), {}, "Gloves 2 l") == "unstated"


def test_round2_negations():
    for t in ["Latex free gloves", "Gloves without latex", "Latex-free gloves", "Gloves, no latex"]:
        assert match_spec(_mk(material="latex"), {}, t) == "mismatch", t
    assert match_spec(_mk(material="pvc"), {}, "PVC free tube") == "mismatch"
    assert match_spec(_mk(sterile="Sterile"), {}, "Gloves not for sterile use") == "mismatch"
    for t in ["Unsterile gloves", "Nonsterile gloves"]:
        assert match_spec(_mk(sterile="Sterile"), {}, t) == "mismatch", t
    assert match_spec(_mk(material="latex"), {}, "Latex gloves") == "match"


def test_round2_extra_sizes():
    assert match_spec(_mk(size="L"), {}, "Gloves Extra Large") == "mismatch"
    assert match_spec(_mk(size="L"), {}, "Gloves extra-large") == "mismatch"
    assert match_spec(_mk(size="L"), {}, "Gloves X-Large") == "mismatch"
    assert match_spec(_mk(size="L"), {"size": "Extra Large"}, "Gloves") == "mismatch"
    assert match_spec(_mk(size="S"), {}, "Gloves extra small") == "mismatch"
    assert match_spec(_mk(size="XL"), {}, "Gloves Extra Large") == "match"
    assert match_spec(_mk(size="XXL"), {}, "Gloves 2XL") == "match"
    assert match_spec(_mk(size="L"), {}, "Gloves Large") == "match"


def test_round2_ranges():
    for t in ["Syringe 2-5 ml", "Syringe 2 to 5 ml", "Syringe 2/5 ml"]:
        assert match_spec(_mk(capacity="5 ml"), {}, t) == "ambiguous", t
    assert match_spec(_mk(capacity="5 ml"), {"capacity": "2-5 ml"}, "Syringe") == "ambiguous"


def test_round3_normalised_text():
    assert match_spec(_mk(size="L"), {}, "Gloves x large") == "mismatch"
    assert match_spec(_mk(size="L"), {}, "Gloves extra  large") == "mismatch"
    assert match_spec(_mk(size="XL"), {}, "Gloves 3XL") == "mismatch"
    assert match_spec(_mk(size="XXXL"), {}, "Gloves 3XL") == "match"
    for t in ["Syringe 2 " + chr(0x2013) + " 5 ml", "Syringe 2~5 ml", "Syringe 2 " + chr(0x2014) + " 5 ml"]:
        assert match_spec(_mk(capacity="5 ml"), {}, t) == "ambiguous", t


def test_round3_coordinated_free():
    assert match_spec(_mk(material="latex"), {}, "Latex and nitrile free gloves") == "mismatch"
    assert match_spec(_mk(material="latex"), {}, "Latex gloves") == "match"
    assert match_spec(_mk(material="latex"), {}, "Latex gloves, BIS certified, lint free packaging") == "match"


# ---- Ruling R24 -----------------------------------------------------------------------------

def test_type_gate():
    from app.research.spec import type_matches
    assert not type_matches(["syringe"], "Romsons Disposable Needle - 23G x 1Inch Pack of 100", {})
    assert type_matches(["syringe"], "2 Ml Disposable Syringe With Needles", {})
    assert type_matches(["syringe"], "Disposable Syringes", {})
    urine = ["urine bag", "urine collection bag", "urinary drainage bag"]
    assert type_matches(urine, "Urine Collection Bag", {})
    assert not type_matches(urine, "Garbage Bag", {})
    assert not type_matches(["syringe"], "", {})
    assert type_matches(["glove"], "Nitrile Examination Gloves", {})


def test_type_gate_fallback_uses_last_word_of_name():
    from app.research.spec import type_terms_of
    assert type_terms_of(_mk(capacity="2 ml").model_copy(update={"name": "Nitrile Gloves"})) == ["glove"]
    assert type_terms_of(_mk().model_copy(update={"name": "IV cannula 20G"})) == ["cannula"]
    assert type_terms_of(_mk().model_copy(update={"type_terms": ["mask"]})) == ["mask"]


@pytest.mark.parametrize(("name", "term"), [
    ("Urine bag 2000 mL", "bag"),
    ("Nitrile examination gloves, M, powder-free", "glove"),
    ("Surgical gloves size 7.5", "glove"),
    ("Cotton roll 500 g", "roll"),
    ("Gauze swab 10 x 10 cm", "swab"),
    ("Face mask (3 ply)", "mask"),
    ("IV cannula 20G", "cannula"),
    ("Disposable syringe 2 ml sterile", "syringe"),
    ("Examination gloves Large", "glove"),
    ("cotton 100gm", "cotton"),
])
def test_type_gate_fallback_skips_units_and_qualifiers(name, term):
    from app.research.spec import type_terms_of
    assert type_terms_of(_mk().model_copy(update={"name": name})) == [term]


def test_fallback_type_gate_rejects_other_products():
    from app.research.spec import type_matches, type_terms_of
    terms = type_terms_of(_mk().model_copy(update={"name": "Nitrile examination gloves, M, powder-free"}))
    assert not type_matches(terms, "Alcohol free hand sanitizer", {})


def _cannula():
    item = {"name": "IV cannula", "questions": [
        _q("gauge", "Gauge", "single", [("20", "20G")], pr=True),
        _q("port", "With injection port?", "boolean", pr=True),
        _q("wings", "Does it have wings?", "boolean", pr=True),
        _q("sterile", "Is it sterile?", "boolean", pr=True),
        _q("material", "Material", "text", pr=True),
    ]}
    return build_spec(item, {"gauge": "20", "port": True, "wings": True, "sterile": False, "material": "PTFE"}, 1)


def test_boolean_rendering_and_never_must_match():
    s = _cannula()
    assert s.title == "IV cannula, 20G, With injection port, wings, PTFE"
    assert s.must_match == ["gauge", "material"]
    assert s.primary_key == "gauge"


def test_primary_key_order():
    def spec(name, qs, answers):
        return build_spec({"name": name, "questions": qs}, answers, 1)
    syr = spec("Syringe", [_q("gauge", "Gauge", pr=True), _q("capacity", "Capacity", pr=True),
                           _q("sterile", "Sterile", "single", [("y", "Sterile")], pr=True)],
               {"gauge": "23G", "capacity": "2 ml", "sterile": "y"})
    assert syr.primary_key == "capacity"
    gl = spec("Gloves", [_q("size", "Size", pr=True), _q("material", "Material", pr=True)],
              {"size": "M", "material": "Nitrile"})
    assert gl.primary_key == "material"
    mask = spec("Mask", [_q("material", "Material", pr=True), _q("ply", "Ply", pr=True)],
                {"material": "PP", "ply": "3"})
    assert mask.primary_key == "ply"
    assert spec("Mask", [_q("ply", "Ply")], {"ply": "3"}).primary_key is None


def test_size_list_including_requested_size_matches():
    assert match_spec(_mk(size="M"), {}, "Gloves Sizes: S, M, L, XL") == "match"
    assert match_spec(_mk(size="M"), {}, "Gloves Sizes: S, L, XL") == "mismatch"
    assert match_spec(_mk(size="M"), {"size": "S, M, L, XL"}, "Gloves") == "match"
    assert match_spec(_mk(size="M"), {"size": "L, XL"}, "Gloves") == "mismatch"
    assert match_spec(_mk(capacity="2 ml"), {}, "Syringe 1 ml, 2 ml") == "ambiguous"  # other keys unchanged


def test_match_keys_per_key_verdicts():
    from app.research.spec import match_keys
    s = _mk(capacity="2 ml", gauge="23G")
    assert match_keys(s, {}, "2 Ml Disposable Syringe With Needles") == {"capacity": "match", "gauge": "unstated"}


def test_known_attribute_with_primary_kind_enters_must_match():
    item = {"name": "Syringe", "analysis": {"known_attributes": [
        {"key": "syringe_volume", "label": "Syringe Volume", "value": "2 mL", "evidence": "stated in text"},
        {"key": "with_needle", "label": "Includes Needle", "value": "yes", "evidence": "stated in text"}]},
        "questions": [_q("gauge", "Gauge", pr=True)]}
    s = build_spec(item, {"gauge": "23G"}, 1)
    assert s.must_match == ["gauge", "syringe_volume"] and s.primary_key == "syringe_volume"
    assert match_spec(s, {}, "5 ml Disposable Syringe 23G") == "mismatch"


def test_kind_in_item_name_becomes_must_match():
    # R35: "3-ply" in the name is a defining attribute even when no question covers it
    item = {"name": "3-ply surgical mask", "analysis": {"known_attributes": [
        {"key": "type", "label": "Type", "value": "3-ply surgical", "evidence": "stated in text"}]},
        "questions": [_q("material", "Material", pr=True), _q("tie_type", "Tie type", pr=True)]}
    s = build_spec(item, {"material": "polypropylene", "tie_type": "earloop"}, 1)
    assert "ply" in s.must_match and s.primary_key == "ply" and s.attributes["ply"] == "3 ply"
    assert match_spec(s, {}, "2 Ply Surgical Mask") == "mismatch"
    # a question already covering the kind wins: no implicit duplicate
    item = {"name": "2 mL syringe", "questions": [_q("capacity", "Capacity", pr=True)]}
    s = build_spec(item, {"capacity": "5 ml"}, 1)
    assert s.must_match == ["capacity"] and "capacity" not in {k for k in s.attributes if k != "capacity"}
