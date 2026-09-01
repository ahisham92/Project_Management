"""Progress, schedule and earned-value calculations.

These mirror the measurement rules used in the source control workbook:

    weight %        = weight points / total weight points
    elapsed months  = (data date - NTP) / days per month
    planned %       = linear ramp between a line's start and finish month; a line
                      whose finish <= start is a milestone and steps 0% -> 100%
                      on its date
    earned progress = weight % x actual % complete
    variance        = earned - planned

All percentages are held as fractions (0..1).

This module is pure computation with no database or web dependencies, so it can
be tested directly against the figures the workbook publishes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_DAYS_PER_MONTH = 30.4375
DEFAULT_HOURS_PER_MONTH = 176.0


def parse_date(value: Any) -> date:
    """Accept a date, a datetime, or a YYYY-MM-DD string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date: {value!r}") from exc


def to_iso(value: Any) -> str:
    return parse_date(value).isoformat()


def add_months(ntp: Any, months: float, days_per_month: float) -> date:
    """The calendar date a given elapsed-month position falls on."""
    return parse_date(ntp) + timedelta(days=months * days_per_month)


def days_between(start: Any, end: Any) -> int:
    return (parse_date(end) - parse_date(start)).days


def elapsed_months(ntp: Any, data_date: Any, days_per_month: float, day_offset: float = 0.0) -> float:
    """Elapsed months since NTP.

    ``day_offset`` decides how the NTP day itself is counted. With 0 (the
    default) elapsed time is zero on the NTP date, which is the convention the
    schedule columns assume ("month 0 = NTP") and the one the late/due day
    counts use. With 1 the NTP day counts as a day worked, reproducing
    spreadsheets that measure elapsed time as ``data date - NTP + 1``.
    """
    return (days_between(ntp, data_date) + day_offset) / days_per_month


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, value))


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def planned_pct(task: Mapping[str, Any], elapsed: float) -> float:
    """Planned % complete for one deliverable at a given elapsed-month position."""
    start = _num(task.get("start_month"))
    finish = _num(task.get("finish_month"))
    if finish <= start:                      # milestone
        return 1.0 if elapsed >= finish else 0.0
    return _clamp01((elapsed - start) / (finish - start))


def status_of(actual_pct: float) -> str:
    if actual_pct >= 1:
        return "Complete"
    if actual_pct > 0:
        return "In Progress"
    return "Not Started"


def budget_status(spent_hours: float, budget_hours: float, cpi: float | None) -> str:
    if not spent_hours:
        return "No spend booked"
    if spent_hours > budget_hours:
        return "Over budget"
    if cpi is None:
        return "No spend booked"
    if cpi >= 1:
        return "Under / on budget"
    if cpi >= 0.9:
        return "Slightly over-burning"
    return "Over-burning"


