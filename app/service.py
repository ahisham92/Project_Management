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


def teams_by_office(project_id: int) -> dict[str, int]:
    """Which team works in which office, for the deliverables to inherit."""
    from .offices import normalise

    out: dict[str, int] = {}
    for row in query("SELECT id, office FROM calendars WHERE project_id = ? "
                     "ORDER BY sort_order, id", (project_id,)):
        key = normalise(row["office"])
        if key and key not in out:
            out[key] = row["id"]
    return out


def teams_on(task: Mapping[str, Any], trades: Mapping[Any, Mapping[str, Any]],
             by_office: Mapping[str, int]) -> list[int]:
    """Every team working a deliverable, the largest share first.

    A line is not one team's: it is split between trades, the trades sit in
    offices and the offices keep different weeks. Which team it is *planned*
    against is the first of these; which teams' holidays can disrupt it is all
    of them.
    """
    from .offices import normalise

    weight: dict[int, float] = {}
    for trade_id, share in (task.get("allocations") or {}).items():
        trade = trades.get(trade_id)
        if not trade or not share:
            continue
        team = by_office.get(normalise(trade.get("office")))
        if team:
            weight[team] = weight.get(team, 0.0) + float(share)
    return [team for team, _share in sorted(weight.items(), key=lambda kv: -kv[1])]


def load_tasks(project_id: int) -> list[dict[str, Any]]:
    """Deliverables for a project, each with its trade allocations by trade id.

    The working calendar is not stored on the line any more: it comes from the
    trades carrying it, through the office each trade sits in. Setting a trade
    to Cairo is what puts its share of the work on Cairo's week — one answer in
    one place, rather than the same answer typed again on fifty rows.
    """
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

    trades = {t["id"]: t for t in load_trades(project_id)}
    by_office = teams_by_office(project_id)
    for task in tasks:
        task["allocations"] = by_task.get(task["id"], {})
        teams = teams_on(task, trades, by_office)
        task["teams"] = teams
        # Everything downstream reads calendar_id, so it is answered here
        # rather than in five places: the biggest share's team, or whatever the
        # line was on before offices existed, or the project's default.
        task["calendar_id"] = teams[0] if teams else task.get("calendar_id")
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
    diaries = calendars_for(project)
    snapshot = compute_project(
        project,
        load_tasks(project_id),
        load_trades(project_id),
        iso,
        horizon_days=horizon_days,
        spent_by_trade=spent_hours_by_trade(project_id, iso),
        steps=load_steps(project_id),
        calendars=diaries,
    )
    snapshot["calendars"] = diaries

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
        calendars=calendars_for(project),
    )


def project_period(project: Mapping[str, Any], start: str, end: str) -> dict[str, Any]:
    """What moved between two dates — on the programme and in the minutes.

    A month is not only percentages. Half of what actually happened is in the
    register: the actions that were raised, and the ones that were closed. A
    report that leaves those out is a report somebody has to write a covering
    note for.
    """
    project = as_dict(project)
    report = build_period_report(
        project,
        load_tasks(project["id"]),
        load_trades(project["id"]),
        load_progress_history(project["id"]),
        start,
        end,
        steps=load_steps(project["id"]),
    )
    report.update(items_in_period(int(project["id"]), start, end))
    return report


def items_in_period(project_id: int, start: str, end: str) -> dict[str, Any]:
    """The minuted items that moved between two dates, from both registers.

    Closed in the window and raised in it are two different things, so they are
    two lists — "we closed eleven and picked up four" is the sentence somebody
    is trying to write.
    """
    from .dates import from_input

    first = from_input(start) or str(start or "")[:10]
    last = from_input(end) or str(end or "")[:10]

    def inside(value: Any) -> bool:
        stamp = str(value or "")[:10]
        return bool(stamp) and first <= stamp <= last

    # Read as at the end of the window: an item closed inside it reads as
    # closed here even if it was reopened afterwards.
    items = load_items(project_id, last)
    closed = [i for i in items if not i.get("is_open") and inside(i.get("closed_date"))]
    raised = [i for i in items if inside(i.get("raised_date"))]
    still_open = [i for i in items if i.get("is_open") and str(i.get("raised_date") or "")[:10] <= last]
    return {
        "items_closed": closed,
        "items_raised": raised,
        "items_open_at_end": still_open,
        "items_overdue_at_end": [i for i in still_open if i.get("is_overdue")],
    }


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


def load_meetings(project_id: int, kind: str | None = None) -> list[dict[str, Any]]:
    """Meetings newest first, each with its attendance and item counts.

    `kind` narrows to one register — the client's minutes or the internal
    weekly one — and None takes both.
    """
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
            WHERE m.project_id = ? AND (? IS NULL OR m.kind = ?)
            ORDER BY m.meeting_date DESC, m.id DESC
            """,
            (project_id, kind, kind),
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


def load_items(project_id: int, on_date: str | None = None, kind: str | None = None,
               rewind_to: str = "") -> list[dict[str, Any]]:
    """Every minuted item on the project, ready for filtering.

    Each row carries the names behind its foreign keys, so searching and
    filtering never has to go back to the database.

    `kind` narrows to one register. `rewind_to` gives the register as it stood
    on a date — items raised by then, each open or closed as it was — which is
    the answer to "where were we on the fifteenth?".
    """
    from .minutes import decorate, rewind

    where = "WHERE i.project_id = ?"
    params: list[Any] = [project_id]
    if kind:
        where += " AND i.kind = ?"
        params.append(kind)

    rows = query(
        f"""
        SELECT i.*, m.ref AS meeting_ref, m.title AS meeting_title, m.meeting_date AS meeting_date
        FROM meeting_items i
        LEFT JOIN meetings m ON m.id = i.meeting_id
        {where}
        ORDER BY m.meeting_date DESC, i.sort_order, i.id
        """,
        params,
    )
    by_item = item_trades(project_id)
    plain = [dict(r, trades=by_item.get(r["id"], [])) for r in rows]
    if rewind_to:
        plain = rewind(plain, rewind_to)
    stamp = rewind_to or on_date or today()
    options = load_impacts(project_id)
    names = {o["key"]: o["name"] for o in options}
    meanings = {o["key"]: (bool(o["affects_time"]), bool(o["affects_cost"])) for o in options}
    return [decorate(row, stamp, names, meanings) for row in plain]


# --- what an item can be said to affect -------------------------------------

def load_impacts(project_id: int) -> list[dict[str, Any]]:
    """The project's list of what a minuted item can affect.

    Seeded from the four the app ships with the first time it is asked for, so
    every project has a working list and nobody has to build one before they
    can minute anything.
    """
    from .minutes import IMPACTS, IMPACT_MEANS

    rows = query("SELECT * FROM impact_options WHERE project_id = ? ORDER BY sort_order, id",
                 (project_id,))
    if rows:
        return [dict(r) for r in rows]

    conn = get_db()
    with conn:
        for order, (key, name) in enumerate(IMPACTS, start=1):
            time_, cost = IMPACT_MEANS.get(key, (False, False))
            conn.execute(
                "INSERT OR IGNORE INTO impact_options (project_id, key, name, affects_time, "
                "affects_cost, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                (project_id, key, name, int(time_), int(cost), order),
            )
    return [dict(r) for r in query(
        "SELECT * FROM impact_options WHERE project_id = ? ORDER BY sort_order, id",
        (project_id,))]


def impact_choices(project_id: int) -> list[tuple[str, str]]:
    """The list as a dropdown wants it."""
    return [(o["key"], o["name"]) for o in load_impacts(project_id)]


def add_impact(project_id: int, name: str, affects_time: bool = False,
               affects_cost: bool = False) -> str:
    """Adds something an item can affect. Returns why not, or a blank string."""
    from .minutes import impact_key

    called = " ".join(str(name or "").split())[:60]
    key = impact_key(called)
    if not key:
        return "Give it a name"
    if query_one("SELECT 1 FROM impact_options WHERE project_id = ? AND key = ?",
                 (project_id, key)):
        return f"“{called}” is already on the list"
    insert(
        "INSERT INTO impact_options (project_id, key, name, affects_time, affects_cost, "
        "sort_order) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, key, called, int(bool(affects_time)), int(bool(affects_cost)),
         next_sort_order("impact_options", project_id)),
    )
    return ""


def remove_impact(project_id: int, option_id: int) -> str:
    """Takes one off the list, unless something is using it."""
    row = query_one("SELECT * FROM impact_options WHERE id = ? AND project_id = ?",
                    (option_id, project_id))
    if row is None:
        return "That is not on the list"
    if row["key"] == "none":
        return "“No impact” is what an item says when it affects nothing — it stays"
    used = query_one("SELECT COUNT(*) AS n FROM meeting_items WHERE project_id = ? AND impact = ?",
                     (project_id, row["key"]))
    if used and used["n"]:
        return (f"{used['n']} item{'s' if used['n'] != 1 else ''} still says “{row['name']}”. "
                "Change those first.")
    execute("DELETE FROM impact_options WHERE id = ?", (option_id,))
    return ""


def save_impacts(project_id: int, form: Mapping[str, Any]) -> int:
    """Renames and re-flags the whole list in one go."""
    saved = 0
    conn = get_db()
    with conn:
        for option in load_impacts(project_id):
            field = f"impact_{option['id']}_name"
            if field not in form:
                continue
            conn.execute(
                "UPDATE impact_options SET name = ?, affects_time = ?, affects_cost = ? "
                "WHERE id = ? AND project_id = ?",
                (" ".join(str(form.get(field) or option["name"]).split())[:60],
                 1 if form.get(f"impact_{option['id']}_time") else 0,
                 1 if form.get(f"impact_{option['id']}_cost") else 0,
                 option["id"], project_id),
            )
            saved += 1
    return saved


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

    # The order an issued set of minutes wants: as the roster lists them, or
    # client first and down the seniority. One setting, on the project.
    from .minutes import in_order

    project = query_one("SELECT client, attendee_order FROM projects WHERE id = ?",
                        (project_id,))
    attendance = in_order(attendance, (project or {})["attendee_order"] if project else "",
                          (project or {})["client"] if project else "")

    items = [i for i in load_items(project_id, on_date) if i.get("meeting_id") == meeting_id]
    return {
        "meeting": meeting,
        "attendance": attendance,
        "present": [a for a in attendance if a["present"]],
        "absent": [a for a in attendance if a["invited"] and not a["present"]],
        "items": items,
    }


# --- what is attached to a set of minutes -----------------------------------

# A PDF a client would actually open. Bigger than this is a file to send by
# other means, not to staple onto minutes.
MAX_ATTACHMENT = 20 * 1024 * 1024


class AttachmentError(ValueError):
    """An attachment that cannot be kept, said in words."""


def load_attachments(project_id: int, meeting_id: int,
                     with_content: bool = False) -> list[dict[str, Any]]:
    """What is attached to one meeting. The bytes only when they are wanted."""
    columns = ("id, meeting_id, name, filename, bytes, pages, added_at, sort_order"
               + (", content" if with_content else ""))
    return [dict(r) for r in query(
        f"SELECT {columns} FROM meeting_attachments "
        "WHERE project_id = ? AND meeting_id = ? ORDER BY sort_order, id",
        (project_id, meeting_id))]


def add_attachment(project_id: int, meeting_id: int, name: str, filename: str,
                   data: bytes, user_id: Any = None) -> int:
    """Keeps a PDF with the minutes.

    PDF only, and checked by what is in the file rather than what the name says
    — the export staples these onto the end, and something that is not a PDF
    cannot be stapled onto anything.
    """
    from .pdf import is_pdf, page_count

    if not data:
        raise AttachmentError("Choose a file first")
    if len(data) > MAX_ATTACHMENT:
        raise AttachmentError(
            f"That file is {len(data) / 1024 / 1024:.1f} MB. Attachments are kept in the "
            f"database so the nightly backup carries them, so they stop at "
            f"{MAX_ATTACHMENT // 1024 // 1024} MB.")
    if not is_pdf(data):
        raise AttachmentError("Attachments have to be PDFs — that file is not one")

    called = (str(name or "").strip() or str(filename or "").strip()
              or "Attachment")[:160]
    return insert(
        "INSERT INTO meeting_attachments (project_id, meeting_id, name, filename, bytes, "
        "pages, content, user_id, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, meeting_id, called, str(filename or "")[:160], len(data),
         page_count(data), data, user_id,
         len(load_attachments(project_id, meeting_id)) + 1),
    )


# --- an edited workbook, put back ------------------------------------------
def _as_float(value: Any, default: float = 0.0) -> float:
    """A number out of a workbook cell, or what was there before."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return float(default)


