"""MarineTwin's sensor charts, drawn the same way as every other chart here.

One chart per sensor: its readings over time, with the limits it is judged
against. A thickness-loss chart also runs on to the end of the design life,
showing the fitted loss = a·tᵇ curve against the allowance Triton designed to,
because the question there is not where the steel is but where it is going.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Sequence

from markupsafe import Markup

from .charts import AXIS, CRITICAL, GRID, MUTED, SURFACE, _chart, _empty, _legend, _short_date, _tip

READING = "var(--series-1)"
PROJECTION = "var(--series-2)"
ALERT = "var(--warning)"


def _day(text: str) -> date:
    return date.fromisoformat(str(text)[:10])


def _nice_step(span: float) -> float:
    """A round gridline spacing giving about five lines across ``span``."""
    raw = span / 5 if span > 0 else 1
    power = 10 ** math.floor(math.log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mult * power:
            return mult * power
    return 10 * power


def sensor_trend(sensor: dict[str, Any], readings: Sequence[Any], asset: Any, life: int) -> Markup:
    if not readings:
        return _empty("No readings yet.")
    unit = sensor["unit"]
    relative = sensor["kind"] in ("displacement", "tilt")
    base = readings[0]["value"] if relative else 0.0
    points = [(_day(r["at"]), r["value"] - base) for r in readings]
    first, last = points[0][0], points[-1][0]

    projection: list[tuple[date, float]] = []
    commissioned = _day(asset["commissioned"])
    if sensor["kind"] == "corrosion" and sensor.get("fit_a") is not None:
        a, b = sensor["fit_a"], sensor["fit_b"]
        end = commissioned + timedelta(days=round(365.25 * life))
        steps = 40
        start = first
        for i in range(steps + 1):
            d = start + (end - start) * i / steps
            t = max((d - commissioned).days / 365.25, 0.01)
            projection.append((d, a * t ** b))
        last = max(last, end)

    limits: list[tuple[str, float, str]] = []
    if sensor["kind"] == "corrosion" and sensor.get("allowance"):
        limits.append(("Design allowance", sensor["allowance"], CRITICAL))
    else:
        if sensor.get("alert") is not None:
            limits.append(("Alert", sensor["alert"], ALERT))
        if sensor.get("alarm") is not None:
            limits.append(("Alarm", sensor["alarm"], CRITICAL))

    values = [v for _, v in points] + [v for _, v in projection] + [v for _, v, _ in limits]
    if sensor["kind"] in ("rail_gauge", "rail_level"):
        values += [-v for _, v, _ in limits]                  # either side of the line
    lo, hi = min(values + [0.0]), max(values + [0.0])
    if sensor["kind"] in ("strain", "displacement", "tilt"):
        lo = min(lo, -max(abs(lo), 0))
    if hi - lo < 1e-9:
        hi = lo + 1
    pad = (hi - lo) * 0.08
    lo, hi = lo - (pad if lo < 0 else 0), hi + pad

    w, h, left, right, top, bottom = 800, 280, 58, 16, 14, 30
    plot_w, plot_h = w - left - right, h - top - bottom
    span = max((last - first).days, 1)

    def x_of(d: date) -> float:
        return left + plot_w * (d - first).days / span

    def y_of(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / (hi - lo))

    parts: list[str] = []
    step = _nice_step(hi - lo)
    tick = (lo // step) * step
    digits = 0 if step >= 1 else 2
    while tick <= hi + 1e-9:
        if tick >= lo - 1e-9:
            y = y_of(tick)
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
            parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{tick:,.{digits}f}</text>')
        tick += step
    years = range(first.year + (1 if first.month > 1 else 0), last.year + 1)
    every = max(1, len(years) // 8)
    for year in list(years)[::every]:
        x = x_of(date(year, 1, 1))
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h - bottom}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{x:.1f}" y="{h - bottom + 18}" text-anchor="middle" class="tick">{year}</text>')
    parts.append(f'<text x="{left}" y="{top - 2}" class="tick">{unit}</text>')

    for label, value, colour in limits:
        y = y_of(value)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{colour}" '
                     f'stroke-width="1.5" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{w - right - 4}" y="{y - 5:.1f}" text-anchor="end" class="tick-value">'
                     f'{label} {value:,.{0 if abs(value) >= 100 else 2}f}</text>')
        if sensor["kind"] in ("strain", "rail_gauge", "rail_level") and value > 0:
            parts.append(f'<line x1="{left}" y1="{y_of(-value):.1f}" x2="{w - right}" y2="{y_of(-value):.1f}" '
                         f'stroke="{colour}" stroke-width="1" stroke-dasharray="6 4" opacity="0.6"/>')

    if projection:
        path = " ".join(f"{'M' if i == 0 else 'L'}{x_of(d):.1f},{y_of(v):.1f}" for i, (d, v) in enumerate(projection))
        parts.append(f'<path d="{path}" fill="none" stroke="{PROJECTION}" stroke-width="2" stroke-dasharray="3 3"/>')
        today_x = x_of(points[-1][0])
        parts.append(f'<line x1="{today_x:.1f}" y1="{top}" x2="{today_x:.1f}" y2="{h - bottom}" stroke="{AXIS}" stroke-width="1"/>')
        parts.append(f'<text x="{today_x + 5:.1f}" y="{top + 10}" class="tick">Latest reading</text>')

    if sensor["kind"] == "inspection":
        # A grade holds until the next inspection: a step, not a slope.
        steps = [f"M{x_of(points[0][0]):.1f},{y_of(points[0][1]):.1f}"]
        for d, v in points[1:]:
            steps.append(f"H{x_of(d):.1f}V{y_of(v):.1f}")
        path = " ".join(steps)
    else:
        path = " ".join(f"{'M' if i == 0 else 'L'}{x_of(d):.1f},{y_of(v):.1f}" for i, (d, v) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="{READING}" stroke-width="1.6" stroke-linejoin="round"/>')
    d, v = points[-1]
    parts.append(f'<circle cx="{x_of(d):.1f}" cy="{y_of(v):.1f}" r="4" fill="{READING}" stroke="{SURFACE}" stroke-width="2"/>')

    # Hit bands, thinned so a long record does not draw thousands of them.
    thin = max(1, len(points) // 150)
    shown = points[::thin]
    band = max(plot_w * (shown[1][0] - shown[0][0]).days / span if len(shown) > 1 else plot_w, 2)
    for d, v in shown:
        rows = [{"label": sensor["kind_name"] + (" since installed" if relative else ""),
                 "color": READING, "value": f"{v:,.2f} {unit}"}]
        parts.append(f'<rect class="hit" x="{x_of(d) - band / 2:.1f}" y="{top}" width="{band:.1f}" height="{plot_h}" '
                     f'fill="transparent" data-x="{x_of(d):.1f}" data-tip="{_tip(_short_date(d.isoformat()), rows)}"/>')
    parts.append(f'<line class="crosshair" x1="0" y1="{top}" x2="0" y2="{h - bottom}" stroke="{MUTED}" '
                 f'stroke-width="1" visibility="hidden"/>')

    legend = [("Readings", READING)]
    if projection:
        legend.append(("Fitted loss = a·tᵇ, to end of design life", PROJECTION))
    legend += [(label, colour) for label, _, colour in limits]
    return _chart("".join(parts), _legend(legend), w, h)


# --- operations: the hourly forecast ------------------------------------------------

GUST = "var(--series-2)"
TIDE = "var(--series-3)"


def _hourly(weather: Sequence[dict[str, Any]], series: Sequence[tuple[str, str, str]],
            limits: Sequence[tuple[str, float, str]], unit: str, h: int = 240, now: bool = True,
            step_lines: bool = False) -> Markup:
    """Hourly lines, limits dashed; with ``now``, the past is shaded and the present marked."""
    if not weather:
        return _empty("No forecast.")
    values = [w[key] for w in weather for _, key, _ in series] + [v for _, v, _ in limits] + [0.0]
    lo, hi = min(values), max(values)
    hi += (hi - lo) * 0.08 or 1
    w, left, right, top, bottom = 800, 46, 16, 14, 30
    plot_w, plot_h = w - left - right, h - top - bottom
    count = len(weather) - 1 or 1

    def x_of(i: float) -> float:
        return left + plot_w * i / count

    def y_of(v: float) -> float:
        return top + plot_h * (1 - (v - lo) / (hi - lo))

    parts: list[str] = []
    now_i = max((i for i, row in enumerate(weather) if row["past"]), default=0)
    if now:
        parts.append(f'<rect x="{left}" y="{top}" width="{x_of(now_i) - left:.1f}" height="{plot_h}" fill="{GRID}" opacity="0.45"/>')
    step = _nice_step(hi - lo)
    tick = (lo // step) * step
    digits = 0 if step >= 1 else 1
    while tick <= hi + 1e-9:
        if tick >= lo - 1e-9:
            y = y_of(tick)
            parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
            parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{tick:,.{digits}f}</text>')
        tick += step
    midnights = [i for i, row in enumerate(weather) if row["at"].hour == 0]
    every = max(1, math.ceil(len(midnights) / 8))
    for n, i in enumerate(midnights):
        x = x_of(i)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h - bottom}" stroke="{GRID}" stroke-width="1"/>')
        if n % every == 0:
            label = f'{weather[i]["at"]:%a %d/%m}' if every == 1 else f'{weather[i]["at"]:%d/%m}'
            parts.append(f'<text x="{x + 4:.1f}" y="{h - bottom + 18}" class="tick">{label}</text>')
    if now:
        x_now = x_of(now_i)
        parts.append(f'<line x1="{x_now:.1f}" y1="{top}" x2="{x_now:.1f}" y2="{h - bottom}" stroke="{AXIS}" stroke-width="1.5"/>')
        parts.append(f'<text x="{x_now + 5:.1f}" y="{top + 10}" class="tick">Now</text>')
    parts.append(f'<text x="{left}" y="{top - 2}" class="tick">{unit}</text>')

    for label, value, colour in limits:
        y = y_of(value)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{colour}" '
                     f'stroke-width="1.5" stroke-dasharray="6 4"/>')
        parts.append(f'<text x="{w - right - 4}" y="{y - 5:.1f}" text-anchor="end" class="tick-value">{label}</text>')

    for _, key, colour in series:
        if step_lines:
            path = f"M{x_of(0):.1f},{y_of(weather[0][key]):.1f} " + " ".join(
                f"H{x_of(i):.1f}V{y_of(row[key]):.1f}" for i, row in enumerate(weather) if i)
        else:
            path = " ".join(f"{'M' if i == 0 else 'L'}{x_of(i):.1f},{y_of(row[key]):.1f}" for i, row in enumerate(weather))
        parts.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="1.8" stroke-linejoin="round"/>')

    band = plot_w / count
    for i, row in enumerate(weather):
        digits = 1 if unit == "m/s" else 0 if step_lines or unit in ("trucks", "%", "trucks / %") else 2
        rows = [{"label": label, "color": colour, "value": f"{row[key]:,.{digits}f} {unit}"}
                for label, key, colour in series]
        title = f"{row['at']:%a %d/%m %H:00}" + ("" if row["past"] or not now else " (forecast)")
        parts.append(f'<rect class="hit" x="{x_of(i) - band / 2:.1f}" y="{top}" width="{band:.1f}" height="{plot_h}" '
                     f'fill="transparent" data-x="{x_of(i):.1f}" data-tip="{_tip(title, rows)}"/>')
    parts.append(f'<line class="crosshair" x1="0" y1="{top}" x2="0" y2="{h - bottom}" stroke="{MUTED}" '
                 f'stroke-width="1" visibility="hidden"/>')
    legend = [(label, colour) for label, _, colour in series] + [(label, colour) for label, _, colour in limits]
    return _chart("".join(parts), _legend(legend), w, h)


def wind_forecast(weather: Sequence[dict[str, Any]], limits: dict[str, float]) -> Markup:
    return _hourly(weather, [("Mean wind", "wind", READING), ("Gust", "gust", GUST)], [
        (f"Berthing stops {limits['berthing_wind']:.0f}", limits["berthing_wind"], ALERT),
        (f"Cranes stop {limits['crane_stop_gust']:.0f}", limits["crane_stop_gust"], ALERT),
        (f"Cranes to storm pins {limits['crane_stow_gust']:.0f}", limits["crane_stow_gust"], CRITICAL),
    ], "m/s")


def sea_forecast(weather: Sequence[dict[str, Any]], limits: dict[str, float]) -> Markup:
    return _hourly(weather, [("Significant wave height", "hs", READING), ("Tide above chart datum", "tide", TIDE)], [
        (f"Berthing stops {limits['berthing_hs']:.1f}", limits["berthing_hs"], ALERT),
    ], "m", h=200)


def sim_ships(timeline: Sequence[dict[str, Any]], berths: int) -> Markup:
    return _hourly(timeline, [("Ships alongside", "alongside", READING), ("Ships waiting for a berth", "waiting", GUST)],
                   [(f"{berths} berth{'s' if berths != 1 else ''}", berths, ALERT)], "ships", h=200, now=False, step_lines=True)


def sim_gate(timeline: Sequence[dict[str, Any]]) -> Markup:
    return _hourly(timeline, [("Road trucks queuing at the gate", "gate_queue", GUST)], [], "trucks", h=200, now=False)


def carbon_months(months: Sequence[dict[str, Any]]) -> Markup:
    """Monthly emissions, scope 1 stacked on scope 2, with the carbon per move as a line."""
    if not months:
        return _empty("No energy data.")
    w, h, left, right, top, bottom = 800, 260, 52, 52, 14, 30
    plot_w, plot_h = w - left - right, h - top - bottom
    hi = max(m["scope1"] + m["scope2"] for m in months) * 1.1
    ihi = max(m["intensity"] for m in months) * 1.25
    slot = plot_w / len(months)
    parts = []
    step = _nice_step(hi)
    tick = 0.0
    while tick <= hi:
        y = top + plot_h * (1 - tick / hi)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{tick:,.0f}</text>')
        tick += step
    parts.append(f'<text x="{left}" y="{top - 2}" class="tick">t CO₂e</text>')
    parts.append(f'<text x="{w - right + 4}" y="{top - 2}" class="tick">kg/move</text>')
    points = []
    for i, m in enumerate(months):
        x = left + slot * i + slot * 0.18
        bw = slot * 0.64
        y2 = top + plot_h * (1 - m["scope2"] / hi)
        y1 = top + plot_h * (1 - (m["scope1"] + m["scope2"]) / hi)
        parts.append(f'<rect x="{x:.1f}" y="{y2:.1f}" width="{bw:.1f}" height="{top + plot_h - y2:.1f}" fill="{READING}"/>')
        parts.append(f'<rect x="{x:.1f}" y="{y1:.1f}" width="{bw:.1f}" height="{y2 - y1:.1f}" fill="{GUST}"/>')
        parts.append(f'<text x="{x + bw / 2:.1f}" y="{h - bottom + 18}" text-anchor="middle" class="tick">{m["month"]:%b}</text>')
        points.append((x + bw / 2, top + plot_h * (1 - m["intensity"] / ihi)))
        rows = [{"label": "Scope 1, diesel", "color": GUST, "value": f"{m['scope1']:,.0f} t"},
                {"label": "Scope 2, electricity", "color": READING, "value": f"{m['scope2']:,.0f} t"},
                {"label": "Per container move", "color": TIDE, "value": f"{m['intensity']:.2f} kg"}]
        parts.append(f'<rect class="hit" x="{left + slot * i:.1f}" y="{top}" width="{slot:.1f}" height="{plot_h}" fill="transparent" '
                     f'data-x="{x + bw / 2:.1f}" data-tip="{_tip(m["month"].strftime("%B %Y"), rows)}"/>')
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(points))
    parts.append(f'<path d="{path}" fill="none" stroke="{TIDE}" stroke-width="2"/>')
    for x, y in points:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{TIDE}"/>')
    for frac in (0.25, 0.5, 0.75):
        v = ihi * frac
        parts.append(f'<text x="{w - right + 4}" y="{top + plot_h * (1 - frac) + 4:.1f}" class="tick">{v:.1f}</text>')
    parts.append(f'<line class="crosshair" x1="0" y1="{top}" x2="0" y2="{h - bottom}" stroke="{MUTED}" stroke-width="1" visibility="hidden"/>')
    legend = _legend([("Scope 2, electricity", READING), ("Scope 1, diesel", GUST), ("kg CO₂e per container", TIDE)])
    return _chart("".join(parts), legend, w, h)


def env_chart(timeline: Sequence[dict[str, Any]], series: Sequence[tuple[str, str]], measure: str,
              unit: str, limits: Sequence[tuple[str, float]]) -> Markup:
    """One measure at several stations over the last day."""
    colours = [READING, GUST, TIDE, "var(--series-4)"]
    return _hourly(timeline, [(label, key, colours[i % 4]) for i, (label, key) in enumerate(series)],
                   [(label, value, ALERT if i == 0 else CRITICAL) for i, (label, value) in enumerate(limits)],
                   unit, h=200, now=False)


def life_costs(nothing: Sequence[dict[str, Any]], fixing: Sequence[dict[str, Any]], unit: str) -> Markup:
    """What looking after the berth cost, year by year, both ways: lost moves plus repairs turned
    into moves, added up. Doing nothing is free until the parts fail; then it is not."""
    if not nothing or not fixing:
        return _empty("Nothing to show.")
    w, h, left, right, top, bottom = 800, 280, 70, 16, 14, 30
    plot_w, plot_h = w - left - right, h - top - bottom
    years = max(len(nothing), len(fixing))
    hi = max([r["cost"] for r in nothing] + [r["cost"] for r in fixing] + [1.0]) * 1.08

    def x_of(year: float) -> float:
        return left + plot_w * year / years

    def y_of(v: float) -> float:
        return top + plot_h * (1 - v / hi)

    parts: list[str] = []
    step = _nice_step(hi)
    tick = 0.0
    while tick <= hi + 1e-9:
        y = y_of(tick)
        label = f"{tick / 1e6:,.1f}M" if hi >= 2e6 else f"{tick / 1e3:,.0f}k" if hi >= 2e3 else f"{tick:,.0f}"
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="tick">{label}</text>')
        tick += step
    for year in range(0, years + 1, 5 if years <= 60 else 10):
        x = x_of(year)
        parts.append(f'<text x="{x:.1f}" y="{h - bottom + 18}" text-anchor="middle" class="tick">year {year}</text>')
    parts.append(f'<text x="{left}" y="{top - 2}" class="tick">{unit} lost or spent, to date</text>')
    series = [("Do nothing", nothing, CRITICAL), ("Fix as you go", fixing, READING)]
    for _, rows, colour in series:
        path = f"M{x_of(0):.1f},{y_of(0):.1f} " + " ".join(f"L{x_of(r['year']):.1f},{y_of(r['cost']):.1f}" for r in rows)
        parts.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2" stroke-linejoin="round"/>')
    out = next((r["year"] for r in nothing if r["factor"] == 0), None)
    if out:
        x = x_of(out - 1)
        parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h - bottom}" stroke="{CRITICAL}" stroke-dasharray="4 4"/>')
        parts.append(f'<text x="{x - 6:.1f}" y="{top + 12}" text-anchor="end" class="tick-value">berth out of service</text>')
    band = plot_w / years
    for i in range(years):
        a = nothing[i] if i < len(nothing) else nothing[-1]
        b = fixing[i] if i < len(fixing) else fixing[-1]
        rows = [{"label": label, "color": colour, "value": f"{r['cost']:,.0f} {unit}"}
                for (label, _, colour), r in zip(series, (a, b))]
        parts.append(f'<rect class="hit" x="{x_of(i + 1) - band / 2:.1f}" y="{top}" width="{band:.1f}" height="{plot_h}" '
                     f'fill="transparent" data-x="{x_of(i + 1):.1f}" data-tip="{_tip(f"Year {i + 1}", rows)}"/>')
    parts.append(f'<line class="crosshair" x1="0" y1="{top}" x2="0" y2="{h - bottom}" stroke="{MUTED}" '
                 f'stroke-width="1" visibility="hidden"/>')
    return _chart("".join(parts), _legend([(label, colour) for label, _, colour in series]), w, h)
