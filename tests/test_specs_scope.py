"""Questions and their choices only for what a project builds: a quay is not
asked about high towers, roofs or hollow-core floors, a building is not asked
about marine cover, and the words of a question say "structure" where there is
no building."""

from __future__ import annotations

import json

from app import specs

from .test_specs_kinds import set_id_of

BODY = """# GENERAL
## MONITORING
- Measure settlements under the foundations {{monitor_scope|[of tall towers] [of bridge piers] [of quay walls] <insert description>}}.
- Monitor corrosion of {{monitor_corrosion|[the splash zone] [bridge decks]}}.
## COVER
- Cover to concrete exposed to marine conditions shall be {{rebar_cover_marine|[75] [100]}} mm.
- Cover to interior protected faces shall be {{rebar_cover_interior|[30] [40]}} mm.
- Curing compound {{conc_no_bond|[that does not stop floor finishes bonding]}}.
- Hollow-core slabs: {{precast_hc_depth|[200 mm] [250 mm]}} deep.
"""
WHEN = {"interior protected": "structures=Buildings|Bridges",
        "marine conditions": "structures=Marine structures;exposure=Marine",
        "Hollow-core": "precast_hollowcore=Yes"}
QUESTIONS = [
    {"key": "monitor_scope", "label": "What the monitoring covers", "grp": "Demolition, shoring and monitoring",
     "many": True, "suggested": "of tall towers and of quay walls",
     "choice_when": [{"choice": "tall towers", "when": "structures=Buildings"},
                     {"choice": "bridge piers", "when": "structures=Bridges"},
                     {"choice": "quay walls", "when": "structures=Marine structures"}]},
    {"key": "monitor_corrosion", "label": "Where corrosion of the building is monitored",
     "grp": "Demolition, shoring and monitoring", "suggested": "bridge decks",
     "choice_when": [{"choice": "splash zone", "when": "structures=Bridges|Marine structures;exposure=Marine"},
                     {"choice": "bridge decks", "when": "structures=Bridges"}]},
    {"key": "rebar_cover_marine", "label": "Marine cover, mm", "grp": "Reinforcement"},
    {"key": "rebar_cover_interior", "label": "Interior cover, mm", "grp": "Reinforcement"},
    {"key": "conc_no_bond", "label": "Must curing compounds keep floor coverings bonding?", "grp": "Placing, finishing and curing",
     "optional": True, "choice_when": [{"choice": "*", "when": "structures=Buildings"}]},
    {"key": "precast_hc_depth", "label": "Hollow-core slab depth", "grp": "Post-tensioning and precast"},
]


def _hollowcore(app):
    """The library's switch for hollow-core floors (the seed has none)."""
    from app.db import execute

    with app.app_context():
        execute("INSERT OR IGNORE INTO spec_options (key, label, choices, default_value, grp, kind, position) "
                "VALUES ('precast_hollowcore', 'Hollow-core slabs?', 'No|Yes', 'Yes', "
                "'Post-tensioning and precast', 'one', 90)")


def _project(app, signed_in, **brief):
    from app import specs_questions, specs_store
    from app.db import execute

    _hollowcore(app)
    with app.app_context():
        nodes = specs.align([], specs.from_text(BODY))
        for n in nodes:
            n["when"] = next((w for words, w in WHEN.items() if words in n["text"]), "")
        have = specs_store.section_by_number("013510", "15A")
        section_id = have["id"] if have else specs_store.save_section("013510", "STRUCTURAL MONITORING", nodes,
                                                                      family="15A")
        specs_questions.save_definitions(QUESTIONS)
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Works", "family": "15A"}))
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    with app.app_context():
        row = specs_store.spec_set(set_id)
        chosen = json.loads(row["options"] or "{}")
        chosen.update(brief)
        execute("UPDATE spec_sets SET options = ? WHERE id = ?", (json.dumps(chosen), set_id))
    return set_id


