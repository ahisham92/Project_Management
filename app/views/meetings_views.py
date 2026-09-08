"""Minutes of meeting: the register, one meeting's minutes, and the agenda."""

from __future__ import annotations

import io

from flask import (
    Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request,
    send_file, url_for,
)

from ..auth import ROLE_RANK, load_project, login_required
from ..dates import from_input, from_input_or, to_display
from ..db import execute, insert, query_one
from ..minutes import (
    ATTENDEE_ORDERS, COLUMNS, DEFAULT_FILTER, FILTERS, KIND_TITLES, KIND_WORDS,
    KINDS, OWNERS, STATUSES, filter_items, next_ref, normalise_attendee_order,
    normalise_impact, normalise_kind, normalise_owner, normalise_sort, normalise_status,
    progress_note, sort_items, summarise,
)
from ..service import (
    impact_choices, load_attachments, load_attendees, load_items, load_meeting, load_meetings,
    load_steps, load_template, load_trades, meeting_items, meeting_sheet, move_item,
    next_sort_order, renumber_items, set_attendance, set_item_trades, today,
)
from ..workflow import ordered as ordered_steps
from .handing_out import PDF, WORD, handed_out

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


def _kind() -> str:
    """Which register this request belongs to.

    The URL says it on the pages that have one of their own; a form posted from
    either register carries it, so a change made on the internal list comes
    back to the internal list.
    """
    if request.view_args and request.view_args.get("kind"):
        return normalise_kind(request.view_args["kind"])
    return normalise_kind(request.form.get("kind") or request.args.get("kind"))


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
        # The date the register is being read as at. Empty means today, which
        # is the live register; a date rewinds it to how it stood then.
        "as_at": from_input(request.args.get("as_at")) or "",
        "kind": _kind(),
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
        "as_at": to_display(filters["as_at"]) or None,
        "kind": filters["kind"],
        "sort": filters["sort"],
        "dir": filters["dir"],
    }
    return {k: v for k, v in args.items() if v is not None}


def _selection(project_id: int, filters: dict[str, object]) -> list[dict]:
    """The items the filters ask for, in the requested order."""
    items = load_items(project_id, today(), kind=str(filters["kind"]),
                       rewind_to=str(filters["as_at"]))
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


def _download(data: bytes, filename: str, project_id: int = 0, kind: str = "",
              name: str = "", note: str = ""):
    """One Word document, sent and kept.

    Kept because "let me see the register Ola sent" is a question about the
    file that went out, not about the one the same filter builds today.
    """
    if project_id and kind:
        return handed_out(project_id, data, filename, WORD, kind, name, note)
    return send_file(io.BytesIO(data), mimetype=WORD, as_attachment=True,
                     download_name=filename)


def _stamp() -> str:
    return today().replace("-", "")


# --- the register ----------------------------------------------------------

@bp.get("/minutes", defaults={"kind": "client"})
@bp.get("/internal/register", defaults={"kind": "internal"})
@login_required
def index(project_id: int, kind: str):
    """One register: the client's minutes, or the internal weekly list.

    The same page either way — an item, an owner, a date, open until it is
    done — because they are the same kind of record kept for two audiences.
    """
    project, role = load_project(project_id)
    filters = _filters()
    # The tiles count the same register the table is showing. Read as at a past
    # date, counting today's open items above a table of how things stood then
    # would put two different days on one page.
    everything = load_items(project_id, today(), kind=str(filters["kind"]),
                            rewind_to=str(filters["as_at"]))
    rows = _selection(project_id, filters)

    return render_template(
        "minutes.html",
        project=project, role=role, items=rows, totals=summarise(everything),
        shown=len(rows), filters=filters, link_args=_link_args(filters),
        chips=FILTERS, impacts=impact_choices(project_id), owners=OWNERS, statuses=STATUSES, columns=COLUMNS,
        kind=filters["kind"], kinds=KINDS, kind_title=KIND_TITLES[str(filters["kind"])],
        kind_word=KIND_WORDS[str(filters["kind"])],
        as_at=filters["as_at"],
        as_at_note=progress_note(rows, str(filters["as_at"])) if filters["as_at"] else "",
        sort=filters["sort"], direction=filters["dir"],
        attendees=load_attendees(project_id), trades=load_trades(project_id),
        attendee_orders=ATTENDEE_ORDERS,
        attendee_order=normalise_attendee_order(project["attendee_order"]),
        meetings=load_meetings(project_id, str(filters["kind"])), today=today(),
        can_report=_can_report(role), can_edit=_can_edit(role),
    )



