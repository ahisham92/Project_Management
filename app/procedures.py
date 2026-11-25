"""The company procedures, as each project's journey through them.

The library (``journey/library.json``) is the PM Procedure Checklist: fifteen
stations from award to close-out, the questions that decide which of its
actions a project needs, and the actions themselves, each with the procedure
section it comes from (PRC-PM-02 and the eighteen procedures around it).

Every project keeps its own progress through it here, on the server, so the
whole team sees one copy: the answers given, which actions are done or not
applicable, notes and target dates. The page itself is the same journey that
ran on its own in a browser (``journey/journey.html``); here it saves to the
project instead of to the browser.

The logic that decides whether an action applies is the page's, written again
in Python so the dashboard and the "needs attention" view can count what is
open without a browser: a condition is true, false, or not yet known because a
question it depends on has not been answered.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .db import execute, query_one

HERE = Path(__file__).resolve().parent / "journey"
LIBRARY_FILE = HERE / "library.json"
PAGE_FILE = HERE / "journey.html"

# The parts of a project's state that are maps of id -> value, and so can be
# changed one key at a time.
MAPS = ("answers", "status", "notes", "due", "skipped", "doneAt", "visited", "ticks")
STATUSES = {"done", "na"}
# How often an action comes round (library "cadences"). The repeating ones are
# ticked once per day, week or month in "ticks", keyed "<action id>|<period>":
# a day is 2026-11-25, a week 2026-W48 (a two-week cycle 2026-F24), a month 2026-11.
REPEATING = {"daily", "weekly", "monthly"}
TICK_PERIOD = re.compile(r"^\d{4}-(\d{2}-\d{2}|W\d{2}|F\d{2}|\d{2})$")


@lru_cache(maxsize=1)
def library() -> dict[str, Any]:
    return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _index() -> dict[str, Any]:
    lib = library()
    questions = {q["id"]: q for q in lib["questions"]}
    stations = {p["id"]: i for i, p in enumerate(lib["phases"])}
    choice = [q for q in lib["questions"] if q.get("opts")]
    # Each question is asked at the first station with an action that needs it,
    # never before a question it depends on: the page's own rule.
    asked: dict[str, int] = {}

    def walk(cond, i):
        for k, v in (cond or {}).items():
            if k == "any":
                for sub in v:
                    walk(sub, i)
            elif k in questions:
                asked[k] = min(asked.get(k, 99), i)

    for it in lib["items"]:
        walk(it.get("when"), stations[it["ph"]])
    for q in choice:
        asked.setdefault(q["id"], 0)
    for q in choice:
        for k in (q.get("show") or {}):
            if asked.get(k, 0) > asked[q["id"]]:
                asked[q["id"]] = asked[k]
    return {"questions": questions, "stations": stations, "choice": choice, "asked": asked,
            "items": {it["id"]: it for it in lib["items"]}}


# --- the logic: True, False, or None (waiting for an answer) ----------------

def _value(key: str, answers: dict) -> Any:
    q = _index()["questions"].get(key)
    if not q:
        return answers.get(key)
    if q.get("show"):
        shown = evaluate(q["show"], answers)
        if shown is False:
            return q["opts"][0][0]
        if shown is None:
            return None
    return answers.get(key)


def evaluate(cond: dict | None, answers: dict) -> bool | None:
    if not cond:
        return True
    result: bool | None = True
    for key, want in cond.items():
        if key == "any":
            subs = [evaluate(c, answers) for c in want]
            r = True if True in subs else (False if all(s is False for s in subs) else None)
        else:
            got = _value(key, answers)
            if got is None:
                r = None
            else:
                r = got in want if isinstance(want, list) else got == want
        if r is False:
            return False
        if r is None:
            result = None
    return result


def item_state(state: dict, item: dict) -> str:
    applies = evaluate(item.get("when"), state.get("answers", {}))
    if applies is False:
        return "hidden"
    if applies is None:
        return "locked"
    return state.get("status", {}).get(item["id"]) or "open"


def _shown(state: dict, q: dict) -> bool:
    return not q.get("show") or evaluate(q["show"], state.get("answers", {})) is True


def waiting_questions(state: dict) -> list[dict]:
    """Questions the project has reached, or skipped, and not yet answered."""
    idx = _index()
    visited = state.get("visited", {})
    skipped = state.get("skipped", {})
    answers = state.get("answers", {})
    out = []
    for q in idx["choice"]:
        if q["id"] in answers or not _shown(state, q):
            continue
        station = idx["asked"][q["id"]]
        if visited.get(str(station)) or visited.get(station) or skipped.get(q["id"]):
            out.append({**q, "station": library()["phases"][station]["s"]})
    return out


def _due(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def summary(state: dict, today: date | None = None) -> dict[str, Any]:
    """What a project's journey adds up to: counts, and the actions that need someone."""
    today = today or date.today()
    lib = library()
    rows = []
    for it in lib["items"]:
        s = item_state(state, it)
        if s != "hidden":
            rows.append((it, s))
    counts = {"open": 0, "done": 0, "na": 0, "locked": 0}
    for _, s in rows:
        counts[s] += 1
    due = state.get("due", {})
    overdue, soon = [], []
    for it, s in rows:
        if s != "open":
            continue
        d = _due(due.get(it["id"]))
        if d is None:
            continue
        entry = {"item": it, "due": d, "days": (d - today).days,
                 "station": lib["phases"][_index()["stations"][it["ph"]]]["s"],
                 "note": state.get("notes", {}).get(it["id"], "")}
        (overdue if d < today else soon).append(entry)
    overdue.sort(key=lambda e: e["due"])
    soon.sort(key=lambda e: e["due"])
    # The next station with anything left to do, and its first open actions.
    stations = []
    for i, ph in enumerate(lib["phases"]):
        its = [(it, s) for it, s in rows if it["ph"] == ph["id"]]
        if not its:
            continue
        left = [it for it, s in its if s in ("open", "locked")]
        stations.append({"id": ph["id"], "name": ph["s"], "total": len(its),
                         "cleared": len(its) - len(left),
                         "open": [it for it, s in its if s == "open"]})
    current = next((s for s in stations if s["cleared"] < s["total"]), None)
    total = len(rows)
    return {
        "counts": counts, "total": total,
        "pct": round((counts["done"] + counts["na"]) / total * 100) if total else 0,
        "overdue": overdue, "soon": [e for e in soon if e["days"] <= 14],
        "waiting": waiting_questions(state),
        "stations": stations, "current": current,
        "stars": sum(1 for s in stations if s["cleared"] == s["total"]),
    }


