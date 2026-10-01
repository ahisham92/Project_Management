"""The master's questions: asked once per project, each answer written into
every clause it belongs to, per element where the master asks it that way."""

from __future__ import annotations

import io
import json

from app import specs
from .test_specs import text
from .test_specs_kinds import set_id_of

MASTER = """# PRODUCTS
## CONCRETE MIXTURES
- Class A {{conc_designation@foundations|<insert designation>}}: Normal-weight concrete used for foundations{{conc_class_a_piling|[, piling]}}, grade beams, and tie beams.
-- Minimum Compressive Strength: {{conc_strength@foundations|[45MPa] [40MPa] [35MPa] <Insert strength>}}.
-- Maximum w/cm: {{conc_max_wcm@foundations|[0.35] [0.40] <Insert number>}}.
- Class B {{conc_designation@basement_walls|<insert designation>}}: Normal-weight concrete used for basement walls.
-- Minimum Compressive Strength: {{conc_strength@basement_walls|[45MPa] [40MPa] [35MPa] <Insert strength>}}.
## MEETINGS
- Conduct conference at {{proj_site|[Project site] <Insert location>}}.
- Admixtures: {{conc_admixtures|[water-reducing] [retarding] [air-entraining]}}.
"""

QUESTIONS = [
    {"key": "conc_strength", "label": "Minimum compressive strength at 28 days",
     "group": "Concrete mixes and properties", "suggested": "40MPa", "per_element": True, "order": 10},
    {"key": "conc_max_wcm", "label": "Maximum water/cementitious ratio",
     "group": "Concrete mixes and properties", "suggested": "0.40", "per_element": True, "order": 20},
    {"key": "conc_designation", "label": "Class designation", "group": "Concrete mixes and properties",
     "suggested": None, "per_element": True, "order": 5},
    {"key": "conc_class_a_piling", "label": "Does Class A concrete also cover piling?",
     "group": "Concrete mixes and properties", "optional": True, "order": 6},
    {"key": "conc_admixtures", "label": "Admixtures", "group": "Concrete materials", "many": True},
    {"key": "proj_site", "label": "Where the project site is", "group": "Project information",
     "suggested": "Project site"},
]


def _project(app, signed_in, elements=""):
    from app import specs_questions, specs_store

    with app.app_context():
        section_id = specs_store.save_section("033000", "CAST-IN-PLACE CONCRETE",
                                              specs.align([], specs.from_text(MASTER)), family="15A")
        specs_questions.save_definitions(QUESTIONS)
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Tower", "family": "15A"}))
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    if elements:
        with app.app_context():
            row = specs_store.spec_set(set_id)
            chosen = json.loads(row["options"] or "{}")
            chosen["elements"] = elements
            from app.db import execute
            execute("UPDATE spec_sets SET options = ? WHERE id = ?", (json.dumps(chosen), set_id))
    return set_id


def _body(app, set_id):
    from app import specs_store

    with app.app_context():
        row = specs_store.spec_set(set_id)
        s = specs_store.set_sections(set_id)[0]
        values = specs_store.values_for(row)
        return [specs.fill(n["text"], values) for n in specs.loads(s["body"])]


def test_fill_keeps_the_master_words_until_answered():
    t = "Strength: {{conc_strength@foundations|[45MPa] [40MPa]}} at {{proj_site|[Project site]}}{{x|[, piling]}}."
    assert specs.fill(t, {}) == "Strength: [45MPa] [40MPa] at [Project site][, piling]."
    assert specs.fill(t, {"conc_strength": "40MPa", "proj_site": "Jeddah", "x": ""}) == \
        "Strength: 40MPa at Jeddah."
    assert specs.fill(t, {"conc_strength": "40MPa", "conc_strength@foundations": "45MPa"}).startswith(
        "Strength: 45MPa")
    assert specs.unfilled([{"text": t + " {{engineer}}"}], {}) == ["engineer"]


def test_the_questions_come_from_the_sections_with_their_choices(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in)
    with app.app_context():
        row = specs_store.spec_set(set_id)
        asked = {q["key"]: q for q in specs_questions.asked(
            specs_store.set_sections(set_id), specs_store.chosen_for(row), row)}
    strength = asked["conc_strength"]
    assert strength["choices"] == ["45MPa", "40MPa", "35MPa"] and strength["free"] == ["Insert strength"]
    assert strength["rows"] == ["foundations", "basement_walls"] and strength["suggested"] == "40MPa"
    assert asked["conc_class_a_piling"]["optional"] and asked["conc_class_a_piling"]["single_choice_optional"]
    page = text(signed_in.get(f"/specs/sets/{set_id}/details"))
    # The first chapter with anything open comes first: the project.
    assert "Where the project site is" in page and "suggested" in page
    assert "The mix" in page


