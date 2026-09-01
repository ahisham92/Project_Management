"""The portfolio list and project creation."""

from __future__ import annotations

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
