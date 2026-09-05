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
            # An item is owned by a party — PM, Client, MR — rather than by a
            # named person, who changes while the responsibility does not.
            ("meeting_items", "owner_code", "TEXT NOT NULL DEFAULT ''"),
            # How the schedule is entered: start + duration, or start and finish.
            ("projects", "schedule_mode", "TEXT NOT NULL DEFAULT 'duration'"),
            # What the client returned: a Code A approves, B and C mean rework.
            ("task_revisions", "code", "TEXT NOT NULL DEFAULT ''"),
            # The day the comments landed, so rework draws on the programme.
            ("task_revisions", "comments_date", "TEXT NOT NULL DEFAULT ''"),
            # How one deliverable waits for another: FS or SS.
            ("task_links", "kind", "TEXT NOT NULL DEFAULT 'FS'"),
            # Where a box sits on the dependency diagram once it has been
            # dragged. Empty means the automatic layout decides.
            ("tasks", "node_x", "REAL"),
            ("tasks", "node_y", "REAL"),
            # Which team's working week and holidays a deliverable is planned
            # against. Empty means the project's default team.
            ("tasks", "calendar_id", "INTEGER"),
            ("projects", "calendar_id", "INTEGER"),
        ):
            _ensure_column(conn, table, column, definition)

        _ensure_calendars(conn)

        _migrate_months_to_dates(conn)
        _ensure_workflow_steps(conn)
        _normalise_item_numbers(conn)
        _migrate_item_owners_and_trades(conn)
        _install_pulse_triggers(conn)
        conn.commit()
    finally:
        conn.close()


