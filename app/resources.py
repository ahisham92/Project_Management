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
week are different answers to "how many do I need". A week's headcount is the
sum of each trade's own figure, not the week's hours divided once: three trades
each wanting four tenths of a person is three people on the rota, because they
are three different people. The figure starts where the arithmetic puts it and
can be typed over — set a week to two and the hours it is allowed do not move,
only what each of those two is carrying.

**A share is held back for comments.** The design workflow says a deliverable is
80% done when it is submitted and 100% when the Code A arrives, which reads as
though the fortnight in between costs nothing. It does not: comments come back
and somebody answers them. So ``comments_reserve_pct`` of every workflow line's
ceiling is set aside at the start, and only the rest is planned into the weeks.

That reserve is settled when the client answers. A line that comes back **Code A
first time never needed it**, so the hours are released — real savings, earned by
finishing something cleanly. A line that comes back **Code B or C did need it**,
and the reserve is what pays for the rework. A line already finalised is
finished with: nothing is added to it and nothing is taken from it.

**Released hours can be redistributed, within the trade that saved them.** Turn
it on and a trade's released reserve is shared over that trade's own open lines,
in proportion to what each of them is already carrying. Never across trades:
Marine finishing cleanly is Marine's saving, and handing it to Geotechnical
would tell the marine team their care bought somebody else the slack. The notes
say which finished lines paid for it, so a bigger ceiling on next month's
drawings can be traced to the ones that went out right first time.
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

# What is held back on a workflow deliverable for answering comments. The
# workflow's own percentages say the fortnight between submission and Code A
# costs nothing, which is true only of the lines that come back clean.
DEFAULT_COMMENTS_RESERVE_PCT = 15.0


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


def reserve_of(project: Mapping[str, Any]) -> float:
    """The comments reserve, as a fraction. 15% comes back as 0.15."""
    percent = _num(project.get("comments_reserve_pct"), DEFAULT_COMMENTS_RESERVE_PCT)
    return min(0.9, max(0.0, percent / 100))


def redistributes(project: Mapping[str, Any]) -> bool:
    """Whether released reserves are pushed back into the open lines."""
    return bool(_num(project.get("redistribute_savings")))


# --- the comments reserve, and what happens to it ----------------------------
#
# Three words are used precisely below and are worth reading once.
#
#   held      — set aside on a line nobody has answered yet. Not planned into
#               the weeks, not spent, not available: it is waiting.
#   released  — the client said Code A first time, so the reserve was never
#               needed. This is the saving, and the only thing redistribution
#               has to give away.
#   consumed  — the client said Code B or C, and answering that is what the
#               reserve was for. It stays with the line that used it.

def _finished_clean(task: Mapping[str, Any]) -> bool:
    """Approved, first time of asking. The reserve was never needed."""
    return bool(task.get("is_approved")) and int(_num(task.get("revision"))) == 0


def _finalised(task: Mapping[str, Any]) -> bool:
    """Done with, either way. Nothing is added to it and nothing taken from it."""
    return bool(task.get("is_approved")) or bool(task.get("is_complete"))


def reserves(tasks: Sequence[Mapping[str, Any]], allowed: Mapping[int, Mapping[int, float]],
             reserve: float) -> dict[int, dict[int, dict[str, Any]]]:
    """What is held, released or consumed on each line, trade by trade.

    Keyed ``{trade_id: {task_id: {...}}}`` to match the ceilings it is read
    beside. Only workflow lines carry a reserve: a transmittal or a meeting has
    no client review to answer, so holding back a sixth of it would be
    inventing a saving that cannot happen.
    """
    by_id = {int(t["id"]): t for t in tasks}
    out: dict[int, dict[int, dict[str, Any]]] = {}
    for trade_id, per_task in allowed.items():
        for task_id, hours in per_task.items():
            task = by_id.get(task_id)
            if task is None:
                continue
            share = reserve if uses_workflow(task) else 0.0
            amount = hours * share
            if amount <= 0:
                state = "none"
            elif _finished_clean(task):
                state = "released"
            elif _finalised(task):
                state = "consumed"
            else:
                state = "held"
            out.setdefault(trade_id, {})[task_id] = {
                "hours": amount, "state": state,
                "wbs": task.get("wbs") or "", "name": task.get("name") or "",
                "revision": int(_num(task.get("revision"))),
                "open": not _finalised(task),
            }
    return out


