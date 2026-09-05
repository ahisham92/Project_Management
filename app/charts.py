"""Charts drawn as inline SVG on the server.

Everything is generated here so the pages need no charting library, no bundler
and no CDN: they work offline, print correctly, and there is nothing to install.
Hover behaviour is added by ``static/app.js``, which reads the data attributes
these functions emit.

Colours come from CSS custom properties defined in ``static/app.css``, so the
same markup re-steps itself for the dark theme.

The eight categorical series slots are a colourblind-safe set used in fixed
order; status colours are reserved and always ship with a label.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from .calc import days_between
from .dates import to_display

from markupsafe import Markup, escape

# Slot 1..8, light values. The stylesheet holds the matching dark steps.
SERIES_SLOTS = [
    ("Blue", "#2a78d6"),
    ("Orange", "#eb6834"),
    ("Aqua", "#1baf7a"),
    ("Yellow", "#eda100"),
    ("Magenta", "#e87ba4"),
    ("Green", "#008300"),
    ("Violet", "#4a3aa7"),
    ("Red", "#e34948"),
]

PLANNED = "var(--series-1)"
EARNED = "var(--series-2)"
GRID = "var(--grid)"
AXIS = "var(--axis)"
MUTED = "var(--muted)"
INK2 = "var(--ink-2)"
SURFACE = "var(--surface)"
CRITICAL = "var(--critical)"


def _fmt_pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def _fmt_hours(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f} h"


def _short_date(iso: str) -> str:
    return to_display(iso) or str(iso)


def _axis_label(iso: str, with_day: bool) -> str:
    """Axis ticks follow the same dd/mm reading order as the rest of the app."""
    try:
        parsed = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
    except ValueError:
        return str(iso)
    return parsed.strftime("%d/%m") if with_day else parsed.strftime("%m/%Y")


def _tip(title: str, rows: Sequence[Mapping[str, Any]]) -> str:
    """A hit target's tooltip payload, read back by app.js."""
    payload = {"title": title, "rows": [dict(r) for r in rows]}
    return escape(json.dumps(payload, ensure_ascii=False))


def _legend(items: Sequence[tuple[str, str]], mark: str = "line") -> str:
    """A legend is always present for two or more series."""
    parts = []
    for label, color in items:
        swatch = (
            f'<span class="legend-line" style="background:{color}"></span>'
            if mark == "line"
            else f'<span class="legend-dot" style="background:{color}"></span>'
        )
        parts.append(f'<span class="legend-item">{swatch}{escape(label)}</span>')
    return f'<div class="legend">{"".join(parts)}</div>'


def _empty(message: str) -> Markup:
    return Markup(f'<p class="chart-empty">{escape(message)}</p>')


def _chart(body: str, legend: str = "", view_w: int = 800, view_h: int = 300,
           natural: bool = False) -> Markup:
    """A chart, sized to its container.

    `natural` caps the width at the drawing's own, so a diagram of boxes is not
    blown up to fill the card — a handful of boxes stretched across a wide
    screen reads as a handful of enormous boxes.
    """
    style = f' style="max-width:{view_w}px"' if natural else ""
    return Markup(
        f'<div class="chart"{style}>{legend}'
        f'<svg viewBox="0 0 {view_w} {view_h}" role="img" preserveAspectRatio="xMidYMid meet">{body}</svg>'
        f'<div class="chart-tip" hidden></div></div>'
    )


# --- S-curve ---------------------------------------------------------------

