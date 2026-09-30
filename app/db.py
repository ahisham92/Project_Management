"""SQLite access. Uses the standard library only, so there is nothing to install
beyond Flask itself.
"""

from __future__ import annotations

import json
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
            # What is held back on a workflow line for answering comments, and
            # whether the reserve a clean Code A releases is pushed back into
            # that trade's open lines or simply left as a saving.
            ("projects", "comments_reserve_pct", "REAL NOT NULL DEFAULT 15"),
            ("projects", "redistribute_savings", "INTEGER NOT NULL DEFAULT 0"),
            # How the register makes a document number. A convention rather than
            # a counter, so the office's own numbering is what comes out.
            ("projects", "document_format", "TEXT NOT NULL DEFAULT ''"),
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
        _ensure_resource_weeks(conn)
        _ensure_register(conn)
        _ensure_crs(conn)
        _ensure_specs(conn)
        for table, column, definition in (
            # A workflow line that hands nothing over. Its hours are not lost:
            # they flow to whatever it feeds, so the deliverable that does go
            # out carries the whole cost of getting it there.
            ("tasks", "submits", "INTEGER NOT NULL DEFAULT 1"),
            ("document_kinds", "standard_hours", "REAL NOT NULL DEFAULT 0"),
            ("project_mix", "quantity", "REAL NOT NULL DEFAULT 0"),
            ("task_mix", "quantity", "REAL NOT NULL DEFAULT 0"),
            # A sign-in name the administrator gives an account, beside its email.
            ("users", "username", "TEXT"),
            # Which programs an account may open, comma-separated. NULL is every
            # program, which is what accounts made before the choice existed keep.
            ("users", "programs", "TEXT"),
        ):
            _ensure_column(conn, table, column, definition)
        # After the register's own tables, not with the other columns above:
        # foreign keys are on, and a column cannot point at a table that does
        # not exist yet.
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username"
                     " ON users(username COLLATE NOCASE) WHERE username IS NOT NULL")
        _ensure_column(conn, "time_entries", "submittal_id",
                       "INTEGER REFERENCES submittals(id) ON DELETE SET NULL")

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


