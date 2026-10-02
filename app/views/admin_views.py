"""The administrator's panel: who has an account, making accounts, and which
programs each account may open.

Only accounts with the admin role reach it; anyone else is told the page does
not exist, so it is not advertised to them.
"""

from __future__ import annotations

import re

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..auth import hash_password
from ..db import execute, insert, query, query_one
from ..programs import PROGRAMS, allowed, pack

bp = Blueprint("admin", __name__, url_prefix="/admin")

MIN_PASSWORD = 8
USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,40}$")


@bp.before_request
def _admins_only():
    if g.user is None:
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    if g.user["role"] != "admin":
        abort(404)
    return None


def _accounts() -> list[dict]:
    rows = query("SELECT * FROM users ORDER BY created_at DESC, id DESC")
    owned = {r["owner_id"]: r["n"] for r in query(
        "SELECT owner_id, COUNT(*) AS n FROM projects GROUP BY owner_id")}
    return [{**dict(row), "can_open": allowed(row), "owns": owned.get(row["id"], 0)} for row in rows]


def _clash(username: str, email: str, but: int | None = None) -> str:
    """What is already taken, or an empty string."""
    other = " AND id != ?" if but else ""
    extra = (but,) if but else ()
    if username and query_one(
            "SELECT 1 FROM users WHERE (username = ? COLLATE NOCASE OR email = ? COLLATE NOCASE)" + other,
            (username, username, *extra)):
        return f"The username {username} is already taken"
    if email and query_one(
            "SELECT 1 FROM users WHERE (email = ? COLLATE NOCASE OR username = ? COLLATE NOCASE)" + other,
            (email, email, *extra)):
        return f"{email} already belongs to another account"
    return ""


@bp.get("/")
def index():
    tab = request.args.get("tab", "users")
    return render_template("admin.html", tab=tab, accounts=_accounts(), programs=PROGRAMS)


@bp.post("/users")
def create_user():
    username = (request.form.get("username") or "").strip().lower()
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    role = "admin" if request.form.get("role") == "admin" else "user"
    chosen = pack(request.form.getlist("programs"))

    problem = ""
    if not USERNAME.match(username):
        problem = "A username is 3 to 40 letters, digits, dots, dashes or underscores"
    elif email and "@" not in email:
        problem = "Enter a valid email address, or leave it empty"
    elif len(password) < MIN_PASSWORD:
        problem = f"The password must be at least {MIN_PASSWORD} characters"
    else:
        problem = _clash(username, email)
    if problem:
        flash(problem, "error")
        return redirect(url_for("admin.index", tab="new"))

    insert(
        "INSERT INTO users (email, username, name, password_hash, role, programs) VALUES (?, ?, ?, ?, ?, ?)",
        # The email column must hold something unique; the username does when none is given.
        (email or username, username, name or username, hash_password(password), role, chosen),
    )
    from ..specs_trades import clean as clean_trade
    execute("UPDATE users SET themis_trade = ? WHERE username = ? COLLATE NOCASE",
            (clean_trade(request.form.get("themis_trade"), ""), username))
    flash(f"Account {username} created. Give them the username and password.", "success")
    return redirect(url_for("admin.index"))


def _account(user_id: int):
    user = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if user is None:
        abort(404)
    return user


@bp.route("/users/<int:user_id>", methods=("GET", "POST"))
def edit_user(user_id: int):
    user = _account(user_id)
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        role = "admin" if request.form.get("role") == "admin" else "user"
        if user["id"] == g.user["id"]:
            role = "admin"                    # never lock yourself out of this page
        problem = ""
        if username and not USERNAME.match(username):
            problem = "A username is 3 to 40 letters, digits, dots, dashes or underscores"
        elif email and "@" not in email and email != username:
            problem = "Enter a valid email address, or leave it empty"
        elif not username and not email:
            problem = "An account needs a username or an email to sign in with"
        else:
            problem = _clash(username, email if email != username else "", but=user["id"])
        if problem:
            flash(problem, "error")
            return redirect(url_for("admin.edit_user", user_id=user_id))
        execute(
            "UPDATE users SET username = ?, name = ?, email = ?, role = ?, programs = ? WHERE id = ?",
            (username or None, name or username or email, email or username, role,
             pack(request.form.getlist("programs")), user_id),
        )
        if "themis_trade" in request.form:
            from ..specs_trades import set_user_trade
            set_user_trade(user_id, request.form.get("themis_trade"))
        flash("Account saved", "success")
        return redirect(url_for("admin.index"))
    return render_template("admin_user.html", account=user, can_open=allowed(user), programs=PROGRAMS)


@bp.post("/users/<int:user_id>/password")
def reset_password(user_id: int):
    user = _account(user_id)
    password = request.form.get("password") or ""
    if len(password) < MIN_PASSWORD:
        flash(f"The password must be at least {MIN_PASSWORD} characters", "error")
    else:
        execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), user["id"]))
        flash(f"New password set for {user['username'] or user['email']}", "success")
    return redirect(url_for("admin.edit_user", user_id=user_id))


@bp.post("/users/<int:user_id>/delete")
def delete_user(user_id: int):
    user = _account(user_id)
    if user["id"] == g.user["id"]:
        flash("You cannot delete your own account", "error")
        return redirect(url_for("admin.edit_user", user_id=user_id))
    if query_one("SELECT 1 FROM projects WHERE owner_id = ?", (user_id,)):
        flash("This account owns projects. Take away its programs instead of deleting it.", "error")
        return redirect(url_for("admin.edit_user", user_id=user_id))
    execute("DELETE FROM users WHERE id = ?", (user_id,))
    flash(f"Account {user['username'] or user['email']} deleted", "success")
    return redirect(url_for("admin.index"))
