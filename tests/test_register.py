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

def shape(made: list[dict]) -> dict[int, float]:
    """Just the weights, which is what most of these tests are about."""
    return {int(row["kind_id"]): round(row["percent"], 4) for row in made}


def test_a_deliverable_follows_the_project_until_it_says_otherwise():
    assert shape(reg.mix_for(1, {}, MIX)) == {1: 35, 2: 60, 3: 5}

    own = {1: [{"kind_id": 3, "percent": 100}]}
    assert shape(reg.mix_for(1, own, MIX)) == {3: 100}


def test_a_mix_that_does_not_total_a_hundred_is_normalised():
    """A split held in thirds and shown rounded reads as 99, and refusing that
    is refusing arithmetic rather than catching a mistake."""
    made = reg.mix_for(1, {}, [{"kind_id": 1, "percent": 30}, {"kind_id": 2, "percent": 30}])
    assert sum(row["percent"] for row in made) == pytest.approx(100)
    assert made[0]["percent"] == pytest.approx(50)


def test_a_mix_of_nothing_is_no_mix_at_all():
    assert reg.mix_for(1, {}, []) == []


# --- counting rather than typing ---------------------------------------------

# What one of each costs: a report is 120 hours, a drawing 35, a specification 20.
STANDARD = {1: 120.0, 2: 35.0, 3: 20.0}


def test_counting_what_a_package_holds_works_its_weight_out():
    """Six drawings at 35 against one report at 120: 210 hours of drawings to
    120 of report, so 64% and 36% — and nobody had to do that sum by hand."""
    counted = [{"kind_id": 1, "percent": 0, "quantity": 1},
               {"kind_id": 2, "percent": 0, "quantity": 6}]
    made = shape(reg.mix_for(1, {}, counted, STANDARD))

    assert made[2] == pytest.approx(210 / 330 * 100, abs=0.01)
    assert made[1] == pytest.approx(120 / 330 * 100, abs=0.01)
    assert sum(made.values()) == pytest.approx(100)


def test_a_counted_kind_says_so_and_carries_its_count():
    counted = [{"kind_id": 2, "percent": 0, "quantity": 6}]
    row = reg.mix_for(1, {}, counted, STANDARD)[0]
    assert row["from_count"] is True
    assert row["quantity"] == pytest.approx(6)


def test_no_two_workflows_need_the_same_deliverables():
    """One line is six drawings, the next is a report and two specifications.
    Both are counted, and neither borrows the other's shape."""
    own = {1: [{"kind_id": 2, "percent": 0, "quantity": 6}],
           2: [{"kind_id": 1, "percent": 0, "quantity": 1},
               {"kind_id": 3, "percent": 0, "quantity": 2}]}

    assert shape(reg.mix_for(1, own, MIX, STANDARD)) == {2: 100}
    second = shape(reg.mix_for(2, own, MIX, STANDARD))
    assert second[1] == pytest.approx(120 / 160 * 100, abs=0.01)   # 120 h of report
    assert second[3] == pytest.approx(40 / 160 * 100, abs=0.01)    # two specs at 20


def test_a_count_with_nothing_to_weigh_it_falls_back_to_the_percentage():
    """A kind nobody has priced cannot be weighed by counting, and dropping it
    would be worse than using the number somebody typed."""
    rows = [{"kind_id": 9, "percent": 40, "quantity": 3},
            {"kind_id": 8, "percent": 60, "quantity": 0}]
    assert shape(reg.mix_for(1, {}, rows, {})) == {9: 40, 8: 60}


def test_a_typed_percentage_is_still_a_mix():
    rows = [{"kind_id": 1, "percent": 35}, {"kind_id": 2, "percent": 65}]
    made = reg.mix_for(1, {}, rows, STANDARD)
    assert shape(made) == {1: 35, 2: 65}
    assert all(row["from_count"] is False for row in made)


# --- expected against what is really there ------------------------------------

def test_the_expected_number_is_the_count_where_one_was_given():
    tasks = [a_task(1, "3.1")]
    own = {1: [{"kind_id": 2, "percent": 0, "quantity": 10}]}
    made = reg.costing(tasks, [], own, MIX, {1: {7: 1000.0}}, {}, STANDARD)

    drawings = next(c for c in made["lines"][0]["by_kind"] if c["kind_id"] == 2)
    assert drawings["expected"] == pytest.approx(10)
    assert drawings["issued"] == 0


