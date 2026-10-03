"""MarineTwin: the monitored life of a marine structure after it is handed over.

An **asset** is one structure — a quay wall, a jetty, a dolphin, a pontoon. It
is made of **elements** (piles, combi wall panels, beams, the deck), each of
which may carry **sensors** — strain gauges, ultrasonic thickness points for
corrosion, displacement and tilt — whose **readings** arrive over time.

What it is judged against comes from the design, and the design came from
Triton (see ``marine_triton``): the utilisation each element was designed to,
and the corrosion it was allowed to lose over its design life. So the twin's
three questions are the client's three questions:

* **How is it now?** Each sensor's latest reading against its limits.
* **Where is it heading?** Corrosion is fitted as loss = a·tᵇ, the usual shape
  of marine steel loss, and projected to the end of the design life: the year
  the allowance is used up, and roughly what that does to Triton's utilisation.
* **What should be done?** A recommendation for each element that needs one.

For the prototype the sensors are **simulated** — deterministic per sensor, so
the same asset tells the same story every time it is drawn — and real readings
can be imported from a CSV whenever a logger exists.
"""

from __future__ import annotations

import csv
import io
import math
import random
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from . import marine_triton

# --- what things are ---------------------------------------------------------------

ASSET_KINDS = [
    ("quay_wall", "Quay wall"),
    ("jetty", "Jetty / pier"),
    ("dolphin", "Dolphin"),
    ("pontoon", "Pontoon"),
    ("breakwater", "Breakwater"),
    ("other", "Other"),
]
ELEMENT_KINDS = [
    ("pile", "Pile"),
    ("combi_wall", "Combi wall"),
    ("sheet_pile", "Sheet pile wall"),
    ("beam", "Beam"),
    ("slab", "Deck slab"),
    ("fender", "Fender"),
    ("bollard", "Bollard"),
    ("other", "Other"),
]
ZONES = [
    ("atmospheric", "Atmospheric"),
    ("splash", "Splash"),
    ("tidal", "Tidal"),
    ("immersed", "Permanently immersed"),
    ("buried", "Buried"),
]
MATERIALS = [("steel", "Steel"), ("concrete", "Reinforced concrete")]

# kind: (name, unit, default alert, default alarm). Corrosion is judged against
# the design allowance instead of fixed limits, so it carries none.
# Strain: S355, εy = 355 / 210 000 ≈ 1690 µε; alert at half of it, alarm at three quarters.
SENSOR_KINDS: dict[str, tuple[str, str, float | None, float | None]] = {
    "strain": ("Strain", "µε", 850.0, 1250.0),
    "corrosion": ("Thickness loss", "mm", None, None),
    "displacement": ("Displacement", "mm", 25.0, 50.0),
    "tilt": ("Tilt", "°", 0.5, 1.0),
}

# A sensor that has said nothing for this long is reported as silent.
SILENT_AFTER_DAYS = 45
# The sampling a simulated sensor keeps: a strain gauge logs, a thickness survey is periodic.
SIM_STEP_DAYS = {"strain": 7, "corrosion": 30, "displacement": 7, "tilt": 7}
# How far back a simulated sensor's history goes, however old the asset.
SIM_HISTORY_YEARS = 6

STATES = ("good", "warning", "critical")
STATE_RANK = {"neutral": -1, "good": 0, "warning": 1, "critical": 2}


