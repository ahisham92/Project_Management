"""The register: numbering, the mix, and what a single drawing is worth.

Most of this is arithmetic on dicts and needs no database — a document's hours
are its deliverable's, times three fractions. The numbering and the routes go
through the app, because a convention that only works in a unit test is a
convention nobody can use.
"""

from __future__ import annotations

import pytest

from app import register as reg


def a_task(task_id: int, wbs: str, points: float = 10.0, section: str = "") -> dict:
    return {"id": task_id, "wbs": wbs, "name": f"Line {wbs}", "weight_points": points,
            "section_id": None, "submission_date": "2026-06-30"}


def a_kind(kind_id: int, key: str, name: str, code: str) -> dict:
    return {"id": kind_id, "key": key, "name": name, "code": code}


def a_doc(doc_id: int, task_id: int, kind_id: int, weight: float = 1.0,
          trades: list | None = None, status: str = "planned") -> dict:
    return {"id": doc_id, "task_id": task_id, "kind_id": kind_id, "weight": weight,
            "number": f"N-{doc_id:04}", "title": f"Document {doc_id}", "status": status,
            "trades": trades or []}


MIX = [{"kind_id": 1, "percent": 35}, {"kind_id": 2, "percent": 60},
       {"kind_id": 3, "percent": 5}]


# --- the numbering convention ------------------------------------------------

def test_a_convention_without_a_running_number_is_refused():
    assert reg.check_format("") != ""
    assert "seq" in reg.check_format("{project}-{kind}")
    assert reg.check_format("{project}-{kind}-{seq:4}") == ""


def test_an_unknown_token_says_which_one():
    trouble = reg.check_format("{project}-{discipline}-{seq}")
    assert "{discipline}" in trouble
    assert "trade" in trouble          # and what it could have used instead


def test_the_number_is_filled_in_from_the_convention():
    project = {"code": "L26100", "client": "Sibline Port Authority",
               "document_format": "{project}-{trade}-{kind}-{seq:4}"}
    made, _prefix = reg.number_for(
        project, [], task=a_task(1, "3.1"), kind=a_kind(2, "drawings", "Drawings", "DWG"),
        trade={"key": "marine"})
    assert made == "L26100-MARINE-DWG-0001"


def test_a_blank_token_does_not_leave_a_gap():
    """A document several trades share has no trade in its number, and that is
    the honest answer rather than picking the biggest share."""
    project = {"code": "L26100", "document_format": "{project}-{trade}-{kind}-{seq:4}"}
    made, _prefix = reg.number_for(project, [], task=a_task(1, "3.1"),
                                   kind=a_kind(1, "report", "Report", "RPT"))
    assert made == "L26100-RPT-0001"


def test_the_running_number_counts_within_its_own_prefix():
    """A convention that groups by trade numbers each trade from one, without
    anybody maintaining a counter."""
    project = {"code": "L26100", "document_format": "{project}-{trade}-{kind}-{seq:4}"}
    kind = a_kind(2, "drawings", "Drawings", "DWG")
    taken = ["L26100-MARINE-DWG-0001", "L26100-MARINE-DWG-0002"]

    marine, _ = reg.number_for(project, taken, task=a_task(1, "3.1"), kind=kind,
                               trade={"key": "marine"})
    geo, _ = reg.number_for(project, taken, task=a_task(1, "3.1"), kind=kind,
                            trade={"key": "geotech"})
    assert marine == "L26100-MARINE-DWG-0003"
    assert geo == "L26100-GEOTECH-DWG-0001"


def test_a_hole_in_the_numbering_is_filled_rather_than_left():
    project = {"code": "L26100", "document_format": "{project}-{kind}-{seq:3}"}
    kind = a_kind(1, "report", "Report", "RPT")
    taken = ["L26100-RPT-001", "L26100-RPT-003"]
    made, _ = reg.number_for(project, taken, task=a_task(1, "3.1"), kind=kind)
    assert made == "L26100-RPT-002"


