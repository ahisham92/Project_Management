"""Everything scoped to a single project."""

from __future__ import annotations

import io

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for,
)

from .. import charts, offices
from ..auth import ROLE_RANK, load_project, login_required, setup_unlocked
from ..charts import SERIES_SLOTS
from ..dates import from_input, from_input_or, to_display
from ..db import execute, insert, query, query_one
from ..sorting import COLUMNS as SORT_COLUMNS
from ..sorting import normalise as normalise_sort
from ..sorting import sort_tasks
from ..schedule import KINDS, MODES, duration_between, finish_from, normalise_mode
from .portfolio_views import guide_page
from ..service import (
    REVIEW_CODES, AllocationError, LinkError, WorkflowError, add_link, install_default_steps, load_revisions,
    load_sections, load_steps, load_trades, next_sort_order, project_period, project_plan,
    add_calendar, add_holiday, apply_schedule, calendar_of, calendars_for,
    clear_node_positions, delete_calendar, load_calendars, load_holidays,
    project_pulse, remove_holiday, save_calendar, set_default_calendar,
    project_overview, project_s_curve, project_snapshot, record_comments,
    record_progress, remove_link, replace_links, set_node_position, simplify_layout,
    update_link,
    apply_setup_workbook, load_impacts, load_snapshots, load_template,
    resource_plan, restore_schedule, set_allocations,
    set_status, set_task_dates, squeeze_plan, apply_squeeze, today,
)
from ..resources import curve as resource_curve
from ..minutes_doc import TEMPLATE_FIELDS
from .handing_out import EXCEL, handed_out
from ..calendars import parse_days
from ..squeeze import SqueezeError
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


@bp.get("/pulse")
@login_required
def pulse(project_id: int):
    """What the page checks to see whether anyone else has changed anything."""
    from flask import jsonify

    load_project(project_id)
    return jsonify({"v": project_pulse(project_id)})


# --- dashboard -------------------------------------------------------------

@bp.app_context_processor
def _pulse_context():
    """The token the open page was drawn with, for the live check."""
    project_id = (request.view_args or {}).get("project_id")
    if not project_id or not g.get("user"):
        return {}
    try:
        return {"page_pulse": project_pulse(int(project_id)),
                "pulse_project_id": int(project_id)}
    except Exception:  # noqa: BLE001 - a missing project must not break the page
        return {}


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
        overview=project_overview(project, snapshot),
        attention=attention,
        s_curve=charts.s_curve(points, snapshot["data_date"]),
        trade_progress=charts.trade_progress(snapshot["trades"]),
        trade_weight=charts.trade_weight(snapshot["trades"]),
        # Hours planned against hours booked: the same question as the S-curve,
        # asked in the currency a team leader staffs with.
        hours_curve=charts.hours_curve(resource_curve(resource_plan(project, snapshot))),
    )


@bp.get("/help")
@login_required
def guide(project_id: int):
    """How to use this: what each tab is for and what every word on it means."""
    project, role = load_project(project_id)
    return render_template("guide.html", project=project, role=role,
                           **guide_page(project))


# --- progress --------------------------------------------------------------

