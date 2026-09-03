"""Minutes of meeting: the vocabulary, filtering and sorting.

Pure functions over plain dictionaries, so the rules that decide what "open",
"overdue" or "affects time" mean are testable without a database or a request.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from .dates import to_display

# What an item bears on. Kept as one field rather than two flags so a filter is
# a single comparison and the minutes read as one column.
IMPACTS: tuple[tuple[str, str], ...] = (
    ("none", "No impact"),
    ("time", "Time"),
    ("cost", "Cost"),
    ("both", "Time & cost"),
)
IMPACT_KEYS = tuple(key for key, _ in IMPACTS)
IMPACT_NAMES = dict(IMPACTS)

# Who owns an item: the party responsible, not a named person. People come and
# go from a project while the responsibility stays where it is.
OWNERS: tuple[str, ...] = ("PM", "Client", "MR", "ST", "GE", "WE", "EL", "PMC")

STATUSES: tuple[tuple[str, str], ...] = (("open", "Open"), ("closed", "Closed"))
STATUS_KEYS = tuple(key for key, _ in STATUSES)
STATUS_NAMES = dict(STATUSES)

# The chips across the top of the register.
FILTERS: tuple[tuple[str, str], ...] = (
    ("open", "Open"),
    ("overdue", "Overdue"),
    ("time", "Affects time"),
    ("cost", "Affects cost"),
    ("closed", "Closed"),
    ("all", "All items"),
)
FILTER_KEYS = tuple(key for key, _ in FILTERS)
DEFAULT_FILTER = "open"

# Column key -> (heading, whether the natural first click is largest/latest first).
COLUMNS: dict[str, tuple[str, bool]] = {
    "ref": ("Item", False),
    "subject": ("Subject", False),
    "meeting": ("Meeting", True),
    "owner": ("Owner", False),
    "trade": ("Trade", False),
    "impact": ("Affects", False),
    "raised": ("Raised", True),
    "due": ("Due", False),
    "status": ("Status", False),
}
DEFAULT_SORT = "due"

_NUMBER = re.compile(r"(\d+)")
_IMPACT_MATCHES = {"time": ("time", "both"), "cost": ("cost", "both")}


def impact_name(key: Any) -> str:
    return IMPACT_NAMES.get(str(key or "none"), "No impact")


def normalise_impact(value: Any) -> str:
    text = str(value or "none").strip().lower()
    return text if text in IMPACT_KEYS else "none"


def normalise_status(value: Any) -> str:
    text = str(value or "open").strip().lower()
    return text if text in STATUS_KEYS else "open"


def normalise_owner(value: Any) -> str:
    """One of the party codes, matched however it was typed, or blank."""
    text = str(value or "").strip()
    for code in OWNERS:
        if text.lower() == code.lower():
            return code
    return ""


def ref_key(value: Any) -> tuple:
    """4.2 before 4.10 — the numeric runs compare as numbers, not as text."""
    parts = _NUMBER.split(str(value or ""))
    return tuple((int(p), "") if p.isdigit() else (10**9, p.lower()) for p in parts if p)


def owner_of(item: Mapping[str, Any]) -> str:
    """The party that owns an item.

    Falls back to the free-text name an older item carried, so nothing
    disappears from a register written before owners became party codes.
    """
    return str(item.get("owner_code") or item.get("owner_name") or "").strip()


def trades_of(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The trades an item sits with — an item can bear on several at once."""
    return list(item.get("trades") or [])


def trade_names(item: Mapping[str, Any]) -> str:
    """The item's trades as one line, for a table cell or a document."""
    return ", ".join(str(trade.get("name") or "") for trade in trades_of(item))


