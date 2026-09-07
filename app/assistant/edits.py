"""The rest of the app, for Carmen: the setup sheet, the deliverable list, the
trade split, the timesheet and the rework a Code B starts.

The reading tools and the everyday changes live in ``tools``. What is here is
the other half — the things somebody would open the Setup tab to do, plus the
bulk change that only makes sense said out loud ("ten percent of every
deliverable is the project manager's"). Same three rules as everywhere else:

* nothing is invented — every tool goes through the service layer a form posts to;
* nothing happens until somebody presses Apply;
* and the setup sheet's own guard still applies. A change here that would edit
  the setup sheet needs what editing the setup sheet needs: manager access, and
  the sheet unlocked in that person's session. Carmen is another way in, not a
  way round.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..dates import to_display
from .common import ApplyError, ToolError, _date, _deliverable, _project

# Changes that edit the setup sheet, and so need it unlocked. Named here rather
# than guessed at from the tool name.
# Changes to the programme itself. The Schedule tab takes manager access to
# move a line, so a change staged here takes the same — Carmen is another way
# in, not another set of rules.
PROGRAMME_KINDS: frozenset[str] = frozenset((
    "set_dates", "add_link", "remove_link", "add_holiday", "squeeze_schedule",
))

SETUP_KINDS: frozenset[str] = frozenset((
    "set_project_settings", "set_trade", "remove_trade", "set_section",
    "set_workflow_step", "remove_workflow_step", "set_team",
    "add_deliverable", "update_deliverable", "remove_deliverable",
    "set_trade_split", "share_across",
))


# --- finding things by the words somebody used ------------------------------

def _one(rows: Sequence[Mapping[str, Any]], reference: Any, what: str,
         field: str = "name") -> dict[str, Any] | None:
    """The row somebody meant, or None if there is no such thing yet.

    Exact first, then a contained word. Two matches is a question, not a coin
    toss: naming the wrong trade in a bulk change is expensive.
    """
    wanted = " ".join(str(reference or "").strip().lower().split())
    if not wanted:
        raise ToolError(f"Say which {what}")
    exact = [r for r in rows if str(r.get(field) or "").strip().lower() == wanted]
    if len(exact) == 1:
        return dict(exact[0])
    near = [r for r in rows if wanted in str(r.get(field) or "").strip().lower()]
    if len(near) == 1:
        return dict(near[0])
    if len(near) > 1:
        listed = ", ".join(str(r.get(field)) for r in near[:8])
        raise ToolError(f"That matches more than one {what}: {listed}. Say which.")
    return None


def _trade(project_id: int, reference: Any) -> dict[str, Any]:
    from ..service import load_trades

    trades = load_trades(project_id)
    found = _one(trades, reference, "trade")
    if found is None:
        names = ", ".join(t["name"] for t in trades) or "none yet"
        raise ToolError(
            f"No trade called {reference!r}. The trades are: {names}. If you have just "
            "staged adding it, say so — it has to be applied before anything can be "
            "given a share of it.")
    return found


def _whole_percent(value: Any, what: str, low: float = 0, high: float = 100) -> int:
    """A percentage as a whole number.

    The trade split on the Setup sheet is kept in whole percents — that is what
    its boxes hold and what its "must total 100%" check reads. A split written
    here in tenths would look right until somebody pressed Save all and was told
    their line totals 101%, so it is refused at the door instead.
    """
    number = _number(value, what, low=low, high=high)
    if abs(number - round(number)) > 1e-9:
        raise ToolError(f"{what} has to be a whole number of percent — the trade split is "
                        f"kept in whole percents, so say {int(number)} or {int(number) + 1}, "
                        f"not {number:g}")
    return int(round(number))


def _rescaled(allocations: Mapping[Any, float], trade_id: Any, share: int) -> dict[Any, float]:
    """One line's split with a trade put on ``share`` percent of it.

    The trades already there keep their proportions to each other inside what is
    left, and the rounding difference goes on the largest of them so the line
    still totals exactly 100.
    """
    others = {k: float(v) for k, v in allocations.items() if k != trade_id and v}
    total = sum(others.values())
    if total <= 0:
        return {}
    left = 100 - share
    exact = {k: v / total * left for k, v in others.items()}
    whole = {k: int(round(v)) for k, v in exact.items()}
    drift = left - sum(whole.values())
    if drift:
        whole[max(whole, key=lambda k: exact[k])] += drift
    out = {k: v / 100 for k, v in whole.items() if v > 0}
    out[trade_id] = share / 100
    return out


def _number(value: Any, what: str, low: float | None = None,
            high: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ToolError(f"{what} has to be a number — got {value!r}") from None
    if low is not None and number < low:
        raise ToolError(f"{what} cannot be less than {low:g}")
    if high is not None and number > high:
        raise ToolError(f"{what} cannot be more than {high:g}")
    return number


# --- reading ----------------------------------------------------------------

def setup_sheet(project_id: int, **_ignored) -> dict[str, Any]:
    """Everything on the Setup tab, so a change can be made against what is
    actually there rather than against what was assumed."""
    from ..calendars import week_label
    from ..offices import name_of as office_name
    from ..service import (load_calendars, load_holidays, load_sections, load_steps,
                           load_tasks, load_trades)
    from ..workflow import ordered

    project = _project(project_id)
    default_team = project.get("calendar_id")
    return {
        "project": {
            "code": project.get("code"), "name": project.get("name"),
            "client": project.get("client"), "status": project.get("status"),
            "ntp_date": to_display(project.get("ntp_date")),
            "duration_months": project.get("duration_months"),
            "days_per_month": project.get("days_per_month"),
            "hours_per_month": project.get("hours_per_month"),
            "max_revisions": project.get("max_revisions"),
            "rework_days": project.get("rework_days"),
            "schedule_mode": project.get("schedule_mode"),
            "currency": project.get("currency"),
        },
        "trades": [{"name": t["name"], "office": office_name(t["office"]) if t["office"] else "",
                    "budget_hours": t["budget_hours"], "colour": t["color"]}
                   for t in load_trades(project_id)],
        "sections": [{"code": s["code"], "name": s["name"]} for s in load_sections(project_id)],
        "workflow": [{"name": s["name"], "key": s["key"],
                      "percent": round(float(s["percent"]) * 100, 2),
                      "anchor": s["anchor"], "offset_days": s["offset_days"]}
                     for s in ordered(load_steps(project_id))],
        "teams": [{"name": c["name"], "working_week": week_label(c["workdays"]),
                   "is_default": c["id"] == default_team}
                  for c in load_calendars(project_id)],
        "holidays": [{"date": to_display(h["holiday_date"]), "name": h["name"],
                      "team": h["calendar_name"] or "everybody"}
                     for h in load_holidays(project_id)][:60],
        "deliverable_count": len(load_tasks(project_id)),
    }


def trade_split(project_id: int, reference: str = "", **_ignored) -> dict[str, Any]:
    """One deliverable's trade split, as percentages that total 100."""
    from ..offices import name_of as office_name
    from ..service import load_trades

    task = _deliverable(project_id, reference)
    trades = {t["id"]: t for t in load_trades(project_id)}
    split = []
    for trade_id, share in (task.get("allocations") or {}).items():
        trade = trades.get(trade_id)
        if trade and share:
            split.append({"trade": trade["name"],
                          "office": office_name(trade["office"]) if trade["office"] else "",
                          "percent": round(float(share) * 100, 2)})
    split.sort(key=lambda row: -row["percent"])
    return {"wbs": task["wbs"], "name": task["name"], "split": split,
            "totals_percent": round(sum(row["percent"] for row in split), 2)}


