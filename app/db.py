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


def live_database() -> Path:
    """The database this app is actually using.

    `database_path` is where one would be by default; an app can be told to use
    another, and anything that copies or replaces the database has to follow
    the one being served rather than the one that would have been.
    """
    from flask import current_app, has_app_context

    if has_app_context():
        configured = current_app.config.get("DATABASE")
        if configured:
            return Path(configured)
    return database_path()


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
            # Which register an item belongs to: the client's minutes, or the
            # internal weekly one. Two registers, one set of rules.
            ("meetings", "kind", "TEXT NOT NULL DEFAULT 'client'"),
            ("meeting_items", "kind", "TEXT NOT NULL DEFAULT 'client'"),
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
            # What the issued minutes carry on their first and last pages: who
            # wrote them, who accepts them, the day they went out, and what was
            # attached. Blank until somebody fills them in, and the signature
            # itself is always a line to sign on rather than a name typed for
            # somebody else.
            ("meetings", "prepared_by", "TEXT NOT NULL DEFAULT ''"),
            ("meetings", "reviewed_by", "TEXT NOT NULL DEFAULT ''"),
            ("meetings", "issue_date", "TEXT NOT NULL DEFAULT ''"),
            ("meetings", "attachment", "TEXT NOT NULL DEFAULT ''"),
            ("meetings", "purpose", "TEXT NOT NULL DEFAULT ''"),
            # Which office carries a trade. Blank until somebody says, because
            # an unanswered question should read as one rather than as Beirut.
            ("trades", "office", "TEXT NOT NULL DEFAULT ''"),
            # How the attendance table is ordered in an issued set of minutes:
            # as the roster lists them, or client first and down the seniority.
            ("projects", "attendee_order", "TEXT NOT NULL DEFAULT 'roster'"),
            # Resource planning: the margin held back off every trade's budget,
            # and one engineer's week.
            ("projects", "target_margin_pct", "REAL NOT NULL DEFAULT 12"),
            ("projects", "hours_per_week", "REAL NOT NULL DEFAULT 40"),
        ):
            _ensure_column(conn, table, column, definition)

        _ensure_calendars(conn)
        _ensure_backup_log(conn)
        _ensure_chat_log(conn)
        _ensure_attachments(conn)
        _ensure_impacts(conn)
        _ensure_snapshots(conn)
        _ensure_templates(conn)
        _ensure_documents(conn)

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
    # Which office a team works in. A deliverable's working week follows the
    # trades carrying it, through this, rather than being set line by line.
    _ensure_column(conn, "calendars", "office", "TEXT NOT NULL DEFAULT ''")
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


def _ensure_backup_log(conn: sqlite3.Connection) -> None:
    """What happened the last time a backup ran.

    Kept so the screen can say whether the nightly one is actually working. A
    backup that has been failing quietly for three weeks is worse than none,
    because it is the one you were counting on.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS backup_runs (
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at TEXT    NOT NULL,
          ok         INTEGER NOT NULL DEFAULT 0,
          where_to   TEXT    NOT NULL DEFAULT '',
          bytes      INTEGER NOT NULL DEFAULT 0,
          detail     TEXT    NOT NULL DEFAULT '',
          link       TEXT    NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_backup_runs_when ON backup_runs(started_at DESC)")


def _ensure_attachments(conn: sqlite3.Connection) -> None:
    """What is attached to a set of minutes.

    The file itself is kept in the database rather than beside it, because the
    nightly backup uploads the database: an attachment in a folder next to it is
    one that does not come back when somebody restores. A PDF of a few hundred
    kilobytes in a BLOB is nothing to SQLite, and it keeps "the minutes" one
    thing rather than two.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meeting_attachments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            meeting_id  INTEGER NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
            name        TEXT    NOT NULL DEFAULT '',
            filename    TEXT    NOT NULL DEFAULT '',
            bytes       INTEGER NOT NULL DEFAULT 0,
            pages       INTEGER NOT NULL DEFAULT 0,
            content     BLOB    NOT NULL,
            user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
            added_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            sort_order  INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attachments_meeting "
                 "ON meeting_attachments(meeting_id, sort_order)")


def _ensure_documents(conn: sqlite3.Connection) -> None:
    """Every document the app has handed out, as the bytes that were handed out.

    A deck built on Tuesday is not the deck the same dates build today: the
    project has moved. So "let me see the presentation Ola sent the client" can
    only be answered by keeping Ola's copy, not by rebuilding one from the same
    query string.

    Kept in the database with everything else, so the nightly backup carries
    them, and trimmed to the most recent few dozen per project so a year of
    weekly reports does not quietly become the largest thing in the file.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind        TEXT    NOT NULL DEFAULT '',
            name        TEXT    NOT NULL DEFAULT '',
            filename    TEXT    NOT NULL DEFAULT '',
            mimetype    TEXT    NOT NULL DEFAULT '',
            bytes       INTEGER NOT NULL DEFAULT 0,
            content     BLOB    NOT NULL,
            note        TEXT    NOT NULL DEFAULT '',
            user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
            user_name   TEXT    NOT NULL DEFAULT '',
            made_at     TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS documents_project "
                 "ON documents (project_id, made_at DESC)")


def _ensure_templates(conn: sqlite3.Connection) -> None:
    """The Word document a project's minutes are built from.

    Kept in the database with everything else, so the nightly backup carries it
    and a restore brings the practice's own layout back with the data. One per
    project per kind, replaced rather than versioned: a template is the current
    form, and the last one is not something anybody asks for.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_templates (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind        TEXT    NOT NULL DEFAULT 'minutes',
            filename    TEXT    NOT NULL DEFAULT '',
            bytes       INTEGER NOT NULL DEFAULT 0,
            fields      TEXT    NOT NULL DEFAULT '',
            content     BLOB    NOT NULL,
            user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
            user_name   TEXT    NOT NULL DEFAULT '',
            added_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS templates_one_per_kind "
                 "ON document_templates (project_id, kind)")


