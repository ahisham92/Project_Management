"""MarineTwin's seabed surveys: the depth in front of the quay, survey by survey.

A multibeam (or single-beam) survey of the berth pocket comes as an XYZ file: a point per line,
its position and its depth. Each survey is gridded into cells (2.5 m by default) in the model's
own frame, so surveys made on different grids or in latitude and longitude still line up. For
each the page gives the area covered, the shallowest and the mean level, and what stands above
the design dredge level (the shoals, and their volume to dredge). Two surveys together give
what changed between them: the silt that came in, what went out (dredged or scoured), and the
siltation rate a year, which the Lifecycle runs on in place of the typical figure.

Levels are kept in metres above chart datum (so a dredged pocket is about -16). A file of depths
(positive down) is turned into levels; one on mean sea level is moved onto chart datum with the
asset's MSL above CD.
"""

from __future__ import annotations

import io
import math
import random
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from . import marine, marine_ifc

CELL_M = 2.5
MAX_POINTS = 6_000_000
MAX_CELLS = 4_000_000            # a grid of 5 km x 2 km at 2.5 m: anything bigger is a wrong frame
# A cell that got deeper by more than this between two surveys was dredged (or scoured), not silted:
# it is left out of the siltation rate.
DREDGED_M = 0.3

SCHEMA = """
CREATE TABLE IF NOT EXISTS marine_surveys (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  surveyed        TEXT NOT NULL,                    -- YYYY-MM-DD
  points          INTEGER NOT NULL DEFAULT 0,       -- soundings read
  cell            REAL NOT NULL DEFAULT 2.5,        -- m
  x0              REAL NOT NULL,                    -- the grid's corner in the model frame, m
  y0              REAL NOT NULL,
  nx              INTEGER NOT NULL,
  ny              INTEGER NOT NULL,
  file            TEXT NOT NULL,                    -- the gridded levels, kept beside the models
  source          TEXT NOT NULL DEFAULT '',         -- the file it came from
  frame           TEXT NOT NULL DEFAULT '',         -- model | grid | latlon, as read
  created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

FRAMES = [("auto", "Work it out"), ("model", "x, y in the model's frame"), ("grid", "Easting, northing on the map grid"),
          ("latlon", "Latitude, longitude")]
ZS = [("auto", "Work it out"), ("depth", "Depths, positive down"), ("level", "Levels, negative below the datum")]
DATUMS = [("cd", "Chart datum"), ("msl", "Mean sea level")]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


# --- reading ---------------------------------------------------------------------------------

def read_xyz(data: bytes) -> np.ndarray:
    """The soundings of an XYZ file as an (n, 3) array: comma, semicolon, tab or space separated, a header line or not."""
    import pandas as pd
    text = data.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()
    first = next((ln for ln in lines if ln.strip() and not ln.lstrip().startswith("#")), "")
    sep = "," if "," in first else ";" if ";" in first else r"\s+"
    head = 0
    try:
        [float(v) for v in (first.split(",") if sep == "," else first.split(";") if sep == ";" else first.split())[:3]]
    except ValueError:
        head = 1                                      # a header line
    frame = pd.read_csv(io.StringIO(text), sep=sep, header=None, skiprows=head, comment="#", usecols=[0, 1, 2],
                        nrows=MAX_POINTS, engine="c", on_bad_lines="skip", dtype=str)
    arr = frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    return arr[np.isfinite(arr).all(axis=1)]


def guess_frame(pts: np.ndarray, asset: Any) -> str:
    x, y = np.median(pts[:, 0]), np.median(pts[:, 1])
    if abs(x) > 100_000 or abs(y) > 100_000:
        return "grid"
    if asset is not None and asset["latitude"] is not None and abs(y - asset["latitude"]) < 1 and abs(x - asset["longitude"]) < 1:
        return "lonlat"
    if asset is not None and asset["latitude"] is not None and abs(x - asset["latitude"]) < 1 and abs(y - asset["longitude"]) < 1:
        return "latlon"
    return "model"


def _inverse(asset: Any, de: np.ndarray, dn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    theta = math.radians(asset["rotation"] or 0.0)
    return de * math.cos(theta) + dn * math.sin(theta), -de * math.sin(theta) + dn * math.cos(theta)


def _from_latlon(asset: Any, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lat0, lon0 = asset["latitude"], asset["longitude"]
    dn = (lat - lat0) * 111_320.0
    de = (lon - lon0) * 111_320.0 * max(math.cos(math.radians(lat0)), 1e-6)
    return _inverse(asset, de, dn)


def to_model(pts: np.ndarray, frame: str, asset: Any, site: dict[str, Any] | None, cell: float) -> tuple[np.ndarray, str]:
    """The soundings in the model frame (x, y, z). Grid positions are first binned at half a cell, so a
    survey of millions of points is turned with a few thousand conversions."""
    frame = guess_frame(pts, asset) if frame == "auto" else frame
    if frame == "model":
        return pts, "model"
    if asset is None or asset["latitude"] is None:
        raise ValueError("Set the asset's location (Set up) to read a survey on the map grid or in latitude and longitude.")
    if frame in ("latlon", "lonlat"):
        lat, lon = (pts[:, 0], pts[:, 1]) if frame == "latlon" else (pts[:, 1], pts[:, 0])
        x, y = _from_latlon(asset, lat, lon)
        return np.column_stack([x, y, pts[:, 2]]), "latlon"
    # The map grid: by the model's map conversion when it has one, else through latitude and longitude on its UTM zone.
    if site and site.get("eastings") and abs(float(site["eastings"])) > 1:
        x, y = _inverse(asset, pts[:, 0] - site["eastings"], pts[:, 1] - (site.get("northings") or 0.0))
        return np.column_stack([x, y, pts[:, 2]]), "grid"
    zone = marine_ifc._epsg_utm(asset["epsg"] or (site or {}).get("epsg") or "")
    if not zone:
        raise ValueError("The model does not say which map grid it is on: give the survey in latitude and longitude, "
                         "or in the model's x and y.")
    half = cell / 2
    keys = np.floor(pts[:, :2] / half).astype(np.int64)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    centres = (uniq + 0.5) * half
    ll = np.array([marine_ifc.utm_to_latlon(e, n, zone[0], zone[1]) for e, n in centres])
    cx, cy = _from_latlon(asset, ll[:, 0], ll[:, 1])
    # Each sounding keeps its offset within its little bin, so nothing is lost but the earth's curve within half a cell.
    theta = math.radians(asset["rotation"] or 0.0)
    oe, on = pts[:, 0] - centres[inv, 0], pts[:, 1] - centres[inv, 1]
    ox, oy = oe * math.cos(theta) + on * math.sin(theta), -oe * math.sin(theta) + on * math.cos(theta)
    return np.column_stack([cx[inv] + ox, cy[inv] + oy, pts[:, 2]]), "grid"


def to_levels(z: np.ndarray, kind: str, datum: str, msl_cd: float) -> np.ndarray:
    if kind == "auto":
        kind = "depth" if np.median(z) > 0 else "level"
    level = -z if kind == "depth" else z
    return level + (msl_cd or 0.0) if datum == "msl" else level


def grid(pts: np.ndarray, cell: float = CELL_M) -> dict[str, Any]:
    """The soundings averaged into cells: the corner, the size and the levels (NaN where none fell)."""
    x0 = math.floor(float(pts[:, 0].min()) / cell) * cell
    y0 = math.floor(float(pts[:, 1].min()) / cell) * cell
    ix = np.floor((pts[:, 0] - x0) / cell).astype(np.int64)
    iy = np.floor((pts[:, 1] - y0) / cell).astype(np.int64)
    nx, ny = int(ix.max()) + 1, int(iy.max()) + 1
    if nx * ny > MAX_CELLS:
        raise ValueError(f"The survey spans {nx * cell:,.0f} by {ny * cell:,.0f} m: too big for one berth. "
                         "Is the position in the frame chosen?")
    flat = iy * nx + ix
    total = np.bincount(flat, weights=pts[:, 2], minlength=nx * ny)
    count = np.bincount(flat, minlength=nx * ny)
    with np.errstate(invalid="ignore", divide="ignore"):
        levels = np.where(count > 0, total / np.maximum(count, 1), np.nan).reshape(ny, nx).astype(np.float32)
    return {"x0": x0, "y0": y0, "nx": nx, "ny": ny, "cell": cell, "levels": levels}


def save(conn: sqlite3.Connection, folder: Path, asset_id: int, name: str, surveyed: str, g: dict[str, Any], points: int,
         source: str, frame: str, user_id: int | None) -> int:
    survey_id = conn.execute(
        "INSERT INTO marine_surveys (asset_id, name, surveyed, points, cell, x0, y0, nx, ny, file, source, frame, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?)",
        (asset_id, name, surveyed, points, g["cell"], g["x0"], g["y0"], g["nx"], g["ny"], source, frame, user_id)).lastrowid
    stored = f"asset-{asset_id}-survey-{survey_id}.npz"
    folder.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(folder / stored, levels=g["levels"])
    conn.execute("UPDATE marine_surveys SET file = ? WHERE id = ?", (stored, survey_id))
    return survey_id


def load(folder: Path, row: Any) -> dict[str, Any] | None:
    try:
        with np.load(folder / row["file"]) as f:
            levels = f["levels"]
    except (OSError, ValueError, KeyError):
        return None
    return {"x0": row["x0"], "y0": row["y0"], "nx": row["nx"], "ny": row["ny"], "cell": row["cell"], "levels": levels}


# --- what they show --------------------------------------------------------------------------

def summary(g: dict[str, Any], design: float) -> dict[str, Any]:
    lv = g["levels"]
    have = np.isfinite(lv)
    area = float(have.sum()) * g["cell"] ** 2
    if not have.any():
        return {"area": 0.0, "cells": 0}
    vals = lv[have]
    above = np.clip(vals - design, 0, None)
    return {"area": area, "cells": int(have.sum()), "shallowest": float(vals.max()), "deepest": float(vals.min()),
            "mean": float(vals.mean()), "shoal_area": float((above > 0).sum()) * g["cell"] ** 2,
            "shoal_m3": float(above.sum()) * g["cell"] ** 2, "worst_above": float(above.max())}


def _on(g: dict[str, Any], x0: float, y0: float, nx: int, ny: int, cell: float) -> np.ndarray:
    """A survey's levels on another grid of the same cell size (cells that do not line up are taken nearest)."""
    out = np.full((ny, nx), np.nan, dtype=np.float32)
    ox = int(round((g["x0"] - x0) / cell))
    oy = int(round((g["y0"] - y0) / cell))
    src = g["levels"]
    xs, xe = max(0, ox), min(nx, ox + g["nx"])
    ys, ye = max(0, oy), min(ny, oy + g["ny"])
    if xs < xe and ys < ye:
        out[ys:ye, xs:xe] = src[ys - oy:ye - oy, xs - ox:xe - ox]
    return out


