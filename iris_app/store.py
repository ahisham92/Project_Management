"""Iris's database: accounts' tools, pairings, messages and phones.

One SQLite file in the data directory. Iris keeps no names of its own for
people: an account is whatever id the site that mounts Iris hands over, so the
site's own sign-in stays the only one.

**What is stored readable.** A tool's name and machine (shown on the phone and
in push notifications), its command buttons, message kinds and times. Every
message *body* is encrypted on the PC or the phone before it is sent, with a
key that only the tool and the phone hold. Iris passes those bodies along and
cannot read them.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS tools (
    id          INTEGER PRIMARY KEY,
    account     TEXT NOT NULL,
    name        TEXT NOT NULL,
    machine     TEXT NOT NULL DEFAULT '',
    commands    TEXT NOT NULL DEFAULT '[]',
    notify      TEXT NOT NULL DEFAULT 'all',
    agent       TEXT NOT NULL DEFAULT '',   -- who speaks for the tool on the phone (Sketch ProMax: the user's coordinator)
    token_hash  TEXT NOT NULL UNIQUE,
    created     REAL NOT NULL,
    seen        REAL NOT NULL,
    read_upto   INTEGER NOT NULL DEFAULT 0, -- the newest phone message the tool has fetched
    revoked     REAL
);
CREATE INDEX IF NOT EXISTS tools_account ON tools(account);

CREATE TABLE IF NOT EXISTS pairings (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    secret_hash TEXT NOT NULL,
    name        TEXT NOT NULL,
    machine     TEXT NOT NULL DEFAULT '',
    commands    TEXT NOT NULL DEFAULT '[]',
    created     REAL NOT NULL,
    tool_id     INTEGER,
    token       TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    tool_id     INTEGER NOT NULL REFERENCES tools(id) ON DELETE CASCADE,
    side        TEXT NOT NULL,              -- 'tool' or 'phone'
    kind        TEXT NOT NULL,              -- update, question, answer, command, message, closed
    reply_to    INTEGER,
    body        TEXT NOT NULL,              -- encrypted, never read here
    state       TEXT NOT NULL DEFAULT '',   -- a question: open, answered, closed
    created     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_tool ON messages(tool_id, id);

CREATE TABLE IF NOT EXISTS phones (
    id          INTEGER PRIMARY KEY,
    account     TEXT NOT NULL,
    endpoint    TEXT NOT NULL UNIQUE,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    created     REAL NOT NULL
);
"""

#: What a tool may send, and what a phone may send.
TOOL_KINDS = frozenset({"update", "question", "closed"})
PHONE_KINDS = frozenset({"answer", "command", "message"})
NOTIFY = ("all", "questions", "none")

#: A pairing code is good for this long.
PAIR_SECONDS = 10 * 60
#: Unambiguous letters and digits only: no 0/O, 1/I/L.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
#: A message body may be this long once encrypted (pictures go elsewhere).
MAX_BODY = 64 * 1024


