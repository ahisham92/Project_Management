"""The resource plan: what a trade may spend, when, and how many people that is.

The engine is arithmetic on dates and weights, so most of this is checked
without a database at all — a handful of dicts shaped like the rows the app
passes in. The last few go through the app itself, because a tab that renders
and a number that is right are two different claims.
"""

from __future__ import annotations

from datetime import date

import pytest

from app import resources


def a_task(task_id: int, points: float, allocations: dict[int, float],
           start: str, submission: str, workflow: bool = False) -> dict:
    return {
        "id": task_id, "wbs": str(task_id), "name": f"Line {task_id}",
        "weight_points": points, "weight_pct": points,
        "allocations": allocations,
        "start_date": start, "submission_date": submission,
        "tracking": "workflow" if workflow else "percent",
        "calendar_id": None,
    }


def a_trade(trade_id: int, name: str, budget: float) -> dict:
    return {"id": trade_id, "name": name, "budget_hours": budget,
            "office": "", "color": ""}


# --- the ceiling ------------------------------------------------------------

def test_the_target_margin_comes_off_the_top():
    trades = [a_trade(1, "Marine", 1000)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-02-27")]

    held = resources.ceilings(tasks, trades, target=0.12)
    assert sum(held[1].values()) == pytest.approx(880)


def test_a_ceiling_splits_by_weight_times_the_trades_share():
    """A line that is 6% of the project and 60% ours is worth twice one that
    is 6% and 30% — weight and share both count, and they multiply."""
    trades = [a_trade(1, "Marine", 1000)]
    tasks = [a_task(10, 6, {1: 0.6}, "2026-01-05", "2026-02-27"),
             a_task(11, 6, {1: 0.3}, "2026-01-05", "2026-02-27")]

    held = resources.ceilings(tasks, trades, target=0.0)
    assert held[1][10] == pytest.approx(held[1][11] * 2)
    assert held[1][10] + held[1][11] == pytest.approx(1000)


def test_a_trade_allocated_to_nothing_plans_nothing():
    trades = [a_trade(1, "Marine", 1000), a_trade(2, "Utilities", 400)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-02-27")]

    held = resources.ceilings(tasks, trades, target=0.12)
    assert held[2] == {}
    # ...and its hours are not quietly handed to somebody else.
    assert sum(held[1].values()) == pytest.approx(880)


# --- when the hours are worked ----------------------------------------------

WORKFLOW = (
    {"key": "design", "name": "Design start", "percent": 0.10,
     "anchor": "start", "offset_days": 0, "sort_order": 1},
    {"key": "idc", "name": "IDC", "percent": 0.40,
     "anchor": "submission", "offset_days": -14, "sort_order": 2},
    {"key": "comments", "name": "Comments addressed", "percent": 0.60,
     "anchor": "submission", "offset_days": -5, "sort_order": 3},
    {"key": "submitted", "name": "Submitted", "percent": 0.80,
     "anchor": "submission", "offset_days": 0, "sort_order": 4},
    {"key": "code_a", "name": "Code A", "percent": 1.00,
     "anchor": "submission", "offset_days": 14, "sort_order": 5},
)


def test_a_flat_line_is_flat():
    """No workflow, no ramp: a transmittal or a meeting is worked evenly."""
    task = a_task(10, 6, {1: 1.0}, "2026-01-05", "2026-01-16")
    laid = resources.spread(task, 80, WORKFLOW, None)

    assert sum(laid.values()) == pytest.approx(80)
    assert len(set(round(v, 6) for v in laid.values())) == 1


def test_the_hours_rise_towards_the_submission():
    task = a_task(10, 6, {1: 1.0}, "2026-01-05", "2026-03-06", workflow=True)
    parts = resources.stretches(task, WORKFLOW, None)

    assert parts, "a workflow line has stretches"
    assert sum(p["share"] for p in parts) == pytest.approx(1.0)
    # Per working day, the last stretch is the busiest and the first the quietest.
    def per_day(part):
        return part["share"] / len(resources._working_days(part["from"], part["to"]))

    rates = [per_day(part) for part in parts]
    assert rates[-1] > rates[0]


def test_nothing_after_the_submission_earns_hours():
    """The last stretch of a design workflow is the client reading it."""
    task = a_task(10, 6, {1: 1.0}, "2026-01-05", "2026-03-06", workflow=True)
    laid = resources.spread(task, 100, WORKFLOW, None)

    assert max(laid) <= date(2026, 3, 6)
    assert sum(laid.values()) == pytest.approx(100)


def test_no_single_day_swallows_the_deliverable():
    """The regression that made this worth writing: a step landing on the start
    date used to put a fortnight of hours into one Monday."""
    task = a_task(10, 6, {1: 1.0}, "2026-01-05", "2026-03-06", workflow=True)
    laid = resources.spread(task, 400, WORKFLOW, None)

    assert max(laid.values()) < 400 * 0.25


def test_a_milestone_lands_on_its_day():
    task = a_task(10, 1, {1: 1.0}, "2026-01-05", "2026-01-05")
    laid = resources.spread(task, 8, WORKFLOW, None)

    assert laid == {date(2026, 1, 5): pytest.approx(8)}


def test_a_line_with_no_dates_is_not_planned():
    task = a_task(10, 6, {1: 1.0}, "", "")
    assert resources.spread(task, 100, WORKFLOW, None) == {}


# --- weeks and people -------------------------------------------------------

def test_the_week_opens_on_the_day_the_project_says():
    thursday = date(2026, 1, 8)
    assert resources.week_of(thursday, 0) == date(2026, 1, 5)      # Monday
    assert resources.week_of(thursday, 6) == date(2026, 1, 4)      # Sunday


def test_hours_become_people_rounded_up():
    """Three-quarters of a person is still a person you have to find."""
    project = {"target_margin_pct": 0, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 100)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-01-09")]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    week = made["weeks"][0]
    assert week["hours"] == pytest.approx(100)
    assert week["engineers"] == pytest.approx(2.5)
    assert week["people"] == 3


def test_the_plan_never_exceeds_the_ceiling():
    project = {"target_margin_pct": 12, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 1000), a_trade(2, "Geotech", 400)]
    tasks = [a_task(10, 60, {1: 0.7, 2: 0.3}, "2026-01-05", "2026-03-06", workflow=True),
             a_task(11, 40, {1: 1.0}, "2026-02-02", "2026-04-10", workflow=True)]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    assert made["budget_hours"] == pytest.approx(1400)
    assert made["ceiling_hours"] == pytest.approx(1232)
    assert made["planned_hours"] == pytest.approx(1232)
    # Every week's hours add back up to the ceiling, nothing lost in the spread.
    assert sum(w["hours"] for w in made["weeks"]) == pytest.approx(1232)


def test_booked_hours_are_read_against_the_plan():
    project = {"target_margin_pct": 0, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 200)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-01-16")]
    booked = {("2026-01-05", 1): 90.0}

    made = resources.plan(project, tasks, trades, WORKFLOW, None, booked, 0)
    assert made["spent_hours"] == pytest.approx(90)
    assert made["left_hours"] == pytest.approx(110)
    assert made["trades"][0]["spent_hours"] == pytest.approx(90)


def test_a_week_only_booked_never_planned_still_shows():
    """Hours charged to a week nothing was planned in are the whole reason to
    look, so they cannot be dropped for having no plan to sit beside."""
    project = {"target_margin_pct": 0, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 200)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-02-02", "2026-02-06")]
    booked = {("2025-12-01", 1): 12.0}

    made = resources.plan(project, tasks, trades, WORKFLOW, None, booked, 0)
    assert made["weeks"][0]["week"] == "2025-12-01"
    assert made["weeks"][0]["spent_hours"] == pytest.approx(12)


def test_a_budgeted_trade_with_no_work_is_named_not_hidden():
    project = {"target_margin_pct": 12, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 1000), a_trade(2, "Utilities", 400)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-02-27")]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    assert made["unplanned"] == ["Utilities"]


def test_the_curve_is_cumulative():
    project = {"target_margin_pct": 0, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 300)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-01-23")]

    points = resources.curve(resources.plan(project, tasks, trades, WORKFLOW, None, None, 0))
    assert [p["planned"] for p in points] == sorted(p["planned"] for p in points)
    assert points[-1]["planned"] == pytest.approx(300)


# --- through the app --------------------------------------------------------

def test_the_tab_reads(signed_in):
    answer = signed_in.get("/projects/1/resources")
    assert answer.status_code == 200
    page = answer.get_data(as_text=True)
    assert "Resources planning" in page
    assert "Engineers per week" in page
    assert "Ceiling per deliverable" in page


def test_the_dashboard_carries_the_hours_curve(signed_in):
    page = signed_in.get("/projects/1/").get_data(as_text=True)
    assert "Planned hours against spent hours" in page


def test_the_settings_hold_the_target_and_the_working_week(signed_in, app):
    from app.db import query_one

    with app.app_context():
        before = dict(query_one("SELECT * FROM projects WHERE id = 1"))
    from .test_web import unlock

    unlock(signed_in)
    signed_in.post("/projects/1/settings", data={
        "name": before["name"], "code": before["code"], "client": before["client"],
        "duration_months": before["duration_months"],
        "target_margin_pct": "20", "hours_per_week": "45",
        "status": "active",
    })
    with app.app_context():
        after = dict(query_one("SELECT * FROM projects WHERE id = 1"))
    assert after["target_margin_pct"] == pytest.approx(20)
    assert after["hours_per_week"] == pytest.approx(45)


def test_a_bigger_margin_leaves_less_to_plan(signed_in, app):
    from app.db import execute
    from app.service import resource_plan

    with app.app_context():
        from app.db import query_one

        execute("UPDATE projects SET target_margin_pct = 0 WHERE id = 1")
        whole = resource_plan(dict(query_one("SELECT * FROM projects WHERE id = 1")))
        execute("UPDATE projects SET target_margin_pct = 25 WHERE id = 1")
        quarter = resource_plan(dict(query_one("SELECT * FROM projects WHERE id = 1")))

    assert quarter["ceiling_hours"] == pytest.approx(whole["ceiling_hours"] * 0.75)
    assert quarter["margin_hours"] > 0


def test_carmen_can_read_the_plan(app):
    from app.assistant.tools import resource_plan

    with app.app_context():
        answer = resource_plan(1, weeks=4)

    assert answer["ceiling_hours"] > 0
    assert answer["weeks_shown"] <= 4
    assert answer["peak_engineers"] > 0
