"""What the assistant is allowed to do, and how it does it.

Every tool is a plain Python function over the same service layer the screens
use, so the assistant can do exactly what a person with that role could do on
those screens and nothing else — it is another way in, not another set of
rules. Three things follow from that and are worth being explicit about:

* **Nothing is invented.** A tool either reads what is in the database or
  changes it through the same function a form posts to. The model never writes
  a number into a field; it names a deliverable and a value, and the service
  layer decides whether that is allowed.
* **Writes are staged, not done.** A tool that changes something returns a
  described intention. The page shows it, and somebody presses Apply. A model
  that has misread "1.2" as "1.12" is then a sentence to correct rather than a
  schedule to unpick.
* **Everything is scoped to one project.** The project id comes from the URL,
  never from the model, so no phrasing can reach another project's data.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from ..dates import from_input, to_display

# --- finding what the reader meant ------------------------------------------

class ToolError(Exception):
    """Something the model asked for that cannot be done, said in words it can
    read and act on — a wrong reference is a thing to correct, not to crash."""


def _project(project_id: int) -> dict[str, Any]:
    from ..db import query_one
    from ..service import as_dict

    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise ToolError("That project does not exist")
    return as_dict(row)


def _deliverable(project_id: int, reference: Any) -> dict[str, Any]:
    """The deliverable the reader meant, by WBS number or by name.

    People say "1.2" and they say "the design basis report"; both have to work,
    and an ambiguous phrase has to come back as a question rather than as a
    guess about which of four lines to change.
    """
    from ..service import load_tasks

    wanted = " ".join(str(reference or "").strip().lower().split())
    if not wanted:
        raise ToolError("Say which deliverable — its WBS number, like 1.2, or its name")

    rows = load_tasks(project_id)
    exact = [t for t in rows if str(t.get("wbs") or "").strip().lower() == wanted]
    if len(exact) == 1:
        return exact[0]

    named = [t for t in rows if wanted in str(t.get("name") or "").lower()]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        listed = "; ".join(f"{t['wbs']} {t['name'][:60]}" for t in named[:6])
        raise ToolError(f"That matches {len(named)} deliverables — say which: {listed}")
    raise ToolError(f"No deliverable matches {reference!r}. Use find_deliverables to look one up.")


def _date(value: Any, what: str) -> str:
    iso = from_input(value)
    if not iso:
        raise ToolError(f"{what} must be a date as dd/mm/yyyy — got {value!r}")
    return iso


def _line(task: Mapping[str, Any]) -> dict[str, Any]:
    """One deliverable, said the way the model should read it back."""
    return {
        "wbs": task.get("wbs"),
        "name": task.get("name"),
        "start": to_display(task.get("start_date")),
        "submission": to_display(task.get("submission_date")),
        "percent": round(float(task.get("actual_pct") or 0) * 100),
        "planned_percent": round(float(task.get("planned_pct") or 0) * 100),
        "status": task.get("status_name") or "Not started",
        "weight_percent": round(float(task.get("weight_pct") or 0) * 100, 2),
        "late": bool(task.get("is_late")),
        "days_late": int(task.get("days_late") or 0),
        "behind_plan": bool(task.get("is_behind")),
        "complete": bool(task.get("is_complete")),
        "revision": int(task.get("revision") or 0),
        "team": task.get("team_name") or "",
        "critical": bool(task.get("is_critical")),
        "float_days": task.get("total_float"),
    }


# --- reading ----------------------------------------------------------------

def overview(project_id: int, **_ignored) -> dict[str, Any]:
    """Where the project stands: dates, float, progress, hours."""
    from ..service import project_overview, project_snapshot, today

    project = _project(project_id)
    snapshot = project_snapshot(project, today())
    seen = project_overview(project, snapshot)
    totals = snapshot["totals"]
    budget = snapshot["budget"]
    return {
        "project": f"{project['code']} — {project['name']}",
        "client": project.get("client") or "",
        "data_date": to_display(snapshot["data_date"]),
        "starts": to_display(seen["start"]),
        "finishes": to_display(seen["finish"]),
        "contract_date": to_display(seen["contract_end"]),
        "float_working_days": seen["float_days"],
        "planned_percent": round(seen["planned"] * 100, 2),
        "earned_percent": round(seen["earned"] * 100, 2),
        "variance_percent": round(seen["variance"] * 100, 2),
        "spi": totals.get("spi"),
        "cpi": budget.get("cpi"),
        "budget_hours": round(budget.get("budget_hours") or 0, 1),
        "booked_hours": round(budget.get("spent_hours") or 0, 1),
        "earned_hours": round(budget.get("earned_hours") or 0, 1),
        "deliverables": totals.get("task_count"),
        "late": totals.get("late_count"),
        "behind_plan": totals.get("behind_count"),
    }


def find_deliverables(project_id: int, query: str = "", state: str = "all",
                      limit: int = 25, **_ignored) -> dict[str, Any]:
    """Deliverables matching a word, a state, or both."""
    from ..service import project_plan

    plan = project_plan(_project(project_id))
    rows = plan["tasks"]
    needle = " ".join(str(query or "").lower().split())
    keep = str(state or "all").strip().lower()

    def wanted(task: Mapping[str, Any]) -> bool:
        if needle and needle not in f"{task.get('wbs')} {task.get('name')}".lower():
            return False
        if keep == "late":
            return bool(task.get("is_late"))
        if keep == "behind":
            return bool(task.get("is_behind"))
        if keep == "complete":
            return bool(task.get("is_complete"))
        if keep == "in_progress":
            return 0 < float(task.get("actual_pct") or 0) < 1
        if keep == "not_started":
            return float(task.get("actual_pct") or 0) <= 0
        if keep == "critical":
            return bool(task.get("is_critical"))
        return True

    found = [_line(task) for task in rows if wanted(task)]
    capped = max(1, min(int(limit or 25), 60))
    return {"matched": len(found), "showing": min(len(found), capped),
            "deliverables": found[:capped]}


def deliverable(project_id: int, reference: str = "", **_ignored) -> dict[str, Any]:
    """Everything about one deliverable, including what it waits on."""
    from ..service import load_links, project_plan

    plan = project_plan(_project(project_id))
    wanted = _deliverable(project_id, reference)
    row = next((t for t in plan["tasks"] if t["id"] == wanted["id"]), wanted)

    by_id = {t["id"]: t for t in plan["tasks"]}
    waits_on, drives = [], []
    for link in load_links(project_id):
        if link["successor_id"] == row["id"]:
            other = by_id.get(link["predecessor_id"], {})
            waits_on.append({"wbs": other.get("wbs"), "name": other.get("name"),
                             "kind": link["kind"], "lag_days": link["lag_days"]})
        elif link["predecessor_id"] == row["id"]:
            other = by_id.get(link["successor_id"], {})
            drives.append({"wbs": other.get("wbs"), "name": other.get("name"),
                           "kind": link["kind"], "lag_days": link["lag_days"]})

    return dict(_line(row), **{
        "remarks": row.get("remarks") or "",
        "approval_due": to_display(row.get("approval_due_date")),
        "waits_on": waits_on,
        "drives": drives,
        "cannot_start_because": row.get("late_reason") or "",
        "holidays_in_run_up": (row.get("run_up") or {}).get("count", 0),
    })


def period_report(project_id: int, start: str = "", end: str = "", **_ignored) -> dict[str, Any]:
    """What actually moved between two dates."""
    from ..service import project_period

    project = _project(project_id)
    from_iso, to_iso = _date(start, "The start of the period"), _date(end, "The end of the period")
    if to_iso < from_iso:
        from_iso, to_iso = to_iso, from_iso

    report = project_period(project, from_iso, to_iso)
    moved = [
        {"wbs": row["wbs"], "name": row["name"],
         "from_percent": round(row["actual_start"] * 100),
         "to_percent": round(row["actual_end"] * 100),
         "gained_percent": round(row["delta_actual"] * 100),
         "project_points_gained": round(row["earned_in_period"] * 100, 3),
         "what_happened": row["period_status"]}
        for row in report["tasks"] if abs(row.get("delta_actual") or 0) > 1e-9
    ]
    moved.sort(key=lambda r: -r["project_points_gained"])
    return {
        "from": to_display(from_iso), "to": to_display(to_iso),
        "days_in_period": report["days_in_period"],
        "earned_at_start_percent": round(report["earned_at_start"] * 100, 2),
        "earned_at_end_percent": round(report["earned_at_end"] * 100, 2),
        "gained_percent": round(report["earned_in_period"] * 100, 2),
        "planned_at_end_percent": round(report["planned_at_end"] * 100, 2),
        "deliverables_that_moved": len(moved),
        "movements": moved[:40],
        "trades": [{"name": t["name"], "gained_percent": round(t["earned_in_period"] * 100, 2)}
                   for t in report.get("trade_earned_in_period", [])],
    }


def schedule_summary(project_id: int, **_ignored) -> dict[str, Any]:
    """The critical path, the paths through the network, and what is late."""
    from ..service import project_plan

    plan = project_plan(_project(project_id))
    return {
        "starts": to_display(plan["window"][0]),
        "finishes": to_display(plan["window"][1]),
        "unique_paths": plan["routes"]["count"],
        "critical_path": [{"wbs": t["wbs"], "name": t["name"],
                           "start": to_display(t.get("start_date")),
                           "submission": to_display(t.get("submission_date"))}
                          for t in plan["chain"]],
        "late": [{"wbs": t["wbs"], "name": t["name"], "days_late": t["days_late"]}
                 for t in plan["tasks"] if t.get("is_late")],
        "dependencies": len(plan["links"]),
        "teams": [{"name": c["name"], "week": c["week_label"],
                   "holidays": len(c["holidays"])} for c in plan["teams"]],
    }


def week_ahead(project_id: int, week: str = "", **_ignored) -> dict[str, Any]:
    """What the project wants of us this week, or any other."""
    from .. import week as weeks
    from ..service import load_items, project_plan, project_snapshot, today

    project = _project(project_id)
    plan = project_plan(project)
    first_day = weeks.first_working_day(plan["calendars"][None].week)
    start, end = weeks.week_window(from_input(week) or today(), first_day)
    targets = {r["id"]: r["planned_pct"] for r in project_snapshot(project, end)["tasks"]}

    rows = weeks.compile_week(plan["tasks"], load_items(project["id"], today(), kind="client"),
                              load_items(project["id"], today(), kind="internal"),
                              start, end, targets)
    return {
        "from": to_display(start), "to": to_display(end),
        "totals": weeks.summarise(rows),
        "requirements": [
            {"need": row["need"], "from": row["source"], "ref": row["ref"],
             "what": row["title"], "who": row["who"], "wanted_by": to_display(row["due"]),
             "state": row["state"]}
            for row in rows[:40]
        ],
    }


def register(project_id: int, kind: str = "client", state: str = "open",
             as_at: str = "", **_ignored) -> dict[str, Any]:
    """Minuted items — the client's register or our own internal one."""
    from ..minutes import normalise_kind
    from ..service import load_items, today

    which = normalise_kind(kind)
    rewind = from_input(as_at) or ""
    items = load_items(project_id, today(), kind=which, rewind_to=rewind)
    want = str(state or "open").lower()

    kept = [i for i in items
            if want == "all"
            or (want == "open" and i["is_open"])
            or (want == "closed" and not i["is_open"])
            or (want == "overdue" and i["is_overdue"])]
    return {
        "register": which,
        "as_at": to_display(rewind) if rewind else "today",
        "count": len(kept),
        "items": [{"ref": i["ref"], "subject": i["subject"], "agreed": i["agreement"],
                   "owner": i["owner_label"], "due": to_display(i["due_date"]),
                   "affects": i["impact_name"],
                   "state": "closed" if not i["is_open"] else
                            ("overdue" if i["is_overdue"] else "open")}
                  for i in kept[:40]],
    }


