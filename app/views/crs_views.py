"""The comment response sheets, as pages.

One address, ``/crs``, and everything under it is a project's sheets. The pages
are the same shape as the rest of project control — server-rendered, editable
by clicking a cell, and working with JavaScript switched off — because they are
part of the same application now rather than a second one that happens to share
a domain.

The sheet page is the one that matters: the client's comments down the page,
our answer beside each, and the code and sign-off as cells you type into. What
is typed is saved as it is typed, so nobody loses forty answers to a closed
laptop.
"""

from __future__ import annotations

from flask import (
    Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for,
)

from .. import crs_store as store
from ..auth import ROLE_RANK, load_project, login_required, require_edit, visible_project_ids
from ..crs_excel import MIMETYPE
from ..crs_sheet import CODES, SIGNOFFS, is_late, overdue_days, tally, by_trade, worst_code
from ..dates import from_input, from_input_or, to_display
from ..db import query, query_one
from ..service import WorkflowError, load_steps, record_comments, today

bp = Blueprint("crs", __name__, url_prefix="/crs")

# How big a file anyone can put on a comment. A marked-up drawing is a few
# megabytes; a video of a site walk is not something to keep in a database.
MOST = 12 * 1024 * 1024


def _projects():
    """The projects this person may see, newest first."""
    ids = visible_project_ids(g.user)
    if not ids:
        return []
    marks = ", ".join("?" * len(ids))
    return query(f"SELECT id, code, name FROM projects WHERE id IN ({marks}) "
                 f"ORDER BY name", ids)


def _wants_json() -> bool:
    return "application/json" in (request.headers.get("Accept") or "")


def _sheet_or_404(project_id: int, sheet_id: int) -> dict:
    row = store.sheet(sheet_id, project_id)
    if row is None:
        abort(404)
    return row


def _deliverable(sheet: dict) -> dict | None:
    """The line on the programme this sheet's comments land on.

    Either the sheet says which one, or the document it is against does. A
    sheet against nothing in the register lands on nothing, and says so rather
    than guessing at a deliverable.
    """
    task_id = sheet.get("task_id")
    if not task_id and sheet.get("submittal_id"):
        row = query_one("SELECT task_id FROM submittals WHERE id = ?",
                        (sheet["submittal_id"],))
        task_id = row["task_id"] if row else None
    if not task_id:
        return None
    row = query_one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
    return dict(row) if row else None


def _comment_or_404(project_id: int, comment_id: int) -> dict:
    row = query_one(
        "SELECT c.*, s.project_id AS project FROM crs_comments c "
        "JOIN crs_sheets s ON s.id = c.sheet_id WHERE c.id = ?", (int(comment_id),))
    if row is None or int(row["project"]) != int(project_id):
        abort(404)
    return dict(row)


# --- the list ---------------------------------------------------------------

@bp.get("/")
@login_required
def index():
    """Whichever project was asked for, or the first one there is."""
    projects = _projects()
    if not projects:
        return render_template("crs/index.html", projects=[], project=None,
                               sheets=[], counted=tally([]))

    asked = request.args.get("project", type=int)
    chosen = next((p for p in projects if p["id"] == asked), projects[0])
    project, role = load_project(int(chosen["id"]))

    return render_template(
        "crs/index.html", projects=projects, project=project, role=role,
        sheets=store.sheets_for(project["id"]), counted=store.overview(project["id"]),
        late=store.late_everywhere(project["id"]),
        submittals=store.submittals_of(project["id"]),
        codes=CODES,
    )