class StoreError(Exception):
    """Something the caller asked that cannot be done; ``status`` says how to answer."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def data_folder() -> Path:
    return Path(os.environ.get("IRIS_DATA_DIR") or Path.home() / "iris-data")


def keep_days() -> int:
    try:
        return max(1, int(os.environ.get("IRIS_KEEP_DAYS", "30")))
    except ValueError:
        return 30


def hashed(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class Store:
    def __init__(self, path: Path | None = None, clock=time.time):
        self.path = Path(path or data_folder() / "iris.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        with self._db() as db:
            db.executescript(SCHEMA)
            columns = {r["name"] for r in db.execute("PRAGMA table_info(tools)")}
            if "read_upto" not in columns:
                db.execute("ALTER TABLE tools ADD COLUMN read_upto INTEGER NOT NULL DEFAULT 0")
            if "agent" not in columns:
                db.execute("ALTER TABLE tools ADD COLUMN agent TEXT NOT NULL DEFAULT ''")
            if db.execute("PRAGMA user_version").fetchone()[0] < 1:
                # Tools connected before 31 Oct 2026 notified about questions only, so updates and replies
                # never buzzed the phone: every tool notifies about everything now (each can be turned down).
                db.execute("UPDATE tools SET notify = 'all' WHERE notify = 'questions'")
                db.execute("PRAGMA user_version = 1")

    def _db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    # ---- pairing ---------------------------------------------------------

    def start_pairing(self, name: str, machine: str, commands: list[str]) -> dict[str, Any]:
        """A tool asks to be connected. It gets a code to show and a secret to poll with."""
        name = (name or "").strip()[:60]
        if not name:
            raise StoreError(400, "A tool needs a name.")
        commands = [str(c).strip()[:24] for c in (commands or []) if str(c).strip()][:6]
        secret = secrets.token_urlsafe(24)
        now = self.clock()
        with self._db() as db:
            db.execute("DELETE FROM pairings WHERE created < ?", (now - PAIR_SECONDS,))
            for _ in range(20):
                code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
                try:
                    cur = db.execute(
                        "INSERT INTO pairings (code, secret_hash, name, machine, commands, created)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (code, hashed(secret), name, (machine or "").strip()[:60], json.dumps(commands), now))
                    return {"pair_id": cur.lastrowid, "code": code, "secret": secret,
                            "expires_in": PAIR_SECONDS}
                except sqlite3.IntegrityError:
                    continue
        raise StoreError(503, "Could not make a pairing code. Try again.")

    def pairing_status(self, pair_id: int, secret: str) -> dict[str, Any]:
        """What the tool polls until a phone has accepted it. The token is handed over once."""
        with self._db() as db:
            row = db.execute("SELECT * FROM pairings WHERE id = ?", (pair_id,)).fetchone()
            if row is None or not secrets.compare_digest(row["secret_hash"], hashed(secret or "")):
                raise StoreError(404, "No such pairing.")
            if row["tool_id"] is None:
                if row["created"] < self.clock() - PAIR_SECONDS:
                    return {"status": "expired"}
                return {"status": "waiting"}
            token = row["token"]
            db.execute("DELETE FROM pairings WHERE id = ?", (pair_id,))
            return {"status": "connected", "tool_id": row["tool_id"], "token": token}

    def describe_pairing(self, code: str) -> dict[str, Any]:
        row = self._pairing_by_code(code)
        return {"name": row["name"], "machine": row["machine"]}

    def accept_pairing(self, account: str, code: str) -> dict[str, Any]:
        """A signed-in phone accepts the code: the tool becomes the account's."""
        row = self._pairing_by_code(code)
        if row["tool_id"] is not None:
            raise StoreError(409, "This code has already been used.")
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with self._db() as db:
            cur = db.execute(
                "INSERT INTO tools (account, name, machine, commands, notify, token_hash, created, seen)"
                " VALUES (?, ?, ?, ?, 'all', ?, ?, ?)",
                (str(account), row["name"], row["machine"], row["commands"], hashed(token), now, now))
            db.execute("UPDATE pairings SET tool_id = ?, token = ? WHERE id = ?",
                       (cur.lastrowid, token, row["id"]))
        return self.tool_for(account, cur.lastrowid)

    def _pairing_by_code(self, code: str) -> sqlite3.Row:
        code = "".join(ch for ch in (code or "").upper() if ch.isalnum())
        with self._db() as db:
            row = db.execute("SELECT * FROM pairings WHERE code = ?", (code,)).fetchone()
        if row is None or row["created"] < self.clock() - PAIR_SECONDS:
            raise StoreError(404, "That code is not valid any more. Show a new one on the PC.")
        return row

    # ---- tools -----------------------------------------------------------

    def tool_by_token(self, token: str) -> sqlite3.Row:
        with self._db() as db:
            row = db.execute("SELECT * FROM tools WHERE token_hash = ?", (hashed(token or ""),)).fetchone()
            if row is None or row["revoked"] is not None:
                raise StoreError(401, "This tool is not connected. Connect it again from its settings.")
            db.execute("UPDATE tools SET seen = ? WHERE id = ?", (self.clock(), row["id"]))
        return row

    def tools(self, account: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT t.*, (SELECT COUNT(*) FROM messages m WHERE m.tool_id = t.id"
                " AND m.kind = 'question' AND m.state = 'open') AS waiting,"
                " (SELECT MAX(id) FROM messages m WHERE m.tool_id = t.id) AS last"
                " FROM tools t WHERE account = ? AND revoked IS NULL ORDER BY created",
                (str(account),)).fetchall()
            views = [self._tool_view(r) for r in rows]
            for view in views:
                last = db.execute("SELECT kind, side, body, created FROM messages WHERE id = ?", (view["last"],)).fetchone()
                view["latest"] = dict(last) if last else None
        # The home list puts the tool that spoke most recently first.
        views.sort(key=lambda v: -(v["latest"]["created"] if v["latest"] else v["created"]))
        return views

    def tool_for(self, account: str, tool_id: int) -> dict[str, Any]:
        for tool in self.tools(account):
            if tool["id"] == tool_id:
                return tool
        raise StoreError(404, "No such tool on your account.")

    @staticmethod
    def _tool_view(row: sqlite3.Row) -> dict[str, Any]:
        keys = row.keys()
        return {
            "id": row["id"], "name": row["name"], "machine": row["machine"],
            "agent": row["agent"] if "agent" in keys else "",
            "commands": json.loads(row["commands"] or "[]"), "notify": row["notify"],
            "created": row["created"], "seen": row["seen"], "read_upto": row["read_upto"],
            "waiting": row["waiting"] if "waiting" in keys else 0,
            "last": (row["last"] or 0) if "last" in keys else 0,
        }

    def set_notify(self, account: str, tool_id: int, notify: str) -> None:
        if notify not in NOTIFY:
            raise StoreError(400, "Notify must be all, questions or none.")
        self.tool_for(account, tool_id)
        with self._db() as db:
            db.execute("UPDATE tools SET notify = ? WHERE id = ?", (notify, tool_id))

    def set_agent(self, tool_id: int, agent: str) -> None:
        """The name the tool speaks under on the phone ("" for its own name)."""
        with self._db() as db:
            db.execute("UPDATE tools SET agent = ? WHERE id = ?", ((agent or "").strip()[:40], tool_id))

    def disconnect(self, tool_id: int, account: str | None = None) -> None:
        """Cut a tool off, from the phone (``account`` given) or from the tool itself."""
        if account is not None:
            self.tool_for(account, tool_id)
        with self._db() as db:
            db.execute("UPDATE tools SET revoked = ? WHERE id = ?", (self.clock(), tool_id))
            db.execute("DELETE FROM messages WHERE tool_id = ?", (tool_id,))

    # ---- messages --------------------------------------------------------

    def post(self, tool_id: int, side: str, kind: str, body: str, reply_to: int | None = None) -> dict[str, Any]:
        allowed = TOOL_KINDS if side == "tool" else PHONE_KINDS
        if kind not in allowed:
            raise StoreError(400, f"A {side} cannot send '{kind}'.")
        if not isinstance(body, str) or not body:
            raise StoreError(400, "A message needs a body.")
        if len(body) > MAX_BODY:
            raise StoreError(413, "That message is too long.")
        now = self.clock()
        with self._db() as db:
            if reply_to is not None:
                question = db.execute(
                    "SELECT * FROM messages WHERE id = ? AND tool_id = ? AND kind = 'question'",
                    (reply_to, tool_id)).fetchone()
                if question is None:
                    raise StoreError(404, "No such question.")
                if question["state"] != "open":
                    raise StoreError(409, "That question has already been settled.")
                db.execute("UPDATE messages SET state = ? WHERE id = ?",
                           ("answered" if kind == "answer" else "closed", reply_to))
            elif kind in ("answer", "closed"):
                raise StoreError(400, "Say which question this settles.")
            cur = db.execute(
                "INSERT INTO messages (tool_id, side, kind, reply_to, body, state, created)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (tool_id, side, kind, reply_to, body, "open" if kind == "question" else "", now))
            db.execute("DELETE FROM messages WHERE created < ?", (now - keep_days() * 86400,))
        return {"id": cur.lastrowid, "created": now}

    def messages(self, tool_id: int, after: int = 0, side: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM messages WHERE tool_id = ? AND id > ?"
        args: list[Any] = [tool_id, int(after or 0)]
        if side:
            sql += " AND side = ?"
            args.append(side)
        sql += " ORDER BY id LIMIT ?"
        args.append(max(1, min(int(limit), 500)))
        with self._db() as db:
            rows = db.execute(sql, args).fetchall()
        return [{k: r[k] for k in ("id", "side", "kind", "reply_to", "body", "state", "created")} for r in rows]

    def tool_inbox(self, tool_id: int, after: int = 0) -> list[dict[str, Any]]:
        """What the phone sent after ``after``; fetched counts as read (the phone shows a tick)."""
        found = self.messages(tool_id, after, side="phone")
        if found:
            with self._db() as db:
                db.execute("UPDATE tools SET read_upto = MAX(read_upto, ?) WHERE id = ?", (found[-1]["id"], tool_id))
        return found

    def wrote_lately(self, tool_id: int, minutes: int = 30) -> bool:
        """The phone wrote to this tool lately: its update is a reply to the user, worth a notification."""
        with self._db() as db:
            row = db.execute("SELECT 1 FROM messages WHERE tool_id = ? AND side = 'phone' AND kind = 'message' AND created > ? LIMIT 1",
                             (tool_id, self.clock() - minutes * 60)).fetchone()
        return row is not None

    def read_upto(self, tool_id: int) -> int:
        with self._db() as db:
            row = db.execute("SELECT read_upto FROM tools WHERE id = ?", (tool_id,)).fetchone()
        return row["read_upto"] if row else 0

    def recent(self, tool_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """The last ``limit`` messages, oldest first: what the phone opens a tool on."""
        with self._db() as db:
            last = db.execute("SELECT id FROM messages WHERE tool_id = ? ORDER BY id DESC LIMIT 1 OFFSET ?",
                              (tool_id, max(0, limit - 1))).fetchone()
        return self.messages(tool_id, after=(last["id"] - 1) if last else 0, limit=limit)

    # ---- phones (push) ---------------------------------------------------

    def add_phone(self, account: str, endpoint: str, p256dh: str, auth: str) -> None:
        if not endpoint.startswith("https://") or not p256dh or not auth:
            raise StoreError(400, "That is not a push subscription.")
        with self._db() as db:
            db.execute("DELETE FROM phones WHERE endpoint = ?", (endpoint,))
            db.execute("INSERT INTO phones (account, endpoint, p256dh, auth, created) VALUES (?, ?, ?, ?, ?)",
                       (str(account), endpoint, p256dh, auth, self.clock()))

    def remove_phone(self, endpoint: str, account: str | None = None) -> None:
        with self._db() as db:
            if account is None:
                db.execute("DELETE FROM phones WHERE endpoint = ?", (endpoint,))
            else:
                db.execute("DELETE FROM phones WHERE endpoint = ? AND account = ?", (endpoint, str(account)))

    def phones(self, account: str) -> list[dict[str, str]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM phones WHERE account = ?", (str(account),)).fetchall()
        return [{"endpoint": r["endpoint"], "p256dh": r["p256dh"], "auth": r["auth"]} for r in rows]
