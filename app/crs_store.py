"""Comment response sheets, in the database the rest of the project is in.

This is the layer between the arithmetic in :mod:`app.crs_sheet`, the client's
own workbook in :mod:`app.crs_excel`, and the four tables :func:`app.db.init_db`
makes. Nothing here draws anything; the views do that.

Three things it is worth being clear about, because they are the reason the
sheets moved out of a browser and into here.

**A sheet is about a real document.** It can point at a submittal in the
register — the drawing or report that actually went out, with the number the
register gave it — and through that at the deliverable the programme costed. So
"what is still owed on this submission" is a question with an answer, rather
than a filename in somebody's downloads.

**A comment is owed by a real trade.** The client writes a discipline in their
own words; that is matched to one of the project's trades on the way in and
kept beside what they wrote, so the resource plan can see the work.

**The client's own workbook is kept.** A sheet that arrived as a file keeps that
file, byte for byte, and the answers are written back into it on the way out.
What the client gets back is their form, not our rendering of it.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Iterable, Mapping, Sequence

from . import crs_excel
from .crs_sheet import (
    CODES, DEFAULT_DUE_DAYS, OPEN, blank_sheet, default_due, is_late, match_trade,
    normalise_code, overdue_days, tally, today, when, worst_code,
)
from .dates import from_input
from .db import execute, insert, query, query_one

# What a sheet is, and what a comment is, as far as a form is concerned.
SHEET_FIELDS = ("submittal_id", "task_id", "title", "revision", "report_no",
                "report_date", "contract_no", "drf_ref", "drf_rev", "drf_date",
                "stage", "engineer", "contractor", "due_days", "received_on",
                "closed_on", "note")

COMMENT_FIELDS = ("sn", "reviewer", "source", "observation", "reference",
                  "trade_id", "discipline", "returned_code", "response",
                  "signoff", "due_date", "closed_on")

# The columns anybody answering a comment may change from the sheet itself.
# Not the observation: that is the client's words, and editing a comment is not
# answering it.
EDITABLE = ("response", "returned_code", "signoff", "trade_id", "due_date",
            "sn", "reviewer", "source", "observation", "reference", "discipline")

# Where the client's own workbook is kept for a sheet — one file, replaced when
# a newer one is uploaded.
ORIGINAL = "original"


class CrsError(ValueError):
    """Something a person did that cannot be done, said in words they can read."""


# --- reading ----------------------------------------------------------------

def _rows(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def sheet(sheet_id: int, project_id: int | None = None) -> dict[str, Any] | None:
    """One sheet, with the document it is about where there is one."""
    row = query_one(
        """
        SELECT s.*, b.number AS submittal_number, b.title AS submittal_title,
               b.revision AS submittal_revision, t.wbs AS task_wbs, t.name AS task_name
        FROM crs_sheets s
        LEFT JOIN submittals b ON b.id = s.submittal_id
        LEFT JOIN tasks t ON t.id = s.task_id
        WHERE s.id = ?
        """,
        (int(sheet_id),),
    )
    if row is None:
        return None
    made = dict(row)
    if project_id is not None and int(made["project_id"]) != int(project_id):
        return None
    return made


def comments_for(sheet_id: int) -> list[dict[str, Any]]:
    """A sheet's comments, in the order the client wrote them."""
    return _rows(query(
        """
        SELECT c.*, t.name AS trade_name, t.color AS trade_color,
               (SELECT COUNT(*) FROM crs_messages m WHERE m.comment_id = c.id) AS replies,
               (SELECT COUNT(*) FROM crs_files f WHERE f.comment_id = c.id) AS files
        FROM crs_comments c
        LEFT JOIN trades t ON t.id = c.trade_id
        WHERE c.sheet_id = ?
        ORDER BY c.sort_order, c.id
        """,
        (int(sheet_id),),
    ))