def timesheet(project_id: int, start: str = "", end: str = "", **_ignored) -> dict[str, Any]:
    """Hours booked in a period, by trade and by person."""
    from ..db import query
    from ..service import today

    from_iso = _date(start, "The start of the period") if start else ""
    to_iso = _date(end, "The end of the period") if end else today()
    if from_iso and to_iso < from_iso:
        from_iso, to_iso = to_iso, from_iso

    rows = query(
        """
        SELECT e.entry_date, e.hours, e.description, u.name AS who,
               tr.name AS trade, t.wbs AS wbs, t.name AS deliverable
        FROM time_entries e
        LEFT JOIN users u ON u.id = e.user_id
        LEFT JOIN trades tr ON tr.id = e.trade_id
        LEFT JOIN tasks t ON t.id = e.task_id
        WHERE e.project_id = ? AND e.entry_date <= ? AND e.entry_date >= ?
        ORDER BY e.entry_date DESC, e.id DESC
        """,
        (project_id, to_iso, from_iso or "0000-01-01"),
    )
    by_trade: dict[str, float] = {}
    by_person: dict[str, float] = {}
    total = 0.0
    for row in rows:
        hours = float(row["hours"] or 0)
        total += hours
        by_trade[row["trade"] or "no trade"] = by_trade.get(row["trade"] or "no trade", 0) + hours
        by_person[row["who"] or "unknown"] = by_person.get(row["who"] or "unknown", 0) + hours

    return {
        "from": to_display(from_iso) if from_iso else "the beginning",
        "to": to_display(to_iso),
        "total_hours": round(total, 1),
        "by_trade": [{"trade": k, "hours": round(v, 1)} for k, v in sorted(by_trade.items(), key=lambda kv: -kv[1])],
        "by_person": [{"who": k, "hours": round(v, 1)} for k, v in sorted(by_person.items(), key=lambda kv: -kv[1])],
        "entries": [{"date": to_display(r["entry_date"]), "hours": round(float(r["hours"] or 0), 2),
                     "who": r["who"] or "", "trade": r["trade"] or "",
                     "deliverable": f"{r['wbs'] or ''} {r['deliverable'] or ''}".strip(),
                     "description": r["description"] or ""}
                    for r in rows[:60]],
    }


# --- changing the setup sheet -----------------------------------------------

FIELDS: dict[str, tuple[str, str]] = {
    # name on the tool -> (column, how to read it)
    "name": ("name", "text"),
    "client": ("client", "text"),
    "status": ("status", "status"),
    "ntp_date": ("ntp_date", "date"),
    "duration_months": ("duration_months", "positive"),
    "days_per_month": ("days_per_month", "positive"),
    "hours_per_month": ("hours_per_month", "positive"),
    "max_revisions": ("max_revisions", "count"),
    "rework_days": ("rework_days", "positive"),
    "schedule_mode": ("schedule_mode", "mode"),
    "currency": ("currency", "text"),
}

STATUSES = ("active", "on_hold", "complete", "archived")


def set_project_settings(project_id: int, **asked) -> dict[str, Any]:
    """Change the project's own settings — the top card of the Setup sheet."""
    from ..schedule import normalise_mode

    project = _project(project_id)
    fields: dict[str, Any] = {}
    said: list[str] = []

    for given, value in asked.items():
        if given not in FIELDS or value in (None, ""):
            continue
        column, kind = FIELDS[given]
        if kind == "date":
            fields[column] = _date(value, "The notice to proceed")
            said.append(f"NTP {to_display(fields[column])}")
        elif kind == "positive":
            fields[column] = _number(value, given.replace("_", " "), low=0.0001)
            said.append(f"{given.replace('_', ' ')} {fields[column]:g}")
        elif kind == "count":
            fields[column] = int(_number(value, given.replace("_", " "), low=0, high=99))
            said.append(f"{given.replace('_', ' ')} {fields[column]}")
        elif kind == "status":
            wanted = str(value).strip().lower().replace(" ", "_")
            if wanted not in STATUSES:
                raise ToolError(f"A project is {', '.join(STATUSES)} — not {value!r}")
            fields[column] = wanted
            said.append(f"status {wanted}")
        elif kind == "mode":
            fields[column] = normalise_mode(value)
            said.append(f"schedule entered by {fields[column]}")
        else:
            fields[column] = str(value).strip()[:120]
            said.append(f"{given} “{fields[column]}”")

    if not fields:
        raise ToolError("Nothing there to change. The settings are: "
                        + ", ".join(FIELDS))
    return {"kind": "set_project_settings", "fields": fields,
            "says": f"{project['code']}: " + ", ".join(said)}