def test_without_a_count_the_hours_say_how_many_to_expect():
    """350 hours of drawings at 35 hours each is ten drawings, whether or not
    anybody counted them."""
    tasks = [a_task(1, "3.1")]
    mix = [{"kind_id": 2, "percent": 35}, {"kind_id": 1, "percent": 65}]
    made = reg.costing(tasks, [], {}, mix, {1: {7: 1000.0}}, {}, STANDARD)

    drawings = next(c for c in made["lines"][0]["by_kind"] if c["kind_id"] == 2)
    assert drawings["expected"] == pytest.approx(10)
    assert drawings["hours_each_expected"] == pytest.approx(35)


def test_what_a_drawing_really_cost_is_measured_against_the_standard():
    """Seven issued with 287 hours booked is 41 a drawing, six over standard."""
    tasks = [a_task(1, "3.1")]
    docs = [a_doc(10 + n, 1, 2, status="issued") for n in range(7)]
    booked = {10 + n: {7: 41.0} for n in range(7)}
    own = {1: [{"kind_id": 2, "percent": 0, "quantity": 10}]}
    made = reg.costing(tasks, docs, own, MIX, {1: {7: 1000.0}}, booked, STANDARD)

    drawings = next(c for c in made["lines"][0]["by_kind"] if c["kind_id"] == 2)
    assert drawings["issued"] == 7
    assert drawings["hours_each_actual"] == pytest.approx(41)
    assert drawings["over_each"] == pytest.approx(6)


def test_a_drawing_still_being_drawn_does_not_count_as_issued():
    tasks = [a_task(1, "3.1")]
    docs = [a_doc(10, 1, 2, status="issued"), a_doc(11, 1, 2, status="planned")]
    booked = {10: {7: 40.0}, 11: {7: 5.0}}
    made = reg.costing(tasks, docs, {}, MIX, {1: {7: 1000.0}}, booked, STANDARD)

    drawings = next(c for c in made["lines"][0]["by_kind"] if c["kind_id"] == 2)
    assert drawings["documents"] == 2
    assert drawings["issued"] == 1
    assert drawings["hours_each_actual"] == pytest.approx(45)   # both lots of hours, one issued


def test_the_whole_project_is_totalled_kind_by_kind():
    tasks = [a_task(1, "3.1"), a_task(2, "3.2")]
    own = {1: [{"kind_id": 2, "percent": 0, "quantity": 6}],
           2: [{"kind_id": 2, "percent": 0, "quantity": 4}]}
    docs = [a_doc(10, 1, 2, status="issued"), a_doc(11, 2, 2, status="planned")]
    made = reg.costing(tasks, docs, own, MIX, {1: {7: 500.0}, 2: {7: 500.0}}, {}, STANDARD)

    drawings = next(row for row in made["expected"] if row["kind_id"] == 2)
    assert drawings["expected"] == pytest.approx(10)
    assert drawings["documents"] == 2
    assert drawings["issued"] == 1
    assert drawings["left"] == pytest.approx(8)     # ten wanted, two already raised
    assert drawings["standard_hours"] == pytest.approx(35)


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


def test_counting_a_deliverable_through_the_page_works_its_weights_out(signed_in, app):
    """Six drawings and one report typed into the form come back as the weights
    that arithmetic says they are, with nobody having typed a percentage."""
    from app.db import query_one
    from app.service import load_kinds, load_task_mixes

    with app.app_context():
        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY wbs LIMIT 1"))
        kinds = {k["key"]: k for k in load_kinds(1)}
        drawings, report = kinds["drawings"], kinds["report"]

    form = {"task_id": task["id"],
            f"count_{drawings['id']}": 6, f"mix_{drawings['id']}": 0,
            f"count_{report['id']}": 1, f"mix_{report['id']}": 0}
    answer = signed_in.post("/projects/1/submittals/mix", data=form, follow_redirects=True)
    assert answer.status_code == 200

    with app.app_context():
        made = {int(row["kind_id"]): row for row in load_task_mixes(1)[task["id"]]}
        # Six at 35 against one at 120: 210 to 120.
        assert made[drawings["id"]]["quantity"] == pytest.approx(6)
        assert made[drawings["id"]]["percent"] == pytest.approx(210 / 330 * 100, abs=0.1)
        assert made[report["id"]]["percent"] == pytest.approx(120 / 330 * 100, abs=0.1)


def test_what_one_costs_is_seeded_and_can_be_changed_on_setup(signed_in, app):
    from app.service import load_kinds, save_kinds

    with app.app_context():
        drawings = next(k for k in load_kinds(1) if k["key"] == "drawings")
        assert drawings["standard_hours"] == pytest.approx(35)

        save_kinds(1, {f"kind_{drawings['id']}_name": drawings["name"],
                       f"kind_{drawings['id']}_code": drawings["code"],
                       f"kind_{drawings['id']}_hours": "48"})
        again = next(k for k in load_kinds(1) if k["key"] == "drawings")
        assert again["standard_hours"] == pytest.approx(48)


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