def compare(old: dict[str, Any], new: dict[str, Any], years: float) -> dict[str, Any]:
    """What changed from one survey to the next, on the newer survey's grid."""
    cell = new["cell"]
    before = _on(old, new["x0"], new["y0"], new["nx"], new["ny"], cell) if old["cell"] == cell else None
    if before is None:
        return {"common": 0}
    change = new["levels"] - before
    both = np.isfinite(change)
    if not both.any():
        return {"common": 0, "change": change}
    d = change[both]
    silted = d[d >= -DREDGED_M]
    a = cell ** 2
    return {
        "common": int(both.sum()), "area": float(both.sum()) * a, "change": change,
        "in_m3": float(np.clip(d, 0, None).sum()) * a, "out_m3": float(np.clip(-d, 0, None).sum()) * a,
        "net_m3": float(d.sum()) * a, "mean": float(d.mean()), "years": years,
        "dredged_area": float((d < -DREDGED_M).sum()) * a,
        "rate": float(silted.mean()) / years if years > 0 and silted.size else None,
    }


# --- pictures --------------------------------------------------------------------------------

def _ramp(t: np.ndarray, stops: list[tuple[float, tuple[int, int, int]]]) -> np.ndarray:
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    xs = [s[0] for s in stops]
    for c in range(3):
        out[..., c] = np.interp(t, xs, [s[1][c] for s in stops])
    return out


