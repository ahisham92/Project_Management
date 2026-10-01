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


def test_a_saved_project_goes_back_to_its_brief(app, signed_in):
    from app import specs_store
    from .test_specs_kinds import applies, load

    set_id = _project(app, signed_in)
    assert f'/specs/sets/{set_id}/story#level-1' in text(signed_in.get(f"/specs/sets/{set_id}"))
    _decided(signed_in, set_id)
    signed_in.post(f"/specs/sets/{set_id}/inputs/office", data={**SITE, "accept_suggested": "1"}, headers=FETCH)
    load(signed_in, "STD15A_SPC_033816_ST_PT.docx", "# GENERAL\n## SUMMARY\n- PT.\n", "033816",
         "UNBONDED POST-TENSIONED CONCRETE")
    applies(app, "033816", "15A", "post_tensioning=Unbonded")
    load(signed_in, "STD15A_SPC_034100_ST_PC.docx", "# GENERAL\n## SUMMARY\n- Precast.\n", "034100",
         "PRECAST STRUCTURAL CONCRETE")
    applies(app, "034100", "15A", "precast=Plant precast")
    with app.app_context():
        pt = specs_store.section_by_number("033816", "15A")["id"]
        pc = specs_store.section_by_number("034100", "15A")["id"]

    def numbers():
        with app.app_context():
            return sorted(r["number"] for r in specs_store.set_sections(set_id))
    # Changed from the brief, the sections the choices call for are asked
    # about first: nothing is saved until the engineer confirms.
    answer = _decided(signed_in, set_id, post_tensioning="Unbonded", precast="Plant precast")
    assert "Nothing is saved yet" in answer["messages"][0]["text"]
    assert 'name="add_section"' in answer["html"] and "033816" in answer["html"] and "034100" in answer["html"]
    assert numbers() == ["033000"]
    with app.app_context():
        assert specs_store.chosen_for(specs_store.spec_set(set_id))["post_tensioning"] in ("", "None")
    # Confirmed with one ticked: that one is put in, the other stays out for good.
    data = {"shown_opt": ["post_tensioning", "precast"], "opt_post_tensioning": "Unbonded",
            "opt_precast": "Plant precast", "confirm": "1", "add_section": [str(pt)]}
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/decide", data=data, headers=FETCH).get_json()
    assert numbers() == ["033000", "033816"]
    with app.app_context():
        row = specs_store.spec_set(set_id)
        assert pc in specs_store.declined(row) and specs_store.chosen_for(row)["post_tensioning"] == "Unbonded"
    assert any("033816" in (m.get("html") or "") for m in answer["messages"])
    # The levels already answered stay open: only the ones with new questions
    # wait to be answered.
    assert not {c["slug"]: c for c in answer["scene"]["chapters"]}["the-project"]["locked"]
    # Taken back out of the brief, a section is named, not taken out.
    data = {"shown_opt": ["post_tensioning"], "opt_post_tensioning": "None"}
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/decide", data=data, headers=FETCH).get_json()
    assert numbers() == ["033000", "033816"]
    assert any("no longer call for" in (m.get("html") or "") for m in answer["messages"])


def test_an_answered_level_after_the_open_one_stays_open(app, signed_in):
    from .test_specs_story import _asked

    set_id = _project(app, signed_in)
    _decided(signed_in, set_id)
    # The mix answered on Details while the project's level is still open.
    mix = next(s for s in _scene(signed_in, set_id)["stations"] if s["id"] == "mixer")
    asked = {q["key"]: q for q in _asked(app, set_id)}
    form = {}
    for q in mix["questions"]:
        a = asked[q["key"]]
        if a.get("switch") or a.get("choices"):
            form[f"q_{q['key']}"] = (a.get("choices") or ["Yes"])[0]
        else:
            form[f"q_{q['key']}"], form[f"t_{q['key']}"] = "__free__", "40MPa"
        form[f"split_{q['key']}"] = "0"
    signed_in.post(f"/specs/sets/{set_id}/details?group=concrete-mixes-and-properties", data=form)
    data = _scene(signed_in, set_id)
    chapters = {c["slug"]: c for c in data["chapters"]}
    assert data["open_stage"] == 1 and chapters["the-mix"]["done"], [(q["key"], q["state"]) for q in mix["questions"]]
    # Answered, it stays open to change; the unanswered level between stays locked.
    assert not chapters["the-mix"]["locked"] and chapters["the-ingredients"]["locked"]
    assert "Locked." not in text(signed_in.get(f"/specs/sets/{set_id}/inputs/mixer"))