FILTERS = (
    ("all", "All"), ("late", "Late"), ("behind", "Behind plan"),
    ("client", "With client"),
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
    office = offices.normalise(request.args.get("office"))

    def keep(task) -> bool:
        if search and search.lower() not in f"{task['wbs']} {task['name']}".lower():
            return False
        # A deliverable is kept if the office has any share of it at all: two
        # offices sharing a line means both of them are working it.
        if office and office not in task["offices"]:
            return False
        if active == "late":
            return task["is_late"]
        if active == "behind":
            return task["is_behind"]
        if active == "client":
            return task["with_client"]
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
        "tasks.html", codes=REVIEW_CODES,
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        groups=grouped, filters=FILTERS, active_filter=active, search=search,
        office=office, office_list=offices.OFFICES,
        office_split=[o for o in snapshot["offices"] if o["office"]],
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

    trouble = ""
    if "status_key" in request.form:
        steps = load_steps(project_id)
        try:
            percent = set_status(task, (request.form.get("status_key") or "").strip(), note,
                                 data_date, g.user["id"], steps)
        except WorkflowError as exc:
            trouble = str(exc)
        else:
            trouble = ""
    else:
        typed = _to_float(request.form.get("actual_pct"), -1)
        if not 0 <= typed <= 100:
            trouble = "Progress must be a value between 0% and 100%"
        else:
            record_progress(task, typed / 100, note, data_date, g.user["id"])
            percent = typed / 100

    if _wants_json():
        return _progress_answer(project_id, task_id, data_date, trouble)
    flash(trouble or f"{label} updated to {percent * 100:g}%", "error" if trouble else "success")
    return _return_to_tasks(project_id)


def _progress_answer(project_id: int, task_id: int, data_date: str, trouble: str = ""):
    """A row saved on its own answers with how it now reads."""
    from flask import jsonify

    if trouble:
        return jsonify({"ok": False, "error": trouble}), 400

    project, _role = load_project(project_id)
    snapshot = project_snapshot(project, data_date)
    row = next((t for t in snapshot["tasks"] if t["id"] == task_id), None)
    if row is None:
        return jsonify({"ok": False}), 404

    bits = current_app.jinja_env.get_template("partials/progress_bits.html").module
    # The buttons follow the state: a line that has just been submitted can now
    # take a Code B or C, and the row should say so without a page load.
    buttons = render_template(
        "partials/progress_actions_row.html", project=project, task=row,
        params={"filter": request.args.get("filter") or "all",
                "data_date": to_display(data_date)},
    )
    return jsonify({
        "ok": True,
        "progress_html": str(bits.progress_cell(row, snapshot["max_revisions"])),
        "status_html": str(bits.status_cell(row, snapshot["max_revisions"])),
        "variance_html": str(bits.variance_cell(row)),
        "actions_html": buttons,
        "actual": round(float(row["actual_pct"]) * 100),
        "status_key": row["status_key"] or "",
    })


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
            code=request.form.get("code") or "",
        )
    except WorkflowError as exc:
        flash(str(exc), "error")
        return _return_to_tasks(project_id)

    flash(
        f"{task['wbs'] or task['name'][:40]} — Code {result['code']}, "
        f"moved to revision {result['revision']} — "
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
    """The plan: what runs when, what depends on what, and what is critical."""
    project, role = load_project(project_id)
    data_date, _horizon = _params()
    plan = project_plan(project, data_date)

    requested = request.args.get("sort")
    sort, direction = normalise_sort(requested or "wbs", request.args.get("dir"))
    rows = sort_tasks(plan["tasks"], sort, direction)

    # Squeezing a stretch: worked out and shown, and nothing moves until the
    # Squeeze button below it is pressed. A GET so the proposal can be read,
    # argued with and re-run without anything having happened.
    squeeze = squeeze_trouble = None
    squeeze_from = _to_int(request.args.get("from_task"))
    squeeze_to = _to_int(request.args.get("to_task"))
    squeeze_start = from_input(request.args.get("starts")) or ""
    squeeze_end = from_input(request.args.get("ends")) or ""
    held = [i for i in (_to_int(v) for v in request.args.getlist("hold")) if i]
    following = request.args.getlist("follow")
    if squeeze_from and squeeze_to and squeeze_start and squeeze_end:
        try:
            squeeze = squeeze_plan(project, squeeze_from, squeeze_to, squeeze_start,
                                   squeeze_end, held,
                                   following if "checked" in request.args else True)
        except SqueezeError as exc:
            squeeze_trouble = str(exc)

    first, last = plan["window"]
    return render_template(
        "schedule.html",
        project=project, role=role, plan=plan, tasks=rows, data_date=data_date,
        squeeze=squeeze, squeeze_trouble=squeeze_trouble, squeeze_from=squeeze_from,
        squeeze_to=squeeze_to, squeeze_start=squeeze_start, squeeze_end=squeeze_end,
        held=held, snapshots=load_snapshots(project_id),
        mode=normalise_mode(project["schedule_mode"]), modes=MODES,
        sort=sort, direction=direction,
        steps=ordered_steps(load_steps(project_id)),
        gantt=charts.gantt(rows, first, last, plan["data_date"]),
        network=charts.network(plan["tasks"], plan["links"], movable=_can_edit(role),
                              links_url=url_for("projects.add_dependency", project_id=project_id)),
        kinds=KINDS, can_edit=_can_edit(role), can_report=_can_report(role),
    )


@bp.post("/schedule/squeeze")
@login_required
def squeeze_schedule(project_id: int):
    """Carries out a squeeze the reader has looked at.

    The proposal is worked out again here from the two ends and the number of
    days rather than trusting dates posted back from a page — what comes back
    from a form is a request, not an answer.
    """
    # Manager access, the same as moving a single line on this tab.
    project, _role = load_project(project_id, "manager")

    first = _to_int(request.form.get("from_task"))
    last = _to_int(request.form.get("to_task"))
    starts = from_input(request.form.get("starts"))
    ends = from_input(request.form.get("ends"))
    held = [i for i in (_to_int(v) for v in request.form.getlist("hold")) if i]
    following = request.form.getlist("follow")
    if not (first and last and starts and ends):
        flash("Say which line the run starts on, which it ends on, and the two dates.", "error")
        return _back("projects.schedule", project_id, panel="squeeze")

    try:
        proposal = squeeze_plan(project, first, last, starts, ends, held, following)
    except SqueezeError as exc:
        flash(str(exc), "error")
        return _back("projects.schedule", project_id, panel="squeeze")

    done = apply_squeeze(project_id, proposal, g.user)
    meetings = ""
    if done["meetings_added"] or done["meetings_removed"]:
        parts = []
        if done["meetings_added"]:
            parts.append(f"{done['meetings_added']} meeting"
                         f"{'s' if done['meetings_added'] != 1 else ''} added")
        if done["meetings_removed"]:
            parts.append(f"{done['meetings_removed']} removed")
        meetings = ", " + " and ".join(parts)
    flash(
        f"Squeezed {done['squeezed']} deliverables — the run now finishes "
        f"{to_display(proposal['finish'])}"
        + (f", {proposal['saved_days']} days earlier" if proposal["saved_days"] > 0
           else f", {-proposal['saved_days']} days later" if proposal["saved_days"] < 0 else "")
        + (f", and {done['followed']} lines after it moved with it" if done["followed"] else "")
        + meetings
        + ". Undo it from the Squeeze panel.",
        "success")
    return _back("projects.schedule", project_id, panel="dates")


@bp.post("/schedule/restore/<int:snapshot_id>")
@login_required
def restore_squeeze(project_id: int, snapshot_id: int):
    """Puts every date back to where it was before a squeeze.

    Not the same arithmetic run backwards — that does not return where it
    started once anything has rounded — but the dates as they actually were.
    """
    _project, _role = load_project(project_id, "manager")
    put_back = restore_schedule(project_id, snapshot_id)
    if not put_back:
        flash("That saved state is no longer there", "error")
    else:
        flash(f"Put {put_back} deliverables back to where they were", "success")
    return _back("projects.schedule", project_id, panel="squeeze")


@bp.post("/schedule/mode")
@login_required
def schedule_mode(project_id: int):
    """Whether a line is entered as start + duration, or as two dates."""
    _project, _role = load_project(project_id, "manager")
    execute("UPDATE projects SET schedule_mode = ? WHERE id = ?",
            (normalise_mode(request.form.get("mode")), project_id))
    return _back("projects.schedule", project_id, panel="dates")


@bp.post("/schedule/<int:task_id>")
@login_required
def save_dates(project_id: int, task_id: int):
    """One line's dates, however the schedule is being entered.

    By duration the finish follows the start; by dates the duration follows the
    two. Either way whatever depends on this line is pushed out with it.
    """
    project, _role = load_project(project_id, "manager")
    task = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id))
    if task is None:
        abort(404)

    mine = calendar_of(dict(task), calendars_for(project))
    mode = normalise_mode(request.form.get("mode") or project["schedule_mode"])
    start = from_input(request.form.get("start_date")) or task["start_date"]
    if mode == "duration" or "duration_days" in request.form:
        days = _to_float(request.form.get("duration_days"),
                         duration_between(task["start_date"], task["submission_date"], mine))
        submission = finish_from(start, days, mine)
    else:
        submission = from_input(request.form.get("submission_date")) or task["submission_date"]
        if submission < start:
            submission = start

    moves = set_task_dates(project_id, task_id, start, submission)
    if not _wants_json():
        if moves:
            flash(f"Dates saved — {len(moves)} dependent deliverable"
                  f"{'' if len(moves) == 1 else 's'} moved with it", "success")
        else:
            flash("Dates saved", "success")
    return _plan_answer(project_id, task_id, moves)