def _asked(app, set_id):
    from app import specs_questions, specs_store

    with app.app_context():
        row = specs_store.spec_set(set_id)
        qs = specs_questions.asked(specs_store.set_sections(set_id), specs_store.chosen_for(row), row)
        return {q["key"]: q for q in qs}


def test_alternatives_in_a_condition():
    when = "structures=Marine structures;exposure=Marine&climate=Hot"
    assert specs.applies(when, {"structures": "Buildings|Marine structures"})
    assert specs.applies(when, {"structures": "Buildings", "exposure": "Marine", "climate": "Hot"})
    assert not specs.applies(when, {"structures": "Buildings", "exposure": "Marine", "climate": "Cold"})
    assert not specs.applies(when, {"structures": "Bridges", "exposure": "General"})
    assert specs.condition_parts("a=1;b=2&c!=3") == ["a=1", "b=2", "c!=3"]
    assert specs.keys_used([{"when": "a=1;b=2&c!=3", "text": ""}]) == {"a", "b", "c"}


def test_the_brief_asks_building_precast_only_of_a_building(app):
    from app import specs_inputs, specs_store

    _hollowcore(app)
    quay = {"structures": "Marine structures", "precast": "Plant precast"}
    assert specs_inputs.brief_applies("precast_delegated_design", quay)
    for key in ("precast_hollowcore", "precast_double_tee", "precast_thin_brick", "precast_stone_facing",
                "precast_insulated_panels", "precast_stadia"):
        assert not specs_inputs.brief_applies(key, quay), key
        assert specs_inputs.brief_applies(key, {**quay, "structures": "Buildings|Marine structures"}), key
    assert not specs_inputs.brief_applies("pt_transfer_girders", {"structures": "Bridges", "post_tensioning": "Bonded"})
    assert not specs_inputs.brief_applies("thermal_break", {"structures": "Marine structures"})
    # Either of two: duct inhibitor with post-tensioning, or a bridge's prestressed girders.
    assert specs_inputs.brief_applies("pt_vapor_inhibitor", {"post_tensioning": "Bonded"})
    assert specs_inputs.brief_applies("pt_vapor_inhibitor", {"structures": "Bridges", "post_tensioning": "None",
                                                             "bridge_items": "Prestressed girders"})
    assert not specs_inputs.brief_applies("pt_vapor_inhibitor", {"structures": "Buildings", "post_tensioning": "None"})
    assert {"structures", "precast", "post_tensioning", "bridge_items"} <= specs_inputs.BRIEF_GATES
    # What is not asked is off for the text: hollow-core "No" on a quay, the
    # fenders "None" on a building, a decision with neither not answered.
    with app.app_context():
        opts = specs_store.options()
        on_quay = specs_inputs.scoped({**specs_store.chosen_for(None, scope=False), **quay}, opts)
        assert on_quay["precast_hollowcore"] == "No" and on_quay["fenders"] == "Cone"
        on_building = specs_inputs.scoped({**specs_store.chosen_for(None, scope=False), "structures": "Buildings",
                                           "steel_framing": "No"}, opts)
        assert on_building["fenders"] == "None" and on_building["ladders"] == "No"
        assert "steel_protection" not in on_building


def test_a_quay_is_asked_only_what_a_quay_has(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in, structures="Marine structures", precast="Plant precast",
                      precast_hollowcore="Yes")
    asked = _asked(app, set_id)
    # Hollow-core floors were left at Yes, but a quay's brief does not ask it.
    assert "precast_hc_depth" not in asked
    assert "rebar_cover_marine" in asked and "rebar_cover_interior" not in asked
    assert "conc_no_bond" not in asked
    assert asked["monitor_scope"]["choices"] == ["of quay walls"]
    # The suggestion keeps only what is offered; one with nothing left is none.
    assert asked["monitor_scope"]["suggested"] == "of quay walls"
    assert asked["monitor_corrosion"]["choices"] == ["the splash zone"]
    assert asked["monitor_corrosion"]["suggested"] is None
    # No building: the question says "structure".
    assert asked["monitor_corrosion"]["label"] == "Where corrosion of the structure is monitored"
    # Optional words a quay does not have are left out of its text.
    with app.app_context():
        row = specs_store.spec_set(set_id)
        assert specs_questions.values(row)["conc_no_bond"] == ""
        text = " ".join(specs.fill(n["text"], specs_store.values_for(row))
                        for n in specs.loads(specs_store.set_sections(set_id)[0]["body"]))
        assert "floor finishes" not in text