def test_the_year_and_the_wbs_are_available_to_a_convention():
    project = {"code": "L26100", "document_format": "{project}-{wbs}-{kind}-{yy}-{seq:2}"}
    made, _ = reg.number_for(project, [], task=a_task(1, "3.10"),
                             kind=a_kind(1, "report", "Report", "RPT"), year="2026")
    assert made == "L26100-310-RPT-26-01"


# --- what a deliverable is made of -------------------------------------------

def test_a_deliverable_follows_the_project_until_it_says_otherwise():
    assert reg.mix_for(1, {}, MIX) == [
        {"kind_id": 1, "percent": 35}, {"kind_id": 2, "percent": 60},
        {"kind_id": 3, "percent": 5}]

    own = {1: [{"kind_id": 3, "percent": 100}]}
    assert reg.mix_for(1, own, MIX) == [{"kind_id": 3, "percent": 100}]


def test_a_mix_that_does_not_total_a_hundred_is_normalised():
    """A split held in thirds and shown rounded reads as 99, and refusing that
    is refusing arithmetic rather than catching a mistake."""
    made = reg.mix_for(1, {}, [{"kind_id": 1, "percent": 30}, {"kind_id": 2, "percent": 30}])
    assert sum(row["percent"] for row in made) == pytest.approx(100)
    assert made[0]["percent"] == pytest.approx(50)


def test_a_mix_of_nothing_is_no_mix_at_all():
    assert reg.mix_for(1, {}, []) == []


# --- costing ------------------------------------------------------------------

def test_a_kind_s_share_splits_evenly_across_its_documents():
    tasks = [a_task(1, "3.1")]
    docs = [a_doc(10, 1, 2), a_doc(11, 1, 2), a_doc(12, 1, 2)]   # three drawings
    made = reg.costing(tasks, docs, {}, MIX, {1: {7: 1000.0}})

    drawings = [d for d in made["documents"] if d["kind_id"] == 2]
    assert [round(d["hours"], 2) for d in drawings] == [200.0, 200.0, 200.0]   # 60% of 1000, in three


def test_a_heavier_drawing_takes_more_of_its_kind():
    tasks = [a_task(1, "3.1")]
    docs = [a_doc(10, 1, 2, weight=3), a_doc(11, 1, 2, weight=1)]
    made = reg.costing(tasks, docs, {}, MIX, {1: {7: 1000.0}})

    hours = {d["id"]: d["hours"] for d in made["documents"]}
    assert hours[10] == pytest.approx(450)      # three quarters of the 600
    assert hours[11] == pytest.approx(150)


def test_one_document_of_its_kind_takes_all_of_it():
    tasks = [a_task(1, "3.1")]
    made = reg.costing(tasks, [a_doc(10, 1, 1)], {}, MIX, {1: {7: 1000.0}})
    assert made["documents"][0]["hours"] == pytest.approx(350)   # the whole 35%
    assert made["documents"][0]["kind_share"] == pytest.approx(35)


def test_a_document_nobody_owns_is_split_the_way_its_deliverable_is():
    """A design basis is one document every discipline writes at once."""
    tasks = [a_task(1, "3.1")]
    made = reg.costing(tasks, [a_doc(10, 1, 1)], {}, MIX, {1: {7: 600.0, 8: 400.0}})

    doc = made["documents"][0]
    assert doc["by_trade"][7] == pytest.approx(350 * 0.6)
    assert doc["by_trade"][8] == pytest.approx(350 * 0.4)


def test_a_document_with_its_own_trades_says_so():
    """A dredging drawing is Marine's alone, whatever the line says."""
    tasks = [a_task(1, "3.1")]
    docs = [a_doc(10, 1, 2, trades=[{"trade_id": 7, "share": 100}])]
    made = reg.costing(tasks, docs, {}, MIX, {1: {7: 600.0, 8: 400.0}})

    doc = made["documents"][0]
    assert doc["by_trade"] == {7: pytest.approx(600)}    # 60% of 1000, all Marine
    assert doc["shares"] == {7: pytest.approx(100)}


