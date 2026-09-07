"""What Carmen can change on the tabs a form used to be the only way into.

The two things worth proving here are the two that would hurt if they were
wrong. First, that a change still goes through the service layer the screens
use — the same validation, the same cascade — so "another way in, not another
set of rules" is true rather than a claim. Second, the bulk change: giving one
trade a share of every deliverable has to rescale the others, has to leave the
splits totalling 100%, and has to say plainly what it skipped.
"""

from __future__ import annotations

import pytest

from app.assistant import tools
from app.assistant.common import ApplyError, ToolError
from app.assistant.runner import apply


def _split(project_id: int, wbs: str) -> dict[str, float]:
    from app.service import load_tasks

    task = next(t for t in load_tasks(project_id) if t["wbs"] == wbs)
    return {k: round(v, 6) for k, v in task["allocations"].items() if v}


def _trade_id(name: str) -> int:
    from app.db import query_one

    return query_one("SELECT id FROM trades WHERE project_id = 1 AND name = ?", (name,))["id"]


# --- the catalogue ----------------------------------------------------------

def test_every_tab_has_something_she_can_change():
    """The whole point of this: no tab where the answer is "you will have to do
    that one by hand"."""
    for name in ("set_project_settings", "set_trade", "set_section", "set_workflow_step",
                 "set_team", "add_deliverable", "update_deliverable", "set_trade_split",
                 "share_across", "book_hours", "return_comments", "add_attendee",
                 "set_progress", "set_dates", "link_deliverables", "minute_meeting"):
        assert name in tools.RUNNERS, f"{name} is not offered"
        assert name in tools.WRITES, f"{name} should be staged, not run"

    for name in ("setup_sheet", "trade_split", "timesheet"):
        assert name in tools.READ_ONLY


# --- reading ----------------------------------------------------------------

def test_the_setup_sheet_reads_what_the_setup_tab_reads(app):
    with app.app_context():
        sheet = tools.run("setup_sheet", 1, {})

    assert sheet["project"]["code"] == "SIBLINE-PORT"
    assert sheet["deliverable_count"] == 55
    assert {t["name"] for t in sheet["trades"]} == {"Marine", "Geotechnical",
                                                    "Marine Structures", "Utilities"}
    assert {t["office"] for t in sheet["trades"]} == {"Beirut", "Cairo"}
    assert any(step["name"] == "Code A received" for step in sheet["workflow"])
    assert sheet["teams"], "a project always has at least the default team"


def test_a_deliverable_says_how_it_is_split_and_who_is_working_it(app):
    with app.app_context():
        split = tools.run("trade_split", 1, {"reference": "1.1"})
        one = tools.run("deliverable", 1, {"reference": "1.1"})

    assert abs(split["totals_percent"] - 100) < 0.01
    assert one["trade_split"] == split["split"]
    assert one["offices"], "a deliverable is worked by the offices its trades belong to"


def test_the_timesheet_totals_by_trade_and_by_person(app):
    from app.db import insert

    with app.app_context():
        insert("INSERT INTO time_entries (project_id, trade_id, user_id, entry_date, hours, "
               "description) VALUES (1, ?, 1, '2026-09-01', 6, 'setting out')",
               (_trade_id("Marine"),))
        sheet = tools.run("timesheet", 1, {"start": "01/09/2026", "end": "30/09/2026"})

    assert sheet["total_hours"] == 6
    assert sheet["by_trade"][0] == {"trade": "Marine", "hours": 6.0}
    assert sheet["by_person"][0]["hours"] == 6.0


# --- the setup sheet --------------------------------------------------------

def test_an_office_is_set_on_a_trade_and_reaches_the_budget(app):
    with app.app_context():
        staged = tools.run("set_trade", 1, {"trade": "Utilities", "office": "Cairo",
                                            "budget_hours": 120})
        assert "Cairo" in staged["says"] and "120" in staged["says"]
        apply(1, [staged], user_id=1)

        budget = tools.run("budget_summary", 1, {})

    utilities = next(t for t in budget["trades"] if t["name"] == "Utilities")
    assert utilities["office"] == "Cairo"
    assert utilities["budget_hours"] == 120
    cairo = next(o for o in budget["offices"] if o["office"] == "Cairo")
    assert "Utilities" in cairo["trades"]


def test_an_office_that_is_not_one_of_the_offices_is_refused(app):
    with app.app_context():
        with pytest.raises(ToolError) as refused:
            tools.run("set_trade", 1, {"trade": "Marine", "office": "Dubai"})
    assert "Beirut" in str(refused.value) and "Cairo" in str(refused.value)


