"""Questions handed to a team before the IDC.

An engineer writing a specification meets a question another team answers
better: the concrete mix to the materials team, the dredging tolerances to
the marine unit. They ask that team for it. The team's engineers see it on
their THEMIS start page and answer it with the question's own buttons and
why; nothing is written into the specification until its own engineers
accept the answer. One they do not accept goes back to the team with a note.
This is the coordination inside and across trades that comes before the
IDC, which is the trades reading each other's finished words.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from . import specs, specs_trades
from .db import execute, query, query_one

# (code, name, the trade it sits under, what it answers)
TEAMS = (
    ("materials", "Materials team", specs_trades.GEOTECHNICAL,
     "Concrete mixes, cement and aggregates, durability, fill and testing."),
    ("marine", "Marine unit", specs_trades.GEOTECHNICAL,
     "Dredging, reclamation, revetments, marine exposure and the works by the sea."),
)
CODES = tuple(t[0] for t in TEAMS)

ASKED, ANSWERED, ACCEPTED, WITHDRAWN = "asked", "answered", "accepted", "withdrawn"
STATE_NAMES = {ASKED: "Waiting for the team", ANSWERED: "Answered, to accept",
               ACCEPTED: "Accepted", WITHDRAWN: "Taken back"}


def clean(code: str | None) -> str:
    code = (code or "").strip().lower()
    return code if code in CODES else ""


def name(code: str | None) -> str:
    return next((n for c, n, _t, _w in TEAMS if c == clean(code)), "")


def choices() -> list[dict]:
    return [{"code": c, "name": n, "trade": t, "trade_name": specs_trades.name(t), "note": w}
            for c, n, t, w in TEAMS]


# --- accounts -------------------------------------------------------------------

def of_user(user: Mapping[str, Any] | None) -> str:
    """The account's team, '' when it is in none."""
    if user is None:
        return ""
    try:
        return clean(user["themis_team"])
    except (KeyError, IndexError):
        return ""


def set_user_team(user_id: int, team: str | None) -> None:
    execute("UPDATE users SET themis_team = ? WHERE id = ?", (clean(team), user_id))


def members(team: str) -> list[dict]:
    from .specs_review import candidates

    return [u for u in candidates() if clean(u.get("themis_team")) == team]


# --- the asks -------------------------------------------------------------------

def _now() -> str:
    return query_one("SELECT datetime('now') AS t")["t"]


def _name(user: Mapping[str, Any]) -> str:
    return user["name"] or user["email"]


def _shaped(row: Mapping[str, Any]) -> dict:
    out = dict(row)
    out["team_name"] = name(row["team"])
    out["state_name"] = STATE_NAMES.get(row["state"], row["state"])
    try:
        out["given"] = json.loads(row["answer"] or "{}")
    except ValueError:
        out["given"] = {}
    out["split"] = out["given"].pop("__split__", {}) if isinstance(out["given"], dict) else {}
    try:
        out["thread"] = json.loads(row["thread"] or "[]")
    except ValueError:
        out["thread"] = []
    return out


def ask(ask_id: int) -> dict | None:
    row = query_one("SELECT * FROM spec_asks WHERE id = ?", (ask_id,))
    return _shaped(row) if row else None


def of_set(set_id: int, live: bool = False) -> list[dict]:
    sql = "SELECT * FROM spec_asks WHERE set_id = ?"
    if live:
        sql += " AND state IN ('asked', 'answered')"
    return [_shaped(r) for r in query(sql + " ORDER BY id DESC", (set_id,))]


def live_by_key(set_id: int) -> dict[str, dict]:
    """The question each open ask is about, for its card to say so."""
    return {a["qkey"]: a for a in reversed(of_set(set_id, live=True))}


def for_team(team: str, state: str = ASKED) -> list[dict]:
    """The asks a team has to answer, each with the project it is for."""
    if not clean(team):
        return []
    rows = query("SELECT a.*, s.name AS set_name, s.code AS set_code, s.trade AS set_trade "
                 "FROM spec_asks a JOIN spec_sets s ON s.id = a.set_id "
                 "WHERE a.team = ? AND a.state = ? ORDER BY a.id", (team, state))
    return [_shaped(r) for r in rows]


def answered_for(user: Mapping[str, Any]) -> list[dict]:
    """The answers waiting on this engineer to accept: on the specifications
    they may change, of the asks they or their team made."""
    from . import specs_store as store
    from .specs_review import may

    rows = query("SELECT a.*, s.name AS set_name, s.code AS set_code, s.trade AS set_trade "
                 "FROM spec_asks a JOIN spec_sets s ON s.id = a.set_id "
                 "WHERE a.state = 'answered' ORDER BY a.id")
    out = []
    for r in rows:
        spec = store.spec_set(r["set_id"])
        if spec and may(spec, user, "edit") and r["answered_by"] != user["id"]:
            out.append(_shaped(r))
    return out