@bp.get("/schedule/<int:task_id>")
@login_required
def task_panel(project_id: int, task_id: int):
    """One deliverable, opened from the schedule.

    Its own page without JavaScript, and the contents of a side panel with it —
    the same markup either way, so a change made in the panel redraws through
    the path everything else uses.
    """
    from ..calendars import week_label

    project, role = load_project(project_id)
    plan = project_plan(project, _params()[0])
    task = next((t for t in plan["tasks"] if t["id"] == task_id), None)
    if task is None:
        abort(404)

    body = render_template(
        "partials/task_panel.html",
        project=project, plan=plan, task=task, kinds=KINDS, kind_names=dict(KINDS),
        mode=normalise_mode(project["schedule_mode"]), week_label=week_label,
        can_edit=_can_edit(role),
    )
    if _wants_json():
        from flask import jsonify

        return jsonify({"ok": True, "panel_html": body, "title": f"{task['wbs']} {task['name']}"})
    return render_template("task.html", project=project, role=role, task=task, panel=body)


@bp.post("/schedule/links")
@login_required
def add_dependency(project_id: int):
    """A new link, from the form under the diagram or drawn on the diagram."""
    _project, _role = load_project(project_id, "manager")
    try:
        add_link(project_id, _to_int(request.form.get("predecessor_id")) or 0,
                 _to_int(request.form.get("successor_id")) or 0,
                 _to_float(request.form.get("lag_days"), 0),
                 request.form.get("kind") or "FS")
    except LinkError as exc:
        if _wants_json():
            from flask import jsonify

            return jsonify({"ok": False, "error": str(exc)}), 400
        flash(str(exc), "error")
        return _back("projects.schedule", project_id, panel="links")

    if _wants_json():
        return _links_answer(project_id, note="Dependency added")
    flash("Dependency added", "success")
    return _back("projects.schedule", project_id, panel="links")


