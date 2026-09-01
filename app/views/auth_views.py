"""Sign in, register and account pages."""

from __future__ import annotations

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for

from ..auth import hash_password, sign_in, sign_out, signup_allowed, verify_password
from ..db import insert, query_one

bp = Blueprint("auth", __name__)

MIN_PASSWORD = 8


def _safe_next(target: str | None) -> str:
    """Only follow same-site redirects, so ?next= cannot bounce elsewhere."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("portfolio.index")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if g.user:
        return redirect(url_for("portfolio.index"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = query_one("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,))
        if user and verify_password(password, user["password_hash"]):
            sign_in(user)
            return redirect(_safe_next(request.args.get("next")))
        flash("Incorrect email or password", "error")

    return render_template("login.html", mode="login", signup_open=signup_allowed())


@bp.route("/register", methods=("GET", "POST"))
def register():
    if g.user:
        return redirect(url_for("portfolio.index"))

    first_user = query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0
    if not first_user and not signup_allowed():
        flash("New accounts are created by an administrator.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        name = (request.form.get("name") or "").strip()
        password = request.form.get("password") or ""

        if not email or "@" not in email:
            flash("Enter a valid email address", "error")
        elif len(password) < MIN_PASSWORD:
            flash(f"Password must be at least {MIN_PASSWORD} characters", "error")
        elif query_one("SELECT 1 FROM users WHERE email = ? COLLATE NOCASE", (email,)):
            flash("An account with that email already exists", "error")
        else:
            user_id = insert(
                "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
                (email, name or email.split("@")[0], hash_password(password), "admin" if first_user else "user"),
            )
            sign_in(query_one("SELECT * FROM users WHERE id = ?", (user_id,)))
            return redirect(url_for("portfolio.index"))

    return render_template("login.html", mode="register", signup_open=True)


@bp.post("/logout")
def logout():
    sign_out()
    return redirect(url_for("auth.login"))


@bp.route("/account", methods=("GET", "POST"))
def account():
    if not g.user:
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        current = request.form.get("current") or ""
        new = request.form.get("new") or ""
        if not verify_password(current, g.user["password_hash"]):
            flash("Current password is incorrect", "error")
        elif len(new) < MIN_PASSWORD:
            flash(f"New password must be at least {MIN_PASSWORD} characters", "error")
        else:
            from ..db import execute

            execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new), g.user["id"]))
            flash("Password changed", "success")
            return redirect(url_for("auth.account"))

    return render_template("account.html")