def set_trade(project_id: int, trade: str = "", office: str = "", budget_hours: Any = None,
              rename_to: str = "", colour: str = "", **_ignored) -> dict[str, Any]:
    """Add a trade, or change one: its office, its hour budget, its name."""
    from ..offices import OFFICES, name_of as office_name, normalise as normalise_office
    from ..service import load_trades

    wanted = str(trade or "").strip()
    if not wanted:
        raise ToolError("Say which trade — its name")
    found = _one(load_trades(project_id), wanted, "trade")

    plan: dict[str, Any] = {"kind": "set_trade", "trade_id": found["id"] if found else None,
                            "name": found["name"] if found else wanted[:60]}
    said: list[str] = []

    if office:
        key = normalise_office(office)
        if not key:
            known = ", ".join(name for _k, name in OFFICES)
            raise ToolError(f"{office!r} is not one of the offices. They are: {known}")
        plan["office"] = key
        said.append(office_name(key))
    if budget_hours is not None and budget_hours != "":
        plan["budget_hours"] = _number(budget_hours, "The budget", low=0)
        said.append(f"{plan['budget_hours']:g} hours")
    if rename_to:
        plan["rename_to"] = str(rename_to).strip()[:60]
        said.append(f"renamed to “{plan['rename_to']}”")
    if colour:
        shade = str(colour).strip()
        if not (shade.startswith("#") and len(shade) == 7):
            raise ToolError("A colour is a hex value like #2a78d6")
        plan["colour"] = shade

    if found is None:
        plan["says"] = f"Add the trade “{plan['name']}”" + (f" — {', '.join(said)}" if said else "")
    elif not said and "colour" not in plan:
        raise ToolError(f"Nothing to change on {found['name']}")
    else:
        plan["says"] = f"{found['name']}: " + (", ".join(said) or "new colour")
    return plan


def remove_trade(project_id: int, trade: str = "", **_ignored) -> dict[str, Any]:
    """Take a trade off the project, and its share of every deliverable with it."""
    found = _trade(project_id, trade)
    return {"kind": "remove_trade", "trade_id": found["id"], "name": found["name"],
            "says": f"Remove the trade “{found['name']}” and its share of every deliverable"}


def set_section(project_id: int, section: str = "", code: str = "", rename_to: str = "",
                **_ignored) -> dict[str, Any]:
    """Add a section, or rename one."""
    from ..service import load_sections

    wanted = str(section or "").strip()
    if not wanted:
        raise ToolError("Say which section — its name")
    found = _one(load_sections(project_id), wanted, "section")

    plan: dict[str, Any] = {"kind": "set_section", "section_id": found["id"] if found else None,
                            "name": (rename_to or (found or {}).get("name") or wanted).strip()[:120],
                            "code": str(code or (found or {}).get("code") or "").strip()[:20]}
    plan["says"] = (f"Add the section “{plan['name']}”" if found is None
                    else f"Section “{found['name']}” → “{plan['name']}”"
                         + (f" ({plan['code']})" if plan["code"] else ""))
    return plan


def set_workflow_step(project_id: int, step: str = "", percent: Any = None, anchor: str = "",
                      offset_days: Any = None, rename_to: str = "", **_ignored) -> dict[str, Any]:
    """Add a workflow step, or change what one means."""
    from ..service import load_steps

    wanted = str(step or "").strip()
    if not wanted:
        raise ToolError("Say which workflow step — its name")
    steps = load_steps(project_id)
    found = _one(steps, wanted, "workflow step")

    plan: dict[str, Any] = {"kind": "set_workflow_step", "step_id": found["id"] if found else None,
                            "name": (rename_to or (found or {}).get("name") or wanted).strip()[:60]}
    said: list[str] = []
    if percent is not None and percent != "":
        plan["percent"] = _number(percent, "The percent", low=0, high=100) / 100
        said.append(f"{plan['percent'] * 100:g}%")
    elif found is None:
        raise ToolError("A new workflow step needs the percent complete it represents")
    if anchor:
        which = str(anchor).strip().lower()
        if which not in ("start", "submission"):
            raise ToolError("A step is anchored to 'start' or to 'submission'")
        plan["anchor"] = which
        said.append(f"from the {which}")
    if offset_days is not None and offset_days != "":
        plan["offset_days"] = _number(offset_days, "The offset")
        said.append(f"{plan['offset_days']:+g} days")

    plan["says"] = ((f"Add the workflow step “{plan['name']}”" if found is None
                     else f"Workflow step “{found['name']}”")
                    + (" — " + ", ".join(said) if said else ""))
    return plan


def remove_workflow_step(project_id: int, step: str = "", **_ignored) -> dict[str, Any]:
    """Take a step out of the workflow."""
    from ..service import load_steps

    steps = load_steps(project_id)
    found = _one(steps, step, "workflow step")
    if found is None:
        names = ", ".join(s["name"] for s in steps)
        raise ToolError(f"No workflow step called {step!r}. They are: {names}")
    return {"kind": "remove_workflow_step", "step_id": found["id"], "name": found["name"],
            "says": f"Remove the workflow step “{found['name']}”"}


def set_team(project_id: int, team: str = "", working_week: str = "", rename_to: str = "",
             is_default: Any = None, **_ignored) -> dict[str, Any]:
    """Add a team with its working week, or change one's."""
    from ..calendars import WEEK_PATTERNS, normalise_week, week_label
    from ..service import load_calendars

    wanted = str(team or "").strip()
    if not wanted:
        raise ToolError("Say which team — its name")
    found = _one(load_calendars(project_id), wanted, "team")

    plan: dict[str, Any] = {"kind": "set_team", "calendar_id": found["id"] if found else None,
                            "name": (rename_to or (found or {}).get("name") or wanted).strip()[:60]}
    said: list[str] = []
    if working_week:
        asked = str(working_week).strip().lower()
        named = next((week for week, label in WEEK_PATTERNS if label.lower() == asked), "")
        week = named or normalise_week(working_week)
        if not named and set(str(working_week).strip()) - set("01yYtTnN"):
            known = "; ".join(label for _w, label in WEEK_PATTERNS)
            raise ToolError(f"{working_week!r} is not a working week. Try one of: {known}, "
                            "or seven characters like 1111100 starting on Monday.")
        plan["workdays"] = week
        said.append(week_label(week))
    elif found is None:
        raise ToolError("A new team needs its working week")
    if is_default:
        plan["is_default"] = True
        said.append("the project's default team")

    plan["says"] = ((f"Add the team “{plan['name']}”" if found is None
                     else f"Team “{found['name']}”")
                    + (" — " + ", ".join(said) if said else ""))
    return plan


# --- the deliverable list ---------------------------------------------------