def redistribute(allowed: Mapping[int, Mapping[int, float]],
                 held: Mapping[int, Mapping[int, Mapping[str, Any]]],
                 on: bool = True) -> tuple[dict[int, dict[int, float]], list[dict[str, Any]]]:
    """The hours actually planned per line, and the notes explaining any move.

    Every line starts at its ceiling less whatever its reserve is holding. Then,
    if redistribution is on, each trade's released hours are shared over that
    trade's own open lines in proportion to what they already carry — a bigger
    line absorbs more of it, which is where the work will actually go.

    Nothing crosses a trade. A trade that finished a line cleanly earned that
    slack, and giving it to another discipline would tell the team that did the
    careful work that it bought somebody else the room.
    """
    planned: dict[int, dict[int, float]] = {}
    notes: list[dict[str, Any]] = []

    for trade_id, per_task in allowed.items():
        mine = held.get(trade_id) or {}
        working = {task_id: hours - _num((mine.get(task_id) or {}).get("hours"))
                   for task_id, hours in per_task.items()}

        # A consumed reserve belongs to the line that used it: the rework was
        # real work and its hours stay where they were spent.
        for task_id, note in mine.items():
            if note["state"] == "consumed":
                working[task_id] = working.get(task_id, 0.0) + note["hours"]

        freed = sum(note["hours"] for note in mine.values() if note["state"] == "released")
        open_lines = {task_id: hours for task_id, hours in working.items()
                      if hours > 0 and (mine.get(task_id) or {}).get("open", True)}
        base = sum(open_lines.values())

        sharing = on and freed > 1e-9 and base > 1e-9
        if sharing:
            for task_id, hours in open_lines.items():
                working[task_id] = hours + freed * hours / base

        # A note whenever a trade released anything, whether or not it was
        # shared out: "we saved 40 hours" is worth reading on its own, and
        # somebody deciding whether to redistribute wants to see where it came
        # from before they press the button rather than after.
        if freed > 1e-9:
            notes.append({
                "trade_id": trade_id,
                "hours": freed,
                "shared": sharing,
                "lines": len(open_lines) if sharing else 0,
                "open_lines": len(open_lines),
                "from": sorted(
                    ({"wbs": note["wbs"], "name": note["name"], "hours": note["hours"]}
                     for note in mine.values() if note["state"] == "released"),
                    key=lambda row: -row["hours"]),
            })
        planned[trade_id] = working
    return planned, notes


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
         first_day: int = 0,
         set_by_hand: Mapping[tuple[str, int], float] | None = None) -> dict[str, Any]:
    """The whole resource plan: hours and people, per week, per trade.

    `spent_by_week` is what has actually been booked, keyed by (week, trade id),
    so the plan and the timesheet can be read against each other without this
    module knowing anything about how hours are recorded. `set_by_hand` is keyed
    the same way and holds the headcounts somebody has typed over: the hours a
    week is allowed never move for one, only what each engineer is carrying.
    """
    target = target_of(project)
    per_week = hours_per_week(project)
    reserve = reserve_of(project)
    sharing = redistributes(project)

    allowed = ceilings(tasks, trades, target)
    held = reserves(tasks, allowed, reserve)
    working, notes = redistribute(allowed, held, sharing)

    by_id = {int(t["id"]): t for t in tasks}
    trade_names = {int(t["id"]): str(t.get("name") or "") for t in trades}
    set_by_hand = {(str(week), int(who)): value
                   for (week, who), value in (set_by_hand or {}).items()}

    def diary(task: Mapping[str, Any]):
        if not calendars:
            return None
        return calendars.get(task.get("calendar_id")) or calendars.get(None)

    # week (ISO date of its first day) -> trade id -> hours
    weekly: dict[str, dict[int, float]] = {}
    # task id -> trade id -> hours, for the drill-down
    by_task: dict[int, dict[int, float]] = {}
    for trade_id, tasks_hours in working.items():
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
    # A week somebody has staffed by hand is a week to show, even if the plan
    # itself has nothing in it: the entry is the point.
    for (week, trade_id) in set_by_hand:
        weekly.setdefault(week, {}).setdefault(trade_id, 0.0)

    ordered = sorted(trade_names, key=lambda i: trade_names.get(i, ""))
    weeks = []
    running_planned = running_spent = 0.0
    for week in sorted(weekly):
        rows = []
        planned_hours = spent_hours = 0.0
        heads = 0
        for trade_id in sorted(weekly[week], key=lambda i: trade_names.get(i, "")):
            hours = weekly[week][trade_id]
            booked = _num(spent_by_week.get((week, trade_id)))
            wanted = _people(hours, per_week)
            typed = set_by_hand.get((week, trade_id))
            people = int(round(typed)) if typed is not None else wanted
            planned_hours += hours
            spent_hours += booked
            heads += people
            rows.append({
                "trade_id": trade_id, "trade": trade_names.get(trade_id, ""),
                "hours": hours, "engineers": hours / per_week,
                "people": people, "wanted": wanted,
                "by_hand": typed is not None,
                # What one of those engineers is carrying. The hours do not move
                # when somebody sets the headcount, so this is where a decision
                # to run a week short shows up as a number.
                "each_hours": (hours / people) if people else 0.0,
                "spent_hours": booked,
                "spent_engineers": booked / per_week,
            })
        running_planned += planned_hours
        running_spent += spent_hours
        # The week's headcount is the sum of its trades, not its hours divided
        # once: three trades each wanting four tenths of a person is three
        # people, because they are three different people.
        weeks.append({
            "week": week,
            "ends": (date.fromisoformat(week) + timedelta(days=6)).isoformat(),
            "rows": rows,
            "by_trade": {row["trade_id"]: row for row in rows},
            "hours": planned_hours,
            "engineers": sum(row["hours"] for row in rows) / per_week,
            "people": heads,
            "wanted": sum(row["wanted"] for row in rows),
            "by_hand": any(row["by_hand"] for row in rows),
            "spent_hours": spent_hours,
            "cumulative_hours": running_planned,
            "cumulative_spent": running_spent,
        })

    trade_rows = []
    for trade in trades:
        trade_id = int(trade["id"])
        budget = _num(trade.get("budget_hours"))
        ceiling = budget * (1 - target)
        mine = held.get(trade_id) or {}
        planned_hours = sum(working.get(trade_id, {}).values())
        booked = sum(hours for (_week, who), hours in spent_by_week.items()
                     if int(who) == trade_id)
        peak = max((week["by_trade"].get(trade_id, {}).get("hours", 0.0)
                    for week in weeks), default=0.0)
        busy = [week["by_trade"][trade_id]["people"] for week in weeks
                if week["by_trade"].get(trade_id, {}).get("hours", 0.0) > 1e-9]
        trade_rows.append({
            "id": trade_id, "name": trade_names.get(trade_id, ""),
            "colour": trade.get("color") or "", "office": trade.get("office") or "",
            "budget_hours": budget, "margin_hours": budget - ceiling,
            "ceiling_hours": ceiling, "planned_hours": planned_hours,
            "spent_hours": booked, "left_hours": ceiling - booked,
            "used_pct": (booked / ceiling) if ceiling > 0 else 0.0,
            "deliverables": len(allowed.get(trade_id, {})),
            "peak_hours": peak, "peak_engineers": peak / per_week,
            "peak_people": max(busy, default=0),
            "average_people": (sum(busy) / len(busy)) if busy else 0.0,
            "held_hours": sum(n["hours"] for n in mine.values() if n["state"] == "held"),
            "released_hours": sum(n["hours"] for n in mine.values() if n["state"] == "released"),
            "consumed_hours": sum(n["hours"] for n in mine.values() if n["state"] == "consumed"),
        })

    budget_total = sum(row["budget_hours"] for row in trade_rows)
    ceiling_total = sum(row["ceiling_hours"] for row in trade_rows)
    planned_total = sum(row["planned_hours"] for row in trade_rows)
    spent_total = sum(row["spent_hours"] for row in trade_rows)
    staffed = [week["people"] for week in weeks if week["hours"] > 1e-9]
    for note in notes:
        note["trade"] = trade_names.get(note["trade_id"], "")
    return {
        "target_pct": target * 100,
        "reserve_pct": reserve * 100,
        "redistributing": sharing,
        "hours_per_week": per_week,
        "budget_hours": budget_total,
        "margin_hours": budget_total - ceiling_total,
        "ceiling_hours": ceiling_total,
        "planned_hours": planned_total,
        "spent_hours": spent_total,
        "left_hours": ceiling_total - spent_total,
        "used_pct": (spent_total / ceiling_total) if ceiling_total > 0 else 0.0,
        "held_hours": sum(row["held_hours"] for row in trade_rows),
        "released_hours": sum(row["released_hours"] for row in trade_rows),
        "consumed_hours": sum(row["consumed_hours"] for row in trade_rows),
        "peak_engineers": max((week["engineers"] for week in weeks), default=0.0),
        "peak_people": max(staffed, default=0),
        "average_people": (sum(staffed) / len(staffed)) if staffed else 0.0,
        "peak_week": max(weeks, key=lambda w: w["hours"])["week"] if weeks else "",
        "weeks": weeks,
        "trades": trade_rows,
        "trade_order": [{"id": i, "name": trade_names[i]} for i in ordered],
        "by_task": by_task,
        "reserves": held,
        "notes": sorted(notes, key=lambda n: -n["hours"]),
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
    the weekly plan, and the answer to "why is this line worth 180 hours".

    `by_trade` carries a column per trade whether or not that trade is on the
    line, so the table can be read down a discipline as well as across a
    deliverable.
    """
    names = {int(t["id"]): str(t.get("name") or "") for t in trades}
    by_task = plan_of.get("by_task") or {}
    kept = plan_of.get("reserves") or {}
    out = []
    for task in tasks:
        task_id = int(task["id"])
        share_of = by_task.get(task_id)
        if not share_of:
            continue
        hours = sum(share_of.values())
        mine = {trade_id: (kept.get(trade_id, {}).get(task_id) or {})
                for trade_id in names}
        states = {note.get("state") for note in mine.values() if note}
        out.append({
            "id": task_id, "wbs": task.get("wbs") or "",
            "name": task.get("name") or "",
            "weight_pct": _num(task.get("weight_pct")),
            "start_date": task.get("start_date"), "submission_date": task.get("submission_date"),
            "duration_days": task.get("duration_days"),
            "hours": hours,
            "by_trade": {trade_id: share_of.get(trade_id, 0.0) for trade_id in names},
            "shares": [{"trade": names.get(trade_id, ""), "hours": value}
                       for trade_id, value in sorted(
                           share_of.items(), key=lambda pair: -pair[1])],
            "flat": not uses_workflow(task),
            # What the comments reserve is doing on this line. One word for the
            # row, because a line is answered or it is not.
            "reserve_hours": sum(_num(note.get("hours")) for note in mine.values() if note),
            "reserve_state": ("released" if "released" in states
                              else "consumed" if "consumed" in states
                              else "held" if "held" in states else "none"),
            "finalised": bool(task.get("is_approved")) or bool(task.get("is_complete")),
            "revision": int(_num(task.get("revision"))),
        })
    return sorted(out, key=lambda row: -row["hours"])


def curve(plan_of: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Planned hours against booked hours, week by week and cumulative — what
    the dashboard draws."""
    return [{"date": week["week"], "planned": week["cumulative_hours"],
             "spent": week["cumulative_spent"], "planned_week": week["hours"],
             "spent_week": week["spent_hours"]}
            for week in plan_of.get("weeks") or ()]


# --- reading the tables in whatever order somebody wants ---------------------
#
# The trade columns are the reason this is here rather than in `sorting`: a
# project's trades are its own, so the sortable columns are not a list that can
# be written down in advance. `trade:7` is a column, and which one depends on
# the project.

TASK_COLUMNS: dict[str, tuple[str, bool]] = {
    "wbs": ("WBS", False),
    "name": ("Deliverable", False),
    "weight": ("Weight", True),
    "start": ("Starts", False),
    "submission": ("Submits", False),
    "hours": ("Hours", True),
    "reserve": ("Reserve", True),
}

WEEK_COLUMNS: dict[str, tuple[str, bool]] = {
    "week": ("Week", False),
    "hours": ("Hours", True),
    "engineers": ("Engineers", True),
    "booked": ("Booked", True),
}


def _trade_column(column: str) -> int | None:
    """`trade:7` names trade 7's column; anything else names none of them."""
    if not str(column).startswith("trade:"):
        return None
    try:
        return int(str(column).split(":", 1)[1])
    except (TypeError, ValueError):
        return None


def sortable(fixed: Mapping[str, tuple[str, bool]],
             trades: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, bool]]:
    """Every column a table can be sorted on, the trades included."""
    out = dict(fixed)
    for trade in trades:
        out[f"trade:{int(trade['id'])}"] = (str(trade.get("name") or ""), True)
    return out