def test_a_building_keeps_its_own_and_not_the_sea(app, signed_in):
    set_id = _project(app, signed_in, structures="Buildings", exposure="General", precast="Plant precast",
                      precast_hollowcore="Yes")
    asked = _asked(app, set_id)
    assert "precast_hc_depth" in asked and "rebar_cover_interior" in asked and "conc_no_bond" in asked
    assert "rebar_cover_marine" not in asked
    assert asked["monitor_scope"]["choices"] == ["of tall towers"]
    assert asked["monitor_scope"]["suggested"] == "of tall towers"
    # A question whose every choice is for other works keeps them: it is never
    # left with nothing to answer.
    assert asked["monitor_corrosion"]["choices"] == ["the splash zone", "bridge decks"]
    assert asked["monitor_corrosion"]["label"] == "Where corrosion of the building is monitored"
    # A building by the sea is asked about marine cover and the splash zone.
    set_id = _project(app, signed_in, structures="Buildings", exposure="Marine")
    asked = _asked(app, set_id)
    assert "rebar_cover_marine" in asked
    assert asked["monitor_corrosion"]["choices"] == ["the splash zone"]


def test_a_mixed_project_is_offered_both(app, signed_in):
    set_id = _project(app, signed_in, structures="Buildings|Marine structures")
    asked = _asked(app, set_id)
    assert asked["monitor_scope"]["choices"] == ["of tall towers", "of quay walls"]
    assert "rebar_cover_marine" in asked and "rebar_cover_interior" in asked
    assert asked["monitor_corrosion"]["label"] == "Where corrosion of the building is monitored"


def test_choices_for_some_works_travel_with_the_library(app):
    from app import specs_questions

    with app.app_context():
        specs_questions.save_definitions(QUESTIONS)
        packed = {q["key"]: q for q in specs_questions.packed()}
        assert packed["monitor_scope"]["choice_when"][0] == {"choice": "tall towers", "when": "structures=Buildings"}
        assert packed["rebar_cover_marine"]["choice_when"] == []
        # A file without them leaves the ones here alone.
        specs_questions.save_definitions([{"key": "monitor_scope", "label": "Monitoring"}])
        assert specs_questions.definitions()["monitor_scope"]["label"] == "Monitoring"
        assert len(json.loads(specs_questions.definitions()["monitor_scope"]["choice_when"])) == 3
    assert specs_questions.clean_choice_when('[{"choice": " a  b ", "when": "x=1"}, {"choice": "c"}, 3]') == \
        [{"choice": "a b", "when": "x=1"}]
    assert specs_questions.structure_for_building("The Building, its BUILDINGS and the building code") == \
        "The Structure, its STRUCTURES and the building code"


def test_the_brief_page_carries_the_rules(app, signed_in):
    from .test_specs import text

    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/decide"))
    import re
    hollow = re.search(r'data-opt="precast_hollowcore"[^>]*>', page).group(0)
    rule = json.loads(re.search(r"data-when='([^']*)'", hollow).group(1))
    assert rule == [[["precast", "some", ""], ["structures", "has", "Buildings"]]]
    fenders = re.search(r'data-opt="fenders"[^>]*>', page).group(0)
    assert json.loads(re.search(r"data-when='([^']*)'", fenders).group(1)) == [[["structures", "has", "Marine structures"]]]