def sheets_for(project_id: int) -> list[dict[str, Any]]:
    """Every sheet on a project, each with how it stands.

    Counted here rather than in SQL because what "late" means is a rule in
    :mod:`app.crs_sheet`, and a rule stated twice is a rule that will disagree
    with itself.
    """
    sheets = _rows(query(
        """
        SELECT s.*, b.number AS submittal_number, b.title AS submittal_title,
               t.wbs AS task_wbs, t.name AS task_name
        FROM crs_sheets s
        LEFT JOIN submittals b ON b.id = s.submittal_id
        LEFT JOIN tasks t ON t.id = s.task_id
        WHERE s.project_id = ?
        ORDER BY IFNULL(NULLIF(s.received_on, ''), s.created_at) DESC, s.id DESC
        """,
        (int(project_id),),
    ))
    if not sheets:
        return []

    held: dict[int, list[dict[str, Any]]] = {int(row["id"]): [] for row in sheets}
    for row in query(
        "SELECT sheet_id, returned_code, signoff, due_date FROM crs_comments "
        "WHERE sheet_id IN (SELECT id FROM crs_sheets WHERE project_id = ?)",
        (int(project_id),),
    ):
        held.setdefault(int(row["sheet_id"]), []).append(dict(row))

    for row in sheets:
        rows = held.get(int(row["id"]), [])
        row.update(tally(rows))
        row["code"] = worst_code(rows)
        row["code_said"] = CODES.get(row["code"], "")
    return sheets


def overview(project_id: int) -> dict[str, Any]:
    """How the project stands across every sheet on it."""
    rows = _rows(query(
        "SELECT returned_code, signoff, due_date, response FROM crs_comments "
        "WHERE sheet_id IN (SELECT id FROM crs_sheets WHERE project_id = ?)",
        (int(project_id),),
    ))
    counted = tally(rows)
    counted["sheets"] = int(query_one(
        "SELECT COUNT(*) AS n FROM crs_sheets WHERE project_id = ?", (int(project_id),))["n"])
    return counted


def trades_of(project_id: int) -> list[dict[str, Any]]:
    return _rows(query(
        "SELECT id, name, color, office FROM trades WHERE project_id = ? ORDER BY sort_order, id",
        (int(project_id),)))


def submittals_of(project_id: int) -> list[dict[str, Any]]:
    """The documents a sheet can be about: what the register says went out."""
    return _rows(query(
        """
        SELECT b.id, b.number, b.title, b.revision, b.task_id, t.name AS task_name
        FROM submittals b LEFT JOIN tasks t ON t.id = b.task_id
        WHERE b.project_id = ?
        ORDER BY b.number, b.id
        """,
        (int(project_id),)))


# --- writing ----------------------------------------------------------------

