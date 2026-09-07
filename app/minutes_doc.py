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

# The form the issued minutes are, bottom left of every page.
FORM_CODE = "PRC-PM-07 (F6) REV1"


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


def _subject_cell(item: Mapping[str, Any]) -> dict[str, Any]:
    """The same, as a cell whose first line is the subject in bold.

    Somebody skimming a page of minutes is looking for a subject, not a
    paragraph, so the subject has to be the thing the eye lands on.
    """
    return {"lead": str(item.get("subject") or "").strip(),
            "text": str(item.get("discussion") or "").strip(),
            "size": 9, "valign": "top"}


def _item_rows(items: Sequence[Mapping[str, Any]]) -> list[list[str]]:
    return [[
        str(item.get("ref") or ""),
        _subject(item),
        str(item.get("agreement") or ""),
        _owner(item),
        trade_names(item) or "—",
        item.get("impact_name") or impact_name(item.get("impact")),
        to_display(item.get("due_date")) or "—",
        _status(item),
    ] for item in items]


_ITEM_HEADERS = ("Item", "Subject & discussion", "Agreed action", "Owner", "Trade",
                 "Affects", "Due", "Status")
_ITEM_WIDTHS = (6, 24, 26, 12, 9, 7, 7, 9)


# --- one meeting's minutes, on the template ---------------------------------

def who_was_there(attendance: Sequence[Mapping[str, Any]]) -> tuple[list[dict], bool]:
    """Who the exported attendance table lists.

    The people who were there, and nobody else: a set of minutes records a
    meeting, and somebody who did not come to it did not say anything in it.
    Where nothing has been marked — minutes typed up before the attendance was
    ticked — the whole roster is listed with an asterisk against whoever is
    marked present, rather than an empty table.
    """
    present = [dict(p) for p in attendance if p.get("present")]
    if present:
        return present, False
    return [dict(p) for p in attendance], True