def apply_setup_workbook(project: Mapping[str, Any],
                         parsed: Mapping[str, Any]) -> dict[str, int]:
    """Writes an imported workbook over the project's setup, in one transaction.

    Progress is preserved: a deliverable keeps its reported status and revision
    where the workbook supplies them.

    Here rather than in the view because the Setup tab's Import button and
    Carmen reading an attached workbook have to do exactly the same thing.
    """
    from .dates import from_input_or

    project_id = project["id"]
    conn = get_db()
    with conn:
        settings = parsed["project"]
        if settings:
            conn.execute(
                """
                UPDATE projects SET name = ?, client = ?, description = ?, ntp_date = ?,
                       duration_months = ?, days_per_month = ?, hours_per_month = ?,
                       elapsed_day_offset = ?, max_revisions = ?, rework_days = ?,
                       revision_reset_step = ?, target_margin_pct = ?, hours_per_week = ?,
                       status = ?, updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    str(settings.get("name") or project["name"]).strip(),
                    str(settings.get("client") or "").strip(),
                    str(settings.get("description") or "").strip(),
                    from_input_or(settings.get("ntp_date"), project["ntp_date"]),
                    _as_float(settings.get("duration_months"), project["duration_months"]),
                    _as_float(settings.get("days_per_month"), project["days_per_month"]),
                    _as_float(settings.get("hours_per_month"), project["hours_per_month"]),
                    _as_float(settings.get("elapsed_day_offset"), project["elapsed_day_offset"]),
                    int(_as_float(settings.get("max_revisions"), project["max_revisions"])),
                    _as_float(settings.get("rework_days"), project["rework_days"]),
                    str(settings.get("revision_reset_step") or project["revision_reset_step"]).strip(),
                    min(95.0, max(0.0, _as_float(settings.get("target_margin_pct"),
                                                 project["target_margin_pct"]))),
                    max(1.0, _as_float(settings.get("hours_per_week"),
                                       project["hours_per_week"])),
                    str(settings.get("status") or project["status"]).strip(),
                    project_id,
                ),
            )

        if parsed["steps"]:
            # A step's key is what every deliverable's status points at, so keep
            # the existing key whenever the name still matches — otherwise a
            # re-import would silently detach every reported status.
            existing_keys = {
                row["name"].strip().lower(): row["key"]
                for row in conn.execute("SELECT key, name FROM workflow_steps WHERE project_id = ?", (project_id,))
            }
            conn.execute("DELETE FROM workflow_steps WHERE project_id = ?", (project_id,))
            for order, step in enumerate(parsed["steps"], start=1):
                generated = "".join(c if c.isalnum() else "_" for c in step["name"].lower()).strip("_")
                key = existing_keys.get(step["name"].strip().lower()) or generated or f"step_{order}"
                conn.execute(
                    """
                    INSERT INTO workflow_steps (project_id, key, name, percent, anchor, offset_days, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_id, key, step["name"], step["percent"],
                     step["anchor"], step["offset_days"], order),
                )

        # Trades and sections are matched by name so their ids — and therefore
        # the hours already booked against them — survive the import.
        trade_ids: dict[str, int] = {}
        existing_trades = {r["name"].lower(): r for r in
                           conn.execute("SELECT * FROM trades WHERE project_id = ?", (project_id,))}
        for order, trade in enumerate(parsed["trades"], start=1):
            found = existing_trades.pop(trade["name"].lower(), None)
            if found:
                conn.execute(
                    "UPDATE trades SET name = ?, budget_hours = ?, color = ?, office = ?, "
                    "sort_order = ? WHERE id = ?",
                    (trade["name"], trade["budget_hours"], trade["color"],
                     trade.get("office") or "", order, found["id"]),
                )
                trade_ids[trade["name"].lower()] = found["id"]
            else:
                key = "".join(c if c.isalnum() else "_" for c in trade["name"].lower()).strip("_")
                cursor = conn.execute(
                    "INSERT INTO trades (project_id, key, name, budget_hours, color, office, "
                    "sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (project_id, key or f"trade_{order}", trade["name"], trade["budget_hours"],
                     trade["color"], trade.get("office") or "", order),
                )
                trade_ids[trade["name"].lower()] = cursor.lastrowid
        for leftover in existing_trades.values():
            conn.execute("DELETE FROM trades WHERE id = ?", (leftover["id"],))

        section_ids: dict[str, int] = {}
        existing_sections = {r["name"].lower(): r for r in
                             conn.execute("SELECT * FROM sections WHERE project_id = ?", (project_id,))}
        for order, section in enumerate(parsed["sections"], start=1):
            found = existing_sections.pop(section["name"].lower(), None)
            if found:
                conn.execute("UPDATE sections SET code = ?, sort_order = ? WHERE id = ?",
                             (section["code"], order, found["id"]))
                section_ids[section["name"].lower()] = found["id"]
            else:
                cursor = conn.execute(
                    "INSERT INTO sections (project_id, code, name, sort_order) VALUES (?, ?, ?, ?)",
                    (project_id, section["code"], section["name"], order),
                )
                section_ids[section["name"].lower()] = cursor.lastrowid
        for leftover in existing_sections.values():
            conn.execute("DELETE FROM sections WHERE id = ?", (leftover["id"],))

        # Deliverables are matched on WBS so progress already reported against a
        # line is kept when the workbook comes back.
        existing_tasks = {}
        for row in conn.execute("SELECT * FROM tasks WHERE project_id = ?", (project_id,)):
            existing_tasks[(row["wbs"] or "").strip().lower() or f"#{row['id']}"] = row

        seen: set[int] = set()
        for order, task in enumerate(parsed["tasks"], start=1):
            section_id = section_ids.get(task["section"].lower()) if task["section"] else None
            tracking = "simple" if task["tracking"].startswith("simple") else "workflow"
            key = task["wbs"].strip().lower()
            found = existing_tasks.get(key) if key else None

            # Status and revision are deliberately not taken from the workbook,
            # so importing an older export cannot revert progress reported since.
            values = (task["wbs"], task["name"], section_id, task["weight_points"],
                      task["start_date"], task["submission_date"], tracking,
                      task["remarks"], order)
            if found:
                conn.execute(
                    """
                    UPDATE tasks SET wbs = ?, name = ?, section_id = ?, weight_points = ?,
                           start_date = ?, submission_date = ?, tracking = ?,
                           remarks = ?, sort_order = ?, updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    values + (found["id"],),
                )
                task_id = found["id"]
            else:
                task_id = conn.execute(
                    """
                    INSERT INTO tasks (project_id, wbs, name, section_id, weight_points,
                                       start_date, submission_date, tracking, remarks, sort_order)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (project_id,) + values,
                ).lastrowid
            seen.add(task_id)

            conn.execute("DELETE FROM task_allocations WHERE task_id = ?", (task_id,))
            for trade_name, share in task["allocations"].items():
                trade_id = trade_ids.get(trade_name.lower())
                if trade_id and share > 0:
                    conn.execute(
                        "INSERT INTO task_allocations (task_id, trade_id, pct) VALUES (?, ?, ?)",
                        (task_id, trade_id, share),
                    )

        for row in conn.execute("SELECT id FROM tasks WHERE project_id = ?", (project_id,)).fetchall():
            if row["id"] not in seen:
                conn.execute("DELETE FROM tasks WHERE id = ?", (row["id"],))

        # A step's percentage may have been edited in the workbook, so re-derive
        # each deliverable's percent complete from the status it already holds.
        steps = {r["key"]: r["percent"] for r in
                 conn.execute("SELECT key, percent FROM workflow_steps WHERE project_id = ?", (project_id,))}
        for row in conn.execute(
            "SELECT id, tracking, status_key FROM tasks WHERE project_id = ?", (project_id,)
        ).fetchall():
            if row["tracking"] == "workflow":
                conn.execute("UPDATE tasks SET actual_pct = ? WHERE id = ?",
                             (steps.get(row["status_key"], 0.0), row["id"]))

    return {
        "tasks": len(parsed["tasks"]), "trades": len(parsed["trades"]),
        "sections": len(parsed["sections"]), "steps": len(parsed["steps"]),
    }