def s_curve(points: Sequence[Mapping[str, Any]], data_date: str) -> Markup:
    """Planned versus earned cumulative progress over the life of the project."""
    if len(points) < 2:
        return _empty("Not enough schedule data to draw a curve yet.")

    w, h = 800, 300
    left, right, top, bottom = 56, 16, 16, 40
    plot_w, plot_h = w - left - right, h - top - bottom

    n = len(points)
    x_of = lambda i: left + plot_w * i / (n - 1)          # noqa: E731
    y_of = lambda v: top + plot_h * (1 - v)               # noqa: E731

    parts: list[str] = []

    # Gridlines and y ticks, recessive.
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        y = y_of(frac)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(
            f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{frac * 100:.0f}%</text>'
        )

    # X ticks: roughly six, always including the first and last sample.
    stride = max(1, (n - 1) // 5)
    # Month names repeat on a programme shorter than a year, so add the day.
    with_day = days_between(points[0]["date"], points[-1]["date"]) <= 400
    for i in range(0, n, stride):
        # Anchor the outermost labels inward so they stay inside the viewBox.
        anchor = "start" if i == 0 else ("end" if i >= n - stride else "middle")
        parts.append(
            f'<text x="{x_of(i):.1f}" y="{h - bottom + 18:.0f}" text-anchor="{anchor}" class="tick">'
            f"{escape(_axis_label(points[i]['date'], with_day))}</text>"
        )
    parts.append(
        f'<line x1="{left}" y1="{y_of(0):.1f}" x2="{w - right}" y2="{y_of(0):.1f}" stroke="{AXIS}" stroke-width="1"/>'
    )

    # The data date, marked so the earned curve's end point is obvious.
    cut = next((i for i, p in enumerate(points) if p["date"] == data_date), None)
    if cut is not None:
        x = x_of(cut)
        parts.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{y_of(0):.1f}" stroke="{AXIS}" '
            f'stroke-width="1" stroke-dasharray="4 3"/>'
        )
        parts.append(f'<text x="{x + 5:.1f}" y="{top + 10}" class="tick">Data date</text>')

    def polyline(key: str, color: str) -> str:
        coords = [
            f"{x_of(i):.1f},{y_of(max(0.0, min(1.0, p[key]))):.1f}"
            for i, p in enumerate(points)
            if p.get(key) is not None
        ]
        if len(coords) < 2:
            return ""
        return f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'

    parts.append(polyline("planned", PLANNED))
    parts.append(polyline("earned", EARNED))

    # The earned series can be a single reported point; show it as a marker so
    # it is not invisible.
    earned_pts = [(i, p) for i, p in enumerate(points) if p.get("earned") is not None]
    if len(earned_pts) == 1:
        i, p = earned_pts[0]
        parts.append(
            f'<circle cx="{x_of(i):.1f}" cy="{y_of(p["earned"]):.1f}" r="4" fill="{EARNED}" '
            f'stroke="{SURFACE}" stroke-width="2"/>'
        )
    elif earned_pts:
        i, p = earned_pts[-1]
        parts.append(
            f'<circle cx="{x_of(i):.1f}" cy="{y_of(p["earned"]):.1f}" r="4" fill="{EARNED}" '
            f'stroke="{SURFACE}" stroke-width="2"/>'
        )

    # Invisible hit bands drive the crosshair and tooltip.
    band = plot_w / (n - 1)
    for i, p in enumerate(points):
        rows = [{"label": "Planned", "color": PLANNED, "value": _fmt_pct(p["planned"])}]
        if p.get("earned") is not None:
            rows.append({"label": "Earned", "color": EARNED, "value": _fmt_pct(p["earned"])})
        parts.append(
            f'<rect class="hit" x="{x_of(i) - band / 2:.1f}" y="{top}" width="{band:.1f}" height="{plot_h}" '
            f'fill="transparent" data-x="{x_of(i):.1f}" data-tip="{_tip(_short_date(p["date"]), rows)}"/>'
        )

    parts.append(
        f'<line class="crosshair" x1="0" y1="{top}" x2="0" y2="{y_of(0):.1f}" stroke="{AXIS}" '
        f'stroke-width="1" visibility="hidden"/>'
    )

    return _chart("".join(parts), _legend([("Planned", PLANNED), ("Earned", EARNED)]), w, h)


# --- grouped bars: planned vs earned per trade ------------------------------