def budget_summary(project_id: int, **_ignored) -> dict[str, Any]:
    """Hours by trade: budgeted, booked, earned, and what that says."""
    from ..service import project_snapshot, today

    snapshot = project_snapshot(_project(project_id), today())
    budget = snapshot["budget"]
    return {
        "budget_hours": round(budget["budget_hours"], 1),
        "booked_hours": round(budget["spent_hours"], 1),
        "earned_hours": round(budget["earned_hours"], 1),
        "cpi": budget.get("cpi"),
        "estimate_at_completion_hours": round(budget.get("eac_hours") or 0, 1),
        "trades": [{"name": t["name"], "budget_hours": round(t["budget_hours"], 1),
                    "booked_hours": round(t["spent_hours"], 1),
                    "earned_hours": round(t["earned_hours"], 1),
                    "earned_percent": round(t["earned_pct_of_trade"] * 100, 2),
                    "cpi": t.get("cpi")}
                   for t in snapshot["trades"]],
    }


# --- changing things (staged, not done) -------------------------------------
#
# Each of these only *describes* what it would do. The runner collects them,
# the page shows them, and apply() below is what actually writes — after
# somebody has looked at the list and pressed the button.

def set_progress(project_id: int, reference: str = "", percent: Any = None,
                 status: str = "", note: str = "", **_ignored) -> dict[str, Any]:
    """Record progress on a deliverable."""
    from ..service import load_steps
    from ..workflow import ordered

    task = _deliverable(project_id, reference)
    plan = {"kind": "set_progress", "task_id": task["id"], "wbs": task["wbs"],
            "name": task["name"], "note": str(note or "")[:200]}

    if status:
        steps = ordered(load_steps(project_id))
        wanted = str(status).strip().lower()
        found = next((s for s in steps
                      if wanted in (str(s["key"]).lower(), str(s["name"]).lower())), None)
        if found is None:
            names = ", ".join(f"{s['name']} ({s['key']})" for s in steps)
            raise ToolError(f"No workflow step called {status!r}. The steps are: {names}")
        plan["status_key"] = found["key"]
        plan["says"] = (f"{task['wbs']} {task['name'][:60]} → {found['name']} "
                        f"({round(found['percent'] * 100)}%)")
        return plan

    try:
        value = float(percent)
    except (TypeError, ValueError):
        raise ToolError("Give either a percent between 0 and 100 or a workflow step name") from None
    if not 0 <= value <= 100:
        raise ToolError("Progress must be between 0 and 100")

    plan["percent"] = value
    was = round(float(task.get("actual_pct") or 0) * 100)
    plan["says"] = f"{task['wbs']} {task['name'][:60]} → {value:g}% (was {was}%)"
    return plan


