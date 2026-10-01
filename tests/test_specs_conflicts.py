"""An engineer's own words against the answers: a value typed into an amended
clause, or a paragraph of their own, that says otherwise than the answer to
the question it belongs to."""

from __future__ import annotations

from app import specs, specs_conflicts
from .test_specs import text
from .test_specs_kinds import set_id_of

MASTER = """# PRODUCTS
## CONCRETE MIXTURES
- Cover to other exterior exposed faces: {{rebar_cover_exterior|[50] [40]}} mm.
- Minimum Compressive Strength: {{conc_strength@foundations|[45MPa] [40MPa]}}.
- Maximum w/cm: {{conc_max_wcm@foundations|[0.35] [0.40]}}.
- Exposure class: {{conc_exposure_class|[XS1] [XS2] [XS3]}}.
- Slump: {{conc_slump_value|100 mm}}, plus or minus 25 mm.
"""

QUESTIONS = [
    {"key": "rebar_cover_exterior", "label": "Cover to other exterior exposed faces, mm",
     "group": "Reinforcement"},
    {"key": "conc_strength", "label": "Minimum compressive strength at 28 days",
     "group": "Concrete mixes and properties", "per_element": True},
    {"key": "conc_max_wcm", "label": "Maximum water/cementitious materials ratio",
     "group": "Concrete mixes and properties", "per_element": True},
    {"key": "conc_exposure_class", "label": "Exposure class", "group": "Concrete mixes and properties"},
    {"key": "conc_slump_value", "label": "Slump, plus or minus 25 mm",
     "group": "Concrete mixes and properties"},
]

ANSWERS = {"rebar_cover_exterior": "50", "conc_strength": "40MPa",
           "conc_strength@foundations": "45MPa", "conc_max_wcm": "0.40",
           "conc_exposure_class": "XS3", "conc_slump_value": "100 mm"}


def _project(app, signed_in, answers=ANSWERS):
    from app import specs_questions, specs_store

    with app.app_context():
        have = specs_store.section_by_number("033000", "15A")
        section_id = have["id"] if have else specs_store.save_section(
            "033000", "CAST-IN-PLACE CONCRETE", specs.align([], specs.from_text(MASTER)), family="15A")
        specs_questions.save_definitions(QUESTIONS)
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Quay", "family": "15A"}))
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    with app.app_context():
        specs_questions.save_answers(set_id, answers, {"conc_strength": True})
    return set_id


def _amend(app, set_id, old, new, add=None):
    """The engineer's own words, as the section editor saves them."""
    from app import specs_store

    with app.app_context():
        row = specs_store.set_sections(set_id)[0]
        nodes = specs.loads(row["body"])
        for n in nodes:
            if old and old in n["text"]:
                n["text"] = n["text"].replace(old, new)
        if add:
            nodes.append({**nodes[-1], "id": "own1", "text": add})
        specs_store.save_set_section(set_id, row["id"], nodes)
        return row["id"]


def _found(app, set_id):
    from app import specs_store

    with app.app_context():
        return specs_store.check_set(set_id)["answers"]


# --- the reading ------------------------------------------------------------------------

def test_values_compared_by_quantity_and_family():
    d = specs_conflicts.disagree
    assert d("50", "40") and d("50 mm", "40 mm") and not d("50", "50 mm")
    assert not d("40MPa", "40 N/mm2") and d("40MPa", "35 N/mm²")
    assert d("0.40", "0.45") and not d("0.40", "0.4")
    assert d("XS3", "XS2") and not d("XS3", "XS3") and not d("XS3", "C32/40")
    assert not d("100 mm, plus or minus 25 mm", "100 mm") and d("100 mm, plus or minus 25 mm", "75 mm")
    # Words with no value in them are the engineer's to reword.
    assert not d("50", "as shown on the drawings")
    m = specs_conflicts.matched_answer
    assert m("50", "40") == "40" and m("100 mm, plus or minus 25 mm", "75 mm") == "75 mm, plus or minus 25 mm"
    assert m("XS3", "XS2") == "XS2"


def test_typed_over_a_field_is_found_with_its_place():
    over, own = specs_conflicts.typed_over("Cover: {{rebar_cover_exterior|[50]}} mm, at least.",
                                           "Cover: 40 mm, at least.")
    assert [(o["field"], o["typed"]) for o in over] == [("{{rebar_cover_exterior|[50]}}", "40")]
    assert own == []


# --- through the check -------------------------------------------------------------------

def test_cover_typed_as_40_against_an_answer_of_50(app, signed_in):
    set_id = _project(app, signed_in)
    assert _found(app, set_id) == []              # the master as answered: nothing to say
    _amend(app, set_id, "{{rebar_cover_exterior|[50] [40]}}", "40")
    found = _found(app, set_id)
    assert len(found) == 1
    c = found[0]["conflict"]
    assert (c["typed"], c["answer"], c["label"]) == ("40", "50", "Cover to other exterior exposed faces, mm")
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "Against the answers" in page and "Your clause says" in page
    assert "Use the answer, 50 mm" in page and "Change the answer to 40 mm" in page and "Keep with this reason" in page
    # The issue is held until it is settled.
    from app import specs_store
    with app.app_context():
        assert specs_store.open_items(set_id)["checks"] >= 1