# --- this week -------------------------------------------------------------

@bp.get("/internal")
@login_required
def week(project_id: int):
    """What the project needs from us this week, from wherever it comes from.

    The Internal tab opens here rather than on a list, because a list of
    minuted items is only ever half a week. The other half is on the programme
    — what goes out, what comes back, and the lines that simply have to be
    carried forward with nothing to show at the end of it. Reading two tabs and
    holding the join in your head is how a week goes wrong.

    Nothing on this page is stored. Every row is a reading of a deliverable or
    an item that already exists, so a change made here is a change to that
    record — it shows on the Progress, Schedule and Minutes tabs at once, and a
    change made on any of them shows here.
    """
    from .. import week as weeks
    from ..service import project_plan, project_snapshot

    project, role = load_project(project_id)
    plan = project_plan(project)

    # A Sunday-to-Thursday team's week opens on Sunday. Reading it off the
    # project's own calendar beats assuming a Monday for everyone.
    first_day = weeks.first_working_day(plan["calendars"][None].week)

    asked = from_input(request.args.get("week")) or today()
    start, end = weeks.week_window(asked, first_day)

    # Where each line is meant to have got to by the end of the week, not by
    # today: that is what turns "carry on with it" into a number.
    targets = {row["id"]: row["planned_pct"]
               for row in project_snapshot(project, end)["tasks"]}

    trades = {t["id"]: t["name"] for t in plan["trades"]}
    for row in plan["tasks"]:
        row["trade_names"] = ", ".join(
            trades[key] for key, share in (row.get("allocations") or {}).items()
            if share and key in trades)

    client_items = load_items(project_id, today(), kind="client")
    internal_items = load_items(project_id, today(), kind="internal")
    rows = weeks.compile_week(plan["tasks"], client_items, internal_items, start, end, targets)

    meetings = load_meetings(project_id, "internal")
    return render_template(
        "week.html",
        project=project, role=role, kind="internal",
        kind_title=KIND_TITLES["internal"], kind_word=KIND_WORDS["internal"],
        start=start, end=end, today=today(),
        is_this_week=start <= today() <= end,
        previous=weeks.shift(start, -1), next=weeks.shift(start, 1),
        groups=weeks.group(rows), rows=rows, totals=weeks.summarise(rows),
        sources=weeks.SOURCES,
        meeting=weeks.in_week(meetings, start, end),
        suggested_ref=weeks.meeting_ref(start),
        meetings=meetings, trades=plan["trades"], owners=OWNERS,
        impacts=impact_choices(project_id),
        steps=ordered_steps(load_steps(project_id)),
        limit=plan["max_revisions"],
        editing=_to_int(request.args.get("edit")),
        can_report=_can_report(role), can_edit=_can_edit(role),
    )


@bp.post("/internal/weekly")
@login_required
def weekly_meeting(project_id: int):
    """Opens this week's internal meeting, making it if it is not there yet.

    One button rather than a form: the week decides the date and the reference,
    and a weekly meeting that has to be described before it can be opened is a
    weekly meeting that gets skipped.
    """
    from .. import week as weeks

    project, _role = load_project(project_id, "member")
    asked = from_input(request.form.get("week")) or today()
    start, end = weeks.week_window(asked)

    existing = weeks.in_week(load_meetings(project_id, "internal"), start, end)
    if existing:
        return redirect(url_for("meetings.meeting", project_id=project_id,
                                meeting_id=existing["id"]))

    # Dated the day it is held — today when this is the current week, otherwise
    # the day the week opens.
    held = today() if start <= today() <= end else start
    meeting_id = insert(
        """
        INSERT INTO meetings (project_id, kind, ref, title, meeting_date, chaired_by, notes, user_id)
        VALUES (?, 'internal', ?, ?, ?, ?, '', ?)
        """,
        (project_id, weeks.meeting_ref(start),
         f"Internal weekly — week of {to_display(start)}", held,
         g.user["name"], g.user["id"]),
    )

    roster = [int(a["id"]) for a in load_attendees(project_id, include_inactive=False)]
    if roster:
        set_attendance(meeting_id, roster, roster)

    flash("Weekly meeting opened — the week's requirements are on the Internal tab", "success")
    return redirect(url_for("meetings.meeting", project_id=project_id, meeting_id=meeting_id))


