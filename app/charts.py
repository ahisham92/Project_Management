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
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return str(iso)


def _axis_label(iso: str, with_day: bool) -> str:
    try:
        parsed = datetime.strptime(str(iso)[:10], "%Y-%m-%d")
    except ValueError:
        return str(iso)
    return parsed.strftime("%d %b") if with_day else parsed.strftime("%b %Y")


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


def _chart(body: str, legend: str = "", view_w: int = 800, view_h: int = 300) -> Markup:
    return Markup(
        f'<div class="chart">{legend}'
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