def test_per_element_answer_and_each_quantity(app, signed_in):
    set_id = _project(app, signed_in)
    _amend(app, set_id, "{{conc_strength@foundations|[45MPa] [40MPa]}}", "40MPa")
    _amend(app, set_id, "{{conc_max_wcm@foundations|[0.35] [0.40]}}", "0.45")
    _amend(app, set_id, "{{conc_exposure_class|[XS1] [XS2] [XS3]}}", "XS2")
    _amend(app, set_id, "{{conc_slump_value|100 mm}}", "75 mm")
    by_key = {f["conflict"]["key"]: f["conflict"] for f in _found(app, set_id)}
    assert set(by_key) == {"conc_strength", "conc_max_wcm", "conc_exposure_class", "conc_slump_value"}
    # Foundations has its own strength answer: that is the one compared, and named.
    assert by_key["conc_strength"]["answer"] == "45MPa" and by_key["conc_strength"]["element"] == "foundations"
    assert by_key["conc_max_wcm"]["answer"] == "0.40" and by_key["conc_max_wcm"]["element"] == ""


def test_own_paragraph_giving_cover_is_checked_by_topic(app, signed_in):
    set_id = _project(app, signed_in)
    _amend(app, set_id, None, None, add="Nominal cover to the deck soffit shall be 45 mm.")
    found = _found(app, set_id)
    assert len(found) == 1 and found[0]["conflict"]["kind"] == "topic"
    assert found[0]["conflict"]["typed"] == "45 mm" and found[0]["conflict"]["answers"][0]["answer"] == "50"
    # One that agrees with an answer says nothing.
    set_two = _project(app, signed_in)
    _amend(app, set_two, None, None, add="Nominal cover to the deck soffit shall be 50 mm.")
    assert _found(app, set_two) == []


def test_use_the_answer_puts_the_field_back(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    row_id = _amend(app, set_id, "{{rebar_cover_exterior|[50] [40]}}", "40")
    key = _found(app, set_id)[0]["key"]
    signed_in.post(f"/specs/sets/{set_id}/check/conflict", data={"key": key, "how": "use"})
    with app.app_context():
        body = specs.loads(specs_store.set_section(set_id, row_id)["body"])
        assert any("{{rebar_cover_exterior|[50] [40]}} mm" in n["text"] for n in body)
        report = specs_store.check_set(set_id)
        assert report["answers"] == [] and report["open"]["answers"] == 0
        assert report["done"]["answers"][0]["settled"]["how"] == "amended"


def test_change_the_answer_to_match(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in)
    row_id = _amend(app, set_id, "{{rebar_cover_exterior|[50] [40]}}", "40")
    key = _found(app, set_id)[0]["key"]
    page = text(signed_in.post(f"/specs/sets/{set_id}/check/conflict", data={"key": key, "how": "change"},
                               follow_redirects=True))
    assert "is now 40 mm (it was 50 mm)" in page
    with app.app_context():
        assert specs_questions.answers_of(specs_store.spec_set(set_id))["rebar_cover_exterior"] == "40"
        # The clause follows the answer again.
        body = specs.loads(specs_store.set_section(set_id, row_id)["body"])
        assert any("{{rebar_cover_exterior|" in n["text"] for n in body)
        assert specs_store.check_set(set_id)["answers"] == []


def test_keep_needs_a_reason_and_keeps_it(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    _amend(app, set_id, "{{rebar_cover_exterior|[50] [40]}}", "40")
    key = _found(app, set_id)[0]["key"]
    page = text(signed_in.post(f"/specs/sets/{set_id}/check/conflict",
                               data={"key": key, "how": "keep", "reason": ""}, follow_redirects=True))
    assert "Say why" in page
    signed_in.post(f"/specs/sets/{set_id}/check/conflict",
                   data={"key": key, "how": "keep", "reason": "Internal face, protected by cladding"})
    with app.app_context():
        report = specs_store.check_set(set_id)
        item = report["answers"][0]
        assert item["settled"]["how"] == "kept"
        assert item["settled"]["detail"]["reason"] == "Internal face, protected by cladding"
        assert report["open"]["answers"] == 0
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "Reason: Internal face, protected by cladding" in page


def test_typed_over_again_after_the_answer_was_used_is_open_again(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    _amend(app, set_id, "{{rebar_cover_exterior|[50] [40]}}", "40")
    key = _found(app, set_id)[0]["key"]
    signed_in.post(f"/specs/sets/{set_id}/check/conflict", data={"key": key, "how": "use"})
    assert _found(app, set_id) == []
    _amend(app, set_id, "{{rebar_cover_exterior|[50] [40]}}", "40")
    with app.app_context():
        report = specs_store.check_set(set_id)
        assert len(report["answers"]) == 1 and not report["answers"][0]["settled"]
        assert report["open"]["answers"] == 1
