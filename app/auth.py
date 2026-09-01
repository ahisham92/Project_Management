"""Accounts, sessions and per-project permissions.

Passwords are hashed with Werkzeug's scrypt helper and sessions ride in Flask's
signed, httpOnly cookie, so no extra packages are needed for either.
"""

from __future__ import annotations

import functools
import os
import secrets
from pathlib import Path
from typing import Any, Callable

from flask import abort, flash, g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import data_dir, query, query_one

ROLE_RANK = {"viewer": 0, "member": 1, "manager": 2, "owner": 3}


def secret_key() -> str:
    """The key that signs session cookies.

    Taken from SECRET_KEY when set. Otherwise one is generated and kept in the
    data directory, so a local install needs no configuration yet still keeps
    people signed in across restarts.
    """
    from_env = os.environ.get("SECRET_KEY")
    if from_env:
        return from_env

    key_file = data_dir() / "secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()

    generated = secrets.token_hex(32)
    key_file.write_text(generated, encoding="utf-8")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass  # Windows and some filesystems do not support this
    return generated


def hash_password(plain: str) -> str:
    return generate_password_hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return check_password_hash(hashed, plain)


def signup_allowed() -> bool:
    if os.environ.get("ALLOW_SIGNUP", "true").lower() == "false":
        # The very first account is always allowed, or nobody could ever sign in.
        return query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    return True


def load_user() -> None:
    """Populates g.user from the session before each request."""
    user_id = session.get("user_id")
    g.user = query_one("SELECT * FROM users WHERE id = ?", (user_id,)) if user_id else None


def sign_in(user: Any) -> None:
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True


def sign_out() -> None:
    session.clear()


def login_required(view: Callable) -> Callable:
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def project_role(project: Any, user: Any) -> str | None:
    """'owner', 'manager', 'member', 'viewer', or None when there is no access."""
    if user is None:
        return None
    if project["owner_id"] == user["id"]:
        return "owner"
    if user["role"] == "admin":
        return "manager"
    member = query_one(
        "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
        (project["id"], user["id"]),
    )
    return member["role"] if member else None


def load_project(project_id: int, min_role: str = "viewer"):
    """Fetches a project the current user may see, or aborts.

    A project the user cannot see is reported as missing rather than forbidden,
    so the app does not confirm that an id exists to someone with no access.
    """
    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if project is None:
        abort(404)
    role = project_role(project, g.user)
    if role is None:
        abort(404)
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        abort(403)
    g.project = project
    g.project_role = role
    return project, role


def require_edit(role: str, message: str = "You do not have permission to change this project.") -> bool:
    """Flashes and reports False when the role cannot edit, for POST handlers."""
    if ROLE_RANK[role] < ROLE_RANK["manager"]:
        flash(message, "error")
        return False
    return True


# --- setup sheet lock ------------------------------------------------------
#
# This guards the Setup sheet from accidental edits, the way a protected
# spreadsheet does. It is a workflow guard, not a security boundary: anyone with
# manager access to the project can be given the password. Real access control
# is the project role.

DEFAULT_SETUP_PASSWORD = "2026"


def setup_password_hash(project: Any) -> str:
    stored = (project["setup_password_hash"] or "").strip()
    return stored or generate_password_hash(DEFAULT_SETUP_PASSWORD)


def check_setup_password(project: Any, attempt: str) -> bool:
    return check_password_hash(setup_password_hash(project), attempt or "")


def unlock_setup(project_id: int) -> None:
    unlocked = set(session.get("setup_unlocked") or [])
    unlocked.add(int(project_id))
    session["setup_unlocked"] = sorted(unlocked)


def lock_setup(project_id: int) -> None:
    unlocked = set(session.get("setup_unlocked") or [])
    unlocked.discard(int(project_id))
    session["setup_unlocked"] = sorted(unlocked)


def setup_unlocked(project_id: int) -> bool:
    return int(project_id) in set(session.get("setup_unlocked") or [])


def visible_project_ids(user: Any) -> list[int]:
    """Every project id the user may see."""
    if user["role"] == "admin":
        return [r["id"] for r in query("SELECT id FROM projects")]
    rows = query(
        """
        SELECT id FROM projects WHERE owner_id = ?
        UNION
        SELECT project_id FROM project_members WHERE user_id = ?
        """,
        (user["id"], user["id"]),
    )
    return [r["id"] for r in rows]
