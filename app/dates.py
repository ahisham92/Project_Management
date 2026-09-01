"""Dates are shown and typed as dd/mm/yyyy throughout, and stored as ISO.

Browsers render a native date picker in whatever order the machine's locale
says, which is why 1 September showed as 09/01. Text fields under our own
control avoid that: what you see is what every user sees, on every machine.
Input is forgiving — dd/mm/yyyy, dd-mm-yyyy, dd.mm.yyyy and yyyy-mm-dd all work.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

DISPLAY = "dd/mm/yyyy"
_SEPARATORS = re.compile(r"[/.\-\s]+")


def to_display(value: Any) -> str:
    """ISO (or a date) -> dd/mm/yyyy. Blank stays blank."""
    if not value:
        return ""
    if isinstance(value, (date, datetime)):
        parsed = value if isinstance(value, date) and not isinstance(value, datetime) else value.date()
        return parsed.strftime("%d/%m/%Y")
    text = str(value).strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return text


def from_input(value: Any) -> str | None:
    """What the user typed -> ISO, or None when it is not a usable date."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    # Already ISO?
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass

    parts = [p for p in _SEPARATORS.split(text) if p]
    if len(parts) != 3:
        return None
    try:
        day, month, year = (int(p) for p in parts)
    except ValueError:
        return None
    if year < 100:                                  # a two-digit year means this century
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def from_input_or(value: Any, fallback: str) -> str:
    """Parse a date, falling back when it is missing or malformed."""
    return from_input(value) or fallback
