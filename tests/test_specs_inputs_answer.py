"""Answering from the inputs at a glance: the project's brief decided first,
then every station's questions answered or changed in the picture, its levels
opening in turn, each once everything before it is answered (a suggestion
counting once accepted); and the check's findings on the same works."""

from __future__ import annotations

import json
import re

from .test_specs import text
from .test_specs_questions import _project
from .test_specs_review import _person

FETCH = {"X-Requested-With": "fetch"}
SITE = {"suggest_shown": "1", "q_proj_site": "__free__", "t_proj_site": "Project site"}


def _scene(client, set_id):
    page = text(client.get(f"/specs/sets/{set_id}/inputs"))
    return json.loads(re.search(r'id="spec-scene-data">(.*?)</script>', page, re.S).group(1))


def _decided(client, set_id, **chosen):
    data = {"shown_opt": list(chosen)}
    data.update({f"opt_{k}": v for k, v in chosen.items()})
    return client.post(f"/specs/sets/{set_id}/inputs/decide", data=data, headers=FETCH).get_json()


def _answers(app, set_id):
    from app import specs_questions, specs_store

    with app.app_context():
        return specs_questions.answers_of(specs_store.spec_set(set_id))


def test_the_levels_open_in_turn_from_the_brief(app, signed_in):
    set_id = _project(app, signed_in)
    data = _scene(signed_in, set_id)
    assert [c["slug"] for c in data["chapters"]] == ["deciding", "the-project", "the-ingredients", "the-mix"]
    assert [c["level"] for c in data["chapters"]] == [1, 2, 3, 4]
    # Nothing is open before the brief is decided.
    assert data["open_stage"] == 0 and [c["locked"] for c in data["chapters"]] == [False, True, True, True]
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/office"))
    assert "Finish level 1, Deciding the project, first: decide what the project builds" in page
    # Decided, the project's level opens; the site's site is only suggested,
    # so the ones after it stay locked.
    answer = _decided(signed_in, set_id)
    assert answer["messages"][0]["kind"] == "success"
    data = answer["scene"]
    assert data["open_stage"] == 1 and [c["locked"] for c in data["chapters"]] == [False, False, True, True]
    stations = {s["id"]: s for s in data["stations"]}
    assert not stations["office"]["locked"] and stations["mixer"]["locked"] and stations["mixer"]["level"] == 4


def test_the_brief_draws_the_site(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/decide"))
    assert "Level 1: Deciding the project" in page and 'name="opt_structures"' in page and "Confirm the brief" in page
    answer = _decided(signed_in, set_id, structures="Marine structures", steel_framing="Yes", post_tensioning="Bonded",
                      cranes="Yes", rebar="Epoxy-coated")
    site = answer["scene"]["site"]
    assert site["marine"] and not site["building"] and site["steel"] and site["pt"] == "Bonded"
    assert site["cranes"] and site["rebar"] == ["Epoxy-coated"] and not site["precast"]
    with app.app_context():
        chosen = specs_store.chosen_for(specs_store.spec_set(set_id))
    assert chosen["structures"] == "Marine structures" and chosen["steel_framing"] == "Yes"
    # Saving the project's page decides it too.
    from .test_specs_kinds import set_id_of

    other = set_id_of(signed_in.post("/specs/sets", data={"name": "Quay", "family": "15A"}))
    with app.app_context():
        assert "_decided" not in json.loads(specs_store.spec_set(other)["options"] or "{}")
    signed_in.post(f"/specs/sets/{other}", data={"name": "Quay"})
    with app.app_context():
        assert json.loads(specs_store.spec_set(other)["options"])["_decided"] == "1"


def test_the_stages_open_in_turn(app, signed_in):
    set_id = _project(app, signed_in)
    _decided(signed_in, set_id)
    data = _scene(signed_in, set_id)
    # The project's site is only suggested, so its level is open and the
    # ones after it are locked.
    assert data["open_stage"] == 1
    assert [c["locked"] for c in data["chapters"]] == [False, False, True, True]
    stations = {s["id"]: s for s in data["stations"]}
    assert not stations["office"]["locked"] and stations["mixer"]["locked"] and stations["mixer"]["stage"] == 3


def test_a_station_is_answered_in_the_picture(app, signed_in):
    set_id = _project(app, signed_in)
    _decided(signed_in, set_id)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/office"))
    assert "Level 2: The project" in page and "Site office" in page
    assert 'name="accept_suggested"' in page and "Save site office" in page and "Locked." not in page
    # A suggestion left unaccepted is not written in, and the stage stays open.
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/office", data=SITE, headers=FETCH).get_json()
    assert "proj_site" not in _answers(app, set_id)
    assert any("not written in" in m["text"] for m in answer["messages"])
    assert answer["scene"]["open_stage"] == 1
    # Accepted, it counts: the next level opens.
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/office", data={**SITE, "accept_suggested": "1"},
                            headers=FETCH).get_json()
    assert _answers(app, set_id)["proj_site"] == "Project site"
    assert answer["messages"][0] == {"kind": "success", "text": "Saved 1 answer."}
    assert answer["scene"]["open_stage"] == 2
    assert not {s["id"]: s for s in answer["scene"]["stations"]}["admixtures"]["locked"]
    # Changed later from the picture, the answer is amended.
    signed_in.post(f"/specs/sets/{set_id}/inputs/office", data={"q_proj_site": "__free__", "t_proj_site": "Jeddah"},
                   headers=FETCH)
    assert _answers(app, set_id)["proj_site"] == "Jeddah"