@bp.post("/<int:project_id>/sheets")
@login_required
def new_sheet(project_id: int):
    """A sheet raised here, or one uploaded on the client's own form."""
    _project, role = load_project(project_id, "member")
    if not require_edit(role):
        return redirect(url_for("crs.index", project=project_id))

    upload = request.files.get("workbook")
    submittal_id = request.form.get("submittal_id", type=int)
    if upload and upload.filename:
        data = upload.read(MOST + 1)
        if len(data) > MOST:
            flash("That file is too big to keep here — 12 MB is the limit.", "error")
            return redirect(url_for("crs.index", project=project_id))
        try:
            sheet_id = store.import_workbook(project_id, data, submittal_id=submittal_id)
        except store.CrsError as exc:
            flash(str(exc), "error")
            return redirect(url_for("crs.index", project=project_id))
        flash("Read the form and its comments.", "success")
    else:
        sheet_id = store.create_sheet(
            project_id, title=request.form.get("title", ""),
            submittal_id=submittal_id,
            drf_ref=request.form.get("drf_ref", ""),
            received_on=request.form.get("received_on", ""))

    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))


# --- one sheet --------------------------------------------------------------

@bp.get("/<int:project_id>/sheets/<int:sheet_id>")
@login_required
def sheet(project_id: int, sheet_id: int):
    project, role = load_project(project_id)
    row = _sheet_or_404(project_id, sheet_id)
    comments = store.comments_for(sheet_id)
    trades = store.trades_of(project_id)

    for comment in comments:
        comment["late"] = is_late(comment)
        comment["overdue"] = overdue_days(comment)

    return render_template(
        "crs/sheet.html", project=project, role=role, sheet=row, comments=comments,
        trades=trades, threads=store.threads_for(sheet_id), files=store.files_for(sheet_id),
        counted=tally(comments), owed=by_trade(comments, trades),
        code=worst_code(comments), codes=CODES, signoffs=SIGNOFFS,
        submittals=store.submittals_of(project_id),
        can_edit=ROLE_RANK[role] >= ROLE_RANK["manager"],
        original=store.original(sheet_id) is not None,
        rework=store.sheet_is_rework(sheet_id), deliverable=_deliverable(row),
    )


@bp.post("/<int:project_id>/sheets/<int:sheet_id>")
@login_required
def save_sheet(project_id: int, sheet_id: int):
    _project, role = load_project(project_id, "member")
    _sheet_or_404(project_id, sheet_id)
    if require_edit(role):
        store.update_sheet(sheet_id, **request.form.to_dict())
        flash("Saved.", "success")
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))


@bp.post("/<int:project_id>/sheets/<int:sheet_id>/upload")
@login_required
def upload_onto(project_id: int, sheet_id: int):
    """A newer copy of the same register, onto the sheet that already exists."""
    _project, role = load_project(project_id, "member")
    _sheet_or_404(project_id, sheet_id)
    if not require_edit(role):
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))

    upload = request.files.get("workbook")
    data = upload.read(MOST + 1) if upload and upload.filename else b""
    if not data:
        flash("No file came through.", "error")
    elif len(data) > MOST:
        flash("That file is too big to keep here — 12 MB is the limit.", "error")
    else:
        try:
            store.import_workbook(project_id, data, sheet_id=sheet_id)
            flash("Read the form. Answers already written here were kept.", "success")
        except store.CrsError as exc:
            flash(str(exc), "error")
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))


@bp.get("/<int:project_id>/sheets/<int:sheet_id>.xlsx")
@login_required
def download(project_id: int, sheet_id: int):
    """The sheet, on the client's own form."""
    load_project(project_id)
    _sheet_or_404(project_id, sheet_id)
    try:
        data, name = store.export_workbook(sheet_id)
    except store.CrsError as exc:
        flash(str(exc), "error")
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))
    return Response(data, mimetype=MIMETYPE, headers={
        "Content-Disposition": f'attachment; filename="{name}"',
        "Content-Length": str(len(data)),
    })


@bp.post("/<int:project_id>/sheets/<int:sheet_id>/delete")
@login_required
def delete_sheet(project_id: int, sheet_id: int):
    _project, role = load_project(project_id, "member")
    _sheet_or_404(project_id, sheet_id)
    if require_edit(role):
        store.delete_sheet(sheet_id)
        flash("The sheet and its comments are gone.", "success")
    return redirect(url_for("crs.index", project=project_id))