def _ensure_snapshots(conn: sqlite3.Connection) -> None:
    """Where every date stood before something moved a lot of them at once.

    A squeeze changes fifty lines. "Put it back to four months" is then a real
    question, and the only honest answer is the dates as they were rather than
    the same arithmetic run backwards, which does not return where it started
    once anything has rounded.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedule_snapshots (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            made_at    TEXT NOT NULL DEFAULT (datetime('now')),
            user_id    INTEGER,
            user_name  TEXT NOT NULL DEFAULT '',
            note       TEXT NOT NULL DEFAULT '',
            lines      INTEGER NOT NULL DEFAULT 0,
            payload    TEXT NOT NULL DEFAULT '[]'
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS snapshots_project "
                 "ON schedule_snapshots (project_id, made_at DESC)")


def _ensure_impacts(conn: sqlite3.Connection) -> None:
    """What a minuted item can be said to affect.

    Started as four words in the code — none, time, cost, both — which is fine
    until a project needs "Dredging Limits". Kept per project so the list is
    something somebody edits on the Setup sheet rather than something that
    needs a release.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS impact_options (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            key          TEXT    NOT NULL,
            name         TEXT    NOT NULL,
            affects_time INTEGER NOT NULL DEFAULT 0,
            affects_cost INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            UNIQUE (project_id, key)
        )
        """
    )


def _ensure_chat_log(conn: sqlite3.Connection) -> None:
    """What everybody has asked Carmen, and what she said back.

    Kept so somebody can see how it is actually being used — which is a
    different question from whether it works — and uploaded to Drive once a day
    as a plain text file that reads without this program.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            asked_at    TEXT NOT NULL,
            project_id  INTEGER,
            user_id     INTEGER,
            user_name   TEXT NOT NULL DEFAULT '',
            question    TEXT NOT NULL DEFAULT '',
            answer      TEXT NOT NULL DEFAULT '',
            tools_used  TEXT NOT NULL DEFAULT '',
            staged      INTEGER NOT NULL DEFAULT 0,
            applied     INTEGER NOT NULL DEFAULT 0,
            trouble     TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS chat_log_day ON chat_log (asked_at)")

    # A conversation, so somebody can come back to a thread and carry on rather
    # than starting from nothing every time. The questions and answers stay in
    # chat_log — this is the spine they hang from.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_threads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER,
            user_id     INTEGER,
            user_name   TEXT NOT NULL DEFAULT '',
            title       TEXT NOT NULL DEFAULT '',
            started_at  TEXT NOT NULL DEFAULT (datetime('now')),
            last_at     TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS chat_threads_project "
                 "ON chat_threads (project_id, last_at DESC)")
    _ensure_column(conn, "chat_log", "thread_id", "INTEGER")
    # What each answer cost, so "is this expensive" is a number rather than a
    # feeling. Cache reads are counted apart because they are charged at a
    # tenth of fresh input.
    for column in ("tokens_in", "tokens_out", "tokens_cached", "tokens_written"):
        _ensure_column(conn, "chat_log", column, "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "chat_log", "from_cache", "INTEGER NOT NULL DEFAULT 0")

    # Answers worth not paying for twice. A question asked again while nothing
    # on the project has changed has the same answer as last time, and the
    # cheapest call to an API is the one that is not made.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_answers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id  INTEGER NOT NULL,
            question    TEXT NOT NULL,
            pulse       TEXT NOT NULL DEFAULT '',
            answer      TEXT NOT NULL DEFAULT '',
            tools_used  TEXT NOT NULL DEFAULT '',
            asked_at    TEXT NOT NULL DEFAULT (datetime('now')),
            used        INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS chat_answers_one "
                 "ON chat_answers (project_id, question)")

    # What was attached to a question. Kept in the database like everything
    # else here, so a conversation reopened next week still has the drawing
    # somebody was asking about.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_files (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            thread_id  INTEGER,
            chat_id    INTEGER,
            user_id    INTEGER,
            name       TEXT NOT NULL DEFAULT '',
            kind       TEXT NOT NULL DEFAULT '',
            bytes      INTEGER NOT NULL DEFAULT 0,
            content    BLOB NOT NULL,
            added_at   TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS chat_files_thread ON chat_files (thread_id, id)")


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