@bp.get("/minutes/register.docx", defaults={"kind": "client"})
@bp.get("/internal/register.docx", defaults={"kind": "internal"})
@login_required
def register_word(project_id: int, kind: str):
    """The register exactly as filtered on screen, as a Word document.

    Read as at a date, it is the answer to a client asking where things stood
    then — so the document says so at the top rather than looking like today's.
    """
    from ..minutes_doc import register_document

    project, _role = load_project(project_id)
    filters = _filters()
    rows = _selection(project_id, filters)

    said = _describe(project_id, filters)
    note = "Filtered: " + ", ".join(said) if said else ""
    if filters["as_at"]:
        note = progress_note(rows, str(filters["as_at"])) + ((" · " + note) if note else "")

    title = KIND_TITLES[str(filters["kind"])] + " — action register"
    data = register_document(project, rows, title, note)
    stem = "internal" if filters["kind"] == "internal" else "actions"
    return _download(data, f"{project['code']}-{stem}-{_stamp()}.docx",
                     project_id, "register", title, note)


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
        parts.append("affecting "
                     + dict(impact_choices(project_id)).get(str(filters["impact"]),
                                                            str(filters["impact"])).lower())
    if filters["from"]:
        parts.append(f"raised from {to_display(filters['from'])}")
    if filters["to"]:
        parts.append(f"raised to {to_display(filters['to'])}")
    return parts


# --- the agenda for the next meeting ---------------------------------------

@bp.get("/minutes/agenda", defaults={"kind": "client"})
@bp.get("/internal/agenda", defaults={"kind": "internal"})
@login_required
def agenda(project_id: int, kind: str):
    """Everything still open, grouped by owner — the sheet you walk into the
    next meeting with."""
    project, role = load_project(project_id)
    search = (request.args.get("q") or "").strip()
    trade_id = _to_int(request.args.get("trade"))
    owner = normalise_owner(request.args.get("owner"))
    kind = _kind()

    items = filter_items(load_items(project_id, today(), kind=kind), chip="open", search=search,
                         trade_id=trade_id, owner=owner)
    items = sort_items(items, "due", "asc")

    by_owner: dict[str, list[dict]] = {}
    for item in items:
        by_owner.setdefault(item["owner_label"] or "Unassigned", []).append(item)
    groups = [{"name": name, "items": rows} for name, rows in by_owner.items()]
    groups.sort(key=lambda grp: (grp["name"] == "Unassigned", grp["name"].lower()))

    meetings = load_meetings(project_id, kind)
    return render_template(
        "agenda.html",
        project=project, role=role, items=items, groups=groups, totals=summarise(items),
        search=search, trade_id=trade_id, owner=owner, owners=OWNERS,
        kind=kind, kind_title=KIND_TITLES[kind], kind_word=KIND_WORDS[kind],
        trades=load_trades(project_id), attendees=load_attendees(project_id),
        last_meeting=meetings[0] if meetings else None, today=today(),
    )


@bp.get("/minutes/agenda.docx", defaults={"kind": "client"})
@bp.get("/internal/agenda.docx", defaults={"kind": "internal"})
@login_required
def agenda_word(project_id: int, kind: str):
    from ..minutes_doc import register_document

    project, _role = load_project(project_id)
    kind = _kind()
    items = sort_items(
        filter_items(load_items(project_id, today(), kind=kind), chip="open"), "due", "asc")
    data = register_document(
        project, items, f"{KIND_TITLES[kind]} — agenda",
        f"Every item still open as at {to_display(today())}.",
    )
    stem = "internal-agenda" if kind == "internal" else "agenda"
    return _download(data, f"{project['code']}-{stem}-{_stamp()}.docx",
                     project_id, "agenda", f"{KIND_TITLES[kind]} — agenda",
                     f"Open as at {to_display(today())}")


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
        attachments=load_attachments(project_id, meeting_id),
        attendee_orders=ATTENDEE_ORDERS,
        attendee_order=normalise_attendee_order(project["attendee_order"]),
        first_id=order[0] if order else None, last_id=order[-1] if order else None,
        project=project, role=role, sheet=sheet, meeting=sheet["meeting"],
        items=sheet["items"], attendance=sheet["attendance"],
        impacts=impact_choices(project_id), owners=OWNERS, statuses=STATUSES,
        editing=editing,
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

    # Where the practice has uploaded its own form on the Setup tab, the
    # minutes are built by filling that in; otherwise the layout in the code.
    # Attachments are named in the document either way; the PDF carries them.
    attachments = load_attachments(project_id, meeting_id)
    form = load_template(project_id, "minutes")
    if form:
        from ..doctemplate import TemplateError
        from ..minutes_doc import minutes_from_template

        try:
            document = minutes_from_template(form["content"], project, sheet, attachments)
        except TemplateError as exc:
            flash(f"{exc} The built-in layout was used instead.", "error")
            document = minutes_document(project, sheet, attachments)
    else:
        document = minutes_document(project, sheet, attachments)
    said = str(sheet["meeting"].get("title") or "Minutes")
    return _download(document, f"{project['code']}-{name}-{stamp}.docx",
                     project_id, "minutes",
                     f"{sheet['meeting'].get('ref') or 'Minutes'} — {said}",
                     to_display(sheet["meeting"].get("meeting_date")))


