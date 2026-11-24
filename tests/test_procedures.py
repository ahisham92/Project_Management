"""The company procedures tab and the "needs attention" view."""

from __future__ import annotations

import json

from app import procedures
from app.journey.check_library import check


def test_library_is_consistent():
    assert check(procedures.library()) == []


def test_sibline_starts_blank(signed_in):
    state = signed_in.get("/projects/1/procedures/state").get_json()
    assert state["answers"]["num"] == "SIBLINE-PORT"
    assert state["status"] == {} and state["notes"] == {}


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


def test_stations_follow_the_order_work_happens():
    ids = [p["id"] for p in procedures.library()["phases"]]
    assert ids.index("supply") < ids.index("exec")      # suppliers appointed before design
    assert ids.index("aide") < ids.index("exec")        # stage checks start with data collection
    assert ids.index("check") < ids.index("submit") < ids.index("close")


def test_a_journey_saved_under_the_first_order_keeps_its_visited_stations():
    state = {"visited": {"10": True, "14": True}}  # "supply" and "aide" in the first order
    procedures._reorder_visited(state)
    ids = [p["id"] for p in procedures.library()["phases"]]
    assert state["visited"] == {str(ids.index("supply")): True, str(ids.index("aide")): True}


def test_the_journey_shows_the_project_number_and_name_as_they_are_now(signed_in, app):
    lib = procedures.library()
    signed_in.post("/projects/1/procedures/save", json={"patch": {"status": {lib["items"][0]["id"]: "done"}}})
    with app.app_context():
        from app.db import execute
        execute("UPDATE projects SET code = 'L26100-B', name = 'Renamed' WHERE id = 1")
    state = signed_in.get("/projects/1/procedures/state").get_json()
    assert state["answers"]["num"] == "L26100-B" and state["answers"]["title"] == "Renamed"
    assert state["status"][lib["items"][0]["id"]] == "done"
