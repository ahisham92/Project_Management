"""Progress, schedule and earned-value calculations.

Deliverables are scheduled by real dates: a start date and a submission date.
How much progress is *planned* on any given day comes from the design workflow —
the steps a deliverable passes through, each worth a percentage and each planned
relative to the start or the submission date (see ``workflow.py``). Planned
percent interpolates between consecutive steps, so it lands exactly on a step's
percentage on that step's own date and ramps smoothly in between.

Lines that do not follow the design workflow (meetings, milestones) are tracked
as ``simple``: a percentage you type, ramping linearly between the two dates, or
stepping 0% -> 100% on the date when the two dates are the same.

The money side is unchanged:

    weight %        = weight points / total weight points
    earned progress = weight % x actual % complete
    variance        = earned - planned

All percentages are held as fractions (0..1).

This module is pure computation with no database or web dependencies, so it can
be tested directly against the figures a control workbook publishes.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping, Sequence

DEFAULT_DAYS_PER_MONTH = 30.4375
DEFAULT_HOURS_PER_MONTH = 176.0


# --- dates -----------------------------------------------------------------

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
    """Elapsed months since NTP, used for the headline "months elapsed" figure.

    ``day_offset`` decides how the NTP day itself is counted. With 0 (the
    default) elapsed time is zero on the NTP date. With 1 the NTP day counts as
    a day worked, reproducing spreadsheets that measure it as
    ``data date - NTP + 1``.
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


# --- the plan for one deliverable ------------------------------------------

def task_dates(task: Mapping[str, Any]) -> tuple[str, str]:
    """A deliverable's start and submission dates, tolerating a missing one."""
    start = str(task.get("start_date") or "")
    submission = str(task.get("submission_date") or "")
    if not start and not submission:
        return "", ""
    return (start or submission), (submission or start)


def uses_workflow(task: Mapping[str, Any]) -> bool:
    return str(task.get("tracking") or "workflow") == "workflow"


