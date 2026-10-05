"""MarineTwin: the monitored life of a marine structure after it is handed over.

An **asset** is one structure — a quay wall, a jetty, a dolphin, a pontoon. It
is made of **elements**: the structure itself (piles, combi wall panels, beams,
the deck) and the quay furniture that takes the knocks (fenders, bollards, crane
rails, ladders, stoppers). Each element may carry **sensors**, whose
**readings** arrive over time:

* steel — strain, ultrasonic thickness (corrosion), movement and tilt;
* concrete — chloride at the rebar, crack width and half-cell potential, the
  three things that say reinforcement corrosion is coming before the spalling does;
* furniture — the fender reaction and bollard line load against their ratings,
  and the crane rail's gauge and level against tolerance;
* anything — the grade from a visual inspection, 1 (as new) to 5 (failed), with
  the inspector's note, so damage nobody instrumented is still reported.

What it is judged against comes from the design, and the design came from
Triton (see ``marine_triton``): the utilisation each element was designed to,
the corrosion it was allowed to lose, and the fender and bollard ratings. Triton
is only read. The twin's three questions are the client's three questions:

* **How is it now?** Each sensor's latest reading against its limits.
* **Where is it heading?** Corrosion is fitted as loss = a·tᵇ and projected to
  the end of the design life; chlorides and cracks are trended to the year they
  reach their limit.
* **What should be done?** A recommendation for each element that needs one.

For the prototype the sensors are **simulated** — deterministic per sensor, so
the same asset tells the same story every time it is drawn — and real readings
can be imported from a CSV, or an inspection typed in, whenever they exist.
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
    ("crane_rail", "Crane rail"),
    ("crane_stopper", "Crane stopper"),
    ("storm_pin", "Storm pin / tie-down"),
    ("ladder", "Ladder"),
    ("ramp", "RoRo ramp / linkspan"),
    ("tie_rod", "Tie rod / anchor"),
    ("other", "Other"),
]
# The quay furniture: what the ships and cranes knock about, as against the structure.
FURNITURE = {"fender", "bollard", "crane_rail", "crane_stopper", "storm_pin", "ladder", "ramp"}
# What the berth handles: it decides the ships, the equipment and the 3D scene.
TERMINAL_TYPES = [
    ("container", "Container"),
    ("general_cargo", "General cargo"),
    ("roro", "RoRo (vehicles)"),
    ("bulk", "Dry bulk"),
    ("multipurpose", "Multipurpose"),
]
# What a berth without crane stoppers (no rail-mounted cranes) is used for: the user sets it per
# berth in the live port. The ships that call, the cranes and what is stored behind follow it.
BERTH_USES = [
    ("container", "Containers, mobile cranes"),
    ("general_cargo", "General cargo, mobile cranes"),
    ("roro", "RoRo, vehicles over the ramp"),
    ("mixed", "Both: cargo and RoRo ships"),
]
ZONES = [
    ("atmospheric", "Atmospheric"),
    ("splash", "Splash"),
    ("tidal", "Tidal"),
    ("immersed", "Permanently immersed"),
    ("buried", "Buried"),
]
MATERIALS = [("steel", "Steel"), ("concrete", "Reinforced concrete"), ("rubber", "Rubber / elastomer")]

# What each sensor measures and the limits it is judged by.
#   alert, alarm  the defaults; a sensor can carry its own
#   rated         the limit is a rating from Triton's quay furniture: alarm at the rating, alert at 80 %
#   relative      measured from the first reading (movement since installation)
#   absolute      either side of zero is as bad (a rail off its line one way or the other)
#   lower_worse   more negative is worse (half-cell potential)
#   trend         projected to the year it reaches its alarm
#   latest        only the latest reading counts (an inspection grade supersedes the last)
# Strain: S355, εy = 355 / 210 000 ≈ 1690 µε; alert at half of it, alarm at three quarters.
SENSOR_KINDS: dict[str, dict[str, Any]] = {
    "strain": {"name": "Strain", "unit": "µε", "alert": 850.0, "alarm": 1250.0, "tag": "SG"},
    "corrosion": {"name": "Thickness loss", "unit": "mm", "alert": None, "alarm": None, "tag": "UT"},
    "displacement": {"name": "Displacement", "unit": "mm", "alert": 25.0, "alarm": 50.0, "tag": "D", "relative": True},
    "tilt": {"name": "Tilt", "unit": "°", "alert": 0.5, "alarm": 1.0, "tag": "T", "relative": True},
    # Concrete. Chloride: about 0.4 % by mass of cement at the bar is the usual threshold for
    # corrosion to start (BS EN 206 / BRE 444), alert at half. Cracks: BS 6349 / EN 1992 limit
    # 0.3 mm in the XS classes. Half-cell: ASTM C876, more negative than −350 mV CSE is a
    # 90 % chance of active corrosion, −200 to −350 mV uncertain.
    "chloride": {"name": "Chloride at the rebar", "unit": "% cement", "alert": 0.2, "alarm": 0.4, "tag": "CL", "trend": True},
    "crack_width": {"name": "Crack width", "unit": "mm", "alert": 0.2, "alarm": 0.3, "tag": "CR", "trend": True},
    "half_cell": {"name": "Half-cell potential", "unit": "mV CSE", "alert": -200.0, "alarm": -350.0, "tag": "HC", "lower_worse": True},
    # Furniture.
    "fender_reaction": {"name": "Fender reaction", "unit": "kN", "alert": None, "alarm": None, "tag": "FR", "rated": "fender"},
    "bollard_load": {"name": "Bollard line load", "unit": "t", "alert": None, "alarm": None, "tag": "BL", "rated": "bollard"},
    # Crane rails: a usual tolerance for an operating STS rail is ±10 mm in line and level.
    "rail_gauge": {"name": "Rail line deviation", "unit": "mm", "alert": 5.0, "alarm": 10.0, "tag": "RG", "absolute": True},
    "rail_level": {"name": "Rail level deviation", "unit": "mm", "alert": 5.0, "alarm": 10.0, "tag": "RL", "absolute": True},
    # Anything: a visual inspection.
    "inspection": {"name": "Inspection grade", "unit": "of 5", "alert": 3.0, "alarm": 4.0, "tag": "IN", "latest": True},
}
GRADES = [
    (1, "As new"),
    (2, "Minor wear"),
    (3, "Moderate damage"),
    (4, "Major damage"),
    (5, "Failed / unsafe"),
]

# The sensors an element of each kind is set up with unless others are picked.
SUGGESTED: dict[str, list[str]] = {
    "pile": ["corrosion", "strain"],
    "combi_wall": ["corrosion", "displacement"],
    "sheet_pile": ["corrosion", "displacement"],
    "beam": ["chloride", "crack_width", "half_cell"],
    "slab": ["chloride", "crack_width", "tilt"],
    "fender": ["fender_reaction", "inspection"],
    "bollard": ["bollard_load", "inspection"],
    "crane_rail": ["rail_gauge", "rail_level"],
    "crane_stopper": ["inspection"],
    "storm_pin": ["inspection"],
    "ladder": ["inspection"],
    "ramp": ["displacement", "inspection"],
    "tie_rod": ["strain", "corrosion"],
    "other": ["inspection"],
}

# A sensor that has said nothing for this long is reported as silent; an inspection, a year and a half.
SILENT_AFTER_DAYS = 45
SILENT_INSPECTION_DAYS = 550
# The sampling a simulated sensor keeps: a strain gauge logs, a survey is periodic.
SIM_STEP_DAYS = {"strain": 7, "corrosion": 30, "displacement": 7, "tilt": 7, "chloride": 180,
                 "crack_width": 90, "half_cell": 90, "fender_reaction": 7, "bollard_load": 7,
                 "rail_gauge": 30, "rail_level": 30, "inspection": 180}
# How far back a simulated sensor's history goes, however old the asset.
SIM_HISTORY_YEARS = 6

STATES = ("good", "warning", "critical")
STATE_RANK = {"neutral": -1, "good": 0, "warning": 1, "critical": 2}


def labels(pairs: list[tuple[str, str]]) -> dict[str, str]:
    return dict(pairs)


def suggested(kind: str) -> list[str]:
    return SUGGESTED.get(kind, SUGGESTED["other"])


# --- where things are on the earth ---------------------------------------------------------

def geolocate(asset: Any, x: float, y: float) -> tuple[float, float] | None:
    """A model position (metres along x and y from the site's origin) as latitude and longitude.

    The model is turned by the asset's rotation (from its x axis to east,
    anticlockwise). Good to a few centimetres across a berth, which is all a map needs.
    """
    lat0, lon0 = asset["latitude"], asset["longitude"]
    if lat0 is None or lon0 is None:
        return None
    theta = math.radians(asset["rotation"] or 0.0)
    east = x * math.cos(theta) - y * math.sin(theta)
    north = x * math.sin(theta) + y * math.cos(theta)
    return (lat0 + north / 111_320.0, lon0 + east / (111_320.0 * max(math.cos(math.radians(lat0)), 1e-6)))


# --- what the Revit model brings ---------------------------------------------------------

def apply_site(conn: sqlite3.Connection, asset_id: int, found: dict[str, Any]) -> list[str]:
    """Take the model's location, orientation, datum and terminal type onto the asset. Says what it took."""
    site, took, sets = found.get("site", {}), [], {}
    if site.get("latitude") is not None and site.get("longitude") is not None:
        sets.update(latitude=site["latitude"], longitude=site["longitude"])
        took.append(f"its location ({site['latitude']:.5f}, {site['longitude']:.5f}, from {site.get('source', 'the model')})")
    if site.get("rotation") is not None and (site.get("eastings") is not None or site.get("rotation")):
        sets["rotation"] = site["rotation"]
    if site.get("epsg"):
        sets["epsg"] = site["epsg"]
    if found.get("msl_cd") is not None:
        sets["msl_cd"] = found["msl_cd"]
        took.append(f"its datum (MSL at +{found['msl_cd']:.2f} mCD)")
    if found.get("terminal_type") in dict(TERMINAL_TYPES):
        sets["terminal_type"] = found["terminal_type"]
        took.append(f"its terminal type ({labels(TERMINAL_TYPES)[found['terminal_type']].lower()})")
    project = found.get("project", {})
    if project.get("MT_AssetType") in dict(ASSET_KINDS):
        sets["kind"] = project["MT_AssetType"]
    if project.get("MT_TritonProject"):
        sets["triton_project"] = str(project["MT_TritonProject"])
    try:
        sets["commissioned"] = date.fromisoformat(str(project.get("MT_Commissioned"))[:10]).isoformat()
    except ValueError:
        pass
    try:
        if project.get("MT_DesignLife") is not None:
            sets["design_life"] = max(1, int(float(project["MT_DesignLife"])))
    except (TypeError, ValueError):
        pass
    if sets:
        conn.execute(f"UPDATE marine_assets SET {', '.join(k + ' = ?' for k in sets)} WHERE id = ?", (*sets.values(), asset_id))
    return took


