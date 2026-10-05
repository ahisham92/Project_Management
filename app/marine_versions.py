"""MarineTwin: each Revit model uploaded to an asset kept as a version, and what changed between them.

The model file itself is replaced on each upload (they run to hundreds of MB);
what is kept is the list of elements MarineTwin read from it, enough to say
which elements were added, removed, moved or changed from one export to the
next, and which tracked elements (with sensors and readings) the new model no
longer has.
"""
from __future__ import annotations

import gzip
import json
import math
import sqlite3
from typing import Any

# An element that moved less than this between exports is where it was: rounding in the export.
MOVED_M = 0.05
# What an element carries that is worth saying changed.
COMPARED = ("name", "kind", "material", "zone", "wall_mm", "legend")
# How many names each list in a stored comparison keeps; the counts are always whole.
KEEP = 300


def _slim(e: dict[str, Any]) -> dict[str, Any]:
    return {"id": e.get("global_id") or "", "name": e["name"], "kind": e.get("kind"), "material": e.get("material"),
            "zone": e.get("zone"), "wall_mm": e.get("wall_mm"), "legend": e.get("group") or e.get("legend") or "",
            "x": e.get("x", 0.0), "y": e.get("y", 0.0), "z": e.get("z", 0.0)}


def pack(found: dict[str, Any] | None) -> bytes | None:
    if found is None:
        return None
    return gzip.compress(json.dumps([_slim(e) for e in found.get("elements", [])]).encode("utf-8"))


def unpack(blob: bytes | None) -> list[dict[str, Any]] | None:
    if not blob:
        return None
    try:
        return json.loads(gzip.decompress(blob).decode("utf-8"))
    except (OSError, ValueError):
        return None


def compare(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> dict[str, Any]:
    """What changed from one export's elements to the next.

    Elements are matched by GlobalId, which Revit keeps for an element across
    exports; one without a GlobalId, or whose GlobalId is new, is matched by name.
    """
    old_by_id = {e["id"]: e for e in before if e.get("id")}
    old_by_name = {e["name"]: e for e in before}
    matched: set[int] = set()
    added, moved, changed = [], [], []
    for e in after:
        old = old_by_id.get(e.get("id")) or old_by_name.get(e["name"])
        if old is None or id(old) in matched:
            added.append(e["name"])
            continue
        matched.add(id(old))
        shift = math.dist((old["x"], old["y"], old["z"]), (e["x"], e["y"], e["z"]))
        if shift > MOVED_M:
            moved.append({"name": e["name"], "by": round(shift, 2)})
        what = [k for k in COMPARED if (old.get(k) or "") != (e.get(k) or "")]
        if what:
            changed.append({"name": e["name"], "what": [
                f"name was {old['name']}" if k == "name" else f"{k.replace('_', ' ')} {old.get(k) or '—'} → {e.get(k) or '—'}"
                for k in what]})
    removed = [e["name"] for e in before if id(e) not in matched]
    moved.sort(key=lambda m: -m["by"])
    return {"added": sorted(added), "removed": sorted(removed), "moved": moved, "changed": changed}


def record(conn: sqlite3.Connection, asset_id: int, user_id: int | None, name: str, size: int,
           found: dict[str, Any] | None, before: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Keep a newly uploaded model as the asset's next version, compared with the one before.

    ``before`` stands in for the previous version's elements when there is none
    stored yet (a model uploaded before versions were kept). Returns the counts.
    """
    last = conn.execute("SELECT number, snapshot FROM marine_model_versions WHERE asset_id = ? ORDER BY number DESC LIMIT 1",
                        (asset_id,)).fetchone()
    previous = unpack(last["snapshot"]) if last else None
    if previous is None:
        previous = before
    elements = [_slim(e) for e in found.get("elements", [])] if found is not None else None
    diff = compare(previous, elements) if previous is not None and elements is not None else {}
    counts = {k: len(diff.get(k, [])) for k in ("added", "removed", "moved", "changed")}
    kept = {k: v[:KEEP] for k, v in diff.items()}
    number = (last["number"] if last else 0) + 1
    conn.execute(
        "INSERT INTO marine_model_versions (asset_id, number, user_id, name, size, elements, added, removed, moved, changed,"
        " diff, snapshot) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (asset_id, number, user_id, name, size, len(elements) if elements is not None else None,
         counts["added"], counts["removed"], counts["moved"], counts["changed"],
         json.dumps({**kept, "compared": bool(diff)}), pack(found)))
    # Older snapshots are only needed for the next comparison: keep the latest two.
    conn.execute("UPDATE marine_model_versions SET snapshot = NULL WHERE asset_id = ? AND number < ?", (asset_id, number - 1))
    return {"number": number, "compared": bool(diff), **counts}


def versions(conn: sqlite3.Connection, asset_id: int) -> list[dict[str, Any]]:
    """The asset's model versions, newest first, each with its comparison."""
    out = []
    for r in conn.execute("SELECT v.id, v.number, v.at, v.name, v.size, v.elements, v.added, v.removed, v.moved, v.changed,"
                          " v.diff, u.name AS who FROM marine_model_versions v LEFT JOIN users u ON u.id = v.user_id"
                          " WHERE v.asset_id = ? ORDER BY v.number DESC", (asset_id,)):
        row = dict(r)
        try:
            row["diff"] = json.loads(row["diff"] or "{}")
        except ValueError:
            row["diff"] = {}
        out.append(row)
    return out


def orphans(conn: sqlite3.Connection, asset_id: int, found: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Tracked elements the current model no longer has, with how many sensors and real readings they carry."""
    if not found:
        return []
    ids = {e.get("global_id") for e in found.get("elements", [])}
    names = {e["name"] for e in found.get("elements", [])}
    rows = conn.execute(
        "SELECT e.id, e.name, e.kind, e.model_ref,"
        " (SELECT COUNT(*) FROM marine_sensors s WHERE s.element_id = e.id) AS sensors,"
        " (SELECT COUNT(*) FROM marine_sensors s WHERE s.element_id = e.id AND s.simulated = 0) AS real"
        " FROM marine_elements e WHERE e.asset_id = ? ORDER BY e.name", (asset_id,)).fetchall()
    # Elements typed in by hand never came from the model: only those that did can have left it.
    return [dict(r) for r in rows if r["model_ref"] and r["model_ref"] not in ids and r["name"] not in names]
