"""The design workflow: the steps a deliverable passes through, what each one is
worth, and when it is planned.

The default steps follow a design submission cycle:

    Design started        10%   on the start date
    IDC provided          40%   5 days before submission
    Comments addressed    60%   2 days before submission
    Submitted to client   80%   on the submission date
    Code A received      100%  14 days after submission

Every figure here is a starting point — percentages, anchors and offsets are all
editable per project on the Setup sheet.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Sequence

from .calc import parse_date, to_iso

NOT_STARTED = ""
CODE_A = "code_a"
SUBMITTED = "submitted"

DEFAULT_STEPS: list[dict[str, Any]] = [
    {"key": "design_start", "name": "Design started", "percent": 0.10, "anchor": "start", "offset_days": 0},
    {"key": "idc", "name": "IDC provided", "percent": 0.40, "anchor": "submission", "offset_days": -5},
    {"key": "comments_addressed", "name": "Comments addressed", "percent": 0.60, "anchor": "submission", "offset_days": -2},
    {"key": SUBMITTED, "name": "Submitted to client", "percent": 0.80, "anchor": "submission", "offset_days": 0},
    {"key": CODE_A, "name": "Code A received", "percent": 1.00, "anchor": "submission", "offset_days": 14},
]


def default_steps() -> list[dict[str, Any]]:
    return [dict(step, sort_order=i + 1) for i, step in enumerate(DEFAULT_STEPS)]


def ordered(steps: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Steps sorted the way progress runs: by percent, then by declared order."""
    return sorted((dict(s) for s in steps), key=lambda s: (float(s["percent"]), int(s.get("sort_order") or 0)))


def step_by_key(steps: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any] | None:
    return next((dict(s) for s in steps if s["key"] == key), None)


def percent_for(steps: Sequence[Mapping[str, Any]], key: str) -> float:
    step = step_by_key(steps, key)
    return float(step["percent"]) if step else 0.0


def planned_date(step: Mapping[str, Any], start_date: str, submission_date: str) -> str:
    """When a step is planned, from its anchor and offset."""
    anchor = start_date if step.get("anchor") == "start" else submission_date
    if not anchor:
        anchor = submission_date or start_date
    return to_iso(parse_date(anchor) + timedelta(days=float(step.get("offset_days") or 0)))


def schedule_for(
    steps: Sequence[Mapping[str, Any]], start_date: str, submission_date: str
) -> list[dict[str, Any]]:
    """Every step with the date it is planned for, in progress order."""
    plan = []
    for step in ordered(steps):
        plan.append(
            {
                "key": step["key"],
                "name": step["name"],
                "percent": float(step["percent"]),
                "anchor": step.get("anchor", "submission"),
                "offset_days": float(step.get("offset_days") or 0),
                "date": planned_date(step, start_date, submission_date),
            }
        )
    # A later step should never be planned before an earlier one, however the
    # offsets are edited; clamp so the planned curve cannot run backwards.
    for earlier, later in zip(plan, plan[1:]):
        if later["date"] < earlier["date"]:
            later["date"] = earlier["date"]
    return plan


def planned_pct_from_schedule(plan: Sequence[Mapping[str, Any]], on_date: str) -> float:
    """Planned percent complete on a date.

    Progress through a submission cycle happens in steps, not smoothly: a
    deliverable is planned to be at 40% once the IDC date has passed and stays
    there until the comments date. So the planned figure is the percentage of the
    last step whose date has arrived — it only ever reads one of the step values
    (10, 40, 60, 80, 100 by default), never something in between.
    """
    if not plan:
        return 0.0

    day = parse_date(on_date)
    planned = 0.0
    for step in plan:
        if parse_date(step["date"]) <= day:
            planned = step["percent"]
        else:
            break
    return planned


def next_step(steps: Sequence[Mapping[str, Any]], current_key: str) -> dict[str, Any] | None:
    """The step that follows the current one, or the first when nothing is set."""
    plan = ordered(steps)
    if not plan:
        return None
    if not current_key:
        return plan[0]
    for index, step in enumerate(plan):
        if step["key"] == current_key:
            return plan[index + 1] if index + 1 < len(plan) else None
    return plan[0]


def is_submitted(steps: Sequence[Mapping[str, Any]], status_key: str) -> bool:
    """True once a deliverable has reached the submission step (or beyond)."""
    submitted = step_by_key(steps, SUBMITTED)
    current = step_by_key(steps, status_key)
    if not submitted or not current:
        return False
    return float(current["percent"]) >= float(submitted["percent"])


def is_approved(steps: Sequence[Mapping[str, Any]], status_key: str) -> bool:
    step = step_by_key(steps, status_key)
    return bool(step) and float(step["percent"]) >= 1.0