def trade_progress(trades: Sequence[Mapping[str, Any]]) -> Markup:
    """Each trade's planned and earned percentage of its own scope."""
    if not trades:
        return _empty("Add trades to see progress split by discipline.")

    w, h = 800, 280
    left, right, top, bottom = 62, 16, 16, 44
    plot_w, plot_h = w - left - right, h - top - bottom

    values = [t["planned_pct_of_trade"] for t in trades] + [t["earned_pct_of_trade"] for t in trades]
    top_value = max(values + [0.0]) or 1.0
    scale = top_value * 1.15

    parts: list[str] = []
    for step in range(5):
        frac = step / 4
        y = top + plot_h * (1 - frac)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        label = frac * scale
        digits = 2 if scale < 0.1 else 1
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{_fmt_pct(label, digits)}</text>')

    slot = plot_w / len(trades)
    bar_w = min(26.0, slot / 3.2)
    gap = 2  # a 2px surface gap keeps adjacent bars from touching

    for index, trade in enumerate(trades):
        centre = left + slot * (index + 0.5)
        for offset, (key, color, label) in enumerate(
            ((("planned_pct_of_trade"), PLANNED, "Planned"), ("earned_pct_of_trade", EARNED, "Earned"))
        ):
            value = max(0.0, trade[key])
            bar_h = plot_h * min(1.0, value / scale) if scale else 0
            x = centre - bar_w - gap / 2 + offset * (bar_w + gap)
            y = top + plot_h - bar_h
            rows = [
                {"label": "Planned", "color": PLANNED, "value": _fmt_pct(trade["planned_pct_of_trade"], 2)},
                {"label": "Earned", "color": EARNED, "value": _fmt_pct(trade["earned_pct_of_trade"], 2)},
            ]
            if bar_h > 0.5:
                parts.append(
                    f'<rect class="hit mark" x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
                    f'rx="4" fill="{color}" data-tip="{_tip(str(trade["name"]), rows)}"><title>'
                    f'{escape(trade["name"])} {label} {_fmt_pct(value, 2)}</title></rect>'
                )
            else:
                # Nothing to draw yet; keep a hit target so the trade still responds.
                parts.append(
                    f'<rect class="hit" x="{x:.1f}" y="{top}" width="{bar_w:.1f}" height="{plot_h:.1f}" '
                    f'fill="transparent" data-tip="{_tip(str(trade["name"]), rows)}"/>'
                )

        parts.append(
            f'<text x="{centre:.1f}" y="{h - bottom + 20:.0f}" text-anchor="middle" class="tick">'
            f"{escape(trade['name'])}</text>"
        )

    parts.append(
        f'<line x1="{left}" y1="{top + plot_h:.1f}" x2="{w - right}" y2="{top + plot_h:.1f}" '
        f'stroke="{AXIS}" stroke-width="1"/>'
    )
    return _chart("".join(parts), _legend([("Planned", PLANNED), ("Earned", EARNED)], mark="dot"), w, h)


# --- horizontal bars: share of scope ---------------------------------------

def trade_weight(trades: Sequence[Mapping[str, Any]]) -> Markup:
    """Share of the total project weight carried by each trade, directly labelled."""
    if not trades:
        return _empty("Add trades to see how the scope is shared.")

    row_h, pad_top = 34, 8
    w = 800
    h = pad_top * 2 + row_h * len(trades)
    label_w, value_w = 150, 60
    plot_w = w - label_w - value_w - 16
    top_value = max((t["scope_weight_pct"] for t in trades), default=0.0) or 1.0

    parts: list[str] = []
    for index, trade in enumerate(trades):
        y = pad_top + row_h * index
        centre = y + row_h / 2
        width = plot_w * (trade["scope_weight_pct"] / (top_value * 1.05))
        color = trade.get("color") or SERIES_SLOTS[index % 8][1]
        parts.append(
            f'<text x="{label_w - 10}" y="{centre + 4:.1f}" text-anchor="end" class="tick">'
            f"{escape(trade['name'])}</text>"
        )
        parts.append(
            f'<rect class="hit" x="{label_w}" y="{centre - 9:.1f}" width="{max(width, 2):.1f}" height="18" '
            f'rx="4" fill="{escape(color)}" '
            f'data-tip="{_tip(str(trade["name"]), [{"label": "Share of project weight", "color": color, "value": _fmt_pct(trade["scope_weight_pct"])}])}">'
            f'<title>{escape(trade["name"])} {_fmt_pct(trade["scope_weight_pct"])}</title></rect>'
        )
        parts.append(
            f'<text x="{label_w + max(width, 2) + 8:.1f}" y="{centre + 4:.1f}" class="tick-value">'
            f"{_fmt_pct(trade['scope_weight_pct'])}</text>"
        )
    # A single measure per row, directly labelled, so no legend is needed.
    return _chart("".join(parts), "", w, h)


# --- stacked horizontal bars: hours against budget -------------------------