def test_a_trade_that_is_not_there_yet_is_added(app):
    from app.service import load_trades

    with app.app_context():
        staged = tools.run("set_trade", 1, {"trade": "Project Manager", "office": "Beirut",
                                            "budget_hours": 300})
        assert staged["says"].startswith("Add the trade")
        apply(1, [staged], user_id=1)
        made = next(t for t in load_trades(1) if t["name"] == "Project Manager")

    assert made["office"] == "beirut"
    assert made["budget_hours"] == 300
    assert made["key"] == "project_manager"


def test_project_settings_are_changed_through_the_project_row(app):
    from app.db import query_one

    with app.app_context():
        staged = tools.run("set_project_settings", 1, {"max_revisions": 6, "rework_days": 10,
                                                       "client": "Sibline Cement"})
        apply(1, [staged], user_id=1)
        row = query_one("SELECT * FROM projects WHERE id = 1")

    assert row["max_revisions"] == 6
    assert row["rework_days"] == 10
    assert row["client"] == "Sibline Cement"


def test_a_setting_that_does_not_exist_is_not_smuggled_in(app):
    """The tool takes named settings, not a column name and a value."""
    with app.app_context():
        with pytest.raises(ToolError):
            tools.run("set_project_settings", 1, {"setup_password_hash": "x"})


def test_a_workflow_step_is_added_and_moves_the_planned_dates(app):
    from app.service import load_steps

    with app.app_context():
        staged = tools.run("set_workflow_step", 1, {"step": "Client walkthrough", "percent": 55,
                                                    "anchor": "submission", "offset_days": -3})
        apply(1, [staged], user_id=1)
        steps = load_steps(1)

    added = next(s for s in steps if s["name"] == "Client walkthrough")
    assert added["percent"] == 0.55
    assert added["anchor"] == "submission"
    assert added["offset_days"] == -3


def test_a_team_is_added_with_the_working_week_it_was_asked_for(app):
    from app.service import load_calendars

    with app.app_context():
        staged = tools.run("set_team", 1, {"team": "Cairo studio",
                                           "working_week": "Sunday to Thursday"})
        apply(1, [staged], user_id=1)
        teams = load_calendars(1)

    made = next(c for c in teams if c["name"] == "Cairo studio")
    assert made["workdays"] == "1111001"


def test_a_working_week_nobody_could_read_is_refused_rather_than_guessed(app):
    with app.app_context():
        with pytest.raises(ToolError) as refused:
            tools.run("set_team", 1, {"team": "Nights", "working_week": "whenever"})
    assert "Monday to Friday" in str(refused.value)


def test_a_deliverable_is_added_with_a_split_that_totals_one(app):
    from app.service import load_sections, load_tasks

    with app.app_context():
        staged = tools.run("add_deliverable", 1, {
            "name": "Quay wall cathodic protection", "section": "Marine Design",
            "wbs": "1.99", "weight": 4, "start": "01/11/2026", "submission": "20/11/2026"})
        apply(1, [staged], user_id=1)
        added = next(t for t in load_tasks(1) if t["wbs"] == "1.99")
        marine = next(s for s in load_sections(1) if "Marine Design" in s["name"])

    assert added["section_id"] == marine["id"]
    assert added["name"] == "Quay wall cathodic protection"
    assert added["submission_date"] == "2026-11-20"
    assert abs(sum(added["allocations"].values()) - 1) < 0.005


def test_a_deliverable_is_renamed_and_reweighted(app):
    from app.service import load_tasks

    with app.app_context():
        staged = tools.run("update_deliverable", 1, {"reference": "1.1", "weight": 12,
                                                     "remarks": "issued for tender"})
        apply(1, [staged], user_id=1)
        row = next(t for t in load_tasks(1) if t["wbs"] == "1.1")

    assert row["weight_points"] == 12
    assert row["remarks"] == "issued for tender"


def test_changing_nothing_on_a_deliverable_is_a_question_not_a_write(app):
    with app.app_context():
        with pytest.raises(ToolError):
            tools.run("update_deliverable", 1, {"reference": "1.1"})


# --- the trade split --------------------------------------------------------

def test_a_split_that_does_not_total_a_hundred_is_refused(app):
    with app.app_context():
        with pytest.raises(ToolError) as refused:
            tools.run("set_trade_split", 1, {"reference": "1.1",
                                             "split": {"Marine": 60, "Utilities": 30}})
    assert "100%" in str(refused.value)


def test_one_deliverable_is_resplit(app):
    with app.app_context():
        staged = tools.run("set_trade_split", 1, {"reference": "1.1",
                                                  "split": {"Marine": 70, "Utilities": 30}})
        apply(1, [staged], user_id=1)
        split = _split(1, "1.1")
        wanted = {_trade_id("Marine"): 0.7, _trade_id("Utilities"): 0.3}

    assert split == wanted


