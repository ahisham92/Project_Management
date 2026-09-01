"""Everything scoped to a single project."""

from __future__ import annotations

import io

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import charts
from ..auth import ROLE_RANK, load_project, login_required, setup_unlocked
from ..charts import SERIES_SLOTS
from ..dates import from_input, from_input_or
from ..db import execute, insert, query, query_one
from ..sorting import COLUMNS as SORT_COLUMNS
from ..sorting import normalise as normalise_sort
from ..sorting import sort_tasks
from ..service import (
    AllocationError, WorkflowError, install_default_steps, load_revisions, load_sections,
    load_steps, load_trades, next_sort_order, project_period, project_s_curve,
    project_snapshot, record_comments, record_progress, set_allocations, set_status, today,
)
from ..workflow import ordered as ordered_steps

bp = Blueprint("projects", __name__, url_prefix="/projects/<int:project_id>")

# The look-ahead choices on the schedule. "all" shows every remaining submission.
HORIZONS = (7, 14, 30, 60, 90, 180, 365)


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _params():
    """The data date and look-ahead shared by every project screen.

    The look-ahead accepts any number of days, or "all" for everything ahead,
    which arrives here as None.
    """
    data_date = from_input_or(request.args.get("data_date"), today())
    raw = (request.args.get("horizon") or "").strip().lower()
    if raw in ("all", "0"):
        return data_date, None
    horizon = _to_int(raw, 30) or 30
    return data_date, min(3650, max(1, horizon))


def _can_edit(role: str) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK["manager"]


def _can_report(role: str) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK["member"]


def _display(iso: str) -> str:
    from ..dates import to_display

    return to_display(iso)


def _back(endpoint: str, project_id: int, **extra):
    """Redirect back to the page the form was submitted from."""
    return redirect(url_for(endpoint, project_id=project_id, **extra))


# --- dashboard -------------------------------------------------------------

@bp.get("/")
@login_required
def dashboard(project_id: int):
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)
    points = project_s_curve(project, data_date)

    attention = sorted(
        (t for t in snapshot["tasks"] if t["is_late"] or t["is_behind"]),
        key=lambda t: (not t["is_late"], t["variance"]),
    )[:8]

    return render_template(
        "dashboard.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        attention=attention,
        s_curve=charts.s_curve(points, snapshot["data_date"]),
        trade_progress=charts.trade_progress(snapshot["trades"]),
        trade_weight=charts.trade_weight(snapshot["trades"]),
    )


# --- progress --------------------------------------------------------------

FILTERS = (
    ("all", "All"), ("late", "Late"), ("behind", "Behind plan"),
    ("open", "In progress"), ("notstarted", "Not started"), ("complete", "Complete"),
    ("rework", "In rework"),
)


@bp.get("/tasks")
@login_required
def tasks(project_id: int):
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)

    active = request.args.get("filter", "all")
    search = (request.args.get("q") or "").strip()

    def keep(task) -> bool:
        if search and search.lower() not in f"{task['wbs']} {task['name']}".lower():
            return False
        if active == "late":
            return task["is_late"]
        if active == "behind":
            return task["is_behind"]
        if active == "open":
            return 0 < task["actual_pct"] < 1
        if active == "notstarted":
            return task["actual_pct"] <= 0
        if active == "complete":
            return task["is_complete"]
        if active == "rework":
            return task["in_rework"]
        return True

    kept = [t for t in snapshot["tasks"] if keep(t)]
    sort, direction = normalise_sort(request.args.get("sort"), request.args.get("dir"))
    kept = sort_tasks(kept, sort, direction)

    # Sections are the natural reading order. Asking for any other order means
    # you want one ranked list, so the sections fold away.
    if sort == "wbs":
        groups: dict[object, dict] = {}
        for task in kept:
            key = task["section_id"] if task["section_id"] is not None else "none"
            group = groups.setdefault(
                key, {"name": task["section_name"] or "Unassigned", "tasks": [], "weight": 0.0}
            )
            group["tasks"].append(task)
            group["weight"] += task["weight_pct"]
        grouped = list(groups.values())
    else:
        grouped = [{
            "name": "All deliverables",
            "tasks": kept,
            "weight": sum(t["weight_pct"] for t in kept),
        }] if kept else []

    return render_template(
        "tasks.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        groups=grouped, filters=FILTERS, active_filter=active, search=search,
        shown=len(kept), can_report=_can_report(role),
        steps=ordered_steps(load_steps(project_id)),
        sort=sort, direction=direction, sort_columns=SORT_COLUMNS,
        editing=_to_int(request.args.get("edit")),
        commenting=_to_int(request.args.get("comments")),
    )


def _return_to_tasks(project_id: int, **extra):
    return _back(
        "projects.tasks", project_id,
        data_date=from_input(request.form.get("data_date")) or None,
        filter=request.form.get("filter") or None,
        q=request.form.get("q") or None,
        **extra,
    )


@bp.post("/tasks/<int:task_id>/progress")
@login_required
def update_progress(project_id: int, task_id: int):
    """Records progress.

    A deliverable on the design workflow is moved to a status step, which decides
    the percentage. Meetings and milestones take a typed percentage instead.
    """
    project, role = load_project(project_id, "member")
    task = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if task is None:
        abort(404)

    data_date = from_input_or(request.form.get("data_date"), today())
    note = (request.form.get("note") or "").strip()
    label = task["wbs"] or task["name"][:40]

    if "status_key" in request.form:
        steps = load_steps(project_id)
        try:
            percent = set_status(task, (request.form.get("status_key") or "").strip(), note,
                                 data_date, g.user["id"], steps)
        except WorkflowError as exc:
            flash(str(exc), "error")
        else:
            flash(f"{label} updated to {percent * 100:g}%", "success")
    else:
        percent = _to_float(request.form.get("actual_pct"), -1)
        if not 0 <= percent <= 100:
            flash("Progress must be a value between 0% and 100%", "error")
        else:
            record_progress(task, percent / 100, note, data_date, g.user["id"])
            flash(f"{label} updated to {percent:g}%", "success")

    return _return_to_tasks(project_id)