def decorate(item: Mapping[str, Any], on_date: str) -> dict[str, Any]:
    """One item with the reading the screens need: open, overdue, days left."""
    row = dict(item)
    row["status"] = normalise_status(row.get("status"))
    row["impact"] = normalise_impact(row.get("impact"))
    row["is_open"] = row["status"] == "open"
    row["status_name"] = STATUS_NAMES[row["status"]]
    row["impact_name"] = impact_name(row["impact"])
    row["affects_time"] = row["impact"] in ("time", "both")
    row["affects_cost"] = row["impact"] in ("cost", "both")
    row["owner_label"] = owner_of(row)
    row["trade_ids"] = [int(trade["id"]) for trade in trades_of(row)]
    row["trade_names"] = trade_names(row)

    due = str(row.get("due_date") or "")
    row["days_to_due"] = _days_between(on_date, due) if due else None
    row["is_overdue"] = bool(row["is_open"] and due and due < on_date)
    row["days_overdue"] = -row["days_to_due"] if row["is_overdue"] and row["days_to_due"] is not None else 0
    row["is_due_soon"] = bool(
        row["is_open"] and row["days_to_due"] is not None and 0 <= row["days_to_due"] <= 7
    )
    return row


def _days_between(from_iso: str, to_iso: str) -> int | None:
    try:
        start = date.fromisoformat(str(from_iso)[:10])
        end = date.fromisoformat(str(to_iso)[:10])
    except ValueError:
        return None
    return (end - start).days


def matches_search(item: Mapping[str, Any], needle: str) -> bool:
    """Keyword search across everything a reader would scan by eye."""
    if not needle:
        return True
    words = [w for w in needle.lower().split() if w]
    haystack = " ".join(
        str(item.get(field) or "")
        for field in ("ref", "subject", "discussion", "agreement", "owner_code",
                      "owner_name", "trade_names", "meeting_ref", "meeting_title")
    ).lower()
    return all(word in haystack for word in words)


def filter_items(
    items: Iterable[Mapping[str, Any]],
    *,
    chip: str = DEFAULT_FILTER,
    search: str = "",
    owner: str = "",
    trade_id: int | None = None,
    meeting_id: int | None = None,
    impact: str = "",
    date_from: str = "",
    date_to: str = "",
) -> list[dict[str, Any]]:
    """The register narrowed down to what was asked for.

    Every filter is independent, so "open items owned by Marine raised in
    September" is one pass with three of them set.
    """
    chip = chip if chip in FILTER_KEYS else DEFAULT_FILTER
    kept: list[dict[str, Any]] = []

    for row in items:
        item = dict(row)
        if chip == "open" and not item.get("is_open"):
            continue
        if chip == "closed" and item.get("is_open"):
            continue
        if chip == "overdue" and not item.get("is_overdue"):
            continue
        if chip in _IMPACT_MATCHES and item.get("impact") not in _IMPACT_MATCHES[chip]:
            continue
        if impact and item.get("impact") != impact:
            continue
        if owner and owner_of(item) != owner:
            continue
        # An item bearing on several trades answers to a filter on any of them.
        if trade_id is not None and trade_id not in (item.get("trade_ids") or []):
            continue
        if meeting_id is not None and item.get("meeting_id") != meeting_id:
            continue

        # The date range reads on when an item was raised, which is what
        # "everything from the last two meetings" means to a reader.
        stamp = str(item.get("raised_date") or item.get("meeting_date") or "")
        if date_from and (not stamp or stamp < date_from):
            continue
        if date_to and (not stamp or stamp > date_to):
            continue
        if not matches_search(item, search):
            continue
        kept.append(item)

    return kept


def _key_for(column: str):
    getters = {
        "ref": lambda i: ref_key(i.get("ref")),
        "subject": lambda i: str(i.get("subject") or "").lower(),
        "meeting": lambda i: (str(i.get("meeting_date") or ""), ref_key(i.get("ref"))),
        "owner": lambda i: owner_of(i).lower(),
        "trade": lambda i: str(i.get("trade_names") or "").lower(),
        "impact": lambda i: IMPACT_KEYS.index(normalise_impact(i.get("impact"))),
        "raised": lambda i: str(i.get("raised_date") or i.get("meeting_date") or ""),
        "due": lambda i: str(i.get("due_date") or ""),
        "status": lambda i: (not i.get("is_open"), str(i.get("due_date") or "")),
    }
    return getters.get(column, getters[DEFAULT_SORT])


