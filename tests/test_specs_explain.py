"""The side panel beside a question: what it means, a drawing of it, and what
the codes say about it, with screenshots of their clauses."""

from __future__ import annotations

import io

from .test_specs import text
from .test_specs_questions import _project

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
REFS = [
    {"code": "ACI 318-19", "clause": "19.2.1.1", "title": "Specified compressive strength",
     "says": "Sets the least f'c for each use.", "kinds": ["15A", "16A"]},
    {"code": "BS 8500-1", "clause": "", "title": "Concrete strength classes",
     "says": "Cylinder and cube strength classes.", "kinds": ["03A"]},
]


def _explained(app):
    from app import specs_questions

    with app.app_context():
        specs_questions.save_definitions([{
            "key": "conc_strength", "label": "Minimum compressive strength at 28 days",
            "group": "Concrete mixes and properties", "suggested": "40MPa", "per_element": True,
            "definition": "The strength the concrete must reach at 28 days.",
            "picture": "test-specimens", "refs": REFS}])


def test_a_question_explains_itself_with_the_projects_own_codes(app, signed_in):
    set_id = _project(app, signed_in)
    _explained(app)
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties"))
    assert 'data-explain="conc_strength"' in page and 'id="spec-explain"' in page
    panel = text(signed_in.get(f"/specs/sets/{set_id}/explain/conc_strength"))
    assert "The strength the concrete must reach at 28 days." in panel
    # Every code is shown whatever the basis: a 15A project reads ACI first, then BS.
    assert panel.index("ACI 318-19") < panel.index("BS 8500-1")
    assert "this project&#39;s basis" in panel or "this project's basis" in panel
    assert panel.index("American: ACI") < panel.index("British and European: BS")
    assert panel.count("spec-explain-mine") == 1
    assert "19.2.1.1" in panel and "Where it goes in this project" in panel
    assert signed_in.get(f"/specs/sets/{set_id}/explain/no_such_key").status_code == 404
    # A library file without explanations does not clear them.
    from app import specs_questions

    with app.app_context():
        specs_questions.save_definitions([{"key": "conc_strength", "label": "Strength",
                                           "group": "Concrete mixes and properties"}])
        d = specs_questions.definitions()["conc_strength"]
        assert d["label"] == "Strength" and d["definition"].startswith("The strength")
        assert specs_questions.refs_of(d)[0]["code"] == "ACI 318-19"


def test_screenshots_of_a_code_clause_are_added_shown_and_carried(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in)
    _explained(app)
    r = signed_in.post("/specs/questions/conc_strength/images", data={
        "set_id": str(set_id), "group": "concrete-mixes-and-properties", "code": "ACI 318-19",
        "clause": "19.2.1.1", "caption": "Table 19.2.1.1",
        "image": [(io.BytesIO(PNG), "shot.png"), (io.BytesIO(b"<svg onload=alert(1)>"), "x.svg")]},
        content_type="multipart/form-data")
    assert r.status_code == 302 and "explain=conc_strength" in r.headers["location"]
    with app.app_context():
        shots = specs_questions.images("conc_strength")
    assert len(shots) == 1 and shots[0]["mime"] == "image/png"
    got = signed_in.get(f"/specs/question-images/{shots[0]['id']}")
    assert got.data == PNG and got.mimetype == "image/png"
    panel = text(signed_in.get(f"/specs/sets/{set_id}/explain/conc_strength"))
    assert f"/specs/question-images/{shots[0]['id']}" in panel and "Table 19.2.1.1" in panel
    # An administrator adds a screenshot under any code's clause, or pastes one.
    assert "Add a screenshot" in panel and "data-paste-form" in panel
    # The same screenshot twice is kept once; the library file carries it.
    with app.app_context():
        assert specs_questions.add_image("conc_strength", PNG, "ACI 318-19", "19.2.1.1") == shots[0]["id"]
        data = specs_store.pack()
        from app.db import execute
        execute("DELETE FROM spec_question_images")
        specs_store.unpack(data, "update")
        assert [i["caption"] for i in specs_questions.images("conc_strength")] == ["Table 19.2.1.1"]
        image_id = specs_questions.images("conc_strength")[0]["id"]
    signed_in.post(f"/specs/questions/conc_strength/images/{image_id}/delete", data={"set_id": str(set_id)})
    with app.app_context():
        assert specs_questions.images("conc_strength") == []


def test_an_administrator_edits_the_explanation(app, signed_in):
    from app import specs_questions

    set_id = _project(app, signed_in)
    _explained(app)
    signed_in.post("/specs/questions/conc_strength/explain", data={
        "set_id": str(set_id), "definition": "Strength at 28 days.", "picture": "../../etc/passwd",
        "refs": "SBC 304-2018 | 19.2.1.1 | Strength | Same as ACI. | 16A\n\n | no code | x"})
    with app.app_context():
        d = specs_questions.definitions()["conc_strength"]
        assert d["definition"] == "Strength at 28 days." and d["picture"] == ""
        assert specs_questions.refs_of(d) == [{"code": "SBC 304-2018", "clause": "19.2.1.1",
                                              "title": "Strength", "says": "Same as ACI.",
                                              "kinds": ["16A"]}]
        assert specs_questions.drawing("../x") == ""


def test_a_kind_can_word_the_definition_its_own_way(app, signed_in):
    from app import specs_questions

    set_id = _project(app, signed_in)
    with app.app_context():
        specs_questions.save_definitions([{
            "key": "conc_strength", "label": "Strength", "definition": "Specified f'c at 28 days.",
            "definition_kinds": {"03a": "Strength class, cylinder/cube, as BS 8500."}}])
        d = specs_questions.definitions()["conc_strength"]
        assert specs_questions.definition_for(d, "03A").startswith("Strength class")
        assert specs_questions.definition_for(d, "15A") == "Specified f'c at 28 days."
    assert "Specified f&#39;c at 28 days." in text(signed_in.get(f"/specs/sets/{set_id}/explain/conc_strength"))
    signed_in.post("/specs/questions/conc_strength/explain", data={
        "set_id": str(set_id), "definition": "Only for 15A.", "kind": "15A", "only_kind": "1"})
    with app.app_context():
        d = specs_questions.definitions()["conc_strength"]
        assert d["definition"] == "Specified f'c at 28 days."
        assert specs_questions.definition_for(d, "15A") == "Only for 15A."
        assert specs_questions.definition_for(d, "03A").startswith("Strength class")


def test_the_drawings_are_safe_to_put_in_the_page():
    import xml.etree.ElementTree as ET

    from app import specs_questions

    names = specs_questions.drawings()
    assert len(names) >= 60
    for name in names:
        svg = specs_questions.drawing(name)
        assert svg.startswith("<svg") and "<script" not in svg.lower() and "href" not in svg.lower()
        assert not any(a.startswith("on") for el in ET.fromstring(svg).iter() for a in el.attrib)
