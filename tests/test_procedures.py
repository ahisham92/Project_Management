"""The company procedures tab and the "needs attention" view."""

from __future__ import annotations

import json

from app import procedures
from app.journey.check_library import check


def test_library_is_consistent():
    assert check(procedures.library()) == []


def test_sibline_starts_from_its_checklist(signed_in):
    state = signed_in.get("/projects/1/procedures/state").get_json()
    assert state["answers"]["num"] == "S25001-0100D"
    s = procedures.summary(state)
    assert s["total"] == 213
    assert s["counts"]["done"] == 1 and s["counts"]["na"] == 1
    assert s["counts"]["locked"] == 0


def test_tab_and_journey_page_render(signed_in):
    page = signed_in.get("/projects/1/procedures")
    assert page.status_code == 200 and b"journey-frame" in page.data
    app = signed_in.get("/projects/1/procedures/app")
    assert app.status_code == 200
    assert b"/*SERVER*/" not in app.data and b"/*LIBRARY*/" not in app.data


def test_changes_are_saved_key_by_key(signed_in):
    lib = procedures.library()
    a, b = lib["items"][2]["id"], lib["items"][3]["id"]
    r = signed_in.post("/projects/1/procedures/save", json={"patch": {"status": {a: "done"}}})
    assert r.status_code == 200
    # A second change from somebody else's browser keeps the first.
    signed_in.post("/projects/1/procedures/save",
                   json={"patch": {"status": {b: "na"}, "notes": {b: "Not in scope"}}})
    state = signed_in.get("/projects/1/procedures/state").get_json()
    assert state["status"][a] == "done" and state["status"][b] == "na"
    signed_in.post("/projects/1/procedures/save", json={"patch": {"status": {a: None}}})
    state = signed_in.get("/projects/1/procedures/state").get_json()
    assert a not in state["status"]


def test_bad_changes_are_refused(signed_in):
    r = signed_in.post("/projects/1/procedures/save", json={"patch": {"status": {"nope": "done"}}})
    assert r.status_code == 400
    r = signed_in.post("/projects/1/procedures/save", json={"patch": {"answers": {"process": "pencil"}}})
    assert r.status_code == 400
    r = signed_in.post("/projects/1/procedures/save", json={"patch": {"secret": {}}})
    assert r.status_code == 400


def test_a_new_project_starts_blank():
    state = procedures.blank_state({"id": 9, "code": "NEW-1", "name": "New"})
    s = procedures.summary(state)
    assert s["counts"]["done"] == 0
    assert s["counts"]["locked"] > 0  # waiting on the first answers


def test_answers_unlock_and_hide_actions():
    state = procedures.blank_state({"id": 9, "code": "NEW-1", "name": "New"})
    before = procedures.summary(state)["counts"]["locked"]
    procedures.apply_patch(state, {"answers": {"process": "cadd"}})
    assert procedures.summary(state)["counts"]["locked"] < before


def test_attention_view_lists_overdue_procedure_actions(signed_in):
    lib = procedures.library()
    item = lib["items"][1]
    signed_in.post("/projects/1/procedures/save",
                   json={"patch": {"due": {item["id"]: "2020-01-01"}, "status": {item["id"]: None}}})
    page = signed_in.get("/projects/1/attention")
    assert page.status_code == 200
    assert item["t"].encode() in page.data or json.dumps(item["t"])[1:-1].encode() in page.data
    assert b"Needs a decision now" in page.data


def test_dashboard_shows_the_attention_strip(signed_in):
    page = signed_in.get("/projects/1/")
    assert b"See what needs attention" in page.data
