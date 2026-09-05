"""Loading and roll-up helpers that sit between the database and the views."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

from .calc import build_period_report, build_s_curve, compute_project, parse_date, to_iso
from .workflow import CODE_A, default_steps, is_submitted, percent_for, step_by_key
from .db import execute, get_db, insert, query, query_one


def today() -> str:
    return date.today().isoformat()


def as_dict(row: Any) -> dict[str, Any]:
    """sqlite3.Row supports item access but not .get(), which the calculation
    engine relies on, so rows are converted before they cross that boundary."""
    return row if isinstance(row, dict) else dict(row)


def load_tasks(project_id: int) -> list[dict[str, Any]]:
    """Deliverables for a project, each with its trade allocations by trade id."""
    tasks = [
        dict(row)
        for row in query(
            """
            SELECT t.*, s.name AS section_name, s.code AS section_code, s.sort_order AS section_order
            FROM tasks t
            LEFT JOIN sections s ON s.id = t.section_id
            WHERE t.project_id = ?
            ORDER BY COALESCE(s.sort_order, 999), t.sort_order, t.id
            """,
            (project_id,),
        )
    ]
    allocations = query(
        """
        SELECT a.task_id, a.trade_id, a.pct
        FROM task_allocations a
        JOIN tasks t ON t.id = a.task_id
        WHERE t.project_id = ?
        """,
        (project_id,),
    )
    by_task: dict[int, dict[int, float]] = {}
    for row in allocations:
        by_task.setdefault(row["task_id"], {})[row["trade_id"]] = row["pct"]
    for task in tasks:
        task["allocations"] = by_task.get(task["id"], {})
    return tasks


def load_trades(project_id: int) -> list[dict[str, Any]]:
    return [dict(r) for r in query("SELECT * FROM trades WHERE project_id = ? ORDER BY sort_order, id", (project_id,))]


def load_steps(project_id: int) -> list[dict[str, Any]]:
    """The project's workflow steps, in progress order."""
    rows = [
        dict(r)
        for r in query("SELECT * FROM workflow_steps WHERE project_id = ? ORDER BY percent, sort_order, id", (project_id,))
    ]
    return rows


def load_sections(project_id: int) -> list[dict[str, Any]]:
    return [dict(r) for r in query("SELECT * FROM sections WHERE project_id = ? ORDER BY sort_order, id", (project_id,))]


def spent_hours_by_trade(project_id: int, data_date: str) -> dict[int, float]:
    """Hours booked per trade, up to and including the data date."""
    rows = query(
        """
        SELECT trade_id, SUM(hours) AS hours
        FROM time_entries
        WHERE project_id = ? AND entry_date <= ?
        GROUP BY trade_id
        """,
        (project_id, data_date),
    )
    return {r["trade_id"]: r["hours"] for r in rows if r["trade_id"] is not None}


def unallocated_hours(project_id: int, data_date: str) -> float:
    row = query_one(
        """
        SELECT COALESCE(SUM(hours), 0) AS hours
        FROM time_entries
        WHERE project_id = ? AND entry_date <= ? AND trade_id IS NULL
        """,
        (project_id, data_date),
    )
    return float(row["hours"])


def load_progress_history(project_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in query(
            "SELECT task_id, actual_pct, data_date FROM progress_updates WHERE project_id = ? ORDER BY data_date, id",
            (project_id,),
        )
    ]


def project_snapshot(project: Mapping[str, Any], data_date: str | None = None,
                     horizon_days: int | None = 30) -> dict[str, Any]:
    """The full computed view of a project at a data date."""
    project = as_dict(project)
    iso = to_iso(data_date or today())
    project_id = project["id"]
    snapshot = compute_project(
        project,
        load_tasks(project_id),
        load_trades(project_id),
        iso,
        horizon_days=horizon_days,
        spent_by_trade=spent_hours_by_trade(project_id, iso),
        steps=load_steps(project_id),
    )

    # Hours booked without a trade still count against the project total.
    loose = unallocated_hours(project_id, iso)
    budget = snapshot["budget"]
    budget["unallocated_hours"] = loose
    budget["spent_hours"] += loose
    budget["remaining_hours"] = budget["budget_hours"] - budget["spent_hours"]
    budget["hours_used_pct"] = budget["spent_hours"] / budget["budget_hours"] if budget["budget_hours"] > 0 else 0.0
    return snapshot


