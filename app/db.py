"""SQLite access. Uses the standard library only, so there is nothing to install
beyond Flask itself.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from flask import current_app, g

HERE = Path(__file__).resolve().parent


def data_dir() -> Path:
    """Where the database and secret key live.

    DATA_DIR lets a deployment point this at a mounted persistent volume; by
    default it sits next to the application so a local install just works.
    """
    directory = Path(os.environ.get("DATA_DIR") or HERE.parent / "data")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def database_path() -> Path:
    override = os.environ.get("DATABASE_FILE")
    return Path(override) if override else data_dir() / "pm.sqlite"


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or database_path()))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db() -> sqlite3.Connection:
    """The connection for the current request, opened lazily."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exception: BaseException | None = None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    """Adds a column to an existing database if a newer schema introduced it."""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db(path: Path | str | None = None) -> None:
    """Creates the schema if it is missing and applies any later additions."""
    conn = connect(path)
    try:
        conn.executescript((HERE / "schema.sql").read_text(encoding="utf-8"))
        _ensure_column(conn, "projects", "elapsed_day_offset", "REAL NOT NULL DEFAULT 0")
        conn.commit()
    finally:
        conn.close()


# --- small query helpers ---------------------------------------------------

def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return get_db().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return get_db().execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    conn = get_db()
    cursor = conn.execute(sql, tuple(params))
    conn.commit()
    return cursor


def insert(sql: str, params: Iterable[Any] = ()) -> int:
    return int(execute(sql, params).lastrowid)