def _clean(fields: Mapping[str, Any], allowed: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in allowed:
        if name not in fields:
            continue
        value = fields[name]
        if name in ("submittal_id", "task_id", "trade_id"):
            out[name] = int(value) if str(value or "").strip() not in ("", "0", "None") else None
        elif name == "due_days":
            out[name] = max(0, int(value or DEFAULT_DUE_DAYS))
        elif name == "returned_code":
            out[name] = normalise_code(value)
        elif name == "signoff":
            out[name] = "closed" if str(value or "").strip().lower() in ("closed", "1", "true") else OPEN
        elif name.endswith("_date") or name.endswith("_on"):
            # dd/mm/yyyy is what the app's own fields hand over; a workbook
            # hands over something else again. Both have to land as one date.
            out[name] = from_input(value) or when(value)
        else:
            out[name] = str(value or "").strip()
    return out


def _or_blank(made: Mapping[str, Any], name: str) -> Any:
    """What to store for a column nobody filled in.

    Everything but the three that point at something else is text and declared
    NOT NULL, because a comment with no reviewer on it has no reviewer rather
    than an unknown one.
    """
    value = made.get(name)
    if value is None and name not in ("trade_id", "task_id", "submittal_id"):
        return ""
    return value


def create_sheet(project_id: int, **fields: Any) -> int:
    """A sheet with nothing on it yet."""
    made = blank_sheet(int(project_id))
    made.update(_clean(fields, SHEET_FIELDS))
    names = ["project_id"] + list(SHEET_FIELDS)
    return insert(
        f"INSERT INTO crs_sheets ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        [int(project_id)] + [_or_blank(made, name) for name in SHEET_FIELDS],
    )


def update_sheet(sheet_id: int, **fields: Any) -> None:
    changing = _clean(fields, SHEET_FIELDS)
    if not changing:
        return
    sets = ", ".join(f"{name} = ?" for name in changing)
    execute(f"UPDATE crs_sheets SET {sets}, updated_at = datetime('now') WHERE id = ?",
            list(changing.values()) + [int(sheet_id)])


def delete_sheet(sheet_id: int) -> None:
    execute("DELETE FROM crs_sheets WHERE id = ?", (int(sheet_id),))


def add_comment(sheet_id: int, **fields: Any) -> int:
    """One more comment on a sheet, at the bottom of it."""
    made = _clean(fields, COMMENT_FIELDS)
    row = query_one("SELECT * FROM crs_sheets WHERE id = ?", (int(sheet_id),))
    if row is None:
        raise CrsError("That sheet no longer exists.")
    made.setdefault("signoff", OPEN)
    if not made.get("due_date"):
        made["due_date"] = default_due(dict(row))
    last = query_one("SELECT IFNULL(MAX(sort_order), 0) AS n FROM crs_comments WHERE sheet_id = ?",
                     (int(sheet_id),))
    order = int(last["n"]) + 1
    if not made.get("sn"):
        made["sn"] = str(order)

    names = ["sheet_id", "sort_order"] + list(COMMENT_FIELDS)
    values = [int(sheet_id), order] + [_or_blank(made, name) for name in COMMENT_FIELDS]
    return insert(
        f"INSERT INTO crs_comments ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        values)


def set_comment(comment_id: int, **fields: Any) -> dict[str, Any]:
    """Change what can be changed on a comment, and hand the row back.

    Signing a comment off dates it, and re-opening one clears that date: the
    day something was closed is a fact about the closing, not a field somebody
    should have to keep in step by hand.
    """
    changing = _clean(fields, EDITABLE)
    if not changing:
        raise CrsError("There is nothing there to change.")
    if "signoff" in changing:
        changing["closed_on"] = today() if changing["signoff"] == "closed" else ""

    sets = ", ".join(f"{name} = ?" for name in changing)
    execute(f"UPDATE crs_comments SET {sets}, updated_at = datetime('now') WHERE id = ?",
            list(changing.values()) + [int(comment_id)])
    row = query_one("SELECT * FROM crs_comments WHERE id = ?", (int(comment_id),))
    if row is None:
        raise CrsError("That comment no longer exists.")
    return dict(row)


def delete_comment(comment_id: int) -> None:
    execute("DELETE FROM crs_comments WHERE id = ?", (int(comment_id),))


def close_what_is_answered(sheet_id: int) -> int:
    """Sign off every comment that has an answer written against it."""
    cursor = execute(
        "UPDATE crs_comments SET signoff = 'closed', closed_on = ?, "
        "updated_at = datetime('now') WHERE sheet_id = ? AND signoff <> 'closed' "
        "AND TRIM(response) <> ''",
        (today(), int(sheet_id)))
    return int(cursor.rowcount or 0)


# --- the thread against a comment -------------------------------------------

def messages_for(comment_id: int) -> list[dict[str, Any]]:
    return _rows(query(
        "SELECT m.*, (SELECT COUNT(*) FROM crs_files f WHERE f.message_id = m.id) AS files "
        "FROM crs_messages m WHERE m.comment_id = ? ORDER BY m.id",
        (int(comment_id),)))


def threads_for(sheet_id: int) -> dict[int, list[dict[str, Any]]]:
    """Every thread on a sheet at once, so drawing it is one query and not forty."""
    held: dict[int, list[dict[str, Any]]] = {}
    for row in query(
        "SELECT m.* FROM crs_messages m JOIN crs_comments c ON c.id = m.comment_id "
        "WHERE c.sheet_id = ? ORDER BY m.id", (int(sheet_id),)
    ):
        held.setdefault(int(row["comment_id"]), []).append(dict(row))
    return held


def add_message(comment_id: int, body: str, user: Mapping[str, Any] | None = None,
                role: str = "", published: bool = True) -> int:
    said = str(body or "").strip()
    if not said:
        raise CrsError("There is nothing to say there.")
    # A signed-in user arrives as a database row, which is a mapping that has
    # no .get on it.
    who = dict(user) if user is not None else {}
    return insert(
        "INSERT INTO crs_messages (comment_id, user_id, author, role, body, published) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (int(comment_id), who.get("id"), str(who.get("name") or ""),
         str(role or ""), said, 1 if published else 0))


# --- files ------------------------------------------------------------------

def attach(*, name: str, mimetype: str, content: bytes,
           comment_id: int | None = None, message_id: int | None = None,
           sheet_id: int | None = None, user_name: str = "") -> int:
    """A photo, a marked-up PDF, the workbook a sheet arrived on.

    Kept in the database rather than beside it, for the same reason the minutes'
    attachments are: the nightly backup uploads the database, and a file in a
    folder next to it is one that does not come back.
    """
    if not content:
        raise CrsError("That file is empty.")
    return insert(
        "INSERT INTO crs_files (comment_id, message_id, sheet_id, name, mimetype, "
        "bytes, content, user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (comment_id, message_id, sheet_id, str(name or "file"), str(mimetype or ""),
         len(content), sqlite3.Binary(content), str(user_name or "")))


