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
           start: str, submission: str, workflow: bool = False,
           approved: bool = False, revision: int = 0) -> dict:
    return {
        "id": task_id, "wbs": str(task_id), "name": f"Line {task_id}",
        "weight_points": points, "weight_pct": points,
        "allocations": allocations,
        "start_date": start, "submission_date": submission,
        "tracking": "workflow" if workflow else "percent",
        "calendar_id": None,
        "is_approved": approved, "is_complete": approved, "revision": revision,
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


def test_a_week_is_counted_trade_by_trade_not_all_at_once():
    """Three trades each wanting four tenths of a person is three people, not
    two — they are three different people, from three different teams."""
    project = {"target_margin_pct": 0, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 16), a_trade(2, "Geotech", 16),
              a_trade(3, "Utilities", 16)]
    tasks = [a_task(10, 100, {1: 1 / 3, 2: 1 / 3, 3: 1 / 3}, "2026-01-05", "2026-01-09")]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    week = made["weeks"][0]
    assert week["hours"] == pytest.approx(48)
    assert week["engineers"] == pytest.approx(1.2)     # the hours, divided once
    assert week["people"] == 3                         # the rota, trade by trade
    assert made["peak_people"] == 3
    assert made["average_people"] == pytest.approx(3)


def test_the_plan_never_exceeds_the_ceiling():
    """The ceiling, less whatever the comments reserve is holding."""
    project = {"target_margin_pct": 12, "hours_per_week": 40, "comments_reserve_pct": 0}
    trades = [a_trade(1, "Marine", 1000), a_trade(2, "Geotech", 400)]
    tasks = [a_task(10, 60, {1: 0.7, 2: 0.3}, "2026-01-05", "2026-03-06", workflow=True),
             a_task(11, 40, {1: 1.0}, "2026-02-02", "2026-04-10", workflow=True)]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    assert made["budget_hours"] == pytest.approx(1400)
    assert made["ceiling_hours"] == pytest.approx(1232)
    assert made["planned_hours"] == pytest.approx(1232)
    # Every week's hours add back up to the ceiling, nothing lost in the spread.
    assert sum(w["hours"] for w in made["weeks"]) == pytest.approx(1232)