# --- each project's copy ------------------------------------------------------

def blank_state(project) -> dict[str, Any]:
    return {
        "id": f"project-{project['id']}",
        "created": _now_ms(), "updated": _now_ms(),
        "answers": {"num": project["code"], "title": project["name"]},
        "status": {}, "notes": {}, "due": {}, "skipped": {}, "doneAt": {}, "visited": {}, "ticks": {},
        "stationOrder": _station_order(),
    }


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# The station order the first journeys were saved against. "visited" is kept by
# station position, so a journey saved under an older order is moved across.
FIRST_ORDER = ("start", "init", "contract", "quality", "plan", "bimset", "sustset", "exec",
               "check", "change", "supply", "review", "submit", "close", "aide")


def _station_order() -> list[str]:
    return [p["id"] for p in library()["phases"]]


def _reorder_visited(state: dict) -> None:
    order = _station_order()
    saved = state.get("stationOrder") or list(FIRST_ORDER)
    if saved == order:
        return
    visited = {}
    for k, v in (state.get("visited") or {}).items():
        try:
            sid = saved[int(k)]
        except (ValueError, IndexError):
            continue
        if sid in order:
            visited[str(order.index(sid))] = v
    state["visited"] = visited
    state["stationOrder"] = order


def load_state(project) -> dict[str, Any]:
    row = query_one("SELECT state FROM project_journeys WHERE project_id = ?", (project["id"],))
    if row is not None:
        state = json.loads(row["state"])
        for key in MAPS:
            state.setdefault(key, {})
        _reorder_visited(state)
        state["id"] = f"project-{project['id']}"
        # The project's number and name belong to its Setup; the journey shows
        # them as they are now, not as they were when it was first opened.
        state["answers"]["num"] = project["code"]
        state["answers"]["title"] = project["name"]
        return state
    return blank_state(project)


def save_state(project_id: int, state: dict, user_id: int | None) -> None:
    execute(
        "INSERT INTO project_journeys (project_id, state, updated_by, updated_at)"
        " VALUES (?, ?, ?, datetime('now'))"
        " ON CONFLICT(project_id) DO UPDATE SET state = excluded.state,"
        " updated_by = excluded.updated_by, updated_at = excluded.updated_at",
        (project_id, json.dumps(state, ensure_ascii=False), user_id),
    )


class PatchError(ValueError):
    pass


def apply_patch(state: dict, patch: dict) -> dict:
    """Applies one browser's changes, key by key, to the project's copy.

    A change is sent as only the keys it touched (a null removes one), so two
    people working on different actions at the same time both keep their work.
    """
    if not isinstance(patch, dict):
        raise PatchError("A change must be an object.")
    idx = _index()
    for key, changes in patch.items():
        if key not in MAPS:
            raise PatchError(f"Unknown part '{key}'.")
        if not isinstance(changes, dict):
            raise PatchError(f"'{key}' must be an object.")
        target = state.setdefault(key, {})
        for k, v in changes.items():
            k = str(k)[:80]
            if v is None:
                target.pop(k, None)
                continue
            if key == "answers" and k in ("num", "title"):
                continue  # set in the project's Setup, not here
            if key == "status" and (k not in idx["items"] or v not in STATUSES):
                raise PatchError(f"'{v}' is not a status for '{k}'.")
            if key == "answers" and k in idx["questions"]:
                q = idx["questions"][k]
                if q.get("opts") and v not in {o[0] for o in q["opts"]}:
                    raise PatchError(f"'{v}' is not an answer to '{k}'.")
            if key == "ticks":
                item_id, _, period = k.partition("|")
                it = idx["items"].get(item_id)
                if not it or it.get("cad") not in REPEATING or not TICK_PERIOD.match(period):
                    raise PatchError(f"'{k}' is not a repeating action and period.")
            if key == "due" and v and _due(v) is None:
                raise PatchError(f"'{v}' is not a date.")
            if isinstance(v, str):
                v = v[:4000]
            elif not isinstance(v, (int, float, bool)):
                raise PatchError(f"'{key}.{k}' must be a plain value.")
            target[k] = v
    state["updated"] = _now_ms()
    return state


def page_html(server: dict) -> str:
    """The journey page, with the library and this project's copy built in."""
    html = PAGE_FILE.read_text(encoding="utf-8")
    lib = json.dumps(library(), ensure_ascii=False)
    srv = json.dumps(server, ensure_ascii=False)
    # A closing script tag inside the data would end the block early.
    lib = lib.replace("</", "<\\/")
    srv = srv.replace("</", "<\\/")
    return html.replace("/*LIBRARY*/", lib).replace("/*SERVER*/", srv)
