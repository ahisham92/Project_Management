"""What needs someone's thought on a project, gathered in one place.

Every screen already shows its own problems: the schedule its late lines, the
minutes their overdue actions, the procedures their waiting questions. This
puts them side by side, each with the question it is really asking, so a
project manager can see in one look what needs a decision today and what can
wait for the week.

Each item lands in one of three lanes:

  now   overdue, or a decision nobody has made yet;
  week  coming due in the next seven days, or drifting behind plan;
  soon  worth a thought before it becomes either.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from flask import url_for

from . import procedures
from .db import query

LANES = (
    ("now", "Needs a decision now", "Overdue, or waiting on an answer from you"),
    ("week", "This week", "Coming due within seven days, or slipping behind plan"),
    ("soon", "Worth a thought", "Not urgent yet. Better looked at before it is"),
)

KINDS = {
    "deliverable": ("Deliverable", "doc"),
    "client": ("With the client", "send"),
    "action": ("Minutes action", "chat"),
    "procedure": ("Procedure", "check"),
    "question": ("Decision", "q"),
    "budget": ("Budget", "coin"),
}


def _item(lane, kind, title, think, detail, href, days=None, weight=0.0):
    label, icon = KINDS[kind]
    return {"lane": lane, "kind": kind, "kind_label": label, "icon": icon,
            "title": title, "think": think, "detail": detail, "href": href,
            "days": days, "weight": weight}


def _days(n: int) -> str:
    return f"{n} day{'' if abs(n) == 1 else 's'}"


def gather(project, snapshot, today: date | None = None) -> list[dict[str, Any]]:
    today = today or date.fromisoformat(snapshot["data_date"])
    pid = project["id"]
    out: list[dict[str, Any]] = []
    progress = url_for("projects.tasks", project_id=pid)

    # --- the programme ---------------------------------------------------
    for t in snapshot["tasks"]:
        name = f"{t.get('wbs') or ''} {t['name']}".strip()
        href = url_for("projects.task_history", project_id=pid, task_id=t["id"])
        if t["at_revision_limit"] and not t["is_complete"]:
            out.append(_item("now", "deliverable", name,
                             "It has used every revision allowed. Escalate it, or agree a different route with the client?",
                             f"Revision {t['revision']} of {snapshot['max_revisions']}", href, weight=t["weight_pct"]))
        elif t["is_late"]:
            out.append(_item("now", "deliverable", name,
                             "Re-plan the submission, add people to it, or tell the client it is coming late?",
                             f"Late by {_days(t['days_late'])} · {t['status_name']}", href,
                             days=-t["days_late"], weight=t["weight_pct"]))
        elif t["overdue_back"]:
            out.append(_item("now", "client", name,
                             "The client is past the review time. Chase them for the code?",
                             f"Issued {_days(t['waiting_days'])} ago, no Code A yet", href,
                             days=-t["waiting_days"], weight=t["weight_pct"]))
        elif t["is_behind"] and t["days_to_due"] <= 7:
            out.append(_item("week", "deliverable", name,
                             "Due within the week and behind plan. Will it make it?",
                             f"Due in {_days(t['days_to_due'])} · {round(t['actual_pct'] * 100)}% done "
                             f"against {round(t['planned_pct'] * 100)}% planned", href,
                             days=t["days_to_due"], weight=t["weight_pct"]))
        elif t["is_behind"]:
            out.append(_item("soon", "deliverable", name,
                             "Slipping behind plan. Is the plan or the progress wrong?",
                             f"{round(t['actual_pct'] * 100)}% done against {round(t['planned_pct'] * 100)}% planned",
                             href, days=t["days_to_due"], weight=t["weight_pct"]))
        elif t["in_rework"] and not t["with_client"]:
            out.append(_item("week" if t["days_to_due"] <= 7 else "soon", "deliverable", name,
                             "Back from the client with comments. Who answers them, and by when?",
                             f"Revision {t['revision']} · due {_days(t['days_to_due'])} from now", href,
                             days=t["days_to_due"], weight=t["weight_pct"]))

    # --- the money -------------------------------------------------------
    b = snapshot.get("budget") or {}
    spent, budget = b.get("spent_hours") or 0, b.get("budget_hours") or 0
    earned_pct = snapshot["totals"]["earned_progress"]
    if budget and spent / budget > earned_pct + 0.10:
        out.append(_item("now" if spent / budget > earned_pct + 0.25 else "week", "budget",
                         "Hours are running ahead of progress",
                         "More of the budget is booked than the work has earned. Where are the hours going?",
                         f"{round(spent / budget * 100)}% of hours booked for {round(earned_pct * 100)}% earned",
                         url_for("projects.budget", project_id=pid)))

    # --- the minutes -----------------------------------------------------
    week_end = (today + timedelta(days=7)).isoformat()
    rows = query(
        "SELECT id, ref, subject, agreement, owner_name, due_date, kind FROM meeting_items"
        " WHERE project_id = ? AND status = 'open' AND due_date != '' AND due_date <= ?"
        " ORDER BY due_date", (pid, week_end))
    for r in rows:
        due = date.fromisoformat(r["due_date"]) if r["due_date"] else today
        days = (due - today).days
        href = url_for("meetings.index", project_id=pid, kind=r["kind"] or "client")
        title = f"{r['ref']} {r['subject']}".strip() or "Action from the minutes"
        owner = r["owner_name"] or "No owner named"
        if days < 0:
            out.append(_item("now", "action", title,
                             "Past its date. Close it, or agree a new one at the next meeting?",
                             f"Overdue by {_days(-days)} · {owner}", href, days=days))
        else:
            out.append(_item("week", "action", title, "Due this week. Is the owner on it?",
                             f"Due in {_days(days)} · {owner}" if days else f"Due today · {owner}",
                             href, days=days))

    # --- the procedures --------------------------------------------------
    state = procedures.load_state(project)
    s = procedures.summary(state, today)
    href = url_for("projects.procedures", project_id=pid)
    for q in s["waiting"]:
        out.append(_item("now", "question", q.get("short") or q["label"],
                         q["label"], f"Asked at {q['station']} · it decides which procedure actions apply", href))
    for e in s["overdue"]:
        it = e["item"]
        out.append(_item("now", "procedure", it["t"],
                         "Its target date has passed. Do it, mark it not applicable, or set a new date?",
                         f"Overdue by {_days(-e['days'])} · {it.get('ref', '')} · {it.get('who', '')}", href,
                         days=e["days"]))
    for e in s["soon"]:
        if e["days"] > 7:
            continue
        it = e["item"]
        out.append(_item("week", "procedure", it["t"], "Target date this week.",
                         f"Due in {_days(e['days'])} · {it.get('ref', '')}", href, days=e["days"]))
    cur = s["current"]
    if cur and cur["open"]:
        n = len(cur["open"])
        out.append(_item("soon", "procedure", f"{cur['name']}: {n} action{'' if n == 1 else 's'} open",
                         "The station the project has reached in the company procedures. What is next on it?",
                         "; ".join(it["t"] for it in cur["open"][:2]) + ("…" if n > 2 else ""), href))

    order = {"now": 0, "week": 1, "soon": 2}
    out.sort(key=lambda i: (order[i["lane"]], i["days"] if i["days"] is not None else 0, -i["weight"]))
    return out


def lanes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"key": k, "title": t, "hint": h, "items": [i for i in items if i["lane"] == k]}
            for k, t, h in LANES]