def file(file_id: int) -> dict[str, Any] | None:
    row = query_one("SELECT * FROM crs_files WHERE id = ?", (int(file_id),))
    return dict(row) if row else None


def files_for(sheet_id: int) -> list[dict[str, Any]]:
    """What is attached anywhere on a sheet, without the contents."""
    return _rows(query(
        """
        SELECT f.id, f.name, f.mimetype, f.bytes, f.user_name, f.made_at,
               f.comment_id, f.message_id, f.sheet_id
        FROM crs_files f
        LEFT JOIN crs_comments c ON c.id = f.comment_id
        LEFT JOIN crs_messages m ON m.id = f.message_id
        WHERE f.sheet_id = ? OR c.sheet_id = ?
           OR m.comment_id IN (SELECT id FROM crs_comments WHERE sheet_id = ?)
        ORDER BY f.id
        """,
        (int(sheet_id), int(sheet_id), int(sheet_id))))


def original(sheet_id: int) -> dict[str, Any] | None:
    """The workbook a sheet came in on, where it came in on one."""
    row = query_one(
        "SELECT * FROM crs_files WHERE sheet_id = ? AND name = ? ORDER BY id DESC LIMIT 1",
        (int(sheet_id), ORIGINAL))
    return dict(row) if row else None


# --- the client's workbook, in and out --------------------------------------

def read_workbook(data: bytes) -> dict[str, Any]:
    """The uploaded form, or a refusal somebody can act on."""
    try:
        return crs_excel.read(data)
    except crs_excel.SheetError as exc:
        raise CrsError(str(exc)) from exc


def import_workbook(project_id: int, data: bytes, *, submittal_id: int | None = None,
                    sheet_id: int | None = None) -> int:
    """A client's form, as a sheet with its comments against the project's trades.

    Uploading onto a sheet that already exists replaces its comments, because
    what arrived is the register as the client now holds it — a second file is
    a revision of the first, not more rows to add to it. The answers already
    written here are kept against the comments they answer, matched on the
    client's own numbering.
    """
    form = read_workbook(data)
    trades = trades_of(project_id)
    info = form["info"]

    fields = {name: info.get(name, "") for name in
              ("report_no", "report_date", "contract_no", "drf_ref", "drf_rev",
               "drf_date", "stage", "engineer", "contractor")}
    fields["title"] = info.get("title", "")
    fields["revision"] = info.get("drf_rev", "")
    if submittal_id:
        fields["submittal_id"] = submittal_id

    if sheet_id:
        kept = {str(row["sn"] or "").strip().lower(): row
                for row in comments_for(sheet_id) if str(row["sn"] or "").strip()}
        update_sheet(sheet_id, **fields)
        execute("DELETE FROM crs_comments WHERE sheet_id = ?", (int(sheet_id),))
    else:
        kept = {}
        fields.setdefault("received_on", info.get("report_date", "") or today())
        sheet_id = create_sheet(project_id, **fields)

    row = dict(query_one("SELECT * FROM crs_sheets WHERE id = ?", (int(sheet_id),)))
    due = default_due(row)

    for order, comment in enumerate(form["comments"], start=1):
        was = kept.get(str(comment.get("sn") or "").strip().lower(), {})
        trade_id = match_trade(comment.get("discipline"), trades) or was.get("trade_id")
        values = {
            "sn": comment.get("sn", "") or str(order),
            "reviewer": comment.get("reviewer", ""),
            "source": comment.get("source", ""),
            "observation": comment.get("observation", ""),
            "reference": comment.get("reference", ""),
            "discipline": comment.get("discipline", ""),
            "trade_id": trade_id,
            # Ours, where the client's form does not carry one: an answer
            # already written here is not lost because they sent the sheet again.
            "returned_code": comment.get("returned_code") or was.get("returned_code", ""),
            "response": comment.get("response") or was.get("response", ""),
            "signoff": comment.get("signoff") or was.get("signoff") or OPEN,
            "due_date": was.get("due_date") or due,
            "closed_on": was.get("closed_on", ""),
        }
        made = _clean(values, COMMENT_FIELDS)
        names = ["sheet_id", "sort_order"] + list(COMMENT_FIELDS)
        execute(f"INSERT INTO crs_comments ({', '.join(names)}) "
                f"VALUES ({', '.join('?' * len(names))})",
                [int(sheet_id), order] + [_or_blank(made, name) for name in COMMENT_FIELDS])

    # The file itself, so what goes back out is the client's own workbook.
    execute("DELETE FROM crs_files WHERE sheet_id = ? AND name = ?", (int(sheet_id), ORIGINAL))
    attach(name=ORIGINAL, mimetype=crs_excel.MIMETYPE, content=data, sheet_id=int(sheet_id))
    return int(sheet_id)


