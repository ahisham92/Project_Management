"""The calculation engine.

Figures that do not depend on the schedule — weight points, trade scope weights,
earned progress and earned man-months — are still checked against the source
control workbook. Planned progress now comes from the design workflow's step
dates rather than a linear ramp over elapsed months, so those figures are
asserted against the workflow model instead.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.calc import (
    build_period_report,
    build_s_curve,
    compute_project,
    elapsed_months,
    parse_date,
    planned_pct_on,
    task_schedule,
)
from app.workflow import default_steps, ordered

SEED = json.loads((Path(__file__).resolve().parent.parent / "seed" / "sibline-port.json").read_text())
DATA_DATE = "2026-09-01"

TRADES = [dict(t, id=i + 1) for i, t in enumerate(SEED["trades"])]
TRADE_ID = {t["key"]: t["id"] for t in TRADES}
PROJECT = SEED["project"]
STEPS = [dict(s, id=i + 1) for i, s in enumerate(default_steps())]

_NTP = parse_date(PROJECT["ntp_date"])
_PER_MONTH = PROJECT["days_per_month"]


def _as_date(months: float) -> str:
    return (_NTP + timedelta(days=months * _PER_MONTH)).isoformat()


def _tasks(tracking: str | None = None) -> list[dict]:
    """The seeded deliverables, with the schedule converted to real dates.

    Meetings and milestones are tracked as a simple percentage rather than
    through the design workflow — the same rule the seeder applies.
    """
    out = []
    for index, task in enumerate(SEED["tasks"]):
        milestone = task["finish_month"] <= task["start_month"] or "(milestone)" in task["name"].lower()
        mode = tracking or ("simple" if milestone else "workflow")
        out.append(
            dict(
                task,
                id=index + 1,
                start_date=_as_date(task["start_month"]),
                submission_date=_as_date(task["finish_month"]),
                tracking=mode,
                status_key="",
                revision=0,
                allocations={TRADE_ID[k]: pct for k, pct in task["allocations"].items() if pct > 0},
            )
        )
    return out


TASKS = _tasks()


def close(actual, expected, tol=1e-9):
    assert actual == pytest.approx(expected, abs=tol), f"expected {expected}, got {actual}"


# --- figures the workbook still anchors ------------------------------------

def test_weight_points_total_100():
    close(sum(t["weight_points"] for t in SEED["tasks"]), 100, 1e-6)


def test_every_trade_allocation_totals_100_pct():
    for task in SEED["tasks"]:
        if task["weight_points"] == 0:
            continue
        close(sum(task["allocations"].values()), 1, 1e-6)


def test_earned_progress_matches_the_workbook():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, steps=STEPS)
    close(result["totals"]["earned_progress"], 0.005)


def test_trade_scope_weights_match_the_workbook():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, steps=STEPS)
    by = {t["key"]: t for t in result["trades"]}
    close(by["marine"]["scope_weight_pct"], 0.35145, 1e-9)
    close(by["geotechnical"]["scope_weight_pct"], 0.212, 1e-9)
    close(by["marine_structures"]["scope_weight_pct"], 0.37565, 1e-9)
    close(by["utilities"]["scope_weight_pct"], 0.0609, 1e-9)
    close(sum(t["scope_weight_pct"] for t in result["trades"]), 1)
    close(sum(t["earned_contribution"] for t in result["trades"]), result["totals"]["earned_progress"])


def test_earned_hours_follow_the_workbook_man_month_figures():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, steps=STEPS)
    by = {t["key"]: t for t in result["trades"]}
    mm = PROJECT["hours_per_month"]
    close(by["marine"]["earned_hours"] / mm, 0.02560819462227912)
    close(by["geotechnical"]["earned_hours"] / mm, 0.017688679245283015)
    close(by["marine_structures"]["earned_hours"] / mm, 0.023958471981898037)
    close(by["utilities"]["earned_hours"] / mm, 0.004105090311986863)
    close(result["budget"]["earned_hours"] / mm, 0.07136043616144702)
    close(result["budget"]["budget_hours"], 15 * mm)


def test_elapsed_months_still_reports_the_workbook_convention():
    # Only the headline "months elapsed" uses this; planned progress comes from
    # the workflow dates now.
    close(elapsed_months(PROJECT["ntp_date"], DATA_DATE, _PER_MONTH, 1), 0.06570841889117043)
    close(elapsed_months(PROJECT["ntp_date"], DATA_DATE, _PER_MONTH, 0), 1 / _PER_MONTH)


# --- the design workflow ----------------------------------------------------

def test_the_default_workflow_matches_the_agreed_steps():
    steps = ordered(STEPS)
    assert [(s["name"], s["percent"]) for s in steps] == [
        ("Design started", 0.10),
        ("IDC provided", 0.40),
        ("Comments addressed", 0.60),
        ("Submitted to client", 0.80),
        ("Code A received", 1.00),
    ]


def test_step_dates_hang_off_the_start_and_submission_dates():
    task = {"start_date": "2026-08-31", "submission_date": "2026-09-30", "tracking": "workflow"}
    plan = {s["key"]: s["date"] for s in task_schedule(task, STEPS)}
    assert plan["design_start"] == "2026-08-31"        # on the start date
    assert plan["idc"] == "2026-09-25"                 # 5 days before submission
    assert plan["comments_addressed"] == "2026-09-28"  # 2 days before submission
    assert plan["submitted"] == "2026-09-30"           # the submission date
    assert plan["code_a"] == "2026-10-14"              # 14 days after submission


def test_planned_percent_lands_exactly_on_each_step_date():
    task = {"start_date": "2026-08-31", "submission_date": "2026-09-30", "tracking": "workflow"}
    plan = task_schedule(task, STEPS)
    for step in plan:
        close(planned_pct_on(task, step["date"], STEPS), step["percent"])
    # Before the first step there is nothing planned; after the last it is complete.
    close(planned_pct_on(task, "2026-08-30", STEPS), 0)
    close(planned_pct_on(task, "2026-12-31", STEPS), 1)


def test_planned_percent_holds_a_step_until_the_next_one_falls_due():
    """A submission cycle moves in steps, so the planned figure only ever reads
    one of the step values — never something in between."""
    task = {"start_date": "2026-08-31", "submission_date": "2026-09-30", "tracking": "workflow"}
    reading = {d: planned_pct_on(task, d, STEPS) for d in [
        "2026-08-30", "2026-08-31", "2026-09-10", "2026-09-24", "2026-09-25",
        "2026-09-27", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-13", "2026-10-14",
    ]}
    assert list(reading.values()) == [0.0, 0.10, 0.10, 0.10, 0.40, 0.40, 0.60, 0.60, 0.80, 0.80, 1.00]


def test_planned_percent_never_reads_a_value_between_steps():
    task = {"start_date": "2026-08-31", "submission_date": "2026-09-30", "tracking": "workflow"}
    allowed = {0.0} | {s["percent"] for s in STEPS}
    day = parse_date("2026-08-25")
    for _ in range(80):
        assert planned_pct_on(task, day.isoformat(), STEPS) in allowed
        day += timedelta(days=1)


def test_editing_a_step_offset_moves_the_planned_date():
    task = {"start_date": "2026-08-31", "submission_date": "2026-09-30", "tracking": "workflow"}
    steps = [dict(s) for s in STEPS]
    next(s for s in steps if s["key"] == "idc")["offset_days"] = -10
    plan = {s["key"]: s["date"] for s in task_schedule(task, steps)}
    assert plan["idc"] == "2026-09-20"


def test_a_simple_line_ramps_between_its_two_dates():
    task = {"start_date": "2026-01-01", "submission_date": "2026-01-11", "tracking": "simple"}
    close(planned_pct_on(task, "2026-01-01", STEPS), 0)
    close(planned_pct_on(task, "2026-01-06", STEPS), 0.5)
    close(planned_pct_on(task, "2026-01-11", STEPS), 1)


def test_a_milestone_steps_to_100_on_its_date():
    task = {"start_date": "2026-01-10", "submission_date": "2026-01-10", "tracking": "simple"}
    close(planned_pct_on(task, "2026-01-09", STEPS), 0)
    close(planned_pct_on(task, "2026-01-10", STEPS), 1)


# --- the project as a whole -------------------------------------------------

def test_overall_planned_earned_and_variance():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, steps=STEPS)
    totals = result["totals"]
    # Six workflow lines have reached their start date, so each is planned at
    # 10% of its weight; the kick-off milestone is due (100% of its 1%) and the
    # first bi-weekly meeting is one day into its fifteen.
    close(totals["planned_progress"], 0.020266666666666655, 1e-12)
    close(totals["earned_progress"], 0.005)
    close(totals["variance"], -0.015266666666666658, 1e-12)
    close(sum(t["planned_contribution"] for t in result["trades"]), totals["planned_progress"])


def test_every_planned_figure_is_a_step_value():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, steps=STEPS)
    allowed = {0.0} | {s["percent"] for s in STEPS}
    for row in result["tasks"]:
        if row["uses_workflow"]:
            assert row["planned_pct"] in allowed, f"{row['wbs']} planned {row['planned_pct']}"


def test_late_and_behind_counts():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, horizon_days=2, steps=STEPS)
    assert result["totals"]["late_count"] == 1      # the kick-off meeting, due at NTP, 50% done
    assert result["totals"]["upcoming_count"] == 0
    assert result["totals"]["behind_count"] == 8
    close(result["totals"]["weight_at_risk"], 0.01)


def test_the_late_line_is_the_kick_off_meeting():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, steps=STEPS)
    late = [t for t in result["tasks"] if t["is_late"]]
    assert len(late) == 1
    assert late[0]["wbs"] == "1.6"
    assert late[0]["days_late"] == 1
    assert late[0]["due_date"] == "2026-08-31"


def test_a_horizon_of_none_shows_every_remaining_submission():
    windowed = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, horizon_days=30, steps=STEPS)
    everything = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, horizon_days=None, steps=STEPS)
    assert windowed["totals"]["upcoming_count"] == 8
    assert everything["totals"]["upcoming_count"] == 54
    assert everything["horizon_days"] is None


def test_spent_hours_drive_cpi_eac_and_vac():
    result = compute_project(
        PROJECT, TASKS, TRADES, DATA_DATE, spent_by_trade={TRADE_ID["marine"]: 200}, steps=STEPS
    )
    marine = next(t for t in result["trades"] if t["key"] == "marine")
    assert marine["spent_hours"] == 200
    close(marine["cpi"], marine["earned_hours"] / 200)
    close(marine["eac_hours"], marine["budget_hours"] / marine["cpi"])
    close(marine["vac_hours"], marine["budget_hours"] - marine["eac_hours"])
    assert marine["budget_status"] == "Over-burning"
    idle = next(t for t in result["trades"] if t["key"] == "utilities")
    assert idle["cpi"] is None
    assert idle["budget_status"] == "No spend booked"


def test_a_fully_complete_project_earns_100_pct():
    done = [dict(t, actual_pct=1) for t in TASKS]
    result = compute_project(PROJECT, done, TRADES, DATA_DATE, steps=STEPS)
    close(result["totals"]["earned_progress"], 1)
    assert result["totals"]["late_count"] == 0
    assert result["totals"]["behind_count"] == 0


# --- submissions, approvals and revisions -----------------------------------

def _one_task(**overrides) -> list[dict]:
    task = {
        "id": 1, "wbs": "1.1", "name": "Drawing set", "weight_points": 1,
        "start_date": "2026-01-01", "submission_date": "2026-02-01",
        "tracking": "workflow", "status_key": "", "revision": 0, "actual_pct": 0.0,
        "allocations": {},
    }
    task.update(overrides)
    return [task]


def test_a_deliverable_awaiting_code_a_is_judged_on_the_approval_date():
    tasks = _one_task(status_key="submitted", actual_pct=0.8)
    # Submitted on time: the Code A date (15 Feb) is what it is measured against.
    on_time = compute_project(PROJECT, tasks, [], "2026-02-05", steps=STEPS)["tasks"][0]
    assert on_time["due_reason"] == "approval"
    assert on_time["due_date"] == "2026-02-15"
    assert not on_time["is_late"]

    overdue = compute_project(PROJECT, tasks, [], "2026-02-20", steps=STEPS)["tasks"][0]
    assert overdue["is_late"] and overdue["days_late"] == 5


def test_a_deliverable_not_yet_submitted_is_judged_on_the_submission_date():
    tasks = _one_task(status_key="idc", actual_pct=0.4)
    row = compute_project(PROJECT, tasks, [], "2026-02-05", steps=STEPS)["tasks"][0]
    assert row["due_reason"] == "submission"
    assert row["due_date"] == "2026-02-01"
    assert row["is_late"] and row["days_late"] == 4


def test_a_revision_is_flagged_and_capped():
    project = dict(PROJECT, max_revisions=10)
    row = compute_project(project, _one_task(revision=3, status_key="comments_addressed", actual_pct=0.6),
                          [], "2026-02-05", steps=STEPS)["tasks"][0]
    assert row["in_rework"] and not row["at_revision_limit"]

    at_limit = compute_project(project, _one_task(revision=10, status_key="comments_addressed", actual_pct=0.6),
                               [], "2026-02-05", steps=STEPS)["tasks"][0]
    assert at_limit["at_revision_limit"]

    totals = compute_project(project, _one_task(revision=10, status_key="submitted", actual_pct=0.8),
                             [], "2026-02-05", steps=STEPS)["totals"]
    assert totals["rework_count"] == 1
    assert totals["at_limit_count"] == 1


def test_a_simple_line_is_pro_rata_by_time_and_takes_a_typed_percentage():
    """Meetings and milestones do not follow the submission cycle, so their plan
    is simply time elapsed between the two dates."""
    task = {"start_date": "2026-01-01", "submission_date": "2026-01-11",
            "tracking": "simple", "actual_pct": 0.3, "weight_points": 1, "id": 1, "allocations": {}}
    row = compute_project(PROJECT, [task], [], "2026-01-05", steps=STEPS)["tasks"][0]
    close(row["planned_pct"], 0.4)          # 4 of 10 days
    close(row["actual_pct"], 0.3)           # exactly what was typed
    assert not row["uses_workflow"]


def test_a_resubmission_moves_the_planned_dates():
    first = _one_task(status_key="submitted", actual_pct=0.8)
    resubmitted = _one_task(status_key="comments_addressed", actual_pct=0.6, revision=1,
                            submission_date="2026-03-01")
    before = compute_project(PROJECT, first, [], "2026-02-05", steps=STEPS)["tasks"][0]
    after = compute_project(PROJECT, resubmitted, [], "2026-02-05", steps=STEPS)["tasks"][0]
    assert before["approval_due_date"] == "2026-02-15"
    assert after["approval_due_date"] == "2026-03-15"
    assert after["submission_date"] == "2026-03-01"
    # Rework pushes planned progress back down for that line.
    assert after["planned_pct"] < before["planned_pct"]


# --- curves and period reports ----------------------------------------------

def test_s_curve_planned_rises_to_100_pct_and_earned_stops_at_the_data_date():
    history = [
        {"task_id": t["id"], "actual_pct": t["actual_pct"], "data_date": "2026-08-31"}
        for t in TASKS
        if t["actual_pct"] > 0
    ]
    points = build_s_curve(PROJECT, TASKS, history, DATA_DATE, steps=STEPS, samples=30)
    close(points[-1]["planned"], 1, 1e-9)
    for earlier, later in zip(points, points[1:]):
        assert later["planned"] >= earlier["planned"] - 1e-12, "planned curve must not go backwards"
    assert points[-1]["earned"] is None, "no earned value beyond the data date"
    assert any(p["date"] == DATA_DATE for p in points), "the data date is always sampled"
    assert points[0]["date"] == "2026-08-31"


def test_period_report_attributes_progress_to_the_right_period_and_trades():
    kickoff = next(t for t in TASKS if t["wbs"] == "1.6")
    history = [
        {"task_id": kickoff["id"], "actual_pct": 0.25, "data_date": "2026-08-31"},
        {"task_id": kickoff["id"], "actual_pct": 0.5, "data_date": "2026-09-01"},
    ]
    period = build_period_report(PROJECT, TASKS, TRADES, history, "2026-09-01", "2026-09-01", steps=STEPS)
    close(period["earned_at_start"], 0.01 * 0.25)
    close(period["earned_at_end"], 0.01 * 0.5)
    close(period["earned_in_period"], 0.01 * 0.25)
    marine = next(t for t in period["trade_earned_in_period"] if t["name"] == "Marine")
    close(marine["earned_in_period"], 0.01 * 0.25 * 0.3)
    assert next(t for t in period["tasks"] if t["wbs"] == "1.6")["period_status"] == "Advanced in period"


def test_period_report_shows_rework_as_going_backwards():
    task = next(t for t in TASKS if t["wbs"] == "2.3")
    history = [
        {"task_id": task["id"], "actual_pct": 0.8, "data_date": "2026-09-01"},
        {"task_id": task["id"], "actual_pct": 0.6, "data_date": "2026-09-10"},
    ]
    period = build_period_report(PROJECT, TASKS, TRADES, history, "2026-09-05", "2026-09-15", steps=STEPS)
    row = next(t for t in period["tasks"] if t["wbs"] == "2.3")
    assert row["period_status"] == "Went back — rework"
    assert row["delta_actual"] < 0