# --- one monitored element per design ----------------------------------------------------

# Items each carry their own rating or are inspected one by one: every one keeps its sensors.
PER_ITEM_KINDS = {"fender", "bollard", "ladder", "storm_pin", "crane_stopper", "ramp"}
# Elements of one design with no legend in the model are still grouped, a stretch of quay at a time.
GROUP_STRETCH_M = 200.0


def design_group(e: Any) -> str:
    """The design an element shares with others, so one of them carries the sensors for all.

    The model's legend wins (MT_Legend, or the name every pile of a design section
    shares, MP1-DS03). Without one, elements of the same kind, material, zone and
    wall are one design along each 200 m of quay. A fender, bollard or ladder is
    its own design: each is rated or inspected by itself.
    """
    keys = e.keys() if hasattr(e, "keys") else ()
    get = (lambda k: e[k] if k in keys else None)
    kind = get("kind") or "other"
    if kind in PER_ITEM_KINDS:
        return ""
    named = (get("design_group") or get("group") or get("legend") or "").strip()
    if named:
        return f"{kind}:{named}"
    wall = get("wall_mm")
    cell = (math.floor((get("x") or 0) / GROUP_STRETCH_M), math.floor((get("y") or 0) / GROUP_STRETCH_M))
    return f"{kind}|{get('material') or ''}|{get('zone') or ''}|{round(wall) if wall else ''}|{cell[0]},{cell[1]}"


def trim_sensors(conn: sqlite3.Connection, asset_id: int) -> dict[str, int]:
    """Keep the sensors of one element per design and remove the rest's simulated ones.

    The element kept is one with a real feed or a typed-in inspection, else the
    first by name. A sensor that ever got a real reading or an inspector's note
    stays wherever it is. Returns how many sensors were removed and how many remain.
    """
    elements = conn.execute("SELECT * FROM marine_elements WHERE asset_id = ? ORDER BY name", (asset_id,)).fetchall()
    sensors: dict[int, list[Any]] = {}
    for s in conn.execute(
            "SELECT s.id, s.element_id, s.simulated, s.feed_device,"
            " EXISTS (SELECT 1 FROM marine_readings r WHERE r.sensor_id = s.id AND r.note != '') AS noted"
            " FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id WHERE e.asset_id = ?", (asset_id,)):
        sensors.setdefault(s["element_id"], []).append(s)

    def real(s) -> bool:
        return not s["simulated"] or bool(s["feed_device"]) or bool(s["noted"])

    groups: dict[str, list[Any]] = {}
    for e in elements:
        group = design_group(e)
        if group and sensors.get(e["id"]):
            groups.setdefault(group, []).append(e)
    gone: list[int] = []
    for members in groups.values():
        keep = next((e for e in members if any(real(s) for s in sensors[e["id"]])), members[0])
        for e in members:
            if e["id"] != keep["id"]:
                gone += [s["id"] for s in sensors[e["id"]] if not real(s)]
    for i in range(0, len(gone), 500):
        chunk = gone[i:i + 500]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"DELETE FROM marine_readings WHERE sensor_id IN ({marks})", chunk)
        conn.execute(f"DELETE FROM marine_sensors WHERE id IN ({marks})", chunk)
    left = conn.execute("SELECT COUNT(*) FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
                        " WHERE e.asset_id = ?", (asset_id,)).fetchone()[0]
    return {"removed": len(gone), "left": left}