# --- resource planning ------------------------------------------------------

def booked_by_week(project_id: int, first_day: int = 0) -> dict[tuple[str, int], float]:
    """Hours booked, totalled by the week they were worked and the trade.

    Keyed the way the planner wants them, so the plan and the timesheet can be
    read against each other without either knowing how the other is stored.
    """
    from datetime import date as _date

    from .resources import week_of

    def to_date(value):
        try:
            return _date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None

    out: dict[tuple[str, int], float] = {}
    for row in query(
        "SELECT entry_date, trade_id, hours FROM time_entries WHERE project_id = ?",
        (project_id,),
    ):
        day = to_date(row["entry_date"])
        if day is None or row["trade_id"] is None:
            continue
        key = (week_of(day, first_day).isoformat(), int(row["trade_id"]))
        out[key] = out.get(key, 0.0) + float(row["hours"] or 0)
    return out


def resource_plan(project: Mapping[str, Any],
                  snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The whole resource plan for a project: ceilings, weeks and people.

    Built from the same snapshot the other tabs read, so the hours a week wants
    and the progress it is meant to earn cannot disagree.
    """
    from . import resources
    from .week import first_working_day

    project = as_dict(project)
    project_id = int(project["id"])
    snapshot = snapshot or project_snapshot(project)
    diaries = calendars_for(project)
    opens = first_working_day(diaries[None].week)

    made = resources.plan(
        project, snapshot["tasks"], load_trades(project_id), load_steps(project_id),
        diaries, booked_by_week(project_id, opens), opens,
    )
    made["tasks"] = resources.task_rows(made, snapshot["tasks"],
                                        load_trades(project_id))
    return made


# --- every document the app hands out ---------------------------------------
#
# A deck built on Tuesday is not the deck the same dates build today, because
# the project has moved. So "let me see the presentation Ola sent the client"
# can only be answered by keeping Ola's copy. Every export is kept as the bytes
# that went out, with who asked for it and when.

# How many to keep per project. A year of weekly reports and every set of
# minutes twice over fits comfortably; past that the oldest go, because a
# database is not an archive and the nightly backup carries all of it.
KEEP_DOCUMENTS = 60

# What each kind is called on the page, in the words somebody would use.
DOCUMENT_KINDS: dict[str, str] = {
    "deck": "Presentation",
    "minutes": "Minutes of meeting",
    "minutes_pdf": "Minutes of meeting (PDF)",
    "register": "Action register",
    "agenda": "Agenda",
    "schedule": "Programme",
    "dependencies": "Dependencies",
    "setup": "Setup sheet",
    "week": "The week",
}


def keep_document(project_id: int, kind: str, name: str, filename: str,
                  mimetype: str, data: bytes, user: Any = None,
                  note: str = "") -> int:
    """Writes down one document the app has just handed somebody."""
    if not data:
        return 0
    who = as_dict(user) if user is not None else {}
    made = insert(
        "INSERT INTO documents (project_id, kind, name, filename, mimetype, bytes, "
        "content, note, user_id, user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, str(kind or "")[:40], str(name or "")[:160],
         str(filename or "")[:160], str(mimetype or "")[:120], len(data), data,
         str(note or "")[:200], who.get("id"),
         str(who.get("name") or who.get("email") or "")[:120]),
    )
    execute(
        "DELETE FROM documents WHERE project_id = ? AND id NOT IN "
        "(SELECT id FROM documents WHERE project_id = ? ORDER BY id DESC LIMIT ?)",
        (project_id, project_id, KEEP_DOCUMENTS),
    )
    return made


def load_documents(project_id: int, limit: int = 30) -> list[dict[str, Any]]:
    """What has been handed out on this project, newest first, without the
    bytes — a list of sixty decks is not something to read into memory to draw
    a table of their names."""
    return [
        dict(row, kind_name=DOCUMENT_KINDS.get(row["kind"], row["kind"].title()))
        for row in query(
            "SELECT id, project_id, kind, name, filename, mimetype, bytes, note, "
            "user_id, user_name, made_at FROM documents WHERE project_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (project_id, max(1, int(limit))),
        )
    ]


def document(project_id: int, document_id: int) -> dict[str, Any] | None:
    row = query_one("SELECT * FROM documents WHERE id = ? AND project_id = ?",
                    (document_id, project_id))
    return dict(row) if row else None


# --- the Word template the minutes are built from ---------------------------

# A Word document with a letterhead and a logo in it. Larger than this is a
# document with something else inside it, not a template.
MAX_TEMPLATE = 8 * 1024 * 1024


def load_template(project_id: int, kind: str = "minutes",
                  with_content: bool = True) -> dict[str, Any] | None:
    """The template a project's documents of that kind are built from, if any."""
    columns = "*" if with_content else ("id, project_id, kind, filename, bytes, fields, "
                                        "user_name, added_at")
    row = query_one(f"SELECT {columns} FROM document_templates "
                    "WHERE project_id = ? AND kind = ?", (project_id, kind))
    return dict(row) if row else None


def save_template(project_id: int, data: bytes, filename: str = "",
                  kind: str = "minutes", user: Any = None) -> dict[str, Any]:
    """Keeps an uploaded template, replacing whatever was there.

    Checked on the way in — a file that will not open in Word will not fill in
    here either, and the time to say so is now rather than the first time
    somebody exports a set of minutes for a client.
    """
    from .doctemplate import check, placeholders

    if not data:
        raise AttachmentError("Choose a file first")
    if len(data) > MAX_TEMPLATE:
        raise AttachmentError(
            f"That file is {len(data) / 1024 / 1024:.1f} MB. A template is a form, not a "
            f"folder — they stop at {MAX_TEMPLATE // 1024 // 1024} MB.")
    check(data)

    fields = sorted(placeholders(data))
    who = ""
    if isinstance(user, Mapping):
        who = str(user.get("name") or user.get("email") or "")
    execute("DELETE FROM document_templates WHERE project_id = ? AND kind = ?",
            (project_id, kind))
    insert(
        "INSERT INTO document_templates (project_id, kind, filename, bytes, fields, "
        "content, user_id, user_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, kind, str(filename or "")[:160], len(data), ", ".join(fields),
         data, (user or {}).get("id") if isinstance(user, Mapping) else None, who),
    )
    return {"fields": fields, "bytes": len(data)}


def remove_template(project_id: int, kind: str = "minutes") -> bool:
    """Back to the built-in layout."""
    return bool(execute("DELETE FROM document_templates WHERE project_id = ? AND kind = ?",
                        (project_id, kind)))


def remove_attachment(project_id: int, attachment_id: int) -> bool:
    return bool(execute("DELETE FROM meeting_attachments WHERE id = ? AND project_id = ?",
                        (attachment_id, project_id)))


def attachment(project_id: int, attachment_id: int) -> dict[str, Any] | None:
    row = query_one("SELECT * FROM meeting_attachments WHERE id = ? AND project_id = ?",
                    (attachment_id, project_id))
    return dict(row) if row else None


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


def move_attendee(project_id: int, attendee_id: int, direction: str) -> bool:
    """Swaps a person with the one above or below them on the roster.

    The roster's order is the order an issued set of minutes lists people in,
    so this is the control for "the client goes first, then our director" when
    the house rule does not fit the meeting.
    """
    from .minutes import moved

    rows = load_attendees(project_id)
    if not any(int(r["id"]) == int(attendee_id) for r in rows):
        return False

    order = moved(rows, int(attendee_id), "up" if direction == "up" else "down")
    if [r["id"] for r in order] == [r["id"] for r in rows]:
        return False

    conn = get_db()
    with conn:
        for place, person in enumerate(order, start=1):
            conn.execute("UPDATE attendees SET sort_order = ? WHERE id = ? AND project_id = ?",
                         (place, person["id"], project_id))
    return True


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