@bp.post("/schedule/links/<int:link_id>")
@login_required
def save_dependency(project_id: int, link_id: int):
    """A link's lag or its type, changed where it stands."""
    _project, _role = load_project(project_id, "manager")
    try:
        link = update_link(
            project_id, link_id,
            lag_days=_to_float(request.form.get("lag_days"), 0) if "lag_days" in request.form else None,
            kind=request.form.get("kind") if "kind" in request.form else None,
            predecessor_id=(_to_int(request.form.get("predecessor_id"))
                            if "predecessor_id" in request.form else None),
            successor_id=(_to_int(request.form.get("successor_id"))
                          if "successor_id" in request.form else None),
        )
    except LinkError as exc:
        if _wants_json():
            from flask import jsonify

            return jsonify({"ok": False, "error": str(exc)}), 400
        flash(str(exc), "error")
        return _back("projects.schedule", project_id, panel="links")

    if link is None:
        abort(404)

    if _wants_json():
        return _links_answer(project_id, link_id=link_id)
    flash("Dependency saved", "success")
    return _back("projects.schedule", project_id, panel="links")


@bp.post("/schedule/links/<int:link_id>/delete")
@login_required
def delete_dependency(project_id: int, link_id: int):
    _project, _role = load_project(project_id, "manager")
    if not remove_link(project_id, link_id):
        abort(404)

    if _wants_json():
        return _links_answer(project_id, removed=link_id)
    flash("Dependency removed", "success")
    return _back("projects.schedule", project_id, panel="links")


def _links_answer(project_id: int, removed: int | None = None, link_id: int | None = None,
                  note: str = ""):
    """A link change answers with the plan as it now reads: the float a change
    moves, the diagram redrawn, and the row itself when either end has changed.
    """
    from flask import jsonify

    project, role = load_project(project_id)
    plan = project_plan(project)

    row_html = ""
    if link_id is not None:
        link = next((l for l in plan["links"] if l["id"] == link_id), None)
        if link is not None:
            # Rendered by the macro the table itself uses, so what is swapped
            # in is exactly what a reload would have drawn.
            row_html = render_template(
                "partials/link_row_one.html", project=project, link=link,
                kind_names=dict(KINDS), can_edit=_can_edit(role),
            )

    return jsonify({
        "ok": True,
        "removed": removed,
        "link_html": row_html,
        "rows": [
            {"id": row["id"], "float": row.get("total_float", 0),
             "critical": bool(row.get("is_critical"))}
            for row in plan["tasks"]
        ],
        "network_html": str(charts.network(plan["tasks"], plan["links"], movable=_can_edit(role),
                              links_url=url_for("projects.add_dependency", project_id=project_id))),
        "critical_count": plan["totals"]["critical"],
        "note": note,
    })


@bp.post("/schedule/layout/<int:task_id>")
@login_required
def move_node(project_id: int, task_id: int):
    """Where a box was dragged to on the dependency diagram."""
    from flask import jsonify

    _project, _role = load_project(project_id, "manager")
    if not set_node_position(project_id, task_id,
                             _to_float(request.form.get("x"), 0),
                             _to_float(request.form.get("y"), 0)):
        abort(404)
    if _wants_json():
        return jsonify({"ok": True})
    return _back("projects.schedule", project_id, panel="links")


@bp.get("/schedule.xlsx")
@login_required
def export_schedule(project_id: int):
    """The dates and durations as a workbook, ready to edit and import back."""
    from flask import send_file

    from ..excel import ExcelUnavailable, build_schedule_workbook

    project, _role = load_project(project_id)
    plan = project_plan(project)
    try:
        data = build_schedule_workbook(project, sort_tasks(plan["tasks"], "wbs", "asc"),
                                       normalise_mode(project["schedule_mode"]))
    except ExcelUnavailable as exc:
        flash(str(exc), "error")
        return _back("projects.schedule", project_id, panel="dates")

    stamp = today().replace("-", "")
    return handed_out(project_id, data, f"{project['code']}-schedule-{stamp}.xlsx",
                      EXCEL, "schedule", "The programme",
                      f"{len(plan['tasks'])} deliverables")


@bp.post("/schedule/import")
@login_required
def import_schedule(project_id: int):
    """Puts the dates where an edited workbook says they are."""
    from ..excel import ExcelUnavailable, ImportError_, read_schedule_workbook

    project, _role = load_project(project_id, "manager")
    upload = request.files.get("workbook")
    if upload is None or not upload.filename:
        flash("Choose a workbook to import", "error")
        return _back("projects.schedule", project_id, panel="dates")

    try:
        rows = read_schedule_workbook(upload.read())
    except (ExcelUnavailable, ImportError_) as exc:
        flash(str(exc), "error")
        return _back("projects.schedule", project_id, panel="dates")

    result = apply_schedule(project_id, rows, normalise_mode(project["schedule_mode"]))
    flash(
        f"{result['applied']} deliverable{'' if result['applied'] == 1 else 's'} rescheduled"
        + (f" · {len(result['skipped'])} skipped" if result["skipped"] else ""),
        "error" if result["skipped"] else "success",
    )
    for note in result["skipped"][:5]:
        flash(note, "error")
    return _back("projects.schedule", project_id, panel="dates")