@bp.post("/tasks/<int:task_id>/comments")
@login_required
def record_task_comments(project_id: int, task_id: int):
    """The client returned comments rather than a Code A: raise a revision."""
    project, role = load_project(project_id, "member")
    task = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if task is None:
        abort(404)

    comments_date = from_input_or(request.form.get("comments_date"), today())
    new_submission = from_input(request.form.get("new_submission_date"))
    try:
        result = record_comments(
            task, project, load_steps(project_id), comments_date, new_submission or "",
            (request.form.get("note") or "").strip(), g.user["id"],
        )
    except WorkflowError as exc:
        flash(str(exc), "error")
        return _return_to_tasks(project_id)

    flash(
        f"{task['wbs'] or task['name'][:40]} moved to revision {result['revision']} — "
        f"back to \u201c{result['reset_to']}\u201d, resubmission planned for "
        f"{_display(result['submission_date'])}",
        "success",
    )
    return _return_to_tasks(project_id)


@bp.get("/tasks/<int:task_id>/history")
@login_required
def task_history(project_id: int, task_id: int):
    """The full trail for one deliverable: every status change and revision."""
    project, role = load_project(project_id)
    task = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if task is None:
        abort(404)

    snapshot = project_snapshot(project, _params()[0])
    computed = next((t for t in snapshot["tasks"] if t["id"] == task_id), None)
    updates = query(
        """
        SELECT p.*, u.name AS user_name
        FROM progress_updates p LEFT JOIN users u ON u.id = p.user_id
        WHERE p.task_id = ? ORDER BY p.data_date DESC, p.id DESC
        """,
        (task_id,),
    )
    return render_template(
        "task_history.html",
        project=project, role=role, task=task, computed=computed,
        data_date=snapshot["data_date"], updates=updates, revisions=load_revisions(task_id),
        steps=ordered_steps(load_steps(project_id)),
    )


# --- schedule --------------------------------------------------------------

@bp.get("/schedule")
@login_required
def schedule(project_id: int):
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)
    rows = snapshot["tasks"]

    requested = request.args.get("sort")
    sort, direction = normalise_sort(requested, request.args.get("dir"))

    def arrange(subset, fallback):
        """Each table has a sensible default order until a column is chosen."""
        if requested in SORT_COLUMNS:
            return sort_tasks(subset, sort, direction)
        return sorted(subset, key=fallback)

    return render_template(
        "schedule.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        horizon=horizon, horizons=HORIZONS, steps=ordered_steps(load_steps(project_id)),
        sort=sort, direction=direction, sort_columns=SORT_COLUMNS, sorted_by=requested in SORT_COLUMNS,
        late=arrange([t for t in rows if t["is_late"]], lambda t: -t["days_late"]),
        upcoming=arrange([t for t in rows if t["is_upcoming"]], lambda t: t["days_to_due"]),
        behind=arrange([t for t in rows if t["is_behind"] and not t["is_late"]], lambda t: t["variance"]),
    )


# --- budget ----------------------------------------------------------------

@bp.get("/budget")
@login_required
def budget(project_id: int):
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)
    return render_template(
        "budget.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        budget_chart=charts.budget_hours(snapshot["trades"]),
    )


# --- period report ---------------------------------------------------------

@bp.get("/period")
@login_required
def period(project_id: int):
    project, role = load_project(project_id)
    start = from_input_or(request.args.get("from"), project["ntp_date"])
    end = from_input_or(request.args.get("to"), today())
    report = project_period(project, start, end)
    moved = [t for t in report["tasks"] if abs(t["earned_in_period"]) > 1e-9]
    return render_template(
        "period.html", project=project, role=role, report=report, moved=moved, start=start, end=end
    )


# --- timesheet -------------------------------------------------------------

@bp.get("/time")
@login_required
def timesheet(project_id: int):
    project, role = load_project(project_id)
    snapshot = project_snapshot(project)
    entries = query(
        """
        SELECT e.*, u.name AS user_name, tr.name AS trade_name, tr.color AS trade_color,
               t.wbs AS task_wbs, t.name AS task_name
        FROM time_entries e
        LEFT JOIN users u ON u.id = e.user_id
        LEFT JOIN trades tr ON tr.id = e.trade_id
        LEFT JOIN tasks t ON t.id = e.task_id
        WHERE e.project_id = ?
        ORDER BY e.entry_date DESC, e.id DESC
        LIMIT 500
        """,
        (project_id,),
    )
    booked: dict[object, float] = {}
    for entry in entries:
        key = entry["trade_id"] if entry["trade_id"] is not None else "none"
        booked[key] = booked.get(key, 0.0) + entry["hours"]

    return render_template(
        "timesheet.html",
        project=project, role=role, snapshot=snapshot, entries=entries, booked=booked,
        total_hours=sum(e["hours"] for e in entries), today=today(),
        can_report=_can_report(role),
    )