def add_deliverable(project_id: int, name: str = "", section: str = "", wbs: str = "",
                    weight: Any = None, start: str = "", submission: str = "",
                    tracking: str = "workflow", **_ignored) -> dict[str, Any]:
    """Add a deliverable to the list."""
    from ..service import load_sections

    title = " ".join(str(name or "").split())
    if not title:
        raise ToolError("A deliverable needs a name")
    if not submission:
        raise ToolError("A deliverable needs a submission date")

    section_row = _one(load_sections(project_id), section, "section") if section else None
    if section and section_row is None:
        names = ", ".join(s["name"] for s in load_sections(project_id)) or "none yet"
        raise ToolError(f"No section called {section!r}. The sections are: {names}")

    submit = _date(submission, "The submission")
    began = _date(start, "The start") if start else submit
    if began > submit:
        began, submit = submit, began
    how = "simple" if str(tracking or "").strip().lower() in ("simple", "percent") else "workflow"

    return {
        "kind": "add_deliverable", "name": title[:200], "wbs": str(wbs or "").strip()[:20],
        "section_id": section_row["id"] if section_row else None,
        "weight_points": _number(weight, "The weight", low=0) if weight not in (None, "") else 0.0,
        "start": began, "submission": submit, "tracking": how,
        "says": (f"Add {(str(wbs).strip() + ' ') if wbs else ''}“{title[:60]}”"
                 + (f" to {section_row['name']}" if section_row else "")
                 + f", {to_display(began)} to {to_display(submit)}"),
    }


def update_deliverable(project_id: int, reference: str = "", name: str = "", wbs: str = "",
                       weight: Any = None, section: str = "", remarks: str = "",
                       tracking: str = "", team: str = "", **_ignored) -> dict[str, Any]:
    """Change a deliverable itself — its name, number, weight, section or team."""
    from ..service import load_calendars, load_sections

    task = _deliverable(project_id, reference)
    plan: dict[str, Any] = {"kind": "update_deliverable", "task_id": task["id"],
                            "wbs_was": task["wbs"], "fields": {}}
    said: list[str] = []

    if name:
        plan["fields"]["name"] = " ".join(str(name).split())[:200]
        said.append(f"named “{plan['fields']['name'][:50]}”")
    if wbs:
        plan["fields"]["wbs"] = str(wbs).strip()[:20]
        said.append(f"numbered {plan['fields']['wbs']}")
    if weight not in (None, ""):
        plan["fields"]["weight_points"] = _number(weight, "The weight", low=0)
        said.append(f"weight {plan['fields']['weight_points']:g}")
    if remarks:
        plan["fields"]["remarks"] = str(remarks).strip()[:500]
        said.append("remarks")
    if tracking:
        how = str(tracking).strip().lower()
        if how not in ("workflow", "simple", "percent"):
            raise ToolError("A deliverable is tracked by 'workflow' or by 'simple' percentage")
        plan["fields"]["tracking"] = "simple" if how in ("simple", "percent") else "workflow"
        said.append(f"tracked by {plan['fields']['tracking']}")
    if section:
        found = _one(load_sections(project_id), section, "section")
        if found is None:
            names = ", ".join(s["name"] for s in load_sections(project_id)) or "none yet"
            raise ToolError(f"No section called {section!r}. The sections are: {names}")
        plan["fields"]["section_id"] = found["id"]
        said.append(f"in {found['name']}")
    if team:
        found = _one(load_calendars(project_id), team, "team")
        if found is None:
            names = ", ".join(c["name"] for c in load_calendars(project_id))
            raise ToolError(f"No team called {team!r}. The teams are: {names}")
        plan["fields"]["calendar_id"] = found["id"]
        said.append(f"on the {found['name']} calendar")

    if not plan["fields"]:
        raise ToolError("Nothing there to change on that deliverable")
    plan["says"] = f"{task['wbs']} {task['name'][:50]}: " + ", ".join(said)
    return plan


def remove_deliverable(project_id: int, reference: str = "", **_ignored) -> dict[str, Any]:
    """Take a deliverable off the project, with its progress and its links."""
    task = _deliverable(project_id, reference)
    return {"kind": "remove_deliverable", "task_id": task["id"],
            "says": (f"Remove {task['wbs']} “{task['name'][:60]}” — its progress history "
                     f"and its dependencies go with it")}


# --- the trade split --------------------------------------------------------

def _as_shares(project_id: int, split: Any) -> dict[int, float]:
    """A {trade: percent} mapping turned into trade ids and fractions."""
    if not isinstance(split, Mapping) or not split:
        raise ToolError("Give the split as trade names against percentages, "
                        "like {\"Marine\": 60, \"Utilities\": 40}")
    shares: dict[int, float] = {}
    for named, value in split.items():
        trade = _trade(project_id, named)
        shares[trade["id"]] = shares.get(trade["id"], 0.0) + _whole_percent(
            value, f"{trade['name']}'s share") / 100
    total = sum(shares.values())
    if abs(total - 1) > 0.005:
        raise ToolError(f"A trade split has to total 100% — that one totals {total * 100:.1f}%")
    return shares


def set_trade_split(project_id: int, reference: str = "", split: Any = None,
                    **_ignored) -> dict[str, Any]:
    """Set one deliverable's trade split."""
    from ..service import load_trades

    task = _deliverable(project_id, reference)
    shares = _as_shares(project_id, split)
    names = {t["id"]: t["name"] for t in load_trades(project_id)}
    said = ", ".join(f"{names[k]} {v * 100:g}%" for k, v in shares.items())
    return {"kind": "set_trade_split", "task_id": task["id"],
            "shares": {str(k): v for k, v in shares.items()},
            "says": f"{task['wbs']} {task['name'][:50]} split {said}"}