def test_the_story_tells_each_level_for_the_works_it_builds(app, signed_in):
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/story"))
    assert 'data-mode="story"' in page and "the story of the works" in page
    # Details stays as the list view of the same questions.
    assert f'href="/specs/sets/{set_id}/details"' in page and "List view" in page
    data = json.loads(re.search(r'id="spec-scene-data">(.*?)</script>', page, re.S).group(1))
    tale = {c["slug"]: c["story"] for c in data["chapters"]}
    assert tale["deciding"].startswith("Every project starts at the drawing board. Decide what the building is")
    assert "The mixer turns." in tale["the-mix"]
    # A quay on the sea is told as the quay.
    _decided(signed_in, set_id, structures="Marine structures")
    data = json.loads(re.search(r'id="spec-scene-data">(.*?)</script>',
                                text(signed_in.get(f"/specs/sets/{set_id}/story")), re.S).group(1))
    assert "Decide what the quay is" in data["chapters"][0]["story"]
    # The details page points to the story.
    assert f'href="/specs/sets/{set_id}/story"' in text(signed_in.get(f"/specs/sets/{set_id}/details"))


def test_the_story_needs_a_project_and_a_sign_in(app, signed_in):
    set_id = _project(app, signed_in)
    assert signed_in.get("/specs/sets/999/story").status_code == 404
    signed_in.post("/logout")
    assert signed_in.get(f"/specs/sets/{set_id}/story").status_code in (302, 401)


def test_the_story_asks_one_question_at_a_time(app, signed_in):
    set_id = _project(app, signed_in)
    _decided(signed_in, set_id)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/office?cards=1"))
    # A card for the question, with its own form: Next saves only that one,
    # a suggestion shown on its own card being accepted as it is moved past.
    assert page.count("data-card ") == 1 and 'name="only" value="proj_site"' in page
    assert 'name="accept_suggested" value="1"' in page and "Suggested from the master" in page
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/office",
                            data={**SITE, "only": "proj_site", "accept_suggested": "1"}, headers=FETCH).get_json()
    assert _answers(app, set_id)["proj_site"] == "Project site" and answer["scene"]["open_stage"] == 2
    # A station of several questions: saving one card leaves the others as they were.
    from app import specs_questions

    data = answer["scene"]
    with app.app_context():
        specs_questions.save_answers(set_id, {q["key"]: "As agreed" for s in data["stations"] if s["id"] in
                                              data["chapters"][2]["stations"] for q in s["questions"]}, {})
    data = _scene(signed_in, set_id)
    assert data["open_stage"] == 3
    station = "mixer"
    questions = {s["id"]: s for s in data["stations"]}[station]["questions"]
    assert len(questions) >= 2
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/{station}?cards=1"))
    assert page.count("data-card ") == len(questions)
    first, second = questions[0]["key"], questions[1]["key"]
    before = _answers(app, set_id)
    signed_in.post(f"/specs/sets/{set_id}/inputs/{station}",
                   data={"only": first, f"q_{first}": "__free__", f"t_{first}": "As agreed", f"q_{second}": "__free__",
                         f"t_{second}": "Not this one"}, headers=FETCH)
    after = _answers(app, set_id)
    assert after[first] == "As agreed" and after.get(second) == before.get(second)
    # A key not at the station is not found.
    assert signed_in.post(f"/specs/sets/{set_id}/inputs/{station}", data={"only": "proj_site"},
                          headers=FETCH).status_code == 404


def test_the_brief_asks_only_what_applies(app, signed_in):
    from app import specs_inputs

    # Marine furniture only for marine structures, the steel's details only
    # with a steel frame, and a detail of a detail only when both apply.
    assert not specs_inputs.brief_applies("fenders", {"structures": "Buildings"})
    assert specs_inputs.brief_applies("fenders", {"structures": "Buildings|Marine structures"})
    assert not specs_inputs.brief_applies("steel_protection", {"steel_framing": "No"})
    assert specs_inputs.brief_applies("steel_protection", {"steel_framing": "Yes"})
    assert not specs_inputs.brief_applies("deck_design", {"steel_framing": "No", "steel_systems": "Steel deck"})
    assert specs_inputs.brief_applies("pt_encapsulation", {"post_tensioning": "Unbonded"})
    assert not specs_inputs.brief_applies("pt_delegated_design", {"post_tensioning": "None"})
    assert specs_inputs.brief_applies("standards", {})
    set_id = _project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/decide"))
    fenders = re.search(r'<div class="spec-decide-q" data-opt="fenders"[^>]*>\s*<input[^>]*>', page).group(0)
    assert "data-when=" in fenders and " hidden" in fenders and "disabled" in fenders
    # A part saved on the way is kept without deciding the brief or adding a section.
    from app import specs_store

    with app.app_context():
        sections = len(specs_store.set_sections(set_id))
    answer = signed_in.post(f"/specs/sets/{set_id}/inputs/decide", headers=FETCH, data={
        "partial": "1", "shown_opt": ["structures"], "opt_structures": ["Marine structures"]}).get_json()
    assert answer["scene"]["chapters"][0]["done"] is False
    with app.app_context():
        assert specs_store.chosen_for(specs_store.spec_set(set_id))["structures"] == "Marine structures"
        assert len(specs_store.set_sections(set_id)) == sections
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/decide"))
    fenders = re.search(r'<div class="spec-decide-q" data-opt="fenders"[^>]*>', page).group(0)
    assert " hidden" not in fenders