def test_the_register_never_spends_more_than_the_line_allows():
    tasks = [a_task(1, "3.1")]
    docs = [a_doc(10, 1, 1), a_doc(11, 1, 2), a_doc(12, 1, 2), a_doc(13, 1, 3)]
    made = reg.costing(tasks, docs, {}, MIX, {1: {7: 1000.0}})

    assert sum(d["hours"] for d in made["documents"]) == pytest.approx(1000)
    assert made["lines"][0]["raised_hours"] == pytest.approx(1000)


def test_a_kind_with_nothing_raised_against_it_is_named():
    tasks = [a_task(1, "3.1")]
    made = reg.costing(tasks, [a_doc(10, 1, 1)], {}, MIX, {1: {7: 1000.0}})

    line = made["lines"][0]
    assert sorted(line["missing_kinds"]) == [2, 3]     # the drawings and the specification
    assert line["raised_hours"] == pytest.approx(350)  # only the report is worth anything yet
    assert made["unraised"] == [line]


def test_booked_hours_reach_the_document_and_the_deliverable():
    tasks = [a_task(1, "3.1")]
    docs = [a_doc(10, 1, 2), a_doc(11, 1, 2)]
    made = reg.costing(tasks, docs, {}, MIX, {1: {7: 1000.0}}, {10: {7: 220.0}})

    assert made["documents"][0]["spent_hours"] == pytest.approx(220)
    assert made["documents"][1]["spent_hours"] == pytest.approx(0)
    assert made["lines"][0]["spent_hours"] == pytest.approx(220)
    assert made["lines"][0]["left_hours"] == pytest.approx(780)


def test_a_deliverable_with_nothing_raised_is_still_returned():
    """"Nothing has been raised for this" is the most useful thing the register
    can say about a line."""
    made = reg.costing([a_task(1, "3.1")], [], {}, MIX, {1: {7: 1000.0}})
    assert made["lines"][0]["documents"] == 0
    assert made["lines"][0]["planned_hours"] == pytest.approx(1000)
    assert made["unraised"]


# --- through the app ----------------------------------------------------------

def test_the_tab_reads(signed_in):
    answer = signed_in.get("/projects/1/submittals")
    assert answer.status_code == 200
    page = answer.get_data(as_text=True)
    assert "Document register" in page
    assert "What a deliverable is made of" in page


def test_the_kinds_are_seeded_the_first_time_they_are_asked_for(app):
    from app.service import load_kinds, load_mix

    with app.app_context():
        kinds = load_kinds(1)
        assert {k["key"] for k in kinds} >= {"report", "drawings", "specifications", "boq"}
        assert {m["percent"] for m in load_mix(1)} == {35.0, 60.0, 5.0}


def test_raising_a_document_numbers_it(app):
    from app.db import query_one
    from app.service import load_kinds, raise_submittal

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY wbs LIMIT 1"))
        kind = next(k for k in load_kinds(1) if k["key"] == "report")

        made, trouble = raise_submittal(project, task["id"], kind["id"], "Design basis report")
        assert trouble == ""
        row = query_one("SELECT * FROM submittals WHERE id = ?", (made,))
        assert row["number"].endswith("RPT-0001")
        assert row["title"] == "Design basis report"


def test_a_document_needs_a_title(app):
    from app.db import query_one
    from app.service import load_kinds, raise_submittal

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 LIMIT 1"))
        kind = load_kinds(1)[0]
        made, trouble = raise_submittal(project, task["id"], kind["id"], "   ")
        assert made == 0 and "title" in trouble


def test_two_documents_never_share_a_number(app):
    from app.db import query_one
    from app.service import load_kinds, raise_submittal

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 LIMIT 1"))
        kind = load_kinds(1)[0]
        first, _ = raise_submittal(project, task["id"], kind["id"], "One")
        taken = query_one("SELECT number FROM submittals WHERE id = ?", (first,))["number"]
        made, trouble = raise_submittal(project, task["id"], kind["id"], "Two", number=taken)
        assert made == 0 and "already in the register" in trouble