def set_dates(project_id: int, reference: str = "", start: str = "", submission: str = "",
              cascade: bool = True, **_ignored) -> dict[str, Any]:
    """Move a deliverable's start and submission, pushing what depends on it."""
    task = _deliverable(project_id, reference)
    new_start = _date(start, "The start") if start else str(task.get("start_date") or "")
    new_end = _date(submission, "The submission") if submission else str(task.get("submission_date") or "")
    if not new_start or not new_end:
        raise ToolError("A deliverable needs both a start and a submission date")

    return {
        "kind": "set_dates", "task_id": task["id"], "wbs": task["wbs"], "name": task["name"],
        "start": new_start, "submission": new_end, "cascade": bool(cascade),
        "says": (f"{task['wbs']} {task['name'][:60]} → {to_display(new_start)} to "
                 f"{to_display(new_end)}"
                 + (" (and everything that waits on it moves with it)" if cascade else "")),
    }


def link_deliverables(project_id: int, predecessor: str = "", successor: str = "",
                      kind: str = "FS", lag_days: Any = 0, **_ignored) -> dict[str, Any]:
    """Make one deliverable wait on another."""
    from ..schedule import normalise_kind

    first = _deliverable(project_id, predecessor)
    second = _deliverable(project_id, successor)
    if first["id"] == second["id"]:
        raise ToolError("A deliverable cannot wait on itself")

    try:
        lag = float(lag_days or 0)
    except (TypeError, ValueError):
        raise ToolError("The lag must be a number of days") from None

    shape = normalise_kind(kind)
    return {
        "kind": "add_link", "predecessor_id": first["id"], "successor_id": second["id"],
        "link_kind": shape, "lag_days": lag,
        "says": (f"{second['wbs']} waits on {first['wbs']} ({shape}"
                 + (f", {lag:g}d lag" if lag else "") + ")"),
    }


