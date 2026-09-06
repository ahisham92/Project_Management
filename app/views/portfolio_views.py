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


# --- backups ----------------------------------------------------------------

ZONES = ("Africa/Cairo", "Asia/Beirut", "Asia/Riyadh", "Asia/Dubai", "Europe/London", "UTC")
HOURS = tuple(range(24))


def _admin_only() -> bool:
    """A backup is every project's data in one file, so who may touch it is who
    may see all of it."""
    if g.user["role"] == "admin":
        return True
    flash("Backups are for administrators", "error")
    return False


def _redirect_uri() -> str:
    """Where Google sends the browser back to. It has to match, character for
    character, what is registered against the OAuth client."""
    return url_for("portfolio.drive_connected", _external=True)


@bp.get("/backups")
@login_required
def backups():
    """Whether the nightly backup is working, and a way to take one now."""
    from .. import clock
    from ..backup import DEFAULT_FILE_NAME, describe, readable
    from ..db import live_database
    from ..drive import configured
    from ..service import backup_due, last_good_backup, load_backup_runs
    from ..vault import settings

    if not _admin_only():
        return redirect(url_for("portfolio.index"))

    where = Path(live_database())
    held = settings()
    hour, zone = int(held.get("hour", 0) or 0), str(held.get("zone") or clock.DEFAULT_ZONE)
    last = last_good_backup()

    return render_template(
        "backups.html",
        runs=load_backup_runs(),
        drive_ready=configured(held),
        from_env=bool(held.get("from_env")),
        account=held.get("account", ""),
        connected_at=held.get("connected_at", ""),
        folder_id=held.get("folder_id", ""),
        file_name=held.get("file_name") or DEFAULT_FILE_NAME,
        client_id=held.get("client_id", ""),
        auto=bool(held.get("auto", True)),
        hour=hour, zone=zone, zones=ZONES, hours=HOURS,
        redirect_uri=_redirect_uri(),
        # The same hour said in UTC, because a host that only runs UTC
        # schedules has to be told a UTC time — and the right one moves twice
        # a year with the clocks.
        utc_hour=clock.utc_hour(hour, zone),
        offset=clock.offset_words(zone),
        local_now=clock.now(zone).strftime("%H:%M"),
        next_run=clock.next_run(hour, zone),
        overdue=backup_due(),
        last_good=last,
        database=str(where),
        size=readable(where.stat().st_size) if where.exists() else "—",
        inside=describe(where) if where.exists() else {"counts": {}, "projects": []},
    )


@bp.post("/backups/connect")
@login_required
def connect_drive():
    """Step one of linking a Google account: off to Google to say yes.

    The client id and secret identify the *application* and are not a key to
    anything on their own; the refresh token that comes back at the end is, and
    that is why none of the three go anywhere near the database.
    """
    import secrets

    from flask import session

    from ..drive import consent_url
    from ..vault import update

    if not _admin_only():
        return redirect(url_for("portfolio.index"))

    client_id = (request.form.get("client_id") or "").strip()
    client_secret = (request.form.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        flash("Both the client ID and the client secret are needed", "error")
        return redirect(url_for("portfolio.backups"))

    update(client_id=client_id, client_secret=client_secret)

    # Google will send a browser back to us carrying a code. Without this, so
    # could anyone else, and we would exchange their code and back up this
    # database to a Drive belonging to somebody we have never heard of.
    session["drive_state"] = secrets.token_urlsafe(24)
    return redirect(consent_url(client_id, _redirect_uri()) + "&state=" + session["drive_state"])


@bp.get("/backups/connected")
@login_required
def drive_connected():
    """Step two: the code Google sent back, traded for a lasting one."""
    from datetime import datetime, timezone

    from flask import session

    from ..drive import DriveError, about, access_token, exchange
    from ..vault import read, update

    if not _admin_only():
        return redirect(url_for("portfolio.index"))

    expected = session.pop("drive_state", "")
    if request.args.get("error"):
        flash(f"Google did not connect the account: {request.args['error']}", "error")
        return redirect(url_for("portfolio.backups"))
    if not expected or request.args.get("state") != expected:
        flash("That did not come back from the request this page made — nothing was saved", "error")
        return redirect(url_for("portfolio.backups"))

    held = read()
    try:
        answer = exchange(held.get("client_id", ""), held.get("client_secret", ""),
                          request.args.get("code", ""), _redirect_uri())
    except DriveError as exc:
        flash(str(exc), "error")
        return redirect(url_for("portfolio.backups"))

    who = {}
    try:
        who = about(access_token(held.get("client_id", ""), held.get("client_secret", ""),
                                 answer["refresh_token"]))
    except DriveError:
        pass                                       # connected either way

    update(refresh_token=answer["refresh_token"],
           account=who.get("emailAddress") or who.get("displayName") or "",
           connected_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    flash("Google Drive connected. Take one now to prove it works.", "success")
    return redirect(url_for("portfolio.backups"))


@bp.post("/backups/disconnect")
@login_required
def disconnect_drive():
    """Forgets the account. The token is deleted, not merely switched off."""
    from ..vault import forget

    if not _admin_only():
        return redirect(url_for("portfolio.index"))

    forget()
    flash("Google Drive disconnected — nothing will be uploaded until it is connected again",
          "success")
    return redirect(url_for("portfolio.backups"))


@bp.post("/backups/schedule")
@login_required
def backup_schedule():
    """When the nightly backup runs, in the zone it means it in."""
    from .. import clock
    from ..vault import update

    if not _admin_only():
        return redirect(url_for("portfolio.index"))

    try:
        hour = int(request.form.get("hour") or 0)
    except ValueError:
        hour = 0
    zone = (request.form.get("zone") or clock.DEFAULT_ZONE).strip() or clock.DEFAULT_ZONE

    update(auto=bool(request.form.get("auto")), hour=max(0, min(23, hour)), zone=zone,
           folder_id=(request.form.get("folder_id") or "").strip(),
           file_name=(request.form.get("file_name") or "").strip())
    flash(f"Nightly backup set for {hour:02d}:00 {zone} "
          f"({clock.utc_hour(hour, zone)} UTC today)", "success")
    return redirect(url_for("portfolio.backups"))


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
