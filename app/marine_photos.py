"""MarineTwin's photos: what inspectors, divers and drones saw, pinned to the element they show.

A photo is kept at a size a browser shows quickly (the original beside it, for the record: a
radiometric thermal image keeps its temperatures only in the original). Its date and place come
from the camera (EXIF) when it has them; a photo with GPS and no element picked is pinned to the
nearest element of the structure, within 40 m.
"""

from __future__ import annotations

import io
import math
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from . import marine

KINDS = [("photo", "Photo"), ("thermal", "Thermal"), ("drone", "Drone"), ("diver", "Diver or ROV"), ("survey", "Survey sheet")]
TYPES = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}
PHOTO_LIMIT = 30 * 1024 * 1024
SHOWN_PX = 2400
THUMB_PX = 420
NEAREST_M = 40.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS marine_photos (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  element_id      INTEGER REFERENCES marine_elements(id) ON DELETE SET NULL,
  taken           TEXT NOT NULL,                    -- YYYY-MM-DD
  kind            TEXT NOT NULL DEFAULT 'photo',    -- KINDS
  caption         TEXT NOT NULL DEFAULT '',
  name            TEXT NOT NULL DEFAULT '',         -- the file as it was uploaded
  original        TEXT NOT NULL DEFAULT '',         -- the stored original's file name
  width           INTEGER NOT NULL DEFAULT 0,
  height          INTEGER NOT NULL DEFAULT 0,
  latitude        REAL,                             -- from the camera's GPS
  longitude       REAL,
  pinned          TEXT NOT NULL DEFAULT '',         -- how it came to its element: picked | gps | ''
  created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS marine_photos_asset ON marine_photos (asset_id, taken);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _ratio(v: Any) -> float:
    try:
        return float(v[0]) / float(v[1]) if isinstance(v, tuple) else float(v)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def camera(img: Any) -> dict[str, Any]:
    """The date and place the camera wrote into the photo, where it did."""
    out: dict[str, Any] = {}
    try:
        exif = img.getexif()
    except Exception:  # noqa: BLE001 - a photo without readable EXIF is still a photo
        return out
    when = exif.get(36867) or exif.get(306)            # DateTimeOriginal, else DateTime
    try:
        sub = exif.get_ifd(0x8769)
        when = sub.get(36867) or when
    except Exception:  # noqa: BLE001
        pass
    if when:
        try:
            out["taken"] = datetime.strptime(str(when)[:19], "%Y:%m:%d %H:%M:%S").date().isoformat()
        except ValueError:
            pass
    try:
        gps = exif.get_ifd(0x8825)
    except Exception:  # noqa: BLE001
        gps = {}
    if gps and 2 in gps and 4 in gps:
        def deg(v):
            d, m, s = (_ratio(x) for x in v)
            return d + m / 60 + s / 3600
        lat, lon = deg(gps[2]), deg(gps[4])
        if str(gps.get(1, "N")).upper().startswith("S"):
            lat = -lat
        if str(gps.get(3, "E")).upper().startswith("W"):
            lon = -lon
        if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat or lon):
            out.update(latitude=round(lat, 7), longitude=round(lon, 7))
    return out


def nearest(asset: Any, elements: Iterable[Any], lat: float, lon: float) -> int | None:
    """The element nearest a GPS position, within NEAREST_M."""
    best, gap = None, NEAREST_M
    for e in elements:
        at = marine.geolocate(asset, e["x"], e["y"])
        if not at:
            return None
        d = math.hypot((at[0] - lat) * 111_320.0, (at[1] - lon) * 111_320.0 * math.cos(math.radians(lat)))
        if d <= gap:
            best, gap = e["id"], d
    return best


def folder(root: Path, asset_id: int) -> Path:
    f = root / f"asset-{asset_id}"
    f.mkdir(parents=True, exist_ok=True)
    return f


def store(conn: sqlite3.Connection, root: Path, asset: Any, data: bytes, name: str, kind: str, caption: str,
          element_id: int | None, taken: str | None, user_id: int | None, elements: list[Any]) -> dict[str, Any]:
    """Keep one photo: its original, a size to show and a thumbnail. Says what it did."""
    from PIL import Image, ImageOps, UnidentifiedImageError
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, ValueError) as err:
        raise ValueError(f"{name} is not a picture this can read.") from err
    cam = camera(img)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    pinned = "picked" if element_id else ""
    if not element_id and cam.get("latitude") is not None and asset["latitude"] is not None:
        element_id = nearest(asset, elements, cam["latitude"], cam["longitude"])
        pinned = "gps" if element_id else ""
    when = taken or cam.get("taken") or date.today().isoformat()
    suffix = Path(name).suffix.lower() if Path(name).suffix.lower() in TYPES else ".jpg"
    photo_id = conn.execute(
        "INSERT INTO marine_photos (asset_id, element_id, taken, kind, caption, name, width, height, latitude, longitude, pinned, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (asset["id"], element_id, when, kind, caption[:300], name[:120], img.width, img.height, cam.get("latitude"),
         cam.get("longitude"), pinned, user_id)).lastrowid
    where = folder(root, asset["id"])
    original = f"{photo_id}-original{suffix}"
    (where / original).write_bytes(data)
    shown = img.copy()
    shown.thumbnail((SHOWN_PX, SHOWN_PX))
    shown.save(where / f"{photo_id}.jpg", "JPEG", quality=85, optimize=True)
    thumb = img.copy()
    thumb.thumbnail((THUMB_PX, THUMB_PX))
    thumb.save(where / f"{photo_id}-thumb.jpg", "JPEG", quality=80, optimize=True)
    conn.execute("UPDATE marine_photos SET original = ? WHERE id = ?", (original, photo_id))
    return {"id": photo_id, "element_id": element_id, "pinned": pinned, "taken": when}


def remove(root: Path, row: Any) -> None:
    where = root / f"asset-{row['asset_id']}"
    for f in (f"{row['id']}.jpg", f"{row['id']}-thumb.jpg", row["original"]):
        if f:
            (where / f).unlink(missing_ok=True)