def unlink_deliverables(project_id: int, predecessor: str = "", successor: str = "",
                        **_ignored) -> dict[str, Any]:
    """Remove a dependency between two deliverables."""
    from ..service import load_links

    first = _deliverable(project_id, predecessor)
    second = _deliverable(project_id, successor)
    link = next((l for l in load_links(project_id)
                 if l["predecessor_id"] == first["id"] and l["successor_id"] == second["id"]), None)
    if link is None:
        raise ToolError(f"{second['wbs']} does not wait on {first['wbs']}")

    return {"kind": "remove_link", "link_id": link["id"],
            "says": f"{second['wbs']} no longer waits on {first['wbs']}"}


def raise_item(project_id: int, register: str = "internal", subject: str = "",
               owner: str = "", due: str = "", agreed: str = "", **_ignored) -> dict[str, Any]:
    """Raise an action in the client's minutes or the internal register."""
    from ..minutes import normalise_kind, normalise_owner

    if not str(subject or "").strip():
        raise ToolError("An action needs a subject")

    which = normalise_kind(register)
    return {
        "kind": "raise_item", "register": which, "subject": str(subject).strip()[:300],
        "owner": normalise_owner(owner), "due": _date(due, "The action date") if due else "",
        "agreed": str(agreed or "").strip()[:2000],
        "says": (f"Raise “{str(subject).strip()[:60]}” in the "
                 f"{'client' if which == 'client' else 'internal'} register"
                 + (f", {normalise_owner(owner)}" if normalise_owner(owner) else "")
                 + (f", by {to_display(_date(due, 'The action date'))}" if due else "")),
    }