def compute_project(
    project: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]] = (),
    data_date: Any = None,
    horizon_days: int = 30,
    spent_by_trade: Mapping[Any, float] | None = None,
) -> dict[str, Any]:
    """Every derived figure for one project at a data date.

    ``tasks`` may each carry an ``allocations`` mapping of trade id -> share
    (0..1) describing how that deliverable's weight is split between trades.
    """
    spent_by_trade = spent_by_trade or {}
    days_per_month = _num(project.get("days_per_month"), DEFAULT_DAYS_PER_MONTH) or DEFAULT_DAYS_PER_MONTH
    hours_per_month = _num(project.get("hours_per_month"), DEFAULT_HOURS_PER_MONTH) or DEFAULT_HOURS_PER_MONTH
    day_offset = _num(project.get("elapsed_day_offset"))
    duration = _num(project.get("duration_months"))

    cutoff = parse_date(data_date)
    elapsed = elapsed_months(project["ntp_date"], cutoff, days_per_month, day_offset)
    horizon_end = cutoff + timedelta(days=horizon_days)

    total_points = sum(_num(t.get("weight_points")) for t in tasks)

    rows: list[dict[str, Any]] = []
    for task in tasks:
        points = _num(task.get("weight_points"))
        weight_pct = points / total_points if total_points > 0 else 0.0
        actual = _clamp01(_num(task.get("actual_pct")))
        planned = planned_pct(task, elapsed)
        earned = weight_pct * actual
        planned_progress = weight_pct * planned

        start_month = _num(task.get("start_month"))
        finish_month = _num(task.get("finish_month"))
        planned_start = add_months(project["ntp_date"], start_month, days_per_month)
        due_date = add_months(project["ntp_date"], finish_month, days_per_month)
        days_to_due = (due_date - cutoff).days
        is_complete = actual >= 1
        is_late = (not is_complete) and due_date < cutoff

        row = dict(task)
        row.update(
            weight_pct=weight_pct,
            actual_pct=actual,
            planned_pct=planned,
            earned_progress=earned,
            planned_progress=planned_progress,
            variance=earned - planned_progress,
            status=status_of(actual),
            planned_start=planned_start.isoformat(),
            due_date=due_date.isoformat(),
            days_to_due=days_to_due,
            is_complete=is_complete,
            is_late=is_late,
            days_late=-days_to_due if is_late else 0,
            is_upcoming=(not is_complete) and (not is_late) and due_date <= horizon_end,
            is_behind=(not is_complete) and actual < planned - 1e-9,
            is_milestone=finish_month <= start_month,
        )
        rows.append(row)

    earned_total = sum(r["earned_progress"] for r in rows)
    planned_total = sum(r["planned_progress"] for r in rows)

    trade_rows: list[dict[str, Any]] = []
    for trade in trades:
        trade_id = trade["id"]
        scope_weight = earned_contrib = planned_contrib = 0.0
        for row in rows:
            share = _num((row.get("allocations") or {}).get(trade_id))
            if not share:
                continue
            scope_weight += row["weight_pct"] * share
            earned_contrib += row["earned_progress"] * share
            planned_contrib += row["planned_progress"] * share

        # Percent complete *of that trade's own scope*, as in the workbook's
        # budget control tab.
        earned_of_trade = earned_contrib / scope_weight if scope_weight > 0 else 0.0
        planned_of_trade = planned_contrib / scope_weight if scope_weight > 0 else 0.0

        budget_hours = _num(trade.get("budget_hours"))
        spent_hours = _num(spent_by_trade.get(trade_id))
        earned_hours = budget_hours * earned_of_trade
        cpi = earned_hours / spent_hours if spent_hours > 0 else None
        eac = budget_hours / cpi if cpi else budget_hours

        trade_rows.append(
            {
                "id": trade_id,
                "key": trade.get("key"),
                "name": trade.get("name"),
                "color": trade.get("color"),
                "sort_order": trade.get("sort_order"),
                "scope_weight_pct": scope_weight,
                "earned_contribution": earned_contrib,
                "planned_contribution": planned_contrib,
                "earned_pct_of_trade": earned_of_trade,
                "planned_pct_of_trade": planned_of_trade,
                "schedule_variance_pct": earned_of_trade - planned_of_trade,
                "budget_hours": budget_hours,
                "budget_months": budget_hours / hours_per_month if hours_per_month else 0.0,
                "spent_hours": spent_hours,
                "hours_used_pct": spent_hours / budget_hours if budget_hours > 0 else 0.0,
                "earned_hours": earned_hours,
                # Positive = burning more hours than progress has earned.
                "hours_over_under": spent_hours - earned_hours,
                "remaining_hours": budget_hours - spent_hours,
                "cpi": cpi,
                "eac_hours": eac,
                "vac_hours": budget_hours - eac,
                "budget_status": budget_status(spent_hours, budget_hours, cpi),
            }
        )

    budget_hours = sum(t["budget_hours"] for t in trade_rows)
    spent_hours = sum(t["spent_hours"] for t in trade_rows)
    earned_hours = sum(t["earned_hours"] for t in trade_rows)
    project_cpi = earned_hours / spent_hours if spent_hours > 0 else None
    eac_hours = budget_hours / project_cpi if project_cpi else budget_hours

    late = [r for r in rows if r["is_late"]]
    upcoming = [r for r in rows if r["is_upcoming"]]
    behind = [r for r in rows if r["is_behind"]]

    return {
        "data_date": cutoff.isoformat(),
        "ntp_date": to_iso(project["ntp_date"]),
        "elapsed_months": elapsed,
        "duration_months": duration,
        "time_elapsed_pct": _clamp01(elapsed / duration) if duration > 0 else 0.0,
        "total_weight_points": total_points,
        "horizon_days": horizon_days,
        "totals": {
            "planned_progress": planned_total,
            "earned_progress": earned_total,
            "variance": earned_total - planned_total,
            "spi": earned_total / planned_total if planned_total > 0 else None,
            "task_count": len(rows),
            "weighted_count": sum(1 for r in rows if _num(r.get("weight_points")) > 0),
            "complete_count": sum(1 for r in rows if r["is_complete"]),
            "in_progress_count": sum(1 for r in rows if not r["is_complete"] and r["actual_pct"] > 0),
            "not_started_count": sum(1 for r in rows if r["actual_pct"] <= 0),
            "late_count": len(late),
            "upcoming_count": len(upcoming),
            "behind_count": len(behind),
            "weight_at_risk": sum(r["weight_pct"] for r in late),
        },
        "budget": {
            "hours_per_month": hours_per_month,
            "budget_hours": budget_hours,
            "spent_hours": spent_hours,
            "earned_hours": earned_hours,
            "remaining_hours": budget_hours - spent_hours,
            "hours_used_pct": spent_hours / budget_hours if budget_hours > 0 else 0.0,
            "hours_over_under": spent_hours - earned_hours,
            "cpi": project_cpi,
            "eac_hours": eac_hours,
            "vac_hours": budget_hours - eac_hours,
            "budget_status": budget_status(spent_hours, budget_hours, project_cpi),
            "unallocated_hours": 0.0,
        },
        "tasks": rows,
        "trades": trade_rows,
    }