@bp.post("/<int:project_id>/sheets/<int:sheet_id>/close-answered")
@login_required
def close_answered(project_id: int, sheet_id: int):
    _project, role = load_project(project_id, "member")
    _sheet_or_404(project_id, sheet_id)
    if require_edit(role):
        many = store.close_what_is_answered(sheet_id)
        flash(f"Signed off {many} comment{'' if many == 1 else 's'}.", "success")
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))


# --- comments ---------------------------------------------------------------

@bp.post("/<int:project_id>/sheets/<int:sheet_id>/comments")
@login_required
def add_comment(project_id: int, sheet_id: int):
    _project, role = load_project(project_id, "member")
    _sheet_or_404(project_id, sheet_id)
    if require_edit(role):
        try:
            store.add_comment(sheet_id, **request.form.to_dict())
        except store.CrsError as exc:
            flash(str(exc), "error")
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))


@bp.post("/<int:project_id>/comments/<int:comment_id>")
@login_required
def save_comment(project_id: int, comment_id: int):
    """One cell, saved as it is typed."""
    _project, role = load_project(project_id, "member")
    row = _comment_or_404(project_id, comment_id)
    if ROLE_RANK[role] < ROLE_RANK["manager"]:
        if _wants_json():
            return {"ok": False, "error": "You cannot change this project."}, 403
        flash("You do not have permission to change this project.", "error")
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=row["sheet_id"]))

    try:
        saved = store.set_comment(comment_id, **request.form.to_dict())
    except store.CrsError as exc:
        if _wants_json():
            return {"ok": False, "error": str(exc)}, 400
        flash(str(exc), "error")
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=row["sheet_id"]))

    if _wants_json():
        comments = store.comments_for(row["sheet_id"])
        counted = tally(comments)
        trade = query_one("SELECT name FROM trades WHERE id = ?",
                          (saved["trade_id"],)) if saved["trade_id"] else None
        return {
            "ok": True,
            "comment": {
                "id": saved["id"],
                "response": saved["response"],
                "returned_code": saved["returned_code"],
                "code_said": CODES.get(saved["returned_code"], ""),
                "signoff": saved["signoff"],
                "closed": saved["signoff"] == "closed",
                "due_date": saved["due_date"],
                "closed_on": saved["closed_on"],
                "trade_id": saved["trade_id"],
                "trade_name": trade["name"] if trade else "",
                "late": is_late(saved),
                "overdue": overdue_days(saved),
            },
            "sheet": {
                "comments": counted["comments"], "closed": counted["closed"],
                "open": counted["open"], "late": counted["late"],
                "answered": counted["answered"], "done_pct": round(counted["done_pct"], 1),
                "code": worst_code(comments),
                "code_said": CODES.get(worst_code(comments), ""),
            },
        }
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=row["sheet_id"]))


@bp.post("/<int:project_id>/comments/<int:comment_id>/delete")
@login_required
def delete_comment(project_id: int, comment_id: int):
    _project, role = load_project(project_id, "member")
    row = _comment_or_404(project_id, comment_id)
    if require_edit(role):
        store.delete_comment(comment_id)
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=row["sheet_id"]))


@bp.post("/<int:project_id>/comments/<int:comment_id>/messages")
@login_required
def add_message(project_id: int, comment_id: int):
    """A word about a comment, kept against it.

    Anybody who can see the project may say something; answering the client is
    the response column, and that is a manager's to write.
    """
    _project, _role = load_project(project_id)
    row = _comment_or_404(project_id, comment_id)
    try:
        store.add_message(comment_id, request.form.get("body", ""), user=g.user)
    except store.CrsError as exc:
        flash(str(exc), "error")
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=row["sheet_id"],
                            _anchor=f"c{comment_id}"))


