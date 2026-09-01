"""Checks the calculation engine against the figures produced by the source
control workbook at its 2026-09-01 data date."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.calc import (
    build_period_report,
    build_s_curve,
    compute_project,
    elapsed_months,
    planned_pct,
)

SEED = json.loads((Path(__file__).resolve().parent.parent / "seed" / "sibline-port.json").read_text())
DATA_DATE = "2026-09-01"

TRADES = [dict(t, id=i + 1) for i, t in enumerate(SEED["trades"])]
TRADE_ID = {t["key"]: t["id"] for t in TRADES}
TASKS = [
    dict(
        t,
        id=i + 1,
        allocations={TRADE_ID[k]: pct for k, pct in t["allocations"].items() if pct > 0},
    )
    for i, t in enumerate(SEED["tasks"])
]
# The workbook measures elapsed time as `data date - NTP + 1`; the seed carries
# that convention so the demo project reproduces its published figures.
PROJECT = SEED["project"]


def close(actual, expected, tol=1e-9):
    assert actual == pytest.approx(expected, abs=tol), f"expected {expected}, got {actual}"


def test_seed_uses_the_workbook_convention():
    assert PROJECT["elapsed_day_offset"] == 1


def test_elapsed_months_matches_the_workbook():
    close(elapsed_months(PROJECT["ntp_date"], DATA_DATE, PROJECT["days_per_month"], 1), 0.06570841889117043)
    # Default convention: no elapsed time on the NTP date itself.
    close(elapsed_months(PROJECT["ntp_date"], PROJECT["ntp_date"], PROJECT["days_per_month"], 0), 0)
    close(
        elapsed_months(PROJECT["ntp_date"], DATA_DATE, PROJECT["days_per_month"], 0),
        1 / PROJECT["days_per_month"],
    )


def test_weight_points_total_100():
    close(sum(t["weight_points"] for t in SEED["tasks"]), 100, 1e-6)


def test_every_trade_allocation_totals_100_pct():
    for task in SEED["tasks"]:
        if task["weight_points"] == 0:
            continue
        close(sum(task["allocations"].values()), 1, 1e-6)


def test_planned_ramps_linearly_and_milestones_step():
    close(planned_pct({"start_month": 0, "finish_month": 4}, 2), 0.5)
    close(planned_pct({"start_month": 1, "finish_month": 3}, 0), 0)     # before start
    close(planned_pct({"start_month": 1, "finish_month": 3}, 9), 1)     # after finish
    close(planned_pct({"start_month": 0, "finish_month": 0}, 0), 1)     # milestone on its date
    close(planned_pct({"start_month": 2, "finish_month": 2}, 1.9), 0)   # milestone not yet due


def test_overall_planned_earned_and_variance_match_the_workbook():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE)
    close(result["totals"]["planned_progress"], 0.01762217659137577)
    close(result["totals"]["earned_progress"], 0.005)
    close(result["totals"]["variance"], -0.01262217659137577)


def test_late_upcoming_and_behind_counts_match_the_task_schedule_tab():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE, horizon_days=2)
    assert result["totals"]["late_count"] == 1      # kick-off meeting, due at NTP, only 50% done
    assert result["totals"]["upcoming_count"] == 0
    assert result["totals"]["behind_count"] == 8
    close(result["totals"]["weight_at_risk"], 0.01)


def test_the_late_line_is_the_kick_off_meeting():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE)
    late = [t for t in result["tasks"] if t["is_late"]]
    assert len(late) == 1
    assert late[0]["wbs"] == "1.6"
    assert late[0]["days_late"] == 1
    assert late[0]["due_date"] == "2026-08-31"


def test_trade_scope_weights_and_contributions_match_the_budget_control_tab():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE)
    by = {t["key"]: t for t in result["trades"]}

    close(by["marine"]["scope_weight_pct"], 0.35145000000000015)
    close(by["geotechnical"]["scope_weight_pct"], 0.21200000000000005)
    close(by["marine_structures"]["scope_weight_pct"], 0.37565000000000004)
    close(by["utilities"]["scope_weight_pct"], 0.06090000000000001)

    close(by["marine"]["planned_contribution"], 0.005441067761806982)
    close(by["geotechnical"]["planned_contribution"], 0.005404928131416837)
    close(by["marine_structures"]["planned_contribution"], 0.005401642710472279)
    close(by["utilities"]["planned_contribution"], 0.0013745379876796715)

    close(by["marine"]["earned_contribution"], 0.0015)
    close(by["geotechnical"]["earned_contribution"], 0.0015)
    close(by["marine_structures"]["earned_contribution"], 0.0015)
    close(by["utilities"]["earned_contribution"], 0.0005)

    close(by["marine"]["earned_pct_of_trade"], 0.00426803243704652)
    close(by["geotechnical"]["earned_pct_of_trade"], 0.007075471698113206)
    close(by["utilities"]["schedule_variance_pct"], -0.014360229682753222)

    # Scope weights must add back up to the whole project.
    close(sum(t["scope_weight_pct"] for t in result["trades"]), 1)
    close(sum(t["earned_contribution"] for t in result["trades"]), result["totals"]["earned_progress"])
    close(sum(t["planned_contribution"] for t in result["trades"]), result["totals"]["planned_progress"])


def test_earned_hours_follow_the_workbook_man_month_figures():
    result = compute_project(PROJECT, TASKS, TRADES, DATA_DATE)
    by = {t["key"]: t for t in result["trades"]}
    mm = PROJECT["hours_per_month"]
    # Workbook: Marine earned 0.02560819462227912 MM of a 6 MM budget.
    close(by["marine"]["earned_hours"] / mm, 0.02560819462227912)
    close(by["geotechnical"]["earned_hours"] / mm, 0.017688679245283015)
    close(by["marine_structures"]["earned_hours"] / mm, 0.023958471981898037)
    close(by["utilities"]["earned_hours"] / mm, 0.004105090311986863)
    close(result["budget"]["earned_hours"] / mm, 0.07136043616144702)
    close(result["budget"]["budget_hours"], 15 * mm)


def test_spent_hours_drive_cpi_eac_and_vac():
    result = compute_project(
        PROJECT, TASKS, TRADES, DATA_DATE, spent_by_trade={TRADE_ID["marine"]: 200}
    )
    marine = next(t for t in result["trades"] if t["key"] == "marine")
    assert marine["spent_hours"] == 200
    close(marine["cpi"], marine["earned_hours"] / 200)
    close(marine["eac_hours"], marine["budget_hours"] / marine["cpi"])
    close(marine["vac_hours"], marine["budget_hours"] - marine["eac_hours"])
    assert marine["hours_over_under"] > 0, "burning hours ahead of earned progress"
    assert marine["budget_status"] == "Over-burning"

    idle = next(t for t in result["trades"] if t["key"] == "utilities")
    assert idle["cpi"] is None
    assert idle["budget_status"] == "No spend booked"


def test_a_fully_complete_project_earns_100_pct():
    done = [dict(t, actual_pct=1) for t in TASKS]
    result = compute_project(PROJECT, done, TRADES, DATA_DATE)
    close(result["totals"]["earned_progress"], 1)
    assert result["totals"]["late_count"] == 0
    assert result["totals"]["behind_count"] == 0


def test_the_elapsed_day_convention_changes_planned_but_not_earned():
    strict = compute_project({**PROJECT, "elapsed_day_offset": 0}, TASKS, TRADES, DATA_DATE)
    workbook = compute_project(PROJECT, TASKS, TRADES, DATA_DATE)
    close(strict["totals"]["earned_progress"], workbook["totals"]["earned_progress"])
    assert strict["totals"]["planned_progress"] < workbook["totals"]["planned_progress"]
    close(strict["totals"]["planned_progress"], 0.01381108829568788)


def test_s_curve_planned_rises_to_100_pct_and_earned_stops_at_the_data_date():
    history = [
        {"task_id": t["id"], "actual_pct": t["actual_pct"], "data_date": "2026-08-31"}
        for t in TASKS
        if t["actual_pct"] > 0
    ]
    points = build_s_curve(PROJECT, TASKS, history, DATA_DATE, steps=20)
    # Month 0 already carries the kick-off milestone, which falls due on the NTP date.
    close(points[0]["planned"], 0.01)
    close(points[-1]["planned"], 1)
    for earlier, later in zip(points, points[1:]):
        assert later["planned"] >= earlier["planned"] - 1e-12, "planned curve must not go backwards"
    assert points[-1]["earned"] is None, "no earned value beyond the data date"
    assert sum(1 for p in points if p["earned"] is not None) >= 1
    # The curve's dates line up with how due dates are computed (month 0 = NTP).
    assert points[0]["date"] == "2026-08-31"
    assert any(p["date"] == DATA_DATE for p in points)


def test_period_report_attributes_progress_to_the_right_period_and_trades():
    kickoff = next(t for t in TASKS if t["wbs"] == "1.6")
    history = [
        {"task_id": kickoff["id"], "actual_pct": 0.25, "data_date": "2026-08-31"},
        {"task_id": kickoff["id"], "actual_pct": 0.5, "data_date": "2026-09-01"},
    ]
    period = build_period_report(PROJECT, TASKS, TRADES, history, "2026-09-01", "2026-09-01")
    close(period["earned_at_start"], 0.01 * 0.25)
    close(period["earned_at_end"], 0.01 * 0.5)
    close(period["earned_in_period"], 0.01 * 0.25)
    marine = next(t for t in period["trade_earned_in_period"] if t["name"] == "Marine")
    close(marine["earned_in_period"], 0.01 * 0.25 * 0.3)
    assert next(t for t in period["tasks"] if t["wbs"] == "1.6")["period_status"] == "Advanced in period"
