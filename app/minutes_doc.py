"""The Word documents produced from the minutes.

The issued minutes follow the practice's own template — the letterhead across
the top, the logo and page number along the bottom, the details and attendance
grid, the shaded items table, and the two signature blocks at the end. That is
not decoration: a set of minutes that arrives looking like the last set is one
the client reads without first working out what it is.

Kept apart from :mod:`app.word`, which knows nothing about projects, and from
:mod:`app.minutes`, which knows nothing about file formats.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from .dates import to_display
from .minutes import impact_name, owner_of, trade_names
from .word import Document

# The grids, in twips, straight off the template. Fixed rather than
# proportional: a name column that grows because somebody has a long surname is
# exactly what makes two sets of minutes look like two different documents.
DETAILS_GRID = (1081, 1709, 1440, 1620, 1692, 2242)
ITEMS_GRID = (568, 2786, 1323, 884, 1234, 1204, 1629)
SIGNATURE_GRID = (1351, 4118, 1419, 2902)

HEAD_FILL = "D9D9D9"          # the items table's two header rows
BAND_FILL = "E6E6E6"          # the attendance header inside the details table
SIGN_FONT = "Arial"

HEADING = "Minutes of Meeting"


@lru_cache(maxsize=1)
def letterhead_logo() -> bytes:
    """The logo the footer draws, read once."""
    where = Path(__file__).with_name("static") / "dar-logo.png"
    try:
        return where.read_bytes()
    except OSError:
        return b""            # a missing logo is a plainer page, not a failure


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
    return owner_of(item) or "—"


def _subject(item: Mapping[str, Any]) -> str:
    """The subject with its discussion under it, as the template runs them."""
    body = str(item.get("subject") or "").strip()
    discussion = str(item.get("discussion") or "").strip()
    if discussion:
        return f"{body}\n{discussion}" if body else discussion
    return body


def _item_rows(items: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    return [[
        str(item.get("ref") or ""),
        _subject(item),
        str(item.get("agreement") or ""),
        _owner(item),
        trade_names(item) or "—",
        impact_name(item.get("impact")),
        to_display(item.get("due_date")) or "—",
        _status(item),
    ] for item in items]


_ITEM_HEADERS = ("Item", "Subject & discussion", "Agreed action", "Owner", "Trade",
                 "Affects", "Due", "Status")
_ITEM_WIDTHS = (6, 24, 26, 12, 9, 7, 7, 9)


# --- one meeting's minutes, on the template ---------------------------------

def _details(project: Mapping[str, Any], meeting: Mapping[str, Any],
             attendance: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    """The first grid: what the meeting was, and who was in it.

    An asterisk beside the number marks who actually attended, which is how the
    template says it — one column instead of two, and a legend under the table.
    """
    label = {"bold": True, "size": 9}
    rows: list[list[Any]] = [
        [dict(label, text="Project:"),
         {"text": _project_line(project), "span": 5, "bold": True, "size": 10}],
        [dict(label, text="Reference"),
         {"text": str(meeting.get("ref") or "—"), "span": 5, "size": 9}],
        [dict(label, text="Purpose:"),
         {"text": str(meeting.get("purpose") or meeting.get("title") or "—"),
          "span": 2, "size": 9},
         dict(label, text="Date:"),
         {"text": to_display(meeting.get("meeting_date")) or "—", "span": 2, "size": 9}],
        [dict(label, text="Location:"),
         {"text": str(meeting.get("location") or "—"), "span": 2, "size": 9},
         dict(label, text="Time:"),
         {"text": str(meeting.get("meeting_time") or "—"), "span": 2, "size": 9}],
        [{"text": "", "fill": BAND_FILL, "repeat": True},
         {"text": "Name", "fill": BAND_FILL, "bold": True, "size": 9},
         {"text": "Organization", "fill": BAND_FILL, "bold": True, "size": 9},
         {"text": "Role", "fill": BAND_FILL, "bold": True, "size": 9},
         {"text": "Trade", "fill": BAND_FILL, "bold": True, "size": 9, "span": 2}],
    ]

    for number, person in enumerate(attendance, start=1):
        mark = "*" if person.get("present") else ""
        rows.append([
            {"text": f"{number}{mark}", "align": "center", "size": 9},
            {"text": person.get("name") or "", "size": 9},
            {"text": person.get("organisation") or "—", "size": 9},
            {"text": person.get("job_title") or "—", "size": 9},
            {"text": person.get("trade_name") or "—", "size": 9, "span": 2},
        ])
    return rows


def _items_table(items: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    """The second grid: the items, under two shaded header rows."""
    head = {"fill": HEAD_FILL, "bold": True, "size": 10, "repeat": True}
    rows: list[list[Any]] = [
        [{"text": "Items and Agreement", "span": 7, "fill": HEAD_FILL, "bold": True,
          "size": 11, "align": "center", "repeat": True}],
        [dict(head, text="Item"), dict(head, text="Subject & discussion"),
         dict(head, text="Agreed action"), dict(head, text="Owner"),
         dict(head, text="Affects"), dict(head, text="Due"), dict(head, text="Status")],
    ]
    for item in items:
        rows.append([
            {"text": str(item.get("ref") or ""), "size": 9, "valign": "top"},
            {"text": _subject(item), "size": 9, "valign": "top"},
            {"text": str(item.get("agreement") or ""), "size": 9, "valign": "top"},
            {"text": _owner(item), "size": 9, "valign": "top"},
            {"text": impact_name(item.get("impact")), "size": 9, "valign": "top"},
            {"text": to_display(item.get("due_date")) or "—", "size": 9, "valign": "top"},
            {"text": _status(item), "size": 9, "valign": "top"},
        ])
    return rows


def _signature_block(role: str, name: str, issued: str) -> list[list[Any]]:
    """Two lines: who, with a rule to sign on, and the day it was issued.

    The signature is always a blank rule. A document that arrives with somebody
    else's signature already on it is not a signature.
    """
    field = {"size": 9, "font": SIGN_FONT, "valign": "bottom"}
    return [
        [dict(field, text=role),
         dict(field, text=name or "", underline=True),
         dict(field, text="Signature:"),
         dict(field, text="", underline=True)],
        [dict(field, text="Issue date:"),
         dict(field, text=issued or "", underline=True),
         dict(field, text=""),
         dict(field, text="")],
    ]


def minutes_document(project: Mapping[str, Any], sheet: Mapping[str, Any]) -> bytes:
    """One meeting's minutes, on the practice's template."""
    project = dict(project)          # a database row does not answer .get()
    meeting = dict(sheet["meeting"])
    attendance = list(sheet.get("attendance") or [])
    items = list(sheet.get("items") or [])

    title = str(meeting.get("title") or "").strip() or "Minutes of meeting"
    doc = Document(
        title=f"{project.get('code')} — {title}",
        heading=HEADING,
        logo=letterhead_logo(),
        footer_note=_project_line(project),
    )

    doc.add_grid(DETAILS_GRID, _details(project, meeting, attendance), indent=-34)
    if attendance:
        doc.add_paragraph("* Present at this meeting", style="Caption")
    else:
        doc.add_paragraph("No attendees recorded.", style="Caption")

    if items:
        doc.add_grid(ITEMS_GRID, _items_table(items))
    else:
        doc.add_paragraph("No items were minuted for this meeting.", italic=True)

    attachment = str(meeting.get("attachment") or "").strip()
    if attachment:
        doc.add_paragraph(f"Attachment: {attachment}", style="Caption")

    if str(meeting.get("notes") or "").strip():
        doc.add_heading("Notes", 2)
        doc.add_paragraph(meeting["notes"])

    doc.add_paragraph("", style="Caption")
    doc.add_grid(SIGNATURE_GRID,
                 _signature_block("Prepared by:", str(meeting.get("prepared_by") or ""),
                                  to_display(meeting.get("issue_date"))),
                 borders=False)
    doc.add_grid(SIGNATURE_GRID,
                 _signature_block("Reviewed & Accepted by:",
                                  str(meeting.get("reviewed_by") or ""), ""),
                 borders=False)
    return doc.render()


# --- the register and the agenda --------------------------------------------

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
    different heading, so what is on screen is what lands in the document.

    Landscape and proportional, unlike the minutes: this is a working list that
    grows a column when somebody asks for one, not an issued document.
    """
    project = dict(project)
    doc = Document(title=f"{project.get('code')} — {title}", orientation="landscape",
                   heading=title, logo=letterhead_logo(),
                   footer_note=_project_line(project))
    doc.add_title(title, _project_line(project))
    if note:
        doc.add_paragraph(note, style="Caption")

    if items:
        rows = [[_meeting_of(i)] + row for i, row in zip(items, _item_rows(items))]
        doc.add_table(
            headers=("Meeting",) + _ITEM_HEADERS,
            rows=rows,
            widths=(12,) + tuple(w * 0.88 for w in _ITEM_WIDTHS),
        )
    else:
        doc.add_paragraph("Nothing matches this filter.", italic=True)

    return doc.render()