@bp.get("/schedule/links.xlsx")
@login_required
def export_dependencies(project_id: int):
    """The dependencies as a workbook, ready to edit and import back."""
    from flask import send_file

    from ..excel import ExcelUnavailable, build_links_workbook

    project, _role = load_project(project_id)
    plan = project_plan(project)
    try:
        data = build_links_workbook(project, plan["tasks"], plan["links"])
    except ExcelUnavailable as exc:
        flash(str(exc), "error")
        return _back("projects.schedule", project_id, panel="links")

    stamp = today().replace("-", "")
    return handed_out(project_id, data, f"{project['code']}-dependencies-{stamp}.xlsx",
                      EXCEL, "dependencies", "The dependencies",
                      f"{len(plan['links'])} links")


@bp.post("/schedule/links/import")
@login_required
def import_dependencies(project_id: int):
    """Replaces the dependencies with what an edited workbook says."""
    from ..excel import ExcelUnavailable, ImportError_, read_links_workbook

    _project, _role = load_project(project_id, "manager")
    upload = request.files.get("workbook")
    if upload is None or not upload.filename:
        flash("Choose a workbook to import", "error")
        return _back("projects.schedule", project_id, panel="links")

    try:
        rows = read_links_workbook(upload.read())
    except (ExcelUnavailable, ImportError_) as exc:
        flash(str(exc), "error")
        return _back("projects.schedule", project_id, panel="links")

    result = replace_links(project_id, rows)
    flash(
        f"{result['added']} dependenc{'y' if result['added'] == 1 else 'ies'} imported"
        + (f" · {len(result['skipped'])} skipped" if result["skipped"] else ""),
        "error" if result["skipped"] else "success",
    )
    for note in result["skipped"][:5]:
        flash(note, "error")
    return _back("projects.schedule", project_id, panel="links")


@bp.post("/schedule/layout/simplify")
@login_required
def simplify_diagram(project_id: int):
    """Re-lays the diagram out so as few lines cross as can be managed."""
    _project, _role = load_project(project_id, "manager")
    result = simplify_layout(project_id)

    if not result["moved"]:
        note, tone = "Nothing is linked yet, so there is nothing to untangle", "error"
    elif result["before"] == result["after"]:
        note, tone = (
            f"Already as clear as it gets — {result['before']} crossing"
            f"{'' if result['before'] == 1 else 's'} left, and none of them can be undone"
            " without changing what the diagram says",
            "success",
        )
    else:
        note, tone = (
            f"Simplified — crossing lines down from {result['before']} to {result['after']}",
            "success",
        )

    if _wants_json():
        return _links_answer(project_id, note=note)
    flash(note, tone)
    return _back("projects.schedule", project_id, panel="links")


@bp.post("/schedule/layout/reset")
@login_required
def reset_layout(project_id: int):
    """Puts every box back where the automatic layout would draw it."""
    _project, _role = load_project(project_id, "manager")
    clear_node_positions(project_id)
    if _wants_json():
        return _links_answer(project_id)
    flash("The diagram is back to its automatic layout", "success")
    return _back("projects.schedule", project_id, panel="links")


def _wants_json() -> bool:
    return "application/json" in (request.headers.get("Accept") or "")


def _plan_answer(project_id: int, task_id: int, moves: dict):
    """A saved line answers with the rows that moved, so the page can redraw
    them without fetching the whole plan again."""
    if not _wants_json():
        return _back("projects.schedule", project_id, panel="dates")

    from flask import jsonify

    project, _role = load_project(project_id)
    plan = project_plan(project)
    by_id = {t["id"]: t for t in plan["tasks"]}
    touched = [task_id, *moves]
    return jsonify({
        "ok": True,
        "moved": [
            {
                "id": row["id"],
                "start": to_display(row["start_date"]),
                "submission": to_display(row["submission_date"]),
                "duration": row.get("duration_days", 0),
                "float": row.get("total_float", 0),
                "critical": bool(row.get("is_critical")),
                "team": row.get("team_name") or "—",
                "team_id": row.get("calendar_id") or "",
            }
            for row in (by_id[i] for i in touched if i in by_id)
        ],
        "stale": True,
    })


# --- budget ----------------------------------------------------------------

