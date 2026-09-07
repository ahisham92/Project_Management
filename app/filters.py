"""Template formatting helpers, so the templates stay free of arithmetic."""

from __future__ import annotations

from typing import Any

from flask import Flask

from .dates import DISPLAY, to_display


def pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def signed_pct(value: Any, digits: int = 1) -> str:
    if value is None:
        return "—"
    number = float(value) * 100
    return f"{'+' if number > 0 else ''}{number:.{digits}f}%"


def hours(value: Any, digits: int = 0) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f} h"


def num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}"


def index(value: Any) -> str:
    """A performance index such as CPI or SPI; blank when there is no basis yet."""
    return "—" if value is None else f"{float(value):.2f}"


def short_date(value: Any) -> str:
    """Every date on screen reads dd/mm/yyyy, whatever the viewer's locale."""
    if not value:
        return "—"
    return to_display(value) or "—"


def date_input(value: Any) -> str:
    """The dd/mm/yyyy value for a text date field; blank rather than a dash."""
    return to_display(value)


def variance_state(value: Any) -> str:
    """Maps a progress variance onto a status word used for colour and label."""
    if value is None:
        return "neutral"
    number = float(value)
    if number >= -0.0001:
        return "good"
    if number >= -0.05:
        return "warning"
    return "critical"


def usage_state(value: Any) -> str:
    number = float(value or 0)
    if number > 1:
        return "critical"
    if number > 0.9:
        return "warning"
    return "good"


def office_name(value: Any) -> str:
    """An office, or the offices on one deliverable, as it reads on a screen."""
    from .offices import label, name_of

    if isinstance(value, (list, tuple)):
        return label(value)
    return name_of(value)


def bar_width(value: Any) -> str:
    """A CSS percentage clamped to the track."""
    return f"{min(1.0, max(0.0, float(value or 0))) * 100:.2f}%"


def register(app: Flask) -> None:
    from .backup import readable

    for func in (pct, signed_pct, hours, num, index, short_date, date_input,
                 variance_state, usage_state, bar_width, office_name, readable):
        app.jinja_env.filters[func.__name__] = func
        app.jinja_env.globals[func.__name__] = func
    app.jinja_env.globals["DATE_FORMAT"] = DISPLAY

    # The helper strip at the top of every tab reads its own entry out of the
    # same dictionary the How to use page renders, so the two cannot drift.
    from .guide import for_endpoint, terms_for

    app.jinja_env.globals["guide_for"] = for_endpoint
    app.jinja_env.globals["guide_terms"] = terms_for