def test_a_new_project_starts_on_the_story_with_nothing_assumed(app, signed_in):
    from app import specs_inputs, specs_store

    answer = signed_in.post("/specs/sets", data={"name": "Jeddah Tower", "family": "15A"})
    set_id = int(answer.headers["Location"].split("/sets/")[1].split("/")[0])
    # Straight into the story, at the brief: no page in between.
    assert answer.headers["Location"].endswith(f"/specs/sets/{set_id}/story#level-1")
    assert "the story of the works" in text(signed_in.get(f"/specs/sets/{set_id}/story"))

    def question(page, key):
        return re.search(r'<div class="spec-decide-q" data-opt="%s".*?</div>' % key, page, re.S).group(0)

    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/decide"))
    # What the project builds and whether it has a steel frame are asked, not
    # assumed: nothing picked, so neither marine furniture nor the steel's
    # details are asked, and the site is a bare plot.
    for key in ("structures", "steel_framing", "precast", "post_tensioning"):
        assert "data-gate" in question(page, key) and "checked" not in question(page, key)
    for key in ("fenders", "bollards", "steel_protection", "fire"):
        assert re.search(r'data-opt="%s"[^>]*hidden' % key, page), key
    assert "spec-decide-art" in question(page, "seismic")          # a picture on every question
    scene = _scene(signed_in, set_id)
    assert scene["site"]["builds"] is False and scene["site"]["steel"] is False
    # Picked on the way, each brings its own questions, and unpicked takes them away.
    signed_in.post(f"/specs/sets/{set_id}/inputs/decide", headers=FETCH, data={
        "partial": "1", "shown_opt": ["structures", "steel_framing"],
        "opt_structures": ["Buildings"], "opt_steel_framing": "No"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/decide"))
    assert 'value="Buildings" checked' in question(page, "structures")
    assert re.search(r'data-opt="fenders"[^>]*hidden', page) and re.search(r'data-opt="aess"[^>]*hidden', page)
    signed_in.post(f"/specs/sets/{set_id}/inputs/decide", headers=FETCH, data={
        "partial": "1", "shown_opt": ["steel_framing"], "opt_steel_framing": "Yes"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/decide"))
    assert not re.search(r'data-opt="aess"[^>]*hidden', page)
    # The brief as decided names only what applies: no fenders on a building.
    with app.app_context():
        chosen = specs_store.chosen_for(specs_store.spec_set(set_id))
        named = [d["key"] for d in specs_inputs.decisions(chosen, specs_store.options())]
    assert "fenders" not in named and "aess" in named


def test_where_the_project_is_is_asked_as_a_city_and_country(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    _decided(signed_in, set_id)
    with app.app_context():
        specs_store.set_place(set_id, "Jeddah", "Saudi Arabia")
    page = text(signed_in.get(f"/specs/sets/{set_id}/inputs/office?cards=1"))
    assert "Where is the project?" in page and "as the specification names it" not in page
    assert 'value="Jeddah" placeholder="e.g. Jeddah" data-place-city' in page
    assert 'value="Saudi Arabia" placeholder="e.g. Saudi Arabia" data-place-country' in page
    assert 'name="t_proj_site" value="Jeddah, Saudi Arabia"' in page and 'id="spec-countries"' in page
    signed_in.post(f"/specs/sets/{set_id}/inputs/office", headers=FETCH, data={
        "only": "proj_site", "suggest_shown": "1", "accept_suggested": "1",
        "q_proj_site": "__free__", "t_proj_site": "Yanbu, Saudi Arabia"})
    assert _answers(app, set_id)["proj_site"] == "Yanbu, Saudi Arabia"