def project_s_curve(project: Mapping[str, Any], data_date: str | None = None, samples: int = 40) -> list[dict[str, Any]]:
    project = as_dict(project)
    return build_s_curve(
        project,
        load_tasks(project["id"]),
        load_progress_history(project["id"]),
        to_iso(data_date or today()),
        steps=load_steps(project["id"]),
        samples=samples,
    )


def project_period(project: Mapping[str, Any], start: str, end: str) -> dict[str, Any]:
    project = as_dict(project)
    return build_period_report(
        project,
        load_tasks(project["id"]),
        load_trades(project["id"]),
        load_progress_history(project["id"]),
        start,
        end,
        steps=load_steps(project["id"]),
    )


def portfolio_card(project: Mapping[str, Any], data_date: str | None = None) -> dict[str, Any]:
    """The compact figures used by the portfolio list."""
    project = as_dict(project)
    snapshot = project_snapshot(project, data_date)
    totals, budget = snapshot["totals"], snapshot["budget"]
    end_date = max((t["due_date"] for t in snapshot["tasks"]), default=snapshot["ntp_date"])
    return {
        "id": project["id"],
        "code": project["code"],
        "name": project["name"],
        "client": project["client"],
        "status": project["status"],
        "ntp_date": project["ntp_date"],
        "duration_months": project["duration_months"],
        "end_date": end_date,
        "elapsed_months": snapshot["elapsed_months"],
        "time_elapsed_pct": snapshot["time_elapsed_pct"],
        "planned_progress": totals["planned_progress"],
        "earned_progress": totals["earned_progress"],
        "variance": totals["variance"],
        "spi": totals["spi"],
        "task_count": totals["task_count"],
        "complete_count": totals["complete_count"],
        "late_count": totals["late_count"],
        "upcoming_count": totals["upcoming_count"],
        "behind_count": totals["behind_count"],
        "budget_hours": budget["budget_hours"],
        "spent_hours": budget["spent_hours"],
        "hours_used_pct": budget["hours_used_pct"],
        "cpi": budget["cpi"],
        "budget_status": budget["budget_status"],
    }


def portfolio(user: Mapping[str, Any], data_date: str | None = None) -> dict[str, Any]:
    """Every project the user can see, plus a weighted roll-up."""
    from .auth import visible_project_ids

    ids = visible_project_ids(user)
    if not ids:
        return {"projects": [], "totals": _empty_totals()}

    placeholders = ",".join("?" for _ in ids)
    rows = query(f"SELECT * FROM projects WHERE id IN ({placeholders}) ORDER BY status, name", ids)
    cards = [portfolio_card(row, data_date) for row in rows]

    # Progress is weighted by each project's hour budget, so a large project
    # moves the portfolio number more than a small one.
    budget = sum(c["budget_hours"] for c in cards)
    spent = sum(c["spent_hours"] for c in cards)

    def weight(card: Mapping[str, Any]) -> float:
        return card["budget_hours"] / budget if budget > 0 else 1 / len(cards)

    return {
        "projects": cards,
        "totals": {
            "project_count": len(cards),
            "active_count": sum(1 for c in cards if c["status"] == "active"),
            "planned_progress": sum(c["planned_progress"] * weight(c) for c in cards),
            "earned_progress": sum(c["earned_progress"] * weight(c) for c in cards),
            "variance": sum(c["variance"] * weight(c) for c in cards),
            "late_count": sum(c["late_count"] for c in cards),
            "upcoming_count": sum(c["upcoming_count"] for c in cards),
            "behind_count": sum(c["behind_count"] for c in cards),
            "budget_hours": budget,
            "spent_hours": spent,
            "hours_used_pct": spent / budget if budget > 0 else 0.0,
        },
    }


def _empty_totals() -> dict[str, Any]:
    return {
        "project_count": 0, "active_count": 0, "planned_progress": 0.0, "earned_progress": 0.0,
        "variance": 0.0, "late_count": 0, "upcoming_count": 0, "behind_count": 0,
        "budget_hours": 0.0, "spent_hours": 0.0, "hours_used_pct": 0.0,
    }