def add_link(project_id: int, predecessor_id: int, successor_id: int, lag_days: float = 0,
             kind: str = "FS") -> int:
    """Joins two deliverables, refusing anything that cannot hold."""
    from .schedule import normalise_kind, would_cycle

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
        "INSERT INTO task_links (project_id, predecessor_id, successor_id, lag_days, kind) "
        "VALUES (?, ?, ?, ?, ?)",
        (project_id, predecessor_id, successor_id, float(lag_days or 0), normalise_kind(kind)),
    )


def remove_link(project_id: int, link_id: int) -> bool:
    """Removes a dependency, saying whether there was one to remove."""
    row = query_one("SELECT id FROM task_links WHERE id = ? AND project_id = ?", (link_id, project_id))
    if row is None:
        return False
    execute("DELETE FROM task_links WHERE id = ?", (link_id,))
    return True


def update_link(project_id: int, link_id: int, lag_days: float | None = None,
                kind: str | None = None, predecessor_id: int | None = None,
                successor_id: int | None = None) -> dict[str, Any] | None:
    """Changes a dependency, leaving alone whatever was not given.

    Moving either end is checked the same way making the link was: both
    deliverables must be this project's, a line cannot wait for itself, the
    pair must not already exist, and the programme must not come to depend on
    itself.
    """
    from .schedule import normalise_kind, would_cycle

    row = query_one("SELECT * FROM task_links WHERE id = ? AND project_id = ?", (link_id, project_id))
    if row is None:
        return None

    first = predecessor_id if predecessor_id is not None else row["predecessor_id"]
    second = successor_id if successor_id is not None else row["successor_id"]

    if predecessor_id is not None or successor_id is not None:
        if first == second:
            raise LinkError("A deliverable cannot depend on itself")

        owned = {
            int(r["id"])
            for r in query("SELECT id FROM tasks WHERE project_id = ? AND id IN (?, ?)",
                           (project_id, first, second))
        }
        if len(owned) != 2:
            raise LinkError("Both deliverables must belong to this project")

        others = [l for l in load_links(project_id) if l["id"] != link_id]
        if any(l["predecessor_id"] == first and l["successor_id"] == second for l in others):
            raise LinkError("Those two are already linked")
        if would_cycle(others, first, second):
            raise LinkError("That link would make the programme depend on itself")

    execute(
        "UPDATE task_links SET predecessor_id = ?, successor_id = ?, lag_days = ?, kind = ? "
        "WHERE id = ?",
        (first, second,
         float(lag_days) if lag_days is not None else row["lag_days"],
         normalise_kind(kind) if kind is not None else row["kind"], link_id),
    )
    return dict(query_one("SELECT * FROM task_links WHERE id = ?", (link_id,)))