def budget_hours(trades: Sequence[Mapping[str, Any]]) -> Markup:
    """Booked hours, remaining budget and any overrun for each trade.

    Trades are named on the axis, so colour here carries the booked / remaining
    / over distinction instead — encoding both at once would leave the legend
    unable to name a single colour for "booked".
    """
    if not trades:
        return _empty("Add trades with an hour budget to track spend.")

    row_h, pad_top, pad_bottom = 36, 8, 28
    w = 800
    h = pad_top + pad_bottom + row_h * len(trades)
    label_w = 150
    plot_w = w - label_w - 60

    scale = max([max(t["budget_hours"], t["spent_hours"]) for t in trades] + [1.0])

    parts: list[str] = []
    for index, trade in enumerate(trades):
        y = pad_top + row_h * index
        centre = y + row_h / 2
        booked = max(0.0, trade["spent_hours"])
        budget = max(0.0, trade["budget_hours"])
        remaining = max(0.0, budget - booked)
        over = max(0.0, booked - budget)

        parts.append(
            f'<text x="{label_w - 10}" y="{centre + 4:.1f}" text-anchor="end" class="tick">'
            f"{escape(trade['name'])}</text>"
        )

        rows = [
            {"label": "Budget", "color": MUTED, "value": _fmt_hours(budget)},
            {"label": "Booked", "color": PLANNED, "value": _fmt_hours(booked)},
        ]
        rows.append(
            {"label": "Over budget", "color": CRITICAL, "value": _fmt_hours(over)}
            if over > 0
            else {"label": "Remaining", "color": GRID, "value": _fmt_hours(remaining)}
        )
        tip = _tip(str(trade["name"]), rows)

        x = float(label_w)
        # A 2px surface gap keeps the segments from touching.
        for value, color, rounded in (
            (min(booked, budget), PLANNED, over == 0 and remaining == 0),
            (remaining, GRID, True),
            (over, CRITICAL, True),
        ):
            if value <= 0:
                continue
            seg_w = plot_w * value / scale
            radius = 4 if rounded else 0
            parts.append(
                f'<rect class="hit" x="{x:.1f}" y="{centre - 9:.1f}" width="{max(seg_w - 2, 1):.1f}" height="18" '
                f'rx="{radius}" fill="{color}" data-tip="{tip}"/>'
            )
            x += seg_w

        if booked == 0 and budget == 0:
            parts.append(
                f'<rect class="hit" x="{label_w}" y="{centre - 9:.1f}" width="{plot_w:.1f}" height="18" '
                f'fill="transparent" data-tip="{tip}"/>'
            )

    # Axis ticks along the bottom.
    axis_y = h - pad_bottom + 6
    parts.append(f'<line x1="{label_w}" y1="{axis_y}" x2="{label_w + plot_w}" y2="{axis_y}" stroke="{AXIS}" stroke-width="1"/>')
    for step in range(5):
        frac = step / 4
        x = label_w + plot_w * frac
        parts.append(
            f'<text x="{x:.1f}" y="{axis_y + 16}" text-anchor="middle" class="tick">{scale * frac:,.0f}</text>'
        )

    legend = _legend(
        [("Booked", PLANNED), ("Remaining budget", GRID), ("Over budget", CRITICAL)], mark="dot"
    )
    return _chart("".join(parts), legend, w, h)


# --- the plan --------------------------------------------------------------

GANTT_ROW = 26                      # the height one deliverable takes
GANTT_LEFT = 96                     # room for the WBS down the side
GANTT_HEAD = 46                     # the month band and the day ticks above it
REWORK = "var(--warning)"
PATH_END = "var(--series-1)"   # a line nothing waits on: the end of a route

# Each kind of link gets its own colour AND its own dash, so the four are told
# apart in greyscale, on a projector, and by anyone who reads colour
# differently. Red is left to the critical path and blue to a path's end.
KIND_COLOURS = {
    "FS": "var(--series-7)",     # violet
    "SS": "var(--series-3)",     # teal
    "FF": "var(--series-4)",     # amber
    "SF": "var(--series-5)",     # magenta
}
KIND_DASHES = {"FS": "", "SS": "6 3", "FF": "2 3", "SF": "10 3 2 3"}

# The same four patterns as a CSS background, for the legend swatch. Drawn in
# CSS rather than as a little SVG, which the chart's own "svg { width: 100% }"
# would blow up to fill the row.
KIND_SWATCH = {
    "FS": "{ink}",
    "SS": "repeating-linear-gradient(90deg,{ink} 0 6px,transparent 6px 9px)",
    "FF": "repeating-linear-gradient(90deg,{ink} 0 2px,transparent 2px 5px)",
    "SF": ("repeating-linear-gradient(90deg,{ink} 0 10px,transparent 10px 13px,"
           "{ink} 13px 15px,transparent 15px 18px)"),
}
SUBMITTED = "var(--good)"           # the green star that marks a submission


def _span(first: str, last: str) -> int:
    return max(1, days_between(first, last) or 1)


def _x_of(day: str, first: str, span: int, left: int, width: int) -> float:
    return left + (days_between(first, day) / span) * width


def _ticks(first: str, last: str, span: int) -> list[str]:
    """A tick every month for a long plan, every week for a short one."""
    from datetime import date, timedelta

    start = datetime.strptime(first[:10], "%Y-%m-%d").date()
    end = datetime.strptime(last[:10], "%Y-%m-%d").date()
    if span > 120:
        return [day for day in _month_starts(start, end) if day >= start.isoformat()]
    step = 7 if span > 28 else 1
    marks, day = [], start
    while day <= end:
        marks.append(day.isoformat())
        day += timedelta(days=step)
    return marks