def share_across(project_id: int, trade: str = "", percent: Any = None, section: str = "",
                 only: Any = None, **_ignored) -> dict[str, Any]:
    """Give one trade a share of every deliverable, rescaling the others.

    This is the one bulk change, and it is here because it is the one people
    actually ask for out loud: the project manager has a hand in everything, so
    a slice of every line is theirs. The other trades keep their proportions to
    each other inside what is left — a 60/40 line under a 10% project manager
    is 54/36/10, because 60/40/10 totals 110% and would be refused.
    """
    from ..service import load_sections, load_tasks

    mine = _trade(project_id, trade)
    whole = _whole_percent(percent, "The share", low=0, high=90)
    share = whole / 100
    if share <= 0:
        raise ToolError("A share of nothing is not a change — say what percent")

    wanted = load_tasks(project_id)
    scope = "every deliverable"
    if section:
        found = _one(load_sections(project_id), section, "section")
        if found is None:
            names = ", ".join(s["name"] for s in load_sections(project_id)) or "none yet"
            raise ToolError(f"No section called {section!r}. The sections are: {names}")
        wanted = [t for t in wanted if t.get("section_id") == found["id"]]
        scope = f"every deliverable in {found['name']}"
    elif only:
        listed = only if isinstance(only, (list, tuple)) else [only]
        wanted = [_deliverable(project_id, one) for one in listed]
        scope = f"{len(wanted)} deliverable" + ("s" if len(wanted) != 1 else "")

    changed, already, skipped = [], 0, []
    for task in wanted:
        allocations = {k: float(v) for k, v in (task.get("allocations") or {}).items() if v}
        others = {k: v for k, v in allocations.items() if k != mine["id"]}
        if not others:
            # Nothing to take the share out of. What that line's split should
            # be is a question for a person, not something to invent quietly
            # across fifty rows.
            skipped.append(f"{task['wbs'] or task['name'][:30]}")
            continue
        if abs(allocations.get(mine["id"], 0.0) - share) <= 0.005:
            already += 1
            continue
        changed.append(task["id"])

    if not changed:
        if already and not skipped:
            raise ToolError(f"{mine['name']} already has {share * 100:g}% of {scope}")
        raise ToolError(
            f"Nothing to change: {already} already at {share * 100:g}%"
            + (f", and {len(skipped)} with no other trade to take it out of "
               f"({', '.join(skipped[:6])})" if skipped else ""))

    return {
        "kind": "share_across", "trade_id": mine["id"], "share": share, "percent": whole,
        "task_ids": changed,
        "says": (f"{mine['name']} takes {share * 100:g}% of {scope} — {len(changed)} "
                 f"deliverable{'s' if len(changed) != 1 else ''} rescaled"
                 + (f", {already} already there" if already else "")
                 + (f", {len(skipped)} skipped for having no other trade" if skipped else "")),
        "note": {"changing": len(changed), "already": already, "skipped": skipped[:20]},
    }


# --- squeezing the programme ------------------------------------------------

def squeeze_schedule(project_id: int, start_at: str = "", end_at: str = "", days: Any = None,
                     **_ignored) -> dict[str, Any]:
    """Fit a run of deliverables into fewer working days.

    Worked out here rather than described: what comes back is the real proposal
    — every line's new duration and dates, the new finish, and what it saves —
    so what is staged is what will happen.
    """
    from ..service import squeeze_plan
    from ..squeeze import SqueezeError

    first = _deliverable(project_id, start_at)
    last = _deliverable(project_id, end_at)
    if days in (None, ""):
        raise ToolError("Say how many working days the run has to fit into")
    want = int(_number(days, "The stretch", low=1, high=3650))

    try:
        proposal = squeeze_plan(_project(project_id), first["id"], last["id"], want)
    except SqueezeError as exc:
        raise ToolError(str(exc)) from None

    moved = len(proposal["changes"])
    after = len(proposal["after"])
    return {
        "kind": "squeeze_schedule",
        "first_id": first["id"], "last_id": last["id"], "days": want,
        "says": (f"Squeeze {first['wbs']} → {last['wbs']} into {want} working days: "
                 f"{moved} deliverable{'s' if moved != 1 else ''} come down from "
                 f"{proposal['was_days']} days of work to {proposal['days']}, finishing "
                 f"{to_display(proposal['finish'])}"
                 + (f", {proposal['saved_days']} days earlier" if proposal["saved_days"] > 0
                    else f", {-proposal['saved_days']} days later" if proposal["saved_days"] < 0
                    else "")
                 + (f", and {after} line{'s' if after != 1 else ''} after it move with it"
                    if after else "")),
        "note": {
            "lines": [{"wbs": c["wbs"], "was_days": c["was_days"], "days": c["days"],
                       "start": to_display(c["start"]),
                       "submission": to_display(c["submission"])}
                      for c in proposal["changes"][:25]],
            "finish": to_display(proposal["finish"]),
            "was_finish": to_display(proposal["was_finish"]),
            "waiting_does_not_compress": not proposal["reaches_target"],
        },
    }


# --- the timesheet and the rework ------------------------------------------

def book_hours(project_id: int, date: str = "", hours: Any = None, trade: str = "",
               deliverable: str = "", description: str = "", **_ignored) -> dict[str, Any]:
    """Book hours to the timesheet."""
    when = _date(date, "The day") if date else ""
    worked = _number(hours, "The hours", low=0.01, high=24)
    trade_row = _trade(project_id, trade) if trade else None
    task = _deliverable(project_id, deliverable) if deliverable else None

    return {
        "kind": "book_hours", "entry_date": when, "hours": worked,
        "trade_id": trade_row["id"] if trade_row else None,
        "task_id": task["id"] if task else None,
        "description": str(description or "").strip()[:200],
        "says": (f"Book {worked:g}h"
                 + (f" to {trade_row['name']}" if trade_row else "")
                 + (f" on {task['wbs']}" if task else "")
                 + (f" for {to_display(when)}" if when else " for today")),
    }


def return_comments(project_id: int, reference: str = "", code: str = "B",
                    comments_date: str = "", new_submission: str = "", note: str = "",
                    **_ignored) -> dict[str, Any]:
    """Record that the client returned comments — a Code B or C — on a submission."""
    from ..service import normalise_code, today

    task = _deliverable(project_id, reference)
    which = normalise_code(code) or "B"
    if which == "A":
        raise ToolError("A Code A is an approval — record it as the workflow step, "
                        "not as comments")
    when = _date(comments_date, "The day the comments came back") if comments_date else today()
    resubmit = _date(new_submission, "The new submission") if new_submission else ""

    return {
        "kind": "return_comments", "task_id": task["id"], "code": which,
        "comments_date": when, "new_submission": resubmit,
        "note": str(note or "").strip()[:300],
        "says": (f"{task['wbs']} {task['name'][:50]}: Code {which} on {to_display(when)} — "
                 f"revision {int(task.get('revision') or 0) + 1}"
                 + (f", resubmit {to_display(resubmit)}" if resubmit
                    else " (resubmission from the project's rework days)")),
    }


