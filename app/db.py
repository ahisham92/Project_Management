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


# How long a request waits for another one to finish writing before giving up.
# SQLite allows one writer at a time; without this a second simultaneous write
# fails instantly with "database is locked" instead of simply queueing, which is
# what several people using the app at once would otherwise hit.
BUSY_TIMEOUT_MS = int(os.environ.get("SQLITE_BUSY_TIMEOUT_MS", "10000"))


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or database_path()), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Write-ahead logging lets readers carry on while someone is writing, which
    # is what makes concurrent use workable at all.
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous = NORMAL")
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

        for table, column, definition in (
            ("projects", "elapsed_day_offset", "REAL NOT NULL DEFAULT 0"),
            ("projects", "max_revisions", "INTEGER NOT NULL DEFAULT 10"),
            ("projects", "rework_days", "REAL NOT NULL DEFAULT 7"),
            ("projects", "revision_reset_step", "TEXT NOT NULL DEFAULT 'comments_addressed'"),
            ("projects", "setup_password_hash", "TEXT NOT NULL DEFAULT ''"),
            ("tasks", "start_date", "TEXT NOT NULL DEFAULT ''"),
            ("tasks", "submission_date", "TEXT NOT NULL DEFAULT ''"),
            ("tasks", "tracking", "TEXT NOT NULL DEFAULT 'workflow'"),
            ("tasks", "status_key", "TEXT NOT NULL DEFAULT ''"),
            ("tasks", "revision", "INTEGER NOT NULL DEFAULT 0"),
        ):
            _ensure_column(conn, table, column, definition)

        _migrate_months_to_dates(conn)
        _ensure_workflow_steps(conn)
        conn.commit()
    finally:
        conn.close()


def _migrate_months_to_dates(conn: sqlite3.Connection) -> None:
    """Fills in start and submission dates for deliverables created when the
    schedule was held as elapsed months since NTP."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if "start_month" not in columns:
        return

    from datetime import datetime, timedelta

    rows = conn.execute(
        """
        SELECT t.id, t.start_month, t.finish_month, p.ntp_date, p.days_per_month
        FROM tasks t JOIN projects p ON p.id = t.project_id
        WHERE t.start_date = '' OR t.submission_date = ''
        """
    ).fetchall()
    for row in rows:
        try:
            ntp = datetime.strptime(str(row["ntp_date"])[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        per_month = float(row["days_per_month"] or 30.4375)
        start = ntp + timedelta(days=float(row["start_month"] or 0) * per_month)
        finish = ntp + timedelta(days=float(row["finish_month"] or 0) * per_month)
        conn.execute(
            "UPDATE tasks SET start_date = ?, submission_date = ? WHERE id = ?",
            (start.isoformat(), finish.isoformat(), row["id"]),
        )


def _ensure_workflow_steps(conn: sqlite3.Connection) -> None:
    """Gives every project the default design workflow if it has none."""
    from .workflow import default_steps

    projects = conn.execute(
        """
        SELECT id FROM projects
        WHERE id NOT IN (SELECT DISTINCT project_id FROM workflow_steps)
        """
    ).fetchall()
    for project in projects:
        for step in default_steps():
            conn.execute(
                """
                INSERT INTO workflow_steps (project_id, key, name, percent, anchor, offset_days, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project["id"], step["key"], step["name"], step["percent"],
                 step["anchor"], step["offset_days"], step["sort_order"]),
            )


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