def _month_starts(start, end) -> list[str]:
    from datetime import date

    days, day = [], date(start.year, start.month, 1)
    while day <= end:
        days.append(day.isoformat())
        day = date(day.year + (day.month == 12), (day.month % 12) + 1, 1)
    return days


def _months(first: str, last: str) -> list[tuple[str, str, str]]:
    """(first day, last day, label) for every month the plan touches.

    The band across the top says which month you are looking at, which a row of
    dates alone does not — the point of a programme is where you are in it.
    """
    from datetime import date, timedelta

    start = datetime.strptime(first[:10], "%Y-%m-%d").date()
    end = datetime.strptime(last[:10], "%Y-%m-%d").date()
    out = []
    for day in _month_starts(start, end):
        opens = date.fromisoformat(day)
        nxt = date(opens.year + (opens.month == 12), (opens.month % 12) + 1, 1)
        closes = nxt - timedelta(days=1)
        out.append((max(opens, start).isoformat(), min(closes, end).isoformat(),
                    opens.strftime("%b %Y")))
    return out


def gantt(tasks: Sequence[Mapping[str, Any]], first: str, last: str, data_date: str,
          steps: Sequence[Mapping[str, Any]] = ()) -> Markup:
    """The programme as bars, with the design milestones marked on each line.

    A bar runs from a deliverable's start to its submission, with a green star
    on the submission itself. A line on the design workflow also carries its
    IDC as a red circle and its Code A as a red star; a line tracked as a plain
    percentage — a meeting, a milestone, a transmittal — has neither, because
    neither happens to it. A resubmission draws its own bar underneath in amber:
    the rework a Code B or C caused, and how far it pushed the line out. The
    vertical line is today, and the band across the top says which month you
    are looking at.
    """
    if not tasks:
        return _empty("No deliverables to plan yet.")

    span = _span(first, last)
    width, left = 660, GANTT_LEFT
    top, foot = GANTT_HEAD, 30
    height = top + len(tasks) * GANTT_ROW + foot
    x_of = lambda day: _x_of(day, first, span, left, width)

    parts = [f'<rect x="{left}" y="{top}" width="{width}" height="{len(tasks) * GANTT_ROW}"'
             f' fill="{SURFACE}" rx="4"/>']

    # The month band, alternating so one month reads apart from the next.
    for index, (opens, closes, label) in enumerate(_months(first, last)):
        x1, x2 = x_of(opens), x_of(closes)
        room = max(0.0, x2 - x1)
        parts.append(
            f'<rect x="{x1:.1f}" y="6" width="{room:.1f}" height="18" rx="3"'
            f' fill="{SURFACE}" opacity="{0.9 if index % 2 == 0 else 0.45}"/>'
        )
        if room > 26:                          # only where the name will fit
            parts.append(
                f'<text x="{x1 + room / 2:.1f}" y="19" text-anchor="middle" font-size="9"'
                f' font-weight="500" fill="{INK2}">{escape(label)}</text>'
            )
        parts.append(f'<line x1="{x1:.1f}" y1="6" x2="{x1:.1f}" y2="{height - foot}"'
                     f' stroke="{GRID}" stroke-width="1"/>')

    # Day or week ticks under the band. On a long programme the band already
    # names every month, so the ticks are drawn without repeating it.
    named = span > 120
    for tick in _ticks(first, last, span):
        x = x_of(tick)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{height - foot}"'
                     f' stroke="{GRID}" stroke-width="1" opacity="0.6"/>')
        if not named:
            parts.append(f'<text x="{x:.1f}" y="{top - 6}" text-anchor="middle"'
                         f' font-size="8" fill="{MUTED}">{escape(_axis_label(tick, True))}</text>')

    for index, task in enumerate(tasks):
        y = top + index * GANTT_ROW
        start, finish = task.get("start_date"), task.get("submission_date")
        if not start or not finish:
            continue

        critical = bool(task.get("is_critical"))
        colour = CRITICAL if critical else PLANNED
        x1, x2 = x_of(start), x_of(finish)
        bar_y = y + 6
        parts.append(
            f'<text x="{left - 8}" y="{bar_y + 8}" text-anchor="end" font-size="9"'
            f' fill="{INK2}">{escape(str(task.get("wbs") or ""))}</text>'
        )
        parts.append(
            f'<rect class="mark" x="{x1:.1f}" y="{bar_y}" width="{max(2.0, x2 - x1):.1f}" height="10"'
            f' rx="3" fill="{colour}" opacity="{0.95 if critical else 0.75}"/>'
        )
        # How far the line has actually got, drawn inside its own bar.
        done = float(task.get("actual_pct") or 0)
        if done > 0:
            parts.append(
                f'<rect x="{x1:.1f}" y="{bar_y + 3}" width="{max(1.0, (x2 - x1) * done):.1f}"'
                f' height="4" rx="2" fill="var(--ink)" opacity="0.45"/>'
            )

        # The submission itself, on every line that has one.
        parts.append(_star(x2, bar_y + 5, 5.5, SUBMITTED))

        # The IDC and the Code A belong to the design workflow. A line tracked
        # as a plain percentage has neither.
        if task.get("uses_workflow"):
            plan = {step["key"]: step["date"] for step in (task.get("step_plan") or ())}
            if plan.get("idc"):
                cx = x_of(plan["idc"])
                parts.append(f'<circle cx="{cx:.1f}" cy="{bar_y + 5}" r="4" fill="{CRITICAL}"'
                             f' stroke="var(--plane)" stroke-width="1"/>')
            if task.get("approval_due_date"):
                parts.append(_star(x_of(task["approval_due_date"]), bar_y + 5, 6, CRITICAL))

        # Each resubmission: from the day the comments landed to the new date.
        for revision in task.get("revisions") or ():
            raised, again = revision.get("comments_date"), revision.get("submission_date")
            if not raised or not again:
                continue
            rx1, rx2 = x_of(raised), x_of(again)
            parts.append(
                f'<rect class="mark" x="{rx1:.1f}" y="{bar_y + 12}" width="{max(2.0, rx2 - rx1):.1f}"'
                f' height="5" rx="2" fill="{REWORK}"/>'
            )
            code = str(revision.get("cause_code") or "").upper()
            if code:
                parts.append(f'<text x="{rx1:.1f}" y="{bar_y + 11}" font-size="7"'
                             f' fill="{REWORK}">{escape(code)}</text>')

        rows = []
        if task.get("section_name"):
            rows.append({"label": "Section", "value": str(task["section_name"]), "color": MUTED})
        rows += [
            {"label": "Start", "value": _short_date(start), "color": colour},
            {"label": "Submission", "value": _short_date(finish), "color": SUBMITTED},
            {"label": "Duration", "value": f'{task.get("duration_days", 0)} days', "color": MUTED},
            {"label": "Float", "value": f'{task.get("total_float", 0)} days', "color": MUTED},
        ]
        if task.get("status_name"):
            rows.append({"label": "Status", "value": str(task["status_name"]),
                         "color": PLANNED})
        if task.get("actual_pct") is not None:
            rows.append({"label": "Progress", "value": _fmt_pct(float(task.get("actual_pct") or 0)),
                         "color": EARNED})
        if task.get("uses_workflow") and task.get("approval_due_date"):
            rows.append({"label": "Code A due", "value": _short_date(task["approval_due_date"]),
                         "color": CRITICAL})
        if task.get("revisions"):
            rows.append({"label": "Resubmissions", "value": str(len(task["revisions"])), "color": REWORK})
        if task.get("starts_late"):
            rows.append({"label": "Cannot start until", "value": _short_date(task.get("early_start")),
                         "color": REWORK})
        # The whole row is the hit target, the WBS label included, so hovering
        # anywhere on a line says what the line is.
        parts.append(
            f'<rect class="hit" x="0" y="{y}" width="{left + width}" height="{GANTT_ROW}"'
            f' fill="transparent" data-tip="{_tip(str(task.get("wbs") or "") + " " + str(task.get("name") or ""), rows)}"/>'
        )

    x = x_of(data_date)
    parts.append(f'<line x1="{x:.1f}" y1="{top - 2}" x2="{x:.1f}" y2="{height - foot}"'
                 f' stroke="{CRITICAL}" stroke-width="1.5" stroke-dasharray="4 3"/>')
    parts.append(f'<text x="{x:.1f}" y="{height - foot + 12}" text-anchor="middle" font-size="9"'
                 f' fill="{CRITICAL}">today</text>')

    legend = _gantt_legend()
    return _chart("".join(parts), legend, view_w=left + width + 20, view_h=height)


