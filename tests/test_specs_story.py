"""The questions told as the story of the build, and the project's inputs at a
glance before it is issued: each answer on a station of the works, with the
words of the specification it goes into."""

from __future__ import annotations

import json
import re

from .test_specs import text
from .test_specs_questions import _project


def _asked(app, set_id):
    from app import specs_questions, specs_store

    with app.app_context():
        row = specs_store.spec_set(set_id)
        return specs_questions.asked(specs_store.set_sections(set_id), specs_store.chosen_for(row), row)


def test_the_questions_are_told_in_the_order_the_project_is_built(app, signed_in):
    from app import specs_questions

    set_id = _project(app, signed_in)
    chapters = specs_questions.story(_asked(app, set_id))
    assert [c["name"] for c in chapters] == ["The project", "The ingredients", "The mix"]
    assert [c["number"] for c in chapters] == [1, 2, 3]
    assert chapters[2]["groups"] == ["Concrete mixes and properties"]
    assert {q["key"] for q in chapters[2]["questions"]} >= {"conc_strength", "conc_designation"}
    # Every chapter is a whole group, in the order of the build.
    order = [g for c in specs_questions.STORY for g in c[3]]
    assert sorted(order) == sorted(specs_questions.GROUPS + [specs_questions.OTHER])
    assert order.index("Concrete materials") < order.index("Concrete mixes and properties") < \
        order.index("Placing, finishing and curing") < order.index("Quality, testing and inspection")


def test_details_walks_the_chapters_and_still_shows_the_groups(app, signed_in):
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/details"))
    assert "Chapter 1: The project" in page and "chapter 1 of 3" in page
    assert "Save and next: The ingredients" in page and "Show by group" in page
    # A group named the old way opens its chapter, and saves there.
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties"))
    assert "Chapter 3: The mix" in page and "Different for some elements" in page
    signed_in.post(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties",
                   data={"q_conc_strength": "45MPa", "split_conc_strength": "0"})
    from app import specs_questions, specs_store
    with app.app_context():
        assert specs_questions.answers_of(specs_store.spec_set(set_id))["conc_strength"] == "45MPa"
    # By group, as before.
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?by=group"))
    assert "Project information" in page and "group 1 of 3" in page and "Tell it as a story" in page
    assert 'name="by" value="group"' in page


def test_a_question_left_off_the_form_keeps_its_answers_per_element(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in)
    url = f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties"
    signed_in.post(url, data={"split_conc_strength": "1", "q_conc_strength@foundations": "45MPa",
                              "q_conc_strength@basement_walls": "35MPa"})
    signed_in.post(url, data={"q_conc_max_wcm": "0.40"})
    with app.app_context():
        answers = specs_questions.answers_of(specs_store.spec_set(set_id))
    assert answers["conc_strength@foundations"] == "45MPa" and answers["conc_max_wcm"] == "0.40"
    assert "conc_strength" in specs_questions.split_keys(answers)


def test_the_inputs_page_puts_each_answer_on_its_station(app, signed_in):
    set_id = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties",
                   data={"q_conc_strength": "45MPa", "split_conc_strength": "0"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs"))
    assert "The inputs at a glance" in page and "Play the story" in page
    data = json.loads(re.search(r'id="spec-scene-data">(.*?)</script>', page, re.S).group(1))
    stations = {s["id"]: s for s in data["stations"]}
    assert set(stations) == {"decide", "office", "admixtures", "mixer"}
    strength = next(q for q in stations["mixer"]["questions"] if q["key"] == "conc_strength")
    assert strength["state"] == "answered" and strength["value"] == "45MPa"
    assert strength["places"][0]["url"].endswith("#p-" + strength["places"][0]["url"].split("#p-")[1])
    assert "45MPa" in strength["places"][0]["words"]
    designation = next(q for q in stations["mixer"]["questions"] if q["key"] == "conc_designation")
    assert designation["state"] == "needed"
    site = stations["office"]["questions"][0]
    assert site["state"] == "suggested" and site["value"] == "Project site"
    # The mix as a table of the elements.
    assert {"conc_strength", "conc_designation"} <= {c["key"] for c in data["mix"]["columns"]}
    assert {r["element"] for r in data["mix"]["rows"]} == {"Foundations", "Basement walls"}
    assert data["totals"]["answered"] == 1 and data["count"] == sum(len(s["questions"]) for s in data["stations"])
    # The brief comes first: what the project builds, decided before any question.
    assert data["chapters"][0]["slug"] == "deciding" and stations["decide"]["needed"] == 1
    assert data["site"]["building"] and not data["site"]["marine"]
    # The plain summary carries the same.
    assert "Level 4: The mix" in page and "Each element&#39;s concrete" in page or "Each element's concrete" in page
    assert "Needs your answer" in page


def test_the_ingredients_stand_where_they_go_in():
    from app import specs_inputs

    def at(key, label):
        return specs_inputs.station_of({"key": key, "label": label}, "the-ingredients")
    assert at("conc_cement_type", "Portland cement type") == "cement"
    assert at("conc_arch_fine_aggregate", "Fine aggregate standard") == "sand"
    assert at("conc_max_aggregate", "Nominal maximum coarse aggregate size") == "gravel"
    assert at("conc_water_bs_en1008", "Also accept mixing water to BS EN 1008?") == "water"
    assert at("conc_admixtures", "Admixtures") == "admixtures"
    assert at("conc_steel_fibre_length", "Minimum steel fibre length") == "admixtures"
    assert at("conc_joint_filler_strips", "Expansion joint-filler strips") == "store"
    assert specs_inputs.station_of({"key": "x", "label": "x"}, "the-pour") == "pour"


def test_a_project_with_nothing_asked_starts_at_its_brief(app, signed_in):
    from .test_specs_kinds import set_id_of

    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Empty", "family": "15A"}))
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs"))
    # Only the brief: what the project builds is decided before any question.
    data = json.loads(re.search(r'id="spec-scene-data">(.*?)</script>', page, re.S).group(1))
    assert [s["id"] for s in data["stations"]] == ["decide"] and data["count"] == 0
