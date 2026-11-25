"""MarineTwin's pile tracker: the piles as built against the piles as designed.

The piling contractor's as-built record (a CSV of each pile's name, where its head ended up, its
cut-off and toe levels and the day it went in) is laid over the design, which is every pile in
the Revit model (or, with no model read, the piles MarineTwin tracks). For each design pile it
says whether it is in, and how far it is from where it should be against the tolerance; for the
quay, how many are in, how fast they are going in and when, at that rate, the last one will be.

Positions are worked in the model's own frame: metres along its x and y from the site's origin,
as the 3D view and the map use them. The as-built record can give them that way (x, y), on the
project's map grid (easting, northing, when the model carries its map conversion) or as latitude
and longitude.
"""

from __future__ import annotations

import csv
import io
import math
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from . import marine

# What counts as a pile: one position each. Sheet piles run as walls and are left out.
PILE_KINDS = ("pile", "combi_wall")
# How far, in metres, an as-built pile with a name the design does not know may be from a design
# pile and still be taken as that pile.
NEAREST_M = 3.0
# Two design piles closer than this are one pile drawn twice (a king pile and its concrete fill).
SAME_SPOT_M = 0.3
# The usual tolerance on a pile's position at cut-off for marine piling (ICE SPERW and most
# port specifications give 75 mm on land and 100 to 150 mm over water). The person sets their own.
TOLERANCE_MM = 150
MAX_ROWS = 20000

SCHEMA = """
CREATE TABLE IF NOT EXISTS marine_piles (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,                    -- as the contractor's record names it
  design          TEXT NOT NULL DEFAULT '',         -- the design pile it was taken as; blank: none
  x               REAL NOT NULL,                    -- the head as built, model frame, m
  y               REAL NOT NULL,
  level           REAL,                             -- cut-off level as built, mCD
  toe             REAL,                             -- toe level reached, mCD
  installed       TEXT,                             -- YYYY-MM-DD
  note            TEXT NOT NULL DEFAULT '',
  source          TEXT NOT NULL DEFAULT '',         -- the file it came from
  added_at        TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (asset_id, name)
);
"""

ALIASES = {
    "name": "name", "pile": "name", "pile name": "name", "pile id": "name", "id": "name", "mark": "name", "tag": "name",
    "x": "x", "y": "y", "easting": "e", "east": "e", "e": "e", "northing": "n", "north": "n", "n": "n",
    "lat": "lat", "latitude": "lat", "lon": "lon", "lng": "lon", "long": "lon", "longitude": "lon",
    "level": "level", "cut-off": "level", "cut off": "level", "cutoff": "level", "cut-off level": "level", "top": "level",
    "head level": "level", "z": "level", "toe": "toe", "toe level": "toe", "date": "installed", "installed": "installed",
    "date installed": "installed", "driven": "installed", "note": "note", "notes": "note", "remarks": "note",
}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


# --- where a position is --------------------------------------------------------------------

def to_model(asset: Any, site: dict[str, Any] | None, row: dict[str, Any]) -> tuple[float, float] | None:
    """The model-frame position a row gives, whichever way it gives it."""
    if row.get("x") is not None and row.get("y") is not None:
        return row["x"], row["y"]
    theta = math.radians((asset["rotation"] if asset is not None else 0.0) or 0.0)
    de = dn = None
    if row.get("e") is not None and row.get("n") is not None and site and site.get("eastings") is not None:
        de, dn = row["e"] - site["eastings"], row["n"] - (site.get("northings") or 0.0)
    elif row.get("lat") is not None and row.get("lon") is not None and asset is not None and asset["latitude"] is not None:
        lat0, lon0 = asset["latitude"], asset["longitude"]
        dn = (row["lat"] - lat0) * 111_320.0
        de = (row["lon"] - lon0) * 111_320.0 * max(math.cos(math.radians(lat0)), 1e-6)
    if de is None:
        return None
    # The inverse of marine.geolocate's turn.
    return de * math.cos(theta) + dn * math.sin(theta), -de * math.sin(theta) + dn * math.cos(theta)


