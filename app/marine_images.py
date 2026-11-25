"""MarineTwin's site images: drone orthophotos of the site, dated, laid on the map.

A drone survey's orthophoto comes as a GeoTIFF (it says where it is), or as a JPEG or PNG with a
world file beside it (.jgw, .pgw, .tfw), or as a plain picture whose corners are typed in. It is
kept at a size a browser shows quickly, with its bounds in latitude and longitude, so the site
record can show the site on any date and swipe between two dates.

Positions are read in WGS 84 (EPSG:4326), Web Mercator (EPSG:3857) or WGS 84 UTM (EPSG:326xx and
327xx). A UTM image is laid on the map by its corners: north on the grid is a fraction of a degree
off true north away from the zone's middle, which is less than a pixel across a berth.
"""

from __future__ import annotations

import io
import math
import sqlite3
from pathlib import Path
from typing import Any

from . import marine, marine_ifc

KINDS = [("ortho", "Orthophoto"), ("thermal", "Thermal"), ("survey", "Survey drawing"), ("other", "Other")]
TYPES = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".webp"}
WORLD_TYPES = {".jgw", ".pgw", ".tfw", ".wld", ".j2w", ".tifw", ".jpgw", ".pngw"}
IMAGE_LIMIT = 150 * 1024 * 1024
MAX_PIXELS = 160_000_000          # what Pillow is let open: about 12,600 px square
SHOWN_PX = 4096
THUMB_PX = 360

SCHEMA = """
CREATE TABLE IF NOT EXISTS marine_images (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  name            TEXT NOT NULL DEFAULT '',
  taken           TEXT NOT NULL,                    -- YYYY-MM-DD
  kind            TEXT NOT NULL DEFAULT 'ortho',    -- KINDS
  south           REAL NOT NULL,
  west            REAL NOT NULL,
  north           REAL NOT NULL,
  east            REAL NOT NULL,
  width           INTEGER NOT NULL DEFAULT 0,       -- as kept
  height          INTEGER NOT NULL DEFAULT 0,
  gsd             REAL,                             -- ground sample distance of the original, m a pixel
  placed          TEXT NOT NULL DEFAULT '',         -- geotiff | world file | typed | made up
  file            TEXT NOT NULL DEFAULT '',         -- the original's file name, as uploaded
  created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS marine_images_asset ON marine_images (asset_id, taken);
"""

CRS = [("", "As the file says"), ("4326", "Latitude and longitude (WGS 84)"), ("3857", "Web Mercator (EPSG:3857)"),
       ("utm", "UTM, the model's zone")]


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


# --- where an image is ---------------------------------------------------------------------------

def to_latlon(x: float, y: float, epsg: int) -> tuple[float, float]:
    """A position in the image's reference system as latitude and longitude."""
    if epsg == 4326:
        return y, x
    if epsg == 3857:
        r = 6378137.0
        return math.degrees(math.atan(math.sinh(y / r))), math.degrees(x / r)
    if 32601 <= epsg <= 32660 or 32701 <= epsg <= 32760:
        return marine_ifc.utm_to_latlon(x, y, epsg % 100, epsg < 32700)
    raise ValueError(f"EPSG:{epsg} is not one this reads: use latitude and longitude, Web Mercator or UTM.")


def _box(corners: list[tuple[float, float]], epsg: int) -> dict[str, float]:
    pts = [to_latlon(x, y, epsg) for x, y in corners]
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    out = {"south": min(lats), "west": min(lons), "north": max(lats), "east": max(lons)}
    if not (-90 <= out["south"] < out["north"] <= 90 and -180 <= out["west"] < out["east"] <= 180):
        raise ValueError("The image's corners do not fall on the earth: is the reference system right?")
    return out