def _gantt_legend() -> str:
    """What each mark on a bar means. Shape as well as colour, since the two
    stars differ only in what they stand for."""
    items = [
        ('<span class="legend-line" style="background:var(--series-1)"></span>', "Planned bar"),
        ('<span class="legend-dot" style="background:var(--critical)"></span>', "IDC (workflow only)"),
        ('<span class="legend-star" style="color:var(--good)">★</span>', "Submission"),
        ('<span class="legend-star" style="color:var(--critical)">★</span>', "Code A due (workflow only)"),
        ('<span class="legend-line" style="background:var(--warning)"></span>', "Rework after a Code B or C"),
        ('<span class="legend-line" style="background:var(--critical);height:2px"></span>', "Today"),
    ]
    marks = "".join(f'<span class="legend-item">{mark}{escape(label)}</span>'
                    for mark, label in items)
    return f'<div class="legend">{marks}</div>'


def _star(cx: float, cy: float, size: float, colour: str) -> str:
    """A five-pointed star, for the Code A on a bar."""
    import math

    points = []
    for step in range(10):
        radius = size if step % 2 == 0 else size * 0.45
        angle = math.pi / 2 * 3 + step * math.pi / 5
        points.append(f"{cx + radius * math.cos(angle):.1f},{cy + radius * math.sin(angle):.1f}")
    return f'<polygon points="{" ".join(points)}" fill="{colour}" stroke="var(--plane)" stroke-width="0.5"/>'