def test_the_reserve_comes_out_of_what_is_planned():
    project = {"target_margin_pct": 0, "hours_per_week": 40, "comments_reserve_pct": 15}
    trades = [a_trade(1, "Marine", 1000)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-03-06", workflow=True)]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    assert made["ceiling_hours"] == pytest.approx(1000)
    assert made["held_hours"] == pytest.approx(150)
    assert made["planned_hours"] == pytest.approx(850)
    assert sum(w["hours"] for w in made["weeks"]) == pytest.approx(850)


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


# --- the comments reserve ---------------------------------------------------

def test_only_a_workflow_line_holds_a_reserve():
    """A transmittal has no client review to answer, so holding a sixth of it
    back would be inventing a saving that cannot happen."""
    trades = [a_trade(1, "Marine", 1000)]
    tasks = [a_task(10, 50, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True),
             a_task(11, 50, {1: 1.0}, "2026-01-05", "2026-02-27")]
    allowed = resources.ceilings(tasks, trades, target=0.0)

    kept = resources.reserves(tasks, allowed, 0.15)
    assert kept[1][10]["hours"] == pytest.approx(75)
    assert kept[1][11]["hours"] == pytest.approx(0)
    assert kept[1][11]["state"] == "none"


def test_a_clean_code_a_releases_the_reserve_and_a_code_b_spends_it():
    trades = [a_trade(1, "Marine", 900)]
    tasks = [a_task(10, 30, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=0),
             a_task(11, 30, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=2),
             a_task(12, 30, {1: 1.0}, "2026-03-02", "2026-04-24", workflow=True)]
    allowed = resources.ceilings(tasks, trades, target=0.0)

    kept = resources.reserves(tasks, allowed, 0.15)
    assert kept[1][10]["state"] == "released"     # right first time
    assert kept[1][11]["state"] == "consumed"     # the rework needed it
    assert kept[1][12]["state"] == "held"         # nobody has answered yet


def test_a_consumed_reserve_stays_on_the_line_that_used_it():
    """Answering comments was real work, and its hours were spent there."""
    trades = [a_trade(1, "Marine", 600)]
    tasks = [a_task(10, 50, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=1),
             a_task(11, 50, {1: 1.0}, "2026-03-02", "2026-04-24", workflow=True)]
    allowed = resources.ceilings(tasks, trades, target=0.0)
    kept = resources.reserves(tasks, allowed, 0.15)

    working, notes = resources.redistribute(allowed, kept, on=True)
    assert working[1][10] == pytest.approx(300)     # its whole ceiling, reserve included
    assert notes == []                              # nothing was released to move


def test_a_saving_is_named_even_when_it_is_not_shared_out():
    """Somebody deciding whether to redistribute wants to see where the hours
    came from before they press the button, not after."""
    trades = [a_trade(1, "Marine", 900)]
    tasks = [a_task(10, 30, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=0),
             a_task(11, 30, {1: 1.0}, "2026-03-02", "2026-04-24", workflow=True)]
    allowed = resources.ceilings(tasks, trades, target=0.0)
    kept = resources.reserves(tasks, allowed, 0.15)

    # Two equal lines off a 900 h budget: 450 h each, 15% of which is 67.5 h.
    _held, quiet = resources.redistribute(allowed, kept, on=False)
    assert quiet[0]["hours"] == pytest.approx(67.5)
    assert quiet[0]["shared"] is False
    assert quiet[0]["lines"] == 0            # nothing moved
    assert quiet[0]["open_lines"] == 1       # but this is what it would move into
    assert quiet[0]["from"][0]["wbs"] == "10"


# --- redistribution ---------------------------------------------------------

def test_released_hours_go_back_into_the_same_trade_s_open_lines():
    trades = [a_trade(1, "Marine", 900)]
    tasks = [a_task(10, 30, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=0),
             a_task(11, 30, {1: 1.0}, "2026-03-02", "2026-04-24", workflow=True),
             a_task(12, 30, {1: 1.0}, "2026-05-04", "2026-06-26", workflow=True)]
    allowed = resources.ceilings(tasks, trades, target=0.0)
    kept = resources.reserves(tasks, allowed, 0.15)

    held, _ = resources.redistribute(allowed, kept, on=False)
    shared, notes = resources.redistribute(allowed, kept, on=True)

    # 45 h released off a 300 h line, split evenly over two equal open lines.
    assert held[1][11] == pytest.approx(255)
    assert shared[1][11] == pytest.approx(255 + 22.5)
    assert shared[1][12] == pytest.approx(255 + 22.5)
    # And nothing lands back on the line that is already finished with.
    assert shared[1][10] == pytest.approx(held[1][10])
    assert notes[0]["hours"] == pytest.approx(45)
    assert notes[0]["shared"] is True
    assert notes[0]["from"][0]["wbs"] == "10"


def test_one_trade_s_saving_is_never_handed_to_another():
    """Marine finishing cleanly is Marine's slack. Giving it to Geotechnical
    would tell the team that did the careful work it bought somebody else room."""
    trades = [a_trade(1, "Marine", 600), a_trade(2, "Geotech", 600)]
    tasks = [a_task(10, 50, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=0),
             a_task(11, 50, {1: 1.0}, "2026-03-02", "2026-04-24", workflow=True),
             a_task(12, 50, {2: 1.0}, "2026-03-02", "2026-04-24", workflow=True)]
    allowed = resources.ceilings(tasks, trades, target=0.0)
    kept = resources.reserves(tasks, allowed, 0.15)

    before, _ = resources.redistribute(allowed, kept, on=False)
    after, notes = resources.redistribute(allowed, kept, on=True)

    assert after[1][11] > before[1][11]                   # Marine gains
    assert after[2][12] == pytest.approx(before[2][12])   # Geotech does not
    assert [n["trade_id"] for n in notes] == [1]


def test_the_notes_say_which_lines_paid_for_it():
    project = {"target_margin_pct": 0, "hours_per_week": 40,
               "comments_reserve_pct": 15, "redistribute_savings": 1}
    trades = [a_trade(1, "Marine", 900)]
    tasks = [a_task(10, 30, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=0),
             a_task(11, 30, {1: 1.0}, "2026-03-02", "2026-04-24", workflow=True)]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    note = made["notes"][0]
    assert note["trade"] == "Marine"
    assert note["lines"] == 1
    assert [row["wbs"] for row in note["from"]] == ["10"]
    assert made["released_hours"] == pytest.approx(67.5)


def test_a_finalised_line_is_left_alone():
    project = {"target_margin_pct": 0, "hours_per_week": 40,
               "comments_reserve_pct": 15, "redistribute_savings": 1}
    trades = [a_trade(1, "Marine", 900)]
    tasks = [a_task(10, 30, {1: 1.0}, "2026-01-05", "2026-02-27", workflow=True,
                    approved=True, revision=0),
             a_task(11, 30, {1: 1.0}, "2026-03-02", "2026-04-24", workflow=True,
                    approved=True, revision=1),
             a_task(12, 30, {1: 1.0}, "2026-05-04", "2026-06-26", workflow=True)]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    rows = {row["wbs"]: row for row in resources.task_rows(made, tasks, trades)}
    # The whole release lands on the one line still open.
    assert rows["12"]["hours"] == pytest.approx(255 + 45)
    assert rows["11"]["hours"] == pytest.approx(300)
    assert rows["11"]["reserve_state"] == "consumed"
    assert rows["10"]["reserve_state"] == "released"


# --- the headcount somebody sets by hand -------------------------------------

def test_a_hand_set_week_keeps_its_hours():
    """Setting a week to two engineers is a decision about who is available,
    not about what the work is worth."""
    project = {"target_margin_pct": 0, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 200)]
    tasks = [a_task(10, 100, {1: 1.0}, "2026-01-05", "2026-01-09")]

    plain = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    week = plain["weeks"][0]["week"]
    typed = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0,
                           {(week, 1): 2})

    assert typed["weeks"][0]["hours"] == pytest.approx(plain["weeks"][0]["hours"])
    assert typed["weeks"][0]["people"] == 2
    assert typed["weeks"][0]["wanted"] == 5
    assert typed["weeks"][0]["by_hand"] is True
    # What changes is the load each of those two is carrying.
    assert typed["weeks"][0]["rows"][0]["each_hours"] == pytest.approx(100)


