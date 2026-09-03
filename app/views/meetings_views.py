"""Minutes of meeting: the register, one meeting's minutes, and the agenda."""

from __future__ import annotations

import io

from flask import (
    Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file,
    url_for,
)

from ..auth import ROLE_RANK, load_project, login_required
from ..dates import from_input, from_input_or, to_display
from ..db import execute, insert, query_one
from ..minutes import (
    COLUMNS, DEFAULT_FILTER, FILTERS, IMPACTS, OWNERS, STATUSES, filter_items, next_ref,
    normalise_impact, normalise_owner, normalise_sort, normalise_status, sort_items, summarise,
)
from ..service import (
    load_attendees, load_items, load_meeting, load_meetings, load_trades, meeting_items,
    meeting_sheet, move_item, next_sort_order, renumber_items, set_attendance,
    set_item_trades, today,
)

bp = Blueprint("meetings", __name__, url_prefix="/projects/<int:project_id>")


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _can_edit(role: str) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK["manager"]


def _can_report(role: str) -> bool:
    """Minutes are working records, so anyone who can report progress may keep them."""
    return ROLE_RANK[role] >= ROLE_RANK["member"]


def _clean(name: str) -> str:
    return (request.form.get(name) or "").strip()


def _filters() -> dict[str, object]:
    """Everything narrowing the register, read from the query string.

    The same dictionary is used to run the filter, to render the controls, and
    to rebuild the link after a form is submitted, so the view never drifts
    from what was asked for.
    """
    chip = (request.args.get("filter") or DEFAULT_FILTER).strip().lower()
    sort, direction = normalise_sort(request.args.get("sort"), request.args.get("dir"))
    return {
        "filter": chip,
        "q": (request.args.get("q") or "").strip(),
        "owner": normalise_owner(request.args.get("owner")),
        "trade": _to_int(request.args.get("trade")),
        "meeting": _to_int(request.args.get("meeting")),
        "impact": (request.args.get("impact") or "").strip().lower(),
        "from": from_input(request.args.get("from")) or "",
        "to": from_input(request.args.get("to")) or "",
        "sort": sort,
        "dir": direction,
    }


def _link_args(filters: dict[str, object]) -> dict[str, object]:
    """The query values worth putting back in a URL — blanks are dropped."""
    args = {
        "filter": filters["filter"],
        "q": filters["q"] or None,
        "owner": filters["owner"] or None,
        "trade": filters["trade"],
        "meeting": filters["meeting"],
        "impact": filters["impact"] or None,
        "from": to_display(filters["from"]) or None,
        "to": to_display(filters["to"]) or None,
        "sort": filters["sort"],
        "dir": filters["dir"],
    }
    return {k: v for k, v in args.items() if v is not None}


def _selection(project_id: int, filters: dict[str, object]) -> list[dict]:
    """The items the filters ask for, in the requested order."""
    items = load_items(project_id, today())
    kept = filter_items(
        items,
        chip=str(filters["filter"]),
        search=str(filters["q"]),
        owner=str(filters["owner"]),
        trade_id=filters["trade"],
        meeting_id=filters["meeting"],
        impact=str(filters["impact"]),
        date_from=str(filters["from"]),
        date_to=str(filters["to"]),
    )
    return sort_items(kept, str(filters["sort"]), str(filters["dir"]))


def _back(project_id: int, **extra):
    """Back to the register, keeping whatever filter the user was looking at."""
    args = _link_args(_filters())
    args.update(extra)
    return redirect(url_for("meetings.index", project_id=project_id, **args))


def _download(data: bytes, filename: str):
    return send_file(
        io.BytesIO(data),
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        as_attachment=True,
        download_name=filename,
    )


def _stamp() -> str:
    return today().replace("-", "")


# --- the register ----------------------------------------------------------

@bp.get("/minutes")
@login_required
def index(project_id: int):
    project, role = load_project(project_id)
    filters = _filters()
    everything = load_items(project_id, today())
    rows = _selection(project_id, filters)

    return render_template(
        "minutes.html",
        project=project, role=role, items=rows, totals=summarise(everything),
        shown=len(rows), filters=filters, link_args=_link_args(filters),
        chips=FILTERS, impacts=IMPACTS, owners=OWNERS, statuses=STATUSES, columns=COLUMNS,
        sort=filters["sort"], direction=filters["dir"],
        attendees=load_attendees(project_id), trades=load_trades(project_id),
        meetings=load_meetings(project_id), today=today(),
        can_report=_can_report(role), can_edit=_can_edit(role),
    )