class AllocationError(ValueError):
    """Raised when a deliverable's trade split does not add up to 100%."""


def set_allocations(task_id: int, project_id: int, allocations: Mapping[Any, float]) -> None:
    """Rewrites a deliverable's trade split, checking that it totals 100%."""
    valid = {t["id"] for t in load_trades(project_id)}
    entries = [(int(k), float(v)) for k, v in allocations.items() if int(k) in valid]
    total = sum(pct for _, pct in entries)
    if entries and abs(total - 1) > 0.005:
        raise AllocationError(f"The trade split must total 100% (currently {total * 100:.1f}%)")

    conn = get_db()
    with conn:  # one transaction; rolled back if anything raises
        conn.execute("DELETE FROM task_allocations WHERE task_id = ?", (task_id,))
        conn.executemany(
            "INSERT INTO task_allocations (task_id, trade_id, pct) VALUES (?, ?, ?)",
            [(task_id, trade_id, pct) for trade_id, pct in entries if pct > 0],
        )


def record_progress(task: Mapping[str, Any], actual_pct: float, note: str, data_date: str,
                    user_id: int, status_key: str | None = None) -> None:
    """Saves a new percent complete and keeps the previous value as history."""
    conn = get_db()
    with conn:
        if status_key is None:
            conn.execute(
                "UPDATE tasks SET actual_pct = ?, updated_at = datetime('now') WHERE id = ?",
                (actual_pct, task["id"]),
            )
        else:
            conn.execute(
                "UPDATE tasks SET actual_pct = ?, status_key = ?, updated_at = datetime('now') WHERE id = ?",
                (actual_pct, status_key, task["id"]),
            )
        conn.execute(
            """
            INSERT INTO progress_updates
                (task_id, project_id, user_id, previous_pct, actual_pct, note, data_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task["id"], task["project_id"], user_id, task["actual_pct"], actual_pct, note, data_date),
        )


class WorkflowError(ValueError):
    """Raised when a workflow action does not apply to a deliverable."""


def set_status(task: Mapping[str, Any], status_key: str, note: str, data_date: str,
               user_id: int, steps: Sequence[Mapping[str, Any]]) -> float:
    """Moves a deliverable to a workflow step. The step decides the percentage.

    Reaching the final step closes the open revision as approved.
    """
    if status_key and step_by_key(steps, status_key) is None:
        raise WorkflowError("That status does not exist on this project")

    percent = percent_for(steps, status_key) if status_key else 0.0
    label = (step_by_key(steps, status_key) or {}).get("name", "Not started")
    record_progress(task, percent, note or f"Status set to {label}", data_date, user_id, status_key=status_key)

    if status_key == CODE_A:
        _open_revision(task, close_as="code_a", outcome_date=data_date, user_id=user_id,
                       note=note, code="A")
    return percent


def _current_revision_row(task_id: int):
    return query_one(
        "SELECT * FROM task_revisions WHERE task_id = ? ORDER BY revision DESC, id DESC LIMIT 1", (task_id,)
    )


def _open_revision(task: Mapping[str, Any], close_as: str, outcome_date: str, user_id: int,
                   note: str, code: str = "") -> None:
    """Closes the deliverable's open revision with an outcome, creating the row
    for revision 0 if it was never recorded."""
    row = _current_revision_row(task["id"])
    if row is None:
        execute(
            """
            INSERT INTO task_revisions
                (task_id, project_id, revision, submission_date, outcome, outcome_date, note, user_id, code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (task["id"], task["project_id"], int(task["revision"] or 0), task["submission_date"],
             close_as, outcome_date, note, user_id, code),
        )
    elif row["outcome"] == "open":
        execute(
            "UPDATE task_revisions SET outcome = ?, outcome_date = ?, note = ?, code = ? WHERE id = ?",
            (close_as, outcome_date, note or row["note"], code or row["code"], row["id"]),
        )


REVIEW_CODES: tuple[tuple[str, str], ...] = (
    ("A", "Code A — approved"),
    ("B", "Code B — approved with comments, resubmit"),
    ("C", "Code C — not approved, resubmit"),
)
REWORK_CODES = ("B", "C")


def normalise_code(value: Any) -> str:
    """One of A, B or C, or blank when nothing was said."""
    text = str(value or "").strip().upper().replace("CODE", "").strip()
    return text if text in {code for code, _ in REVIEW_CODES} else ""


def record_comments(task: Mapping[str, Any], project: Mapping[str, Any], steps: Sequence[Mapping[str, Any]],
                    comments_date: str, new_submission_date: str, note: str, user_id: int,
                    code: str = "") -> dict[str, Any]:
    """Records that the client returned a Code B or C instead of a Code A.

    The deliverable moves to the next revision, drops back to the step the
    project nominates, and is rescheduled around a new submission date — so the
    schedule and the progress figures both follow the rework.
    """
    if not is_submitted(steps, str(task["status_key"] or "")):
        raise WorkflowError("Only a deliverable that has been submitted can receive comments")

    max_revisions = int(project["max_revisions"] or 10)
    revision = int(task["revision"] or 0) + 1
    if revision > max_revisions:
        raise WorkflowError(
            f"This deliverable has reached the limit of {max_revisions} revisions. "
            "Raise the limit on the Setup sheet, or escalate it."
        )

    if not new_submission_date:
        new_submission_date = to_iso(parse_date(comments_date) + timedelta(days=float(project["rework_days"] or 7)))

    reset_key = str(project["revision_reset_step"] or "")
    if step_by_key(steps, reset_key) is None:
        reset_key = ""
    percent = percent_for(steps, reset_key) if reset_key else 0.0
    reset_name = (step_by_key(steps, reset_key) or {}).get("name", "Not started")

    code = normalise_code(code) or "B"
    _open_revision(task, close_as="comments", outcome_date=comments_date, user_id=user_id,
                   note=note, code=code)

    conn = get_db()
    with conn:
        conn.execute(
            """
            UPDATE tasks SET revision = ?, submission_date = ?, status_key = ?, actual_pct = ?,
                   updated_at = datetime('now')
            WHERE id = ?
            """,
            (revision, new_submission_date, reset_key, percent, task["id"]),
        )
        conn.execute(
            """
            INSERT INTO progress_updates
                (task_id, project_id, user_id, previous_pct, actual_pct, note, data_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task["id"], task["project_id"], user_id, task["actual_pct"], percent,
             note or f"Comments received — revision {revision}", comments_date),
        )
        conn.execute(
            """
            INSERT INTO task_revisions
                (task_id, project_id, revision, submission_date, outcome, note, user_id, comments_date)
            VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (task["id"], task["project_id"], revision, new_submission_date, note, user_id,
             comments_date),
        )

    return {"revision": revision, "submission_date": new_submission_date, "reset_to": reset_name,
            "code": code}


def load_revisions(task_id: int) -> list[dict[str, Any]]:
    return [
        dict(r)
        for r in query(
            """
            SELECT r.*, u.name AS user_name
            FROM task_revisions r LEFT JOIN users u ON u.id = r.user_id
            WHERE r.task_id = ? ORDER BY r.revision, r.id
            """,
            (task_id,),
        )
    ]


def install_default_steps(project_id: int) -> None:
    """Gives a new project the default design workflow."""
    for step in default_steps():
        execute(
            """
            INSERT INTO workflow_steps (project_id, key, name, percent, anchor, offset_days, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, step["key"], step["name"], step["percent"],
             step["anchor"], step["offset_days"], step["sort_order"]),
        )


def next_sort_order(table: str, project_id: int) -> int:
    row = query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE project_id = ?", (project_id,))
    return int(row["n"]) + 1


# --- minutes of meeting ----------------------------------------------------

def load_attendees(project_id: int, include_inactive: bool = True) -> list[dict[str, Any]]:
    """The attendance roster, each person with their trade if they have one."""
    clause = "" if include_inactive else " AND a.active = 1"
    return [
        dict(r)
        for r in query(
            f"""
            SELECT a.*, tr.name AS trade_name, tr.color AS trade_color
            FROM attendees a
            LEFT JOIN trades tr ON tr.id = a.trade_id
            WHERE a.project_id = ?{clause}
            ORDER BY a.sort_order, a.id
            """,
            (project_id,),
        )
    ]


def load_meetings(project_id: int) -> list[dict[str, Any]]:
    """Meetings newest first, each with its attendance and item counts."""
    return [
        dict(r)
        for r in query(
            """
            SELECT m.*, u.name AS minuted_by,
                   (SELECT COUNT(*) FROM meeting_attendance ma
                     WHERE ma.meeting_id = m.id AND ma.present = 1) AS present_count,
                   (SELECT COUNT(*) FROM meeting_items i WHERE i.meeting_id = m.id) AS item_count,
                   (SELECT COUNT(*) FROM meeting_items i
                     WHERE i.meeting_id = m.id AND i.status = 'open') AS open_count
            FROM meetings m
            LEFT JOIN users u ON u.id = m.user_id
            WHERE m.project_id = ?
            ORDER BY m.meeting_date DESC, m.id DESC
            """,
            (project_id,),
        )
    ]


def load_meeting(project_id: int, meeting_id: int) -> dict[str, Any] | None:
    row = query_one(
        """
        SELECT m.*, u.name AS minuted_by
        FROM meetings m LEFT JOIN users u ON u.id = m.user_id
        WHERE m.id = ? AND m.project_id = ?
        """,
        (meeting_id, project_id),
    )
    return dict(row) if row is not None else None


def load_items(project_id: int, on_date: str | None = None) -> list[dict[str, Any]]:
    """Every minuted item on the project, ready for filtering.

    Each row carries the names behind its foreign keys, so searching and
    filtering never has to go back to the database.
    """
    from .minutes import decorate

    rows = query(
        """
        SELECT i.*, m.ref AS meeting_ref, m.title AS meeting_title, m.meeting_date AS meeting_date
        FROM meeting_items i
        LEFT JOIN meetings m ON m.id = i.meeting_id
        WHERE i.project_id = ?
        ORDER BY m.meeting_date DESC, i.sort_order, i.id
        """,
        (project_id,),
    )
    by_item = item_trades(project_id)
    stamp = on_date or today()
    return [
        decorate(dict(r, trades=by_item.get(r["id"], [])), stamp)
        for r in rows
    ]


def item_trades(project_id: int) -> dict[int, list[dict[str, Any]]]:
    """item id -> the trades it sits with, in the project's trade order."""
    rows = query(
        """
        SELECT it.item_id, tr.id, tr.name, tr.color
        FROM meeting_item_trades it
        JOIN trades tr ON tr.id = it.trade_id
        JOIN meeting_items i ON i.id = it.item_id
        WHERE i.project_id = ?
        ORDER BY tr.sort_order, tr.id
        """,
        (project_id,),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["item_id"], []).append(
            {"id": row["id"], "name": row["name"], "color": row["color"]}
        )
    return grouped


def set_item_trades(project_id: int, item_id: int, trade_ids: Sequence[int]) -> None:
    """Replaces the trades on one item, ignoring any that are not this
    project's — an id in a posted form is not to be trusted."""
    allowed = {int(r["id"]) for r in query("SELECT id FROM trades WHERE project_id = ?", (project_id,))}
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM meeting_item_trades WHERE item_id = ?", (item_id,))
        for trade_id in dict.fromkeys(int(t) for t in trade_ids if int(t) in allowed):
            conn.execute(
                "INSERT INTO meeting_item_trades (item_id, trade_id) VALUES (?, ?)",
                (item_id, trade_id),
            )


def load_attendance(meeting_id: int) -> dict[int, int]:
    """attendee id -> 1 present, 0 invited but absent. Missing means not invited."""
    return {
        int(r["attendee_id"]): int(r["present"])
        for r in query("SELECT attendee_id, present FROM meeting_attendance WHERE meeting_id = ?", (meeting_id,))
    }


def set_attendance(meeting_id: int, present_ids: Sequence[int], invited_ids: Sequence[int]) -> None:
    """Records who was invited and which of them attended, in one pass."""
    present = {int(i) for i in present_ids}
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM meeting_attendance WHERE meeting_id = ?", (meeting_id,))
        for attendee_id in {int(i) for i in invited_ids} | present:
            conn.execute(
                "INSERT INTO meeting_attendance (meeting_id, attendee_id, present) VALUES (?, ?, ?)",
                (meeting_id, attendee_id, 1 if attendee_id in present else 0),
            )


def meeting_sheet(project_id: int, meeting_id: int, on_date: str | None = None) -> dict[str, Any] | None:
    """Everything one set of minutes needs: the meeting, who was there, its items.

    The attendance list covers the whole roster so absentees are shown as
    absent rather than simply left out.
    """
    meeting = load_meeting(project_id, meeting_id)
    if meeting is None:
        return None

    marks = load_attendance(meeting_id)
    roster = load_attendees(project_id)
    attendance = []
    for person in roster:
        mark = marks.get(int(person["id"]))
        if mark is None and not person["active"]:
            continue
        attendance.append(dict(person, invited=mark is not None, present=bool(mark)))

    items = [i for i in load_items(project_id, on_date) if i.get("meeting_id") == meeting_id]
    return {
        "meeting": meeting,
        "attendance": attendance,
        "present": [a for a in attendance if a["present"]],
        "absent": [a for a in attendance if a["invited"] and not a["present"]],
        "items": items,
    }


def meeting_items(project_id: int, meeting_id: int | None) -> list[dict[str, Any]]:
    """One meeting's items in the order they are minuted. `meeting_id` of None
    is the items raised outside any meeting, which are their own group."""
    if meeting_id is None:
        rows = query(
            "SELECT * FROM meeting_items WHERE project_id = ? AND meeting_id IS NULL "
            "ORDER BY sort_order, id",
            (project_id,),
        )
    else:
        rows = query(
            "SELECT * FROM meeting_items WHERE project_id = ? AND meeting_id = ? "
            "ORDER BY sort_order, id",
            (project_id, meeting_id),
        )
    return [dict(r) for r in rows]


def renumber_items(project_id: int, meeting_id: int | None) -> None:
    """Gives one meeting's items the numbers their positions imply.

    Called after anything that changes the order or the membership of a
    meeting, so the numbers on screen always run 1, 2, 3 with no gaps and no
    two items sharing one.
    """
    from .minutes import renumber

    rows = meeting_items(project_id, meeting_id)
    if not rows:
        return

    ref = ""
    if meeting_id is not None:
        meeting = query_one("SELECT ref FROM meetings WHERE id = ?", (meeting_id,))
        ref = meeting["ref"] if meeting else ""

    current = {row["id"]: (row["sort_order"], row["ref"]) for row in rows}
    conn = get_db()
    with conn:
        for target in renumber(rows, ref):
            if current[target["id"]] != (target["sort_order"], target["ref"]):
                conn.execute(
                    "UPDATE meeting_items SET sort_order = ?, ref = ? WHERE id = ?",
                    (target["sort_order"], target["ref"], target["id"]),
                )


def move_item(project_id: int, item_id: int, direction: str) -> bool:
    """Swaps an item with the one above or below it and renumbers the meeting.

    Returns False when the item is already at that end of the list, so the
    caller can say so rather than claiming a move that did not happen.
    """
    from .minutes import moved, renumber

    item = query_one("SELECT * FROM meeting_items WHERE id = ? AND project_id = ?", (item_id, project_id))
    if item is None:
        return False

    rows = meeting_items(project_id, item["meeting_id"])
    order = moved(rows, item_id, "up" if direction == "up" else "down")
    if [r["id"] for r in order] == [r["id"] for r in rows]:
        return False

    ref = ""
    if item["meeting_id"] is not None:
        meeting = query_one("SELECT ref FROM meetings WHERE id = ?", (item["meeting_id"],))
        ref = meeting["ref"] if meeting else ""

    conn = get_db()
    with conn:
        for target in renumber(order, ref):
            conn.execute(
                "UPDATE meeting_items SET sort_order = ?, ref = ? WHERE id = ?",
                (target["sort_order"], target["ref"], target["id"]),
            )
    return True


# --- the plan --------------------------------------------------------------

def load_links(project_id: int) -> list[dict[str, Any]]:
    """Every dependency on the project, each with the two WBS it joins."""
    return [
        dict(r)
        for r in query(
            """
            SELECT l.*, p.wbs AS predecessor_wbs, p.name AS predecessor_name,
                   s.wbs AS successor_wbs, s.name AS successor_name
            FROM task_links l
            JOIN tasks p ON p.id = l.predecessor_id
            JOIN tasks s ON s.id = l.successor_id
            WHERE l.project_id = ?
            ORDER BY p.sort_order, p.id, s.sort_order, s.id
            """,
            (project_id,),
        )
    ]


class LinkError(ValueError):
    """A dependency that cannot be made."""


def add_link(project_id: int, predecessor_id: int, successor_id: int, lag_days: float = 0) -> int:
    """Joins two deliverables, refusing anything that cannot hold."""
    from .schedule import would_cycle

    if predecessor_id == successor_id:
        raise LinkError("A deliverable cannot depend on itself")

    owned = {
        int(r["id"])
        for r in query("SELECT id FROM tasks WHERE project_id = ? AND id IN (?, ?)",
                       (project_id, predecessor_id, successor_id))
    }
    if len(owned) != 2:
        raise LinkError("Both deliverables must belong to this project")

    links = load_links(project_id)
    if any(l["predecessor_id"] == predecessor_id and l["successor_id"] == successor_id for l in links):
        raise LinkError("Those two are already linked")
    if would_cycle(links, predecessor_id, successor_id):
        raise LinkError("That link would make the programme depend on itself")

    return insert(
        "INSERT INTO task_links (project_id, predecessor_id, successor_id, lag_days) "
        "VALUES (?, ?, ?, ?)",
        (project_id, predecessor_id, successor_id, float(lag_days or 0)),
    )


def remove_link(project_id: int, link_id: int) -> None:
    execute("DELETE FROM task_links WHERE id = ? AND project_id = ?", (link_id, project_id))


def set_task_dates(project_id: int, task_id: int, start: str, submission: str,
                   cascade: bool = True) -> dict[int, dict[str, str]]:
    """Moves one deliverable and pushes whatever depends on it.

    Successors are only ever pushed later: pulling a predecessor forward frees
    float rather than dragging the programme back with it.
    """
    from .schedule import shift_successors

    execute(
        "UPDATE tasks SET start_date = ?, submission_date = ?, updated_at = datetime('now') "
        "WHERE id = ? AND project_id = ?",
        (start, submission, task_id, project_id),
    )
    if not cascade:
        return {}

    tasks = [
        {"id": r["id"], "start_date": r["start_date"], "submission_date": r["submission_date"]}
        for r in query("SELECT id, start_date, submission_date FROM tasks WHERE project_id = ?",
                       (project_id,))
    ]
    moves = shift_successors(tasks, load_links(project_id), task_id)
    conn = get_db()
    with conn:
        for moved_id, dates in moves.items():
            conn.execute(
                "UPDATE tasks SET start_date = ?, submission_date = ?, updated_at = datetime('now') "
                "WHERE id = ? AND project_id = ?",
                (dates["start_date"], dates["submission_date"], moved_id, project_id),
            )
    return moves


def project_plan(project: Mapping[str, Any], data_date: str | None = None) -> dict[str, Any]:
    """Everything the schedule screen draws: the lines, their float, the links."""
    from .schedule import analyse, critical_path, summarise, window

    project_id = project["id"]
    stamp = data_date or today()
    snapshot = project_snapshot(project, stamp)
    rows = snapshot["tasks"]
    links = load_links(project_id)
    analysis = analyse(rows, links)

    revisions = load_project_revisions(project_id)
    for row in rows:
        row.update(analysis.get(row["id"], {}))
        # A revision carries the code that closed it. The rework it caused is
        # the *next* attempt, so each one is told what sent it back.
        history = revisions.get(row["id"], [])
        for index, attempt in enumerate(history):
            attempt["cause_code"] = history[index - 1].get("code", "") if index else ""
        row["revisions"] = history
        closed = [a for a in history if a.get("code")]
        row["last_code"] = closed[-1]["code"] if closed else ""

    first, last = window(rows, stamp)
    return {
        "tasks": rows,
        "links": links,
        "analysis": analysis,
        "critical": critical_path(analysis),
        "totals": summarise(analysis),
        "window": (first, last),
        "data_date": stamp,
        "trades": snapshot["trades"],
        "max_revisions": snapshot["max_revisions"],
    }


def load_project_revisions(project_id: int) -> dict[int, list[dict[str, Any]]]:
    """task id -> its resubmissions, oldest first."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in query(
        "SELECT * FROM task_revisions WHERE project_id = ? ORDER BY task_id, revision, id",
        (project_id,),
    ):
        grouped.setdefault(row["task_id"], []).append(dict(row))
    return grouped
