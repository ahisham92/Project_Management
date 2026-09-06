"""This week: everything the project needs from us between one date and another.

The Internal tab opens on this rather than on a list of minuted items, because
a list of items is only ever half the week. The other half is on the programme
— packages going out, approvals coming back, and the lines that need a day's
work put into them without anything being submitted at the end of it. Reading
two tabs and holding the join in your head is how a week goes wrong.

Nothing here is stored. A requirement is a *reading* of a deliverable or a
minuted item that already exists, so changing it on this page changes the
record it came from, and a change made anywhere else shows up here on the next
draw. There is one copy of everything, which is the only way two screens can
never disagree.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

# What a line is being asked for, most pressing first. The order is the order
# they are grouped on the page, so it reads as a week rather than a table.
NEEDS: tuple[tuple[str, str, str], ...] = (
    ("submit", "Going out", "packages due to be issued"),
    ("approve", "Coming back", "approvals due from the client"),
    ("start", "Starting", "work that begins this week"),
    ("progress", "Carrying on", "nothing to submit — just the days that have to go in"),
    ("close", "Actions", "items falling due, from the minutes and from us"),
)
NEED_KEYS = tuple(key for key, _title, _hint in NEEDS)
NEED_TITLES = {key: title for key, title, _hint in NEEDS}
NEED_HINTS = {key: hint for key, _title, hint in NEEDS}

# Where a requirement came from, in the words the tabs use.
SOURCES = {
    "schedule": "Schedule",
    "client": "Minutes",
    "internal": "Internal",
}

_STATE_RANK = {"late": 0, "due": 1, "open": 2, "done": 3}
_SOURCE_RANK = {"schedule": 0, "client": 1, "internal": 2}


# --- which week ------------------------------------------------------------

def as_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def first_working_day(workdays: Any) -> int:
    """The day a working week opens, as Monday = 0.

    A Sunday-to-Thursday team's week starts on Sunday, and showing them a
    Monday-to-Sunday week would cut their week in half and call the first day
    of it "last week". Read off the working pattern rather than assumed.
    """
    week = str(workdays or "")
    if len(week) != 7 or "1" not in week:
        return 0
    if week[6] == "1" and week[5] != "1":       # Sunday on, Saturday off
        return 6
    return week.index("1")


def week_window(on_date: Any, first_day: int = 0) -> tuple[str, str]:
    """The seven days containing `on_date`, opening on `first_day`."""
    day = as_date(on_date) or date.today()
    start = day - timedelta(days=(day.weekday() - first_day) % 7)
    return start.isoformat(), (start + timedelta(days=6)).isoformat()


def shift(start: Any, weeks: int) -> str:
    """The same week, a number of weeks either side of it."""
    day = as_date(start) or date.today()
    return (day + timedelta(weeks=weeks)).isoformat()


def within(value: Any, start: str, end: str) -> bool:
    stamp = str(value or "")[:10]
    return bool(stamp) and start <= stamp <= end


# --- what the programme asks for -------------------------------------------

def _task_need(task: Mapping[str, Any], start: str, end: str) -> str:
    """The one thing this deliverable is being asked for this week.

    A line can answer to several of these at once — starting on Monday and
    submitting on Friday — so it is listed under the most pressing, once. Five
    rows for one deliverable is a table, not a week.
    """
    if task.get("is_complete"):
        return ""

    if within(task.get("submission_date"), start, end):
        return "submit"
    if task.get("is_submitted") and not task.get("is_approved") \
            and within(task.get("approval_due_date"), start, end):
        return "approve"
    if within(task.get("start_date"), start, end):
        return "start"

    # Running through the week without a date in it. This is the half a
    # programme never shows: nothing is due, and the days still have to go in.
    began = str(task.get("start_date") or "")[:10]
    ends = str(task.get("submission_date") or "")[:10]
    if began and ends and began <= end and ends >= start:
        return "progress"
    return ""


def _late_need(task: Mapping[str, Any]) -> str:
    """What an overdue line is being asked for, whatever week it is."""
    return "approve" if task.get("is_submitted") and not task.get("is_approved") else "submit"


def from_schedule(tasks: Iterable[Mapping[str, Any]], start: str, end: str,
                  targets: Mapping[int, float] | None = None) -> list[dict[str, Any]]:
    """The deliverables this week wants something from.

    `targets` is where each line should have got to by the end of the week —
    planned progress read at the Sunday rather than at today — which turns
    "carry on with it" into a number somebody can be held to.
    """
    rows: list[dict[str, Any]] = []
    for task in tasks:
        late = bool(task.get("is_late"))
        need = _late_need(task) if late else _task_need(task, start, end)
        if not need:
            continue

        due = (task.get("submission_date") if need in ("submit", "start", "progress")
               else task.get("approval_due_date"))
        target = float((targets or {}).get(task["id"], task.get("planned_pct") or 0.0))
        actual = float(task.get("actual_pct") or 0.0)

        rows.append({
            "source": "schedule",
            "need": need,
            "id": task["id"],
            "ref": task.get("wbs") or "",
            "title": task.get("name") or "",
            "detail": task.get("remarks") or "",
            "who": task.get("trade_names") or task.get("team_name") or "",
            "due": str(task.get("start_date") if need == "start" else due or "")[:10],
            "state": "late" if late else ("done" if task.get("is_complete") else "due"),
            "actual_pct": actual,
            "target_pct": target,
            # What the week actually asks for, in percentage points. A line
            # already past its target asks for nothing but keeping it there.
            "to_do_pct": max(0.0, target - actual),
            "days_late": int(task.get("days_late") or 0),
            "weight_pct": float(task.get("weight_pct") or 0.0),
            "task": task,
        })
    return rows


# --- what the registers ask for --------------------------------------------

def from_register(items: Iterable[Mapping[str, Any]], start: str, end: str,
                  source: str) -> list[dict[str, Any]]:
    """Open actions falling due this week, plus anything already overdue.

    An item raised inside the week comes too even when it has no date on it:
    it was raised in this week's meeting, and this is the week's page.
    """
    rows: list[dict[str, Any]] = []
    for item in items:
        if not item.get("is_open"):
            continue

        due = str(item.get("due_date") or "")[:10]
        raised = str(item.get("raised_date") or item.get("meeting_date") or "")[:10]
        overdue = bool(item.get("is_overdue"))
        falls_due = bool(due) and due <= end
        raised_now = within(raised, start, end)
        if not (overdue or falls_due or raised_now):
            continue

        rows.append({
            "source": source,
            "need": "close",
            "id": item["id"],
            "ref": item.get("ref") or "",
            "title": item.get("subject") or item.get("agreement") or "",
            "detail": item.get("agreement") or "",
            "who": item.get("owner_label") or "",
            "due": due,
            "state": "late" if overdue else ("due" if falls_due else "open"),
            "days_late": int(item.get("days_overdue") or 0),
            "item": item,
        })
    return rows


# --- the week, in one list -------------------------------------------------

def order(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Late first, then by the day it is wanted, then by where it came from."""
    from .minutes import ref_key

    return [dict(row) for row in sorted(rows, key=lambda r: (
        _STATE_RANK.get(str(r.get("state")), 9),
        str(r.get("due") or "9999-99-99"),
        _SOURCE_RANK.get(str(r.get("source")), 9),
        ref_key(r.get("ref")),
    ))]


