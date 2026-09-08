"""Resource planning: how many engineers, on what, in which week.

A budget in hours says what a trade may spend. It does not say when, and "when"
is the only part anybody can act on — a team leader deciding on a Thursday
whether to put two people or five on the marine drawings next week is not
helped by a number for the whole project.

So this turns the budget into a week-by-week plan, in four steps.

**A target margin comes off the top.** Set 12% in Setup and the plan is drawn
against 88% of every trade's budget. The gap is what the project is trying to
earn, and planning to the whole budget is planning to make nothing.

**Each trade's ceiling is split across the deliverables it carries**, in
proportion to how much of the project each one is and how much of it that trade
holds — the deliverable's weight times the trade's share of it. A trade with 10%
of a 6-point line and 60% of a 3-point line is planned mostly on the second.

**The hours rise towards the submission.** This is the part worth being explicit
about, because it is the whole difference between a plan somebody can staff and
a flat average. A deliverable on the design workflow earns 10% at the start, 40%
by the IDC, 60% when comments are addressed, 80% at submission — those
percentages come in bigger jumps over shorter stretches as the issue date
approaches, which is exactly the shape of the work: two people scoping in week
one, six drawing in the fortnight before it goes out.

But **value earned is not effort spent**, and a profile that follows the
percentages alone puts sixty percent of the hours into the last five days, which
no team has ever worked. So the profile sits between the two:
a little over half of it follows the value curve and the rest is flat across
the days. It rises, by two or
three times from the first stretch to the last, without asking for the
impossible. ``RAMP`` below is that half, in one place, so an office that works
differently can argue with the number rather than with the code.

A line tracked as a plain percentage — a meeting, a milestone, a transmittal —
has no steps, so it comes out flat, which is what actually happens.

**Nothing after the submission earns hours.** The last 20% of a design workflow
is the client reading it. That is their fortnight, not ours, so the effort is
spread over the part of the curve this office actually works.

**Hours become people** by dividing by the hours one engineer works in a week.
That is a setting rather than a constant, because a 40-hour week and a 45-hour
week are different answers to "how many do I need".
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

from .calc import task_dates, uses_workflow

# What a project plans against when nobody has said otherwise: the whole
# budget, with a twelfth of it held back as the margin.
DEFAULT_TARGET_PCT = 12.0

# One engineer's week. Not derived from the monthly figure: a month is a
# billing convention and a week is a rota, and the two are set by different
# people for different reasons.
DEFAULT_HOURS_PER_WEEK = 40.0

# How much of the effort profile follows the value curve rather than the
# calendar. At 1.0 the hours track the workflow percentages exactly, which puts
# most of a month into its last week; at 0.0 they are flat, which is the average
# nobody can staff from. Half way rises by two or three times across a
# deliverable, which is what a design team actually does.
RAMP = 0.6


def _num(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _day(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def target_of(project: Mapping[str, Any]) -> float:
    """The margin held back, as a fraction. 12% comes back as 0.12."""
    percent = _num(project.get("target_margin_pct"), DEFAULT_TARGET_PCT)
    return min(0.9, max(0.0, percent / 100))


def hours_per_week(project: Mapping[str, Any]) -> float:
    return max(1.0, _num(project.get("hours_per_week"), DEFAULT_HOURS_PER_WEEK))


# --- what each trade may spend, and on what ---------------------------------

def ceilings(tasks: Sequence[Mapping[str, Any]], trades: Sequence[Mapping[str, Any]],
             target: float = DEFAULT_TARGET_PCT / 100) -> dict[int, dict[int, float]]:
    """Hours a trade may plan on each deliverable: ``{trade_id: {task_id: hours}}``.

    A trade's ceiling is its budget less the margin. That ceiling is divided
    between the deliverables it carries in proportion to the weight of each and
    the share of it the trade holds — so a line that is 6% of the project and
    60% that trade's is worth twice one that is 6% and 30%.

    A trade allocated to nothing has nothing to plan, and its ceiling stays
    where it is rather than being spread over lines it does not work on.
    """
    points = {int(t["id"]): _num(t.get("weight_points")) for t in tasks}
    whole = sum(points.values())

    out: dict[int, dict[int, float]] = {}
    for trade in trades:
        trade_id = int(trade["id"])
        ceiling = max(0.0, _num(trade.get("budget_hours")) * (1 - target))
        shares: dict[int, float] = {}
        for task in tasks:
            allocation = _num((task.get("allocations") or {}).get(trade_id))
            if allocation <= 0 or whole <= 0:
                continue
            shares[int(task["id"])] = (points[int(task["id"])] / whole) * allocation
        total = sum(shares.values())
        out[trade_id] = ({task_id: ceiling * share / total
                          for task_id, share in shares.items()} if total > 0 else {})
    return out


# --- when those hours are worked --------------------------------------------

def stretches(task: Mapping[str, Any], steps: Sequence[Mapping[str, Any]] = (),
              calendar: Any = None) -> list[dict[str, Any]]:
    """The stretches of work in a deliverable, each with the share it earns.

    A line on the design workflow is its steps: start to IDC, IDC to comments,
    comments to submission, and so on — each carrying the percentage gained
    across it. A line tracked as a plain percentage is one stretch, start to
    submission, carrying all of it.

    The share is what makes the hours ramp: the later stretches are shorter and
    worth more, so more of the effort lands near the submission.
    """
    from .calc import task_schedule

    start, submission = task_dates(task)
    began, ends = _day(start), _day(submission)
    if not began or not ends:
        return []
    if ends < began:
        began, ends = ends, began

    if ends <= began:
        # A milestone happens on its day: one stretch, all of it.
        return [{"from": began, "to": ends, "share": 1.0}]

    plan = task_schedule(task, steps, calendar) if uses_workflow(task) else []
    marks: list[tuple[date, float]] = []
    for step in plan:
        when = _day(step.get("date"))
        # Nothing after the submission: the last stretch of a design workflow is
        # the client reading it, and that is their fortnight, not ours.
        if when and began <= when <= ends:
            marks.append((when, min(1.0, max(0.0, _num(step.get("percent"))))))
    marks.sort()

    # The stretches between the marks, each carrying the value earned across it.
    parts: list[dict[str, Any]] = []
    at, gained = began, 0.0
    for when, percent in marks:
        if percent > gained + 1e-9:
            parts.append({"from": at, "to": when, "value": percent - gained})
            at, gained = when, percent
    if at < ends or not parts:
        parts.append({"from": at, "to": ends, "value": max(1.0 - gained, 1e-9)})

    # A stretch of no length is a step landing on a date another one already
    # holds — the design start on day one, usually. Its value belongs to the
    # stretch beside it rather than to a single day, which would put a week of
    # hours into a Monday. Forward where there is something after it, back into
    # the last real stretch where there is not.
    kept: list[dict[str, Any]] = []
    carried = 0.0
    for part in parts:
        if part["to"] <= part["from"]:
            carried += part["value"]
            continue
        kept.append(dict(part, value=part["value"] + carried))
        carried = 0.0
    if carried:
        if kept:
            kept[-1]["value"] += carried
        else:
            # Every step anchored to the same day. The workflow says nothing
            # about the shape of the work, so it is worked evenly.
            kept = [{"from": began, "to": ends, "value": carried}]

    lengths = [len(_working_days(part["from"], part["to"], calendar)) for part in kept]
    values = [part["value"] for part in kept]
    whole_days, whole_value = sum(lengths) or 1, sum(values) or 1.0

    # Part of the profile follows the value curve and the rest the calendar.
    # Either alone is wrong in a way somebody would notice on the first Monday.
    shares = [RAMP * (value / whole_value) + (1 - RAMP) * (days / whole_days)
              for value, days in zip(values, lengths)]
    total = sum(shares) or 1.0
    return [{"from": part["from"], "to": part["to"], "share": share / total}
            for part, share in zip(kept, shares)]


def _working_days(first: date, last: date, calendar: Any = None) -> list[date]:
    """Every day worked between two dates, both included."""
    if last < first:
        first, last = last, first
    days: list[date] = []
    at = first
    while at <= last:
        if calendar is None or calendar.works_on(at):
            days.append(at)
        at += timedelta(days=1)
    return days or [first]


def spread(task: Mapping[str, Any], hours: float,
           steps: Sequence[Mapping[str, Any]] = (), calendar: Any = None,
           ) -> dict[date, float]:
    """One deliverable's hours, laid out day by day.

    Each stretch's share of the hours is spread evenly over the days actually
    worked inside it, so a fortnight with a public holiday in it carries the
    same hours over fewer days rather than quietly losing a day's work.
    """
    if hours <= 0:
        return {}
    out: dict[date, float] = {}
    for stretch in stretches(task, steps, calendar):
        days = _working_days(stretch["from"], stretch["to"], calendar)
        each = hours * stretch["share"] / len(days)
        for day in days:
            out[day] = out.get(day, 0.0) + each
    return out


# --- the plan, by week ------------------------------------------------------

def week_of(day: date, first_day: int = 0) -> date:
    """The Monday — or Sunday — that opens the week a day falls in."""
    return day - timedelta(days=(day.weekday() - first_day) % 7)


def plan(project: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
         trades: Sequence[Mapping[str, Any]],
         steps: Sequence[Mapping[str, Any]] = (),
         calendars: Mapping[Any, Any] | None = None,
         spent_by_week: Mapping[tuple[str, int], float] | None = None,
         first_day: int = 0) -> dict[str, Any]:
    """The whole resource plan: hours and people, per week, per trade.

    `spent_by_week` is what has actually been booked, keyed by (week, trade id),
    so the plan and the timesheet can be read against each other without this
    module knowing anything about how hours are recorded.
    """
    target = target_of(project)
    per_week = hours_per_week(project)
    allowed = ceilings(tasks, trades, target)
    by_id = {int(t["id"]): t for t in tasks}
    trade_names = {int(t["id"]): str(t.get("name") or "") for t in trades}

    def diary(task: Mapping[str, Any]):
        if not calendars:
            return None
        return calendars.get(task.get("calendar_id")) or calendars.get(None)

    # week (ISO date of its first day) -> trade id -> hours
    weekly: dict[str, dict[int, float]] = {}
    # task id -> trade id -> hours, for the drill-down
    by_task: dict[int, dict[int, float]] = {}
    for trade_id, tasks_hours in allowed.items():
        for task_id, hours in tasks_hours.items():
            task = by_id.get(task_id)
            if task is None or hours <= 0:
                continue
            by_task.setdefault(task_id, {})[trade_id] = hours
            for day, worked in spread(task, hours, steps, diary(task)).items():
                week = week_of(day, first_day).isoformat()
                weekly.setdefault(week, {})[trade_id] = (
                    weekly.setdefault(week, {}).get(trade_id, 0.0) + worked)

    spent_by_week = spent_by_week or {}
    for (week, trade_id) in spent_by_week:
        weekly.setdefault(str(week), {}).setdefault(int(trade_id), 0.0)

    weeks = []
    running_planned = running_spent = 0.0
    for week in sorted(weekly):
        rows = []
        planned_hours = spent_hours = 0.0
        for trade_id in sorted(weekly[week], key=lambda i: trade_names.get(i, "")):
            hours = weekly[week][trade_id]
            booked = _num(spent_by_week.get((week, trade_id)))
            planned_hours += hours
            spent_hours += booked
            rows.append({
                "trade_id": trade_id, "trade": trade_names.get(trade_id, ""),
                "hours": hours, "engineers": hours / per_week,
                "people": _people(hours, per_week),
                "spent_hours": booked,
                "spent_engineers": booked / per_week,
            })
        running_planned += planned_hours
        running_spent += spent_hours
        weeks.append({
            "week": week,
            "ends": (date.fromisoformat(week) + timedelta(days=6)).isoformat(),
            "rows": rows,
            "hours": planned_hours,
            "engineers": planned_hours / per_week,
            "people": _people(planned_hours, per_week),
            "spent_hours": spent_hours,
            "cumulative_hours": running_planned,
            "cumulative_spent": running_spent,
        })

    trade_rows = []
    for trade in trades:
        trade_id = int(trade["id"])
        budget = _num(trade.get("budget_hours"))
        ceiling = budget * (1 - target)
        planned_hours = sum(allowed.get(trade_id, {}).values())
        booked = sum(hours for (_week, who), hours in spent_by_week.items()
                     if int(who) == trade_id)
        peak = max((sum(r["hours"] for r in week["rows"] if r["trade_id"] == trade_id)
                    for week in weeks), default=0.0)
        trade_rows.append({
            "id": trade_id, "name": trade_names.get(trade_id, ""),
            "colour": trade.get("color") or "", "office": trade.get("office") or "",
            "budget_hours": budget, "margin_hours": budget - ceiling,
            "ceiling_hours": ceiling, "planned_hours": planned_hours,
            "spent_hours": booked, "left_hours": ceiling - booked,
            "used_pct": (booked / ceiling) if ceiling > 0 else 0.0,
            "deliverables": len(allowed.get(trade_id, {})),
            "peak_hours": peak, "peak_engineers": peak / per_week,
        })

    budget_total = sum(row["budget_hours"] for row in trade_rows)
    ceiling_total = sum(row["ceiling_hours"] for row in trade_rows)
    planned_total = sum(row["planned_hours"] for row in trade_rows)
    spent_total = sum(row["spent_hours"] for row in trade_rows)
    return {
        "target_pct": target * 100,
        "hours_per_week": per_week,
        "budget_hours": budget_total,
        "margin_hours": budget_total - ceiling_total,
        "ceiling_hours": ceiling_total,
        "planned_hours": planned_total,
        "spent_hours": spent_total,
        "left_hours": ceiling_total - spent_total,
        "used_pct": (spent_total / ceiling_total) if ceiling_total > 0 else 0.0,
        "peak_engineers": max((week["engineers"] for week in weeks), default=0.0),
        "peak_week": max(weeks, key=lambda w: w["hours"])["week"] if weeks else "",
        "weeks": weeks,
        "trades": trade_rows,
        "by_task": by_task,
        "unplanned": [trade_names.get(t["id"], "") for t in trade_rows
                      if t["budget_hours"] > 0 and not t["deliverables"]],
    }


def _people(hours: float, per_week: float) -> int:
    """How many engineers that is, as a number of people you can actually ask
    for. Rounded up, because three-quarters of a person is a person."""
    import math

    return int(math.ceil(hours / per_week - 1e-9)) if hours > 1e-9 else 0


def task_rows(plan_of: Mapping[str, Any], tasks: Sequence[Mapping[str, Any]],
              trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The ceiling on each deliverable, trade by trade — the drill-down under
    the weekly plan, and the answer to "why is this line worth 180 hours"."""
    names = {int(t["id"]): str(t.get("name") or "") for t in trades}
    by_task = plan_of.get("by_task") or {}
    out = []
    for task in tasks:
        held = by_task.get(int(task["id"]))
        if not held:
            continue
        hours = sum(held.values())
        out.append({
            "id": int(task["id"]), "wbs": task.get("wbs") or "",
            "name": task.get("name") or "",
            "weight_pct": _num(task.get("weight_pct")),
            "start_date": task.get("start_date"), "submission_date": task.get("submission_date"),
            "duration_days": task.get("duration_days"),
            "hours": hours,
            "shares": [{"trade": names.get(trade_id, ""), "hours": value}
                       for trade_id, value in sorted(
                           held.items(), key=lambda pair: -pair[1])],
            "flat": not uses_workflow(task),
        })
    return sorted(out, key=lambda row: -row["hours"])


def curve(plan_of: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Planned hours against booked hours, week by week and cumulative — what
    the dashboard draws."""
    return [{"date": week["week"], "planned": week["cumulative_hours"],
             "spent": week["cumulative_spent"], "planned_week": week["hours"],
             "spent_week": week["spent_hours"]}
            for week in plan_of.get("weeks") or ()]