def add_attendee(project_id: int, name: str = "", organisation: str = "", job_title: str = "",
                 email: str = "", **_ignored) -> dict[str, Any]:
    """Put somebody on the attendance roster the minutes are built from."""
    from ..service import load_attendees

    who = " ".join(str(name or "").split())
    if not who:
        raise ToolError("A person needs a name")
    if _one(load_attendees(project_id), who, "attendee"):
        raise ToolError(f"{who} is already on the roster")

    return {"kind": "add_attendee", "name": who[:120],
            "organisation": str(organisation or "").strip()[:120],
            "job_title": str(job_title or "").strip()[:120],
            "email": str(email or "").strip()[:160],
            "says": f"Add {who[:60]} to the roster"
                    + (f" ({str(organisation).strip()[:40]})" if organisation else "")}


# --- the catalogue ----------------------------------------------------------

def _tool(name: str, says: str, properties: dict[str, Any],
          required: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "description": says,
            "input_schema": {"type": "object", "properties": properties,
                             "required": required or []}}


_TEXT = {"type": "string"}
_NUMBER = {"type": "number"}

CATALOGUE: tuple[dict[str, Any], ...] = (
    _tool("setup_sheet",
          "Everything on the Setup tab: the project's settings, its trades and their offices, "
          "sections, workflow steps, teams and holidays. Read this before changing any of them.",
          {}),
    _tool("trade_split", "How one deliverable is split between the trades.",
          {"reference": {"type": "string", "description": "WBS number or name"}},
          ["reference"]),
    _tool("timesheet", "Hours booked in a period, totalled by trade and by person.",
          {"start": {"type": "string", "description": "dd/mm/yyyy; omitted means from the start"},
           "end": {"type": "string", "description": "dd/mm/yyyy; omitted means today"}}),

    _tool("set_project_settings",
          "Change the project's own settings on the Setup sheet. Give only what changes.",
          {"name": _TEXT, "client": _TEXT,
           "status": {"type": "string", "enum": list(STATUSES)},
           "ntp_date": {"type": "string", "description": "Notice to proceed, dd/mm/yyyy"},
           "duration_months": _NUMBER, "days_per_month": _NUMBER, "hours_per_month": _NUMBER,
           "max_revisions": _NUMBER, "rework_days": _NUMBER,
           "schedule_mode": {"type": "string", "enum": ["duration", "dates"]},
           "currency": _TEXT}),
    _tool("set_trade",
          "Add a trade, or change one: which office carries it, its hour budget, its name. "
          "A trade that is not there yet is added.",
          {"trade": {"type": "string", "description": "The trade's name"},
           "office": {"type": "string", "description": "Beirut or Cairo"},
           "budget_hours": _NUMBER, "rename_to": _TEXT,
           "colour": {"type": "string", "description": "Hex, like #2a78d6"}},
          ["trade"]),
    _tool("remove_trade", "Remove a trade, and its share of every deliverable with it.",
          {"trade": _TEXT}, ["trade"]),
    _tool("set_section", "Add a section, or rename one.",
          {"section": _TEXT, "code": _TEXT, "rename_to": _TEXT}, ["section"]),
    _tool("set_workflow_step",
          "Add a workflow step or change one: the percent it represents, whether it is measured "
          "from the start or the submission, and by how many days.",
          {"step": _TEXT, "percent": {"type": "number", "description": "0 to 100"},
           "anchor": {"type": "string", "enum": ["start", "submission"]},
           "offset_days": {"type": "number", "description": "Negative is before the anchor"},
           "rename_to": _TEXT},
          ["step"]),
    _tool("remove_workflow_step", "Remove a step from the workflow.", {"step": _TEXT}, ["step"]),
    _tool("set_team",
          "Add a team with its working week, or change one. The week is a name like "
          "'Sunday to Thursday' or seven characters like 1111100 starting on Monday.",
          {"team": _TEXT, "working_week": _TEXT, "rename_to": _TEXT,
           "is_default": {"type": "boolean"}},
          ["team"]),

    _tool("add_deliverable", "Add a deliverable to the project.",
          {"name": _TEXT, "section": _TEXT, "wbs": _TEXT, "weight": _NUMBER,
           "start": {"type": "string", "description": "dd/mm/yyyy"},
           "submission": {"type": "string", "description": "dd/mm/yyyy"},
           "tracking": {"type": "string", "enum": ["workflow", "simple"]}},
          ["name", "submission"]),
    _tool("update_deliverable",
          "Change a deliverable itself: its name, WBS number, weight, section, remarks, how it "
          "is tracked, or the team whose working week it is planned against. Dates go through "
          "set_dates instead.",
          {"reference": _TEXT, "name": _TEXT, "wbs": _TEXT, "weight": _NUMBER,
           "section": _TEXT, "remarks": _TEXT,
           "tracking": {"type": "string", "enum": ["workflow", "simple"]}, "team": _TEXT},
          ["reference"]),
    _tool("remove_deliverable",
          "Remove a deliverable, with its progress history and its dependencies.",
          {"reference": _TEXT}, ["reference"]),

    _tool("set_trade_split",
          "Set one deliverable's trade split. The percentages have to total 100.",
          {"reference": _TEXT,
           "split": {"type": "object", "description":
                     "Trade names against percentages, e.g. {\"Marine\": 60, \"Utilities\": 40}",
                     "additionalProperties": {"type": "number"}}},
          ["reference", "split"]),
    _tool("share_across",
          "Give one trade a share of every deliverable, rescaling the other trades on each line "
          "to fit what is left. This is how a project manager gets a slice of everything. "
          "Applies to the whole project unless a section or a list of deliverables is named.",
          {"trade": _TEXT, "percent": {"type": "number", "description": "0 to 90"},
           "section": {"type": "string", "description": "Limit it to one section"},
           "only": {"type": "array", "items": {"type": "string"},
                    "description": "Limit it to these deliverables, by WBS or name"}},
          ["trade", "percent"]),

    _tool("squeeze_schedule",
          "Fit a run of deliverables — from one line to another along the dependencies — into "
          "a given number of working days. Every line's duration comes down in proportion to "
          "what it already is, in whole days with the leftover day going to the shorter lines, "
          "and everything that waits on the run is pulled forward with it. Use this whenever "
          "somebody wants the programme compressed rather than moving lines one at a time.",
          {"start_at": {"type": "string", "description": "The line the run starts on, by WBS or name"},
           "end_at": {"type": "string", "description": "The line it ends on, by WBS or name"},
           "days": {"type": "number", "description": "Working days the whole run has to fit into"}},
          ["start_at", "end_at", "days"]),
    _tool("book_hours", "Book hours to the timesheet.",
          {"date": {"type": "string", "description": "dd/mm/yyyy; omitted means today"},
           "hours": _NUMBER, "trade": _TEXT, "deliverable": _TEXT, "description": _TEXT},
          ["hours"]),
    _tool("return_comments",
          "Record that the client returned comments — a Code B or C — on a deliverable that has "
          "been submitted. It raises the revision and reschedules the resubmission.",
          {"reference": _TEXT, "code": {"type": "string", "enum": ["B", "C"]},
           "comments_date": {"type": "string", "description": "dd/mm/yyyy; omitted means today"},
           "new_submission": {"type": "string", "description":
                              "dd/mm/yyyy; omitted uses the project's rework days"},
           "note": _TEXT},
          ["reference"]),
    _tool("add_attendee", "Put somebody on the attendance roster the minutes are built from.",
          {"name": _TEXT, "organisation": _TEXT, "job_title": _TEXT, "email": _TEXT},
          ["name"]),
)