@bp.get("/budget")
@login_required
def budget(project_id: int):
    """Finance: the budget, and the hours booked against it.

    One tab rather than two. Reading a booked figure here and going somewhere
    else to see what made it is how a number stops being checked.
    """
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)
    entries, booked = _booked_hours(project_id)
    return render_template(
        "finance.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        budget_chart=charts.budget_hours(snapshot["trades"]),
        entries=entries, booked=booked, total_hours=sum(e["hours"] for e in entries),
        today=today(), can_report=_can_report(role),
    )


def _booked_hours(project_id: int) -> tuple[list, dict]:
    """The time entries, newest first, and the hours totalled by trade."""
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
    return list(entries), booked


# --- resources planning ----------------------------------------------------

@bp.get("/resources")
@login_required
def resources(project_id: int):
    """How many engineers, on what, in which week — and against what was booked.

    The budget already says what a trade may spend. This tab is the part
    somebody can act on: the ceiling after the margin, split across the
    deliverables by weight, spread over the weeks with the hours rising towards
    each submission, and divided into people.
    """
    project, role = load_project(project_id)
    data_date, horizon = _params()
    snapshot = project_snapshot(project, data_date, horizon)
    plan = resource_plan(project, snapshot)
    return render_template(
        "resources.html",
        project=project, role=role, snapshot=snapshot, data_date=data_date,
        plan=plan,
        hours_curve=charts.hours_curve(resource_curve(plan)),
        week_shape=charts.week_shape(plan["weeks"], plan["hours_per_week"]),
        can_edit=_can_edit(role),
    )


# --- summarized progress ---------------------------------------------------

@bp.get("/period")
@login_required
def period(project_id: int):
    project, role = load_project(project_id)
    start = from_input_or(request.args.get("from"), project["ntp_date"])
    end = from_input_or(request.args.get("to"), today())
    report = project_period(project, start, end)
    moved = [t for t in report["tasks"] if abs(t["earned_in_period"]) > 1e-9]
    return render_template(
        "summarized.html", project=project, role=role, report=report, moved=moved,
        start=start, end=end,
    )


# --- timesheet -------------------------------------------------------------
# The hours live on the Finance tab now, beside the budget they are charged
# against. This is kept so a bookmark, a link in an old email or anything
# pointing at the timesheet still lands somewhere useful.

@bp.get("/time")
@login_required
def timesheet(project_id: int):
    load_project(project_id)
    return redirect(url_for("projects.budget", project_id=project_id) + "#hours")


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


# How far out a trade split may read before it is a mistake rather than a
# rounding artefact. Two points is a line held in halves; sixty and sixty is
# somebody typing the wrong number.
NEAR_ENOUGH = 2.5


def _to_a_hundred(supplied: dict[int, float]) -> dict[int, float]:
    """A split nudged to total exactly 100, on the largest share."""
    whole = {tid: round(pct) for tid, pct in supplied.items()}
    drift = 100 - sum(whole.values())
    if drift and whole:
        biggest = max(whole, key=lambda tid: whole[tid])
        whole[biggest] += drift
    return {tid: float(pct) for tid, pct in whole.items()}


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
    from ..calendars import WEEK_PATTERNS, week_days
    from ..claude import EFFORTS
    from ..vault import carmen
    from .carmen_avatar import uploaded as carmen_uploaded

    return render_template(
        "setup.html",
        project=project, role=role, snapshot=snapshot,
        sections=load_sections(project_id), trades=load_trades(project_id),
        steps=ordered_steps(load_steps(project_id)),
        teams=load_calendars(project_id), holidays=load_holidays(project_id),
        week_days=week_days, week_patterns=WEEK_PATTERNS,
        # The keys live here now: one place, administrators only, and what is
        # set is set for everybody rather than per person.
        is_admin=g.user["role"] == "admin", carmen=carmen(), efforts=EFFORTS,
        carmen_picture_uploaded=carmen_uploaded() is not None,
        members=members, owner=owner, series=SERIES_SLOTS, office_list=offices.OFFICES,
        impacts=load_impacts(project_id),
        minutes_template=load_template(project_id, "minutes", with_content=False),
        template_fields=TEMPLATE_FIELDS,
        can_edit=_setup_editable(project_id, role), is_manager=_can_edit(role),
        unlocked=setup_unlocked(project_id),
        editing=_to_int(request.args.get("split")),
    )


@bp.post("/setup/teams")
@login_required
def add_calendar_team(project_id: int):
    """A team, with the days of the week it works."""
    _project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    made = add_calendar(project_id, request.form.get("name") or "",
                        request.form.get("workdays") or "")
    execute("UPDATE calendars SET office = ? WHERE id = ? AND project_id = ?",
            (offices.normalise(request.form.get("office")), made, project_id))
    flash("Team added — set the office it works in, and the trades in that office follow it",
          "success")
    return _back("projects.setup", project_id)