@bp.get("/minutes/register.docx")
@login_required
def register_word(project_id: int):
    """The register exactly as filtered on screen, as a Word document."""
    from ..minutes_doc import register_document

    project, _role = load_project(project_id)
    filters = _filters()
    rows = _selection(project_id, filters)
    note = "Filtered: " + ", ".join(_describe(project_id, filters)) if _describe(project_id, filters) else ""
    data = register_document(project, rows, "Action register", note)
    return _download(data, f"{project['code']}-actions-{_stamp()}.docx")


def _describe(project_id: int, filters: dict[str, object]) -> list[str]:
    """The filters in words, so a printed register says what it is showing."""
    parts: list[str] = []
    labels = dict(FILTERS)
    if filters["filter"] != "all":
        parts.append(labels.get(str(filters["filter"]), str(filters["filter"])))
    if filters["q"]:
        parts.append(f'matching "{filters["q"]}"')
    if filters["owner"]:
        parts.append(f"owned by {filters['owner']}")
    if filters["trade"]:
        row = query_one("SELECT name FROM trades WHERE id = ? AND project_id = ?",
                        (filters["trade"], project_id))
        if row:
            parts.append(f"trade {row['name']}")
    if filters["meeting"]:
        row = query_one("SELECT ref, title FROM meetings WHERE id = ? AND project_id = ?",
                        (filters["meeting"], project_id))
        if row:
            parts.append(f"meeting {row['ref'] or row['title'] or filters['meeting']}")
    if filters["impact"]:
        parts.append(f"affecting {dict(IMPACTS).get(str(filters['impact']), filters['impact']).lower()}")
    if filters["from"]:
        parts.append(f"raised from {to_display(filters['from'])}")
    if filters["to"]:
        parts.append(f"raised to {to_display(filters['to'])}")
    return parts


# --- the agenda for the next meeting ---------------------------------------

@bp.get("/minutes/agenda")
@login_required
def agenda(project_id: int):
    """Everything still open, grouped by owner — the sheet you walk into the
    next meeting with."""
    project, role = load_project(project_id)
    search = (request.args.get("q") or "").strip()
    trade_id = _to_int(request.args.get("trade"))
    owner = normalise_owner(request.args.get("owner"))

    items = filter_items(load_items(project_id, today()), chip="open", search=search,
                         trade_id=trade_id, owner=owner)
    items = sort_items(items, "due", "asc")

    by_owner: dict[str, list[dict]] = {}
    for item in items:
        by_owner.setdefault(item["owner_label"] or "Unassigned", []).append(item)
    groups = [{"name": name, "items": rows} for name, rows in by_owner.items()]
    groups.sort(key=lambda grp: (grp["name"] == "Unassigned", grp["name"].lower()))

    meetings = load_meetings(project_id)
    return render_template(
        "agenda.html",
        project=project, role=role, items=items, groups=groups, totals=summarise(items),
        search=search, trade_id=trade_id, owner=owner, owners=OWNERS,
        trades=load_trades(project_id), attendees=load_attendees(project_id),
        last_meeting=meetings[0] if meetings else None, today=today(),
    )


@bp.get("/minutes/agenda.docx")
@login_required
def agenda_word(project_id: int):
    from ..minutes_doc import register_document

    project, _role = load_project(project_id)
    items = sort_items(filter_items(load_items(project_id, today()), chip="open"), "due", "asc")
    data = register_document(
        project, items, "Agenda — open items",
        f"Every item still open as at {to_display(today())}.",
    )
    return _download(data, f"{project['code']}-agenda-{_stamp()}.docx")


# --- one meeting -----------------------------------------------------------

@bp.get("/minutes/meetings/<int:meeting_id>")
@login_required
def meeting(project_id: int, meeting_id: int):
    project, role = load_project(project_id)
    sheet = meeting_sheet(project_id, meeting_id, today())
    if sheet is None:
        abort(404)

    editing = _to_int(request.args.get("edit"))
    order = [row["id"] for row in meeting_items(project_id, meeting_id)]
    return render_template(
        "meeting.html",
        first_id=order[0] if order else None, last_id=order[-1] if order else None,
        project=project, role=role, sheet=sheet, meeting=sheet["meeting"],
        items=sheet["items"], attendance=sheet["attendance"],
        impacts=IMPACTS, owners=OWNERS, statuses=STATUSES, editing=editing,
        attendees=load_attendees(project_id), trades=load_trades(project_id),
        suggested_ref=next_ref(sheet["items"], sheet["meeting"]["ref"]),
        today=today(), can_report=_can_report(role), can_edit=_can_edit(role),
    )