def geotiff(img: Any) -> tuple[list[float], list[float], int | None] | None:
    """A GeoTIFF's pixel scale, tie point and EPSG code, where it has them."""
    tags = getattr(img, "tag_v2", None)
    if not tags or 33550 not in tags or 33922 not in tags:
        return None
    scale, tie = [float(v) for v in tags[33550]], [float(v) for v in tags[33922]]
    epsg = None
    keys = tags.get(34735)
    if keys:
        keys = [int(k) for k in keys]
        for i in range(4, len(keys) - 3, 4):
            key, where, _count, value = keys[i:i + 4]
            if where == 0 and key in (3072, 2048) and value not in (0, 32767):
                epsg = value if key == 3072 else (4326 if value in (4326, 4030) else value)
                if key == 3072:
                    break
    return scale, tie, epsg


def world_file(text: str) -> tuple[float, float, float, float]:
    """A world file's pixel size and the centre of its top-left pixel: (a, e, c, f)."""
    try:
        a, d, b, e, c, f = (float(v) for v in text.split()[:6])
    except ValueError as err:
        raise ValueError("The world file should hold six numbers, one a line.") from err
    if abs(b) > 1e-9 or abs(d) > 1e-9:
        raise ValueError("The world file turns the image: export it north up.")
    return a, e, c, f


def place(img: Any, width: int, height: int, world: str | None, epsg: int | None, bounds: dict[str, float] | None,
          asset: Any) -> tuple[dict[str, float], str, float | None]:
    """Where the image lies: its bounds, how that was known, and its metres a pixel."""
    if bounds:
        b = {k: float(bounds[k]) for k in ("south", "west", "north", "east")}
        if not (-90 <= b["south"] < b["north"] <= 90 and -180 <= b["west"] < b["east"] <= 180):
            raise ValueError("The corners should be south below north and west left of east, in degrees.")
        gsd = (b["east"] - b["west"]) * 111_320.0 * math.cos(math.radians((b["north"] + b["south"]) / 2)) / max(width, 1)
        return b, "typed", gsd
    if world:
        a, e, c, f = world_file(world)
        code = epsg or _asset_epsg(asset) or 4326
        left, top = c - a / 2, f - e / 2
        right, bottom = left + a * width, top + e * height
        box = _box([(left, top), (right, top), (left, bottom), (right, bottom)], code)
        return box, "world file", (abs(a) if code != 4326 else abs(a) * 111_320.0)
    geo = geotiff(img)
    if geo:
        scale, tie, own = geo
        code = epsg or own or _asset_epsg(asset)
        if not code:
            raise ValueError("The GeoTIFF does not say its reference system: pick it below.")
        i, j, _k, x, y = tie[:5]
        left, top = x - i * scale[0], y + j * scale[1]
        right, bottom = left + scale[0] * width, top - scale[1] * height
        box = _box([(left, top), (right, top), (left, bottom), (right, bottom)], code)
        return box, "geotiff", (scale[0] if code != 4326 else scale[0] * 111_320.0)
    raise ValueError("This picture does not say where it is: bring its world file with it, or type its corners.")


def _asset_epsg(asset: Any) -> int | None:
    found = marine_ifc._epsg_utm(asset["epsg"] or "") if asset and asset["epsg"] else None
    return (32600 if found[1] else 32700) + found[0] if found else None