def network(tasks: Sequence[Mapping[str, Any]], links: Sequence[Mapping[str, Any]],
            movable: bool = False) -> Markup:
    """Who depends on whom, as small boxes.

    Each box is a WBS number — the name is on hover, so hundreds of boxes stay
    readable. The automatic layout puts a box in the column after the last of
    its predecessors, which is the order the work actually runs in; a box that
    has been dragged keeps where it was put. The critical path is picked out.
    """
    if not tasks:
        return _empty("No deliverables to draw yet.")
    if not links:
        return _empty("No dependencies yet — link two deliverables to see the network.")

    from .schedule import kind_label, normalise_kind, paths
    from .schedule import order as topological

    by_id = {int(t["id"]): t for t in tasks}
    predecessors: dict[int, list[int]] = {}
    for link in links:
        predecessors.setdefault(int(link["successor_id"]), []).append(int(link["predecessor_id"]))

    # Only what is joined to something; an unlinked line says nothing here.
    joined = {int(l["predecessor_id"]) for l in links} | {int(l["successor_id"]) for l in links}
    joined &= set(by_id)
    if not joined:
        return _empty("No dependencies yet — link two deliverables to see the network.")

    column: dict[int, int] = {}
    for task_id in topological(list(joined), links):
        earlier = [column.get(p, 0) for p in predecessors.get(task_id, ()) if p in joined]
        column[task_id] = (max(earlier) + 1) if earlier else 0

    columns: dict[int, list[int]] = {}
    for task_id, depth in column.items():
        columns.setdefault(depth, []).append(task_id)
    for depth in columns:
        columns[depth].sort(key=lambda t: str(by_id[t].get("wbs") or ""))

    from .layout import BOX_H, BOX_W, point

    box_w, box_h = BOX_W, BOX_H
    place: dict[int, tuple[float, float]] = {}
    for depth, ids in columns.items():
        for row, task_id in enumerate(ids):
            place[task_id] = point(depth, row)

    # A box that has been dragged sits where it was put instead.
    for task_id in list(place):
        moved_x, moved_y = by_id[task_id].get("node_x"), by_id[task_id].get("node_y")
        if moved_x is not None and moved_y is not None:
            place[task_id] = (float(moved_x), float(moved_y))

    from .layout import PAD

    drawn_w = max(x for x, _ in place.values()) + box_w + PAD
    height = max(y for _, y in place.values()) + box_h + PAD
    width = max(drawn_w, 760)

    # One arrow head per link colour: a marker takes its own fill, not the
    # line's, so each kind needs its own.
    heads = "".join(
        f'<marker id="arrow-{key}" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="6"'
        f' markerHeight="6" orient="auto-start-reverse">'
        f'<path d="M0,0 L8,4 L0,8 z" fill="{colour}"/></marker>'
        for key, colour in KIND_COLOURS.items()
    )
    parts = [f"<defs>{heads}</defs>"]

    for link in links:
        first, second = int(link["predecessor_id"]), int(link["successor_id"])
        if first not in place or second not in place:
            continue

        critical = bool(by_id[first].get("is_critical") and by_id[second].get("is_critical"))
        kind = normalise_kind(link.get("kind"))
        lag = float(link.get("lag_days") or 0)
        curve = _edge_path(place[first], place[second], box_w, box_h, kind)

        title = "{} → {}, {}".format(by_id[first].get("wbs") or "",
                                     by_id[second].get("wbs") or "", kind_label(kind))
        if lag:
            title += f", {lag:+g} days"

        # The critical run keeps its red, as a wide soft trace under the line,
        # so the colour on top is free to say which kind of link it is.
        if critical:
            parts.append(f'<path d="{curve}" fill="none" stroke="{CRITICAL}"'
                         f' stroke-width="5" opacity="0.22" stroke-linecap="round"/>')

        dashes = KIND_DASHES.get(kind, "")
        parts.append(
            '<path class="net-edge" data-from="{first}" data-to="{second}" data-kind="{kind}"'
            ' d="{path}"'
            ' fill="none" stroke="{colour}" stroke-width="{weight}" opacity="{opacity}"'
            '{dashes} marker-end="url(#arrow-{kind})"><title>{title}</title></path>'.format(
                first=first, second=second, path=curve, kind=kind,
                colour=KIND_COLOURS.get(kind, AXIS),
                weight=2 if critical else 1.2,
                opacity=1 if critical else 0.75,
                dashes=f' stroke-dasharray="{dashes}"' if dashes else "",
                title=escape(title),
            )
        )

    routes = paths(joined, links)
    ends = set(routes["ends"])

    for task_id, (x, y) in place.items():
        task = by_id[task_id]
        critical = bool(task.get("is_critical"))
        ending = task_id in ends
        rows = [
            {"label": "Deliverable", "value": str(task.get("name") or ""), "color": INK2},
            {"label": "Start", "value": _short_date(task.get("start_date")), "color": PLANNED},
            {"label": "Submission", "value": _short_date(task.get("submission_date")), "color": PLANNED},
            {"label": "Float", "value": f'{task.get("total_float", 0)} days',
             "color": CRITICAL if critical else MUTED},
        ]
        if ending:
            rows.append({"label": "Ends a path", "value": "nothing waits on it", "color": PATH_END})

        # A line nothing waits on closes a route through the programme, and is
        # drawn blue whatever else it is. A critical one keeps the heavier
        # outline, so both still read on the same box.
        outline = PATH_END if ending else (CRITICAL if critical else AXIS)
        ink = PATH_END if ending else (CRITICAL if critical else INK2)
        parts.append(
            f'<g class="net-node{" movable" if movable else ""}" data-node="{task_id}"'
            f' data-x="{x:.0f}" data-y="{y:.0f}" transform="translate({x:.0f},{y:.0f})">'
            f'<rect class="mark hit" x="0" y="0" width="{box_w}" height="{box_h}" rx="5"'
            f' fill="{SURFACE}" stroke="{outline}"'
            f' stroke-width="{1.8 if critical or ending else 1}"'
            f' data-tip="{_tip(str(task.get("wbs") or ""), rows)}"/>'
            f'<text x="{box_w / 2}" y="{box_h / 2 + 3.5}" text-anchor="middle"'
            f' font-size="10" font-weight="{600 if critical or ending else 400}"'
            f' fill="{ink}" pointer-events="none">'
            f'{escape(str(task.get("wbs") or ""))}</text></g>'
        )

    legend = (_legend([("On the critical path", "var(--critical)"),
                       ("Has float", AXIS),
                       ("End of a path — nothing waits on it", PATH_END)], mark="dot")
              + _kind_legend())
    body = f'<g class="net" data-box-w="{box_w}" data-box-h="{box_h}">{"".join(parts)}</g>'
    return _chart(body, legend, view_w=int(width), view_h=int(height), natural=True)