def _details(project: Mapping[str, Any], meeting: Mapping[str, Any],
             attendance: Sequence[Mapping[str, Any]], marked: bool = False) -> list[list[Any]]:
    """The first grid: what the meeting was, and who was in it."""
    label = {"bold": True, "size": 9}
    rows: list[list[Any]] = [
        [dict(label, text="Project:"),
         {"text": _project_line(project), "span": 5, "bold": True, "size": 9}],
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
        mark = "*" if marked and person.get("present") else ""
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
    head = {"fill": HEAD_FILL, "bold": True, "size": 9, "repeat": True}
    rows: list[list[Any]] = [
        [{"text": "Items and Agreement", "span": 7, "fill": HEAD_FILL, "bold": True,
          "size": 10, "align": "center", "repeat": True}],
        [dict(head, text="Item"), dict(head, text="Subject & discussion"),
         dict(head, text="Agreed action"), dict(head, text="Owner"),
         dict(head, text="Affects"), dict(head, text="Due"), dict(head, text="Status")],
    ]
    for item in items:
        rows.append([
            {"text": str(item.get("ref") or ""), "size": 9, "valign": "top"},
            _subject_cell(item),
            {"text": str(item.get("agreement") or ""), "size": 9, "valign": "top"},
            {"text": _owner(item), "size": 9, "valign": "top"},
            {"text": item.get("impact_name") or impact_name(item.get("impact")),
             "size": 9, "valign": "top"},
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
        # The issue date belongs under the signature it dates, on the right,
        # rather than under the name on the left.
        [dict(field, text=""),
         dict(field, text=""),
         dict(field, text="Issue date:"),
         dict(field, text=issued or "", underline=True)],
    ]


def _attachment_note(attachments: Sequence[Mapping[str, Any]],
                     typed: str = "") -> list[str]:
    """The lines that say what is attached, as the last thing in the minutes."""
    named = [str(a.get("name") or a.get("filename") or "Attachment").strip()
             for a in attachments]
    if typed.strip() and typed.strip() not in named:
        named.append(typed.strip())
    if not named:
        return []
    if len(named) == 1:
        return [f"Attachment: {named[0]}"]
    return ["Attachments:"] + [f"{n}. {name}" for n, name in enumerate(named, start=1)]


def _write(doc: Any, project: Mapping[str, Any], sheet: Mapping[str, Any],
           attachments: Sequence[Mapping[str, Any]]) -> Any:
    """The minutes, written into whichever document was handed in.

    One body for both formats: the Word writer and the PDF writer take the same
    calls and the same grids, so a change to the layout cannot reach one of them
    and not the other.
    """
    meeting = dict(sheet["meeting"])
    attendance = list(sheet.get("attendance") or [])
    items = list(sheet.get("items") or [])

    listed, marked = who_was_there(attendance)
    doc.add_grid(DETAILS_GRID, _details(project, meeting, listed, marked), indent=-34)
    if not listed:
        doc.add_paragraph("No attendees recorded.", style="Caption")
    elif marked:
        doc.add_paragraph("* Present at this meeting", style="Caption")

    # The attendance and the details are the cover: the minutes themselves start
    # on the page after, the way the practice issues them.
    doc.add_page_break()

    if items:
        doc.add_grid(ITEMS_GRID, _items_table(items))
    else:
        doc.add_paragraph("No items were minuted for this meeting.", italic=True)

    if str(meeting.get("notes") or "").strip():
        doc.add_heading("Notes", 2)
        doc.add_paragraph(meeting["notes"])

    for line in _attachment_note(attachments, str(meeting.get("attachment") or "")):
        doc.add_paragraph(line, style="Caption")

    doc.add_paragraph("", style="Caption")
    doc.add_grid(SIGNATURE_GRID,
                 _signature_block("Prepared by:", str(meeting.get("prepared_by") or ""),
                                  to_display(meeting.get("issue_date"))),
                 borders=False)
    doc.add_grid(SIGNATURE_GRID,
                 # The reviewer signs and dates it themselves, so both are rules.
                 _signature_block("Reviewed & Accepted by:",
                                  str(meeting.get("reviewed_by") or ""), ""),
                 borders=False)
    return doc


def minutes_document(project: Mapping[str, Any], sheet: Mapping[str, Any],
                     attachments: Sequence[Mapping[str, Any]] = ()) -> bytes:
    """One meeting's minutes as a Word document, on the practice's template.

    The attachments are named here but not embedded: a PDF does not go inside a
    .docx in any way a client can open. The exported PDF carries them.
    """
    project = dict(project)          # a database row does not answer .get()
    meeting = dict(sheet["meeting"])
    title = str(meeting.get("title") or "").strip() or "Minutes of meeting"
    doc = Document(
        title=f"{project.get('code')} — {title}",
        heading=HEADING,
        logo=letterhead_logo(),
        # The issued minutes carry the form code and the page number, and
        # nothing else: the project is named on the first page, and repeating
        # it at the foot of every one is a line nobody reads.
        footer_code=FORM_CODE,
    )
    _write(doc, project, sheet, attachments)
    return doc.render()


def minutes_pdf(project: Mapping[str, Any], sheet: Mapping[str, Any],
                attachments: Sequence[Mapping[str, Any]] = ()) -> bytes:
    """The same minutes as a PDF, with whatever is attached stapled on the end.

    Built rather than printed, so what the client opens is the document itself
    — the same letterhead, the same grids, the same signature blocks — instead
    of a screen with a browser's own margins around it.
    """
    from .pdf import Document as PdfDocument, join

    project = dict(project)
    meeting = dict(sheet["meeting"])
    title = str(meeting.get("title") or "").strip() or "Minutes of meeting"
    doc = PdfDocument(
        title=f"{project.get('code')} — {title}",
        heading=HEADING,
        logo=letterhead_logo(),
        footer_code=FORM_CODE,
    )
    _write(doc, project, sheet, attachments)
    minutes = doc.render()

    files = [a.get("content") for a in attachments if a.get("content")]
    return join(minutes, *files) if files else minutes


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


# --- the same minutes, from a Word template somebody else wrote --------------
#
# The layout above is written in code, which is fine until the practice moves a
# column or adds a line to the signature block — and then it is a change to the
# software, made by somebody who is not in the room. So the layout can come
# from a .docx instead: download the template, change it in Word, upload it
# back, and every Word export is built by filling it in.

# What a template may ask for, grouped as the page explains them. The values
# are what each one means, in the words somebody editing the template needs.
TEMPLATE_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "The project": (
        ("project.code", "The project number"),
        ("project.name", "The project name"),
        ("project.client", "The client"),
    ),
    "The meeting": (
        ("meeting.ref", "Its reference, like MOM-04"),
        ("meeting.title", "The subject"),
        ("meeting.purpose", "The purpose, or the subject where none is typed"),
        ("meeting.date", "The day it was held"),
        ("meeting.time", "The time it started"),
        ("meeting.location", "Where it was held"),
        ("meeting.chaired_by", "Who chaired it"),
        ("meeting.next_date", "When the next one is"),
        ("meeting.notes", "Any notes under the items"),
        ("meeting.attachments", "What is attached, as a list"),
        ("meeting.prepared_by", "Who prepared the minutes"),
        ("meeting.reviewed_by", "Who reviewed and accepted them"),
        ("meeting.issue_date", "The day they were issued"),
    ),
    "One row per person who attended": (
        ("attendee.no", "1, 2, 3 down the table"),
        ("attendee.name", "Their name"),
        ("attendee.organisation", "Who they work for"),
        ("attendee.role", "Their role"),
        ("attendee.trade", "The trade they cover"),
    ),
    "One row per item": (
        ("item.ref", "Its number, like 1.4"),
        ("item.subject", "The subject"),
        ("item.discussion", "What was discussed"),
        ("item.agreement", "What was agreed"),
        ("item.owner", "Who owns it"),
        ("item.trades", "The trades it touches"),
        ("item.affects", "What it affects"),
        ("item.due", "The action date"),
        ("item.status", "Open, overdue or closed"),
    ),
}


def template_values(project: Mapping[str, Any], sheet: Mapping[str, Any],
                    attachments: Sequence[Mapping[str, Any]] = ()) -> dict[str, str]:
    """Everything a template can put in a placeholder that is not a row."""
    project = dict(project)
    meeting = dict(sheet["meeting"])
    attached = _attachment_note(attachments, str(meeting.get("attachment") or ""))
    return {
        "project.code": str(project.get("code") or ""),
        "project.name": str(project.get("name") or ""),
        "project.client": str(project.get("client") or ""),
        "meeting.ref": str(meeting.get("ref") or ""),
        "meeting.title": str(meeting.get("title") or ""),
        "meeting.purpose": str(meeting.get("purpose") or meeting.get("title") or ""),
        "meeting.date": to_display(meeting.get("meeting_date")) or "",
        "meeting.time": str(meeting.get("meeting_time") or ""),
        "meeting.location": str(meeting.get("location") or ""),
        "meeting.chaired_by": str(meeting.get("chaired_by") or ""),
        "meeting.next_date": to_display(meeting.get("next_date")) or "",
        "meeting.notes": str(meeting.get("notes") or ""),
        "meeting.attachments": "\n".join(attached),
        "meeting.prepared_by": str(meeting.get("prepared_by") or ""),
        "meeting.reviewed_by": str(meeting.get("reviewed_by") or ""),
        "meeting.issue_date": to_display(meeting.get("issue_date")) or "",
    }


def template_rows(sheet: Mapping[str, Any]) -> dict[str, list[dict[str, str]]]:
    """The repeating rows: who was there, and what was minuted."""
    listed, marked = who_was_there(list(sheet.get("attendance") or []))
    people = []
    for number, person in enumerate(listed, start=1):
        mark = "*" if marked and person.get("present") else ""
        people.append({
            "no": f"{number}{mark}",
            "name": str(person.get("name") or ""),
            "organisation": str(person.get("organisation") or ""),
            "role": str(person.get("job_title") or ""),
            "trade": str(person.get("trade_name") or ""),
        })

    items = []
    for item in sheet.get("items") or ():
        items.append({
            "ref": str(item.get("ref") or ""),
            "subject": str(item.get("subject") or ""),
            "discussion": str(item.get("discussion") or ""),
            "agreement": str(item.get("agreement") or ""),
            "owner": _owner(item),
            "trades": trade_names(item) or "",
            "affects": item.get("impact_name") or impact_name(item.get("impact")),
            "due": to_display(item.get("due_date")) or "",
            "status": _status(item),
        })
    return {"attendee": people, "item": items}


def minutes_from_template(template: bytes, project: Mapping[str, Any],
                          sheet: Mapping[str, Any],
                          attachments: Sequence[Mapping[str, Any]] = ()) -> bytes:
    """One meeting's minutes, built by filling in the practice's own template."""
    from .doctemplate import fill

    return fill(template, template_values(project, sheet, attachments),
                template_rows(sheet))


def starter_template() -> bytes:
    """The template to download and edit: this layout, with placeholders in it.

    Built from the same writer and the same grids as the minutes themselves, so
    what arrives in Word is what the export looks like today — a starting point
    to change rather than a blank page to design.
    """
    label = {"bold": True, "size": 9}
    doc = Document(title="Minutes of meeting — template", heading=HEADING,
                   logo=letterhead_logo(), footer_code=FORM_CODE)

    details: list[list[Any]] = [
        [dict(label, text="Project:"),
         {"text": "{{project.code}} — {{project.name}} · {{project.client}}",
          "span": 5, "bold": True, "size": 9}],
        [dict(label, text="Reference"), {"text": "{{meeting.ref}}", "span": 5, "size": 9}],
        [dict(label, text="Purpose:"), {"text": "{{meeting.purpose}}", "span": 2, "size": 9},
         dict(label, text="Date:"), {"text": "{{meeting.date}}", "span": 2, "size": 9}],
        [dict(label, text="Location:"), {"text": "{{meeting.location}}", "span": 2, "size": 9},
         dict(label, text="Time:"), {"text": "{{meeting.time}}", "span": 2, "size": 9}],
        [{"text": "", "fill": BAND_FILL, "repeat": True},
         {"text": "Name", "fill": BAND_FILL, "bold": True, "size": 9},
         {"text": "Organization", "fill": BAND_FILL, "bold": True, "size": 9},
         {"text": "Role", "fill": BAND_FILL, "bold": True, "size": 9},
         {"text": "Trade", "fill": BAND_FILL, "bold": True, "size": 9, "span": 2}],
        # This row repeats: one per person who attended.
        [{"text": "{{attendee.no}}", "align": "center", "size": 9},
         {"text": "{{attendee.name}}", "size": 9},
         {"text": "{{attendee.organisation}}", "size": 9},
         {"text": "{{attendee.role}}", "size": 9},
         {"text": "{{attendee.trade}}", "size": 9, "span": 2}],
    ]
    doc.add_grid(DETAILS_GRID, details, indent=-34)
    doc.add_page_break()

    head = {"fill": HEAD_FILL, "bold": True, "size": 9, "repeat": True}
    items: list[list[Any]] = [
        [{"text": "Items and Agreement", "span": 7, "fill": HEAD_FILL, "bold": True,
          "size": 10, "align": "center", "repeat": True}],
        [dict(head, text="Item"), dict(head, text="Subject & discussion"),
         dict(head, text="Agreed action"), dict(head, text="Owner"),
         dict(head, text="Affects"), dict(head, text="Due"), dict(head, text="Status")],
        # This row repeats: one per item.
        [{"text": "{{item.ref}}", "size": 9, "valign": "top"},
         {"lead": "{{item.subject}}", "text": "{{item.discussion}}", "size": 9, "valign": "top"},
         {"text": "{{item.agreement}}", "size": 9, "valign": "top"},
         {"text": "{{item.owner}}", "size": 9, "valign": "top"},
         {"text": "{{item.affects}}", "size": 9, "valign": "top"},
         {"text": "{{item.due}}", "size": 9, "valign": "top"},
         {"text": "{{item.status}}", "size": 9, "valign": "top"}],
    ]
    doc.add_grid(ITEMS_GRID, items)
    doc.add_paragraph("{{meeting.notes}}")
    doc.add_paragraph("{{meeting.attachments}}", style="Caption")

    doc.add_paragraph("", style="Caption")
    doc.add_grid(SIGNATURE_GRID,
                 _signature_block("Prepared by:", "{{meeting.prepared_by}}",
                                  "{{meeting.issue_date}}"), borders=False)
    doc.add_grid(SIGNATURE_GRID,
                 _signature_block("Reviewed & Accepted by:", "{{meeting.reviewed_by}}", ""),
                 borders=False)
    return doc.render()