def _ensure_resource_weeks(conn: sqlite3.Connection) -> None:
    """The headcounts somebody has set by hand, week by week and trade by trade.

    The plan says what a week wants; a team leader knows who is actually
    available. Only the number of people is kept — the hours that week is
    allowed are worked out from the programme every time and are not somebody's
    to type over, so a hand-set week shows what each of those engineers is
    carrying rather than quietly shrinking the scope.

    A row is only written when the figure differs from the plan's own, and
    deleted when it goes back to it, so the table holds the decisions and
    nothing else.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS resource_weeks (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            week       TEXT    NOT NULL,
            trade_id   INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
            engineers  REAL    NOT NULL DEFAULT 0,
            set_at     TEXT    NOT NULL DEFAULT (datetime('now')),
            user_id    INTEGER,
            UNIQUE (project_id, week, trade_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS resource_weeks_project "
                 "ON resource_weeks (project_id, week)")


def _ensure_specs(conn: sqlite3.Connection) -> None:
    """The specification writer: the master sections, and each project's copy.

    A section's text is kept as JSON — the paragraphs in order, each with its
    level and an id it keeps for life. The id is what lets a project's copy be
    compared with the master it came from, paragraph by paragraph, and what
    lets a newer master be brought into a copy without losing its amendments.
    Every saved master is kept as a version for the same reason: a copy is
    compared with the master as it was when it was taken.
    """
    fresh = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                         "AND name = 'spec_options'").fetchone() is None
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS spec_sections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            -- The kind of specification it belongs to (03A, 15A, 16A): each
            -- kind numbers its own sections, so 033000 is in two of them.
            family      TEXT    NOT NULL DEFAULT '15A',
            number      TEXT    NOT NULL,
            title       TEXT    NOT NULL DEFAULT '',
            body        TEXT    NOT NULL DEFAULT '[]',
            version     INTEGER NOT NULL DEFAULT 1,
            note        TEXT    NOT NULL DEFAULT '',
            updated_by  TEXT    NOT NULL DEFAULT '',
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            applies     TEXT    NOT NULL DEFAULT '',
            UNIQUE (family, number)
        );
        CREATE TABLE IF NOT EXISTS spec_section_versions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            section_id  INTEGER NOT NULL REFERENCES spec_sections(id) ON DELETE CASCADE,
            version     INTEGER NOT NULL,
            title       TEXT    NOT NULL DEFAULT '',
            body        TEXT    NOT NULL DEFAULT '[]',
            note        TEXT    NOT NULL DEFAULT '',
            saved_by    TEXT    NOT NULL DEFAULT '',
            saved_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (section_id, version)
        );
        -- The choices a project makes that switch paragraphs in and out.
        CREATE TABLE IF NOT EXISTS spec_options (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key         TEXT    NOT NULL UNIQUE,
            label       TEXT    NOT NULL DEFAULT '',
            choices     TEXT    NOT NULL DEFAULT '',
            default_value TEXT  NOT NULL DEFAULT '',
            position    INTEGER NOT NULL DEFAULT 0
        );
        -- The words projects differ on, written {{key}} in the text.
        CREATE TABLE IF NOT EXISTS spec_variables (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            key         TEXT    NOT NULL UNIQUE,
            label       TEXT    NOT NULL DEFAULT '',
            default_value TEXT  NOT NULL DEFAULT '',
            position    INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS spec_sets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT    NOT NULL DEFAULT '',
            code         TEXT    NOT NULL DEFAULT '',
            client       TEXT    NOT NULL DEFAULT '',
            header_left  TEXT    NOT NULL DEFAULT '',
            header_right TEXT    NOT NULL DEFAULT '',
            doc_code     TEXT    NOT NULL DEFAULT '',
            revision     TEXT    NOT NULL DEFAULT '0',
            issue_date   TEXT    NOT NULL DEFAULT '',
            file_pattern TEXT    NOT NULL DEFAULT 'SPC-{number}',
            options      TEXT    NOT NULL DEFAULT '{}',
            variables    TEXT    NOT NULL DEFAULT '{}',
            created_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS spec_set_sections (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id       INTEGER NOT NULL REFERENCES spec_sets(id) ON DELETE CASCADE,
            -- The master it was copied from, and which version of it. A copy
            -- outlives its master being deleted: it is the project's text.
            section_id   INTEGER REFERENCES spec_sections(id) ON DELETE SET NULL,
            base_version INTEGER NOT NULL DEFAULT 0,
            number       TEXT    NOT NULL DEFAULT '',
            title        TEXT    NOT NULL DEFAULT '',
            doc_code     TEXT    NOT NULL DEFAULT '',
            body         TEXT    NOT NULL DEFAULT '[]',
            updated_by   TEXT    NOT NULL DEFAULT '',
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            UNIQUE (set_id, number)
        );
        -- The Word document every section is issued in: its styles, page,
        -- header and footer. One, replaced rather than versioned.
        CREATE TABLE IF NOT EXISTS spec_template (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            filename    TEXT    NOT NULL DEFAULT '',
            content     BLOB    NOT NULL,
            user_name   TEXT    NOT NULL DEFAULT '',
            added_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.execute("CREATE TABLE IF NOT EXISTS spec_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    seeded = conn.execute("SELECT value FROM spec_meta WHERE key = 'seed'").fetchone()
    upgrading = not fresh and int(seeded[0] if seeded else 0) < SPEC_SEED_VERSION
    for column, definition in (("grp", "TEXT NOT NULL DEFAULT ''"),
                               ("kind", "TEXT NOT NULL DEFAULT 'one'")):
        _ensure_column(conn, "spec_options", column, definition)
    # When a library section belongs in a project, as a condition on its choices.
    _ensure_column(conn, "spec_sections", "applies", "TEXT NOT NULL DEFAULT ''")
    _spec_families(conn)
    # A project's kind of specification; the library sections it took out that
    # its answers call for (so they are not put back); what its model said.
    _ensure_column(conn, "spec_sets", "family", "TEXT NOT NULL DEFAULT '15A'")
    _ensure_column(conn, "spec_sets", "declined", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "spec_sets", "model", "TEXT NOT NULL DEFAULT ''")
    _ensure_column(conn, "spec_sets", "set_by", "TEXT NOT NULL DEFAULT '{}'")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS spec_family_templates ("
        " family TEXT PRIMARY KEY, filename TEXT NOT NULL DEFAULT '', content BLOB NOT NULL,"
        " user_name TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL DEFAULT (datetime('now')))")
    # Whether a project is held back until every check item is accepted or rejected,
    # and what was decided about each.
    _ensure_column(conn, "spec_sets", "hold_issue", "INTEGER NOT NULL DEFAULT 1")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS spec_check_settled ("
        " set_id INTEGER NOT NULL REFERENCES spec_sets(id) ON DELETE CASCADE,"
        " key TEXT NOT NULL, state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '',"
        " settled_by TEXT NOT NULL DEFAULT '', settled_at TEXT NOT NULL DEFAULT (datetime('now')),"
        " PRIMARY KEY (set_id, key))")

    from .specs_seed import EQUIVALENTS, OPTIONS, VARIABLES, WITHDRAWN, WORDING

    if upgrading:
        # A library started on an earlier starting list gets what the newer
        # one adds; its own answers and wording are kept.
        merge_spec_seed(conn)
    conn.execute("INSERT OR REPLACE INTO spec_meta (key, value) VALUES ('seed', ?)",
                 (str(SPEC_SEED_VERSION),))

    if fresh:
        # A start, to be changed: the questions every project answers, and
        # the words every project fills in.
        conn.executemany(
            "INSERT OR IGNORE INTO spec_options (key, label, choices, default_value, grp, kind, "
            "position) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(*row, i) for i, row in enumerate(OPTIONS, start=1)])
        conn.executemany(
            "INSERT OR IGNORE INTO spec_variables (key, label, default_value, position) "
            "VALUES (?, ?, ?, ?)", [(*row, i) for i, row in enumerate(VARIABLES, start=1)])

    # The standards: what each is on the other basis, and what has been
    # withdrawn. Seeded once, when the tables first appear.
    new_tables = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                              "AND name = 'spec_standards'").fetchone() is None
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS spec_standards (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            topic     TEXT NOT NULL DEFAULT '',
            bs        TEXT NOT NULL DEFAULT '',
            us        TEXT NOT NULL DEFAULT '',
            position  INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS spec_withdrawn (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            old       TEXT NOT NULL DEFAULT '',
            new       TEXT NOT NULL DEFAULT '',
            note      TEXT NOT NULL DEFAULT '',
            position  INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    # The office's words, and words the project's scope rewords; and the
    # suggestions somebody chose to leave as they are.
    new_wording = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' "
                               "AND name = 'spec_wording'").fetchone() is None
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS spec_wording (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            find        TEXT NOT NULL DEFAULT '',
            replace     TEXT NOT NULL DEFAULT '',
            note        TEXT NOT NULL DEFAULT '',
            cond        TEXT NOT NULL DEFAULT '',
            unless_next TEXT NOT NULL DEFAULT '',
            position    INTEGER NOT NULL DEFAULT 0
        );
        -- scope 0 is the library; otherwise the specification's id.
        CREATE TABLE IF NOT EXISTS spec_ignored (
            scope   INTEGER NOT NULL DEFAULT 0,
            words   TEXT    NOT NULL,
            UNIQUE (scope, words)
        );
        """
    )
    if new_wording:
        conn.executemany("INSERT INTO spec_wording (find, replace, note, cond, unless_next, position) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         [(*row, i) for i, row in enumerate(WORDING, start=1)])
    if new_tables:
        conn.executemany("INSERT INTO spec_standards (topic, bs, us, position) VALUES (?, ?, ?, ?)",
                         [(*row, i) for i, row in enumerate(EQUIVALENTS, start=1)])
        conn.executemany("INSERT INTO spec_withdrawn (old, new, note, position) VALUES (?, ?, ?, ?)",
                         [(*row, i) for i, row in enumerate(WITHDRAWN, start=1)])


# Raised whenever the starting list of questions and words gains something an
# existing library should be offered.
SPEC_SEED_VERSION = 4


def _spec_families(conn: sqlite3.Connection) -> None:
    """A library from before there were kinds of specification: its sections
    were numbered once across the lot. They become 15A's — the American
    MasterFormat sections every library so far was made of — and the table is
    rebuilt so that each kind numbers its own.

    SQLite cannot drop a UNIQUE constraint, so the table is copied: foreign
    keys are off while it is, or dropping the old one would take every
    version and project copy with it.
    """
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(spec_sections)")}
    if "family" in columns:
        return
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            """
            BEGIN;
            CREATE TABLE spec_sections_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                family      TEXT    NOT NULL DEFAULT '15A',
                number      TEXT    NOT NULL,
                title       TEXT    NOT NULL DEFAULT '',
                body        TEXT    NOT NULL DEFAULT '[]',
                version     INTEGER NOT NULL DEFAULT 1,
                note        TEXT    NOT NULL DEFAULT '',
                updated_by  TEXT    NOT NULL DEFAULT '',
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                applies     TEXT    NOT NULL DEFAULT '',
                UNIQUE (family, number)
            );
            INSERT INTO spec_sections_new (id, family, number, title, body, version, note,
                                           updated_by, updated_at, applies)
                SELECT id, '15A', number, title, body, version, note, updated_by, updated_at,
                       applies FROM spec_sections;
            DROP TABLE spec_sections;
            ALTER TABLE spec_sections_new RENAME TO spec_sections;
            COMMIT;
            """)
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def merge_spec_seed(conn: sqlite3.Connection) -> int:
    """The starting questions and words a library lacks, added. A question it
    already has keeps its wording and default; it only gains the starting
    choices it did not offer, and a group if it had none."""
    from .specs_seed import OPTIONS, VARIABLES

    added = 0
    with conn:
        last = conn.execute("SELECT COALESCE(MAX(position), 0) FROM spec_options").fetchone()[0]
        for key, label, choices, default, grp, kind in OPTIONS:
            have = conn.execute("SELECT choices, grp FROM spec_options WHERE key = ?",
                                (key,)).fetchone()
            if have is None:
                last += 1
                conn.execute(
                    "INSERT INTO spec_options (key, label, choices, default_value, grp, kind, "
                    "position) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (key, label, choices, default, grp, kind, last))
                added += 1
                continue
            offered = [c for c in have[0].split("|") if c.strip()]
            if key == "standards" and offered == ["BS EN", "ASTM"]:
                offered = ["BS EN", "ACI/ASTM"]     # the first release's wording
                for spec_set in conn.execute("SELECT id, options FROM spec_sets").fetchall():
                    chosen = json.loads(spec_set[1] or "{}")
                    if chosen.get("standards") == "ASTM":
                        chosen["standards"] = "ACI/ASTM"
                        conn.execute("UPDATE spec_sets SET options = ? WHERE id = ?",
                                     (json.dumps(chosen, ensure_ascii=False), spec_set[0]))
            known = {c.strip().lower() for c in offered}
            extra = [c for c in choices.split("|") if c.strip().lower() not in known]
            if extra or not have[1]:
                conn.execute("UPDATE spec_options SET choices = ?, grp = ? WHERE key = ?",
                             ("|".join(offered + extra), have[1] or grp, key))
                added += len(extra)
        # AWS D1.1 was the first list's counterpart for headed studs as well as
        # for structural welding, so welding citations became the stud standard.
        conn.execute("UPDATE spec_standards SET us = 'ASTM A108' "
                     "WHERE bs = 'BS EN ISO 13918' AND us = 'AWS D1.1'")
        last = conn.execute("SELECT COALESCE(MAX(position), 0) FROM spec_variables").fetchone()[0]
        for key, label, default in VARIABLES:
            if conn.execute("SELECT 1 FROM spec_variables WHERE key = ?", (key,)).fetchone():
                continue
            last += 1
            conn.execute("INSERT INTO spec_variables (key, label, default_value, position) "
                         "VALUES (?, ?, ?, ?)", (key, label, default, last))
            added += 1
    return added


def _ensure_crs(conn: sqlite3.Connection) -> None:
    """The comment response sheets.

    A sheet is a client's comments on one submission, so it hangs off the
    document in the register that went out — the same drawing or report the
    programme costed and the register numbered. That is the whole point of it
    living in this database rather than in a browser: a comment is against a
    real document, raised by a real person, and owed by a real trade.

    A sheet may also stand on its own, for comments that arrive before anybody
    has raised the document they are about, or for a submission from before the
    register existed. Hence the nullable submittal.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crs_sheets (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            -- The document in the register these comments are about, where
            -- there is one. Set null rather than cascading: losing the sheet
            -- because somebody tidied the register would be worse.
            submittal_id INTEGER REFERENCES submittals(id) ON DELETE SET NULL,
            task_id      INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
            title        TEXT    NOT NULL DEFAULT '',
            revision     TEXT    NOT NULL DEFAULT '',
            -- What the client's own header says. Kept as given, because a
            -- transmittal quotes it back and it has to match.
            report_no    TEXT    NOT NULL DEFAULT '',
            report_date  TEXT    NOT NULL DEFAULT '',
            contract_no  TEXT    NOT NULL DEFAULT '',
            drf_ref      TEXT    NOT NULL DEFAULT '',
            drf_rev      TEXT    NOT NULL DEFAULT '',
            drf_date     TEXT    NOT NULL DEFAULT '',
            stage        TEXT    NOT NULL DEFAULT '',
            engineer     TEXT    NOT NULL DEFAULT '',
            contractor   TEXT    NOT NULL DEFAULT '',
            -- How long a comment has to be answered, when nobody says.
            due_days     INTEGER NOT NULL DEFAULT 14,
            received_on  TEXT    NOT NULL DEFAULT '',
            closed_on    TEXT    NOT NULL DEFAULT '',
            note         TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS crs_sheets_project "
                 "ON crs_sheets (project_id, submittal_id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crs_comments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            sheet_id      INTEGER NOT NULL REFERENCES crs_sheets(id) ON DELETE CASCADE,
            -- The client's own numbering, kept as text: "12", "12a" and "3.4"
            -- are all things a comment register has called a row.
            sn            TEXT    NOT NULL DEFAULT '',
            reviewer      TEXT    NOT NULL DEFAULT '',
            source        TEXT    NOT NULL DEFAULT '',
            observation   TEXT    NOT NULL DEFAULT '',
            reference     TEXT    NOT NULL DEFAULT '',
            -- Which of our trades owes the answer. The discipline the client
            -- wrote is kept beside it, because the two do not always agree and
            -- theirs is what their sheet says.
            trade_id      INTEGER REFERENCES trades(id) ON DELETE SET NULL,
            discipline    TEXT    NOT NULL DEFAULT '',
            returned_code TEXT    NOT NULL DEFAULT '',
            response      TEXT    NOT NULL DEFAULT '',
            signoff       TEXT    NOT NULL DEFAULT 'open',
            due_date      TEXT    NOT NULL DEFAULT '',
            closed_on     TEXT    NOT NULL DEFAULT '',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS crs_comments_sheet "
                 "ON crs_comments (sheet_id, sort_order, id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crs_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id INTEGER NOT NULL REFERENCES crs_comments(id) ON DELETE CASCADE,
            user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
            author     TEXT    NOT NULL DEFAULT '',
            role       TEXT    NOT NULL DEFAULT '',
            body       TEXT    NOT NULL DEFAULT '',
            -- Held back until the sheet goes out, so a half-written answer is
            -- not something the client can read.
            published  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS crs_messages_comment "
                 "ON crs_messages (comment_id, id)")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS crs_files (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            comment_id INTEGER REFERENCES crs_comments(id) ON DELETE CASCADE,
            message_id INTEGER REFERENCES crs_messages(id) ON DELETE CASCADE,
            sheet_id   INTEGER REFERENCES crs_sheets(id) ON DELETE CASCADE,
            name       TEXT    NOT NULL DEFAULT '',
            mimetype   TEXT    NOT NULL DEFAULT '',
            bytes      INTEGER NOT NULL DEFAULT 0,
            content    BLOB    NOT NULL,
            user_name  TEXT    NOT NULL DEFAULT '',
            made_at    TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS crs_files_comment ON crs_files (comment_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS crs_files_message ON crs_files (message_id)")


def _ensure_register(conn: sqlite3.Connection) -> None:
    """The register of everything issued, and what a deliverable is made of.

    A deliverable is a line on a programme; it is not a thing anybody hands
    over. What gets handed over is a report, a set of drawings, a
    specification — and those are what carry numbers, go out on transmittals and
    come back with comments. Four tables:

    `document_kinds` is what this office issues, with the code that goes in a
    number. `project_mix` and `task_mix` say what a deliverable is made of and
    in what proportion — the project's shape, and the one line that is different.
    `submittals` is the register itself, and `submittal_trades` is who is
    actually writing each one, which a programme cannot tell you: a design basis
    is one document four disciplines write at once.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_kinds (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            key        TEXT    NOT NULL,
            name       TEXT    NOT NULL,
            code       TEXT    NOT NULL DEFAULT '',
            many       INTEGER NOT NULL DEFAULT 0,
            -- What one of these costs, as a rule of thumb: a drawing is 35
            -- hours. It is what turns "six drawings and a report" into a
            -- weight, and what the real thing is measured against.
            standard_hours REAL NOT NULL DEFAULT 0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            UNIQUE (project_id, key)
        )
        """
    )
    # The project's default mix, and the deliverables that differ from it.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_mix (
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            kind_id    INTEGER NOT NULL REFERENCES document_kinds(id) ON DELETE CASCADE,
            percent    REAL    NOT NULL DEFAULT 0,
            -- How many of this kind the package contains. Given one, the
            -- weight works itself out; left at nothing, the percent above is
            -- what somebody typed and the count is worked back from it.
            quantity   REAL    NOT NULL DEFAULT 0,
            PRIMARY KEY (project_id, kind_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_mix (
            task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            kind_id INTEGER NOT NULL REFERENCES document_kinds(id) ON DELETE CASCADE,
            percent REAL    NOT NULL DEFAULT 0,
            quantity REAL   NOT NULL DEFAULT 0,
            PRIMARY KEY (task_id, kind_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submittals (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id    INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            kind_id    INTEGER NOT NULL REFERENCES document_kinds(id) ON DELETE CASCADE,
            number     TEXT    NOT NULL DEFAULT '',
            title      TEXT    NOT NULL DEFAULT '',
            weight     REAL    NOT NULL DEFAULT 1,
            revision   INTEGER NOT NULL DEFAULT 0,
            status     TEXT    NOT NULL DEFAULT 'planned',
            planned_date TEXT  NOT NULL DEFAULT '',
            issued_date  TEXT  NOT NULL DEFAULT '',
            note       TEXT    NOT NULL DEFAULT '',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS submittals_project "
                 "ON submittals (project_id, task_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS submittals_number "
                 "ON submittals (project_id, number) WHERE number != ''")
    # Who is issuing it, and how much of it is theirs. Empty means the document
    # is split the way its deliverable is, which is the usual answer.
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submittal_trades (
            submittal_id INTEGER NOT NULL REFERENCES submittals(id) ON DELETE CASCADE,
            trade_id     INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
            share        REAL    NOT NULL DEFAULT 0,
            PRIMARY KEY (submittal_id, trade_id)
        )
        """
    )


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
