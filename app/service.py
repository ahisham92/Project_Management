"""Loading and roll-up helpers that sit between the database and the views."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from .calc import build_period_report, build_s_curve, compute_project, to_iso
from .db import execute, get_db, query, query_one


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


def project_snapshot(project: Mapping[str, Any], data_date: str | None = None, horizon_days: int = 30) -> dict[str, Any]:
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
    )

    # Hours booked without a trade still count against the project total.
    loose = unallocated_hours(project_id, iso)
    budget = snapshot["budget"]
    budget["unallocated_hours"] = loose
    budget["spent_hours"] += loose
    budget["remaining_hours"] = budget["budget_hours"] - budget["spent_hours"]
    budget["hours_used_pct"] = budget["spent_hours"] / budget["budget_hours"] if budget["budget_hours"] > 0 else 0.0
    return snapshot


def project_s_curve(project: Mapping[str, Any], data_date: str | None = None, steps: int = 40) -> list[dict[str, Any]]:
    project = as_dict(project)
    return build_s_curve(
        project,
        load_tasks(project["id"]),
        load_progress_history(project["id"]),
        to_iso(data_date or today()),
        steps,
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


def record_progress(task: Mapping[str, Any], actual_pct: float, note: str, data_date: str, user_id: int) -> None:
    """Saves a new percent complete and keeps the previous value as history."""
    conn = get_db()
    with conn:
        conn.execute(
            "UPDATE tasks SET actual_pct = ?, updated_at = datetime('now') WHERE id = ?",
            (actual_pct, task["id"]),
        )
        conn.execute(
            """
            INSERT INTO progress_updates
                (task_id, project_id, user_id, previous_pct, actual_pct, note, data_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task["id"], task["project_id"], user_id, task["actual_pct"], actual_pct, note, data_date),
        )


def next_sort_order(table: str, project_id: int) -> int:
    row = query_one(f"SELECT COUNT(*) AS n FROM {table} WHERE project_id = ?", (project_id,))
    return int(row["n"]) + 1
