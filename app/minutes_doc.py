"""The Word documents produced from the minutes: a meeting's minutes, the
agenda for the next one, and the action register.

Kept apart from :mod:`app.word`, which knows nothing about projects, and from
:mod:`app.minutes`, which knows nothing about file formats.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .dates import to_display
from .minutes import impact_name
from .word import Document


def _project_line(project: Mapping[str, Any]) -> str:
    """The project number and name, which every document carries at the top."""
    parts = [str(project.get("code") or "").strip(), str(project.get("name") or "").strip()]
    line = " — ".join(p for p in parts if p)
    client = str(project.get("client") or "").strip()
    return f"{line} · {client}" if client else line


def _status(item: Mapping[str, Any]) -> str:
    if not item.get("is_open"):
        closed = to_display(item.get("closed_date"))
        return f"Closed {closed}" if closed else "Closed"
    if item.get("is_overdue"):
        return f"Open — {item.get('days_overdue')} days overdue"
    return "Open"


def _owner(item: Mapping[str, Any]) -> str:
    return str(item.get("owner_label") or item.get("owner_person") or item.get("owner_name") or "—")


def _item_rows(items: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    rows = []
    for item in items:
        body = str(item.get("subject") or "").strip()
        discussion = str(item.get("discussion") or "").strip()
        if discussion:
            body = f"{body}\n{discussion}" if body else discussion
        rows.append([
            str(item.get("ref") or ""),
            body,
            str(item.get("agreement") or ""),
            _owner(item),
            str(item.get("trade_name") or "—"),
            impact_name(item.get("impact")),
            to_display(item.get("due_date")) or "—",
            _status(item),
        ])
    return rows


_ITEM_HEADERS = ("Item", "Subject & discussion", "Agreed action", "Owner", "Trade",
                 "Affects", "Due", "Status")
_ITEM_WIDTHS = (6, 24, 26, 12, 9, 7, 7, 9)


def minutes_document(project: Mapping[str, Any], sheet: Mapping[str, Any]) -> bytes:
    """One meeting's minutes: header, attendance, then the items."""
    project = dict(project)          # a database row does not answer .get()
    meeting = sheet["meeting"]
    title = str(meeting.get("title") or "").strip() or "Minutes of meeting"
    doc = Document(title=f"{project.get('code')} — {title}", orientation="landscape")

    doc.add_title("Minutes of meeting", _project_line(project))
    doc.add_fields([
        ("Meeting", meeting.get("ref") or "—"),
        ("Subject", meeting.get("title")),
        ("Date", to_display(meeting.get("meeting_date"))),
        ("Time", meeting.get("meeting_time")),
        ("Location", meeting.get("location")),
        ("Chaired by", meeting.get("chaired_by")),
        ("Minuted by", meeting.get("minuted_by")),
        ("Next meeting", to_display(meeting.get("next_date"))),
    ])

    attendance = sheet.get("attendance") or []
    doc.add_heading("Attendance", 2)
    if attendance:
        doc.add_table(
            headers=("", "Name", "Organisation", "Role", "Trade"),
            rows=[[
                "Present" if person["present"] else ("Absent" if person["invited"] else "—"),
                person.get("name"),
                person.get("organisation") or "—",
                person.get("job_title") or "—",
                person.get("trade_name") or "—",
            ] for person in attendance],
            widths=(10, 26, 26, 22, 16),
        )
    else:
        doc.add_paragraph("No attendees recorded.", italic=True)

    items = sheet.get("items") or []
    doc.add_heading("Items and agreements", 2)
    if items:
        doc.add_table(headers=_ITEM_HEADERS, rows=_item_rows(items), widths=_ITEM_WIDTHS)
    else:
        doc.add_paragraph("No items were minuted for this meeting.", italic=True)

    open_items = [i for i in items if i.get("is_open")]
    doc.add_paragraph(
        f"{len(items)} item{'' if len(items) == 1 else 's'} minuted · "
        f"{len(open_items)} still open · "
        f"{sum(1 for i in open_items if i.get('affects_time'))} affecting time · "
        f"{sum(1 for i in open_items if i.get('affects_cost'))} affecting cost",
        style="Caption",
    )

    if str(meeting.get("notes") or "").strip():
        doc.add_heading("Notes", 2)
        doc.add_paragraph(meeting["notes"])

    return doc.render()


def _meeting_of(item: Mapping[str, Any]) -> str:
    """Which meeting an item came from, as the register column reads it."""
    if not item.get("meeting_id"):
        return "—"
    name = str(item.get("meeting_ref") or item.get("meeting_title") or "Meeting").strip()
    stamp = to_display(item.get("meeting_date"))
    return f"{name}\n{stamp}" if stamp else name


def register_document(project: Mapping[str, Any], items: Sequence[Mapping[str, Any]],
                      title: str = "Action register", note: str = "") -> bytes:
    """The filtered register, or the agenda for the next meeting — same shape,
    different heading, so what is on screen is what lands in the document."""
    project = dict(project)
    doc = Document(title=f"{project.get('code')} — {title}", orientation="landscape")
    doc.add_title(title, _project_line(project))
    if note:
        doc.add_paragraph(note, style="Caption")

    if items:
        rows = [
            [_meeting_of(i)] + row for i, row in zip(items, _item_rows(items))
        ]
        doc.add_table(
            headers=("Meeting",) + _ITEM_HEADERS,
            rows=rows,
            widths=(12,) + tuple(w * 0.88 for w in _ITEM_WIDTHS),
        )
    else:
        doc.add_paragraph("Nothing matches this filter.", italic=True)

    return doc.render()