@bp.post("/time")
@login_required
def add_time(project_id: int):
    project, role = load_project(project_id, "member")
    hours = _to_float(request.form.get("hours"), 0)
    trade_id = _to_int(request.form.get("trade_id"))
    task_id = _to_int(request.form.get("task_id"))
    entry_date = from_input_or(request.form.get("entry_date"), today())

    if hours <= 0:
        flash("Enter the number of hours worked", "error")
    elif trade_id and not query_one("SELECT 1 FROM trades WHERE id = ? AND project_id = ?", (trade_id, project_id)):
        flash("That trade does not belong to this project", "error")
    elif task_id and not query_one("SELECT 1 FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)):
        flash("That deliverable does not belong to this project", "error")
    else:
        insert(
            """
            INSERT INTO time_entries (project_id, trade_id, task_id, user_id, entry_date, hours, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, trade_id, task_id, g.user["id"], entry_date, hours,
             (request.form.get("description") or "").strip()),
        )
        flash(f"Booked {hours:g} hours", "success")

    return _back("projects.timesheet", project_id)


@bp.post("/time/<int:entry_id>/delete")
@login_required
def delete_time(project_id: int, entry_id: int):
    project, role = load_project(project_id, "member")
    entry = query_one("SELECT * FROM time_entries WHERE id = ? AND project_id = ?", (entry_id, project_id))
    if entry is None:
        abort(404)
    # Members may remove their own bookings; managers may remove anyone's.
    if entry["user_id"] != g.user["id"] and not _can_edit(role):
        flash("You can only delete your own time entries", "error")
    else:
        execute("DELETE FROM time_entries WHERE id = ?", (entry_id,))
        flash("Time entry deleted", "success")
    return _back("projects.timesheet", project_id)


# --- setup -----------------------------------------------------------------

def _setup_editable(project_id: int, role: str) -> bool:
    """Setup changes need manager access *and* the sheet to be unlocked."""
    return _can_edit(role) and setup_unlocked(project_id)


def _require_setup_edit(project_id: int, role: str) -> bool:
    if not _can_edit(role):
        flash("You need manager access to change the project setup.", "error")
        return False
    if not setup_unlocked(project_id):
        flash("The setup sheet is locked. Unlock it before making changes.", "error")
        return False
    return True


@bp.get("/setup")
@login_required
def setup(project_id: int):
    project, role = load_project(project_id)
    snapshot = project_snapshot(project)
    members = query(
        """
        SELECT u.id, u.name, u.email, m.role
        FROM project_members m JOIN users u ON u.id = m.user_id
        WHERE m.project_id = ? ORDER BY u.name
        """,
        (project_id,),
    )
    owner = query_one("SELECT id, name, email FROM users WHERE id = ?", (project["owner_id"],))
    return render_template(
        "setup.html",
        project=project, role=role, snapshot=snapshot,
        sections=load_sections(project_id), trades=load_trades(project_id),
        steps=ordered_steps(load_steps(project_id)),
        members=members, owner=owner, series=SERIES_SLOTS,
        can_edit=_setup_editable(project_id, role), is_manager=_can_edit(role),
        unlocked=setup_unlocked(project_id),
        editing=_to_int(request.args.get("split")),
    )


@bp.post("/setup/unlock")
@login_required
def unlock(project_id: int):
    from ..auth import check_setup_password, lock_setup, unlock_setup

    project, role = load_project(project_id, "manager")
    if request.form.get("action") == "lock":
        lock_setup(project_id)
        flash("Setup sheet locked", "success")
    elif check_setup_password(project, request.form.get("password") or ""):
        unlock_setup(project_id)
        flash("Setup sheet unlocked", "success")
    else:
        flash("Incorrect setup password", "error")
    return _back("projects.setup", project_id)


@bp.post("/setup/password")
@login_required
def change_setup_password(project_id: int):
    from werkzeug.security import generate_password_hash

    from ..auth import check_setup_password

    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    current = request.form.get("current") or ""
    new = request.form.get("new") or ""
    if not check_setup_password(project, current):
        flash("The current setup password is incorrect", "error")
    elif len(new) < 4:
        flash("The setup password must be at least 4 characters", "error")
    else:
        execute("UPDATE projects SET setup_password_hash = ? WHERE id = ?",
                (generate_password_hash(new), project_id))
        flash("Setup password changed", "success")
    return _back("projects.setup", project_id)


# --- workflow steps --------------------------------------------------------

@bp.post("/steps")
@login_required
def save_steps(project_id: int):
    """Saves every step's percentage, anchor and day offset in one go."""
    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    if request.form.get("action") == "reset":
        execute("DELETE FROM workflow_steps WHERE project_id = ?", (project_id,))
        install_default_steps(project_id)
        flash("Workflow reset to the default design steps", "success")
        return _back("projects.setup", project_id)

    if request.form.get("action") == "add":
        name = (request.form.get("name") or "").strip()
        key = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
        if not name:
            flash("Enter a step name", "error")
        elif query_one("SELECT 1 FROM workflow_steps WHERE project_id = ? AND key = ?", (project_id, key)):
            flash("A step with that name already exists", "error")
        else:
            insert(
                """
                INSERT INTO workflow_steps (project_id, key, name, percent, anchor, offset_days, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, key, name, _to_float(request.form.get("percent")) / 100,
                 request.form.get("anchor") or "submission", _to_float(request.form.get("offset_days")),
                 next_sort_order("workflow_steps", project_id)),
            )
            flash(f"Step \u201c{name}\u201d added", "success")
        return _back("projects.setup", project_id)

    if request.form.get("action", "").startswith("delete:"):
        step_id = _to_int(request.form["action"].split(":", 1)[1])
        execute("DELETE FROM workflow_steps WHERE id = ? AND project_id = ?", (step_id, project_id))
        flash("Step removed", "success")
        return _back("projects.setup", project_id)

    saved = 0
    for step in load_steps(project_id):
        sid = step["id"]
        if f"name_{sid}" not in request.form:
            continue
        execute(
            "UPDATE workflow_steps SET name = ?, percent = ?, anchor = ?, offset_days = ? WHERE id = ? AND project_id = ?",
            (
                (request.form.get(f"name_{sid}") or step["name"]).strip(),
                max(0.0, min(1.0, _to_float(request.form.get(f"percent_{sid}"), step["percent"] * 100) / 100)),
                request.form.get(f"anchor_{sid}") or step["anchor"],
                _to_float(request.form.get(f"offset_{sid}"), step["offset_days"]),
                sid, project_id,
            ),
        )
        saved += 1
    flash(f"Workflow saved ({saved} step{'' if saved == 1 else 's'})", "success")
    return _back("projects.setup", project_id)


@bp.post("/settings")
@login_required
def save_settings(project_id: int):
    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    code = (request.form.get("code") or "").strip()
    clash = query_one("SELECT 1 FROM projects WHERE code = ? AND id != ?", (code, project_id))
    if not code or not (request.form.get("name") or "").strip():
        flash("Project name and code are required", "error")
    elif clash:
        flash("A project with that code already exists", "error")
    else:
        execute(
            """
            UPDATE projects SET code = ?, name = ?, client = ?, description = ?, ntp_date = ?,
                   duration_months = ?, days_per_month = ?, hours_per_month = ?,
                   elapsed_day_offset = ?, max_revisions = ?, rework_days = ?,
                   revision_reset_step = ?, status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                code, request.form.get("name").strip(), (request.form.get("client") or "").strip(),
                (request.form.get("description") or "").strip(),
                from_input_or(request.form.get("ntp_date"), project["ntp_date"]),
                _to_float(request.form.get("duration_months"), project["duration_months"]),
                _to_float(request.form.get("days_per_month"), 30.4375),
                _to_float(request.form.get("hours_per_month"), 176),
                _to_float(request.form.get("elapsed_day_offset"), 0),
                max(0, int(_to_float(request.form.get("max_revisions"), project["max_revisions"]))),
                max(0.0, _to_float(request.form.get("rework_days"), project["rework_days"])),
                request.form.get("revision_reset_step") or project["revision_reset_step"],
                request.form.get("status") or "active", project_id,
            ),
        )
        flash("Project saved", "success")
    return _back("projects.setup", project_id)


@bp.post("/delete")
@login_required
def delete_project(project_id: int):
    project, _role = load_project(project_id, "owner")
    if (request.form.get("confirm") or "").strip() != project["code"]:
        flash("Type the project code to confirm deletion", "error")
        return _back("projects.setup", project_id)
    execute("DELETE FROM projects WHERE id = ?", (project_id,))
    flash(f'Deleted "{project["name"]}"', "success")
    return redirect(url_for("portfolio.index"))


# --- sections --------------------------------------------------------------

@bp.post("/sections")
@login_required
def add_section(project_id: int):
    _, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Enter a section name", "error")
    else:
        insert(
            "INSERT INTO sections (project_id, code, name, sort_order) VALUES (?, ?, ?, ?)",
            (project_id, (request.form.get("code") or "").strip(), name, next_sort_order("sections", project_id)),
        )
        flash("Section added", "success")
    return _back("projects.setup", project_id)


@bp.post("/sections/<int:section_id>")
@login_required
def save_section(project_id: int, section_id: int):
    _, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    if request.form.get("action") == "delete":
        execute("DELETE FROM sections WHERE id = ? AND project_id = ?", (section_id, project_id))
        flash("Section removed. Its deliverables are now unassigned.", "success")
    else:
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Section name cannot be empty", "error")
        else:
            execute(
                "UPDATE sections SET code = ?, name = ? WHERE id = ? AND project_id = ?",
                ((request.form.get("code") or "").strip(), name, section_id, project_id),
            )
            flash("Section saved", "success")
    return _back("projects.setup", project_id)


# --- trades ----------------------------------------------------------------

@bp.post("/trades")
@login_required
def add_trade(project_id: int):
    _, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    name = (request.form.get("name") or "").strip()
    key = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
    if not name:
        flash("Enter a trade name", "error")
    elif query_one("SELECT 1 FROM trades WHERE project_id = ? AND key = ?", (project_id, key)):
        flash("A trade with that name already exists on this project", "error")
    else:
        count = next_sort_order("trades", project_id)
        insert(
            "INSERT INTO trades (project_id, key, name, budget_hours, color, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
            (
                project_id, key, name, _to_float(request.form.get("budget_hours")),
                request.form.get("color") or SERIES_SLOTS[(count - 1) % len(SERIES_SLOTS)][1], count,
            ),
        )
        flash("Trade added", "success")
    return _back("projects.setup", project_id)


@bp.post("/trades/<int:trade_id>")
@login_required
def save_trade(project_id: int, trade_id: int):
    _, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    if request.form.get("action") == "delete":
        execute("DELETE FROM trades WHERE id = ? AND project_id = ?", (trade_id, project_id))
        flash("Trade removed, along with its share of each deliverable", "success")
    else:
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("Trade name cannot be empty", "error")
        else:
            execute(
                "UPDATE trades SET name = ?, budget_hours = ?, color = ? WHERE id = ? AND project_id = ?",
                (name, _to_float(request.form.get("budget_hours")), request.form.get("color") or "#2a78d6",
                 trade_id, project_id),
            )
            flash("Trade saved", "success")
    return _back("projects.setup", project_id)


# --- deliverables ----------------------------------------------------------

def _task_dates(project, form) -> tuple[str, str]:
    """A deliverable's dates, entered either as dates or as days from NTP."""
    from datetime import timedelta

    from ..calc import parse_date

    ntp = parse_date(project["ntp_date"])

    def resolve(date_field: str, days_field: str) -> str:
        typed = from_input(form.get(date_field))
        if typed:
            return typed
        days = (form.get(days_field) or "").strip()
        if days:
            return (ntp + timedelta(days=_to_float(days))).isoformat()
        return ""

    start = resolve("start_date", "start_days")
    submission = resolve("submission_date", "submission_days")
    return (start or submission), (submission or start)


@bp.post("/tasks")
@login_required
def add_task(project_id: int):
    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    name = (request.form.get("name") or "").strip()
    section_id = _to_int(request.form.get("section_id"))
    if not name:
        flash("Enter a deliverable name", "error")
        return _back("projects.setup", project_id)
    if section_id and not query_one("SELECT 1 FROM sections WHERE id = ? AND project_id = ?", (section_id, project_id)):
        flash("That section does not belong to this project", "error")
        return _back("projects.setup", project_id)

    start_date, submission_date = _task_dates(project, request.form)
    if not submission_date:
        flash("Enter a submission date, or a number of days from NTP", "error")
        return _back("projects.setup", project_id)

    task_id = insert(
        """
        INSERT INTO tasks (project_id, section_id, wbs, name, weight_points,
                           start_date, submission_date, tracking, remarks, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id, section_id, (request.form.get("wbs") or "").strip(), name,
            _to_float(request.form.get("weight_points")), start_date, submission_date,
            request.form.get("tracking") or "workflow",
            (request.form.get("remarks") or "").strip(), next_sort_order("tasks", project_id),
        ),
    )
    # Start with an even split so the line is measurable straight away.
    trades = load_trades(project_id)
    if trades:
        set_allocations(task_id, project_id, {t["id"]: 1 / len(trades) for t in trades})
    flash("Deliverable added", "success")
    return _back("projects.setup", project_id)


@bp.post("/tasks/<int:task_id>/edit")
@login_required
def save_task(project_id: int, task_id: int):
    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    task = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if task is None:
        abort(404)

    action = request.form.get("action")
    if action == "delete":
        execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        flash("Deliverable deleted", "success")
        return _back("projects.setup", project_id)

    if action == "split":
        raw = {
            _to_int(key.removeprefix("alloc_")): _to_float(value)
            for key, value in request.form.items()
            if key.startswith("alloc_")
        }
        try:
            set_allocations(task_id, project_id, {k: v / 100 for k, v in raw.items() if k is not None})
            flash("Trade split saved", "success")
        except AllocationError as exc:
            flash(str(exc), "error")
            return _back("projects.setup", project_id, split=task_id)
        return _back("projects.setup", project_id)

    name = (request.form.get("name") or "").strip()
    section_id = _to_int(request.form.get("section_id"))
    if not name:
        flash("Deliverable name cannot be empty", "error")
    else:
        start_date, submission_date = _task_dates(project, request.form)
        execute(
            """
            UPDATE tasks SET wbs = ?, name = ?, section_id = ?, weight_points = ?,
                   start_date = ?, submission_date = ?, tracking = ?, remarks = ?,
                   updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                (request.form.get("wbs") or "").strip(), name, section_id,
                _to_float(request.form.get("weight_points")),
                start_date or task["start_date"], submission_date or task["submission_date"],
                request.form.get("tracking") or task["tracking"],
                (request.form.get("remarks") or "").strip(), task_id,
            ),
        )
        flash("Deliverable saved", "success")
    return _back("projects.setup", project_id)