def picture(values: np.ndarray, mode: str, design: float | None = None, marks: list[tuple[int, int]] | None = None,
            scale: int | None = None) -> bytes:
    """A plan of the levels (against the design level) or of the change, as a PNG: north of the grid up."""
    from PIL import Image
    ny, nx = values.shape
    have = np.isfinite(values)
    if mode == "levels":
        rel = np.where(have, values - (design or 0.0), 0.0)
        # Deeper than the design: blues, darker the deeper; above it (a shoal): yellow to red.
        t = np.clip(rel, -4, 2)
        rgb = _ramp(t, [(-4, (8, 48, 107)), (-1.5, (49, 130, 189)), (-0.01, (189, 215, 231)), (0.0, (254, 217, 118)),
                        (0.5, (253, 141, 60)), (2, (189, 0, 38))])
    else:
        t = np.clip(np.where(have, values, 0.0), -1.5, 1.5)
        rgb = _ramp(t, [(-1.5, (33, 102, 172)), (-0.05, (209, 229, 240)), (0.05, (247, 247, 247)), (0.05001, (253, 219, 199)),
                        (1.5, (140, 81, 10))])
    img = np.where(have[..., None], rgb, 245).astype(np.uint8)
    for (mx, my) in marks or []:
        if 0 <= mx < nx and 0 <= my < ny:
            img[my, mx] = (20, 20, 20)
    img = img[::-1]                                    # rows run south to north in the grid; images top down
    k = scale or max(1, min(10, int(900 / max(nx, ny, 1))))
    pic = Image.fromarray(img, "RGB")
    if k > 1:
        pic = pic.resize((nx * k, ny * k), Image.NEAREST)
    out = io.BytesIO()
    pic.save(out, "PNG", optimize=True)
    return out.getvalue()