def _kind_legend() -> str:
    """What each colour of line means. The dash is part of the answer, so the
    swatch is drawn rather than coloured in."""
    from .schedule import KINDS

    def swatch(key: str) -> str:
        ink = KIND_COLOURS.get(key, AXIS)
        pattern = KIND_SWATCH.get(key, "{ink}").format(ink=ink)
        return f'<span class="legend-line legend-dash" style="background:{pattern}"></span>'

    marks = "".join(
        f'<span class="legend-item">{swatch(key)}{escape(key)} · {escape(label)}</span>'
        for key, label in KINDS
    )
    return f'<div class="legend">{marks}</div>'


# The two kinds that hang on the predecessor's start rather than its finish,
# and so leave the left-hand edge of its box.
FROM_START = ("SS", "SF")


def _edge_path(start: tuple[float, float], end: tuple[float, float],
               box_w: float, box_h: float, kind: str = "FS") -> str:
    """The curve from one box to another.

    A link that waits on the other line's finish leaves the right-hand edge,
    where that work ends; one that waits on its start leaves the left, because
    that is the moment it refers to.
    """
    x1, y1 = start
    x2, y2 = end
    from_x = x1 if kind in FROM_START else x1 + box_w
    from_y = y1 + box_h / 2
    to_y = y2 + box_h / 2
    bend = max(24.0, abs(x2 - from_x) / 2)
    return (f"M{from_x:.0f},{from_y:.0f} C{from_x + bend:.0f},{from_y:.0f}"
            f" {x2 - bend:.0f},{to_y:.0f} {x2:.0f},{to_y:.0f}")