@bp.post("/setup/teams/default")
@login_required
def default_calendar(project_id: int):
    """Which team a deliverable follows when it is not given one of its own."""
    _project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    if set_default_calendar(project_id, _to_int(request.form.get("calendar_id")) or 0):
        flash("Default team set", "success")
    else:
        flash("No such team", "error")
    return _back("projects.setup", project_id)


@bp.post("/setup/holidays")
@login_required
def add_project_holiday(project_id: int):
    """A day off, for one team or for everybody."""
    _project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    trouble = add_holiday(project_id, _to_int(request.form.get("calendar_id")),
                          from_input(request.form.get("holiday_date")) or "",
                          request.form.get("name") or "")
    flash(trouble or "Holiday added", "error" if trouble else "success")
    return _back("projects.setup", project_id)


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

    # The workflow saves on its own, under the same field names the Save-all
    # form uses. It used to read names nothing sent any more, so it reported
    # success and changed nothing — and being part of Save all meant a changed
    # Code A offset could also be lost to a trade split reading 101% two cards
    # down the sheet. A step's dates are worth their own button.
    saved = 0
    for step in load_steps(project_id):
        sid = step["id"]
        if f"step_{sid}_name" not in request.form:
            continue
        execute(
            "UPDATE workflow_steps SET name = ?, percent = ?, anchor = ?, offset_days = ? "
            "WHERE id = ? AND project_id = ?",
            (
                (request.form.get(f"step_{sid}_name") or step["name"]).strip(),
                max(0.0, min(1.0, _to_float(request.form.get(f"step_{sid}_percent"),
                                            step["percent"] * 100) / 100)),
                request.form.get(f"step_{sid}_anchor") or step["anchor"],
                _to_float(request.form.get(f"step_{sid}_offset"), step["offset_days"]),
                sid, project_id,
            ),
        )
        saved += 1

    if not saved:
        flash("Nothing to save on the workflow", "error")
    else:
        flash(f"Workflow saved — {saved} step{'' if saved == 1 else 's'}. "
              "Every planned date on the schedule follows it.", "success")
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
                   revision_reset_step = ?, target_margin_pct = ?, hours_per_week = ?,
                   status = ?, updated_at = datetime('now')
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
                # The margin is held back from the plan, so it cannot be the
                # whole budget or there is nothing left to staff.
                min(95.0, max(0.0, _to_float(request.form.get("target_margin_pct"),
                                             project["target_margin_pct"]))),
                max(1.0, _to_float(request.form.get("hours_per_week"),
                                   project["hours_per_week"])),
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


# --- the Word template the minutes are built from ---------------------------

@bp.get("/setup/minutes-template.docx")
@login_required
def minutes_template(project_id: int):
    """The template to edit: whatever was uploaded, or the built-in layout with
    its placeholders in it, so a first edit starts from what the minutes look
    like today rather than a blank page."""
    from flask import send_file

    from ..minutes_doc import starter_template

    project, _role = load_project(project_id)
    form = load_template(project_id, "minutes")
    data = form["content"] if form else starter_template()
    return send_file(
        io.BytesIO(data), as_attachment=True,
        download_name=f"{project['code']}-minutes-template.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@bp.post("/setup/minutes-template")
@login_required
def upload_minutes_template(project_id: int):
    """Takes the practice's own form and builds every set of minutes from it."""
    from ..service import AttachmentError, save_template
    from ..doctemplate import TemplateError

    _project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    sent = request.files.get("file")
    try:
        kept = save_template(project_id, sent.read() if sent else b"",
                             getattr(sent, "filename", ""), "minutes", g.user)
    except (AttachmentError, TemplateError) as exc:
        flash(str(exc), "error")
        return _back("projects.setup", project_id)

    found = len(kept["fields"])
    flash(f"Template saved — {found} placeholder{'' if found == 1 else 's'} found. "
          "Every set of minutes is built from it from now on."
          if found else
          "Template saved, but it has no {{placeholders}} in it, so every set of minutes "
          "will come out identical. Download the template to see what to put in.",
          "success" if found else "error")
    return _back("projects.setup", project_id)


@bp.post("/setup/minutes-template/remove")
@login_required
def remove_minutes_template(project_id: int):
    from ..service import remove_template

    _project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)
    remove_template(project_id, "minutes")
    flash("Back to the built-in layout", "success")
    return _back("projects.setup", project_id)


# --- what a minuted item can affect -----------------------------------------