def set_node_position(project_id: int, task_id: int, x: float | None, y: float | None) -> bool:
    """Where a box sits on the dependency diagram after it has been dragged.

    Clearing both puts the box back under the automatic layout.
    """
    if not query_one("SELECT 1 FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)):
        return False
    execute("UPDATE tasks SET node_x = ?, node_y = ? WHERE id = ?", (x, y, task_id))
    return True


def clear_node_positions(project_id: int) -> None:
    """Puts every box back where the automatic layout would draw it."""
    execute("UPDATE tasks SET node_x = NULL, node_y = NULL WHERE project_id = ?", (project_id,))


# --- working calendars ------------------------------------------------------

def load_calendars(project_id: int) -> list[dict[str, Any]]:
    """The project's teams, each with the days it works and its holidays."""
    from .calendars import week_label

    rows = [dict(r) for r in query(
        "SELECT * FROM calendars WHERE project_id = ? ORDER BY sort_order, id", (project_id,))]
    days = load_holidays(project_id)
    shared = [h for h in days if h["calendar_id"] is None]
    for row in rows:
        own = [h for h in days if h["calendar_id"] == row["id"]]
        row["holidays"] = sorted(own + shared, key=lambda h: h["holiday_date"])
        row["own_holidays"] = own
        row["week_label"] = week_label(row["workdays"])
    return rows


def load_holidays(project_id: int) -> list[dict[str, Any]]:
    """Every holiday on the project, its own team's or everybody's."""
    return [dict(r) for r in query(
        "SELECT * FROM holidays WHERE project_id = ? ORDER BY holiday_date, id", (project_id,))]


def calendars_for(project: Mapping[str, Any]) -> dict[Any, Any]:
    """A ready-made Calendar per team, keyed by id, with a default under None.

    Built once per request and handed round, because every date on the schedule
    asks it something.
    """
    from .calendars import ROUND_THE_CLOCK, Calendar

    project = as_dict(project)
    rows = load_calendars(project["id"])
    made: dict[Any, Any] = {}
    for row in rows:
        made[row["id"]] = Calendar(row["name"], row["workdays"],
                                   [h["holiday_date"] for h in row["holidays"]])
    default_id = project.get("calendar_id")
    made[None] = made.get(default_id) or (made[rows[0]["id"]] if rows else ROUND_THE_CLOCK)
    return made


def calendar_of(task: Mapping[str, Any], calendars: Mapping[Any, Any]):
    """The calendar a deliverable is planned against."""
    from .calendars import ROUND_THE_CLOCK

    return (calendars.get(task.get("calendar_id"))
            or calendars.get(None)
            or ROUND_THE_CLOCK)


def add_calendar(project_id: int, name: str, workdays: str) -> int:
    from .calendars import normalise_week

    order = query_one("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next FROM calendars "
                      "WHERE project_id = ?", (project_id,))["next"]
    return insert(
        "INSERT INTO calendars (project_id, name, workdays, sort_order) VALUES (?, ?, ?, ?)",
        (project_id, (name or "Team").strip()[:60], normalise_week(workdays), order),
    )


def save_calendar(project_id: int, calendar_id: int, name: str, workdays: str) -> bool:
    from .calendars import normalise_week

    if not query_one("SELECT 1 FROM calendars WHERE id = ? AND project_id = ?",
                     (calendar_id, project_id)):
        return False
    execute("UPDATE calendars SET name = ?, workdays = ? WHERE id = ?",
            ((name or "Team").strip()[:60], normalise_week(workdays), calendar_id))
    return True


def delete_calendar(project_id: int, calendar_id: int) -> str:
    """Removes a team, unless it is the last one or the project's default."""
    rows = query("SELECT id FROM calendars WHERE project_id = ?", (project_id,))
    if len(rows) <= 1:
        return "A project keeps at least one team calendar"

    project = query_one("SELECT calendar_id FROM projects WHERE id = ?", (project_id,))
    if project and project["calendar_id"] == calendar_id:
        return "That is the project's default team — make another the default first"

    if not query_one("SELECT 1 FROM calendars WHERE id = ? AND project_id = ?",
                     (calendar_id, project_id)):
        return "No such team"

    db = get_db()
    with db:
        db.execute("UPDATE tasks SET calendar_id = NULL WHERE calendar_id = ?", (calendar_id,))
        db.execute("DELETE FROM holidays WHERE calendar_id = ?", (calendar_id,))
        db.execute("DELETE FROM calendars WHERE id = ?", (calendar_id,))
    return ""


def set_default_calendar(project_id: int, calendar_id: int) -> bool:
    if not query_one("SELECT 1 FROM calendars WHERE id = ? AND project_id = ?",
                     (calendar_id, project_id)):
        return False
    execute("UPDATE projects SET calendar_id = ? WHERE id = ?", (calendar_id, project_id))
    return True


def add_holiday(project_id: int, calendar_id: int | None, holiday_date: str,
                name: str) -> str:
    """A day off, for one team or for everybody. Returns why not, or ""."""
    from .calendars import as_date

    when = as_date(holiday_date)
    if when is None:
        return "That is not a date"
    if calendar_id is not None and not query_one(
            "SELECT 1 FROM calendars WHERE id = ? AND project_id = ?", (calendar_id, project_id)):
        return "No such team"

    already = query_one(
        "SELECT 1 FROM holidays WHERE project_id = ? AND IFNULL(calendar_id, 0) = ? "
        "AND holiday_date = ?", (project_id, calendar_id or 0, when.isoformat()))
    if already:
        return "That day is already a holiday"

    insert("INSERT INTO holidays (project_id, calendar_id, holiday_date, name) VALUES (?, ?, ?, ?)",
           (project_id, calendar_id, when.isoformat(), (name or "").strip()[:80]))
    return ""


def remove_holiday(project_id: int, holiday_id: int) -> bool:
    if not query_one("SELECT 1 FROM holidays WHERE id = ? AND project_id = ?",
                     (holiday_id, project_id)):
        return False
    execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
    return True


def set_task_calendar(project_id: int, task_id: int, calendar_id: int | None) -> bool:
    """Which team a deliverable is planned against."""
    if not query_one("SELECT 1 FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)):
        return False
    if calendar_id is not None and not query_one(
            "SELECT 1 FROM calendars WHERE id = ? AND project_id = ?", (calendar_id, project_id)):
        return False
    execute("UPDATE tasks SET calendar_id = ? WHERE id = ?", (calendar_id, task_id))
    return True


def simplify_layout(project_id: int) -> dict[str, int]:
    """Re-lays the diagram out so the lines cross as little as possible.

    The columns are untouched — they say the order the work runs in — so only
    the order of the boxes within a column changes. The result is written down
    as their positions, which means it can then be nudged by hand and Tidy up
    still puts everything back.
    """
    from .layout import arrange, point
    from .sorting import sort_tasks

    tasks = sort_tasks(load_tasks(project_id), "wbs", "asc")
    result = arrange([task["id"] for task in tasks], load_links(project_id))
    if not result["places"]:
        return {"before": 0, "after": 0, "moved": 0}

    db = get_db()
    with db:
        for task_id, (depth, row) in result["places"].items():
            x, y = point(depth, row)
            db.execute("UPDATE tasks SET node_x = ?, node_y = ? WHERE id = ? AND project_id = ?",
                       (x, y, task_id, project_id))
    return {"before": result["before"], "after": result["after"],
            "moved": len(result["places"])}


def set_task_dates(project_id: int, task_id: int, start: str, submission: str,
                   cascade: bool = True) -> dict[int, dict[str, str]]:
    """Moves one deliverable and pushes whatever depends on it.

    Successors are only ever pushed later: pulling a predecessor forward frees
    float rather than dragging the programme back with it.
    """
    from .schedule import on_a_working_day, shift_successors

    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    diaries = calendars_for(dict(project)) if project else {}
    task = query_one("SELECT calendar_id FROM tasks WHERE id = ? AND project_id = ?",
                     (task_id, project_id))
    mine = calendar_of(dict(task) if task else {}, diaries)

    # A start on a holiday is not a start, and nothing is submitted on a day
    # nobody is in, so both land on the next day the team is working.
    start = on_a_working_day(start, mine) or start
    submission = on_a_working_day(submission, mine) or submission
    if submission < start:
        submission = start

    execute(
        "UPDATE tasks SET start_date = ?, submission_date = ?, updated_at = datetime('now') "
        "WHERE id = ? AND project_id = ?",
        (start, submission, task_id, project_id),
    )
    if not cascade:
        return {}

    tasks = [
        {"id": r["id"], "start_date": r["start_date"], "submission_date": r["submission_date"],
         "calendar_id": r["calendar_id"]}
        for r in query("SELECT id, start_date, submission_date, calendar_id FROM tasks "
                       "WHERE project_id = ?", (project_id,))
    ]
    moves = shift_successors(tasks, load_links(project_id), task_id, diaries)
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
    from .schedule import (analyse, critical_chain, critical_path, paths,
                           start_reason, summarise, window)

    project_id = project["id"]
    stamp = data_date or today()
    snapshot = project_snapshot(project, stamp)
    rows = snapshot["tasks"]
    links = load_links(project_id)
    diaries = snapshot.get("calendars") or calendars_for(project)
    analysis = analyse(rows, links, diaries)

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

    # Holidays in the week before a submission are the ones that hurt: they eat
    # the days the package is being pulled together, and nobody plans for them.
    team_names = {c["id"]: c["name"] for c in load_calendars(project["id"])}
    for row in rows:
        mine = calendar_of(row, diaries)
        row["team_name"] = mine.name
        row["team_week"] = mine.week
        row["run_up"] = run_up_holidays(row, mine, diaries)
        # And days off, anywhere in the run, for any team working the line —
        # including the one it is not planned against.
        row["clashes"] = holiday_clashes(row, diaries, team_names)
        row["team_names"] = [team_names.get(t, "") for t in (row.get("teams") or [])]

    # A line that cannot start where it is drawn says which link holds it back
    # and why — a finish → finish link moves a start without ever mentioning it,
    # which is otherwise a puzzle to read.
    by_id = {row["id"]: row for row in rows}
    for row in rows:
        driver = row.get("driven_by")
        row["late_reason"] = (
            start_reason(driver, by_id.get(driver["task_id"], {}),
                         row.get("duration_days", 1), row.get("early_start"))
            if row.get("starts_late") and driver and driver["task_id"] in by_id
            else ""
        )

    first, last = window(rows, stamp)
    return {
        "tasks": rows,
        "links": links,
        "analysis": analysis,
        "critical": critical_path(analysis),
        # The run of work that ends the programme, in the order it runs, each
        # line whole so the card below the plan can simply be drawn from it.
        "chain": [by_id[task_id] for task_id in critical_chain(analysis) if task_id in by_id],
        "routes": paths([row["id"] for row in rows], links),
        "totals": summarise(analysis),
        "window": (first, last),
        "data_date": stamp,
        "calendars": diaries,
        "teams": load_calendars(project_id),
        "trades": snapshot["trades"],
        "max_revisions": snapshot["max_revisions"],
    }


def project_overview(project: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """The project on one line: when it runs, how much room it has, where it is.

    "Float" here is the project's own, not a deliverable's: how many working
    days sit between the last submission on the programme and the completion
    date the contract gives. It is the number that says whether the programme
    still fits, which no per-line float can answer — every line can have slack
    while the whole thing finishes a month late.
    """
    from .calc import add_months, to_iso

    project = as_dict(project)
    rows = list(snapshot.get("tasks") or [])
    totals = snapshot.get("totals") or {}
    budget = snapshot.get("budget") or {}
    diary = (snapshot.get("calendars") or calendars_for(project)).get(None)

    starts = [str(row["start_date"])[:10] for row in rows if row.get("start_date")]
    # The last date the programme actually asks for: a submission, or the Code A
    # that follows it, whichever is later.
    ends = [str(row[field])[:10] for row in rows
            for field in ("submission_date", "approval_due_date") if row.get(field)]

    start = min(starts) if starts else to_iso(project.get("ntp_date"))
    finish = max(ends) if ends else ""

    days_per_month = float(project.get("days_per_month") or 30.4375) or 30.4375
    duration = float(project.get("duration_months") or 12.0) or 12.0
    contract_end = to_iso(add_months(project["ntp_date"], duration, days_per_month))

    # Positive: the programme finishes with days to spare. Negative: the
    # contract date has already gone, whatever any single line's float says.
    slack = 0
    if finish and diary is not None:
        slack = (diary.duration(finish, contract_end) - 1 if finish <= contract_end
                 else -(diary.duration(contract_end, finish) - 1))

    return {
        "start": start,
        "finish": finish,
        "contract_end": contract_end,
        "float_days": slack,
        "on_time": slack >= 0,
        "deliverables": len(rows),
        "planned": totals.get("planned_progress", 0.0),
        "earned": totals.get("earned_progress", 0.0),
        "variance": totals.get("variance", 0.0),
        "earned_hours": budget.get("earned_hours", 0.0),
        "budget_hours": budget.get("budget_hours", 0.0),
        "team": getattr(diary, "name", ""),
    }


RUN_UP_DAYS = 7


def run_up_holidays(task: Mapping[str, Any], mine: Any,
                    diaries: Mapping[Any, Any] | None = None) -> dict[str, Any]:
    """Days off in the last week before a submission, and whose they are.

    A holiday in the run-up to a submission is the one that costs: it takes days
    out of the week the package is being pulled together, and it is exactly the
    thing a programme drawn in calendar days hides. A day everybody is off is
    worth saying more loudly than one only this team takes.
    """
    from .calendars import as_date

    submission = as_date(task.get("submission_date"))
    if submission is None:
        return {"days": [], "count": 0, "everyone": 0, "from": "", "to": ""}

    from datetime import timedelta

    opens = submission - timedelta(days=RUN_UP_DAYS - 1)
    others = [c for key, c in (diaries or {}).items()
              if key is not None and c is not mine]

    days = []
    for day in mine.holidays_between(opens, submission):
        iso = day.isoformat()
        shared = all(iso in team.holidays for team in others) if others else True
        days.append({"date": iso, "everyone": shared})

    return {
        "days": days,
        "count": len(days),
        "everyone": sum(1 for day in days if day["everyone"]),
        "from": opens.isoformat(),
        "to": submission.isoformat(),
    }


def holiday_clashes(task: Mapping[str, Any], diaries: Mapping[Any, Any],
                    names: Mapping[Any, str] | None = None) -> list[dict[str, Any]]:
    """Days off, inside a deliverable's run, for a team actually working it.

    A line split between Beirut and Cairo is worked to two different calendars.
    It is planned against one of them, so the other's holidays are invisible —
    and they are exactly the days somebody is waiting for an answer that is not
    coming. Named here so the schedule can say so.
    """
    from .calendars import as_date

    start, finish = as_date(task.get("start_date")), as_date(task.get("submission_date"))
    if start is None or finish is None or finish < start:
        return []

    out: list[dict[str, Any]] = []
    for team_id in task.get("teams") or []:
        diary = diaries.get(team_id)
        if diary is None:
            continue
        days = [day.isoformat() for day in diary.holidays_between(start, finish)]
        if days:
            out.append({"team_id": team_id,
                        "team": (names or {}).get(team_id) or getattr(diary, "name", "") or "team",
                        "days": days, "count": len(days)})
    return out


def load_project_revisions(project_id: int) -> dict[int, list[dict[str, Any]]]:
    """task id -> its resubmissions, oldest first."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in query(
        "SELECT * FROM task_revisions WHERE project_id = ? ORDER BY task_id, revision, id",
        (project_id,),
    ):
        grouped.setdefault(row["task_id"], []).append(dict(row))
    return grouped


# --- backups ----------------------------------------------------------------

def record_backup(ok: bool, where_to: str, size: int, detail: str = "",
                  link: str = "") -> int:
    """Writes down what a backup run did, so the screen can say so.

    Only the last handful are kept: this is a health light, not a log.
    """
    run_id = insert(
        "INSERT INTO backup_runs (started_at, ok, where_to, bytes, detail, link) "
        "VALUES (datetime('now'), ?, ?, ?, ?, ?)",
        (1 if ok else 0, where_to, int(size), detail[:500], link),
    )
    execute(
        "DELETE FROM backup_runs WHERE id NOT IN "
        "(SELECT id FROM backup_runs ORDER BY id DESC LIMIT 20)"
    )
    return run_id


def load_backup_runs(limit: int = 10) -> list[dict[str, Any]]:
    return [dict(r) for r in query(
        "SELECT * FROM backup_runs ORDER BY id DESC LIMIT ?", (limit,))]


def last_backup() -> dict[str, Any] | None:
    row = query_one("SELECT * FROM backup_runs ORDER BY id DESC LIMIT 1")
    return dict(row) if row else None


def last_good_backup() -> dict[str, Any] | None:
    """The last one that actually landed. A failed run is not a backup."""
    row = query_one("SELECT * FROM backup_runs WHERE ok = 1 AND where_to = 'drive' "
                    "ORDER BY id DESC LIMIT 1")
    return dict(row) if row else None


def backup_due(at: Any = None) -> bool:
    """Whether tonight's backup is still owed.

    Read off the appointed hour in the project's own zone and the last run that
    actually reached Drive, so a night the server was asleep is caught the next
    time anybody opens a page rather than waited out for another day.
    """
    from . import clock
    from .drive import configured
    from .vault import schedule, settings

    when = schedule()
    if not when["auto"] or not configured(settings()):
        return False

    last = last_good_backup()
    return clock.due(last["started_at"] if last else "", when["hour"], when["zone"], at)


def backup_if_due(at: Any = None) -> dict[str, Any] | None:
    """Runs the nightly backup, but only if it has not already run tonight.

    The day's chat transcript goes up with it — one job, one moment, so there
    is one thing to check rather than two.
    """
    if not backup_due(at):
        return None

    result = run_backup(note="Nightly")
    try:
        result["chats"] = upload_chat_log()
    except Exception as exc:                          # noqa: BLE001 - never lose the backup over it
        result["chats"] = {"ok": False, "detail": str(exc)}
    return result


def run_backup(upload_to_drive: bool = True, note: str = "") -> dict[str, Any]:
    """Take a backup, put it on Drive, and write down what happened.

    Never raises: a nightly job that dies on a network hiccup leaves nothing
    behind saying so, and the whole point is to be able to see that it ran.
    """
    from .backup import build, readable
    from .db import live_database
    from .drive import DriveError, configured, upload
    from .vault import settings as drive_settings

    try:
        data, manifest = build(live_database(), note)
    except Exception as exc:                          # noqa: BLE001 - reported, not raised
        record_backup(False, "backup", 0, f"Could not take the backup: {exc}")
        return {"ok": False, "detail": f"Could not take the backup: {exc}"}

    result: dict[str, Any] = {
        "ok": True, "bytes": len(data), "size": readable(len(data)),
        "manifest": manifest, "data": data, "uploaded": False, "link": "",
    }

    settings = drive_settings()
    if not upload_to_drive:
        record_backup(True, "local", len(data), "Taken, not uploaded")
        result["detail"] = "Taken, not uploaded"
        return result

    if not configured(settings):
        missing = ("Google Drive is not connected — open the Backups page and "
                   "press Connect Google Drive")
        record_backup(False, "drive", len(data), missing)
        result["ok"] = False
        result["detail"] = missing
        return result

    try:
        said = upload(settings, data)
    except DriveError as exc:
        record_backup(False, "drive", len(data), str(exc))
        result["ok"] = False
        result["detail"] = str(exc)
        return result

    what = "Replaced" if said.get("replaced") else "Created"
    detail = f"{what} {said.get('name', 'the backup')} on Google Drive"
    record_backup(True, "drive", len(data), detail, said.get("link", ""))
    result.update(uploaded=True, detail=detail, link=said.get("link", ""), drive=said)
    return result


# --- what has been asked of Carmen ------------------------------------------

# --- conversations ----------------------------------------------------------
#
# A question on its own is a search box. A conversation somebody can come back
# to a week later and carry on is the thing that is actually useful, so the
# thread is a record of its own and the exchanges hang from it.

TITLE_LENGTH = 70


def open_thread(project_id: Any, user: Any, title: str = "") -> int:
    """Starts a conversation. The title is the first thing asked, tidied."""
    who = as_dict(user) if user is not None else {}
    words = " ".join(str(title or "").split())
    if len(words) > TITLE_LENGTH:
        words = words[:TITLE_LENGTH].rsplit(" ", 1)[0] + "…"
    return insert(
        "INSERT INTO chat_threads (project_id, user_id, user_name, title) VALUES (?, ?, ?, ?)",
        (project_id, who.get("id"), str(who.get("name") or "")[:120],
         words or "New conversation"),
    )


def touch_thread(thread_id: Any, title: str = "") -> None:
    """Marks a conversation as the one most recently used."""
    if not thread_id:
        return
    execute("UPDATE chat_threads SET last_at = datetime('now') WHERE id = ?", (thread_id,))
    if title:
        execute("UPDATE chat_threads SET title = ? WHERE id = ? AND "
                "(title = '' OR title = 'New conversation')",
                (title[:TITLE_LENGTH], thread_id))


def load_threads(project_id: Any, user_id: Any = None, limit: int = 60) -> list[dict[str, Any]]:
    """The conversations on a project — everybody's, or one person's.

    Each one carries how many exchanges it holds, so a thread somebody opened
    and never used reads as empty rather than as something to go back to.
    """
    where = "t.project_id = ?"
    params: list[Any] = [project_id]
    if user_id is not None:
        where += " AND t.user_id = ?"
        params.append(user_id)
    rows = query(
        f"""
        SELECT t.*, COUNT(c.id) AS exchanges
        FROM chat_threads t
        LEFT JOIN chat_log c ON c.thread_id = t.id
        WHERE {where}
        GROUP BY t.id
        ORDER BY t.last_at DESC, t.id DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    return [dict(r) for r in rows]


def load_thread(project_id: Any, thread_id: Any) -> dict[str, Any] | None:
    row = query_one("SELECT * FROM chat_threads WHERE id = ? AND project_id = ?",
                    (thread_id, project_id))
    return dict(row) if row else None


def thread_messages(thread_id: Any) -> list[dict[str, Any]]:
    """One conversation, as the page draws it and the model reads it back."""
    rows = query(
        "SELECT id, question, answer, tools_used, trouble, asked_at, user_name "
        "FROM chat_log WHERE thread_id = ? ORDER BY id",
        (thread_id,),
    )
    files: dict[Any, list[dict[str, Any]]] = {}
    for one in thread_files(thread_id):
        files.setdefault(one["chat_id"], []).append(one)

    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({"role": "user", "content": row["question"], "who": row["user_name"],
                    "at": row["asked_at"], "files": files.get(row["id"], [])})
        out.append({"role": "assistant", "content": row["answer"] or row["trouble"],
                    "used": [t for t in str(row["tools_used"] or "").split(", ") if t],
                    "failed": bool(row["trouble"]) and not row["answer"]})
    return out


# A megabyte of prose is more than anybody means to attach to a question.
MAX_CHAT_FILES = 4


def keep_file(project_id: Any, thread_id: Any, user: Any, name: str, kind: str,
              data: bytes) -> int:
    """Keeps what somebody attached to a question."""
    who = as_dict(user) if user is not None else {}
    return insert(
        "INSERT INTO chat_files (project_id, thread_id, user_id, name, kind, bytes, content) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, thread_id, who.get("id"), str(name)[:160], str(kind)[:20],
         len(data), data),
    )


def name_files(chat_id: Any, file_ids: Sequence[int]) -> None:
    """Ties the files to the exchange they were asked about."""
    for one in file_ids:
        execute("UPDATE chat_files SET chat_id = ? WHERE id = ?", (chat_id, one))


def thread_files(thread_id: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in query(
        "SELECT id, chat_id, name, kind, bytes, added_at FROM chat_files "
        "WHERE thread_id = ? ORDER BY id", (thread_id,))]


def chat_file(project_id: Any, file_id: int) -> dict[str, Any] | None:
    row = query_one("SELECT * FROM chat_files WHERE id = ? AND project_id = ?",
                    (file_id, project_id))
    return dict(row) if row else None


def rename_thread(project_id: Any, thread_id: Any, title: str) -> bool:
    words = " ".join(str(title or "").split())[:TITLE_LENGTH]
    if not words:
        return False
    return bool(execute("UPDATE chat_threads SET title = ? WHERE id = ? AND project_id = ?",
                        (words, thread_id, project_id)))


def delete_thread(project_id: Any, thread_id: Any) -> bool:
    """Forgets a conversation. What was said stays in the log — the transcript
    that goes to Drive is the record of use, and it is not somebody's to erase."""
    if not query_one("SELECT 1 FROM chat_threads WHERE id = ? AND project_id = ?",
                     (thread_id, project_id)):
        return False
    execute("UPDATE chat_log SET thread_id = NULL WHERE thread_id = ?", (thread_id,))
    execute("DELETE FROM chat_threads WHERE id = ?", (thread_id,))
    return True


def record_chat(project_id: Any, user: Any, question: str, answer: Any,
                thread_id: Any = None) -> int:
    """Writes down one exchange.

    Kept because "does it work" and "is anybody using it, and for what" are
    different questions, and only the second one tells you whether it was worth
    building. The transcript goes to Drive once a day as plain text.
    """
    who = as_dict(user) if user is not None else {}
    spent = dict(getattr(answer, "spent", {}) or {})
    written = insert(
        """
        INSERT INTO chat_log (asked_at, project_id, user_id, user_name, question, answer,
                              tools_used, staged, trouble, thread_id, tokens_in, tokens_out,
                              tokens_cached, tokens_written, from_cache)
        VALUES (datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, who.get("id"), str(who.get("name") or "")[:120],
         str(question)[:4000], str(getattr(answer, "text", "") or "")[:8000],
         ", ".join(getattr(answer, "used", []) or [])[:400],
         len(getattr(answer, "staged", []) or []), str(getattr(answer, "trouble", "") or "")[:500],
         thread_id, int(spent.get("input") or 0), int(spent.get("output") or 0),
         int(spent.get("cache_read") or 0), int(spent.get("cache_written") or 0),
         1 if getattr(answer, "from_cache", False) else 0),
    )
    touch_thread(thread_id, " ".join(str(question).split())[:TITLE_LENGTH])
    return written


# --- answers worth not paying for twice -------------------------------------
#
# The cheapest call to an API is the one that is not made. A question asked
# again while nothing on the project has changed has the same answer as last
# time — the figures come from the project, and the project has not moved. So
# the answer is kept against the project's own change counter, and a repeat
# while that counter is unchanged is handed straight back.
#
# Only answers that read: anything that staged a change, produced a link or
# went wrong is worked out again, because what those produce is not just words.


def _asked_as(question: str) -> str:
    """A question, in the form two people asking the same thing would share."""
    words = " ".join(str(question or "").lower().split())
    return words.strip(" .?!")[:400]


def remembered_answer(project_id: int, question: str) -> dict[str, Any] | None:
    """The last answer to this question, if the project has not moved since."""
    asked = _asked_as(question)
    if not asked:
        return None
    row = query_one("SELECT * FROM chat_answers WHERE project_id = ? AND question = ?",
                    (project_id, asked))
    if row is None or str(row["pulse"]) != project_pulse(project_id):
        return None
    execute("UPDATE chat_answers SET used = used + 1 WHERE id = ?", (row["id"],))
    return dict(row)


def remember_answer(project_id: int, question: str, text: str,
                    used: Sequence[str] = ()) -> None:
    """Keeps one answer against the project as it stands now."""
    asked = _asked_as(question)
    if not asked or not str(text or "").strip():
        return
    execute(
        "INSERT INTO chat_answers (project_id, question, pulse, answer, tools_used) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (project_id, question) DO UPDATE SET "
        "pulse = excluded.pulse, answer = excluded.answer, "
        "tools_used = excluded.tools_used, asked_at = datetime('now'), used = 0",
        (project_id, asked, project_pulse(project_id), str(text)[:8000],
         ", ".join(used)[:400]),
    )


def forget_answers(project_id: int) -> int:
    """Throws the kept answers away, and says how many there were.

    Nothing needs this — a kept answer falls out of use on its own the moment
    anything on the project changes — but somebody who wants a fresh answer to
    everything should be able to say so.
    """
    return int(execute("DELETE FROM chat_answers WHERE project_id = ?",
                       (project_id,)).rowcount or 0)


def chat_spend(project_id: int, days: int = 30) -> dict[str, Any]:
    """What Carmen has cost on this project lately, in tokens.

    Not money: the price per token depends on the model and changes, and a
    figure in dollars that is quietly wrong is worse than a count that is not.
    """
    row = query_one(
        """
        SELECT COUNT(*) AS asked,
               COALESCE(SUM(tokens_in), 0) AS fresh,
               COALESCE(SUM(tokens_out), 0) AS written,
               COALESCE(SUM(tokens_cached), 0) AS cached,
               COALESCE(SUM(tokens_written), 0) AS kept,
               COALESCE(SUM(from_cache), 0) AS answered_free
        FROM chat_log
        WHERE project_id = ? AND asked_at >= datetime('now', ?)
        """,
        (project_id, f"-{max(1, int(days))} days"),
    )
    found = dict(row) if row else {}
    fresh, cached = int(found.get("fresh") or 0), int(found.get("cached") or 0)
    return {
        **{k: int(v or 0) for k, v in found.items()},
        "days": int(days),
        # What share of the input never had to be sent fresh. The two savings
        # that show up here are the kept prompt and the shorter history.
        "cached_share": (cached / (cached + fresh)) if (cached + fresh) else 0.0,
    }


def note_applied(chat_id: Any, how_many: int) -> None:
    """Marks that the reader went on to apply what was proposed."""
    if chat_id:
        execute("UPDATE chat_log SET applied = applied + ? WHERE id = ?",
                (int(how_many), chat_id))


def load_chats(on_day: str = "", limit: int = 500) -> list[dict[str, Any]]:
    """One day's conversations, oldest first — or the most recent, given none."""
    if on_day:
        rows = query("SELECT * FROM chat_log WHERE date(asked_at) = ? ORDER BY id", (on_day,))
    else:
        rows = query("SELECT * FROM chat_log ORDER BY id DESC LIMIT ?", (limit,))
        rows = list(reversed(rows))
    return [dict(r) for r in rows]


def chat_transcript(on_day: str) -> str:
    """One day's conversations as plain text.

    Plain text on purpose: somebody looking at a month of these on Drive should
    be able to read one in a browser tab without a tool, and grep the lot.
    """
    from .dates import to_display

    rows = load_chats(on_day)
    lines = [
        f"Project Control — Carmen, {to_display(on_day) or on_day}",
        f"{len(rows)} exchange{'' if len(rows) == 1 else 's'}",
        "=" * 72,
        "",
    ]
    projects = {p["id"]: f"{p['code']} — {p['name']}"
                for p in (dict(r) for r in query("SELECT id, code, name FROM projects"))}

    for row in rows:
        lines.append(f"[{str(row['asked_at'])[11:16]} UTC] {row['user_name'] or 'someone'}"
                     f" · {projects.get(row['project_id'], 'no project')}")
        lines.append(f"  asked: {row['question']}")
        if row["trouble"]:
            lines.append(f"  failed: {row['trouble']}")
        else:
            for index, part in enumerate((row["answer"] or "").splitlines() or [""]):
                lines.append(("  said:  " if index == 0 else "         ") + part)
        if row["tools_used"]:
            lines.append(f"  read:  {row['tools_used']}")
        if row["staged"]:
            lines.append(f"  proposed {row['staged']} change(s); "
                         f"{row['applied']} applied")
        lines.append("")

    if not rows:
        lines.append("Nobody asked her anything.")
    return "\n".join(lines)


def upload_chat_log(on_day: str = "") -> dict[str, Any]:
    """Puts one day's transcript on Drive, beside the backup.

    A file per day rather than one file replaced, because the question this
    answers is how usage changes over time — which a single file overwritten
    every night cannot show. Re-running for the same day replaces that day's
    file rather than making a second.
    """
    from .drive import DriveError, configured, upload
    from .vault import settings as drive_settings

    from . import clock
    from .vault import schedule

    when = schedule()
    day = on_day or clock.local_date(when["zone"])
    text = chat_transcript(day)
    name = f"project-control-chats-{day}.txt"

    settings = drive_settings()
    if not configured(settings):
        return {"ok": False, "detail": "Google Drive is not connected", "name": name}

    try:
        said = upload(settings, text.encode("utf-8"), name)
    except DriveError as exc:
        record_backup(False, "chats", len(text), f"Chat log: {exc}")
        return {"ok": False, "detail": str(exc), "name": name}

    what = "Replaced" if said.get("replaced") else "Created"
    detail = f"{what} {name} on Google Drive"
    record_backup(True, "chats", len(text.encode("utf-8")), detail, said.get("link", ""))
    return {"ok": True, "detail": detail, "name": name, "link": said.get("link", ""),
            "exchanges": len(load_chats(day))}


# --- knowing when something changed ----------------------------------------

def project_pulse(project_id: int) -> str:
    """How many times anything on this project has changed.

    Cheap enough to ask for every few seconds — one indexed row. The counter is
    kept by triggers in the database, so no write can forget to move it, and two
    changes in the same second cannot be mistaken for one.
    """
    row = query_one("SELECT version FROM project_pulse WHERE project_id = ?", (project_id,))
    return str(row["version"] if row else 0)


def replace_links(project_id: int, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Puts the project's dependencies where an imported sheet says they are.

    Nothing is written until every row has been checked, so a sheet with a
    mistake in it cannot leave the programme half-linked. Rows that name a WBS
    the project does not have, or that would make it depend on itself, are
    reported rather than silently dropped.
    """
    from .schedule import normalise_kind, would_cycle

    by_wbs = {
        str(r["wbs"]).strip(): int(r["id"])
        for r in query("SELECT id, wbs FROM tasks WHERE project_id = ?", (project_id,))
        if str(r["wbs"] or "").strip()
    }

    wanted: list[dict[str, Any]] = []
    trouble: list[str] = []
    seen: set[tuple[int, int]] = set()

    for row in rows:
        first = by_wbs.get(str(row.get("predecessor_wbs") or "").strip())
        second = by_wbs.get(str(row.get("successor_wbs") or "").strip())
        pair = f"{row.get('successor_wbs')} waits for {row.get('predecessor_wbs')}"

        if first is None or second is None:
            trouble.append(f"{pair}: no deliverable with that WBS")
            continue
        if first == second:
            trouble.append(f"{pair}: a deliverable cannot depend on itself")
            continue
        if (first, second) in seen:
            trouble.append(f"{pair}: listed twice")
            continue
        if would_cycle(wanted, first, second):
            trouble.append(f"{pair}: would make the programme depend on itself")
            continue

        seen.add((first, second))
        wanted.append({
            "predecessor_id": first, "successor_id": second,
            "kind": normalise_kind(row.get("kind")),
            "lag_days": float(row.get("lag_days") or 0),
        })

    conn = get_db()
    with conn:
        conn.execute("DELETE FROM task_links WHERE project_id = ?", (project_id,))
        for link in wanted:
            conn.execute(
                "INSERT INTO task_links (project_id, predecessor_id, successor_id, lag_days, kind) "
                "VALUES (?, ?, ?, ?, ?)",
                (project_id, link["predecessor_id"], link["successor_id"],
                 link["lag_days"], link["kind"]),
            )
    return {"added": len(wanted), "skipped": trouble}


def squeeze_plan(project: Mapping[str, Any], first_id: int, last_id: int,
                 starts: Any, ends: Any, excluded: Sequence[int] = (),
                 with_meetings: Any = True) -> dict[str, Any]:
    """What squeezing a run of the programme between two dates would do.

    Writes nothing. The answer is the whole proposal, including what happens to
    any series of recurring meetings inside the run — there are as many of those
    as the programme is long, so a shorter programme has fewer of them.
    """
    from .dates import from_input
    from .squeeze import meetings_for, plan

    # Dates arrive as somebody typed them; everything below works in ISO.
    starts, ends = (from_input(starts) or starts), (from_input(ends) or ends)
    project = as_dict(project)
    project_id = int(project["id"])
    tasks = load_tasks(project_id)
    links = load_links(project_id)
    diaries = calendars_for(project)

    proposal = plan(tasks, links, diaries, int(first_id), int(last_id), starts, ends,
                    load_steps(project_id), excluded)

    # A series of recurring meetings inside the run is not work that compresses
    # — each one is a day — but there are as many of them as the programme is
    # long. What each would become is worked out and shown; which of them
    # actually follow the span is somebody's decision, not a guess.
    from .schedule import _diaries

    inside = set(proposal["scope"])
    rows = {int(t["id"]): dict(t) for t in tasks}
    found = meetings_for([t for t in tasks if t["id"] in inside],
                         proposal["start"], proposal["finish"], _diaries(rows, diaries))
    wanted = None if with_meetings is True else set(with_meetings or ())
    for run in found:
        run["follow"] = run["is_meeting"] if wanted is None else (run["name"] in wanted)
    proposal["meetings"] = found
    return proposal


def snapshot_schedule(project_id: int, user: Any = None, note: str = "") -> int:
    """Writes down where every date stands, so it can be put back."""
    import json

    who = as_dict(user) if user is not None else {}
    rows = [{"id": r["id"], "start_date": r["start_date"],
             "submission_date": r["submission_date"]}
            for r in query("SELECT id, start_date, submission_date FROM tasks "
                           "WHERE project_id = ?", (project_id,))]
    return insert(
        "INSERT INTO schedule_snapshots (project_id, user_id, user_name, note, lines, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, who.get("id"), str(who.get("name") or "")[:120], str(note)[:200],
         len(rows), json.dumps(rows)),
    )


def load_snapshots(project_id: int, limit: int = 10) -> list[dict[str, Any]]:
    return [dict(r) for r in query(
        "SELECT id, made_at, user_name, note, lines FROM schedule_snapshots "
        "WHERE project_id = ? ORDER BY id DESC LIMIT ?", (project_id, limit))]


def restore_schedule(project_id: int, snapshot_id: int) -> int:
    """Puts every date back to where a snapshot says it was."""
    import json

    row = query_one("SELECT * FROM schedule_snapshots WHERE id = ? AND project_id = ?",
                    (snapshot_id, project_id))
    if row is None:
        return 0
    lines = json.loads(row["payload"] or "[]")
    conn = get_db()
    with conn:
        for line in lines:
            conn.execute(
                "UPDATE tasks SET start_date = ?, submission_date = ?, "
                "updated_at = datetime('now') WHERE id = ? AND project_id = ?",
                (line["start_date"], line["submission_date"], line["id"], project_id),
            )
    return len(lines)


def apply_squeeze(project_id: int, proposal: Mapping[str, Any],
                  user: Any = None) -> dict[str, Any]:
    """Puts a squeeze where the proposal says it goes.

    Where every date stood is written down first, so "put it back to four
    months" is a button rather than an afternoon.
    """
    from .dates import to_display

    kept = snapshot_schedule(project_id, user,
                             f"Before squeezing to {to_display(proposal.get('end'))}")

    conn = get_db()
    lines = [*proposal.get("changes", ()), *proposal.get("after", ())]
    with conn:
        for line in lines:
            conn.execute(
                "UPDATE tasks SET start_date = ?, submission_date = ?, "
                "updated_at = datetime('now') WHERE id = ? AND project_id = ?",
                (line["start"], line["submission"], line["id"], project_id),
            )

    following = [run for run in (proposal.get("meetings") or []) if run.get("follow")]
    added, removed, moved = _fit_meetings(project_id, following)

    return {"squeezed": len(proposal.get("changes", ())),
            "followed": len(proposal.get("after", ())),
            "meetings_added": added, "meetings_removed": removed,
            "meetings_moved": moved, "snapshot": kept}


def _fit_meetings(project_id: int, series: Sequence[Mapping[str, Any]]) -> tuple[int, int, int]:
    """Adds, drops and renumbers a run of recurring meetings to fit the span."""
    added = removed = moved = 0
    conn = get_db()
    with conn:
        for run in series:
            for line in run.get("moves") or []:
                conn.execute(
                    "UPDATE tasks SET name = ?, start_date = ?, submission_date = ?, "
                    "updated_at = datetime('now') WHERE id = ? AND project_id = ?",
                    (line["name"], line.get("start") or line["date"], line["date"],
                     line["id"], project_id))
                moved += 1
            for line in run.get("remove") or []:
                conn.execute("DELETE FROM tasks WHERE id = ? AND project_id = ?",
                             (line["id"], project_id))
                removed += 1

    # Adding copies the last one in the series — its section, its weight and its
    # trade split — because a meeting added by hand would be copied from it too.
    for run in series:
        for line in run.get("add") or []:
            like = query_one("SELECT * FROM tasks WHERE id = ? AND project_id = ?",
                             (line.get("like"), project_id))
            if like is None:
                continue
            made = insert(
                """
                INSERT INTO tasks (project_id, section_id, wbs, name, weight_points,
                                   start_date, submission_date, tracking, remarks, sort_order)
                VALUES (?, ?, '', ?, ?, ?, ?, ?, '', ?)
                """,
                (project_id, like["section_id"], line["name"], like["weight_points"],
                 line.get("start") or line["date"], line["date"], like["tracking"],
                 next_sort_order("tasks", project_id)),
            )
            split = {r["trade_id"]: r["pct"] for r in query(
                "SELECT trade_id, pct FROM task_allocations WHERE task_id = ?", (like["id"],))}
            if split:
                set_allocations(made, project_id, split)
            added += 1
    return added, removed, moved


def apply_schedule(project_id: int, rows: Sequence[Mapping[str, Any]], mode: str) -> dict[str, Any]:
    """Puts the project's dates where an imported sheet says they are.

    The sheet is the authority, so nothing is cascaded on top of it — every
    line lands where it was written. Whether the finish or the duration is read
    follows the project's own setting, the same as on screen. Nothing is
    written until every row has been checked.
    """
    from .dates import from_input
    from .schedule import duration_between, finish_from, normalise_mode, on_a_working_day

    project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    diaries = calendars_for(dict(project)) if project else {}

    by_duration = normalise_mode(mode) != "dates"
    by_wbs = {
        str(r["wbs"]).strip(): dict(r)
        for r in query("SELECT id, wbs, start_date, submission_date, calendar_id FROM tasks "
                       "WHERE project_id = ?", (project_id,))
        if str(r["wbs"] or "").strip()
    }

    wanted: list[tuple[int, str, str]] = []
    trouble: list[str] = []

    for row in rows:
        wbs = str(row.get("wbs") or "").strip()
        task = by_wbs.get(wbs)
        if task is None:
            trouble.append(f"{wbs}: no deliverable with that WBS")
            continue

        start = from_input(row.get("start_date")) or task["start_date"]
        if not start:
            trouble.append(f"{wbs}: no start date")
            continue

        mine = calendar_of(task, diaries)
        start = on_a_working_day(start, mine) or start
        if by_duration:
            days = float(row.get("duration_days") or 0) or duration_between(
                task["start_date"], task["submission_date"], mine) or 1
            finish = finish_from(start, days, mine)
        else:
            finish = from_input(row.get("submission_date")) or task["submission_date"]
            if not finish:
                trouble.append(f"{wbs}: no finish date")
                continue
            if finish < start:
                trouble.append(f"{wbs}: the finish is before the start")
                continue
            finish = on_a_working_day(finish, mine) or finish

        wanted.append((int(task["id"]), start, finish))

    conn = get_db()
    with conn:
        for task_id, start, finish in wanted:
            conn.execute(
                "UPDATE tasks SET start_date = ?, submission_date = ?, updated_at = datetime('now') "
                "WHERE id = ? AND project_id = ?",
                (start, finish, task_id, project_id),
            )
    return {"applied": len(wanted), "skipped": trouble}