def utm_code(asset: Any) -> int | None:
    """The UTM zone the asset sits in, from the model's EPSG or its longitude."""
    code = _asset_epsg(asset)
    if code:
        return code
    if asset["latitude"] is None:
        return None
    zone = int((asset["longitude"] + 180) // 6) + 1
    return (32600 if asset["latitude"] >= 0 else 32700) + zone


# --- keeping one --------------------------------------------------------------------------------

def folder(root: Path, asset_id: int) -> Path:
    f = root / f"asset-{asset_id}"
    f.mkdir(parents=True, exist_ok=True)
    return f


def open_picture(data: bytes, name: str) -> Any:
    from PIL import Image, UnidentifiedImageError
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        img = Image.open(io.BytesIO(data))
        if img.width * img.height > MAX_PIXELS:
            raise ValueError(f"{name} is {img.width:,} by {img.height:,} pixels: export it at a coarser resolution "
                             "(5 cm a pixel is plenty for a berth).")
        if img.format == "JPEG":
            img.draft("RGB", (SHOWN_PX, SHOWN_PX))   # a big JPEG is read already reduced
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as err:
        raise ValueError(f"{name} is not a picture this can read.") from err
    return img


def shown(img: Any) -> Any:
    """The picture to keep: north up as it came, RGBA where it has empty corners, at most SHOWN_PX."""
    from PIL import Image
    img.load()
    if img.mode in ("I;16", "I;16B", "I", "F"):
        import numpy as np
        a = np.asarray(img, dtype="float64")
        lo, hi = np.nanpercentile(a, 2), np.nanpercentile(a, 98)
        img = Image.fromarray((np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1) * 255).astype("uint8"))
    if img.mode not in ("RGB", "RGBA", "L", "LA"):
        img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")
    if img.mode == "LA":
        img = img.convert("RGBA")
    out = img.copy()
    out.thumbnail((SHOWN_PX, SHOWN_PX), Image.LANCZOS)
    return out


def store(conn: sqlite3.Connection, root: Path, asset: Any, data: bytes, name: str, kind: str, taken: str,
          world: str | None, epsg: int | None, bounds: dict[str, float] | None, user_id: int | None) -> dict[str, Any]:
    """Keep one site image, laid where it belongs. Says what it did."""
    img = open_picture(data, name)
    full_w, full_h = img.size
    box, how, gsd = place(img, full_w, full_h, world, epsg, bounds, asset)
    return keep(conn, root, asset, shown(img), name, kind, taken, box, how, gsd, user_id)


def keep(conn: sqlite3.Connection, root: Path, asset: Any, img: Any, name: str, kind: str, taken: str,
         box: dict[str, float], how: str, gsd: float | None, user_id: int | None) -> dict[str, Any]:
    image_id = conn.execute(
        "INSERT INTO marine_images (asset_id, name, taken, kind, south, west, north, east, width, height, gsd, placed, file, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (asset["id"], Path(name).stem[:120] or "Site image", taken, kind, box["south"], box["west"], box["north"], box["east"],
         img.width, img.height, gsd, how, name[:160], user_id)).lastrowid
    where = folder(root, asset["id"])
    img.save(where / f"{image_id}.webp", "WEBP", quality=82, method=4)
    thumb = img.copy()
    thumb.thumbnail((THUMB_PX, THUMB_PX))
    thumb.save(where / f"{image_id}-thumb.webp", "WEBP", quality=75)
    return {"id": image_id, "placed": how, "gsd": gsd, **box}


def remove(root: Path, row: Any) -> None:
    where = root / f"asset-{row['asset_id']}"
    for f in (f"{row['id']}.webp", f"{row['id']}-thumb.webp"):
        (where / f).unlink(missing_ok=True)


def covers(row: Any) -> float:
    """The ground an image covers, m²."""
    mid = math.radians((row["north"] + row["south"]) / 2)
    return (row["north"] - row["south"]) * 111_320.0 * (row["east"] - row["west"]) * 111_320.0 * math.cos(mid)


def layers(rows: list[Any], url) -> list[dict[str, Any]]:
    """The images as the page's map wants them, oldest first."""
    return [{"id": r["id"], "name": r["name"], "taken": r["taken"], "kind": r["kind"], "url": url(r),
             "bounds": [[r["south"], r["west"]], [r["north"], r["east"]]]} for r in sorted(rows, key=lambda r: (r["taken"], r["id"]))]


# --- two made-up flights, to try the page -----------------------------------------------------------

