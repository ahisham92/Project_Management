"""Answering from the inputs at a glance: every station's questions are
answered or changed in the picture, and its stages open in turn, each once
everything before it is answered (a suggestion counting once accepted)."""

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


def _answers(app, set_id):
    from app import specs_questions, specs_store

    with app.app_context():
        return specs_questions.answers_of(specs_store.spec_set(set_id))


def test_the_stages_open_in_turn(app, signed_in):
    set_id = _project(app, signed_in)
    data = _scene(signed_in, set_id)
    assert [c["slug"] for c in data["chapters"]] == ["the-project", "the-ingredients", "the-mix"]
    # The project's site is only suggested, so the first stage is still open
    # and the ones after it are locked.
    assert data["open_stage"] == 0
    assert [c["locked"] for c in data["chapters"]] == [False, True, True]
    stations = {s["id"]: s for s in data["stations"]}
    assert not stations["office"]["locked"] and stations["mixer"]["locked"] and stations["mixer"]["stage"] == 2


def test_a_station_is_answered_in_the_picture(app, signed_in):
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/office"))
    assert "Chapter 1: The project" in page and "Site office" in page
    assert 'name="accept_suggested"' in page and "Save site office" in page and "Locked." not in page
    # A suggestion left unaccepted is not written in, and the stage stays open.
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/office", data=SITE, headers=FETCH).get_json()
    assert "proj_site" not in _answers(app, set_id)
    assert any("not written in" in m["text"] for m in answer["messages"])
    assert answer["scene"]["open_stage"] == 0
    # Accepted, it counts: the next stage opens.
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/office", data={**SITE, "accept_suggested": "1"},
                            headers=FETCH).get_json()
    assert _answers(app, set_id)["proj_site"] == "Project site"
    assert answer["messages"][0] == {"kind": "success", "text": "Saved 1 answer."}
    assert answer["scene"]["open_stage"] == 1
    assert not {s["id"]: s for s in answer["scene"]["stations"]}["admixtures"]["locked"]
    # Changed later from the picture, the answer is amended.
    signed_in.post(f"/specs/sets/{set_id}/inputs/office", data={"q_proj_site": "__free__", "t_proj_site": "Jeddah"},
                   headers=FETCH)
    assert _answers(app, set_id)["proj_site"] == "Jeddah"


def test_a_locked_stage_is_not_answered_until_the_one_before_is(app, signed_in):
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/mixer"))
    assert "Locked." in page and "Finish chapter 1, The project, first: 1 question" in page
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
    omar = _person(app, signed_in, "Omar")
    page = text(omar.get(f"/specs/sets/{set_id}/inputs/office"))
    assert "You can read this specification" in page and "Save site office" not in page
    omar.post(f"/specs/sets/{set_id}/inputs/office", data={**SITE, "accept_suggested": "1"}, headers=FETCH)
    assert "proj_site" not in _answers(app, set_id)


def test_a_station_not_in_this_project_is_not_found(app, signed_in):
    set_id = _project(app, signed_in)
    assert signed_in.get(f"/specs/sets/{set_id}/inputs/bridge").status_code == 404
    assert signed_in.get(f"/specs/sets/{set_id}/inputs/nowhere").status_code == 404
