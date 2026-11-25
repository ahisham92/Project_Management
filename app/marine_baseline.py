"""MarineTwin's baseline: the asset as it stood on a date, and what changed since.

Any date can be looked at from the record: the readings taken by then, the piles in by then, the
latest seabed survey, photos and drone flight by then. A snapshot freezes that picture, so it still
reads the same after readings are corrected or records removed; one snapshot can be marked the
handover baseline, the state the contractor handed over and everything later is measured against.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any, Callable

from . import marine

SCHEMA = """
CREATE TABLE IF NOT EXISTS marine_snapshots (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id        INTEGER NOT NULL REFERENCES marine_assets(id) ON DELETE CASCADE,
  name            TEXT NOT NULL DEFAULT '',
  day             TEXT NOT NULL,                    -- YYYY-MM-DD, the date it shows
  handover        INTEGER NOT NULL DEFAULT 0,       -- 1: the handover baseline (one an asset)
  data            TEXT NOT NULL,                    -- JSON, as state_on gives it
  created_by      INTEGER REFERENCES users(id) ON DELETE SET NULL,
  created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS marine_snapshots_asset ON marine_snapshots (asset_id, day);
"""

RANK = marine.STATE_RANK
WORD = {"good": "good", "warning": "watch", "critical": "act", "neutral": "no data"}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _n(conn: sqlite3.Connection, sql: str, args: tuple) -> int:
    return int(conn.execute(sql, args).fetchone()[0] or 0)


def state_on(conn: sqlite3.Connection, asset: Any, day: date, seabed: Callable[[Any], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """The asset as it stood on day, from what the record holds now. Small enough to keep as JSON."""
    twin = marine.assess_asset(conn, asset, day, past=True)
    iso, aid = day.isoformat(), asset["id"]
    elements = {}
    for e in twin["elements"]:
        el = e["element"]
        elements[el["name"]] = {
            "kind": el["kind"], "state": e["state"], "health": e["health"],
            "sensors": {s["label"]: {"kind": s["kind_name"], "unit": s["unit"], "latest": s["latest"], "at": s["latest_at"],
                                     "state": s["state"]} for s in e["sensors"] if s["latest"] is not None},
        }
    survey = conn.execute("SELECT * FROM marine_surveys WHERE asset_id = ? AND surveyed <= ? ORDER BY surveyed DESC, id DESC LIMIT 1",
                          (aid, iso)).fetchone()
    seabed_now = None
    if survey is not None:
        seabed_now = {"name": survey["name"], "surveyed": survey["surveyed"]}
        found = seabed(survey) if seabed else None
        if found and found.get("cells"):
            seabed_now.update(shoal_m3=round(found["shoal_m3"], 1), shallowest=round(found["shallowest"], 2), mean=round(found["mean"], 2))
    image = conn.execute("SELECT id, name, taken FROM marine_images WHERE asset_id = ? AND taken <= ? ORDER BY taken DESC, id DESC LIMIT 1",
                         (aid, iso)).fetchone()
    return {
        "day": iso,
        "health": twin["health"], "state": twin["state"], "counts": twin["counts"],
        "elements": elements,
        "piles_in": _n(conn, "SELECT COUNT(*) FROM marine_piles WHERE asset_id = ? AND installed IS NOT NULL AND installed <= ?", (aid, iso)),
        "photos": _n(conn, "SELECT COUNT(*) FROM marine_photos WHERE asset_id = ? AND taken <= ?", (aid, iso)),
        "inspections": _n(conn, "SELECT COUNT(*) FROM marine_readings r JOIN marine_sensors s ON s.id = r.sensor_id"
                                " JOIN marine_elements e ON e.id = s.element_id WHERE e.asset_id = ? AND s.kind = 'inspection' AND r.at < ?",
                          (aid, iso + "~")),
        "seabed": seabed_now,
        "image": dict(image) if image else None,
    }


def keep(conn: sqlite3.Connection, asset_id: int, name: str, state: dict[str, Any], handover: bool, user_id: int | None) -> int:
    if handover:
        conn.execute("UPDATE marine_snapshots SET handover = 0 WHERE asset_id = ?", (asset_id,))
    return conn.execute("INSERT INTO marine_snapshots (asset_id, name, day, handover, data, created_by) VALUES (?, ?, ?, ?, ?, ?)",
                        (asset_id, name[:120], state["day"], 1 if handover else 0, json.dumps(state, separators=(",", ":")), user_id)).lastrowid


def kept(row: Any) -> dict[str, Any]:
    return json.loads(row["data"])


def compare(then: dict[str, Any], now: dict[str, Any]) -> dict[str, Any]:
    """What changed from one state to another: the elements that got worse or better, and their readings."""
    worse, better, moved, gone, new = [], [], [], [], []
    for name, b in now["elements"].items():
        a = then["elements"].get(name)
        if a is None:
            new.append({"name": name, "kind": b["kind"], "state": b["state"]})
            continue
        step = RANK.get(b["state"], -1) - RANK.get(a["state"], -1)
        readings = []
        for label, rb in b["sensors"].items():
            ra = a["sensors"].get(label)
            if ra and ra["latest"] is not None and rb["latest"] is not None and rb["latest"] != ra["latest"]:
                readings.append({"label": label, "kind": rb["kind"], "unit": rb["unit"], "was": ra["latest"], "now": rb["latest"],
                                 "change": rb["latest"] - ra["latest"], "worse": RANK.get(rb["state"], -1) > RANK.get(ra["state"], -1)})
            elif not ra and rb["latest"] is not None:
                readings.append({"label": label, "kind": rb["kind"], "unit": rb["unit"], "was": None, "now": rb["latest"], "change": None,
                                 "worse": rb["state"] in ("warning", "critical")})
        readings.sort(key=lambda r: (not r["worse"], r["label"]))
        row = {"name": name, "kind": b["kind"], "was": a["state"], "now": b["state"], "health_was": a["health"], "health_now": b["health"],
               "readings": readings}
        if a["state"] != "neutral" and b["state"] != "neutral" and step > 0:
            worse.append(row)
        elif a["state"] != "neutral" and b["state"] != "neutral" and step < 0:
            better.append(row)
        elif readings:
            moved.append(row)
    for name, a in then["elements"].items():
        if name not in now["elements"]:
            gone.append({"name": name, "kind": a["kind"], "state": a["state"]})
    for rows in (worse, better):
        rows.sort(key=lambda r: (-RANK.get(r["now"], -1), r["name"]))
    seabed = None
    if then.get("seabed") and now.get("seabed") and then["seabed"].get("shoal_m3") is not None and now["seabed"].get("shoal_m3") is not None:
        seabed = now["seabed"]["shoal_m3"] - then["seabed"]["shoal_m3"]
    health = (now["health"] - then["health"]) if now["health"] is not None and then["health"] is not None else None
    return {"worse": worse, "better": better, "moved": moved[:60], "new": new, "gone": gone, "health": health, "seabed": seabed,
            "piles": now["piles_in"] - then["piles_in"], "photos": now["photos"] - then["photos"],
            "inspections": now["inspections"] - then["inspections"]}


def picked(conn: sqlite3.Connection, asset: Any, token: str | None, fallback: date,
           seabed: Callable[[Any], dict[str, Any] | None] | None = None) -> tuple[str, dict[str, Any], str]:
    """A side of the comparison from the page's choice: 's<id>' a snapshot, a date, or the fallback date.
    Gives the token, the state and how to name it."""
    token = (token or "").strip()
    if token.startswith("s") and token[1:].isdigit():
        row = conn.execute("SELECT * FROM marine_snapshots WHERE id = ? AND asset_id = ?", (int(token[1:]), asset["id"])).fetchone()
        if row is not None:
            return token, kept(row), (row["name"] or "Snapshot") + (" (handover)" if row["handover"] else "")
    try:
        day = date.fromisoformat(token[:10])
    except ValueError:
        day = fallback
    day = min(day, date.today())
    return day.isoformat(), state_on(conn, asset, day, seabed), "the record on " + day.strftime("%d/%m/%Y")


def export_csv(change: dict[str, Any]) -> str:
    import csv
    import io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["element", "kind", "was", "now", "health was", "health now", "reading", "value was", "value now", "unit"])
    for group in ("worse", "better", "moved"):
        for r in change[group]:
            if not r["readings"]:
                w.writerow([r["name"], r["kind"], WORD.get(r["was"]), WORD.get(r["now"]), r["health_was"], r["health_now"], "", "", "", ""])
            for x in r["readings"]:
                w.writerow([r["name"], r["kind"], WORD.get(r["was"]), WORD.get(r["now"]), r["health_was"], r["health_now"],
                            x["label"], x["was"], x["now"], x["unit"]])
    return out.getvalue()