def labels(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return dict(pairs)


# --- storage -----------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS marine_assets (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  name            TEXT NOT NULL,
  kind            TEXT NOT NULL DEFAULT 'quay_wall',
  location        TEXT NOT NULL DEFAULT '',
  client          TEXT NOT NULL DEFAULT '',
  commissioned    TEXT NOT NULL,                    -- YYYY-MM-DD, when its design life started
  design_life     INTEGER NOT NULL DEFAULT 50,      -- years
  corrosion_code  TEXT NOT NULL DEFAULT 'bs6349',   -- 'bs6349' | 'en1993_5', when not linked to Triton
  triton_project  TEXT NOT NULL DEFAULT '',         -- Triton project id, blank when not linked
  triton_section  TEXT NOT NULL DEFAULT '',
  model_file      TEXT NOT NULL DEFAULT '',         -- stored name of the uploaded IFC / glTF model
  model_name      TEXT NOT NULL DEFAULT '',         -- the name it was uploaded as
  created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS marine_elements (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  kind            TEXT NOT NULL DEFAULT 'pile',
  material        TEXT NOT NULL DEFAULT 'steel',
  zone            TEXT NOT NULL DEFAULT 'splash',
  wall_mm         REAL,                             -- steel wall thickness, for the section-loss estimate
  design_ur       REAL,                             -- typed in when the asset is not linked to Triton
  triton_element  TEXT NOT NULL DEFAULT '',         -- its name in Triton, when that differs
  model_ref       TEXT NOT NULL DEFAULT '',         -- its GlobalId, Tag or Name in the Revit model
  x               REAL NOT NULL DEFAULT 0,          -- where the schematic view draws it, metres
  y               REAL NOT NULL DEFAULT 0,
  z               REAL NOT NULL DEFAULT 0,
  UNIQUE (asset_id, name)
);

CREATE TABLE IF NOT EXISTS marine_sensors (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  element_id      INTEGER NOT NULL REFERENCES marine_elements(id) ON DELETE CASCADE,
  kind            TEXT NOT NULL,
  label           TEXT NOT NULL,
  alert           REAL,
  alarm           REAL,
  simulated       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS marine_readings (
  sensor_id       INTEGER NOT NULL REFERENCES marine_sensors(id) ON DELETE CASCADE,
  at              TEXT NOT NULL,                    -- YYYY-MM-DD or YYYY-MM-DDTHH:MM
  value           REAL NOT NULL,
  PRIMARY KEY (sensor_id, at)
);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


# --- dates -------------------------------------------------------------------------

def _day(text: str) -> date:
    return datetime.fromisoformat(str(text)[:10]).date()


def years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


# --- the simulator -----------------------------------------------------------------

def _rng(sensor_id: int, kind: str) -> random.Random:
    return random.Random(f"marinetwin:{sensor_id}:{kind}")


def simulate(sensor: Any, element: Any, asset: Any, allowance: float | None,
             until: date | None = None) -> list[tuple[str, float]]:
    """The readings a simulated sensor would have logged up to ``until`` (today).

    Deterministic: one sensor always tells the same story, and running it again
    later only adds the weeks since. Shapes, not data — but the shapes engineers
    expect: corrosion that slows as rust builds up (≈ t^0.85), strain riding a
    seasonal thermal cycle with the odd berthing spike, creep that settles.
    """
    until = until or date.today()
    commissioned = _day(asset["commissioned"])
    start = max(commissioned, until - timedelta(days=round(365.25 * SIM_HISTORY_YEARS)))
    kind = sensor["kind"]
    step = SIM_STEP_DAYS.get(kind, 7)
    rng = _rng(int(sensor["id"]), kind)
    life = float(asset["design_life"] or 50)

    if kind == "corrosion":
        # Lose between 55 % and 120 % of the allowance by the end of the design life.
        target = (allowance or 3.0) * rng.uniform(0.55, 1.2)
        b = rng.uniform(0.75, 0.95)
        a = target / life ** b
    elif kind == "strain":
        alarm = float(sensor["alarm"] or SENSOR_KINDS["strain"][3])
        base = alarm * rng.uniform(0.2, 0.5)
        seasonal = rng.uniform(40, 120)
        spikes = rng.uniform(0.01, 0.05)
    elif kind == "displacement":
        creep = rng.uniform(3, 14)
    elif kind == "tilt":
        drift = rng.uniform(0.004, 0.03)

    out: list[tuple[str, float]] = []
    day = start
    last_loss = 0.0
    while day <= until:
        t = max(years_between(commissioned, day), 1 / 365.25)
        season = math.cos(2 * math.pi * (day.timetuple().tm_yday - 200) / 365.25)
        if kind == "corrosion":
            loss = a * t ** b + rng.gauss(0, 0.04)
            last_loss = max(last_loss - 0.05, loss, 0.0)   # a survey can read a little low, not negative
            value = round(last_loss, 2)
        elif kind == "strain":
            value = base + seasonal * season + rng.gauss(0, 15)
            if rng.random() < spikes:
                value += rng.uniform(100, 400)              # a hard berthing
            value = round(value, 1)
        elif kind == "displacement":
            value = round(creep * math.log1p(t) + 1.5 * season + rng.gauss(0, 0.4), 2)
        elif kind == "tilt":
            value = round(drift * t + 0.02 * season + rng.gauss(0, 0.01), 3)
        else:
            value = 0.0
        out.append((day.isoformat(), value))
        day += timedelta(days=step)
    return out


def refresh_simulated(conn: sqlite3.Connection, asset_id: int, until: date | None = None) -> int:
    """Bring every simulated sensor on an asset up to today. Returns readings written."""
    asset = conn.execute("SELECT * FROM marine_assets WHERE id = ?", (asset_id,)).fetchone()
    if asset is None:
        return 0
    allowances = marine_triton.durability(asset)["allowances"]
    written = 0
    rows = conn.execute(
        "SELECT s.*, e.id AS e_id FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
        " WHERE e.asset_id = ? AND s.simulated = 1", (asset_id,)).fetchall()
    for sensor in rows:
        element = conn.execute("SELECT * FROM marine_elements WHERE id = ?", (sensor["e_id"],)).fetchone()
        allowance = marine_triton.allowance_for(element, allowances)
        series = simulate(sensor, element, asset, allowance, until)
        conn.execute("DELETE FROM marine_readings WHERE sensor_id = ?", (sensor["id"],))
        conn.executemany("INSERT INTO marine_readings (sensor_id, at, value) VALUES (?, ?, ?)",
                         [(sensor["id"], at, value) for at, value in series])
        written += len(series)
    return written


# --- importing real readings -----------------------------------------------------------

def import_csv(conn: sqlite3.Connection, asset_id: int, text: str) -> dict[str, Any]:
    """Readings from a logger export: columns ``sensor``, ``at`` and ``value``.

    ``sensor`` is the sensor's label on this asset (or its number). A sensor
    that receives real readings stops being simulated, so the two never mix.
    """
    sensors = {str(r["label"]).strip().lower(): r["id"] for r in conn.execute(
        "SELECT s.id, s.label FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
        " WHERE e.asset_id = ?", (asset_id,))}
    ids = set(sensors.values())
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    fields = {f.strip().lower(): f for f in (reader.fieldnames or [])}
    missing = [f for f in ("sensor", "at", "value") if f not in fields]
    if missing:
        return {"written": 0, "problems": [f"The file needs the columns sensor, at and value "
                                           f"(missing: {', '.join(missing)})."]}
    written, problems, touched = 0, [], set()
    for number, row in enumerate(reader, start=2):
        key = (row.get(fields["sensor"]) or "").strip()
        sensor_id = sensors.get(key.lower())
        if sensor_id is None and key.isdigit() and int(key) in ids:
            sensor_id = int(key)
        if sensor_id is None:
            problems.append(f"Row {number}: no sensor called “{key}” on this asset.")
            continue
        at = (row.get(fields["at"]) or "").strip().replace(" ", "T")[:16]
        try:
            datetime.fromisoformat(at)
            value = float((row.get(fields["value"]) or "").strip())
        except ValueError:
            problems.append(f"Row {number}: the date or the value could not be read.")
            continue
        if sensor_id not in touched:
            # The first real reading for a sensor clears its simulated history.
            if conn.execute("SELECT simulated FROM marine_sensors WHERE id = ?", (sensor_id,)).fetchone()[0]:
                conn.execute("DELETE FROM marine_readings WHERE sensor_id = ?", (sensor_id,))
                conn.execute("UPDATE marine_sensors SET simulated = 0 WHERE id = ?", (sensor_id,))
            touched.add(sensor_id)
        conn.execute("INSERT OR REPLACE INTO marine_readings (sensor_id, at, value) VALUES (?, ?, ?)",
                     (sensor_id, at, value))
        written += 1
    return {"written": written, "problems": problems[:20], "sensors": len(touched)}


# --- the assessment ----------------------------------------------------------------

def score(ratio: float, fine: float = 0.6, gone: float = 1.3) -> int:
    """0–100: 100 while the ratio is comfortably low, 0 once it is well past the limit."""
    if ratio <= fine:
        return 100
    return max(0, min(100, round(100 * (gone - ratio) / (gone - fine))))


def fit_corrosion(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    """(a, b) for loss = a·tᵇ through (years, mm) points, b kept between 0.4 and 1.2.

    Marine corrosion slows as the rust layer builds (b < 1) and an unprotected
    splash zone can run close to linear; anything outside that band is noise in
    a short record, so it is clamped and a refitted.
    """
    usable = [(t, v) for t, v in points if t > 0.05 and v > 0]
    if not usable:
        return None
    if len(usable) < 3:
        t, v = usable[-1]
        return v / t, 1.0
    xs = [math.log(t) for t, _ in usable]
    ys = [math.log(v) for _, v in usable]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx > 0 else 1.0
    b = min(1.2, max(0.4, b))
    a = math.exp(sum(y - b * x for x, y in zip(xs, ys)) / len(xs))
    return a, b


def _state(value: float, alert: float | None, alarm: float | None) -> str:
    if alarm is not None and value >= alarm:
        return "critical"
    if alert is not None and value >= alert:
        return "warning"
    return "good"


def assess_sensor(sensor: Any, readings: list[Any], element: Any, asset: Any,
                  allowance: float | None, life: int, today: date) -> dict[str, Any]:
    kind = sensor["kind"]
    name, unit, _, _ = SENSOR_KINDS.get(kind, (kind, "", None, None))
    out: dict[str, Any] = {"id": sensor["id"], "label": sensor["label"], "kind": kind, "kind_name": name,
                           "unit": unit, "simulated": bool(sensor["simulated"]), "count": len(readings),
                           "state": "neutral", "score": None, "latest": None, "latest_at": None,
                           "headline": "No readings yet", "silent": False}
    if not readings:
        return out
    latest = readings[-1]
    out["latest"], out["latest_at"] = latest["value"], latest["at"]
    if (today - _day(latest["at"])).days > SILENT_AFTER_DAYS:
        out["silent"] = True

    if kind == "corrosion":
        commissioned = _day(asset["commissioned"])
        points = [(years_between(commissioned, _day(r["at"])), r["value"]) for r in readings]
        fit = fit_corrosion(points)
        out["allowance"] = allowance
        if fit is None or not allowance:
            out["state"], out["score"] = "good", 100
            out["headline"] = f"{latest['value']:.2f} mm lost" + ("" if allowance else " (no allowance to judge it by)")
            return out
        a, b = fit
        at_life = a * life ** b
        exhausted = (allowance / a) ** (1 / b) if a > 0 else math.inf
        ratio = at_life / allowance
        out.update(
            fit_a=a, fit_b=b, projected_at_life=round(at_life, 2), ratio=round(ratio, 2),
            used=round(latest["value"] / allowance, 2),
            exhausted_year=(commissioned.year + exhausted) if math.isfinite(exhausted) else None,
            state="critical" if ratio >= 1 else "warning" if ratio >= 0.85 else "good",
            score=score(ratio, 0.7, 1.3),
        )
        if out["exhausted_year"] is not None and ratio >= 0.85:
            when = f"used up around {int(out['exhausted_year'])}"
        else:
            when = f"{round(100 * ratio)}% of the allowance by the end of the design life"
        out["headline"] = f"{latest['value']:.2f} of {allowance:.2f} mm lost; {when}"
        return out

    alert = sensor["alert"] if sensor["alert"] is not None else SENSOR_KINDS.get(kind, (0, 0, None, None))[2]
    alarm = sensor["alarm"] if sensor["alarm"] is not None else SENSOR_KINDS.get(kind, (0, 0, None, None))[3]
    value = latest["value"]
    if kind in ("displacement", "tilt"):
        value = value - readings[0]["value"]                  # since it was installed
    magnitude = abs(value)
    peak = max(abs(r["value"] - (readings[0]["value"] if kind in ("displacement", "tilt") else 0))
               for r in readings[-13:])                       # the last quarter or so
    out.update(alert=alert, alarm=alarm, current=round(value, 3), recent_peak=round(peak, 3))
    worst = max(magnitude, peak)
    out["state"] = _state(worst, alert, alarm)
    out["score"] = score(worst / alarm, (alert or alarm * 0.6) / alarm, 1.3) if alarm else 100
    since = " since installation" if kind in ("displacement", "tilt") else ""
    out["headline"] = f"{value:.{1 if kind == 'strain' else 2}f} {unit}{since}" + (
        f", peak {peak:.{1 if kind == 'strain' else 2}f} recently" if peak > magnitude * 1.15 else "")
    return out


def assess_element(element: Any, sensors: list[dict[str, Any]], asset: Any, allowance: float | None,
                   life: int, design: dict[str, Any] | None) -> dict[str, Any]:
    """An element's condition: its worst sensor, and what its corrosion does to Triton's ratio."""
    judged = [s for s in sensors if s["score"] is not None and not s["silent"]]
    state = max((s["state"] for s in judged), key=lambda s: STATE_RANK[s], default="neutral")
    health = min((s["score"] for s in judged), default=None)
    design_ur = (design or {}).get("ur") if design else None
    if design_ur is None and element["design_ur"] is not None:
        design_ur = float(element["design_ur"])
    out: dict[str, Any] = {"state": state, "health": health, "design_ur": design_ur,
                           "design_from": "Triton" if design else ("typed in" if design_ur is not None else ""),
                           "ur_at_life": None, "allowance": allowance}
    corrosion = next((s for s in sensors if s["kind"] == "corrosion" and s.get("projected_at_life") is not None), None)
    wall = element["wall_mm"]
    if corrosion and design_ur is not None and wall and allowance:
        # A thin steel section's capacity falls roughly in proportion to its remaining wall.
        # Triton designed it with the allowance gone, so scale by what the projection leaves instead.
        left = wall - corrosion["projected_at_life"]
        out["ur_at_life"] = round(design_ur * (wall - allowance) / left, 2) if left > 0 else math.inf
        if out["ur_at_life"] > 1:
            out["state"] = "critical"
            out["health"] = min(out["health"] if out["health"] is not None else 100, 30)
    return out


def recommendations(element: Any, condition: dict[str, Any], sensors: list[dict[str, Any]],
                    asset: Any) -> list[dict[str, str]]:
    """What to do about one element, most pressing first."""
    out: list[dict[str, str]] = []
    name = element["name"]
    for s in sensors:
        if s["silent"]:
            out.append({"state": "warning", "element": name,
                        "text": f"{s['label']} has sent nothing since {s['latest_at'][:10]}. Check the logger and its cable before relying on {name}'s status."})
        if s["kind"] == "corrosion" and s["state"] == "critical":
            year = f" around {int(s['exhausted_year'])}" if s.get("exhausted_year") else ""
            out.append({"state": "critical", "element": name,
                        "text": f"Corrosion on {name} is on course to use up its {s['allowance']:.1f} mm allowance{year}, before the end of its design life. Commission an ultrasonic thickness survey to confirm, and price cathodic protection or a coating repair for the {labels(ZONES).get(element['zone'], element['zone']).lower()} zone."})
        elif s["kind"] == "corrosion" and s["state"] == "warning":
            out.append({"state": "warning", "element": name,
                        "text": f"Corrosion on {name} is close to its design rate ({round(100 * s['ratio'])}% of the allowance by end of life). Move its thickness survey to every six months."})
        elif s["kind"] == "strain" and s["state"] == "critical":
            out.append({"state": "critical", "element": name,
                        "text": f"{s['label']} on {name} has passed its alarm strain ({s['alarm']:.0f} µε). Inspect {name} for berthing or overload damage, and check the recorded strains against Triton's design forces."})
        elif s["kind"] == "strain" and s["state"] == "warning":
            out.append({"state": "warning", "element": name,
                        "text": f"{s['label']} on {name} is above its alert strain. Review the berthing log for the dates of the peaks."})
        elif s["kind"] in ("displacement", "tilt") and s["state"] in ("warning", "critical"):
            out.append({"state": s["state"], "element": name,
                        "text": f"{name} has moved {s['current']} {s['unit']} since installation. Order a survey of the line and level of the {labels(ASSET_KINDS).get(asset['kind'], 'structure').lower()} around it."})
    ur = condition.get("ur_at_life")
    if ur is not None and ur > 1:
        shown = "beyond its remaining section" if not math.isfinite(ur) else f"about {ur:.2f}"
        out.append({"state": "critical", "element": name,
                    "text": f"With the projected section loss, {name}'s utilisation reaches {shown} by the end of its design life (Triton designed it at {condition['design_ur']:.2f}). Re-run {name} in Triton with the measured thickness."})
    out.sort(key=lambda r: -STATE_RANK[r["state"]])
    return out


def readings_for(conn: sqlite3.Connection, sensor_ids: Iterable[int]) -> dict[int, list[Any]]:
    ids = list(sensor_ids)
    found: dict[int, list[Any]] = {i: [] for i in ids}
    if not ids:
        return found
    marks = ",".join("?" * len(ids))
    for row in conn.execute(f"SELECT sensor_id, at, value FROM marine_readings WHERE sensor_id IN ({marks})"
                            " ORDER BY sensor_id, at", ids):
        found[row["sensor_id"]].append(row)
    return found


def assess_asset(conn: sqlite3.Connection, asset: Any, today: date | None = None) -> dict[str, Any]:
    """Everything the asset's page shows: each element, its sensors, the asset's health."""
    today = today or date.today()
    durability = marine_triton.durability(asset)
    life = int(durability["life"])
    design = marine_triton.design_utilisation(asset["triton_project"], asset["triton_section"])
    elements = conn.execute("SELECT * FROM marine_elements WHERE asset_id = ? ORDER BY x, name",
                            (asset["id"],)).fetchall()
    sensors = conn.execute(
        "SELECT s.* FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
        " WHERE e.asset_id = ? ORDER BY s.label", (asset["id"],)).fetchall()
    readings = readings_for(conn, [s["id"] for s in sensors])
    by_element: dict[int, list[Any]] = {}
    for s in sensors:
        by_element.setdefault(s["element_id"], []).append(s)

    out_elements, advice = [], []
    for element in elements:
        allowance = marine_triton.allowance_for(element, durability["allowances"])
        judged = [assess_sensor(s, readings[s["id"]], element, asset, allowance, life, today)
                  for s in by_element.get(element["id"], [])]
        from_triton = design.get(element["triton_element"] or element["name"])
        condition = assess_element(element, judged, asset, allowance, life, from_triton)
        todo = recommendations(element, condition, judged, asset)
        advice.extend(todo)
        out_elements.append({"element": dict(element), "sensors": judged, **condition, "advice": todo})

    scored = [e["health"] for e in out_elements if e["health"] is not None]
    state = max((e["state"] for e in out_elements), key=lambda s: STATE_RANK[s], default="neutral")
    advice.sort(key=lambda r: -STATE_RANK[r["state"]])
    return {
        "elements": out_elements,
        "health": round(sum(scored) / len(scored)) if scored else None,
        "state": state,
        "counts": {s: sum(1 for e in out_elements if e["state"] == s) for s in ("good", "warning", "critical", "neutral")},
        "sensors": len(sensors),
        "advice": advice,
        "durability": durability,
        "triton_linked": bool(design),
        "today": today.isoformat(),
    }


# --- a demonstration asset -------------------------------------------------------------

def create_demo(conn: sqlite3.Connection, user_id: int | None, today: date | None = None) -> int:
    """A berth of tubular piles, a combi wall and a deck, wired with simulated sensors.

    It exists so the twin can be seen working before a real asset is set up:
    eight years into a fifty-year life, some piles corroding faster than they
    were designed to and one of them overloaded at berthing.
    """
    today = today or date.today()
    commissioned = date(today.year - 8, 3, 1).isoformat()
    asset_id = conn.execute(
        "INSERT INTO marine_assets (name, kind, location, client, commissioned, design_life, corrosion_code, created_by)"
        " VALUES (?, 'quay_wall', ?, ?, ?, 50, 'bs6349', ?)",
        ("Demo berth — Quay 1", "Demonstration", "Port authority (demo)", commissioned, user_id)).lastrowid

    def element(name, kind, material, zone, x, y, z, wall=None, ur=None):
        return conn.execute(
            "INSERT INTO marine_elements (asset_id, name, kind, material, zone, wall_mm, design_ur, model_ref, x, y, z)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (asset_id, name, kind, material, zone, wall, ur, name, x, y, z)).lastrowid

    def sensor(element_id, kind, label):
        _, _, alert, alarm = SENSOR_KINDS[kind]
        conn.execute("INSERT INTO marine_sensors (element_id, kind, label, alert, alarm, simulated)"
                     " VALUES (?, ?, ?, ?, ?, 1)", (element_id, kind, label, alert, alarm))

    urs = [0.71, 0.78, 0.84, 0.88, 0.80, 0.74]
    for i, ur in enumerate(urs):
        pid = element(f"P{i + 1:02d}", "pile", "steel", "splash", i * 8.0, 0.0, 0.0, wall=16.0, ur=ur)
        sensor(pid, "corrosion", f"P{i + 1:02d}-UT1")
        sensor(pid, "strain", f"P{i + 1:02d}-SG1")
    for i in range(3):
        wid = element(f"CW{i + 1}", "combi_wall", "steel", "tidal", 4.0 + i * 14.0, -6.0, 0.0, wall=20.0, ur=0.82)
        sensor(wid, "corrosion", f"CW{i + 1}-UT1")
        sensor(wid, "displacement", f"CW{i + 1}-D1")
    deck = element("DECK", "slab", "concrete", "atmospheric", 20.0, -3.0, 3.5, ur=0.66)
    sensor(deck, "tilt", "DECK-T1")
    sensor(deck, "strain", "DECK-SG1")
    refresh_simulated(conn, asset_id, today)
    return asset_id
