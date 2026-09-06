"""The portfolio list and project creation."""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..auth import login_required
from ..charts import SERIES_SLOTS
from ..db import insert, query_one
from ..dates import from_input_or
from ..service import install_default_steps, portfolio, today

bp = Blueprint("portfolio", __name__)


@bp.get("/")
@login_required
def index():
    data_date = from_input_or(request.args.get("data_date"), today())
    data = portfolio(g.user, data_date)
    return render_template("portfolio.html", data_date=data_date, **data)


@bp.get("/backups")
@login_required
def backups():
    """Whether the nightly backup is working, and a way to take one now.

    Administrators only: a backup is every project's data in one file, so who
    may download it is who may see all of it.
    """
    import os

    from ..backup import DEFAULT_FILE_NAME, describe, readable
    from ..db import live_database
    from ..drive import configured, settings_from_env
    from ..service import load_backup_runs

    if g.user["role"] != "admin":
        flash("Backups are for administrators", "error")
        return redirect(url_for("portfolio.index"))

    where = Path(live_database())
    settings = settings_from_env(os.environ)
    return render_template(
        "backups.html",
        runs=load_backup_runs(),
        drive_ready=configured(settings),
        folder_id=settings.get("folder_id", ""),
        file_name=settings.get("file_name") or DEFAULT_FILE_NAME,
        database=str(where),
        size=readable(where.stat().st_size) if where.exists() else "—",
        inside=describe(where) if where.exists() else {"counts": {}, "projects": []},
    )


@bp.post("/backups/run")
@login_required
def run_backup_now():
    """Take one now, rather than waiting for tonight — and prove it works."""
    from ..service import run_backup

    if g.user["role"] != "admin":
        flash("Backups are for administrators", "error")
        return redirect(url_for("portfolio.index"))

    result = run_backup(upload_to_drive=True)
    flash(result.get("detail") or "Backup taken", "success" if result["ok"] else "error")
    return redirect(url_for("portfolio.backups"))


@bp.get("/backups/download")
@login_required
def download_backup():
    """The whole thing, as a file, for anyone who would rather keep their own."""
    import io

    from flask import send_file

    from ..backup import DEFAULT_FILE_NAME, build
    from ..db import live_database
    from ..service import record_backup, today

    if g.user["role"] != "admin":
        flash("Backups are for administrators", "error")
        return redirect(url_for("portfolio.index"))

    data, _manifest = build(live_database(), note=f"Downloaded by {g.user['email']}")
    record_backup(True, "download", len(data), f"Downloaded by {g.user['email']}")
    stem = DEFAULT_FILE_NAME.removesuffix(".zip")
    return send_file(
        io.BytesIO(data), mimetype="application/zip", as_attachment=True,
        download_name=f"{stem}-{today().replace('-', '')}.zip",
    )


@bp.route("/projects/new", methods=("GET", "POST"))
@login_required
def new_project():
    form = {
        "code": "", "name": "", "client": "", "description": "",
        "ntp_date": today(), "duration_months": "12", "days_per_month": "30.4375",
        "hours_per_month": "176", "elapsed_day_offset": "0",
    }
    trades = [{"name": n, "budget_hours": ""} for n in ("Design", "Engineering", "Delivery")]

    if request.method == "POST":
        form = {key: (request.form.get(key) or "").strip() for key in form}
        names = request.form.getlist("trade_name")
        budgets = request.form.getlist("trade_hours")
        trades = [{"name": n.strip(), "budget_hours": b.strip()} for n, b in zip(names, budgets)]

        error = _validate(form)
        if error:
            flash(error, "error")
        elif query_one("SELECT 1 FROM projects WHERE code = ?", (form["code"],)):
            flash("A project with that code already exists", "error")
        else:
            project_id = insert(
                """
                INSERT INTO projects (code, name, client, description, ntp_date, duration_months,
                                      days_per_month, hours_per_month, elapsed_day_offset, owner_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    form["code"], form["name"], form["client"], form["description"],
                    from_input_or(form["ntp_date"], today()),
                    float(form["duration_months"]), float(form["days_per_month"] or 30.4375),
                    float(form["hours_per_month"] or 176), float(form["elapsed_day_offset"] or 0),
                    g.user["id"],
                ),
            )
            install_default_steps(project_id)
            for index, trade in enumerate(t for t in trades if t["name"]):
                key = _slug(trade["name"]) or f"trade_{index + 1}"
                insert(
                    "INSERT INTO trades (project_id, key, name, budget_hours, color, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        project_id, key, trade["name"], _to_float(trade["budget_hours"]),
                        SERIES_SLOTS[index % len(SERIES_SLOTS)][1], index + 1,
                    ),
                )
            flash("Project created. Add its sections and deliverables below.", "success")
            return redirect(url_for("projects.setup", project_id=project_id))

    return render_template("new_project.html", form=form, trades=trades)


def _validate(form: dict[str, str]) -> str | None:
    if not form["code"]:
        return "Enter a project code"
    if not form["name"]:
        return "Enter a project name"
    if not form["ntp_date"]:
        return "Enter the notice to proceed date"
    try:
        if float(form["duration_months"]) <= 0:
            return "Duration must be greater than zero"
    except ValueError:
        return "Duration must be a number"
    return None


def _to_float(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