def test_a_locked_stage_is_not_answered_until_the_one_before_is(app, signed_in):
    set_id = _project(app, signed_in)
    _decided(signed_in, set_id)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/mixer"))
    assert "Locked." in page and "Finish level 2, The project, first: 1 question" in page
    assert 'data-go-stage="office"' in page and "<fieldset class=\"spec-scene-fields\" disabled>" in page
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/mixer", data={"q_conc_strength": "45MPa"},
                            headers=FETCH).get_json()
    assert answer["messages"][0]["kind"] == "error" and "locked" in answer["messages"][0]["text"]
    assert "conc_strength" not in _answers(app, set_id)
    # Without scripts the form goes back to the page, with the same refusal.
    back = signed_in.post(f"/specs/sets/{set_id}/inputs/mixer", data={"q_conc_strength": "45MPa"})
    assert back.status_code == 302 and back.headers["Location"].endswith("/inputs#st-mixer")
    assert "conc_strength" not in _answers(app, set_id)


def test_only_the_people_who_change_it_answer_there(app, signed_in):
    set_id = _project(app, signed_in)
    _decided(signed_in, set_id)
    omar = _person(app, signed_in, "Omar")
    assert "Confirm the brief" not in text(omar.get(f"/specs/sets/{set_id}/inputs/decide"))
    page = text(omar.get(f"/specs/sets/{set_id}/inputs/office"))
    assert "You can read this specification" in page and "Save site office" not in page
    omar.post(f"/specs/sets/{set_id}/inputs/office", data={**SITE, "accept_suggested": "1"}, headers=FETCH)
    assert "proj_site" not in _answers(app, set_id)


def test_a_station_not_in_this_project_is_not_found(app, signed_in):
    set_id = _project(app, signed_in)
    assert signed_in.get(f"/specs/sets/{set_id}/inputs/bridge").status_code == 404
    assert signed_in.get(f"/specs/sets/{set_id}/inputs/nowhere").status_code == 404


def test_the_check_pins_its_findings_on_the_works(app, signed_in):
    from app import specs_inputs

    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert 'data-mode="checks"' in page and "Walk the findings" in page
    data = json.loads(re.search(r'id="spec-scene-data">(.*?)</script>', page, re.S).group(1))
    found = data["flags"]
    assert found["total"] == sum(len(v) for v in found["stations"].values())
    for station, items in found["stations"].items():
        assert station in found["names"]
        assert all(i["url"].startswith("#item-") or i["url"] == "#language" for i in items)
    # A section's findings stand where its questions do, else by its number.
    known = {"033000": "mixer"}
    assert specs_inputs.station_of_section("033000", known) == "mixer"
    assert specs_inputs.station_of_section("031000", {}) == "formwork"
    assert specs_inputs.station_of_section("032000", {}) == "rebar"
    assert specs_inputs.station_of_section("033819", {}) == "tendons"
    assert specs_inputs.station_of_section("034100", {}) == "precast"
    assert specs_inputs.station_of_section("051200", {}) == "frame"
    assert specs_inputs.station_of_section("071326", {}) == "membrane"
    assert specs_inputs.station_of_section("E20", {}) == "formwork"