def build_s_curve(
    project: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    progress_history: Iterable[Mapping[str, Any]],
    data_date: Any,
    steps: int = 40,
) -> list[dict[str, Any]]:
    """Planned and earned cumulative curves over the life of the project.

    Planned comes from the schedule; earned is reconstructed from the progress
    history so the curve shows what was actually reported at each point in time.
    """
    days_per_month = _num(project.get("days_per_month"), DEFAULT_DAYS_PER_MONTH) or DEFAULT_DAYS_PER_MONTH
    day_offset = _num(project.get("elapsed_day_offset"))
    duration = _num(project.get("duration_months"), 12.0) or 12.0
    total_points = sum(_num(t.get("weight_points")) for t in tasks)

    def weight_of(task: Mapping[str, Any]) -> float:
        return _num(task.get("weight_points")) / total_points if total_points > 0 else 0.0

    ntp = parse_date(project["ntp_date"])
    cutoff = parse_date(data_date)
    cutoff_iso = cutoff.isoformat()
    end_months = max(duration, elapsed_months(ntp, cutoff, days_per_month, day_offset))

    history = sorted(progress_history, key=lambda h: str(h["data_date"]))

    # Sample evenly across the programme, but always include the data date
    # itself so the earned curve ends exactly on the reported progress. Month
    # positions map to dates the same way deliverable due dates do (month 0 = NTP).
    samples: list[tuple[float, str]] = []
    for i in range(steps + 1):
        month = end_months * i / steps
        samples.append((month, (ntp + timedelta(days=month * days_per_month)).isoformat()))
    cutoff_month = elapsed_months(ntp, cutoff, days_per_month, day_offset)
    if 0 <= cutoff_month <= end_months:
        samples.append((cutoff_month, cutoff_iso))
    samples.sort(key=lambda s: (s[0], s[1]))

    points: list[dict[str, Any]] = []
    previous: float | None = None
    for month, iso in samples:
        if previous is not None and abs(month - previous) < 1e-9:
            continue
        previous = month
        planned = sum(weight_of(t) * planned_pct(t, month) for t in tasks)

        earned = None
        if iso <= cutoff_iso:
            state: dict[Any, float] = {}
            for entry in history:
                if str(entry["data_date"]) > iso:
                    break
                state[entry["task_id"]] = _clamp01(_num(entry["actual_pct"]))
            earned = sum(weight_of(t) * state.get(t["id"], 0.0) for t in tasks)

        points.append({"month": round(month, 3), "date": iso, "planned": planned, "earned": earned})
    return points