@bp.get("/minutes/meetings/<int:meeting_id>.pdf")
@login_required
def meeting_pdf(project_id: int, meeting_id: int):
    """The minutes as a PDF, with whatever is attached compiled onto the end."""
    from ..minutes_doc import minutes_pdf
    from ..pdf import PdfError

    project, _role = load_project(project_id)
    sheet = meeting_sheet(project_id, meeting_id, today())
    if sheet is None:
        abort(404)

    try:
        data = minutes_pdf(project, sheet,
                           load_attachments(project_id, meeting_id, with_content=True))
    except PdfError as exc:
        flash(str(exc), "error")
        return redirect(url_for("meetings.meeting", project_id=project_id,
                                meeting_id=meeting_id))

    stamp = (sheet["meeting"]["meeting_date"] or today()).replace("-", "")
    name = (sheet["meeting"]["ref"] or "minutes").replace("/", "-").replace(" ", "-")
    said = str(sheet["meeting"].get("title") or "Minutes")
    return handed_out(project_id, data, f"{project['code']}-{name}-{stamp}.pdf", PDF,
                      "minutes_pdf",
                      f"{sheet['meeting'].get('ref') or 'Minutes'} — {said}",
                      to_display(sheet["meeting"].get("meeting_date")))


@bp.post("/minutes/meetings/<int:meeting_id>/attachments")
@login_required
def add_meeting_attachment(project_id: int, meeting_id: int):
    """A PDF kept with the minutes and compiled into the exported PDF."""
    from ..service import AttachmentError, MAX_ATTACHMENT, add_attachment

    _project, role = load_project(project_id, "member")
    if load_meeting(project_id, meeting_id) is None:
        abort(404)

    upload = request.files.get("file")
    data = upload.read(MAX_ATTACHMENT + 1) if upload else b""
    try:
        add_attachment(project_id, meeting_id, request.form.get("name") or "",
                       (upload.filename if upload else ""), data, g.user["id"])
        flash("Attached — it is compiled into the exported PDF", "success")
    except AttachmentError as exc:
        flash(str(exc), "error")
    return redirect(url_for("meetings.meeting", project_id=project_id,
                            meeting_id=meeting_id) + "#attachments")


@bp.get("/minutes/attachments/<int:attachment_id>")
@login_required
def read_attachment(project_id: int, attachment_id: int):
    from ..service import attachment as one_attachment

    load_project(project_id)
    found = one_attachment(project_id, attachment_id)
    if found is None:
        abort(404)
    return send_file(io.BytesIO(found["content"]), mimetype="application/pdf",
                     as_attachment=False,
                     download_name=(found["filename"] or found["name"] or "attachment") + (
                         "" if str(found["filename"] or "").lower().endswith(".pdf") else ".pdf"))


@bp.post("/minutes/attachments/<int:attachment_id>/delete")
@login_required
def delete_attachment(project_id: int, attachment_id: int):
    from ..service import attachment as one_attachment, remove_attachment

    _project, role = load_project(project_id, "member")
    found = one_attachment(project_id, attachment_id)
    if found is None:
        abort(404)
    remove_attachment(project_id, attachment_id)
    flash("Attachment removed", "success")
    return redirect(url_for("meetings.meeting", project_id=project_id,
                            meeting_id=found["meeting_id"]) + "#attachments")