@bp.post("/setup/impacts")
@login_required
def save_impact_options(project_id: int):
    """The list behind "Affects" on the minutes: renamed, added or removed."""
    from ..service import add_impact, remove_impact, save_impacts

    _project, role = load_project(project_id, "manager")
    if not _require_setup_edit(project_id, role):
        return _back("projects.setup", project_id)

    action = (request.form.get("action") or "save").strip()
    if action == "add":
        trouble = add_impact(project_id, request.form.get("name") or "",
                             bool(request.form.get("affects_time")),
                             bool(request.form.get("affects_cost")))
        flash(trouble or "Added — it is on the Affects list from now on",
              "error" if trouble else "success")
    elif action.startswith("remove:"):
        trouble = remove_impact(project_id, _to_int(action.split(":", 1)[1]) or 0)
        flash(trouble or "Removed from the Affects list", "error" if trouble else "success")
    else:
        saved = save_impacts(project_id, request.form)
        flash(f"Saved {saved} option{'' if saved == 1 else 's'}", "success")
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
            "INSERT INTO trades (project_id, key, name, budget_hours, color, office, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                project_id, key, name, _to_float(request.form.get("budget_hours")),
                request.form.get("color") or SERIES_SLOTS[(count - 1) % len(SERIES_SLOTS)][1],
                offices.normalise(request.form.get("office")), count,
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
                "UPDATE trades SET name = ?, budget_hours = ?, color = ?, office = ? "
                "WHERE id = ? AND project_id = ?",
                (name, _to_float(request.form.get("budget_hours")), request.form.get("color") or "#2a78d6",
                 offices.normalise(request.form.get("office")), trade_id, project_id),
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
    tidied: list[str] = []
    for task in tasks:
        supplied = {
            trade["id"]: _to_float(form.get(f"task_{task['id']}_alloc_{trade['id']}"))
            for trade in trades
            if f"task_{task['id']}_alloc_{trade['id']}" in form
        }
        if not supplied:
            continue
        total = sum(supplied.values())
        # A line reading 101% is almost always a split held in fractions and
        # shown rounded — refusing the whole sheet for it means a workflow edit
        # three cards up is lost to a rounding artefact somebody cannot see.
        # Anything within a couple of points is tidied to exactly 100 instead.
        if 0.5 < abs(total - 100) <= NEAR_ENOUGH:
            supplied = _to_a_hundred(supplied)
            total = sum(supplied.values())
            tidied.append(str(task["wbs"] or task["name"][:30]))
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
                   revision_reset_step = ?, target_margin_pct = ?, hours_per_week = ?,
                   status = ?, updated_at = datetime('now')
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
                min(95.0, max(0.0, _to_float(form.get("target_margin_pct"),
                                             project["target_margin_pct"]))),
                max(1.0, _to_float(form.get("hours_per_week"), project["hours_per_week"])),
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

        for team in load_calendars(project_id):
            field = f"calendar_{team['id']}_name"
            if field not in form:
                continue
            conn.execute(
                "UPDATE calendars SET name = ?, workdays = ? WHERE id = ? AND project_id = ?",
                (
                    (form.get(field) or team["name"]).strip()[:60],
                    parse_days(form.getlist(f"calendar_{team['id']}_days")),
                    team["id"], project_id,
                ),
            )
            conn.execute("UPDATE calendars SET office = ? WHERE id = ? AND project_id = ?",
                         (offices.normalise(form.get(f"calendar_{team['id']}_office")),
                          team["id"], project_id))
            changed["teams"] = changed.get("teams", 0) + 1

        for trade in trades:
            field = f"trade_{trade['id']}_name"
            if field not in form:
                continue
            conn.execute(
                "UPDATE trades SET name = ?, budget_hours = ?, color = ?, office = ? "
                "WHERE id = ? AND project_id = ?",
                (
                    (form.get(field) or trade["name"]).strip(),
                    _to_float(form.get(f"trade_{trade['id']}_budget"), trade["budget_hours"]),
                    form.get(f"trade_{trade['id']}_color") or trade["color"],
                    offices.normalise(form.get(f"trade_{trade['id']}_office")),
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
        (f"{len(tidied)} trade split{'' if len(tidied) == 1 else 's'} rounded to 100% "
         f"({', '.join(tidied[:6])}). " if tidied else "") +
        f"Saved — project settings, {changed['trades']} trades, "
        f"{changed.get('teams', 0)} teams, {changed['sections']} sections and "
        f"{changed['tasks']} deliverables",
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

    # A team and a holiday are not plain rows: removing a team hands its
    # deliverables back to the default, and the last one is never removed.
    if kind == "calendar" and item_id is not None:
        trouble = delete_calendar(project_id, item_id)
        flash(trouble or "Team removed — its deliverables now follow the default team",
              "error" if trouble else "success")
        return _back("projects.setup", project_id)
    if kind == "holiday" and item_id is not None:
        gone = remove_holiday(project_id, item_id)
        flash("Holiday removed" if gone else "No such holiday", "success" if gone else "error")
        return _back("projects.setup", project_id)

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
    return handed_out(project_id, data, f"{project['code']}-setup-{stamp}.xlsx",
                      EXCEL, "setup", "The setup sheet")


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

    summary = apply_setup_workbook(project, parsed)
    flash(
        f"Imported {summary['tasks']} deliverables, {summary['trades']} trades, "
        f"{summary['sections']} sections and {summary['steps']} workflow steps",
        "success",
    )
    return _back("projects.setup", project_id)


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