def build_period_report(
    project: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    progress_history: Iterable[Mapping[str, Any]],
    start: Any,
    end: Any,
) -> dict[str, Any]:
    """Progress gained between two dates, per deliverable, trade and in total."""
    from_iso = to_iso(start)
    to_iso_ = to_iso(end)
    total_points = sum(_num(t.get("weight_points")) for t in tasks)
    history = sorted(progress_history, key=lambda h: str(h["data_date"]))

    at_start: dict[Any, float] = {}
    at_end: dict[Any, float] = {}
    for entry in history:
        pct = _clamp01(_num(entry["actual_pct"]))
        if str(entry["data_date"]) < from_iso:
            at_start[entry["task_id"]] = pct
        if str(entry["data_date"]) <= to_iso_:
            at_end[entry["task_id"]] = pct

    rows: list[dict[str, Any]] = []
    for task in tasks:
        weight_pct = _num(task.get("weight_points")) / total_points if total_points > 0 else 0.0
        start_pct = at_start.get(task["id"], 0.0)
        if task["id"] in at_end:
            end_pct = at_end[task["id"]]
        elif task["id"] in at_start:
            end_pct = start_pct
        else:
            # No history at all: fall back to the live value.
            end_pct = _clamp01(_num(task.get("actual_pct")))
        delta = end_pct - start_pct

        trade_earned = {}
        for trade in trades:
            share = _num((task.get("allocations") or {}).get(trade["id"]))
            if share:
                trade_earned[trade["id"]] = weight_pct * delta * share

        if delta > 1e-9:
            period_status = "Completed in period" if end_pct >= 1 else "Advanced in period"
        elif end_pct >= 1:
            period_status = "Already complete"
        elif start_pct > 0:
            period_status = "No change – in progress"
        else:
            period_status = "No change – not started"

        rows.append(
            {
                "id": task["id"],
                "wbs": task.get("wbs"),
                "name": task.get("name"),
                "section_id": task.get("section_id"),
                "weight_pct": weight_pct,
                "actual_start": start_pct,
                "actual_end": end_pct,
                "delta_actual": delta,
                "earned_start": weight_pct * start_pct,
                "earned_end": weight_pct * end_pct,
                "earned_in_period": weight_pct * delta,
                "trade_earned": trade_earned,
                "period_status": period_status,
            }
        )

    days_per_month = _num(project.get("days_per_month"), DEFAULT_DAYS_PER_MONTH) or DEFAULT_DAYS_PER_MONTH
    elapsed_at_end = elapsed_months(
        project["ntp_date"], to_iso_, days_per_month, _num(project.get("elapsed_day_offset"))
    )
    planned_at_end = sum(
        (_num(t.get("weight_points")) / total_points if total_points > 0 else 0.0) * planned_pct(t, elapsed_at_end)
        for t in tasks
    )

    return {
        "from": from_iso,
        "to": to_iso_,
        "days_in_period": days_between(from_iso, to_iso_) + 1,
        "earned_at_start": sum(r["earned_start"] for r in rows),
        "earned_at_end": sum(r["earned_end"] for r in rows),
        "earned_in_period": sum(r["earned_in_period"] for r in rows),
        "planned_at_end": planned_at_end,
        "trade_earned_in_period": [
            {
                "id": t["id"],
                "name": t.get("name"),
                "color": t.get("color"),
                "earned_in_period": sum(r["trade_earned"].get(t["id"], 0.0) for r in rows),
            }
            for t in trades
        ],
        "tasks": rows,
    }