def close_item(project_id: int, reference: str = "", closed_on: str = "", **_ignored) -> dict[str, Any]:
    """Close a minuted item, on the day it was actually closed."""
    from ..service import load_items, today

    wanted = " ".join(str(reference or "").strip().lower().split())
    if not wanted:
        raise ToolError("Say which item — its number, like 3.1, or words from its subject")

    items = [i for i in load_items(project_id, today()) if i["is_open"]]
    exact = [i for i in items if str(i.get("ref") or "").strip().lower() == wanted]
    found = exact or [i for i in items if wanted in str(i.get("subject") or "").lower()]
    if not found:
        raise ToolError(f"No open item matches {reference!r}")
    if len(found) > 1:
        listed = "; ".join(f"{i['ref']} {i['subject'][:50]}" for i in found[:6])
        raise ToolError(f"That matches {len(found)} items — say which: {listed}")

    item = found[0]
    when = _date(closed_on, "The closing date") if closed_on else today()
    return {"kind": "close_item", "item_id": item["id"], "closed_on": when,
            "says": f"Close {item['ref']} “{item['subject'][:60]}” on {to_display(when)}"}


def add_project_holiday(project_id: int, date: str = "", team: str = "",
                        name: str = "", **_ignored) -> dict[str, Any]:
    """Add a holiday, for one team or for everybody."""
    from ..service import load_calendars

    when = _date(date, "The holiday")
    calendar_id = None
    whose = "everybody"
    if str(team or "").strip():
        wanted = str(team).strip().lower()
        found = next((c for c in load_calendars(project_id)
                      if wanted in str(c["name"]).lower()), None)
        if found is None:
            names = ", ".join(c["name"] for c in load_calendars(project_id))
            raise ToolError(f"No team called {team!r}. The teams are: {names}")
        calendar_id, whose = found["id"], found["name"]

    return {"kind": "add_holiday", "date": when, "calendar_id": calendar_id,
            "name": str(name or "").strip()[:60],
            "says": f"{to_display(when)} off for {whose}" +
                    (f" — {str(name).strip()[:40]}" if name else "")}


# --- views and documents ----------------------------------------------------

VIEWS = {
    "dashboard": ("projects.dashboard", "the dashboard"),
    "progress": ("projects.tasks", "the progress tab"),
    "schedule": ("projects.schedule", "the schedule"),
    "budget": ("projects.budget", "the budget"),
    "period": ("projects.period", "the period report"),
    "timesheet": ("projects.timesheet", "the timesheet"),
    "minutes": ("meetings.index", "the client's minutes"),
    "internal": ("meetings.week", "this week"),
    "setup": ("projects.setup", "the setup sheet"),
    "guide": ("projects.guide", "the how-to-use guide"),
}


def open_view(project_id: int, view: str = "dashboard", printable: bool = False,
              start: str = "", end: str = "", **_ignored) -> dict[str, Any]:
    """A link to one of the app's own pages, optionally straight into print."""
    from flask import url_for

    wanted = str(view or "").strip().lower()
    if wanted not in VIEWS:
        raise ToolError(f"There is no {view!r} view. Choose one of: {', '.join(VIEWS)}")

    endpoint, said = VIEWS[wanted]
    args: dict[str, Any] = {"project_id": project_id}
    if wanted == "minutes":
        args["kind"] = "client"
    if wanted == "period":
        if start:
            args["start"] = to_display(_date(start, "The start of the period"))
        if end:
            args["end"] = to_display(_date(end, "The end of the period"))
    if printable:
        # The page opens its own print dialog on arrival, where "Save as PDF"
        # makes the file — no PDF library, nothing to install.
        args["print"] = 1

    return {"kind": "open_view", "view": wanted, "url": url_for(endpoint, **args),
            "printable": bool(printable),
            "says": ("Print " if printable else "Open ") + said}