def test_answers_fill_every_clause_and_can_differ_per_element(app, signed_in):
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties"))
    assert "Different for some elements" in page and "Basement walls" in page
    answer = signed_in.post(f"/specs/sets/{set_id}/details", data={
        "group": "concrete-mixes-and-properties", "go": "stay",
        "q_conc_strength": "40MPa", "split_conc_strength": "1",
        "q_conc_strength@foundations": "__same__",
        "q_conc_strength@basement_walls": "__free__", "t_conc_strength@basement_walls": "50MPa",
        "q_conc_max_wcm": "0.40", "split_conc_max_wcm": "0",
        "q_conc_designation": "__free__", "t_conc_designation": "C1",
        "q_conc_class_a_piling": "__none__"}, follow_redirects=True)
    assert "Saved" in text(answer)
    body = _body(app, set_id)
    assert "Minimum Compressive Strength: 40MPa." in body            # foundations: same as all
    assert body.count("Minimum Compressive Strength: 50MPa.") == 1   # basement walls: its own
    assert "Maximum w/cm: 0.40." in body
    assert "Class A C1: Normal-weight concrete used for foundations, grade beams, and tie beams." in body


def test_several_answers_and_the_project_information(app, signed_in):
    set_id = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}/details", data={
        "group": "concrete-materials", "go": "stay",
        "q_conc_admixtures": ["water-reducing", "retarding"]})
    signed_in.post(f"/specs/sets/{set_id}/details", data={
        "group": "project-information", "go": "stay",
        "q_proj_site": "__free__", "t_proj_site": "the King Abdullah Port site"})
    body = _body(app, set_id)
    assert "Admixtures: water-reducing and retarding." in body
    assert "Conduct conference at the King Abdullah Port site." in body
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=project-information"))
    assert 'value="the King Abdullah Port site"' in page


def test_only_the_project_elements_get_a_row(app, signed_in):
    set_id = _project(app, signed_in, elements="Foundations")
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties"))
    assert 'name="q_conc_strength@foundations"' in page
    assert 'name="q_conc_strength@basement_walls"' not in page


def test_the_library_file_carries_the_questions(app, signed_in):
    from app import specs_questions, specs_store

    _project(app, signed_in)
    with app.app_context():
        data = specs_store.pack()
        from app.db import execute
        execute("DELETE FROM spec_questions")
        specs_store.unpack(data, "update")
        assert specs_questions.definitions()["conc_strength"]["per_element"] == 1
    assert io.BytesIO(data).read(2) == b"PK"


def test_the_project_page_leads_to_the_story_and_keeps_the_location(app, signed_in):
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    # The questions are answered on the story; Details stays as its list view.
    assert "<strong>The story</strong>" in page and "0 of 6 answered" in page
    assert f'href="/specs/sets/{set_id}/story">Next: the story (6 to answer)' in page
    assert f'href="/specs/sets/{set_id}/details"' in page and "List view" in page
    assert f'href="/specs/sets/{set_id}/story#level-1"' in page
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "proj_location": " Jeddah,  KSA "})
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    # An older project's one-line location reads as its city and country.
    assert 'name="city" value="Jeddah"' in page and 'name="country" value="KSA"' in page


def test_optional_words_are_a_yes_or_no_that_keeps_each_place_its_own(app, signed_in):
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties"))
    assert "Does Class A concrete also cover piling?" in page and "Yes keeps the words “piling”" in page
    signed_in.post(f"/specs/sets/{set_id}/details", data={
        "group": "concrete-mixes-and-properties", "go": "stay", "q_conc_class_a_piling": "__keep__"})
    assert "Normal-weight concrete used for foundations, piling, grade beams, and tie beams." in \
        " ".join(_body(app, set_id))


def test_a_project_with_no_elements_named_keeps_every_element_paragraph():
    assert specs.applies("elements=Slab on grade", {})
    assert not specs.applies("elements=Slab on grade", {"elements": "Piles"})
    assert specs.applies("elements=Slab on grade|Deck", {"elements": "Piles|Deck"})


def test_the_master_switches_are_asked_with_the_details(app, signed_in):
    from app import specs_store
    from app.db import execute

    with app.app_context():
        execute("INSERT INTO spec_options (key, label, choices, default_value, grp, kind, position) "
                "VALUES ('vapor_retarder', 'Is there a vapour retarder under slabs on grade?', 'No|Yes', "
                "'No', 'Placing, finishing and curing', 'one', 99)")
        section_id = specs_store.save_section("033001", "SLABS", specs.align([], specs.from_text(
            "# EXECUTION\n## SLABS\n- {if vapor_retarder=Yes} Lap the vapour retarder 150 mm.\n"
            "- Cure for {{conc_curing_days|[7] [10] <Insert number>}} days.\n")), family="15A")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Mall", "family": "15A"}))
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=placing-finishing-and-curing"))
    assert "Is there a vapour retarder under slabs on grade?" in page
    assert "Decides which paragraphs of the sections are issued." in page
    signed_in.post(f"/specs/sets/{set_id}/details", data={
        "group": "placing-finishing-and-curing", "go": "stay", "q_vapor_retarder": "Yes"})
    # A question the library does not describe is still asked, under "Other details".
    signed_in.post(f"/specs/sets/{set_id}/details", data={
        "group": "other-details", "go": "stay", "q_conc_curing_days": "7"})
    body = _body(app, set_id)
    with app.app_context():
        chosen = specs_store.chosen_for(specs_store.spec_set(set_id))
        nodes = specs.loads(specs_store.set_sections(set_id)[0]["body"])
        issued = [n["text"] for n in specs.number(nodes, chosen) if n["included"]]
    assert chosen["vapor_retarder"] == "Yes" and "Lap the vapour retarder 150 mm." in issued
    assert "Cure for 7 days." in body