def _num(text: Any) -> float | None:
    try:
        value = float(str(text).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _date(text: Any) -> str | None:
    text = str(text or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def read_csv(text: str, asset: Any, site: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[str]]:
    """The as-built piles a CSV gives, and why any row was skipped."""
    reader = csv.DictReader(io.StringIO(text))
    good: list[dict[str, Any]] = []
    bad: list[str] = []
    for i, raw in enumerate(reader, start=2):
        row: dict[str, Any] = {}
        for k, v in raw.items():
            key = ALIASES.get((k or "").strip().lower())
            if key and key not in row:
                row[key] = v
        name = str(row.get("name") or "").strip()
        if not name:
            bad.append(f"Row {i}: no pile name.")
            continue
        for k in ("x", "y", "e", "n", "lat", "lon", "level", "toe"):
            row[k] = _num(row.get(k)) if row.get(k) not in (None, "") else None
        at = to_model(asset, site, row)
        if at is None:
            bad.append(f"Row {i} ({name}): no position. Give x and y in the model's frame, easting and northing"
                       " (when the model carries its map grid), or latitude and longitude.")
            continue
        good.append({"name": name[:80], "x": round(at[0], 4), "y": round(at[1], 4), "level": row["level"], "toe": row["toe"],
                     "installed": _date(row.get("installed")), "note": str(row.get("note") or "").strip()[:300]})
        if len(good) >= MAX_ROWS:
            break
    return good, bad


# --- the design ------------------------------------------------------------------------------

def design_piles(found: dict[str, Any] | None, elements: Iterable[Any]) -> list[dict[str, Any]]:
    """Every pile of the design: from the model read when there is one, else the tracked ones."""
    out: dict[str, dict[str, Any]] = {}
    for e in (found or {}).get("elements", []):
        if e.get("kind") in PILE_KINDS:
            out[e["name"]] = {"name": e["name"], "kind": e["kind"], "group": e.get("group") or e.get("legend") or "",
                              "material": str(e.get("material") or ""),
                              "x": float((e.get("body") or [e.get("x") or 0])[0]), "y": float((e.get("body") or [0, e.get("y") or 0])[1]),
                              "z": e.get("z")}
    if out:
        # A king pile and the concrete filling it are two objects in Revit but one pile on site:
        # where two sit on one spot, the steel one is kept.
        keep: dict[tuple[int, int], list[dict[str, Any]]] = {}
        order = sorted(out.values(), key=lambda p: (p["material"] != "steel", "FKC" in p["group"].upper(), p["name"]))
        for p in order:
            cell = (int(math.floor(p["x"] / SAME_SPOT_M)), int(math.floor(p["y"] / SAME_SPOT_M)))
            near = [q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in keep.get((cell[0] + dx, cell[1] + dy), [])]
            if any(math.hypot(q["x"] - p["x"], q["y"] - p["y"]) < SAME_SPOT_M for q in near):
                del out[p["name"]]
                continue
            keep.setdefault(cell, []).append(p)
    if not out:
        for e in elements:
            e = dict(e)
            if e["kind"] in PILE_KINDS:
                out[e["name"]] = {"name": e["name"], "kind": e["kind"], "group": e.get("design_group") or "",
                                  "x": float(e["x"] or 0), "y": float(e["y"] or 0), "z": e["z"]}
    return sorted(out.values(), key=lambda p: (p["x"], p["y"], p["name"]))


def match(design: list[dict[str, Any]], built: list[dict[str, Any]]) -> dict[str, str]:
    """Which design pile each as-built pile is: by name, else the nearest free one within NEAREST_M."""
    names = {p["name"]: p for p in design}
    taken: dict[str, str] = {}
    out: dict[str, str] = {}
    for b in built:
        if b["name"] in names and b["name"] not in taken:
            out[b["name"]] = b["name"]
            taken[b["name"]] = b["name"]
    grid: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for p in design:
        grid.setdefault((int(math.floor(p["x"] / NEAREST_M)), int(math.floor(p["y"] / NEAREST_M))), []).append(p)
    for b in built:
        if b["name"] in out:
            continue
        best, gap = None, NEAREST_M
        cx, cy = int(math.floor(b["x"] / NEAREST_M)), int(math.floor(b["y"] / NEAREST_M))
        for p in (q for dx in (-1, 0, 1) for dy in (-1, 0, 1) for q in grid.get((cx + dx, cy + dy), [])):
            if p["name"] in taken:
                continue
            d = math.hypot(p["x"] - b["x"], p["y"] - b["y"])
            if d <= gap:
                best, gap = p["name"], d
        if best:
            out[b["name"]] = best
            taken[best] = b["name"]
    return out


def save(conn: sqlite3.Connection, asset_id: int, rows: list[dict[str, Any]], design: list[dict[str, Any]], source: str,
         replace: bool = False) -> dict[str, int]:
    """Keep the as-built piles (a pile already there is replaced by the newer record)."""
    if replace:
        conn.execute("DELETE FROM marine_piles WHERE asset_id = ?", (asset_id,))
    kept = [dict(r) for r in conn.execute("SELECT name, x, y FROM marine_piles WHERE asset_id = ?", (asset_id,))]
    names = {r["name"] for r in rows}
    allb = [r for r in kept if r["name"] not in names] + rows
    which = match(design, allb)
    new = updated = 0
    for r in rows:
        exists = conn.execute("SELECT 1 FROM marine_piles WHERE asset_id = ? AND name = ?", (asset_id, r["name"])).fetchone()
        conn.execute(
            "INSERT INTO marine_piles (asset_id, name, design, x, y, level, toe, installed, note, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (asset_id, name) DO UPDATE SET design = excluded.design, x = excluded.x, y = excluded.y,"
            " level = excluded.level, toe = excluded.toe, installed = excluded.installed, note = excluded.note,"
            " source = excluded.source, added_at = datetime('now')",
            (asset_id, r["name"], which.get(r["name"], ""), r["x"], r["y"], r["level"], r["toe"], r["installed"], r["note"], source))
        updated += bool(exists)
        new += not exists
    # A newer record may have moved which design pile the older ones are taken as.
    for name, d in which.items():
        conn.execute("UPDATE marine_piles SET design = ? WHERE asset_id = ? AND name = ?", (d, asset_id, name))
    return {"new": new, "updated": updated, "matched": sum(1 for r in rows if which.get(r["name"]))}


# --- what it shows ---------------------------------------------------------------------------

def assess(design: list[dict[str, Any]], built: Iterable[Any], tolerance_mm: float = TOLERANCE_MM,
           today: date | None = None) -> dict[str, Any]:
    """Each design pile in, out of position or still to go; the counts, the rate and the finish."""
    today = today or date.today()
    tol = max(float(tolerance_mm or TOLERANCE_MM), 1.0)
    built = [dict(b) for b in built]
    by_design = {b["design"]: b for b in built if b.get("design")}
    piles = []
    for p in design:
        b = by_design.get(p["name"])
        row = {**p, "state": "todo", "built": None, "dev_mm": None, "dx_mm": None, "dy_mm": None}
        if b:
            dx, dy = (b["x"] - p["x"]) * 1000, (b["y"] - p["y"]) * 1000
            dev = math.hypot(dx, dy)
            row.update(built=b, dev_mm=round(dev), dx_mm=round(dx), dy_mm=round(dy),
                       state="good" if dev <= tol else "warning" if dev <= 2 * tol else "critical")
        piles.append(row)
    extra = [b for b in built if not b.get("design")]
    done = sum(1 for p in piles if p["built"])
    total = len(piles)
    groups: dict[str, dict[str, Any]] = {}
    for p in piles:
        g = groups.setdefault(p["group"] or p["kind"].replace("_", " "), {"name": p["group"] or p["kind"].replace("_", " "),
                                                                          "total": 0, "done": 0, "over": 0})
        g["total"] += 1
        g["done"] += bool(p["built"])
        g["over"] += p["state"] in ("warning", "critical")
    # The rate: piles a week over the last four weeks with dates, and the finish at that rate.
    dates = sorted(date.fromisoformat(b["installed"]) for b in built if b.get("installed"))
    recent = [d for d in dates if d > (dates[-1] - timedelta(days=28))] if dates else []
    per_week = len(recent) / 4 if recent else None
    finish = None
    if per_week and total > done:
        finish = (max(today, dates[-1]) + timedelta(days=math.ceil((total - done) / per_week * 7))).isoformat()
    weeks: list[tuple[str, int]] = []
    if dates:
        start = dates[0] - timedelta(days=dates[0].weekday())
        n, i = 0, 0
        while start <= dates[-1]:
            end = start + timedelta(days=7)
            while i < len(dates) and dates[i] < end:
                n, i = n + 1, i + 1
            weeks.append((start.isoformat(), n))
            start = end
    devs = [p["dev_mm"] for p in piles if p["dev_mm"] is not None]
    return {
        "piles": piles, "extra": extra, "groups": sorted(groups.values(), key=lambda g: g["name"]),
        "total": total, "done": done, "pct": round(100 * done / total, 1) if total else 0.0,
        "within": sum(1 for p in piles if p["state"] == "good"),
        "over": sum(1 for p in piles if p["state"] in ("warning", "critical")),
        "worst": max(devs) if devs else None, "mean": round(sum(devs) / len(devs)) if devs else None,
        "per_week": per_week, "finish": finish, "weeks": weeks, "tolerance": tol,
        "first": dates[0].isoformat() if dates else None, "last": dates[-1].isoformat() if dates else None,
    }


def map_points(asset: Any, result: dict[str, Any]) -> list[dict[str, Any]]:
    """The piles for the map: design where none is in yet, as built where it is."""
    out = []
    for p in result["piles"]:
        b = p["built"]
        at = marine.geolocate(asset, b["x"], b["y"]) if b else marine.geolocate(asset, p["x"], p["y"])
        if at:
            out.append({"name": p["name"], "lat": at[0], "lon": at[1], "state": p["state"],
                        "kind": "pile", "dev": p["dev_mm"]})
    for b in result["extra"]:
        at = marine.geolocate(asset, b["x"], b["y"])
        if at:
            out.append({"name": b["name"], "lat": at[0], "lon": at[1], "state": "extra", "kind": "pile", "dev": None})
    return out


def template_csv(design: list[dict[str, Any]]) -> str:
    """The design piles as a sheet for the contractor to fill in: their design position, then as built."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["name", "design_x", "design_y", "x", "y", "level", "toe", "installed", "note"])
    for p in design:
        w.writerow([p["name"], f"{p['x']:.3f}", f"{p['y']:.3f}", "", "", "", "", "", ""])
    return out.getvalue()


def demo_record(design: list[dict[str, Any]], today: date | None = None, share: float = 0.7) -> list[dict[str, Any]]:
    """A made-up record for the demonstration: most piles in, a few off position, one a week."""
    import random
    today = today or date.today()
    rng = random.Random(7)
    n = max(1, int(len(design) * share))
    out = []
    for i, p in enumerate(design[:n]):
        spread = 0.06 if rng.random() > 0.15 else 0.22
        out.append({"name": p["name"], "x": round(p["x"] + rng.gauss(0, spread), 4), "y": round(p["y"] + rng.gauss(0, spread), 4),
                    "level": round((p["z"] or 0) + rng.uniform(-0.03, 0.03), 3) if p.get("z") is not None else None,
                    "toe": round(-24 - rng.uniform(0, 2), 2), "note": "",
                    "installed": (today - timedelta(days=(n - i) * 3)).isoformat()})
    return out