def presentation(project_id: int, start: str = "", end: str = "", title: str = "",
                 **_ignored) -> dict[str, Any]:
    """A slide deck of the work done between two dates."""
    from flask import url_for

    from_iso = _date(start, "The start of the period")
    to_iso = _date(end, "The end of the period")
    if to_iso < from_iso:
        from_iso, to_iso = to_iso, from_iso

    return {
        "kind": "presentation", "start": from_iso, "end": to_iso,
        "title": str(title or "").strip()[:120],
        "url": url_for("assistant.deck", project_id=project_id,
                       start=to_display(from_iso), end=to_display(to_iso),
                       title=str(title or "").strip()[:120] or None),
        "says": f"A deck of the work done {to_display(from_iso)} to {to_display(to_iso)}",
    }


# --- the catalogue ----------------------------------------------------------

def _tool(name: str, says: str, properties: dict[str, Any],
          required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": says,
            "parameters": {"type": "object", "properties": properties,
                           "required": required or []},
        },
    }


_TEXT = {"type": "string"}
_NUMBER = {"type": "number"}
_BOOL = {"type": "boolean"}


CATALOGUE: tuple[dict[str, Any], ...] = (
    _tool("overview", "Where the whole project stands right now: start and finish dates, "
          "float against the contract date, planned and earned progress, hours and CPI. "
          "Call this first when asked anything general about how the project is going.", {}),
    _tool("find_deliverables",
          "Look deliverables up by a word in the name or WBS number, or by state. Use this "
          "to turn what somebody said into the exact WBS numbers before changing anything.",
          {"query": dict(_TEXT, description="A word from the name, or a WBS number like 1.2"),
           "state": {"type": "string",
                     "enum": ["all", "late", "behind", "complete", "in_progress",
                              "not_started", "critical"]},
           "limit": _NUMBER}),
    _tool("deliverable",
          "Everything about one deliverable: its dates, progress, team, float, what it "
          "waits on and what waits on it.",
          {"reference": dict(_TEXT, description="WBS number like 1.2, or words from its name")},
          ["reference"]),
    _tool("period_report",
          "What actually moved between two dates — which deliverables gained progress and "
          "by how much. This is the source for any question about a period, and for a "
          "presentation of work done.",
          {"start": dict(_TEXT, description="dd/mm/yyyy"),
           "end": dict(_TEXT, description="dd/mm/yyyy")}, ["start", "end"]),
    _tool("schedule_summary",
          "The programme: the critical path in order, how many paths there are, what is "
          "late, the teams and their working weeks.", {}),
    _tool("week_ahead",
          "What the project needs this week (or another week): submissions due, approvals "
          "due back, work starting, progress owed, and actions falling due.",
          {"week": dict(_TEXT, description="Any date inside the week, dd/mm/yyyy. "
                        "Leave empty for this week")}),
    _tool("register",
          "Minuted items and actions, from the client's minutes or the internal register. "
          "Can be read as at a past date to answer “where did this stand then?”.",
          {"kind": {"type": "string", "enum": ["client", "internal"]},
           "state": {"type": "string", "enum": ["open", "closed", "overdue", "all"]},
           "as_at": dict(_TEXT, description="dd/mm/yyyy, to rewind the register")}),
    _tool("budget_summary", "Hours by trade: budgeted, booked, earned, CPI and the "
          "estimate at completion.", {}),

    _tool("set_progress",
          "Record progress on a deliverable — either a percentage or the workflow step it "
          "has reached. Prefer the step where the project uses the design workflow, because "
          "the step decides the percentage.",
          {"reference": dict(_TEXT, description="WBS number or words from the name"),
           "percent": dict(_NUMBER, description="0 to 100"),
           "status": dict(_TEXT, description="A workflow step name or key, e.g. Submitted"),
           "note": dict(_TEXT, description="Why, in a few words")}, ["reference"]),
    _tool("set_dates",
          "Move a deliverable's start and submission dates. By default everything that "
          "waits on it moves too.",
          {"reference": _TEXT, "start": dict(_TEXT, description="dd/mm/yyyy"),
           "submission": dict(_TEXT, description="dd/mm/yyyy"),
           "cascade": dict(_BOOL, description="Move dependent deliverables too (default true)")},
          ["reference"]),
    _tool("link_deliverables",
          "Make one deliverable wait on another. FS finish-to-start, SS start-to-start, "
          "FF finish-to-finish, SF start-to-finish.",
          {"predecessor": _TEXT, "successor": _TEXT,
           "kind": {"type": "string", "enum": ["FS", "SS", "FF", "SF"]},
           "lag_days": dict(_NUMBER, description="Working days; negative for a lead")},
          ["predecessor", "successor"]),
    _tool("unlink_deliverables", "Remove the dependency between two deliverables.",
          {"predecessor": _TEXT, "successor": _TEXT}, ["predecessor", "successor"]),
    _tool("raise_item", "Raise an action in the client's minutes or the internal register.",
          {"register": {"type": "string", "enum": ["client", "internal"]},
           "subject": dict(_TEXT, description="What is needed, in a line"),
           "owner": dict(_TEXT, description="PM, Client, MR, ST, GE, WE, EL or PMC"),
           "due": dict(_TEXT, description="dd/mm/yyyy"),
           "agreed": dict(_TEXT, description="The fuller wording, if there is any")},
          ["subject"]),
    _tool("close_item", "Close a minuted item, on the day it was actually closed.",
          {"reference": dict(_TEXT, description="Its number, like 3.1, or words from the subject"),
           "closed_on": dict(_TEXT, description="dd/mm/yyyy; today if left out")}, ["reference"]),
    _tool("add_project_holiday", "Add a holiday for one team or for everybody.",
          {"date": dict(_TEXT, description="dd/mm/yyyy"),
           "team": dict(_TEXT, description="A team name; leave empty for everybody"),
           "name": dict(_TEXT, description="What the holiday is")}, ["date"]),

    _tool("open_view",
          "Give the reader a link to one of the app's own pages, optionally opening straight "
          "into the print dialog so they can save it as a PDF.",
          {"view": {"type": "string", "enum": list(VIEWS)},
           "printable": dict(_BOOL, description="Open the print dialog on arrival"),
           "start": dict(_TEXT, description="For the period report, dd/mm/yyyy"),
           "end": dict(_TEXT, description="For the period report, dd/mm/yyyy")}, ["view"]),
    _tool("presentation",
          "Build a PowerPoint deck of the work done between two dates — the headline "
          "figures, what moved, what is late, and what comes next. Use this whenever "
          "somebody asks for a presentation, a deck or slides.",
          {"start": dict(_TEXT, description="dd/mm/yyyy"),
           "end": dict(_TEXT, description="dd/mm/yyyy"),
           "title": dict(_TEXT, description="A title for the deck")}, ["start", "end"]),
)

