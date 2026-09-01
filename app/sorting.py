"""Sorting for the deliverable tables on the progress and schedule tabs."""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

# Column key -> (heading, whether the natural reading is largest-first).
COLUMNS: dict[str, tuple[str, bool]] = {
    "wbs": ("WBS", False),
    "name": ("Deliverable", False),
    "section": ("Section", False),
    "weight": ("Weight", True),
    "start": ("Start", False),
    "submission": ("Submission", False),
    "due": ("Due", False),
    "planned": ("Planned", True),
    "actual": ("Actual", True),
    "variance": ("Variance", False),
    "status": ("Status", False),
    "revision": ("Revision", True),
    "days": ("Days", False),
}

DEFAULT = "wbs"
_NUMBER = re.compile(r"(\d+)")


def _wbs_key(value: Any) -> tuple:
    """1.2 before 1.10: compare the numeric parts as numbers, not text."""
    parts = _NUMBER.split(str(value or ""))
    return tuple((int(p), "") if p.isdigit() else (10**9, p.lower()) for p in parts if p)


def _key_for(column: str):
    getters = {
        "wbs": lambda t: _wbs_key(t.get("wbs")),
        "name": lambda t: str(t.get("name") or "").lower(),
        "section": lambda t: (str(t.get("section_name") or "").lower(), _wbs_key(t.get("wbs"))),
        "weight": lambda t: float(t.get("weight_pct") or 0),
        "start": lambda t: str(t.get("start_date") or ""),
        "submission": lambda t: str(t.get("submission_date") or ""),
        "due": lambda t: str(t.get("due_date") or ""),
        "planned": lambda t: float(t.get("planned_pct") or 0),
        "actual": lambda t: float(t.get("actual_pct") or 0),
        "variance": lambda t: float(t.get("variance") or 0),
        "status": lambda t: (float(t.get("actual_pct") or 0), str(t.get("status_name") or "")),
        "revision": lambda t: int(t.get("revision") or 0),
        "days": lambda t: int(t.get("days_to_due") or 0),
    }
    return getters.get(column, getters["wbs"])


def normalise(column: str | None, direction: str | None) -> tuple[str, str]:
    """A safe (column, direction) pair from whatever arrived in the query."""
    column = column if column in COLUMNS else DEFAULT
    if direction not in ("asc", "desc"):
        direction = "desc" if COLUMNS[column][1] else "asc"
    return column, direction


def sort_tasks(tasks: Sequence[Mapping[str, Any]], column: str, direction: str) -> list[dict[str, Any]]:
    """Rows in the requested order, always breaking ties on WBS so the result
    is stable rather than depending on the order rows arrived in."""
    key = _key_for(column)
    ordered = sorted(tasks, key=lambda t: _wbs_key(t.get("wbs")))
    return sorted(ordered, key=key, reverse=(direction == "desc"))


def flip(column: str, current_column: str, current_direction: str) -> str:
    """The direction a header link should ask for when it is clicked."""
    if column != current_column:
        return "desc" if COLUMNS.get(column, ("", False))[1] else "asc"
    return "asc" if current_direction == "desc" else "desc"