def regroup(conn: sqlite3.Connection, asset_id: int, found: dict[str, Any]) -> int:
    """Copy each model element's legend onto the matching tracked element. Returns how many changed."""
    by_ref, by_name = {}, {}
    for e in found.get("elements", []):
        named = e.get("group") or e.get("legend") or ""
        by_ref[e.get("global_id")] = named
        by_name[e["name"]] = named
    changed = 0
    for row in conn.execute("SELECT id, name, model_ref, design_group FROM marine_elements WHERE asset_id = ?", (asset_id,)).fetchall():
        named = by_ref.get(row["model_ref"], by_name.get(row["name"]))
        if named is not None and named != row["design_group"]:
            conn.execute("UPDATE marine_elements SET design_group = ? WHERE id = ?", (named, row["id"]))
            changed += 1
    return changed


def import_elements(conn: sqlite3.Connection, asset_id: int, found: dict[str, Any], names: Iterable[str] | None = None) -> dict[str, list[str]]:
    """Create MarineTwin elements for the model's elements, and point existing ones at their GlobalId.

    A new element takes its kind, material, zone, wall and Triton name from the
    model's MT_Common properties (or what its name and IFC class imply), its
    position from the model, and the sensors MT_Sensors lists or the usual ones
    for its kind (for elements sharing a name, only the first of them). A fender or bollard rated in the model (MT_Furniture) has its
    sensor's limits set from that rating.
    """
    wanted = set(names) if names is not None else None
    existing = {r["name"]: r for r in conn.execute("SELECT * FROM marine_elements WHERE asset_id = ?", (asset_id,))}
    kinds, materials, zones = dict(ELEMENT_KINDS), dict(MATERIALS), dict(ZONES)
    made, linked = [], []
    with_sensors = {r[0] for r in conn.execute("SELECT DISTINCT s.element_id FROM marine_sensors s JOIN marine_elements e"
                                               " ON e.id = s.element_id WHERE e.asset_id = ?", (asset_id,))}
    instrumented = {design_group(r) for r in existing.values() if r["id"] in with_sensors} - {""}
    for e in sorted(found.get("elements", []), key=lambda e: e["name"]):
        if wanted is not None and e["name"] not in wanted:
            continue
        if e["name"] in existing:
            row = existing[e["name"]]
            if row is None:
                continue                              # the same name twice in one model: the first is kept
            if row["model_ref"] != e["global_id"]:
                conn.execute("UPDATE marine_elements SET model_ref = ? WHERE id = ?", (e["global_id"], row["id"]))
                linked.append(e["name"])
            continue
        kind = e["kind"] if e["kind"] in kinds else "other"
        element_id = conn.execute(
            "INSERT INTO marine_elements (asset_id, name, kind, material, zone, wall_mm, design_ur, triton_element,"
            " model_ref, design_group, x, y, z) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (asset_id, e["name"], kind, e["material"] if e["material"] in materials else "steel",
             e["zone"] if e["zone"] in zones else "splash", e.get("wall_mm"), e.get("design_ur"),
             e.get("triton_element") or "", e["global_id"], e.get("group") or e.get("legend") or "",
             e["x"], e["y"], e["z"])).lastrowid
        row = conn.execute("SELECT * FROM marine_elements WHERE id = ?", (element_id,)).fetchone()
        chosen = [k for k in e.get("sensors", []) if k in SENSOR_KINDS]
        group = design_group(row)
        if not chosen and group:
            # Elements sharing one design (every MP1-DS03 pile) are monitored through one of them,
            # as on a real quay: the first along the berth gets the usual sensors.
            if group not in instrumented:
                instrumented.add(group)
                chosen = suggested(kind)
        elif not chosen:
            chosen = suggested(kind)
        for sensor_kind in dict.fromkeys(chosen):
            alarm = e.get("rated_reaction") if sensor_kind == "fender_reaction" else \
                e.get("bollard_capacity") if sensor_kind == "bollard_load" else None
            conn.execute("INSERT INTO marine_sensors (element_id, kind, label, alert, alarm, simulated) VALUES (?, ?, ?, ?, ?, 1)",
                         (element_id, sensor_kind, f"{e['name']}-{SENSOR_KINDS[sensor_kind]['tag']}1",
                          round(alarm * 0.8, 1) if alarm else None, alarm))
        made.append(e["name"])
        existing[e["name"]] = None
    if made:
        refresh_simulated(conn, asset_id)
    return {"made": made, "linked": linked}


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
  terminal_type   TEXT NOT NULL DEFAULT 'container',-- see TERMINAL_TYPES
  latitude        REAL,                             -- decimal degrees, WGS 84: from the IFC site or typed in
  longitude       REAL,
  rotation        REAL NOT NULL DEFAULT 0,          -- degrees from the model's x axis to east, anticlockwise
  msl_cd          REAL NOT NULL DEFAULT 1.0,        -- mean sea level above chart datum, m: model levels are mCD
  epsg            TEXT NOT NULL DEFAULT '',         -- the project's map grid, from the model
  feed_key        TEXT NOT NULL DEFAULT '',         -- the key a logger sends readings with; blank: none can
  berth_uses      TEXT NOT NULL DEFAULT '{}',       -- JSON, berth number -> BERTH_USES key, for berths without crane stoppers
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
  design_group    TEXT NOT NULL DEFAULT '',         -- the design it shares with others (MP1-DS03), from the model
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
  alert           REAL,                             -- NULL: the kind's default, or the Triton rating
  alarm           REAL,
  simulated       INTEGER NOT NULL DEFAULT 1,
  feed_device     TEXT NOT NULL DEFAULT ''          -- the logger whose readings it last got, blank: none
);