def demo_pair(asset: Any, elements: list[Any]) -> list[tuple[str, Any, dict[str, float]]]:
    """Two drawn orthophotos of the site a year apart: a stockpile grows, a ship comes alongside."""
    from PIL import Image, ImageDraw, ImageFilter
    import random
    pts = [marine.geolocate(asset, e["x"], e["y"]) for e in elements]
    pts = [p for p in pts if p]
    drawn = bool(pts)
    if not pts:                                    # no elements yet: a quay 300 m by 40 m at the asset's place
        lat0, lon0 = asset["latitude"], asset["longitude"]
        pts = [(lat0 - 0.00018, lon0 - 0.00135), (lat0 + 0.00018, lon0 + 0.00135)]
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    pad_lat = max((max(lats) - min(lats)) * 0.25, 0.0008)
    pad_lon = max((max(lons) - min(lons)) * 0.25, 0.0008)
    box = {"south": min(lats) - pad_lat, "north": max(lats) + pad_lat, "west": min(lons) - pad_lon, "east": max(lons) + pad_lon}
    ground_w = (box["east"] - box["west"]) * 111_320.0 * math.cos(math.radians((box["north"] + box["south"]) / 2))
    ground_h = (box["north"] - box["south"]) * 111_320.0
    w = 1600
    h = max(200, min(4000, int(w * ground_h / max(ground_w, 1))))

    def px(lat, lon):
        return ((lon - box["west"]) / (box["east"] - box["west"]) * w, (box["north"] - lat) / (box["north"] - box["south"]) * h)

    deck = [px(*p) for p in pts]
    xs, ys = [p[0] for p in deck], [p[1] for p in deck]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    out = []
    for n, (label, grow) in enumerate((("Drone flight, before", 0.0), ("Drone flight, a year on", 1.0))):
        rnd = random.Random(7 + n)
        img = Image.new("RGB", (w, h), (32, 74, 96))
        d = ImageDraw.Draw(img)
        for _ in range(900):                       # a ripple on the water
            x, y = rnd.uniform(0, w), rnd.uniform(0, h)
            d.line([(x, y), (x + rnd.uniform(4, 14), y)], fill=(44 + rnd.randint(0, 14), 92, 116), width=1)
        r = 3 if len(deck) > 400 else 5
        if not drawn:
            d.rectangle([min(xs), min(ys), max(xs), max(ys)], fill=(186, 182, 172), outline=(150, 148, 140), width=4)
        for x, y in deck if drawn else []:         # the structure, where the model has it
            d.ellipse([x - r * 2, y - r * 2, x + r * 2, y + r * 2], fill=(150, 148, 140))
        for x, y in deck if drawn else []:
            d.ellipse([x - r, y - r, x + r, y + r], fill=(196, 192, 182))
        img = img.filter(ImageFilter.GaussianBlur(0.6))
        d = ImageDraw.Draw(img)
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        wide = (x1 - x0) >= (y1 - y0)
        length, breadth = (x1 - x0, y1 - y0) if wide else (y1 - y0, x1 - x0)
        breadth = max(breadth, 12)

        def rect(u0, u1, v0, v1, colour):         # along the berth (u) and across it (v), as fractions
            if wide:
                d.rectangle([x0 + u0 * length, y0 + v0 * breadth, x0 + u1 * length, y0 + v1 * breadth], fill=colour)
            else:
                d.rectangle([x0 + v0 * breadth, y0 + u0 * length, x0 + v1 * breadth, y0 + u1 * length], fill=colour)

        if grow:                                   # a year on: the yard cleared for a stockpile, a ship alongside
            rect(0.25, 0.75, 0.2, 0.8, (128, 104, 76))
            rect(0.35, 0.65, 0.32, 0.68, (150, 124, 92))
            rect(0.12, 0.82, 1.25, 1.85, (166, 40, 36))
            rect(0.7, 0.78, 1.32, 1.78, (236, 236, 230))
        else:                                      # before: boxes in rows along the yard
            for k in range(14):
                u = 0.06 + k * 0.064
                rect(u, u + 0.05, 0.2, 0.45, (42, 110, 170) if k % 3 else (200, 120, 40))
                rect(u, u + 0.05, 0.55, 0.8, (200, 120, 40) if k % 2 else (90, 140, 80))
        out.append((label, img, box))
    return out