@bp.get("/minutes/meetings/<int:meeting_id>.docx")
@login_required
def meeting_word(project_id: int, meeting_id: int):
    from ..minutes_doc import minutes_document

    project, _role = load_project(project_id)
    sheet = meeting_sheet(project_id, meeting_id, today())
    if sheet is None:
        abort(404)

    stamp = (sheet["meeting"]["meeting_date"] or today()).replace("-", "")
    name = (sheet["meeting"]["ref"] or "minutes").replace("/", "-").replace(" ", "-")
    return _download(minutes_document(project, sheet), f"{project['code']}-{name}-{stamp}.docx")


@bp.post("/minutes/meetings")
@login_required
def add_meeting(project_id: int):
    _project, role = load_project(project_id, "member")
    meeting_date = from_input(request.form.get("meeting_date"))
    if not meeting_date:
        flash("A meeting needs a date", "error")
        return _back(project_id)

    meeting_id = insert(
        """
        INSERT INTO meetings (project_id, ref, title, meeting_date, meeting_time, location,
                              chaired_by, next_date, notes, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, _clean("ref"), _clean("title"), meeting_date, _clean("meeting_time"),
         _clean("location"), _clean("chaired_by"), from_input(request.form.get("next_date")) or "",
         _clean("notes"), g.user["id"]),
    )

    # Everyone still on the roster is invited by default; who actually turned up
    # is ticked on the meeting itself.
    roster = [int(a["id"]) for a in load_attendees(project_id, include_inactive=False)]
    if roster:
        set_attendance(meeting_id, roster, roster)

    flash("Meeting added — tick who attended and add the items", "success")
    return redirect(url_for("meetings.meeting", project_id=project_id, meeting_id=meeting_id))


@bp.post("/minutes/meetings/<int:meeting_id>")
@login_required
def save_meeting(project_id: int, meeting_id: int):
    """The meeting's details and its attendance ticks, saved together."""
    _project, role = load_project(project_id, "member")
    if load_meeting(project_id, meeting_id) is None:
        abort(404)

    execute(
        """
        UPDATE meetings SET ref = ?, title = ?, meeting_date = ?, meeting_time = ?,
               location = ?, chaired_by = ?, next_date = ?, notes = ?
        WHERE id = ? AND project_id = ?
        """,
        (_clean("ref"), _clean("title"),
         from_input_or(request.form.get("meeting_date"), today()), _clean("meeting_time"),
         _clean("location"), _clean("chaired_by"),
         from_input(request.form.get("next_date")) or "", _clean("notes"),
         meeting_id, project_id),
    )

    # The meeting's reference is the stem of its item numbers (MOM-04 -> 4.1),
    # so renumber when it changes.
    renumber_items(project_id, meeting_id)

    roster = {int(a["id"]) for a in load_attendees(project_id)}
    invited = [i for i in (_to_int(v) for v in request.form.getlist("invited")) if i in roster]
    present = [i for i in (_to_int(v) for v in request.form.getlist("present")) if i in roster]
    set_attendance(meeting_id, present, invited)

    flash("Meeting saved", "success")
    return redirect(url_for("meetings.meeting", project_id=project_id, meeting_id=meeting_id))


@bp.post("/minutes/meetings/<int:meeting_id>/delete")
@login_required
def delete_meeting(project_id: int, meeting_id: int):
    _project, role = load_project(project_id, "manager")
    if load_meeting(project_id, meeting_id) is None:
        abort(404)
    # Items outlive the meeting they were raised in, so the action register
    # keeps its history even when a set of minutes is removed.
    execute("UPDATE meeting_items SET meeting_id = NULL WHERE meeting_id = ?", (meeting_id,))
    execute("DELETE FROM meetings WHERE id = ? AND project_id = ?", (meeting_id, project_id))
    renumber_items(project_id, None)
    flash("Meeting deleted — its items stay in the register", "success")
    return _back(project_id)


# --- items -----------------------------------------------------------------

def _item_fields(project_id: int) -> dict[str, object]:
    """The item columns this form actually carries, validated.

    Only what was posted comes back, so one field can be saved on its own from
    its own cell without blanking everything the form did not include.
    """
    form = request.form
    fields: dict[str, object] = {}

    if "meeting_id" in form:
        meeting_id = _to_int(form.get("meeting_id"))
        if meeting_id and not query_one("SELECT 1 FROM meetings WHERE id = ? AND project_id = ?",
                                        (meeting_id, project_id)):
            meeting_id = None
        fields["meeting_id"] = meeting_id

    for name in ("subject", "discussion", "agreement"):
        if name in form:
            fields[name] = _clean(name)
    if "owner_code" in form:
        fields["owner_code"] = normalise_owner(form.get("owner_code"))
    if "impact" in form:
        fields["impact"] = normalise_impact(form.get("impact"))
    if "raised_date" in form:
        fields["raised_date"] = from_input(form.get("raised_date")) or ""
    if "due_date" in form:
        fields["due_date"] = from_input(form.get("due_date")) or ""

    # Closing an item stamps the date unless one was given; reopening clears it.
    if "status" in form:
        status = normalise_status(form.get("status"))
        fields["status"] = status
        closed = from_input(form.get("closed_date")) or ""
        fields["closed_date"] = (closed or today()) if status == "closed" else ""
    elif "closed_date" in form:
        fields["closed_date"] = from_input(form.get("closed_date")) or ""

    return fields


def _wants_json() -> bool:
    """A cell saving on its own asks for JSON so the page need not reload."""
    return "application/json" in (request.headers.get("Accept") or "")


def _saved(project_id: int, item_id: int, meeting_id: object):
    """The answer to a save: a fresh status badge for the row, or a redirect."""
    if not _wants_json():
        return _after_item(project_id, meeting_id)

    from flask import jsonify

    item = next((i for i in load_items(project_id, today()) if i["id"] == item_id), None)
    if item is None:
        return jsonify({"ok": False}), 404

    # The very macros the page uses, so what is swapped in is what a reload
    # would have drawn.
    bits = current_app.jinja_env.get_template("partials/item_bits.html").module
    return jsonify({
        "ok": True,
        "status_html": str(bits.item_status(item)),
        "trade_html": str(bits.item_trades(item)),
    })


def _after_item(project_id: int, meeting_id: object):
    """Back to wherever the item was added from."""
    if (request.form.get("return") or "") == "meeting" and meeting_id:
        return redirect(url_for("meetings.meeting", project_id=project_id, meeting_id=meeting_id))
    return _back(project_id)


@bp.post("/minutes/items")
@login_required
def add_item(project_id: int):
    _project, role = load_project(project_id, "member")
    fields = _item_fields(project_id)
    if not fields.get("subject") and not fields.get("agreement"):
        flash("An item needs a subject or an agreement", "error")
        return _after_item(project_id, fields.get("meeting_id"))

    if not fields.get("raised_date"):
        stamp = None
        if fields.get("meeting_id"):
            stamp = query_one("SELECT meeting_date FROM meetings WHERE id = ?", (fields["meeting_id"],))
        fields["raised_date"] = stamp["meeting_date"] if stamp else today()

    # The number is set by renumbering once the item is in its meeting.
    columns = dict(fields, project_id=project_id, ref="",
                   sort_order=next_sort_order("meeting_items", project_id))
    names = ", ".join(columns)
    item_id = insert(
        f"INSERT INTO meeting_items ({names}) VALUES ({', '.join('?' for _ in columns)})",
        tuple(columns.values()),
    )
    if "trade_ids" in request.form or "trades_present" in request.form:
        set_item_trades(project_id, item_id, request.form.getlist("trade_ids"))
    renumber_items(project_id, fields.get("meeting_id"))
    flash("Item added", "success")
    return _after_item(project_id, fields.get("meeting_id"))


@bp.post("/minutes/items/<int:item_id>")
@login_required
def save_item(project_id: int, item_id: int):
    """Saves whatever the form carried — a whole item, or one cell of one."""
    _project, role = load_project(project_id, "member")
    before = query_one("SELECT meeting_id FROM meeting_items WHERE id = ? AND project_id = ?",
                       (item_id, project_id))
    if before is None:
        abort(404)

    fields = _item_fields(project_id)
    if fields:
        assignments = ", ".join(f"{name} = ?" for name in fields)
        execute(
            f"UPDATE meeting_items SET {assignments}, updated_at = datetime('now') "
            "WHERE id = ? AND project_id = ?",
            (*fields.values(), item_id, project_id),
        )
    if "trade_ids" in request.form or "trades_present" in request.form:
        set_item_trades(project_id, item_id, request.form.getlist("trade_ids"))

    # Moving an item to another meeting renumbers both: the one it left closes
    # its gap, the one it joined takes it on the end.
    meeting_id = fields.get("meeting_id", before["meeting_id"])
    if "meeting_id" in fields and before["meeting_id"] != meeting_id:
        renumber_items(project_id, before["meeting_id"])
        renumber_items(project_id, meeting_id)

    if not _wants_json():
        flash("Item saved", "success")
    return _saved(project_id, item_id, meeting_id)


@bp.post("/minutes/items/<int:item_id>/status")
@login_required
def set_item_status(project_id: int, item_id: int):
    """Close or reopen an item without opening the whole edit form."""
    _project, role = load_project(project_id, "member")
    item = query_one("SELECT * FROM meeting_items WHERE id = ? AND project_id = ?", (item_id, project_id))
    if item is None:
        abort(404)

    status = normalise_status(request.form.get("status"))
    closed = today() if status == "closed" else ""
    execute(
        "UPDATE meeting_items SET status = ?, closed_date = ?, updated_at = datetime('now') WHERE id = ?",
        (status, closed, item_id),
    )
    if not _wants_json():
        flash("Item closed" if status == "closed" else "Item reopened", "success")
    return _saved(project_id, item_id, item["meeting_id"])


@bp.post("/minutes/items/<int:item_id>/move")
@login_required
def move(project_id: int, item_id: int):
    """Swaps an item with its neighbour and renumbers the meeting."""
    _project, role = load_project(project_id, "member")
    item = query_one("SELECT * FROM meeting_items WHERE id = ? AND project_id = ?", (item_id, project_id))
    if item is None:
        abort(404)

    direction = "up" if (request.form.get("direction") or "").strip().lower() == "up" else "down"
    if not move_item(project_id, item_id, direction):
        flash(f"That item is already {'first' if direction == 'up' else 'last'}", "error")
    return _after_item(project_id, item["meeting_id"])


@bp.post("/minutes/items/<int:item_id>/delete")
@login_required
def delete_item(project_id: int, item_id: int):
    _project, role = load_project(project_id, "member")
    item = query_one("SELECT * FROM meeting_items WHERE id = ? AND project_id = ?", (item_id, project_id))
    if item is None:
        abort(404)
    execute("DELETE FROM meeting_items WHERE id = ?", (item_id,))
    renumber_items(project_id, item["meeting_id"])
    flash("Item deleted", "success")
    return _after_item(project_id, item["meeting_id"])


# --- the attendance roster -------------------------------------------------

@bp.post("/minutes/attendees")
@login_required
def add_attendee(project_id: int):
    _project, role = load_project(project_id, "member")
    name = _clean("name")
    if not name:
        flash("An attendee needs a name", "error")
        return _back(project_id)

    trade_id = _to_int(request.form.get("trade_id"))
    if trade_id and not query_one("SELECT 1 FROM trades WHERE id = ? AND project_id = ?",
                                  (trade_id, project_id)):
        trade_id = None

    insert(
        """
        INSERT INTO attendees (project_id, name, organisation, job_title, email, trade_id, sort_order)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, name, _clean("organisation"), _clean("job_title"), _clean("email"),
         trade_id, next_sort_order("attendees", project_id)),
    )
    flash(f"{name} added to the attendance list", "success")
    return _back(project_id, **({"meeting": _to_int(request.form.get("meeting_id"))}
                                if request.form.get("meeting_id") else {}))


@bp.post("/minutes/attendees/<int:attendee_id>")
@login_required
def save_attendee(project_id: int, attendee_id: int):
    _project, role = load_project(project_id, "member")
    if not query_one("SELECT 1 FROM attendees WHERE id = ? AND project_id = ?", (attendee_id, project_id)):
        abort(404)

    trade_id = _to_int(request.form.get("trade_id"))
    if trade_id and not query_one("SELECT 1 FROM trades WHERE id = ? AND project_id = ?",
                                  (trade_id, project_id)):
        trade_id = None

    execute(
        """
        UPDATE attendees SET name = ?, organisation = ?, job_title = ?, email = ?,
               trade_id = ?, active = ?
        WHERE id = ? AND project_id = ?
        """,
        (_clean("name") or "Unnamed", _clean("organisation"), _clean("job_title"), _clean("email"),
         trade_id, 1 if request.form.get("active") else 0, attendee_id, project_id),
    )
    flash("Attendee saved", "success")
    return _back(project_id)


@bp.post("/minutes/attendees/<int:attendee_id>/delete")
@login_required
def delete_attendee(project_id: int, attendee_id: int):
    _project, role = load_project(project_id, "member")
    if not query_one("SELECT 1 FROM attendees WHERE id = ? AND project_id = ?", (attendee_id, project_id)):
        abort(404)
    # The register is a record, so an item keeps the name of whoever owned it
    # even after that person comes off the roster.
    execute(
        """
        UPDATE meeting_items
           SET owner_name = COALESCE(NULLIF(owner_name, ''),
                                     (SELECT name FROM attendees WHERE id = ?))
         WHERE owner_id = ? AND project_id = ?
        """,
        (attendee_id, attendee_id, project_id),
    )
    execute("DELETE FROM attendees WHERE id = ? AND project_id = ?", (attendee_id, project_id))
    flash("Attendee removed", "success")
    return _back(project_id)