def test_a_quay_is_not_suggested_or_told_about_towers(app, signed_in):
    from app import specs_questions, specs_store

    with app.app_context():
        specs_questions.save_definitions([
            {"key": "monitor_where", "label": "Where it is watched", "grp": "Demolition, shoring and monitoring",
             "suggested": "at the top of the tallest tower",
             "help": "Where it is watched, such as at the top of the tallest tower, a long joint or a tall bridge pier."},
            {"key": "monitor_corrosion", "label": "Where corrosion is monitored",
             "grp": "Demolition, shoring and monitoring", "suggested": "the splash zone"}])
    set_id = _project(app, signed_in, structures="Marine structures")
    asked = _asked(app, set_id)
    # No tag on the choice, but the suggestion names a tower: none is offered.
    assert asked["monitor_scope"]["suggested"] == "of quay walls"
    with app.app_context():
        specs_questions.save_definitions([{**QUESTIONS[0], "key": "monitor_scope",
                                           "suggested": "of the tallest tower", "choice_when": []}])
    asked = _asked(app, set_id)
    assert asked["monitor_scope"]["suggested"] is None
    assert "of tall towers" not in asked["monitor_scope"]["choices"]
    # An answer given before, which names a tower, is asked again.
    with app.app_context():
        specs_questions.save_answers(set_id, {"monitor_scope": "of the tallest tower",
                                              "monitor_corrosion": "the splash zone"}, {})
    asked = _asked(app, set_id)
    assert asked["monitor_scope"]["answered"] is False
    assert asked["monitor_scope"]["off_scope"] == "of the tallest tower"
    assert asked["monitor_corrosion"]["answered"] is True
    # Words the engineer typed are theirs: a port's control tower stays.
    with app.app_context():
        specs_questions.save_answers(set_id, {"monitor_scope": "of the port control tower"}, {})
    assert _asked(app, set_id)["monitor_scope"]["answered"] is True
    with app.app_context():
        specs_questions.save_answers(set_id, {"monitor_scope": "of the tallest tower"}, {})
    from app import specs_inputs
    station = next(specs_inputs.station_of(q, c["slug"]) for c in specs_questions.story(list(asked.values()))
                   for q in c["questions"] if q["key"] == "monitor_scope")
    card = signed_in.get(f"/specs/sets/{set_id}/inputs/{station}?cards=1").get_data(as_text=True)
    assert "Answer again" in card and "of the tallest tower" in card
    # A building keeps the same answer.
    building = _project(app, signed_in, structures="Buildings")
    with app.app_context():
        specs_questions.save_answers(building, {"monitor_scope": "of the tallest tower"}, {})
    assert _asked(app, building)["monitor_scope"]["answered"] is True


def test_examples_follow_what_is_built():
    from app import specs_questions as sq

    text = "Where it is watched, such as at the top of the tallest tower, a long joint or a tall bridge pier."
    quay = sq.off_scope({"structures": "Marine structures"})
    assert sq.scope_examples(text, quay) == "Where it is watched, such as a long joint."
    assert sq.scope_examples("Watch it, such as the tallest tower or a tall bridge pier.", quay) == "Watch it."
    assert sq.scope_examples(text, sq.off_scope({"structures": "Buildings|Bridges"})) == text
    # Nothing said yet about what is built: nothing is taken out.
    assert sq.off_scope({}) is None and sq.scope_examples(text, None) == text
    # A building by the sea keeps its quays; one inland does not.
    assert not sq.off_scope({"structures": "Buildings", "exposure": "Marine"}).search("the quay wall")
    assert sq.off_scope({"structures": "Buildings"}).search("the quay wall")
    # Tower cranes and shoring towers are not towers to be built.
    for words in ("the tower crane base", "vertical towers of the falsework", "shoring towers"):
        assert not quay.search(words), words
    # Untagged choices naming other works are left out when others remain.
    assert sq.offered(["at tall towers", "at the deck"], [], {"structures": "Marine structures"}, quay) == \
        ["at the deck"]
