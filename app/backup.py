"""A backup of everything: one file holding the whole database.

The Setup sheet's Excel export is the *setup* of one project — deliverables,
weights, trades, the workflow. It is not a backup. It has no progress history,
no time entries, no minutes, no dependencies, no teams or holidays, and no
other project. This does.

Two things matter for a backup to be worth having:

* **It has to be consistent.** Copying a live SQLite file while somebody is
  saving can capture a half-written page, and the copy will not open. SQLite's
  own online backup walks the database under a read lock and produces a file
  that is always valid, so the app carries on serving while it runs.
* **It has to be restorable.** A backup nobody has ever put back is a guess, so
  restoring is a command here rather than an exercise for the day it is needed,
  and every backup carries a manifest saying what is in it — if the file that
  comes back off the shelf has one project and yesterday's had six, that is
  visible before it is restored over anything.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# What goes inside the zip. The database keeps its own name so a restore is
# obvious, and the manifest sits beside it in plain JSON that reads without
# this program.
DATABASE_IN_ZIP = "project-control.sqlite3"
MANIFEST_IN_ZIP = "manifest.json"

# The one file on Drive, replaced every night rather than added to.
DEFAULT_FILE_NAME = "project-control-backup.zip"

# The tables worth counting in the manifest: enough to see at a glance that a
# backup holds what it should.
COUNTED = (
    "projects", "tasks", "task_links", "task_revisions", "progress_updates",
    "time_entries", "trades", "sections", "workflow_steps", "calendars",
    "holidays", "meetings", "meeting_items", "attendees", "users",
)


def snapshot(path: Path | str) -> bytes:
    """The database as bytes, taken safely while the app is running.

    Uses SQLite's online backup rather than reading the file, so a write in
    progress cannot produce a copy that will not open.
    """
    source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        held = sqlite3.connect(":memory:")
        try:
            source.backup(held)
            return _serialise(held)
        finally:
            held.close()
    finally:
        source.close()


def _serialise(conn: sqlite3.Connection) -> bytes:
    """The in-memory copy as a real database file.

    `Connection.serialize` is the direct way and is there from Python 3.11; the
    fallback writes the copy out to a temporary file for older ones, so this
    works wherever the app itself runs.
    """
    try:
        return conn.serialize()                      # type: ignore[attr-defined]
    except AttributeError:
        import tempfile

        with tempfile.TemporaryDirectory() as room:
            spare = Path(room) / "copy.sqlite3"
            out = sqlite3.connect(spare)
            try:
                conn.backup(out)
            finally:
                out.close()
            return spare.read_bytes()


def describe(path: Path | str) -> dict[str, Any]:
    """What is in the database, for the manifest and for the screen."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        tables = {row["name"] for row in
                  conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        counts = {}
        for table in COUNTED:
            if table in tables:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"])

        projects = []
        if "projects" in tables:
            projects = [
                {"id": row["id"], "code": row["code"], "name": row["name"]}
                for row in conn.execute("SELECT id, code, name FROM projects ORDER BY id")
            ]
        return {"counts": counts, "projects": projects}
    finally:
        conn.close()


def build(path: Path | str, note: str = "") -> tuple[bytes, dict[str, Any]]:
    """The backup as a zip, and the manifest that went inside it."""
    body = snapshot(path)
    inside = describe(path)
    manifest = {
        "taken_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "database": DATABASE_IN_ZIP,
        "database_bytes": len(body),
        "projects": inside["projects"],
        "counts": inside["counts"],
        "note": note,
        "restore": (
            "Unzip and put the database where the app keeps its own, or run "
            "`python run.py restore <this file>` which does it and keeps a copy "
            "of what was there before."
        ),
    }

    held = io.BytesIO()
    with zipfile.ZipFile(held, "w", zipfile.ZIP_DEFLATED) as book:
        book.writestr(DATABASE_IN_ZIP, body)
        book.writestr(MANIFEST_IN_ZIP, json.dumps(manifest, indent=2))
    return held.getvalue(), manifest


def read_manifest(data: bytes) -> dict[str, Any]:
    """What a backup says about itself, without restoring it."""
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        if MANIFEST_IN_ZIP not in book.namelist():
            return {}
        return json.loads(book.read(MANIFEST_IN_ZIP).decode("utf-8"))


class RestoreError(Exception):
    """A backup that cannot be put back, said in words rather than a traceback."""


def restore(data: bytes, path: Path | str, keep_old: bool = True) -> dict[str, Any]:
    """Puts a backup back, after checking it is one.

    The database that was there is kept beside the new one unless told not to:
    restoring the wrong file is the one mistake this cannot undo for you.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            names = book.namelist()
            if DATABASE_IN_ZIP not in names:
                raise RestoreError(
                    f"That zip has no {DATABASE_IN_ZIP} in it — it is not a backup of this app")
            body = book.read(DATABASE_IN_ZIP)
            manifest = json.loads(book.read(MANIFEST_IN_ZIP).decode("utf-8")) \
                if MANIFEST_IN_ZIP in names else {}
    except zipfile.BadZipFile as exc:
        raise RestoreError("That file is not a zip") from exc

    if not body.startswith(b"SQLite format 3\x00"):
        raise RestoreError("What is inside that zip is not a SQLite database")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if keep_old and target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        target.replace(target.with_name(f"{target.name}.replaced-{stamp}"))

    target.write_bytes(body)
    # The write-ahead log and its index belong to the database that was here a
    # moment ago; left behind they would be replayed over the restored one.
    for leftover in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
        if leftover.exists():
            leftover.unlink()
    return manifest


def readable(size: int) -> str:
    """A byte count as something to put on a screen."""
    step = float(size)
    for unit in ("bytes", "KB", "MB", "GB"):
        if step < 1024 or unit == "GB":
            return f"{step:.0f} {unit}" if unit == "bytes" else f"{step:.1f} {unit}"
        step /= 1024
    return f"{step:.1f} GB"