def framed(g: dict[str, Any], points: list[tuple[float, float]], margin: float = 5.0) -> dict[str, Any]:
    """The grid widened (with empty cells) to take in the structure as well, so the picture shows the quay."""
    if not points:
        return g
    cell = g["cell"]
    xs = [p[0] for p in points] + [g["x0"], g["x0"] + g["nx"] * cell]
    ys = [p[1] for p in points] + [g["y0"], g["y0"] + g["ny"] * cell]
    x0 = math.floor((min(xs) - margin - g["x0"]) / cell) * cell + g["x0"]
    y0 = math.floor((min(ys) - margin - g["y0"]) / cell) * cell + g["y0"]
    nx = int(math.ceil((max(xs) + margin - x0) / cell))
    ny = int(math.ceil((max(ys) + margin - y0) / cell))
    if nx * ny > MAX_CELLS or nx > 4 * g["nx"] + 200 or ny > 4 * g["ny"] + 200:
        return g                                      # the structure is far off the survey: show the survey alone
    return {"x0": x0, "y0": y0, "nx": nx, "ny": ny, "cell": cell, "levels": _on(g, x0, y0, nx, ny, cell)}


def marks_for(points: list[tuple[float, float]], g: dict[str, Any]) -> list[tuple[int, int]]:
    """The structure's elements as cells of the grid, to show where the quay is."""
    out = []
    for x, y in points:
        out.append((int((x - g["x0"]) // g["cell"]), int((y - g["y0"]) // g["cell"])))
    return out


# --- the design level and a made-up pair to try ------------------------------------------

def design_level(asset: Any, berth_rows: list[dict[str, Any]]) -> float:
    """The pocket's design level, mCD: the asset's own, else the deepest berth's declared depth."""
    if asset["dredge_level"] is not None:
        return float(asset["dredge_level"])
    depths = [float(b["depth"]) for b in berth_rows if b.get("depth")]
    return -max(depths) if depths else -14.0


def sea_side(elements: list[dict[str, Any]]) -> tuple[float, float]:
    """Which way the sea is in the model frame: across the quay's long axis, towards the fenders; else +y."""
    if len(elements) < 2:
        return 0.0, 1.0
    pts = np.array([[e["x"], e["y"]] for e in elements], dtype=float)
    centre = pts.mean(axis=0)
    _, _, axes = np.linalg.svd(pts - centre)
    along = axes[0]
    normal = np.array([-along[1], along[0]])
    front = [e for e in elements if e["kind"] in ("fender", "ladder")]
    if front:
        f = np.array([[e["x"], e["y"]] for e in front]).mean(axis=0) - centre
        if float(f @ normal) < 0:
            normal = -normal
    elif normal[1] < 0:
        normal = -normal
    return float(normal[0]), float(normal[1])


def demo_pair(elements: list[dict[str, Any]], design: float, today: date | None = None) -> list[tuple[str, np.ndarray]]:
    """Two made-up surveys of the pocket a year apart: dredged to the design level, then silting near the wall."""
    today = today or date.today()
    rng = random.Random(11)
    xs = [e["x"] for e in elements] or [0.0]
    ys = [e["y"] for e in elements] or [0.0]
    sx, sy = sea_side(elements)
    ux, uy = -sy, sx                                   # along the quay
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    along = [(x - cx) * ux + (y - cy) * uy for x, y in zip(xs, ys)]
    front = max(((x - cx) * sx + (y - cy) * sy for x, y in zip(xs, ys)), default=0.0)
    a0, a1 = min(along) - 20, max(along) + 20
    out = []
    for k, when in enumerate([date(today.year - 1, today.month, min(today.day, 28)), today]):
        pts = []
        a = a0
        while a <= a1:
            c = 2.0
            while c <= 70:
                x = cx + ux * a + sx * (front + c)
                y = cy + uy * a + sy * (front + c)
                base = design - 0.4 - 0.01 * c + 0.15 * math.sin(a / 23)
                silt = k * (0.55 * math.exp(-c / 25) + 0.12 + 0.05 * math.sin(a / 11))
                if k and 0.35 < (a - a0) / max(a1 - a0, 1) < 0.5 and c < 25:
                    silt += 0.45                          # a shoal off one stretch
                pts.append((x + rng.uniform(-0.4, 0.4), y + rng.uniform(-0.4, 0.4), -(base + silt) + rng.gauss(0, 0.04)))
                c += 1.0
            a += 1.0
        out.append((when.isoformat(), np.array(pts)))
    return out