def _note(a: Mapping[str, Any], who: str, said: str, kind: str) -> str:
    thread = list(a.get("thread") or [])
    thread.append({"who": who, "said": said, "kind": kind, "at": _now()})
    return json.dumps(thread, ensure_ascii=False)


def send(row: Mapping[str, Any], q: Mapping[str, Any], team: str, note: str,
         user: Mapping[str, Any], to_user: int | None = None) -> int:
    from .specs_review import note as history

    team = clean(team)
    if not team:
        raise specs.SpecError("Pick the team to ask.")
    if any(a["qkey"] == q["key"] for a in of_set(row["id"], live=True)):
        raise specs.SpecError("This question is with a team already: wait for their answer, or take it back first.")
    if to_user and not any(u["id"] == to_user for u in members(team)):
        to_user = None
    to_name = next((u["name"] for u in members(team) if u["id"] == to_user), "")
    cur = execute(
        "INSERT INTO spec_asks (set_id, qkey, label, team, to_user, to_name, note, asked_by, asked_by_name, "
        "asked_at, state, thread) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'asked', '[]')",
        (row["id"], q["key"], q.get("label") or q["key"], team, to_user, to_name, note.strip(),
         user["id"], _name(user), _now()))
    history(row["id"], "ask", f"Asked the {name(team)}", "",
            f"{q.get('label') or q['key']}" + (f" ({to_name})" if to_name else "")
            + (f": {note.strip()}" if note.strip() else ""))
    return cur.lastrowid


def may_answer(a: Mapping[str, Any], user: Any) -> bool:
    """The team's engineers answer it, while it waits on them."""
    return user is not None and a["state"] == ASKED and of_user(user) == a["team"]


def may_decide(row: Mapping[str, Any], a: Mapping[str, Any], user: Any) -> bool:
    """The specification's own engineers accept it, never the one who answered."""
    from .specs_review import may

    return (user is not None and a["state"] == ANSWERED and may(row, user, "edit")
            and a["answered_by"] != user["id"])


def answer(a: Mapping[str, Any], given: dict, split: dict, why: str, user: Mapping[str, Any]) -> None:
    from .specs_review import note as history

    if not any(v is not None for k, v in given.items()):
        raise specs.SpecError("Pick or type the answer first.")
    packed = dict(given)
    packed["__split__"] = split
    execute("UPDATE spec_asks SET state = 'answered', answer = ?, why = ?, answered_by = ?, answered_by_name = ?, "
            "answered_at = ?, thread = ? WHERE id = ?",
            (json.dumps(packed, ensure_ascii=False), why.strip(), user["id"], _name(user), _now(),
             _note(a, _name(user), shown(given, a["qkey"]) + (f". {why.strip()}" if why.strip() else ""),
                   "answer"), a["id"]))
    history(a["set_id"], "ask", f"{name(a['team'])} answered", "", f"{a['label']}: {shown(given, a['qkey'])}")


def accept(a: Mapping[str, Any], user: Mapping[str, Any]) -> None:
    """The answer written into the specification as the engineer's own."""
    from . import specs_questions

    specs_questions.save_answers(a["set_id"], a["given"], a["split"])
    execute("UPDATE spec_asks SET state = 'accepted', decided_by_name = ?, decided_at = ?, thread = ? WHERE id = ?",
            (_name(user), _now(), _note(a, _name(user), "Accepted", "accept"), a["id"]))


def send_back(a: Mapping[str, Any], why: str, user: Mapping[str, Any]) -> None:
    from .specs_review import note as history

    if not why.strip():
        raise specs.SpecError("Say why it goes back, for the team to answer again.")
    execute("UPDATE spec_asks SET state = 'asked', thread = ? WHERE id = ?",
            (_note(a, _name(user), why.strip(), "back"), a["id"]))
    history(a["set_id"], "ask", f"Answer sent back to the {name(a['team'])}", "", f"{a['label']}: {why.strip()}")


def withdraw(a: Mapping[str, Any], user: Mapping[str, Any]) -> None:
    from .specs_review import note as history

    execute("UPDATE spec_asks SET state = 'withdrawn', decided_by_name = ?, decided_at = ? WHERE id = ?",
            (_name(user), _now(), a["id"]))
    history(a["set_id"], "ask", f"Question taken back from the {name(a['team'])}", "", a["label"])


def shown(given: Mapping[str, Any], key: str) -> str:
    """An answer in words: the question's own, then any per element."""
    main = given.get(key)
    words = "left out" if main == "" else (main or "")
    rows = [f"{k.partition('@')[2].replace('_', ' ')}: {v or 'left out'}"
            for k, v in given.items() if k.startswith(key + "@") and v is not None]
    return "; ".join([w for w in [words] if w] + rows) or "no answer"