READ_ONLY: frozenset[str] = frozenset(("setup_sheet", "trade_split", "timesheet"))

RUNNERS: dict[str, Any] = {
    "setup_sheet": setup_sheet,
    "trade_split": trade_split,
    "timesheet": timesheet,
    "set_project_settings": set_project_settings,
    "set_trade": set_trade,
    "remove_trade": remove_trade,
    "set_section": set_section,
    "set_workflow_step": set_workflow_step,
    "remove_workflow_step": remove_workflow_step,
    "set_team": set_team,
    "add_deliverable": add_deliverable,
    "update_deliverable": update_deliverable,
    "remove_deliverable": remove_deliverable,
    "set_trade_split": set_trade_split,
    "share_across": share_across,
    "squeeze_schedule": squeeze_schedule,
    "book_hours": book_hours,
    "return_comments": return_comments,
    "add_attendee": add_attendee,
}


# --- doing what was approved ------------------------------------------------
#
# Every one goes through the same function a form posts to. Nothing here writes
# a table the screens do not write, which is what makes "another way in, not
# another set of rules" true rather than a claim.

def _own(project_id: int, table: str, row_id: Any, what: str) -> dict[str, Any]:
    from ..db import query_one

    row = query_one(f"SELECT * FROM {table} WHERE id = ? AND project_id = ?", (row_id, project_id))
    if row is None:
        raise ApplyError(f"That {what} is no longer on this project")
    return dict(row)