def task_schedule(task: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The workflow steps for a deliverable, each with the date it is planned."""
    from .workflow import schedule_for

    start, submission = task_dates(task)
    if not submission or not uses_workflow(task) or not steps:
        return []
    return schedule_for(steps, start, submission)


def planned_pct_on(
    task: Mapping[str, Any], on_date: Any, steps: Sequence[Mapping[str, Any]] = (), plan: Sequence[Mapping[str, Any]] | None = None
) -> float:
    """Planned percent complete for one deliverable on a given date."""
    start, submission = task_dates(task)
    if not submission:
        return 0.0

    if uses_workflow(task) and steps:
        from .workflow import planned_pct_from_schedule

        plan = task_schedule(task, steps) if plan is None else plan
        return _clamp01(planned_pct_from_schedule(plan, to_iso(on_date)))

    day, start_day, end_day = parse_date(on_date), parse_date(start), parse_date(submission)
    if end_day <= start_day:                        # a milestone: it happens on its date
        return 1.0 if day >= end_day else 0.0
    return _clamp01((day - start_day).days / (end_day - start_day).days)


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


# --- the whole project -----------------------------------------------------

def compute_project(
    project: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]] = (),
    data_date: Any = None,
    horizon_days: int | None = 30,
    spent_by_trade: Mapping[Any, float] | None = None,
    steps: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Every derived figure for one project at a data date.

    ``horizon_days`` of None means "everything ahead", for the schedule's
    all-dates view.
    """
    from .workflow import CODE_A, is_approved, is_submitted, step_by_key

    spent_by_trade = spent_by_trade or {}
    days_per_month = _num(project.get("days_per_month"), DEFAULT_DAYS_PER_MONTH) or DEFAULT_DAYS_PER_MONTH
    hours_per_month = _num(project.get("hours_per_month"), DEFAULT_HOURS_PER_MONTH) or DEFAULT_HOURS_PER_MONTH
    day_offset = _num(project.get("elapsed_day_offset"))
    duration = _num(project.get("duration_months"))
    max_revisions = int(_num(project.get("max_revisions"), 10))

    cutoff = parse_date(data_date)
    cutoff_iso = cutoff.isoformat()
    elapsed = elapsed_months(project["ntp_date"], cutoff, days_per_month, day_offset)
    horizon_end = None if horizon_days is None else cutoff + timedelta(days=horizon_days)

    total_points = sum(_num(t.get("weight_points")) for t in tasks)

    rows: list[dict[str, Any]] = []
    for task in tasks:
        points = _num(task.get("weight_points"))
        weight_pct = points / total_points if total_points > 0 else 0.0
        actual = _clamp01(_num(task.get("actual_pct")))
        start, submission = task_dates(task)
        plan = task_schedule(task, steps)
        planned = planned_pct_on(task, cutoff, steps, plan)

        earned = weight_pct * actual
        planned_progress = weight_pct * planned

        status_key = str(task.get("status_key") or "")
        revision = int(_num(task.get("revision")))
        workflow = uses_workflow(task) and bool(plan)
        submitted = is_submitted(steps, status_key) if workflow else actual >= 1
        approved = is_approved(steps, status_key) if workflow else actual >= 1
        is_complete = actual >= 1

        # The submission date is the deadline that matters; once a deliverable is
        # with the client, the approval date takes over.
        approval_due = next((s["date"] for s in plan if s["key"] == CODE_A), submission)
        if workflow and submitted and not approved:
            deadline, late_reason = approval_due, "approval"
        else:
            deadline, late_reason = submission, "submission"

        is_late = bool(deadline) and (not is_complete) and deadline < cutoff_iso
        days_to_due = days_between(cutoff_iso, deadline) if deadline else 0

        current = step_by_key(steps, status_key) if workflow else None
        next_due = next((s for s in plan if s["percent"] > (current["percent"] if current else -1)), None)

        row = dict(task)
        row.update(
            weight_pct=weight_pct,
            actual_pct=actual,
            planned_pct=planned,
            earned_progress=earned,
            planned_progress=planned_progress,
            variance=earned - planned_progress,
            status=status_of(actual),
            status_name=(current or {}).get("name", "" if status_key else "Not started"),
            status_key=status_key,
            revision=revision,
            uses_workflow=workflow,
            step_plan=plan,
            start_date=start,
            submission_date=submission,
            approval_due_date=approval_due,
            planned_start=start,
            due_date=deadline,
            due_reason=late_reason,
            next_step=next_due,
            next_step_due=(next_due or {}).get("date", ""),
            days_to_due=days_to_due,
            is_complete=is_complete,
            is_submitted=submitted,
            is_approved=approved,
            is_late=is_late,
            days_late=-days_to_due if is_late else 0,
            is_upcoming=(not is_complete) and (not is_late) and bool(deadline)
            and (horizon_end is None or deadline <= horizon_end.isoformat()),
            is_behind=(not is_complete) and actual < planned - 1e-9,
            is_milestone=bool(submission) and submission == start,
            in_rework=revision > 0 and not is_complete,
            at_revision_limit=revision >= max_revisions,
        )
        rows.append(row)

    earned_total = sum(r["earned_progress"] for r in rows)
    planned_total = sum(r["planned_progress"] for r in rows)

    trade_rows = _trade_rows(rows, trades, spent_by_trade, hours_per_month)

    budget_hours = sum(t["budget_hours"] for t in trade_rows)
    spent_hours = sum(t["spent_hours"] for t in trade_rows)
    earned_hours = sum(t["earned_hours"] for t in trade_rows)
    project_cpi = earned_hours / spent_hours if spent_hours > 0 else None
    eac_hours = budget_hours / project_cpi if project_cpi else budget_hours

    late = [r for r in rows if r["is_late"]]
    upcoming = [r for r in rows if r["is_upcoming"]]
    behind = [r for r in rows if r["is_behind"]]
    rework = [r for r in rows if r["in_rework"]]

    return {
        "data_date": cutoff_iso,
        "ntp_date": to_iso(project["ntp_date"]),
        "elapsed_months": elapsed,
        "duration_months": duration,
        "time_elapsed_pct": _clamp01(elapsed / duration) if duration > 0 else 0.0,
        "total_weight_points": total_points,
        "horizon_days": horizon_days,
        "max_revisions": max_revisions,
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
            "rework_count": len(rework),
            "at_limit_count": sum(1 for r in rework if r["at_revision_limit"]),
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


def _trade_rows(
    rows: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    spent_by_trade: Mapping[Any, float],
    hours_per_month: float,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
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

        # Percent complete *of that trade's own scope*, which is what drives the
        # budget figures.
        earned_of_trade = earned_contrib / scope_weight if scope_weight > 0 else 0.0
        planned_of_trade = planned_contrib / scope_weight if scope_weight > 0 else 0.0

        budget_hours = _num(trade.get("budget_hours"))
        spent_hours = _num(spent_by_trade.get(trade_id))
        earned_hours = budget_hours * earned_of_trade
        cpi = earned_hours / spent_hours if spent_hours > 0 else None
        eac = budget_hours / cpi if cpi else budget_hours

        out.append(
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
    return out


# --- curves and period reports ---------------------------------------------

def project_span(project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
                 steps: Sequence[Mapping[str, Any]], data_date: Any) -> tuple[str, str]:
    """The first and last dates worth plotting."""
    days_per_month = _num(project.get("days_per_month"), DEFAULT_DAYS_PER_MONTH) or DEFAULT_DAYS_PER_MONTH
    duration = _num(project.get("duration_months"), 12.0) or 12.0

    starts = [t["start_date"] for t in ((dict(x) for x in tasks)) if t.get("start_date")]
    ends: list[str] = []
    for task in tasks:
        plan = task_schedule(task, steps)
        _, submission = task_dates(task)
        if plan:
            ends.append(plan[-1]["date"])
        elif submission:
            ends.append(submission)

    first = min(starts + [to_iso(project["ntp_date"])])
    default_end = to_iso(add_months(project["ntp_date"], duration, days_per_month))
    last = max(ends + [default_end, to_iso(data_date)])
    return first, last


def build_s_curve(
    project: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    progress_history: Iterable[Mapping[str, Any]],
    data_date: Any,
    steps: Sequence[Mapping[str, Any]] = (),
    samples: int = 40,
) -> list[dict[str, Any]]:
    """Planned and earned cumulative curves over the life of the project.

    Planned comes from the schedule; earned is reconstructed from the progress
    history, so the curve shows what was actually reported at each point in time
    rather than only the latest value.
    """
    total_points = sum(_num(t.get("weight_points")) for t in tasks)

    def weight_of(task: Mapping[str, Any]) -> float:
        return _num(task.get("weight_points")) / total_points if total_points > 0 else 0.0

    first_iso, last_iso = project_span(project, tasks, steps, data_date)
    first, last = parse_date(first_iso), parse_date(last_iso)
    span = max(1, (last - first).days)
    cutoff_iso = to_iso(data_date)

    history = sorted(progress_history, key=lambda h: str(h["data_date"]))
    plans = {t["id"]: task_schedule(t, steps) for t in tasks if "id" in t}

    # Sample evenly, but always include the data date so the earned curve ends
    # exactly on the reported progress.
    days = {round(span * i / samples) for i in range(samples + 1)}
    cutoff_offset = (parse_date(cutoff_iso) - first).days
    if 0 <= cutoff_offset <= span:
        days.add(cutoff_offset)

    points: list[dict[str, Any]] = []
    for offset in sorted(days):
        iso = (first + timedelta(days=offset)).isoformat()
        planned = sum(weight_of(t) * planned_pct_on(t, iso, steps, plans.get(t.get("id"))) for t in tasks)

        earned = None
        if iso <= cutoff_iso:
            state: dict[Any, float] = {}
            for entry in history:
                if str(entry["data_date"]) > iso:
                    break
                state[entry["task_id"]] = _clamp01(_num(entry["actual_pct"]))
            earned = sum(weight_of(t) * state.get(t["id"], 0.0) for t in tasks)

        points.append({"date": iso, "planned": planned, "earned": earned})
    return points


def build_period_report(
    project: Mapping[str, Any],
    tasks: Sequence[Mapping[str, Any]],
    trades: Sequence[Mapping[str, Any]],
    progress_history: Iterable[Mapping[str, Any]],
    start: Any,
    end: Any,
    steps: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Progress gained between two dates, per deliverable, trade and in total."""
    from_iso, to_iso_ = to_iso(start), to_iso(end)
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
            end_pct = _clamp01(_num(task.get("actual_pct")))   # no history: use the live value
        delta = end_pct - start_pct

        trade_earned = {}
        for trade in trades:
            share = _num((task.get("allocations") or {}).get(trade["id"]))
            if share:
                trade_earned[trade["id"]] = weight_pct * delta * share

        if delta > 1e-9:
            period_status = "Completed in period" if end_pct >= 1 else "Advanced in period"
        elif delta < -1e-9:
            period_status = "Went back — rework"
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
                "revision": int(_num(task.get("revision"))),
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

    planned_at_end = sum(
        (_num(t.get("weight_points")) / total_points if total_points > 0 else 0.0) * planned_pct_on(t, to_iso_, steps)
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