@bp.post("/setup/save-all")
@login_required
def save_all(project_id: int):
    """Saves every change on the Setup sheet in one go.

    The whole page belongs to one form, so project settings, the workflow,
    trades, sections and every deliverable are written together — and in one
    transaction, so a rejected value does not leave the sheet half saved.
    """
    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    form = request.form
    code = (form.get("code") or "").strip()
    name = (form.get("name") or "").strip()
    if not code or not name:
        flash("Project name and code are required", "error")
        return _back("projects.setup", project_id)
    if query_one("SELECT 1 FROM projects WHERE code = ? AND id != ?", (code, project_id)):
        flash("A project with that code already exists", "error")
        return _back("projects.setup", project_id)

    steps = load_steps(project_id)
    trades = load_trades(project_id)
    sections = load_sections(project_id)
    tasks = query("SELECT * FROM tasks WHERE project_id = ?", (project_id,))

    # Trade splits are checked before anything is written, so an invalid one
    # cannot leave the rest of the sheet saved and that line untouched.
    splits: dict[int, dict[int, float]] = {}
    for task in tasks:
        supplied = {
            trade["id"]: _to_float(form.get(f"task_{task['id']}_alloc_{trade['id']}"))
            for trade in trades
            if f"task_{task['id']}_alloc_{trade['id']}" in form
        }
        if not supplied:
            continue
        total = sum(supplied.values())
        if abs(total - 100) > 0.5:
            flash(
                f"{task['wbs'] or task['name'][:40]}: the trade split totals {total:.0f}%, not 100%. "
                "Nothing was saved.",
                "error",
            )
            return _back("projects.setup", project_id)
        splits[task["id"]] = {tid: pct / 100 for tid, pct in supplied.items()}

    from ..db import get_db

    conn = get_db()
    changed = {"steps": 0, "trades": 0, "sections": 0, "tasks": 0}
    with conn:
        conn.execute(
            """
            UPDATE projects SET code = ?, name = ?, client = ?, description = ?, ntp_date = ?,
                   duration_months = ?, days_per_month = ?, hours_per_month = ?,
                   elapsed_day_offset = ?, max_revisions = ?, rework_days = ?,
                   revision_reset_step = ?, status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                code, name, (form.get("client") or "").strip(), (form.get("description") or "").strip(),
                from_input_or(form.get("ntp_date"), project["ntp_date"]),
                _to_float(form.get("duration_months"), project["duration_months"]),
                _to_float(form.get("days_per_month"), 30.4375),
                _to_float(form.get("hours_per_month"), 176),
                _to_float(form.get("elapsed_day_offset"), 0),
                max(0, int(_to_float(form.get("max_revisions"), project["max_revisions"]))),
                max(0.0, _to_float(form.get("rework_days"), project["rework_days"])),
                form.get("revision_reset_step") or project["revision_reset_step"],
                form.get("status") or "active", project_id,
            ),
        )

        for step in steps:
            field = f"step_{step['id']}_name"
            if field not in form:
                continue
            conn.execute(
                """
                UPDATE workflow_steps SET name = ?, percent = ?, anchor = ?, offset_days = ?
                WHERE id = ? AND project_id = ?
                """,
                (
                    (form.get(field) or step["name"]).strip(),
                    max(0.0, min(1.0, _to_float(form.get(f"step_{step['id']}_percent"), step["percent"] * 100) / 100)),
                    form.get(f"step_{step['id']}_anchor") or step["anchor"],
                    _to_float(form.get(f"step_{step['id']}_offset"), step["offset_days"]),
                    step["id"], project_id,
                ),
            )
            changed["steps"] += 1

        for trade in trades:
            field = f"trade_{trade['id']}_name"
            if field not in form:
                continue
            conn.execute(
                "UPDATE trades SET name = ?, budget_hours = ?, color = ? WHERE id = ? AND project_id = ?",
                (
                    (form.get(field) or trade["name"]).strip(),
                    _to_float(form.get(f"trade_{trade['id']}_budget"), trade["budget_hours"]),
                    form.get(f"trade_{trade['id']}_color") or trade["color"],
                    trade["id"], project_id,
                ),
            )
            changed["trades"] += 1

        for section in sections:
            field = f"section_{section['id']}_name"
            if field not in form:
                continue
            conn.execute(
                "UPDATE sections SET code = ?, name = ? WHERE id = ? AND project_id = ?",
                (
                    (form.get(f"section_{section['id']}_code") or "").strip(),
                    (form.get(field) or section["name"]).strip(),
                    section["id"], project_id,
                ),
            )
            changed["sections"] += 1

        for task in tasks:
            field = f"task_{task['id']}_name"
            if field not in form:
                continue
            start, submission = _task_dates(
                project,
                {
                    "start_date": form.get(f"task_{task['id']}_start_date"),
                    "submission_date": form.get(f"task_{task['id']}_submission_date"),
                    "start_days": "", "submission_days": "",
                },
            )
            section_id = _to_int(form.get(f"task_{task['id']}_section"))
            conn.execute(
                """
                UPDATE tasks SET wbs = ?, name = ?, section_id = ?, weight_points = ?,
                       start_date = ?, submission_date = ?, tracking = ?, remarks = ?,
                       updated_at = datetime('now')
                WHERE id = ? AND project_id = ?
                """,
                (
                    (form.get(f"task_{task['id']}_wbs") or "").strip(),
                    (form.get(field) or task["name"]).strip(),
                    section_id,
                    _to_float(form.get(f"task_{task['id']}_points"), task["weight_points"]),
                    start or task["start_date"], submission or task["submission_date"],
                    form.get(f"task_{task['id']}_tracking") or task["tracking"],
                    (form.get(f"task_{task['id']}_remarks") or "").strip(),
                    task["id"], project_id,
                ),
            )
            changed["tasks"] += 1

            if task["id"] in splits:
                conn.execute("DELETE FROM task_allocations WHERE task_id = ?", (task["id"],))
                conn.executemany(
                    "INSERT INTO task_allocations (task_id, trade_id, pct) VALUES (?, ?, ?)",
                    [(task["id"], tid, pct) for tid, pct in splits[task["id"]].items() if pct > 0],
                )

        # A step percentage may have moved, so re-derive each workflow line.
        percentages = {r["key"]: r["percent"] for r in
                       conn.execute("SELECT key, percent FROM workflow_steps WHERE project_id = ?", (project_id,))}
        for row in conn.execute(
            "SELECT id, tracking, status_key FROM tasks WHERE project_id = ? AND tracking = 'workflow'",
            (project_id,),
        ).fetchall():
            conn.execute("UPDATE tasks SET actual_pct = ? WHERE id = ?",
                         (percentages.get(row["status_key"], 0.0), row["id"]))

    flash(
        f"Saved — project settings, {changed['steps']} workflow steps, {changed['trades']} trades, "
        f"{changed['sections']} sections and {changed['tasks']} deliverables",
        "success",
    )
    return _back("projects.setup", project_id)


@bp.post("/setup/remove")
@login_required
def remove_item(project_id: int):
    """Deletes one thing from the Setup sheet.

    Every row's delete button posts here, so the rest of the page can live in a
    single Save all form without nesting forms inside it.
    """
    _, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    target = (request.form.get("target") or "").split(":", 1)
    if len(target) != 2:
        flash("Nothing to remove", "error")
        return _back("projects.setup", project_id)

    kind, raw_id = target
    item_id = _to_int(raw_id)
    tables = {
        "step": ("workflow_steps", "Step removed"),
        "trade": ("trades", "Trade removed, along with its share of each deliverable"),
        "section": ("sections", "Section removed. Its deliverables are now unassigned."),
        "task": ("tasks", "Deliverable deleted"),
    }
    if kind not in tables or item_id is None:
        flash("Nothing to remove", "error")
        return _back("projects.setup", project_id)

    table, message = tables[kind]
    execute(f"DELETE FROM {table} WHERE id = ? AND project_id = ?", (item_id, project_id))
    flash(message, "success")
    return _back("projects.setup", project_id)


# --- Excel round trip ------------------------------------------------------

@bp.get("/setup/export")
@login_required
def export_setup(project_id: int):
    """The whole setup as a workbook, ready to edit and import back."""
    from flask import send_file

    from ..excel import ExcelUnavailable, build_workbook
    from ..service import load_tasks

    project, role = load_project(project_id)
    try:
        data = build_workbook(
            project, ordered_steps(load_steps(project_id)), load_trades(project_id),
            load_sections(project_id), load_tasks(project_id),
        )
    except ExcelUnavailable as exc:
        flash(str(exc), "error")
        return _back("projects.setup", project_id)

    stamp = today().replace("-", "")
    return send_file(
        io.BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"{project['code']}-setup-{stamp}.xlsx",
    )


@bp.post("/setup/import")
@login_required
def import_setup(project_id: int):
    """Replaces the setup from an edited workbook.

    The file is parsed in full before anything is written, and the whole
    replacement runs in one transaction, so a bad file leaves the project as it
    was.
    """
    from ..excel import ExcelUnavailable
    from ..excel import ImportError_ as WorkbookError
    from ..excel import read_workbook

    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    upload = request.files.get("workbook")
    if upload is None or not upload.filename:
        flash("Choose a workbook to import", "error")
        return _back("projects.setup", project_id)
    if not upload.filename.lower().endswith((".xlsx", ".xlsm")):
        flash("Import expects an .xlsx file exported from this page", "error")
        return _back("projects.setup", project_id)

    try:
        parsed = read_workbook(upload.read())
    except (WorkbookError, ExcelUnavailable) as exc:
        flash(str(exc), "error")
        return _back("projects.setup", project_id)

    summary = _apply_setup(project, parsed)
    flash(
        f"Imported {summary['tasks']} deliverables, {summary['trades']} trades, "
        f"{summary['sections']} sections and {summary['steps']} workflow steps",
        "success",
    )
    return _back("projects.setup", project_id)


def _apply_setup(project, parsed) -> dict[str, int]:
    """Writes an imported workbook over the project's setup, in one transaction.

    Progress is preserved: a deliverable keeps its reported status and revision
    where the workbook supplies them.
    """
    from ..db import get_db

    project_id = project["id"]
    conn = get_db()
    with conn:
        settings = parsed["project"]
        if settings:
            conn.execute(
                """
                UPDATE projects SET name = ?, client = ?, description = ?, ntp_date = ?,
                       duration_months = ?, days_per_month = ?, hours_per_month = ?,
                       elapsed_day_offset = ?, max_revisions = ?, rework_days = ?,
                       revision_reset_step = ?, status = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    str(settings.get("name") or project["name"]).strip(),
                    str(settings.get("client") or "").strip(),
                    str(settings.get("description") or "").strip(),
                    from_input_or(settings.get("ntp_date"), project["ntp_date"]),
                    _to_float(settings.get("duration_months"), project["duration_months"]),
                    _to_float(settings.get("days_per_month"), project["days_per_month"]),
                    _to_float(settings.get("hours_per_month"), project["hours_per_month"]),
                    _to_float(settings.get("elapsed_day_offset"), project["elapsed_day_offset"]),
                    int(_to_float(settings.get("max_revisions"), project["max_revisions"])),
                    _to_float(settings.get("rework_days"), project["rework_days"]),
                    str(settings.get("revision_reset_step") or project["revision_reset_step"]).strip(),
                    str(settings.get("status") or project["status"]).strip(),
                    project_id,
                ),
            )

        if parsed["steps"]:
            # A step's key is what every deliverable's status points at, so keep
            # the existing key whenever the name still matches — otherwise a
            # re-import would silently detach every reported status.
            existing_keys = {
                row["name"].strip().lower(): row["key"]
                for row in conn.execute("SELECT key, name FROM workflow_steps WHERE project_id = ?", (project_id,))
            }
            conn.execute("DELETE FROM workflow_steps WHERE project_id = ?", (project_id,))
            for order, step in enumerate(parsed["steps"], start=1):
                generated = "".join(c if c.isalnum() else "_" for c in step["name"].lower()).strip("_")
                key = existing_keys.get(step["name"].strip().lower()) or generated or f"step_{order}"
                conn.execute(
                    """
                    INSERT INTO workflow_steps (project_id, key, name, percent, anchor, offset_days, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, key, step["name"], step["percent"],
                     step["anchor"], step["offset_days"], order),
                )

        # Trades and sections are matched by name so their ids — and therefore
        # the hours already booked against them — survive the import.
        trade_ids: dict[str, int] = {}
        existing_trades = {r["name"].lower(): r for r in
                           conn.execute("SELECT * FROM trades WHERE project_id = ?", (project_id,))}
        for order, trade in enumerate(parsed["trades"], start=1):
            found = existing_trades.pop(trade["name"].lower(), None)
            if found:
                conn.execute(
                    "UPDATE trades SET name = ?, budget_hours = ?, color = ?, sort_order = ? WHERE id = ?",
                    (trade["name"], trade["budget_hours"], trade["color"], order, found["id"]),
                )
                trade_ids[trade["name"].lower()] = found["id"]
            else:
                key = "".join(c if c.isalnum() else "_" for c in trade["name"].lower()).strip("_")
                cursor = conn.execute(
                    "INSERT INTO trades (project_id, key, name, budget_hours, color, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                    (project_id, key or f"trade_{order}", trade["name"], trade["budget_hours"],
                     trade["color"], order),
                )
                trade_ids[trade["name"].lower()] = cursor.lastrowid
        for leftover in existing_trades.values():
            conn.execute("DELETE FROM trades WHERE id = ?", (leftover["id"],))

        section_ids: dict[str, int] = {}
        existing_sections = {r["name"].lower(): r for r in
                             conn.execute("SELECT * FROM sections WHERE project_id = ?", (project_id,))}
        for order, section in enumerate(parsed["sections"], start=1):
            found = existing_sections.pop(section["name"].lower(), None)
            if found:
                conn.execute("UPDATE sections SET code = ?, sort_order = ? WHERE id = ?",
                             (section["code"], order, found["id"]))
                section_ids[section["name"].lower()] = found["id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO sections (project_id, code, name, sort_order) VALUES (?, ?, ?, ?)",
                    (project_id, section["code"], section["name"], order),
                )
                section_ids[section["name"].lower()] = cursor.lastrowid
        for leftover in existing_sections.values():
            conn.execute("DELETE FROM sections WHERE id = ?", (leftover["id"],))

        # Deliverables are matched on WBS so progress already reported against a
        # line is kept when the workbook comes back.
        existing_tasks = {}
        for row in conn.execute("SELECT * FROM tasks WHERE project_id = ?", (project_id,)):
            existing_tasks[(row["wbs"] or "").strip().lower() or f"#{row['id']}"] = row

        seen: set[int] = set()
        for order, task in enumerate(parsed["tasks"], start=1):
            section_id = section_ids.get(task["section"].lower()) if task["section"] else None
            tracking = "simple" if task["tracking"].startswith("simple") else "workflow"
            key = task["wbs"].strip().lower()
            found = existing_tasks.get(key) if key else None

            # Status and revision are deliberately not taken from the workbook,
            # so importing an older export cannot revert progress reported since.
            values = (task["wbs"], task["name"], section_id, task["weight_points"],
                      task["start_date"], task["submission_date"], tracking,
                      task["remarks"], order)
            if found:
                conn.execute(
                    """
                    UPDATE tasks SET wbs = ?, name = ?, section_id = ?, weight_points = ?,
                           start_date = ?, submission_date = ?, tracking = ?,
                           remarks = ?, sort_order = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    values + (found["id"],),
                )
                task_id = found["id"]
            else:
                task_id = conn.execute(
                    """
                    INSERT INTO tasks (project_id, wbs, name, section_id, weight_points,
                                       start_date, submission_date, tracking, remarks, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_id,) + values,
                ).lastrowid
            seen.add(task_id)

            conn.execute("DELETE FROM task_allocations WHERE task_id = ?", (task_id,))
            for trade_name, share in task["allocations"].items():
                trade_id = trade_ids.get(trade_name.lower())
                if trade_id and share > 0:
                    conn.execute(
                        "INSERT INTO task_allocations (task_id, trade_id, pct) VALUES (?, ?, ?)",
                        (task_id, trade_id, share),
                    )

        for row in conn.execute("SELECT id FROM tasks WHERE project_id = ?", (project_id,)).fetchall():
            if row["id"] not in seen:
                conn.execute("DELETE FROM tasks WHERE id = ?", (row["id"],))

        # A step's percentage may have been edited in the workbook, so re-derive
        # each deliverable's percent complete from the status it already holds.
        steps = {r["key"]: r["percent"] for r in
                 conn.execute("SELECT key, percent FROM workflow_steps WHERE project_id = ?", (project_id,))}
        for row in conn.execute(
            "SELECT id, tracking, status_key FROM tasks WHERE project_id = ?", (project_id,)
        ).fetchall():
            if row["tracking"] == "workflow":
                conn.execute("UPDATE tasks SET actual_pct = ? WHERE id = ?",
                             (steps.get(row["status_key"], 0.0), row["id"]))

    return {
        "tasks": len(parsed["tasks"]), "trades": len(parsed["trades"]),
        "sections": len(parsed["sections"]), "steps": len(parsed["steps"]),
    }


# --- team ------------------------------------------------------------------

@bp.post("/members")
@login_required
def add_member(project_id: int):
    project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    email = (request.form.get("email") or "").strip().lower()
    member_role = request.form.get("role") or "member"
    user = query_one("SELECT * FROM users WHERE email = ? COLLATE NOCASE", (email,))

    if member_role not in ("manager", "member", "viewer"):
        flash("Choose a valid access level", "error")
    elif user is None:
        flash("No account with that email. Ask them to register first.", "error")
    elif user["id"] == project["owner_id"]:
        flash("That user already owns this project", "error")
    else:
        execute(
            """
            INSERT INTO project_members (project_id, user_id, role) VALUES (?, ?, ?)
            ON CONFLICT (project_id, user_id) DO UPDATE SET role = excluded.role
            """,
            (project_id, user["id"], member_role),
        )
        flash(f"{user['name']} added as {member_role}", "success")
    return _back("projects.setup", project_id)


@bp.post("/members/<int:user_id>/remove")
@login_required
def remove_member(project_id: int, user_id: int):
    _, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    execute("DELETE FROM project_members WHERE project_id = ? AND user_id = ?", (project_id, user_id))
    flash("Removed from the project", "success")
    return _back("projects.setup", project_id)