# Reading is free; changing is staged and applied by hand. `open_view` and
# `presentation` produce a link rather than a change, so they read as free too.
READ_ONLY: frozenset[str] = frozenset((
    "overview", "find_deliverables", "deliverable", "period_report", "schedule_summary",
    "week_ahead", "register", "budget_summary", "open_view", "presentation",
))

RUNNERS: dict[str, Callable[..., Any]] = {
    "overview": overview,
    "find_deliverables": find_deliverables,
    "deliverable": deliverable,
    "period_report": period_report,
    "schedule_summary": schedule_summary,
    "week_ahead": week_ahead,
    "register": register,
    "budget_summary": budget_summary,
    "set_progress": set_progress,
    "set_dates": set_dates,
    "link_deliverables": link_deliverables,
    "unlink_deliverables": unlink_deliverables,
    "raise_item": raise_item,
    "close_item": close_item,
    "add_project_holiday": add_project_holiday,
    "open_view": open_view,
    "presentation": presentation,
}

WRITES: frozenset[str] = frozenset(RUNNERS) - READ_ONLY


def describe() -> list[dict[str, Any]]:
    """The catalogue as the API wants it."""
    return [dict(tool) for tool in CATALOGUE]


def run(name: str, project_id: int, arguments: Mapping[str, Any]) -> Any:
    """One tool, by name, scoped to one project.

    The project id comes from the URL rather than from the model, so no
    phrasing can reach another project's data.
    """
    runner = RUNNERS.get(str(name))
    if runner is None:
        raise ToolError(f"There is no tool called {name!r}")
    clean = {str(key): value for key, value in dict(arguments or {}).items()
             if key != "project_id"}
    return runner(project_id, **clean)