# --- the bulk change: a share of everything ---------------------------------

def test_a_trade_takes_a_share_of_every_deliverable_and_the_rest_rescale(app):
    """The project manager has a hand in everything, so a slice of every line
    is theirs — and the trades already on a line keep their proportions to each
    other inside what is left."""
    from app.service import load_tasks

    with app.app_context():
        tools.run("set_trade", 1, {"trade": "Project Manager"})
        apply(1, [tools.run("set_trade", 1, {"trade": "Project Manager"})], user_id=1)
        pm = _trade_id("Project Manager")

        before = _split(1, "1.1")
        staged = tools.run("share_across", 1, {"trade": "Project Manager", "percent": 10})
        assert staged["kind"] == "share_across"
        assert "10% of every deliverable" in staged["says"]
        apply(1, [staged], user_id=1)

        after = _split(1, "1.1")
        every = load_tasks(1)

    assert abs(after[pm] - 0.10) < 1e-9
    for trade_id, share in before.items():
        # 60/40 becomes 54/36, not 60/40 with a tenth bolted on the side — to
        # the nearest whole percent, which is all the split editor holds.
        assert abs(after[trade_id] - share * 0.9) <= 0.0051
    for task in every:
        shares = task["allocations"]
        total = sum(shares.values())
        assert abs(total - 1) < 1e-9, f"{task['wbs']} totals {total}"
        assert abs(shares.get(pm, 0) - 0.10) < 1e-9
        # Whole percents, because a split of 58.5% is one the Setup sheet
        # cannot hold and would refuse to save.
        for value in shares.values():
            assert abs(value * 100 - round(value * 100)) < 1e-9, f"{task['wbs']} has {value}"


def test_the_whole_bulk_change_is_one_thing_to_approve(app):
    """Fifty-five staged lines is a list nobody reads. One is a sentence."""
    from app.assistant.runner import MAX_STAGED

    with app.app_context():
        apply(1, [tools.run("set_trade", 1, {"trade": "Project Manager"})], user_id=1)
        staged = tools.run("share_across", 1, {"trade": "Project Manager", "percent": 10})

    # More lines than the runner would ever let her stage one at a time, and it
    # still arrives as a single thing to read and approve.
    assert len(staged["task_ids"]) > MAX_STAGED
    assert staged["kind"] == "share_across"
    assert staged["note"]["changing"] == len(staged["task_ids"])


def test_a_share_in_tenths_is_refused_rather_than_rounded_behind_your_back(app):
    """The Setup sheet holds whole percents. A split written in tenths reads
    right until somebody presses Save all and is told the line totals 101%."""
    with app.app_context():
        apply(1, [tools.run("set_trade", 1, {"trade": "Project Manager"})], user_id=1)
        with pytest.raises(ToolError) as refused:
            tools.run("share_across", 1, {"trade": "Project Manager", "percent": 12.5})
    assert "whole number of percent" in str(refused.value)
    assert "12 or 13" in str(refused.value)


def test_a_share_can_be_limited_to_one_section(app):
    from app.service import load_sections, load_tasks

    with app.app_context():
        apply(1, [tools.run("set_trade", 1, {"trade": "Project Manager"})], user_id=1)
        pm = _trade_id("Project Manager")
        staged = tools.run("share_across", 1, {"trade": "Project Manager", "percent": 5,
                                               "section": "Marine Design"})
        apply(1, [staged], user_id=1)

        section = next(s for s in load_sections(1) if "Marine Design" in s["name"])
        inside = [t for t in load_tasks(1) if t["section_id"] == section["id"]]
        outside = [t for t in load_tasks(1) if t["section_id"] != section["id"]]

    assert inside and outside
    assert all(abs(t["allocations"].get(pm, 0) - 0.05) < 1e-9 for t in inside)
    assert all(t["allocations"].get(pm, 0) == 0 for t in outside)


def test_a_share_that_is_already_there_is_said_rather_than_done_twice(app):
    with app.app_context():
        apply(1, [tools.run("set_trade", 1, {"trade": "Project Manager"})], user_id=1)
        apply(1, [tools.run("share_across", 1, {"trade": "Project Manager", "percent": 10})],
              user_id=1)
        with pytest.raises(ToolError) as refused:
            tools.run("share_across", 1, {"trade": "Project Manager", "percent": 10})

    assert "already" in str(refused.value)