@bp.post("/minutes/attendee-order")
@login_required
def set_attendee_order(project_id: int):
    """How the attendance table is ordered in every issued set of minutes."""
    _project, role = load_project(project_id, "member")
    execute("UPDATE projects SET attendee_order = ? WHERE id = ?",
            (normalise_attendee_order(request.form.get("attendee_order")), project_id))
    flash("The attendance order is set for every set of minutes on this project", "success")
    return redirect(request.form.get("back")
                    or url_for("meetings.index", project_id=project_id, kind="client"))


@bp.post("/minutes/attendees/<int:attendee_id>/move")
@login_required
def move_attendee_row(project_id: int, attendee_id: int):
    """Moves one person up or down the roster, which is the order the exported
    attendance table lists them in."""
    from ..service import move_attendee

    _project, _role = load_project(project_id, "member")
    direction = "up" if (request.form.get("direction") or "").strip().lower() == "up" else "down"
    moved = move_attendee(project_id, attendee_id, direction)

    # Answered as JSON when the page asks, so the row moves where it stands
    # rather than the whole page coming back to show two rows swapped.
    if request.headers.get("Accept", "").startswith("application/json"):
        if not moved:
            return jsonify({"ok": False,
                            "error": f"That person is already "
                                     f"{'first' if direction == 'up' else 'last'}"}), 400
        return jsonify({"ok": True, "moved": attendee_id,
                        "order": [{"id": p["id"]} for p in load_attendees(project_id)]})

    if not moved:
        flash(f"That person is already {'first' if direction == 'up' else 'last'}", "error")
    return _back(project_id)


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
        INSERT INTO meetings (project_id, kind, ref, title, meeting_date, meeting_time, location,
                              chaired_by, next_date, notes, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, _kind(), _clean("ref"), _clean("title"), meeting_date, _clean("meeting_time"),
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
               location = ?, chaired_by = ?, next_date = ?, notes = ?,
               purpose = ?, prepared_by = ?, reviewed_by = ?, issue_date = ?, attachment = ?
        WHERE id = ? AND project_id = ?
        """,
        (_clean("ref"), _clean("title"),
         from_input_or(request.form.get("meeting_date"), today()), _clean("meeting_time"),
         _clean("location"), _clean("chaired_by"),
         from_input(request.form.get("next_date")) or "", _clean("notes"),
         _clean("purpose"), _clean("prepared_by"), _clean("reviewed_by"),
         from_input(request.form.get("issue_date")) or "", _clean("attachment"),
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
        fields["impact"] = normalise_impact(
            form.get("impact"), [key for key, _name in impact_choices(project_id)])
    if "raised_date" in form:
        fields["raised_date"] = from_input(form.get("raised_date")) or ""
    if "due_date" in form:
        fields["due_date"] = from_input(form.get("due_date")) or ""

    # Closing an item stamps today unless a date was given. The date it was
    # actually closed is what a register read as at a past day turns on, so it
    # is editable rather than being whenever somebody got round to ticking it.
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
    """Back to wherever the item was added from.

    An item closed on the week page belongs to the week page: sending somebody
    to the register because that is where the record lives is the sort of thing
    that makes a page not worth using.
    """
    back = (request.form.get("return") or "").strip()
    if back == "meeting" and meeting_id:
        return redirect(url_for("meetings.meeting", project_id=project_id, meeting_id=meeting_id))
    if back == "week":
        return redirect(url_for("meetings.week", project_id=project_id,
                                week=(request.form.get("week") or "").strip() or None))
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

    # An item belongs to whichever register it was raised in — the meeting's
    # own, when it was raised inside one, so the two can never disagree.
    kind = _kind()
    if fields.get("meeting_id"):
        row = query_one("SELECT kind FROM meetings WHERE id = ? AND project_id = ?",
                        (fields["meeting_id"], project_id))
        if row:
            kind = normalise_kind(row["kind"])

    # The number is set by renumbering once the item is in its meeting.
    columns = dict(fields, project_id=project_id, ref="", kind=kind,
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
    moved = move_item(project_id, item_id, direction)

    # Answered as JSON when the page asks for it, so a row swaps where it stands
    # rather than the whole page being fetched again to show two rows in the
    # other order.
    if request.headers.get("Accept", "").startswith("application/json"):
        if not moved:
            return jsonify({"ok": False,
                            "error": f"That item is already "
                                     f"{'first' if direction == 'up' else 'last'}"}), 400
        rows = meeting_items(project_id, item["meeting_id"])
        return jsonify({
            "ok": True,
            "moved": item_id,
            "order": [{"id": row["id"], "ref": row["ref"]} for row in rows],
        })

    if not moved:
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