def compile_week(tasks: Iterable[Mapping[str, Any]],
                 client_items: Iterable[Mapping[str, Any]],
                 internal_items: Iterable[Mapping[str, Any]],
                 start: str, end: str,
                 targets: Mapping[int, float] | None = None) -> list[dict[str, Any]]:
    """Everything wanted between two dates, from the programme and both registers."""
    return order([
        *from_schedule(tasks, start, end, targets),
        *from_register(client_items, start, end, "client"),
        *from_register(internal_items, start, end, "internal"),
    ])


def group(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """The week's requirements under the five headings, empty ones dropped."""
    held: dict[str, list[dict[str, Any]]] = {key: [] for key in NEED_KEYS}
    for row in rows:
        held.setdefault(str(row.get("need")), []).append(dict(row))
    return [
        {"need": key, "title": NEED_TITLES[key], "hint": NEED_HINTS[key], "rows": held[key]}
        for key in NEED_KEYS if held.get(key)
    ]


def summarise(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The headline counts above the week."""
    late = [r for r in rows if r.get("state") == "late"]
    return {
        "total": len(rows),
        "late": len(late),
        "deliverables": sum(1 for r in rows if r.get("source") == "schedule"),
        "actions": sum(1 for r in rows if r.get("need") == "close"),
        "submitting": sum(1 for r in rows if r.get("need") == "submit"),
        "carrying": sum(1 for r in rows if r.get("need") == "progress"),
        "behind": sum(1 for r in rows if float(r.get("to_do_pct") or 0.0) > 0.001),
        # What the week is worth to the project, which is the only honest way to
        # add up progress across deliverables: each line's shortfall weighted by
        # how much of the project that line is. Summing bare percentages would
        # make a 0.1% line count the same as a 9% one.
        "worth": sum(float(r.get("to_do_pct") or 0.0) * float(r.get("weight_pct") or 0.0)
                     for r in rows if r.get("source") == "schedule"),
    }


def meeting_ref(start: str) -> str:
    """The reference the week's internal meeting takes: WK-2026-06."""
    day = as_date(start)
    if day is None:
        return "WK"
    year, number, _weekday = day.isocalendar()
    return f"WK-{year}-{number:02d}"


def in_week(meetings: Iterable[Mapping[str, Any]], start: str, end: str) -> dict[str, Any] | None:
    """The meeting already held for this week, if there is one."""
    for meeting in meetings:
        if within(meeting.get("meeting_date"), start, end):
            return dict(meeting)
    return None