def test_a_line_with_no_other_trade_is_skipped_and_reported(app):
    """Nothing here can decide what a line worked only by the project manager
    should be split into, so it says so instead of inventing one."""
    from app.service import set_allocations

    with app.app_context():
        apply(1, [tools.run("set_trade", 1, {"trade": "Project Manager"})], user_id=1)
        pm = _trade_id("Project Manager")
        task = tools.run("deliverable", 1, {"reference": "1.2"})
        from app.db import query_one
        task_id = query_one("SELECT id FROM tasks WHERE wbs = '1.2' AND project_id = 1")["id"]
        set_allocations(task_id, 1, {pm: 1.0})

        staged = tools.run("share_across", 1, {"trade": "Project Manager", "percent": 10})
        apply(1, [staged], user_id=1)
        left = _split(1, "1.2")

    assert "skipped" in staged["says"]
    assert task["wbs"] == "1.2"
    assert left == {pm: 1.0}, "the line nobody could split was left exactly as it was"


# --- the timesheet and the rework ------------------------------------------

def test_hours_are_booked_the_way_the_timesheet_books_them(app):
    from app.db import query_one

    with app.app_context():
        staged = tools.run("book_hours", 1, {"date": "02/09/2026", "hours": 7.5,
                                             "trade": "Marine", "deliverable": "1.1",
                                             "description": "quay wall sections"})
        apply(1, [staged], user_id=1)
        row = dict(query_one("SELECT * FROM time_entries WHERE project_id = 1 "
                             "ORDER BY id DESC LIMIT 1"))
        marine = _trade_id("Marine")

    assert row["hours"] == 7.5
    assert row["entry_date"] == "2026-09-02"
    assert row["trade_id"] == marine
    assert row["user_id"] == 1


def test_comments_coming_back_raise_the_revision_and_move_the_submission(app):
    from app.db import query_one
    from app.service import load_steps, set_status

    with app.app_context():
        task = dict(query_one("SELECT * FROM tasks WHERE wbs = '1.1' AND project_id = 1"))
        set_status(task, "submitted", "", "2026-09-01", 1, load_steps(1))

        staged = tools.run("return_comments", 1, {"reference": "1.1", "code": "C",
                                                  "comments_date": "10/09/2026",
                                                  "new_submission": "25/09/2026"})
        apply(1, [staged], user_id=1)
        after = query_one("SELECT * FROM tasks WHERE wbs = '1.1' AND project_id = 1")

    assert after["revision"] == 1
    assert after["submission_date"] == "2026-09-25"


def test_comments_on_something_never_submitted_are_refused_with_a_reason(app):
    with app.app_context():
        staged = tools.run("return_comments", 1, {"reference": "1.1", "code": "B"})
        with pytest.raises(ApplyError) as refused:
            apply(1, [staged], user_id=1)
    assert "submitted" in str(refused.value)


def test_somebody_is_added_to_the_roster(app):
    from app.service import load_attendees

    with app.app_context():
        staged = tools.run("add_attendee", 1, {"name": "Rania Haddad",
                                               "organisation": "Dar", "job_title": "Planner"})
        apply(1, [staged], user_id=1)
        roster = load_attendees(1)

    assert any(a["name"] == "Rania Haddad" and a["job_title"] == "Planner" for a in roster)


# --- the guard the setup sheet keeps ----------------------------------------

def test_a_locked_setup_sheet_refuses_a_setup_change(app):
    """Carmen is another way in, not a way round: the setup sheet's own guard
    still applies to a change she staged."""
    with app.app_context():
        staged = tools.run("set_trade", 1, {"trade": "Marine", "office": "Cairo"})
        with pytest.raises(ApplyError) as refused:
            apply(1, [staged], user_id=1, setup_open=False)

    assert "locked" in str(refused.value).lower()
    assert "Unlock it" in str(refused.value)


def test_a_locked_setup_sheet_does_not_stop_ordinary_work(app):
    """Recording progress is not a setup change, and never needed the password."""
    from app.db import query_one

    with app.app_context():
        staged = tools.run("set_progress", 1, {"reference": "1.1", "percent": 25})
        apply(1, [staged], user_id=1, setup_open=False)
        row = query_one("SELECT actual_pct FROM tasks WHERE wbs = '1.1' AND project_id = 1")

    assert abs(row["actual_pct"] - 0.25) < 1e-9


def test_every_setup_change_is_named_in_the_guard():
    """A kind missing from the list is a setup change that applies while the
    sheet is locked — the sort of gap nobody notices until it matters."""
    from app.assistant import edits

    staged_by_setup_tools = {
        "set_project_settings", "set_trade", "remove_trade", "set_section",
        "set_workflow_step", "remove_workflow_step", "set_team", "add_deliverable",
        "update_deliverable", "remove_deliverable", "set_trade_split", "share_across",
    }
    assert edits.SETUP_KINDS == staged_by_setup_tools
