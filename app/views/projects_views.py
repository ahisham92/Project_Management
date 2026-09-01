"""Everything scoped to a single project."""

from __future__ import annotations

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import charts
from ..auth import ROLE_RANK, load_project, login_required
from ..charts import SERIES_SLOTS
from ..db import execute, insert, query, query_one
from ..service import (
    AllocationError, load_sections, load_trades, next_sort_order, project_period,
    project_s_curve, project_snapshot, record_progress, set_allocations, today,
)

bp = Blueprint("projects", __name__, url_prefix="/projects/<int:project_id>")

HORIZONS = (7, 14, 30, 60, 90)


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
    data_date = request.args.get("data_date") or today()
    horizon = _to_int(request.args.get("horizon"), 30) or 30
    return data_date, min(365, max(1, horizon))


def _can_edit(role: str) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK["manager"]


def _can_report(role: str) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK["member"]


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
        return True

    groups: dict[object, dict] = {}
    for task in snapshot["tasks"]:
        if not keep(task):
            continue
        key = task["section_id"] if task["section_id"] is not None else "none"
        group = groups.setdefault(
            key, {"name": task["section_name"] or "Unassigned", "tasks": [], "weight": 0.0}
        )
        group["tasks"].append(task)
        group["weight"] += task["weight_pct"]

    return render_template(
        "tasks.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        groups=list(groups.values()), filters=FILTERS, active_filter=active, search=search,
        shown=sum(len(gr["tasks"]) for gr in groups.values()),
        can_report=_can_report(role),
        editing=_to_int(request.args.get("edit")),
    )


@bp.post("/tasks/<int:task_id>/progress")
@login_required
def update_progress(project_id: int, task_id: int):
    project, role = load_project(project_id, "member")
    task = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if task is None:
        abort(404)

    percent = _to_float(request.form.get("actual_pct"), -1)
    if not 0 <= percent <= 100:
        flash("Progress must be a value between 0% and 100%", "error")
    else:
        record_progress(
            task,
            percent / 100,
            (request.form.get("note") or "").strip(),
            request.form.get("data_date") or today(),
            g.user["id"],
        )
        flash(f"{task['wbs'] or task['name'][:40]} updated to {percent:g}%", "success")

    return _back(
        "projects.tasks", project_id,
        data_date=request.form.get("data_date") or None,
        filter=request.form.get("filter") or None,
        q=request.form.get("q") or None,
    )


# --- schedule --------------------------------------------------------------

@bp.get("/schedule")
@login_required
def schedule(project_id: int):
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)
    rows = snapshot["tasks"]

    return render_template(
        "schedule.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        horizon=horizon, horizons=HORIZONS,
        late=sorted((t for t in rows if t["is_late"]), key=lambda t: -t["days_late"]),
        upcoming=sorted((t for t in rows if t["is_upcoming"]), key=lambda t: t["days_to_due"]),
        behind=sorted((t for t in rows if t["is_behind"] and not t["is_late"]), key=lambda t: t["variance"]),
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
    start = request.args.get("from") or project["ntp_date"]
    end = request.args.get("to") or today()
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
    entry_date = request.form.get("entry_date") or today()

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
        members=members, owner=owner, series=SERIES_SLOTS,
        can_edit=_can_edit(role), editing=_to_int(request.args.get("split")),
    )


@bp.post("/settings")
@login_required
def save_settings(project_id: int):
    project, role = load_project(project_id, "manager")
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
                   elapsed_day_offset = ?, status = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                code, request.form.get("name").strip(), (request.form.get("client") or "").strip(),
                (request.form.get("description") or "").strip(), request.form.get("ntp_date") or project["ntp_date"],
                _to_float(request.form.get("duration_months"), project["duration_months"]),
                _to_float(request.form.get("days_per_month"), 30.4375),
                _to_float(request.form.get("hours_per_month"), 176),
                _to_float(request.form.get("elapsed_day_offset"), 0),
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
    load_project(project_id, "manager")
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
    load_project(project_id, "manager")
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
    load_project(project_id, "manager")
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
    load_project(project_id, "manager")
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

@bp.post("/tasks")
@login_required
def add_task(project_id: int):
    load_project(project_id, "manager")
    name = (request.form.get("name") or "").strip()
    section_id = _to_int(request.form.get("section_id"))
    if not name:
        flash("Enter a deliverable name", "error")
        return _back("projects.setup", project_id)
    if section_id and not query_one("SELECT 1 FROM sections WHERE id = ? AND project_id = ?", (section_id, project_id)):
        flash("That section does not belong to this project", "error")
        return _back("projects.setup", project_id)

    task_id = insert(
        """
        INSERT INTO tasks (project_id, section_id, wbs, name, weight_points,
                           start_month, finish_month, remarks, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id, section_id, (request.form.get("wbs") or "").strip(), name,
            _to_float(request.form.get("weight_points")), _to_float(request.form.get("start_month")),
            _to_float(request.form.get("finish_month")), (request.form.get("remarks") or "").strip(),
            next_sort_order("tasks", project_id),
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
    load_project(project_id, "manager")
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
        execute(
            """
            UPDATE tasks SET wbs = ?, name = ?, section_id = ?, weight_points = ?,
                   start_month = ?, finish_month = ?, remarks = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (
                (request.form.get("wbs") or "").strip(), name, section_id,
                _to_float(request.form.get("weight_points")), _to_float(request.form.get("start_month")),
                _to_float(request.form.get("finish_month")), (request.form.get("remarks") or "").strip(),
                task_id,
            ),
        )
        flash("Deliverable saved", "success")
    return _back("projects.setup", project_id)


# --- team ------------------------------------------------------------------

@bp.post("/members")
@login_required
def add_member(project_id: int):
    project, _role = load_project(project_id, "manager")
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
    load_project(project_id, "manager")
    execute("DELETE FROM project_members WHERE project_id = ? AND user_id = ?", (project_id, user_id))
    flash("Removed from the project", "success")
    return _back("projects.setup", project_id)