def normalise_sort(column: str | None, direction: str | None) -> tuple[str, str]:
    column = column if column in COLUMNS else DEFAULT_SORT
    if direction not in ("asc", "desc"):
        direction = "desc" if COLUMNS[column][1] else "asc"
    return column, direction


def sort_items(items: Sequence[Mapping[str, Any]], column: str, direction: str) -> list[dict[str, Any]]:
    """Rows in the requested order, breaking ties on the meeting date then the
    item reference so the result never depends on the order rows arrived in.

    Items with no action date stay at the bottom whichever way the Due column
    is read; reversing the order would otherwise open the list with the rows
    that say least.
    """
    key = _key_for(column)
    settled = sorted(items, key=lambda i: (str(i.get("meeting_date") or ""), ref_key(i.get("ref"))))
    undated: list[Mapping[str, Any]] = []
    if column == "due":
        settled, undated = ([i for i in settled if i.get("due_date")],
                            [i for i in settled if not i.get("due_date")])
    ordered = sorted(settled, key=key, reverse=(direction == "desc"))
    return [dict(i) for i in ordered + undated]


def summarise(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """The headline counts above the register."""
    return {
        "total": len(items),
        "open": sum(1 for i in items if i.get("is_open")),
        "closed": sum(1 for i in items if not i.get("is_open")),
        "overdue": sum(1 for i in items if i.get("is_overdue")),
        "due_soon": sum(1 for i in items if i.get("is_due_soon")),
        "time": sum(1 for i in items if i.get("is_open") and i.get("affects_time")),
        "cost": sum(1 for i in items if i.get("is_open") and i.get("affects_cost")),
    }


def meeting_stem(meeting_ref: Any) -> str:
    """The number a meeting's items hang off: MOM-04 -> "4".

    Blank when the meeting has no number of its own, so its items read
    1, 2, 3 rather than acquiring a stem that means nothing.
    """
    match = _NUMBER.search(str(meeting_ref or ""))
    return str(int(match.group(1))) if match else ""


def item_ref(stem: str, position: int) -> str:
    """The number of the item sitting at `position` (1-based)."""
    return f"{stem}.{position}" if stem else str(position)


def renumber(items: Sequence[Mapping[str, Any]], meeting_ref: Any = "") -> list[dict[str, Any]]:
    """Numbers for one meeting's items, in the order they are given.

    An item's number is its position, so it cannot be typed, cannot collide
    with another item's, and follows the item when it is moved.
    """
    stem = meeting_stem(meeting_ref)
    return [
        {"id": item["id"], "sort_order": position, "ref": item_ref(stem, position)}
        for position, item in enumerate(items, start=1)
    ]


def moved(items: Sequence[Mapping[str, Any]], item_id: int, direction: str) -> list[Mapping[str, Any]]:
    """The list with one item swapped with the neighbour above or below it.

    Asking to move the first item up, or the last one down, leaves the order
    alone rather than wrapping around to the other end.
    """
    rows = list(items)
    here = next((index for index, row in enumerate(rows) if row["id"] == item_id), None)
    if here is None:
        return rows
    there = here - 1 if direction == "up" else here + 1
    if 0 <= there < len(rows):
        rows[here], rows[there] = rows[there], rows[here]
    return rows


def next_ref(items: Sequence[Mapping[str, Any]], meeting_ref: Any = "") -> str:
    """The number the next item added to a meeting will take."""
    return item_ref(meeting_stem(meeting_ref), len(items) + 1)


def meeting_label(meeting: Mapping[str, Any]) -> str:
    """How a meeting is named in a dropdown or a heading."""
    parts = [str(meeting.get("ref") or "").strip(), str(meeting.get("title") or "").strip()]
    name = " · ".join(p for p in parts if p)
    stamp = to_display(meeting.get("meeting_date"))
    return f"{name} ({stamp})" if name and stamp else (name or stamp or "Meeting")