def _ensure_calendars(conn: sqlite3.Connection) -> None:
    """The working calendars a project plans against, and their holidays.

    Every project gets one to begin with — every day a working day — so nothing
    moves until somebody says a team keeps a shorter week. A holiday with no
    calendar belongs to all of them.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS calendars (
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          name       TEXT    NOT NULL,
          workdays   TEXT    NOT NULL DEFAULT '1111111',
          sort_order INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_calendars_project ON calendars(project_id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS holidays (
          id           INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          calendar_id  INTEGER REFERENCES calendars(id) ON DELETE CASCADE,
          holiday_date TEXT    NOT NULL,
          name         TEXT    NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_holidays_project ON holidays(project_id)")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_holidays_once "
        "ON holidays(project_id, IFNULL(calendar_id, 0), holiday_date)"
    )

    for row in conn.execute(
        "SELECT id FROM projects WHERE id NOT IN (SELECT project_id FROM calendars)"
    ).fetchall():
        conn.execute(
            "INSERT INTO calendars (project_id, name, workdays, sort_order) VALUES (?, ?, ?, 1)",
            (row["id"], "Every day", "1111111"),
        )
    conn.execute(
        """
        UPDATE projects SET calendar_id = (
          SELECT id FROM calendars WHERE calendars.project_id = projects.id
          ORDER BY sort_order, id LIMIT 1
        ) WHERE calendar_id IS NULL
        """
    )


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


# Every table a project's screens read from, and how a row of it finds its
# project. The counter these bump is what tells an open page that somebody else
# has changed something.
_PULSE_TABLES: tuple[tuple[str, str], ...] = (
    ("projects", "id"),
    ("tasks", "project_id"),
    ("task_links", "project_id"),
    ("task_revisions", "project_id"),
    ("progress_updates", "project_id"),
    ("time_entries", "project_id"),
    ("trades", "project_id"),
    ("sections", "project_id"),
    ("workflow_steps", "project_id"),
    ("project_members", "project_id"),
    ("attendees", "project_id"),
    ("meetings", "project_id"),
    ("calendars", "project_id"),
    ("holidays", "project_id"),
    ("meeting_items", "project_id"),
)

# These hang off a parent rather than off the project, so they find it through one.
_PULSE_CHILDREN: tuple[tuple[str, str], ...] = (
    ("task_allocations", "(SELECT project_id FROM tasks WHERE id = {row}.task_id)"),
    ("meeting_attendance", "(SELECT project_id FROM meetings WHERE id = {row}.meeting_id)"),
    ("meeting_item_trades", "(SELECT project_id FROM meeting_items WHERE id = {row}.item_id)"),
)


def _install_pulse_triggers(conn: sqlite3.Connection) -> None:
    """Counts changes per project, in the database itself.

    A page open in somebody's browser asks for this counter every few seconds to
    see whether anyone else has changed anything. Doing it with triggers rather
    than by hand means no write can forget to say so — and unlike a timestamp,
    a counter cannot miss two changes that land in the same second.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_pulse (
          project_id INTEGER PRIMARY KEY,
          version    INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    def bump(source: str) -> str:
        return (
            f"INSERT INTO project_pulse (project_id, version) SELECT {source}, 1 "
            f"WHERE {source} IS NOT NULL "
            "ON CONFLICT(project_id) DO UPDATE SET version = version + 1;"
        )

    existing = {row["name"] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'")}

    for table, column in _PULSE_TABLES:
        if table not in existing:
            continue
        for action, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS pulse_{table}_{action.lower()} "
                f"AFTER {action} ON {table} BEGIN {bump(f'{row}.{column}')} END"
            )

    for table, lookup in _PULSE_CHILDREN:
        if table not in existing:
            continue
        for action, row in (("INSERT", "NEW"), ("UPDATE", "NEW"), ("DELETE", "OLD")):
            conn.execute(
                f"CREATE TRIGGER IF NOT EXISTS pulse_{table}_{action.lower()} "
                f"AFTER {action} ON {table} BEGIN {bump(lookup.format(row=row))} END"
            )


def _migrate_item_owners_and_trades(conn: sqlite3.Connection) -> None:
    """Carries older items onto the party owner and the many-trade model.

    An item used to name a person as its owner and to sit with one trade. The
    person's name is kept as free text so nothing is lost until someone picks a
    party for that item, and the single trade becomes the first of its trades.
    """
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if "meeting_items" not in tables:
        return

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(meeting_items)")}
    if "owner_id" in columns and "attendees" in tables:
        conn.execute(
            """
            UPDATE meeting_items
               SET owner_name = COALESCE(
                       (SELECT name FROM attendees WHERE attendees.id = meeting_items.owner_id), '')
             WHERE owner_id IS NOT NULL AND owner_name = ''
            """
        )
    if "trade_id" in columns and "meeting_item_trades" in tables:
        conn.execute(
            """
            INSERT OR IGNORE INTO meeting_item_trades (item_id, trade_id)
            SELECT id, trade_id FROM meeting_items WHERE trade_id IS NOT NULL
            """
        )


def _normalise_item_numbers(conn: sqlite3.Connection) -> None:
    """Gives every minuted item the number its position implies.

    Item numbers used to be typed, so two items could carry the same one. They
    are now the item's position within its meeting, which makes a duplicate
    impossible and lets a number follow its item when it is moved. This puts
    existing registers on the same footing, keeping the order they are already
    in, and touches only the rows whose number or position actually changes.
    """
    if not conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'meeting_items'"
    ).fetchone():
        return

    from .minutes import ref_key, renumber

    groups = conn.execute(
        "SELECT DISTINCT project_id, meeting_id FROM meeting_items"
    ).fetchall()
    for group in groups:
        if group["meeting_id"] is None:
            rows = conn.execute(
                "SELECT id, ref, sort_order FROM meeting_items "
                "WHERE project_id = ? AND meeting_id IS NULL",
                (group["project_id"],),
            ).fetchall()
            meeting_ref = ""
        else:
            rows = conn.execute(
                "SELECT id, ref, sort_order FROM meeting_items "
                "WHERE project_id = ? AND meeting_id = ?",
                (group["project_id"], group["meeting_id"]),
            ).fetchall()
            meeting = conn.execute(
                "SELECT ref FROM meetings WHERE id = ?", (group["meeting_id"],)
            ).fetchone()
            meeting_ref = meeting["ref"] if meeting else ""

        # The order already on screen is the one to keep: by item number, then
        # by the order the items were added.
        ordered = sorted(rows, key=lambda r: (r["sort_order"], ref_key(r["ref"]), r["id"]))
        current = {r["id"]: (r["sort_order"], r["ref"]) for r in rows}
        for target in renumber([dict(r) for r in ordered], meeting_ref):
            if current[target["id"]] != (target["sort_order"], target["ref"]):
                conn.execute(
                    "UPDATE meeting_items SET sort_order = ?, ref = ? WHERE id = ?",
                    (target["sort_order"], target["ref"], target["id"]),
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