def export_workbook(sheet_id: int) -> tuple[bytes, str]:
    """The sheet as a workbook, and what to call the file.

    Written onto the form it arrived on where there is one, and onto the blank
    form where the sheet was raised here. Either way it is the client's layout,
    their letterhead and their columns — the only difference is whose words are
    in the left-hand ones.
    """
    row = sheet(sheet_id)
    if row is None:
        raise CrsError("That sheet no longer exists.")

    held = original(sheet_id)
    authored = held is None
    data = held["content"] if held else crs_excel.blank_form()
    form = read_workbook(bytes(data))

    rows = comments_for(sheet_id)
    comments = [{
        "row": 0,
        "sn": row_["sn"], "reviewer": row_["reviewer"], "source": row_["source"],
        "observation": row_["observation"], "discipline": row_["discipline"],
        "reference": row_["reference"], "returned_code": row_["returned_code"],
        "response": row_["response"], "signoff": row_["signoff"],
    } for row_ in rows]

    # Where the client's own rows are, so an answer lands on the comment it
    # answers even when somebody has added rows here since.
    where = {str(one.get("sn") or "").strip().lower(): one.get("row")
             for one in form["comments"]}
    for one in comments:
        one["row"] = where.get(str(one["sn"]).strip().lower(), 0) or 0

    info = {name: row.get(name, "") for name in
            ("report_no", "report_date", "contract_no", "drf_ref", "drf_rev",
             "drf_date", "stage", "engineer", "contractor")}
    info["title"] = row.get("title", "")

    made = crs_excel.write(bytes(data), comments, form["header_row"], form["columns"],
                           info=info if authored else None,
                           info_at=form["info_at"],
                           overall=worst_code(rows), overall_at=form["overall_at"],
                           authored=authored)
    name = (row.get("drf_ref") or row.get("report_no") or row.get("title")
            or f"sheet-{sheet_id}")
    safe = "".join(ch if ch.isalnum() or ch in "-_. " else "-" for ch in str(name)).strip()
    return made, f"{safe or 'comment-response'}.xlsx"


# --- what the programme should feel -----------------------------------------

def sheet_is_rework(sheet_id: int) -> dict[str, Any]:
    """Whether a sheet sends its submission round again, and what it costs.

    A Code C or D is the programme's business, not just the sheet's: the
    deliverable goes to another revision. This says so; recording it against the
    deliverable is the register's job and is done from the view.
    """
    rows = comments_for(sheet_id)
    code = worst_code(rows)
    counted = tally(rows)
    return {
        "code": code,
        "said": CODES.get(code, ""),
        "sends_it_back": code in ("C", "D"),
        "open": counted["open"],
        "late": counted["late"],
        "comments": counted["comments"],
    }


def late_everywhere(project_id: int) -> list[dict[str, Any]]:
    """Every comment on the project still owed past its date, worst first."""
    rows = _rows(query(
        """
        SELECT c.*, s.title AS sheet_title, s.id AS sheet, t.name AS trade_name
        FROM crs_comments c
        JOIN crs_sheets s ON s.id = c.sheet_id
        LEFT JOIN trades t ON t.id = c.trade_id
        WHERE s.project_id = ?
        ORDER BY c.due_date
        """,
        (int(project_id),)))
    owed = [row for row in rows if is_late(row)]
    for row in owed:
        row["overdue"] = overdue_days(row)
    return owed