def test_the_engineers_are_saved_and_cleared(app):
    from app.db import query_one
    from app.service import set_staffing

    with app.app_context():
        set_staffing(1, "2026-10-26", 1, 4)
        assert query_one("SELECT engineers FROM resource_weeks WHERE project_id = 1 "
                         "AND week = ? AND trade_id = 1", ("2026-10-26",))["engineers"] == 4
        # Back at what the plan asked for, and the row goes rather than being
        # stored as a decision nobody made.
        set_staffing(1, "2026-10-26", 1, 3, wanted=3)
        assert query_one("SELECT 1 FROM resource_weeks WHERE project_id = 1 "
                         "AND week = ? AND trade_id = 1", ("2026-10-26",)) is None


def test_setting_the_engineers_answers_with_the_whole_week(signed_in, app):
    from app.service import resource_plan

    with app.app_context():
        from app.db import query_one

        made = resource_plan(dict(query_one("SELECT * FROM projects WHERE id = 1")))
    week = next(w for w in made["weeks"] if w["rows"])
    trade_id = week["rows"][0]["trade_id"]

    answer = signed_in.post(
        f"/projects/1/resources/staffing",
        data={"week": week["week"], "trade_id": trade_id, "engineers": "7",
              "wanted": week["rows"][0]["wanted"]},
        headers={"Accept": "application/json"})

    body = answer.get_json()
    assert body["ok"] is True
    assert body["week"]["trades"][str(trade_id)]["people"] == 7
    assert body["week"]["trades"][str(trade_id)]["by_hand"] is True
    # The row's total is the sum of its trades, so it moved with the cell.
    assert body["week"]["people"] == week["people"] - week["rows"][0]["people"] + 7


# --- sorting ----------------------------------------------------------------

def test_every_column_sorts_both_ways():
    project = {"target_margin_pct": 0, "hours_per_week": 40, "comments_reserve_pct": 0}
    trades = [a_trade(1, "Marine", 600), a_trade(2, "Geotech", 300)]
    tasks = [a_task(10, 20, {1: 1.0}, "2026-03-02", "2026-04-24"),
             a_task(11, 50, {1: 0.5, 2: 0.5}, "2026-01-05", "2026-02-27"),
             a_task(12, 30, {2: 1.0}, "2026-02-02", "2026-03-27")]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    rows = resources.task_rows(made, tasks, trades)

    assert [r["wbs"] for r in resources.sort_tasks(rows, "wbs", "asc")] == ["10", "11", "12"]
    assert [r["wbs"] for r in resources.sort_tasks(rows, "wbs", "desc")] == ["12", "11", "10"]
    assert [r["wbs"] for r in resources.sort_tasks(rows, "start", "asc")] == ["11", "12", "10"]
    assert [r["wbs"] for r in resources.sort_tasks(rows, "weight", "desc")] == ["11", "12", "10"]

    # A trade's own column: the lines it is not on sort to the bottom.
    by_geotech = resources.sort_tasks(rows, "trade:2", "desc")
    assert by_geotech[-1]["wbs"] == "10"
    assert by_geotech[0]["by_trade"][2] > 0


def test_the_weeks_sort_on_a_trade_column():
    project = {"target_margin_pct": 0, "hours_per_week": 40}
    trades = [a_trade(1, "Marine", 400), a_trade(2, "Geotech", 400)]
    tasks = [a_task(10, 50, {1: 1.0}, "2026-01-05", "2026-01-16"),
             a_task(11, 50, {2: 1.0}, "2026-02-02", "2026-02-13")]

    made = resources.plan(project, tasks, trades, WORKFLOW, None, None, 0)
    busiest = resources.sort_weeks(made["weeks"], "trade:2", "desc")[0]
    assert busiest["by_trade"][2]["hours"] > 0
    assert busiest["week"] >= "2026-02-01"

    # An unknown column falls back rather than throwing at somebody typing in
    # the address bar.
    columns = resources.sortable(resources.WEEK_COLUMNS, made["trade_order"])
    assert resources.order_for("nonsense", "sideways", columns, "week") == ("week", "asc")
    assert resources.order_for("trade:1", None, columns, "week") == ("trade:1", "desc")


def test_the_tab_carries_the_trade_columns_and_sorts(signed_in):
    page = signed_in.get("/projects/1/resources?weeks=hours&weeks_dir=desc"
                         "&lines=weight&lines_dir=asc").get_data(as_text=True)
    assert "Marine Structures" in page
    assert "Held for comments" in page
    assert 'data-staff=' in page