def order_for(column: str | None, direction: str | None,
              columns: Mapping[str, tuple[str, bool]], fallback: str) -> tuple[str, str]:
    """A safe (column, direction) pair from whatever arrived in the query."""
    column = column if column in columns else fallback
    if direction not in ("asc", "desc"):
        direction = "desc" if columns[column][1] else "asc"
    return column, direction


def sort_tasks(rows: Sequence[Mapping[str, Any]], column: str,
               direction: str = "asc") -> list[dict[str, Any]]:
    """The ceiling table in one column's order, WBS breaking every tie."""
    from .sorting import _wbs_key

    trade_id = _trade_column(column)
    if trade_id is not None:
        key = lambda row: _num((row.get("by_trade") or {}).get(trade_id))   # noqa: E731
    else:
        keys = {
            "wbs": lambda row: _wbs_key(row.get("wbs")),
            "name": lambda row: str(row.get("name") or "").lower(),
            "weight": lambda row: _num(row.get("weight_pct")),
            "start": lambda row: str(row.get("start_date") or ""),
            "submission": lambda row: str(row.get("submission_date") or ""),
            "hours": lambda row: _num(row.get("hours")),
            "reserve": lambda row: _num(row.get("reserve_hours")),
        }
        key = keys.get(column, keys["hours"])

    # WBS second, so two lines worth the same hours still read in a fixed order
    # rather than swapping places every time the page is drawn.
    ordered = sorted(rows, key=lambda row: (key(row), _wbs_key(row.get("wbs"))))
    return list(reversed(ordered)) if direction == "desc" else list(ordered)


def sort_weeks(rows: Sequence[Mapping[str, Any]], column: str,
               direction: str = "asc") -> list[dict[str, Any]]:
    """The weekly table in one column's order, the calendar breaking ties."""
    trade_id = _trade_column(column)
    if trade_id is not None:
        key = lambda row: _num((row.get("by_trade") or {}).get(trade_id, {}).get("hours"))  # noqa: E731
    else:
        keys = {
            "week": lambda row: str(row.get("week") or ""),
            "hours": lambda row: _num(row.get("hours")),
            "engineers": lambda row: _num(row.get("people")),
            "booked": lambda row: _num(row.get("spent_hours")),
        }
        key = keys.get(column, keys["week"])

    ordered = sorted(rows, key=lambda row: (key(row), str(row.get("week") or "")))
    return list(reversed(ordered)) if direction == "desc" else list(ordered)

