"""TritoMoor projects kept on the site, so a project opens from any machine.

TritoMoor itself runs in the browser. What it keeps here is the project file —
the same JSON it saves as a ``.trito`` file — under the account that saved it.
Nobody else sees an account's projects.

**Autosave never loses work.** TritoMoor saves as it is edited, so every save
replaces the last. Before one does, the copy it replaces is kept as an earlier
version once it is older than ``SNAPSHOT_EVERY``; the newest ``KEEP_VERSIONS``
are kept per project and any of them can be brought back.

**Two machines on one project.** Every save names the version it was based on.
If the project has been saved from somewhere else since, the save is refused
with the newer version, and TritoMoor asks which to keep.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

SNAPSHOT_EVERY = 15 * 60          # seconds between kept earlier versions
KEEP_VERSIONS = 40
MAX_BYTES = 12 * 1024 * 1024      # one project; TritoMoor's own projects are well under 1 MB


SCHEMA = """
CREATE TABLE IF NOT EXISTS tritomoor_projects (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL DEFAULT '',
  vessel      TEXT NOT NULL DEFAULT '',
  berth       TEXT NOT NULL DEFAULT '',
  data        TEXT NOT NULL,
  version     INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tritomoor_projects_user ON tritomoor_projects(user_id);
CREATE TABLE IF NOT EXISTS tritomoor_versions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  project_id  INTEGER NOT NULL REFERENCES tritomoor_projects(id) ON DELETE CASCADE,
  version     INTEGER NOT NULL,
  name        TEXT NOT NULL DEFAULT '',
  data        TEXT NOT NULL,
  saved_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tritomoor_versions_project ON tritomoor_versions(project_id);
"""


class Problem(Exception):
    """Something the caller asked for that cannot be done, said plainly."""

    def __init__(self, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _age_seconds(stamp: str) -> float:
    try:
        then = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return float("inf")
    return (datetime.now(timezone.utc) - then).total_seconds()


def _describe(data: Any) -> tuple[str, str, str]:
    """The project's name, vessel and berth type, read from the project itself."""
    if not isinstance(data, dict) or not isinstance(data.get("vessel"), dict):
        raise Problem("This is not a TritoMoor project.")
    vessel = data.get("vessel") or {}
    berth = data.get("berth") or {}
    return (str(data.get("name") or "").strip()[:200], str(vessel.get("name") or "").strip()[:200],
            str(berth.get("type") or "").strip()[:40])


def _encode(data: Any) -> str:
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise Problem("This project is too large to keep on the site.", 413)
    return text


def _row(conn: sqlite3.Connection, user_id: int, project_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tritomoor_projects WHERE id = ? AND user_id = ?",
                       (project_id, user_id)).fetchone()
    if row is None:
        raise Problem("That project is not in your projects.", 404)
    return row


def summary(row: sqlite3.Row) -> dict[str, Any]:
    return {"id": row["id"], "name": row["name"], "vessel": row["vessel"], "berth": row["berth"],
            "version": row["version"], "created_at": row["created_at"], "updated_at": row["updated_at"],
            "size": len(row["data"])}


def listing(conn: sqlite3.Connection, user_id: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM tritomoor_projects WHERE user_id = ? ORDER BY updated_at DESC, id DESC",
                        (user_id,)).fetchall()
    return [summary(r) for r in rows]


def fetch(conn: sqlite3.Connection, user_id: int, project_id: int) -> dict[str, Any]:
    row = _row(conn, user_id, project_id)
    return {**summary(row), "data": json.loads(row["data"])}


def create(conn: sqlite3.Connection, user_id: int, data: Any, name: str | None = None) -> dict[str, Any]:
    own_name, vessel, berth = _describe(data)
    name = (name or "").strip()[:200] or own_name or "Untitled project"
    if isinstance(data, dict):
        data["name"] = name
    stamp = _now()
    cur = conn.execute(
        "INSERT INTO tritomoor_projects (user_id, name, vessel, berth, data, version, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, 1, ?, ?)", (user_id, name, vessel, berth, _encode(data), stamp, stamp))
    conn.commit()
    return summary(_row(conn, user_id, int(cur.lastrowid)))


def _snapshot(conn: sqlite3.Connection, row: sqlite3.Row, force: bool = False) -> None:
    last = conn.execute("SELECT saved_at FROM tritomoor_versions WHERE project_id = ? ORDER BY id DESC LIMIT 1",
                        (row["id"],)).fetchone()
    if not force and last is not None and _age_seconds(last["saved_at"]) < SNAPSHOT_EVERY:
        return
    conn.execute("INSERT INTO tritomoor_versions (project_id, version, name, data, saved_at) VALUES (?, ?, ?, ?, ?)",
                 (row["id"], row["version"], row["name"], row["data"], row["updated_at"]))
    conn.execute(
        "DELETE FROM tritomoor_versions WHERE project_id = ? AND id NOT IN"
        " (SELECT id FROM tritomoor_versions WHERE project_id = ? ORDER BY id DESC LIMIT ?)",
        (row["id"], row["id"], KEEP_VERSIONS))


def save(conn: sqlite3.Connection, user_id: int, project_id: int, *, data: Any = None, name: str | None = None,
         base_version: int | None = None, keep_previous: bool = False) -> dict[str, Any]:
    """Saves over the project. Refused when it has been saved elsewhere since ``base_version``.

    ``keep_previous`` keeps the copy being replaced as an earlier version whatever its age — used
    when one computer knowingly saves over what another saved.
    """
    row = _row(conn, user_id, project_id)
    if base_version is not None and int(base_version) != row["version"]:
        raise Problem("This project has been saved from somewhere else since you opened it.", 409,
                      current=summary(row))
    new_name = row["name"] if name is None else (name.strip()[:200] or row["name"])
    vessel, berth, text = row["vessel"], row["berth"], row["data"]
    if data is not None:
        _, vessel, berth = _describe(data)
        if isinstance(data, dict):
            data["name"] = new_name
        text = _encode(data)
    elif name is not None:
        stored = json.loads(row["data"])
        stored["name"] = new_name
        text = _encode(stored)
    if text == row["data"] and new_name == row["name"]:
        return summary(row)
    _snapshot(conn, row, force=keep_previous)
    conn.execute("UPDATE tritomoor_projects SET name = ?, vessel = ?, berth = ?, data = ?, version = version + 1,"
                 " updated_at = ? WHERE id = ?", (new_name, vessel, berth, text, _now(), project_id))
    conn.commit()
    return summary(_row(conn, user_id, project_id))


def duplicate(conn: sqlite3.Connection, user_id: int, project_id: int) -> dict[str, Any]:
    row = _row(conn, user_id, project_id)
    return create(conn, user_id, json.loads(row["data"]), name=f"{row['name']} (copy)")


def delete(conn: sqlite3.Connection, user_id: int, project_id: int) -> None:
    _row(conn, user_id, project_id)
    conn.execute("DELETE FROM tritomoor_versions WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM tritomoor_projects WHERE id = ?", (project_id,))
    conn.commit()


def history(conn: sqlite3.Connection, user_id: int, project_id: int) -> list[dict[str, Any]]:
    _row(conn, user_id, project_id)
    rows = conn.execute("SELECT id, version, name, saved_at, length(data) AS size FROM tritomoor_versions"
                        " WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    return [dict(r) for r in rows]


def restore(conn: sqlite3.Connection, user_id: int, project_id: int, version_id: int) -> dict[str, Any]:
    """Brings an earlier version back as the newest, keeping the one it replaces."""
    row = _row(conn, user_id, project_id)
    old = conn.execute("SELECT * FROM tritomoor_versions WHERE id = ? AND project_id = ?",
                       (version_id, project_id)).fetchone()
    if old is None:
        raise Problem("That earlier version is not kept any more.", 404)
    _snapshot(conn, row, force=True)
    data = json.loads(old["data"])
    _, vessel, berth = _describe(data)
    conn.execute("UPDATE tritomoor_projects SET name = ?, vessel = ?, berth = ?, data = ?, version = version + 1,"
                 " updated_at = ? WHERE id = ?", (old["name"], vessel, berth, old["data"], _now(), project_id))
    conn.commit()
    return fetch(conn, user_id, project_id)
