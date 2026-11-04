"""Talus projects on disk: one SQLite database under ``TALUS_DATA_DIR``.

A project is the handful of inputs the page sends (JSON); every calculation is
done again from them, so nothing computed is stored. Each save keeps the one
before it, up to ``KEEP`` versions, so any of them can be brought back.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

KEEP = 30
MAX_BYTES = 512 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    owner    TEXT NOT NULL,
    name     TEXT NOT NULL,
    kind     TEXT NOT NULL,
    data     TEXT NOT NULL,
    version  INTEGER NOT NULL DEFAULT 1,
    created  REAL NOT NULL,
    updated  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner);
CREATE TABLE IF NOT EXISTS versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version    INTEGER NOT NULL,
    data       TEXT NOT NULL,
    saved      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_versions_project ON versions(project_id);
"""

KINDS = ("cut", "embankment", "revetment", "section")


class StoreError(Exception):
    def __init__(self, message: str, status: int = 400, **extra: Any):
        super().__init__(message)
        self.status = status
        self.extra = extra


def data_dir() -> Path:
    return Path(os.environ.get("TALUS_DATA_DIR") or Path.cwd() / "data" / "talus")


class Store:
    def __init__(self, folder: Path | None = None):
        self.folder = Path(folder or data_dir())
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "talus.sqlite"
        with self._db() as db:
            db.executescript(SCHEMA)

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @staticmethod
    def _clean(data: Any) -> tuple[str, str, str]:
        if not isinstance(data, dict):
            raise StoreError("A project is a JSON object.")
        kind = data.get("type")
        if kind not in KINDS:
            raise StoreError("Unknown kind of slope.")
        text = json.dumps(data, separators=(",", ":"))
        if len(text) > MAX_BYTES:
            raise StoreError("That project is too large to keep.", 413)
        name = str(data.get("name") or "").strip()[:120] or "Untitled"
        return text, name, kind

    @staticmethod
    def _row(row: sqlite3.Row, with_data: bool = True) -> dict[str, Any]:
        out = {"id": row["id"], "name": row["name"], "kind": row["kind"], "version": row["version"],
               "created": row["created"], "updated": row["updated"]}
        if with_data:
            out["data"] = json.loads(row["data"])
        return out

    def listing(self, owner: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM projects WHERE owner = ? ORDER BY updated DESC, id DESC", (owner,)).fetchall()
        return [self._row(r, with_data=False) for r in rows]

    def _own(self, db: sqlite3.Connection, owner: str, pid: int) -> sqlite3.Row:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
        if row is None or row["owner"] != owner:
            raise StoreError("No such project.", 404)
        return row

    def create(self, owner: str, data: Any) -> dict[str, Any]:
        text, name, kind = self._clean(data)
        now = time.time()
        with self._db() as db:
            cur = db.execute("INSERT INTO projects (owner, name, kind, data, created, updated) VALUES (?, ?, ?, ?, ?, ?)",
                             (owner, name, kind, text, now, now))
            return self._row(self._own(db, owner, cur.lastrowid))

    def fetch(self, owner: str, pid: int) -> dict[str, Any]:
        with self._db() as db:
            return self._row(self._own(db, owner, pid))

    def save(self, owner: str, pid: int, data: Any, base_version: int | None = None) -> dict[str, Any]:
        text, name, kind = self._clean(data)
        with self._db() as db:
            row = self._own(db, owner, pid)
            if base_version is not None and base_version != row["version"]:
                raise StoreError("This project was changed somewhere else.", 409, current=self._row(row))
            if row["data"] == text:
                return self._row(row)
            db.execute("INSERT INTO versions (project_id, version, data, saved) VALUES (?, ?, ?, ?)",
                       (pid, row["version"], row["data"], row["updated"]))
            db.execute("DELETE FROM versions WHERE project_id = ? AND id NOT IN "
                       "(SELECT id FROM versions WHERE project_id = ? ORDER BY id DESC LIMIT ?)", (pid, pid, KEEP))
            db.execute("UPDATE projects SET name = ?, kind = ?, data = ?, version = version + 1, updated = ? WHERE id = ?",
                       (name, kind, text, time.time(), pid))
            return self._row(self._own(db, owner, pid))

    def delete(self, owner: str, pid: int) -> None:
        with self._db() as db:
            self._own(db, owner, pid)
            db.execute("DELETE FROM versions WHERE project_id = ?", (pid,))
            db.execute("DELETE FROM projects WHERE id = ?", (pid,))

    def duplicate(self, owner: str, pid: int) -> dict[str, Any]:
        src = self.fetch(owner, pid)
        data = dict(src["data"])
        data["name"] = (str(data.get("name") or "Untitled") + " (copy)")[:120]
        return self.create(owner, data)

    def history(self, owner: str, pid: int) -> list[dict[str, Any]]:
        with self._db() as db:
            self._own(db, owner, pid)
            rows = db.execute("SELECT id, version, saved FROM versions WHERE project_id = ? ORDER BY id DESC", (pid,)).fetchall()
        return [dict(r) for r in rows]

    def restore(self, owner: str, pid: int, version_id: int) -> dict[str, Any]:
        with self._db() as db:
            self._own(db, owner, pid)
            row = db.execute("SELECT data FROM versions WHERE id = ? AND project_id = ?", (version_id, pid)).fetchone()
            if row is None:
                raise StoreError("No such version.", 404)
        return self.save(owner, pid, json.loads(row["data"]))