CREATE TABLE IF NOT EXISTS marine_readings (
  sensor_id       INTEGER NOT NULL REFERENCES marine_sensors(id) ON DELETE CASCADE,
  at              TEXT NOT NULL,                    -- YYYY-MM-DD or YYYY-MM-DDTHH:MM
  value           REAL NOT NULL,
  note            TEXT NOT NULL DEFAULT '',         -- what an inspector saw
  PRIMARY KEY (sensor_id, at)
);
CREATE TABLE IF NOT EXISTS marine_feed_log (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  at              TEXT NOT NULL,                    -- when it arrived, UTC, YYYY-MM-DDTHH:MM:SS
  device          TEXT NOT NULL DEFAULT '',
  written         INTEGER NOT NULL DEFAULT 0,
  problems        INTEGER NOT NULL DEFAULT 0,
  first_problem   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS marine_changes (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  at              TEXT NOT NULL DEFAULT (datetime('now')),   -- UTC
  user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
  action          TEXT NOT NULL,                    -- what was done, in words
  detail          TEXT NOT NULL DEFAULT ''          -- what the page said came of it
);
CREATE INDEX IF NOT EXISTS marine_changes_asset ON marine_changes (asset_id, id);
CREATE TABLE IF NOT EXISTS marine_scenarios (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  params          TEXT NOT NULL,                    -- JSON, the keys of marine_sim.PARAMS
  created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


# Columns added after the first release, for databases made before them.
LATER_COLUMNS = [
    ("marine_assets", "terminal_type", "TEXT NOT NULL DEFAULT 'container'"),
    ("marine_assets", "latitude", "REAL"),
    ("marine_assets", "longitude", "REAL"),
    ("marine_assets", "rotation", "REAL NOT NULL DEFAULT 0"),
    ("marine_assets", "msl_cd", "REAL NOT NULL DEFAULT 1.0"),
    ("marine_assets", "epsg", "TEXT NOT NULL DEFAULT ''"),
    ("marine_assets", "feed_key", "TEXT NOT NULL DEFAULT ''"),
    ("marine_assets", "berth_uses", "TEXT NOT NULL DEFAULT '{}'"),
    ("marine_sensors", "feed_device", "TEXT NOT NULL DEFAULT ''"),
    ("marine_elements", "design_group", "TEXT NOT NULL DEFAULT ''"),
]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, column, definition in LATER_COLUMNS:
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


# --- dates -------------------------------------------------------------------------

def _day(text: str) -> date:
    return datetime.fromisoformat(str(text)[:10]).date()


def years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


# --- limits ------------------------------------------------------------------------

def limits(sensor: Any, ratings: dict[str, Any]) -> tuple[float | None, float | None, str]:
    """(alert, alarm, where they came from) for one sensor.

    The sensor's own limits win. Otherwise a fender or bollard is judged
    against its rating in Triton's quay furniture, and anything else against
    its kind's default.
    """
    spec = SENSOR_KINDS.get(sensor["kind"], {})
    alert, alarm = sensor["alert"], sensor["alarm"]
    if alert is not None and alarm is not None:
        return alert, alarm, "set on the sensor"
    rated = spec.get("rated")
    if rated and ratings.get(rated):
        rating = float(ratings[rated])
        return (alert if alert is not None else round(0.8 * rating, 1),
                alarm if alarm is not None else rating, ratings.get("source", ""))
    return (alert if alert is not None else spec.get("alert"),
            alarm if alarm is not None else spec.get("alarm"), "default")


# --- the simulator -----------------------------------------------------------------

def _rng(sensor_id: int, kind: str) -> random.Random:
    return random.Random(f"marinetwin:{sensor_id}:{kind}")


def simulate(sensor: Any, element: Any, asset: Any, allowance: float | None,
             until: date | None = None, ratings: dict[str, Any] | None = None) -> list[tuple[str, float]]:
    """The readings a simulated sensor would have logged up to ``until`` (today).

    Deterministic: one sensor always tells the same story, and running it again
    later only adds the weeks since. Shapes, not data — but the shapes engineers
    expect: corrosion that slows as rust builds up (≈ t^0.85), strain riding a
    seasonal thermal cycle with the odd berthing spike, creep that settles,
    chloride diffusing in as √t, cracks that open slowly, fenders and bollards
    that see the odd hard berthing or storm, rails that wander off their line.
    """
    until = until or date.today()
    commissioned = _day(asset["commissioned"])
    start = max(commissioned, until - timedelta(days=round(365.25 * SIM_HISTORY_YEARS)))
    kind = sensor["kind"]
    step = SIM_STEP_DAYS.get(kind, 7)
    rng = _rng(int(sensor["id"]), kind)
    life = float(asset["design_life"] or 50)
    _, alarm, _ = limits(sensor, ratings or {})

    if kind == "corrosion":
        # Lose between 55 % and 120 % of the allowance by the end of the design life.
        target = (allowance or 3.0) * rng.uniform(0.55, 1.2)
        b = rng.uniform(0.75, 0.95)
        a = target / life ** b
    elif kind == "strain":
        base = float(alarm or 1250.0) * rng.uniform(0.2, 0.5)
        seasonal = rng.uniform(40, 120)
        spikes = rng.uniform(0.01, 0.05)
    elif kind == "displacement":
        creep = rng.uniform(3, 14)
    elif kind == "tilt":
        drift = rng.uniform(0.004, 0.03)
    elif kind == "chloride":
        # Fick's law near the surface: C ≈ k·√t, reaching 30–110 % of the threshold by end of life.
        k = float(alarm or 0.4) * rng.uniform(0.3, 1.1) / math.sqrt(life)
        background = rng.uniform(0.02, 0.06)
    elif kind == "crack_width":
        w0 = rng.uniform(0.04, 0.12)
        growth = (float(alarm or 0.3) * rng.uniform(0.6, 1.4) - w0) / life
    elif kind == "half_cell":
        e0 = rng.uniform(-180, -60)
        fall = rng.uniform(2, 12)                          # mV more negative each year
    elif kind in ("fender_reaction", "bollard_load"):
        rating = float(alarm or (2000.0 if kind == "fender_reaction" else 150.0))
        usual = rng.uniform(0.15, 0.4)
        hard = rng.uniform(0.005, 0.03)                    # weeks with a hard berthing or a storm
    elif kind in ("rail_gauge", "rail_level"):
        wander = rng.uniform(0.1, 1.3) * rng.choice((-1, 1))
    elif kind == "inspection":
        worsen = rng.uniform(0.04, 0.2)

    out: list[tuple[str, float]] = []
    day = start
    last = 0.0
    grade = 1
    while day <= until:
        t = max(years_between(commissioned, day), 1 / 365.25)
        season = math.cos(2 * math.pi * (day.timetuple().tm_yday - 200) / 365.25)
        if kind == "corrosion":
            loss = a * t ** b + rng.gauss(0, 0.04)
            last = max(last - 0.05, loss, 0.0)             # a survey can read a little low, not negative
            value = round(last, 2)
        elif kind == "strain":
            value = base + seasonal * season + rng.gauss(0, 15)
            if rng.random() < spikes:
                value += rng.uniform(100, 400)              # a hard berthing
            value = round(value, 1)
        elif kind == "displacement":
            value = round(creep * math.log1p(t) + 1.5 * season + rng.gauss(0, 0.4), 2)
        elif kind == "tilt":
            value = round(drift * t + 0.02 * season + rng.gauss(0, 0.01), 3)
        elif kind == "chloride":
            value = round(max(0.0, background + k * math.sqrt(t) + rng.gauss(0, 0.01)), 3)
        elif kind == "crack_width":
            last = max(last, w0 + growth * t + rng.gauss(0, 0.008))
            value = round(last + 0.01 * season, 3)          # cracks breathe with the temperature
        elif kind == "half_cell":
            value = round(e0 - fall * t + 15 * season + rng.gauss(0, 12), 0)
        elif kind in ("fender_reaction", "bollard_load"):
            share = usual * rng.uniform(0.6, 1.3)
            if kind == "bollard_load":
                share *= 1 + 0.35 * max(season * -1, 0)     # winter storms pull harder
            if rng.random() < hard:
                share = rng.uniform(0.65, 1.08)
            value = round(rating * share, 1)
        elif kind in ("rail_gauge", "rail_level"):
            value = round(wander * t + 0.8 * season + rng.gauss(0, 0.5), 1)
        elif kind == "inspection":
            if rng.random() < worsen:
                grade = min(5, grade + 1)
            value = float(grade)
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
    ratings = marine_triton.ratings(asset)
    written = 0
    rows = conn.execute(
        "SELECT s.*, e.id AS e_id FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
        " WHERE e.asset_id = ? AND s.simulated = 1", (asset_id,)).fetchall()
    for sensor in rows:
        element = conn.execute("SELECT * FROM marine_elements WHERE id = ?", (sensor["e_id"],)).fetchone()
        allowance = marine_triton.allowance_for(element, allowances)
        series = simulate(sensor, element, asset, allowance, until, ratings)
        conn.execute("DELETE FROM marine_readings WHERE sensor_id = ?", (sensor["id"],))
        conn.executemany("INSERT INTO marine_readings (sensor_id, at, value) VALUES (?, ?, ?)",
                         [(sensor["id"], at, value) for at, value in series])
        written += len(series)
    return written


# --- real readings -----------------------------------------------------------------

def record(conn: sqlite3.Connection, sensor_id: int, at: str, value: float, note: str = "") -> None:
    """One real reading. The first for a simulated sensor clears its simulated history,
    so the two never mix."""
    if conn.execute("SELECT simulated FROM marine_sensors WHERE id = ?", (sensor_id,)).fetchone()[0]:
        conn.execute("DELETE FROM marine_readings WHERE sensor_id = ?", (sensor_id,))
        conn.execute("UPDATE marine_sensors SET simulated = 0 WHERE id = ?", (sensor_id,))
    conn.execute("INSERT OR REPLACE INTO marine_readings (sensor_id, at, value, note) VALUES (?, ?, ?, ?)",
                 (sensor_id, at, value, note))


def record_inspection(conn: sqlite3.Connection, element: Any, at: str, grade: int, note: str) -> int:
    """An inspector's grade for an element, on its inspection sensor (made if it has none)."""
    row = conn.execute("SELECT id FROM marine_sensors WHERE element_id = ? AND kind = 'inspection'"
                       " ORDER BY simulated, id LIMIT 1", (element["id"],)).fetchone()
    if row is None:
        sensor_id = conn.execute(
            "INSERT INTO marine_sensors (element_id, kind, label, simulated) VALUES (?, 'inspection', ?, 0)",
            (element["id"], f"{element['name']}-IN1")).lastrowid
    else:
        sensor_id = row["id"]
    record(conn, sensor_id, at, float(max(1, min(5, grade))), note.strip())
    return sensor_id


def import_csv(conn: sqlite3.Connection, asset_id: int, text: str, device: str = "") -> dict[str, Any]:
    """Readings from a logger export: columns ``sensor``, ``at`` and ``value``, and ``note`` if any.

    ``sensor`` is the sensor's label on this asset (or its number). A sensor
    that receives real readings stops being simulated, so the two never mix.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    fields = {f.strip().lower(): f for f in (reader.fieldnames or [])}
    missing = [f for f in ("sensor", "at", "value") if f not in fields]
    if missing:
        return {"written": 0, "sensors": 0, "problem_count": 1,
                "problems": [f"The file needs the columns sensor, at and value (missing: {', '.join(missing)})."]}
    rows = ({k: row.get(fields[k]) for k in ("sensor", "at", "value", "note") if k in fields} for row in reader)
    return write_rows(conn, asset_id, rows, device=device, first=2)


def write_rows(conn: sqlite3.Connection, asset_id: int, rows: Iterable[dict[str, Any]],
               device: str = "", first: int = 1) -> dict[str, Any]:
    """Readings as dicts with ``sensor``, ``at``, ``value`` and maybe ``note``: from a CSV file or a
    logger sending them. Rows it cannot place are listed (the first twenty), never guessed at.
    ``device`` names the logger that sent them, so its sensors can be found again."""
    sensors = {str(r["label"]).strip().lower(): r["id"] for r in conn.execute(
        "SELECT s.id, s.label FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
        " WHERE e.asset_id = ?", (asset_id,))}
    ids = set(sensors.values())
    written, problems, touched = 0, [], set()
    for number, row in enumerate(rows, start=first):
        if not isinstance(row, dict):
            problems.append(f"Row {number}: not a reading.")
            continue
        key = str(row.get("sensor") or "").strip()
        sensor_id = sensors.get(key.lower())
        if sensor_id is None and key.isdigit() and int(key) in ids:
            sensor_id = int(key)
        if sensor_id is None:
            problems.append(f"Row {number}: no sensor called “{key}” on this asset.")
            continue
        at = str(row.get("at") or "").strip().replace(" ", "T")[:16]
        try:
            datetime.fromisoformat(at)
            value = float(str(row.get("value") if row.get("value") is not None else "").strip())
            if not math.isfinite(value):
                raise ValueError
        except ValueError:
            problems.append(f"Row {number}: the date or the value could not be read.")
            continue
        record(conn, sensor_id, at, value, str(row.get("note") or "").strip())
        touched.add(sensor_id)
        written += 1
    if device and touched:
        marks = ",".join("?" * len(touched))
        conn.execute(f"UPDATE marine_sensors SET feed_device = ? WHERE id IN ({marks})", (device, *touched))
    return {"written": written, "problems": problems[:20], "problem_count": len(problems), "sensors": len(touched)}


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


def trend_year(points: list[tuple[float, float]], limit: float, start_year: float) -> float | None:
    """The year a straight line through (years, value) points reaches ``limit``, if it is rising."""
    if len(points) < 3:
        return None
    xs, ys = [t for t, _ in points], [v for _, v in points]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    if slope <= 0:
        return None
    if ys[-1] >= limit:
        return start_year + xs[-1]
    return start_year + xs[-1] + (limit - ys[-1]) / slope


# How wide a forecast's range is: about 90 % of outcomes fall inside ± this many standard errors.
RANGE_Z = 1.645


def trend_range(points: list[tuple[float, float]], limit: float, start_year: float) -> tuple[float, float | None] | None:
    """(earliest, latest) years a rising trend reaches ``limit``, from the scatter of the readings.

    The slope's standard error gives a fast and a slow line; the latest is None
    when the slow line is flat, i.e. the readings cannot rule out it never getting there.
    """
    if len(points) < 4:
        return None
    xs, ys = [t for t, _ in points], [v for _, v in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    if slope <= 0 or ys[-1] >= limit:
        return None
    resid = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys)]
    se = math.sqrt(sum(r * r for r in resid) / (n - 2) / sxx)
    fast, slow = slope + RANGE_Z * se, slope - RANGE_Z * se
    gap = limit - ys[-1]
    early = start_year + xs[-1] + gap / fast
    late = start_year + xs[-1] + gap / slow if slow > 0 else None
    return early, late


def corrosion_spread(points: list[tuple[float, float]], fit: tuple[float, float]) -> float:
    """The factor (≥ 1) the fitted loss may be off by either way, from the readings' scatter about it."""
    a, b = fit
    logs = [math.log(v) - math.log(a * t ** b) for t, v in points if t > 0.05 and v > 0]
    if len(logs) < 4:
        return 1.0
    sigma = math.sqrt(sum(r * r for r in logs) / (len(logs) - 2))
    return math.exp(RANGE_Z * sigma)


def _years(early: float | None, late: float | None) -> str:
    """'2036 to 2049', or 'from 2036' when the latest cannot be told."""
    if early is None:
        return ""
    if late is None:
        return f"from {int(early)}, maybe never"
    return f"{int(early)} to {int(late)}" if int(late) != int(early) else f"{int(early)}"


def _state(value: float, alert: float | None, alarm: float | None) -> str:
    if alarm is not None and value >= alarm:
        return "critical"
    if alert is not None and value >= alert:
        return "warning"
    return "good"


def _fmt(value: float, unit: str) -> str:
    digits = 0 if abs(value) >= 100 else 1 if abs(value) >= 10 else 2
    return f"{value:,.{digits}f} {unit}"


def assess_sensor(sensor: Any, readings: list[Any], element: Any, asset: Any,
                  allowance: float | None, life: int, today: date,
                  ratings: dict[str, Any] | None = None) -> dict[str, Any]:
    kind = sensor["kind"]
    spec = SENSOR_KINDS.get(kind, {"name": kind, "unit": ""})
    unit = spec["unit"]
    out: dict[str, Any] = {"id": sensor["id"], "label": sensor["label"], "kind": kind, "kind_name": spec["name"],
                           "unit": unit, "simulated": bool(sensor["simulated"]), "count": len(readings),
                           "state": "neutral", "score": None, "latest": None, "latest_at": None, "note": "",
                           "headline": "No readings yet", "silent": False}
    if not readings:
        return out
    latest = readings[-1]
    out["latest"], out["latest_at"] = latest["value"], latest["at"]
    out["note"] = latest["note"] if "note" in latest.keys() else ""
    silent_after = SILENT_INSPECTION_DAYS if kind == "inspection" else SILENT_AFTER_DAYS
    if (today - _day(latest["at"])).days > silent_after:
        out["silent"] = True
    commissioned = _day(asset["commissioned"])

    if kind == "corrosion":
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
        spread = corrosion_spread(points, fit)
        out["projected_range"] = (round(at_life / spread, 2), round(at_life * spread, 2))
        if spread > 1 and math.isfinite(exhausted):
            # Faster loss (a × spread) uses the allowance up sooner, slower loss later.
            soon, later = (allowance / (a * spread)) ** (1 / b), (allowance / (a / spread)) ** (1 / b)
            out["exhausted_range"] = (commissioned.year + soon, commissioned.year + later)
        if out["exhausted_year"] is not None and ratio >= 0.85:
            when = f"used up around {int(out['exhausted_year'])}"
            if out.get("exhausted_range"):
                when += f" (likely {_years(*out['exhausted_range'])})"
        else:
            when = f"{round(100 * ratio)}% of the allowance by the end of the design life"
        out["headline"] = f"{latest['value']:.2f} of {allowance:.2f} mm lost; {when}"
        return out

    alert, alarm, source = limits(sensor, ratings or {})
    out.update(alert=alert, alarm=alarm, limit_source=source)
    base = readings[0]["value"] if spec.get("relative") else 0.0
    sign = -1.0 if spec.get("lower_worse") else 1.0

    def severity(value: float) -> float:
        v = (value - base) * sign
        return abs(v) if spec.get("absolute") or spec.get("relative") else v

    value = latest["value"] - base
    current = severity(latest["value"])
    recent = readings[-1:] if spec.get("latest") else readings[-13:]   # the last quarter or so
    peak = max(severity(r["value"]) for r in recent)
    worst = max(current, peak)
    s_alert = alert * sign if alert is not None else None
    s_alarm = alarm * sign if alarm is not None else None
    out.update(current=round(value, 3), recent_peak=round(peak * sign, 3))
    out["state"] = _state(worst, s_alert, s_alarm)
    if s_alarm:
        fine = 0.85 * (s_alert if s_alert is not None else 0.6 * s_alarm) / s_alarm
        out["score"] = score(worst / s_alarm, fine, 1.3)
    else:
        out["score"] = 100

    if kind == "inspection":
        word = labels([(str(g), w) for g, w in GRADES]).get(str(int(latest["value"])), "")
        out["headline"] = f"Grade {int(latest['value'])} of 5, {word.lower()}" + (f": {out['note']}" if out["note"] else "")
    else:
        since = " since installation" if spec.get("relative") else ""
        out["headline"] = _fmt(value, unit) + since
        if peak > current * 1.15 and peak - current > 1e-9:
            out["headline"] += f", peak {_fmt(peak * sign, unit)} recently"
        if spec.get("rated") and alarm:
            out["headline"] += f" ({round(100 * peak / alarm)}% of its {_fmt(alarm, unit)} rating at the peak)"

    if spec.get("rated") and alarm:
        # A fender or bollard overloaded months ago may still be damaged: say how often it has been.
        over = [r for r in readings if r["value"] >= alarm]
        out["exceedances"] = len(over)
        if over:
            out["last_exceeded"] = over[-1]["at"][:10]
            out["headline"] += f"; over its rating {len(over)} time{'s' if len(over) > 1 else ''}, last on {out['last_exceeded']}"
            if out["state"] == "good":
                out["state"] = "warning"
                out["score"] = min(out["score"], 75)

    if spec.get("trend") and alarm is not None:
        points = [(years_between(commissioned, _day(r["at"])), r["value"]) for r in readings[-12:]]
        year = trend_year(points, alarm, commissioned.year + (commissioned.timetuple().tm_yday - 1) / 365.25)
        out["limit_year"] = year
        spread = trend_range(points, alarm, commissioned.year + (commissioned.timetuple().tm_yday - 1) / 365.25)
        out["limit_year_range"] = spread
        end = commissioned.year + life
        if year is not None and current < alarm:
            out["headline"] += f"; reaches {_fmt(alarm, unit)} around {int(year)}"
            if spread:
                out["headline"] += f" (likely {_years(*spread)})"
            if year < end and out["state"] == "good":
                out["state"] = "warning"                    # heading past its limit within the design life
                out["score"] = min(out["score"], 80)
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


# What to do about an element whose last inspection found damage, by what it is.
_REPAIR = {
    "fender": "replace the torn rubber unit or the missing panel pads, and check the chains and anchor bolts",
    "bollard": "check the bollard for cracks and its anchors for movement, and take it out of use until it is checked",
    "crane_rail": "inspect the clips, pads and welds and realign the rail before the crane runs on it again",
    "crane_stopper": "check the stopper and its anchors; a crane that hits a weak stopper runs off the end of the rail",
    "storm_pin": "check the pin socket and the tie-down plates are free and undamaged before the storm season",
    "ladder": "repair or replace the damaged rungs and brackets; a ladder is a means of escape from the water",
    "concrete": "break out the spalled or delaminated concrete, treat the bars and patch-repair it",
    "steel": "clean back, measure the remaining thickness and recoat or plate it",
}


def recommendations(element: Any, condition: dict[str, Any], sensors: list[dict[str, Any]],
                    asset: Any) -> list[dict[str, str]]:
    """What to do about one element, most pressing first."""
    out: list[dict[str, str]] = []
    name = element["name"]

    def add(state: str, text: str) -> None:
        out.append({"state": state, "element": name, "text": text})

    for s in sensors:
        state = s["state"]
        if s["silent"]:
            if s["kind"] == "inspection":
                add("warning", f"{name} has not been inspected since {s['latest_at'][:10]}. Book an inspection.")
            else:
                add("warning", f"{s['label']} has sent nothing since {s['latest_at'][:10]}. Check the logger "
                               f"and its cable before relying on {name}'s status.")
            continue
        if state not in ("warning", "critical"):
            continue
        kind = s["kind"]
        if kind == "corrosion" and state == "critical":
            year = f" around {int(s['exhausted_year'])}" if s.get("exhausted_year") else ""
            add(state, f"Corrosion on {name} is on course to use up its {s['allowance']:.1f} mm allowance{year}, before the end of its design life. Commission an ultrasonic thickness survey to confirm, and price cathodic protection or a coating repair for the {labels(ZONES).get(element['zone'], element['zone']).lower()} zone.")
        elif kind == "corrosion":
            add(state, f"Corrosion on {name} is close to its design rate ({round(100 * s['ratio'])}% of the allowance by end of life). Move its thickness survey to every six months.")
        elif kind == "strain" and state == "critical":
            add(state, f"{s['label']} on {name} has passed its alarm strain ({s['alarm']:.0f} µε). Inspect {name} for berthing or overload damage, and check the recorded strains against Triton's design forces.")
        elif kind == "strain":
            add(state, f"{s['label']} on {name} is above its alert strain. Review the berthing log for the dates of the peaks.")
        elif kind in ("displacement", "tilt"):
            add(state, f"{name} has moved {s['current']} {s['unit']} since installation. Order a survey of the line and level of the {labels(ASSET_KINDS).get(asset['kind'], 'structure').lower()} around it.")
        elif kind == "chloride":
            when = f", and is on course to reach it around {int(s['limit_year'])}" if s.get("limit_year") and s["current"] < s["alarm"] else ""
            if state == "critical":
                add(state, f"Chloride at the reinforcement of {name} is {s['current']:.2f}% by mass of cement, past the {s['alarm']:.1f}% at which the bars start to corrode. Take cores to confirm, survey the bars with half-cell potentials, and price a concrete repair with impressed-current cathodic protection.")
            else:
                add(state, f"Chloride at the reinforcement of {name} is {s['current']:.2f}% by mass of cement against a {s['alarm']:.1f}% threshold{when}. A silane impregnation now keeps the chlorides out for a fraction of the cost of the repair later.")
        elif kind == "crack_width":
            add(state, f"Cracks on {name} have opened to {s['current']:.2f} mm (limit {s['alarm']:.1f} mm). Map them, look for rust staining, and seal them by resin injection{' now' if state == 'critical' else ' at the next maintenance visit'}.")
        elif kind == "half_cell":
            add(state, f"Half-cell potentials on {name} read {s['current']:.0f} mV (CSE): "
                       + ("more negative than −350 mV, a 90% probability of active reinforcement corrosion (ASTM C876). Break out at the worst readings, inspect the bars and plan a repair." if state == "critical"
                          else "in the uncertain band below −200 mV. Repeat the survey in six months and take a core at the most negative point."))
        elif kind in ("fender_reaction", "bollard_load") and s["recent_peak"] < s["alarm"] * 0.8:
            what = "rated reaction" if kind == "fender_reaction" else "rated capacity"
            add(state, f"{name} has gone over its {what} {s['exceedances']} time{'s' if s['exceedances'] > 1 else ''}, last on {s['last_exceeded']}, though recent loads are normal. "
                       f"Make sure it was inspected after each one; an overloaded {'fender' if kind == 'fender_reaction' else 'bollard'} can be damaged without it showing in the readings.")
        elif kind == "fender_reaction":
            add(state, f"{name} has taken {s['recent_peak']:,.0f} kN, {round(100 * s['recent_peak'] / s['alarm'])}% of its rated reaction of {s['alarm']:,.0f} kN ({s['limit_source']}). Inspect the rubber and panel for tears and the anchors for loosening, and review berthing speeds with the harbour master.")
        elif kind == "bollard_load":
            add(state, f"{name} has held {s['recent_peak']:,.1f} t against its {s['alarm']:,.0f} t rating ({s['limit_source']}). Check the bollard and its anchors for movement, and review the mooring arrangement that loaded it.")
        elif kind in ("rail_gauge", "rail_level"):
            which = "line" if kind == "rail_gauge" else "level"
            add(state, f"Crane rail {name} is {abs(s['current']):.1f} mm off its {which} (tolerance ±{s['alarm']:.0f} mm). Survey the rail and realign or re-shim it before it wears the crane wheels and breaks its clips.")
        elif kind == "inspection":
            grade = int(s["latest"])
            note = f" The inspector noted: “{s['note']}”." if s.get("note") else ""
            fix = _REPAIR.get(element["kind"]) or _REPAIR.get(element["material"], "repair it")
            add(state, f"The last inspection graded {name} {grade} of 5 ({dict(GRADES)[grade].lower()}).{note} "
                       f"{'Act now: ' if state == 'critical' else 'At the next maintenance visit, '}{fix}.")
    ur = condition.get("ur_at_life")
    if ur is not None and ur > 1:
        shown = "beyond its remaining section" if not math.isfinite(ur) else f"about {ur:.2f}"
        add("critical", f"With the projected section loss, {name}'s utilisation reaches {shown} by the end of its design life (Triton designed it at {condition['design_ur']:.2f}). Re-run {name} in Triton with the measured thickness.")
    out.sort(key=lambda r: -STATE_RANK[r["state"]])
    return out


def readings_for(conn: sqlite3.Connection, sensor_ids: Iterable[int]) -> dict[int, list[Any]]:
    ids = list(sensor_ids)
    found: dict[int, list[Any]] = {i: [] for i in ids}
    if not ids:
        return found
    marks = ",".join("?" * len(ids))
    for row in conn.execute(f"SELECT sensor_id, at, value, note FROM marine_readings WHERE sensor_id IN ({marks})"
                            " ORDER BY sensor_id, at", ids):
        found[row["sensor_id"]].append(row)
    return found


def assess_asset(conn: sqlite3.Connection, asset: Any, today: date | None = None) -> dict[str, Any]:
    """Everything the asset's page shows: each element, its sensors, the asset's health."""
    today = today or date.today()
    durability = marine_triton.durability(asset)
    ratings = marine_triton.ratings(asset)
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
        judged = [assess_sensor(s, readings[s["id"]], element, asset, allowance, life, today, ratings)
                  for s in by_element.get(element["id"], [])]
        from_triton = design.get(element["triton_element"] or element["name"])
        condition = assess_element(element, judged, asset, allowance, life, from_triton)
        todo = recommendations(element, condition, judged, asset)
        advice.extend(todo)
        out_elements.append({"element": dict(element), "sensors": judged, **condition, "advice": todo,
                             "furniture": element["kind"] in FURNITURE})

    scored = [e["health"] for e in out_elements if e["health"] is not None]
    state = max((e["state"] for e in out_elements), key=lambda s: STATE_RANK[s], default="neutral")
    advice.sort(key=lambda r: -STATE_RANK[r["state"]])
    groups = {}
    for name, test in (("Structure", lambda e: not e["furniture"]), ("Quay furniture", lambda e: e["furniture"])):
        members = [e for e in out_elements if test(e)]
        if members:
            groups[name] = {
                "count": len(members),
                "state": max((e["state"] for e in members), key=lambda s: STATE_RANK[s]),
                "acting": sum(1 for e in members if e["state"] == "critical"),
            }
    return {
        "elements": out_elements,
        "groups": groups,
        "health": round(sum(scored) / len(scored)) if scored else None,
        "state": state,
        "counts": {s: sum(1 for e in out_elements if e["state"] == s) for s in ("good", "warning", "critical", "neutral")},
        "sensors": len(sensors),
        "advice": advice,
        "durability": durability,
        "ratings": ratings,
        "triton_linked": bool(design),
        "today": today.isoformat(),
    }


# --- a demonstration asset -------------------------------------------------------------

def create_demo(conn: sqlite3.Connection, user_id: int | None, today: date | None = None) -> int:
    """A berth of tubular piles, a combi wall, a deck and its furniture, wired with simulated sensors.

    It exists so the twin can be seen working before a real asset is set up:
    eight years into a fifty-year life, some piles corroding faster than they
    were designed to, chlorides creeping into the cope beam, and a fender the
    last inspection found torn.
    """
    today = today or date.today()
    commissioned = date(today.year - 8, 3, 1).isoformat()
    asset_id = conn.execute(
        "INSERT INTO marine_assets (name, kind, location, client, commissioned, design_life, corrosion_code, created_by,"
        " terminal_type, latitude, longitude, rotation, msl_cd)"
        " VALUES (?, 'quay_wall', ?, ?, ?, 50, 'bs6349', ?, 'container', 6.43872, 3.38945, 0, 0.9)",
        ("Demo berth — Quay 1", "Apapa, Lagos (demonstration)", "Port authority (demo)", commissioned, user_id)).lastrowid

    def element(name, kind, material, zone, x, y, z, wall=None, ur=None):
        return conn.execute(
            "INSERT INTO marine_elements (asset_id, name, kind, material, zone, wall_mm, design_ur, model_ref, x, y, z)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (asset_id, name, kind, material, zone, wall, ur, name, x, y, z)).lastrowid

    def sensors(element_id, name, kinds):
        for kind in kinds:
            spec = SENSOR_KINDS[kind]
            conn.execute("INSERT INTO marine_sensors (element_id, kind, label, alert, alarm, simulated)"
                         " VALUES (?, ?, ?, ?, ?, 1)",
                         (element_id, kind, f"{name}-{spec['tag']}1", spec["alert"], spec["alarm"]))

    urs = [0.71, 0.78, 0.84, 0.88, 0.80, 0.74]
    for i, ur in enumerate(urs):
        name = f"P{i + 1:02d}"
        sensors(element(name, "pile", "steel", "splash", i * 8.0, 0.0, 0.0, wall=16.0, ur=ur), name,
                ["corrosion", "strain"])
    for i in range(3):
        name = f"CW{i + 1}"
        sensors(element(name, "combi_wall", "steel", "tidal", 4.0 + i * 14.0, -6.0, 0.0, wall=20.0, ur=0.82), name,
                ["corrosion", "displacement"])
    sensors(element("DECK", "slab", "concrete", "atmospheric", 20.0, -3.0, 3.5, ur=0.66), "DECK",
            ["tilt", "crack_width", "chloride"])
    sensors(element("COPE", "beam", "concrete", "splash", 20.0, 0.5, 3.0, ur=0.72), "COPE",
            ["chloride", "crack_width", "half_cell"])
    for i in range(3):
        name = f"F{i + 1}"
        sensors(element(name, "fender", "rubber", "splash", 4.0 + i * 16.0, 1.2, 2.2), name, ["fender_reaction"])
    for i in range(3):
        name = f"BOL{i + 1}"
        sensors(element(name, "bollard", "steel", "atmospheric", 8.0 + i * 16.0, -0.8, 4.2), name,
                ["bollard_load", "inspection"])
    sensors(element("RAIL-SEA", "crane_rail", "steel", "atmospheric", 20.0, -2.0, 4.0), "RAIL-SEA",
            ["rail_gauge", "rail_level"])
    element("LAD1", "ladder", "steel", "splash", 12.0, 0.9, 1.0)
    refresh_simulated(conn, asset_id, today)

    # The inspection record a real asset would have: typed in, not simulated.
    fenders = {r["name"]: r for r in conn.execute(
        "SELECT * FROM marine_elements WHERE asset_id = ? AND kind IN ('fender', 'ladder')", (asset_id,))}
    year = today.year
    for name, history in {
        "F1": [(f"{year - 3}-04-10", 1, ""), (f"{year - 1}-04-12", 2, "Light abrasion on the panel pads")],
        "F2": [(f"{year - 3}-04-10", 1, ""), (f"{year - 2}-04-15", 2, "Panel pads worn"),
               (f"{year - 1}-04-12", 3, "Split starting at the lower flange of the cone"),
               ((today - timedelta(days=40)).isoformat(), 4, "Cone torn through at the lower flange; two panel pads missing")],
        "F3": [(f"{year - 1}-04-12", 1, "")],
        "LAD1": [(f"{year - 1}-04-12", 3, "Two rungs bent below LAT, heavy marine growth")],
    }.items():
        for at, grade, note in history:
            record_inspection(conn, fenders[name], at, grade, note)
    return asset_id