def test_issuing_a_document_stamps_the_day_and_freezes_its_number(app):
    from app.db import query_one
    from app.service import load_kinds, raise_submittal, today, update_submittal

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 LIMIT 1"))
        kind = load_kinds(1)[0]
        made, _ = raise_submittal(project, task["id"], kind["id"], "Design basis report")

        assert update_submittal(1, made, "status", "issued") == ""
        row = query_one("SELECT * FROM submittals WHERE id = ?", (made,))
        assert row["issued_date"] == today()

        trouble = update_submittal(1, made, "number", "SOMETHING-ELSE")
        assert "not ours to change" in trouble


def test_a_document_with_hours_against_it_is_not_quietly_removed(app):
    from app.db import execute, query_one
    from app.service import load_kinds, raise_submittal, remove_submittal

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 LIMIT 1"))
        kind = load_kinds(1)[0]
        made, _ = raise_submittal(project, task["id"], kind["id"], "Design basis report")
        execute("INSERT INTO time_entries (project_id, task_id, submittal_id, entry_date, hours) "
                "VALUES (?, ?, ?, ?, ?)", (1, task["id"], made, "2026-09-01", 8))

        assert "charged to" in remove_submittal(1, made)
        assert query_one("SELECT 1 FROM submittals WHERE id = ?", (made,)) is not None


def test_a_line_can_be_made_of_something_else_and_handed_back(app):
    from app.db import query_one
    from app.service import load_kinds, load_task_mixes, set_mix

    with app.app_context():
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 LIMIT 1"))
        boq = next(k for k in load_kinds(1) if k["key"] == "boq")

        set_mix(1, {boq["id"]: 100}, task["id"])
        assert load_task_mixes(1)[task["id"]][0]["percent"] == pytest.approx(100)

        set_mix(1, {}, task["id"])
        assert task["id"] not in load_task_mixes(1)


def test_the_number_is_previewed_before_anything_is_raised(signed_in, app):
    from app.db import query_one
    from app.service import load_kinds

    with app.app_context():
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY wbs LIMIT 1"))
        kind = next(k for k in load_kinds(1) if k["key"] == "drawings")

    answer = signed_in.get(f"/projects/1/submittals/number?task_id={task['id']}&kind_id={kind['id']}")
    body = answer.get_json()
    assert body["ok"] is True
    assert body["number"].endswith("DWG-0001")


def test_hours_booked_to_a_document_belong_to_its_deliverable(signed_in, app):
    """Whatever the form said: the two disagreeing is how a register stops
    adding up."""
    from app.db import query_one
    from app.service import load_kinds, raise_submittal

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        mine = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY wbs LIMIT 1"))
        other = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY wbs DESC LIMIT 1"))
        kind = load_kinds(1)[0]
        made, _ = raise_submittal(project, mine["id"], kind["id"], "Design basis report")

    signed_in.post("/projects/1/time", data={
        "entry_date": "01/09/2026", "hours": "6", "submittal_id": made,
        "task_id": other["id"]})

    with app.app_context():
        entry = query_one("SELECT * FROM time_entries WHERE submittal_id = ?", (made,))
        assert entry["task_id"] == mine["id"]


def test_carmen_can_read_the_register(app):
    from app.assistant.tools import document_register
    from app.db import query_one
    from app.service import load_kinds, raise_submittal

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY wbs LIMIT 1"))
        kind = next(k for k in load_kinds(1) if k["key"] == "report")
        raise_submittal(project, task["id"], kind["id"], "Design basis report")

        answer = document_register(1)

    assert answer["documents_in_register"] == 1
    assert answer["documents"][0]["title"] == "Design basis report"
    assert answer["documents"][0]["hours"] > 0
    assert answer["deliverables_with_nothing_raised"]


def test_a_broken_convention_is_refused_rather_than_saved(signed_in, app):
    from app.db import query_one

    from .test_web import unlock

    unlock(signed_in)
    with app.app_context():
        before = dict(query_one("SELECT * FROM projects WHERE id = 1"))

    signed_in.post("/projects/1/settings", data={
        "name": before["name"], "code": before["code"],
        "document_format": "{project}-{nonsense}", "status": "active"})

    with app.app_context():
        after = dict(query_one("SELECT * FROM projects WHERE id = 1"))
    assert after["document_format"] == before["document_format"]