@bp.post("/<int:project_id>/comments/<int:comment_id>/files")
@login_required
def attach_file(project_id: int, comment_id: int):
    """A photo or a marked-up sheet, against the comment it is about."""
    _project, role = load_project(project_id, "member")
    row = _comment_or_404(project_id, comment_id)
    if require_edit(role):
        upload = request.files.get("file")
        data = upload.read(MOST + 1) if upload and upload.filename else b""
        if not data:
            flash("No file came through.", "error")
        elif len(data) > MOST:
            flash("That file is too big to keep here — 12 MB is the limit.", "error")
        else:
            store.attach(name=upload.filename, mimetype=upload.mimetype or "",
                         content=data, comment_id=comment_id,
                         user_name=dict(g.user)["name"] if g.user else "")
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=row["sheet_id"],
                            _anchor=f"c{comment_id}"))


@bp.get("/<int:project_id>/files/<int:file_id>")
@login_required
def read_file(project_id: int, file_id: int):
    load_project(project_id)
    held = store.file(file_id)
    if held is None:
        abort(404)
    # The file has to belong to this project, whichever of the three things it
    # hangs off — a sheet, a comment, or a message on one.
    owner = query_one(
        """
        SELECT s.project_id AS project FROM crs_files f
        LEFT JOIN crs_comments c ON c.id = f.comment_id
        LEFT JOIN crs_messages m ON m.id = f.message_id
        LEFT JOIN crs_comments mc ON mc.id = m.comment_id
        JOIN crs_sheets s ON s.id = IFNULL(f.sheet_id, IFNULL(c.sheet_id, mc.sheet_id))
        WHERE f.id = ?
        """, (int(file_id),))
    if owner is None or int(owner["project"]) != int(project_id):
        abort(404)

    return Response(bytes(held["content"]),
                    mimetype=held["mimetype"] or "application/octet-stream",
                    headers={"Content-Disposition":
                             f'inline; filename="{held["name"]}"'})


# --- what the programme feels ------------------------------------------------

@bp.post("/<int:project_id>/sheets/<int:sheet_id>/rework")
@login_required
def record_rework(project_id: int, sheet_id: int):
    """A Code C or D is the programme's business, not just the sheet's.

    The submission goes round again: the deliverable takes another revision,
    drops back to the step the project nominates and is rescheduled around a new
    submission date. That is the same thing the Progress tab does when somebody
    records comments there — done from here so that reading the sheet and
    moving the programme are one action rather than two, and so the note on the
    revision says which sheet it came from.
    """
    project, role = load_project(project_id, "member")
    sheet = _sheet_or_404(project_id, sheet_id)
    if not require_edit(role):
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))

    task = _deliverable(sheet)
    if task is None:
        flash("This sheet is not against a deliverable, so there is nothing to move. "
              "Point it at a document in the register first.", "error")
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))

    said = store.sheet_is_rework(sheet_id)
    if not said["code"]:
        flash("No returned code on this sheet yet — nothing says the submission "
              "comes back.", "error")
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))

    name = sheet["drf_ref"] or sheet["report_no"] or sheet["title"] or f"sheet {sheet_id}"
    try:
        made = record_comments(
            task, project, load_steps(project_id),
            from_input_or(request.form.get("comments_date"),
                          sheet["received_on"] or today()),
            from_input(request.form.get("new_submission_date")) or "",
            (request.form.get("note") or
             f"{said['comments']} comments on {name}").strip(),
            dict(g.user)["id"], code=said["code"])
    except WorkflowError as exc:
        flash(str(exc), "error")
        return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))

    store.update_sheet(sheet_id, task_id=task["id"])
    flash(f"{task['wbs'] or task['name'][:40]} — Code {made['code']}, moved to revision "
          f"{made['revision']}, back to \u201c{made['reset_to']}\u201d and resubmitting "
          f"{to_display(made['submission_date'])}.", "success")
    return redirect(url_for("crs.sheet", project_id=project_id, sheet_id=sheet_id))