def apply_one(project_id: int, action: Mapping[str, Any], user_id: int, stamp: str) -> str:
    """One staged change, carried out. Returns what to say it did.

    Raises ``KeyError`` for a kind this module knows nothing about, so the
    caller can go on looking.
    """
    from ..db import execute, insert
    from ..service import (as_dict, load_steps, load_trades, next_sort_order,
                           record_comments, set_allocations)

    kind = str(action.get("kind") or "")
    says = str(action.get("says") or kind)

    if kind == "set_project_settings":
        fields = {k: v for k, v in dict(action.get("fields") or {}).items()
                  if k in {column for column, _how in FIELDS.values()}}
        if not fields:
            raise ApplyError("There is nothing to change on the project")
        execute("UPDATE projects SET " + ", ".join(f"{name} = ?" for name in fields)
                + ", updated_at = datetime('now') WHERE id = ?",
                (*fields.values(), project_id))

    elif kind == "set_trade":
        trade_id = action.get("trade_id")
        if trade_id:
            trade = _own(project_id, "trades", trade_id, "trade")
            execute("UPDATE trades SET name = ?, office = ?, budget_hours = ?, color = ? "
                    "WHERE id = ? AND project_id = ?",
                    (str(action.get("rename_to") or trade["name"])[:60],
                     str(action.get("office", trade["office"]) or ""),
                     float(action.get("budget_hours", trade["budget_hours"]) or 0),
                     str(action.get("colour") or trade["color"]),
                     trade["id"], project_id))
        else:
            name = str(action.get("name") or "").strip()[:60]
            if not name:
                raise ApplyError("A trade needs a name")
            key = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
            insert("INSERT INTO trades (project_id, key, name, budget_hours, color, office, "
                   "sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (project_id, key or f"trade_{next_sort_order('trades', project_id)}", name,
                    float(action.get("budget_hours") or 0),
                    str(action.get("colour") or "#2a78d6"), str(action.get("office") or ""),
                    next_sort_order("trades", project_id)))

    elif kind == "remove_trade":
        _own(project_id, "trades", action.get("trade_id"), "trade")
        execute("DELETE FROM trades WHERE id = ? AND project_id = ?",
                (action["trade_id"], project_id))

    elif kind == "set_section":
        if action.get("section_id"):
            _own(project_id, "sections", action["section_id"], "section")
            execute("UPDATE sections SET name = ?, code = ? WHERE id = ? AND project_id = ?",
                    (str(action.get("name") or "")[:120], str(action.get("code") or "")[:20],
                     action["section_id"], project_id))
        else:
            insert("INSERT INTO sections (project_id, code, name, sort_order) VALUES (?, ?, ?, ?)",
                   (project_id, str(action.get("code") or "")[:20],
                    str(action.get("name") or "")[:120], next_sort_order("sections", project_id)))

    elif kind == "set_workflow_step":
        if action.get("step_id"):
            step = _own(project_id, "workflow_steps", action["step_id"], "workflow step")
            execute("UPDATE workflow_steps SET name = ?, percent = ?, anchor = ?, offset_days = ? "
                    "WHERE id = ? AND project_id = ?",
                    (str(action.get("name") or step["name"])[:60],
                     float(action.get("percent", step["percent"]) or 0),
                     str(action.get("anchor") or step["anchor"]),
                     float(action.get("offset_days", step["offset_days"]) or 0),
                     step["id"], project_id))
        else:
            name = str(action.get("name") or "").strip()[:60]
            key = "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")
            if not key:
                raise ApplyError("A workflow step needs a name")
            insert("INSERT INTO workflow_steps (project_id, key, name, percent, anchor, "
                   "offset_days, sort_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (project_id, key, name, float(action.get("percent") or 0),
                    str(action.get("anchor") or "submission"),
                    float(action.get("offset_days") or 0),
                    next_sort_order("workflow_steps", project_id)))

    elif kind == "remove_workflow_step":
        _own(project_id, "workflow_steps", action.get("step_id"), "workflow step")
        execute("DELETE FROM workflow_steps WHERE id = ? AND project_id = ?",
                (action["step_id"], project_id))

    elif kind == "set_team":
        from ..service import add_calendar, save_calendar, set_default_calendar

        calendar_id = action.get("calendar_id")
        if calendar_id:
            team = _own(project_id, "calendars", calendar_id, "team")
            save_calendar(project_id, int(calendar_id), str(action.get("name") or team["name"]),
                          str(action.get("workdays") or team["workdays"]))
        else:
            calendar_id = add_calendar(project_id, str(action.get("name") or ""),
                                       str(action.get("workdays") or ""))
        if action.get("is_default"):
            set_default_calendar(project_id, int(calendar_id))

    elif kind == "add_deliverable":
        from ..service import load_tasks

        task_id = insert(
            """
            INSERT INTO tasks (project_id, section_id, wbs, name, weight_points,
                               start_date, submission_date, tracking, remarks, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?)
            """,
            (project_id, action.get("section_id"), str(action.get("wbs") or "")[:20],
             str(action.get("name") or "")[:200], float(action.get("weight_points") or 0),
             str(action.get("start") or ""), str(action.get("submission") or ""),
             str(action.get("tracking") or "workflow"), next_sort_order("tasks", project_id)),
        )
        # An even split across the trades, the way the Setup form starts one, so
        # the line is measurable rather than weightless.
        trades = load_trades(project_id)
        if trades:
            set_allocations(task_id, project_id, {t["id"]: 1 / len(trades) for t in trades})
        says = says + f" (line {task_id})"

    elif kind == "update_deliverable":
        _own(project_id, "tasks", action.get("task_id"), "deliverable")
        allowed = {"name", "wbs", "weight_points", "section_id", "remarks", "tracking",
                   "calendar_id"}
        fields = {k: v for k, v in dict(action.get("fields") or {}).items() if k in allowed}
        if not fields:
            raise ApplyError("There is nothing to change on that deliverable")
        execute("UPDATE tasks SET " + ", ".join(f"{name} = ?" for name in fields)
                + ", updated_at = datetime('now') WHERE id = ? AND project_id = ?",
                (*fields.values(), action["task_id"], project_id))

    elif kind == "remove_deliverable":
        _own(project_id, "tasks", action.get("task_id"), "deliverable")
        execute("DELETE FROM tasks WHERE id = ? AND project_id = ?",
                (action["task_id"], project_id))

    elif kind == "set_trade_split":
        _own(project_id, "tasks", action.get("task_id"), "deliverable")
        shares = {int(k): float(v) for k, v in dict(action.get("shares") or {}).items()}
        set_allocations(int(action["task_id"]), project_id, shares)

    elif kind == "share_across":
        from ..service import load_tasks

        trade_id = int(action.get("trade_id") or 0)
        whole = int(action.get("percent") or round(float(action.get("share") or 0) * 100))
        _own(project_id, "trades", trade_id, "trade")
        wanted = {int(i) for i in action.get("task_ids") or []}
        if not wanted:
            raise ApplyError("There are no deliverables left to change")
        done = 0
        for task in load_tasks(project_id):
            if task["id"] not in wanted:
                continue
            allocations = {k: float(v) for k, v in (task.get("allocations") or {}).items() if v}
            split = _rescaled(allocations, trade_id, whole)
            if not split:
                # It had another trade when this was staged and has not got one
                # now. Skipped rather than guessed at, same as when it was read.
                continue
            set_allocations(task["id"], project_id, split)
            done += 1
        if not done:
            raise ApplyError("None of those deliverables has another trade to take the share out of")
        says = f"{says} — {done} done"

    elif kind == "squeeze_schedule":
        from ..service import apply_squeeze, squeeze_plan
        from ..squeeze import SqueezeError

        from ..db import query_one

        project = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project is None:
            raise ApplyError("That project is no longer there")
        try:
            # Worked out again from the two ends and the number of days rather
            # than from dates that travelled to a page and back.
            proposal = squeeze_plan(project, int(action["first_id"]), int(action["last_id"]),
                                    int(action.get("days") or 0))
        except SqueezeError as exc:
            raise ApplyError(str(exc)) from exc
        outcome = apply_squeeze(project_id, proposal)
        says = (f"{says} — {outcome['squeezed']} squeezed"
                + (f", {outcome['followed']} moved with them" if outcome["followed"] else ""))

    elif kind == "book_hours":
        from ..service import today

        insert("INSERT INTO time_entries (project_id, trade_id, task_id, user_id, entry_date, "
               "hours, description) VALUES (?, ?, ?, ?, ?, ?, ?)",
               (project_id, action.get("trade_id"), action.get("task_id"), user_id,
                str(action.get("entry_date") or stamp or today()),
                float(action.get("hours") or 0), str(action.get("description") or "")[:200]))

    elif kind == "return_comments":
        from ..db import query_one

        task = _own(project_id, "tasks", action.get("task_id"), "deliverable")
        project = as_dict(query_one("SELECT * FROM projects WHERE id = ?", (project_id,)))
        try:
            outcome = record_comments(
                task, project, load_steps(project_id),
                str(action.get("comments_date") or stamp),
                str(action.get("new_submission") or ""),
                str(action.get("note") or ""), user_id, str(action.get("code") or "B"))
        except Exception as exc:                       # noqa: BLE001 - said, not swallowed
            raise ApplyError(str(exc)) from exc
        says = (f"{says} — now revision {outcome['revision']}, resubmission "
                f"{to_display(outcome['submission_date'])}")

    elif kind == "add_attendee":
        insert("INSERT INTO attendees (project_id, name, organisation, job_title, email, "
               "sort_order) VALUES (?, ?, ?, ?, ?, ?)",
               (project_id, str(action.get("name") or "")[:120],
                str(action.get("organisation") or "")[:120],
                str(action.get("job_title") or "")[:120], str(action.get("email") or "")[:160],
                next_sort_order("attendees", project_id)))

    else:
        raise KeyError(kind)

    return says
