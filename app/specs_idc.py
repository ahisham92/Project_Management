"""IDC: the inter-disciplinary check between a project's trades.

One trade sends its specification to the project's other trades. While the
IDC is open their engineers read it and put their input in as tracked
changes: a paragraph reworded, one added after another, one taken out, each
with why. Nothing in the specification changes until its own engineers
accept a change; a rejected one stays on the IDC with the answer given. And
while it is open the trades' documents are checked against each other, so
what the project is (its standards, design life, exposure, client) and the
answers both trades give read the same in both.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from . import specs, specs_trades
from . import specs_store as store
from .db import execute, get_db, query, query_one

KINDS = {"reword": "Reworded", "add": "Added after", "remove": "Taken out"}


# --- the IDC ----------------------------------------------------------------------

def _now() -> str:
    return query_one("SELECT datetime('now') AS t")["t"]


def _name(user: Mapping[str, Any]) -> str:
    return user["name"] or user["email"]


def idc(idc_id: int) -> dict | None:
    row = query_one("SELECT * FROM spec_idcs WHERE id = ?", (idc_id,))
    return _shaped(row) if row else None


def _shaped(row: Mapping[str, Any]) -> dict:
    out = dict(row)
    out["trade_list"] = [t for t in (row["trades"] or "").split(",") if t]
    out["trade_names"] = [specs_trades.name(t) for t in out["trade_list"]]
    counts = query_one("SELECT COUNT(*) AS n, SUM(state = 'open') AS open, SUM(state = 'accepted') AS accepted, "
                       "SUM(state = 'rejected') AS rejected FROM spec_idc_changes WHERE idc_id = ? "
                       "AND state != 'withdrawn'", (row["id"],))
    out.update({k: counts[k] or 0 for k in ("n", "open", "accepted", "rejected")})
    return out


def open_idc(set_id: int) -> dict | None:
    row = query_one("SELECT * FROM spec_idcs WHERE set_id = ? AND state = 'open' ORDER BY id DESC LIMIT 1",
                    (set_id,))
    return _shaped(row) if row else None


def idcs(set_id: int) -> list[dict]:
    return [_shaped(r) for r in query("SELECT * FROM spec_idcs WHERE set_id = ? ORDER BY id DESC", (set_id,))]


def to_trades(row: Mapping[str, Any]) -> list[dict]:
    """The trades an IDC of this specification can go to: the project's
    other trades, each with its specification of the project if it has one."""
    mine = specs_trades.clean(row.get("trade"))
    have = {specs_trades.clean(s.get("trade")): s for s in specs_trades.siblings(row)}
    return [{"code": c["code"], "name": c["name"], "set": have.get(c["code"])}
            for c in specs_trades.choices() if c["code"] != mine]


def send(row: Mapping[str, Any], trades: list[str], note: str, user: Mapping[str, Any]) -> int:
    from .specs_review import note as history

    if open_idc(row["id"]):
        raise specs.SpecError("An IDC of this specification is open already: close it before sending another.")
    mine = specs_trades.clean(row.get("trade"))
    trades = [t for t in specs_trades.CODES if t in trades and t != mine]
    if not trades:
        raise specs.SpecError("Tick the trades the IDC goes to.")
    cur = execute("INSERT INTO spec_idcs (set_id, trades, note, state, sent_by, sent_by_name, sent_at) "
                  "VALUES (?, ?, ?, 'open', ?, ?, ?)",
                  (row["id"], ",".join(trades), note.strip(), user["id"], _name(user), _now()))
    history(row["id"], "idc", "IDC sent", "", ", ".join(specs_trades.name(t) for t in trades)
            + (f": {note.strip()}" if note.strip() else ""))
    return cur.lastrowid


def close(row: Mapping[str, Any], it: Mapping[str, Any], user: Mapping[str, Any]) -> None:
    from .specs_review import note as history

    execute("UPDATE spec_idcs SET state = 'closed', closed_by_name = ?, closed_at = ? WHERE id = ?",
            (_name(user), _now(), it["id"]))
    left = it["open"]
    history(row["id"], "idc", "IDC closed", "",
            f"{it['accepted']} accepted, {it['rejected']} rejected"
            + (f", {left} left undecided" if left else ""))


# --- who does what ----------------------------------------------------------------

def may_decide(row: Mapping[str, Any], user: Any) -> bool:
    """The specification's own engineers accept or reject the input."""
    from .specs_review import may

    return may(row, user, "edit")


def may_propose(row: Mapping[str, Any], it: Mapping[str, Any] | None, user: Any) -> bool:
    """The engineers of a trade the IDC went to: their account's trade, or a
    place on the team of their trade's specification of the project."""
    if user is None or not it or it["state"] != "open":
        return False
    if specs_trades.of_user(user) in it["trade_list"]:
        return True
    for s in specs_trades.siblings(row):
        if specs_trades.clean(s.get("trade")) in it["trade_list"] and query_one(
                "SELECT 1 FROM spec_set_members WHERE set_id = ? AND user_id = ?", (s["id"], user["id"])):
            return True
    return False


def waiting_for(user: Any) -> list[dict]:
    """The open IDCs this user is asked for input on, with the specification
    each one is of."""
    out = []
    for r in query("SELECT i.*, s.name AS set_name, s.trade AS set_trade, s.code AS set_code "
                   "FROM spec_idcs i JOIN spec_sets s ON s.id = i.set_id WHERE i.state = 'open' ORDER BY i.id DESC"):
        row = store.spec_set(r["set_id"])
        it = _shaped(r)
        if row and may_propose(row, it, user):
            it.update({"set_name": r["set_name"], "set_code": r["set_code"],
                       "from_trade": specs_trades.name(specs_trades.clean(r["set_trade"]))})
            out.append(it)
    return out


# --- the input, as tracked changes ------------------------------------------------

def words_of(row: Mapping[str, Any], section: Mapping[str, Any]) -> list[dict]:
    """A section's paragraphs as they read for the project now: id, level,
    number and words written out."""
    from .specs_review import issued_words

    found = issued_words(row, [section])
    return found[0]["nodes"] if found else []


def propose(row: Mapping[str, Any], it: Mapping[str, Any], row_id: int, node_id: str, kind: str,
            text: str, why: str, user: Mapping[str, Any], level: str = "") -> int:
    if kind not in KINDS:
        raise specs.SpecError("Say how the paragraph changes.")
    section = store.set_section(row["id"], row_id)
    if section is None:
        raise specs.SpecError("That section is not in this specification any more.")
    words = {p["id"]: p for p in words_of(row, section)}
    here = words.get(node_id)
    if here is None:
        raise specs.SpecError("That paragraph is not in the section as it reads now.")
    text = " ".join((text or "").split())
    if kind == "reword":
        if not text:
            raise specs.SpecError("Write the paragraph as it should read, or propose taking it out.")
        if text == here["text"]:
            raise specs.SpecError("The words are the same as they read now.")
    if kind == "add" and not text:
        raise specs.SpecError("Write the paragraph to add.")
    if kind == "remove":
        text = ""
    level = level if level in specs.KINDS else here["level"]
    trade = specs_trades.of_user(user) or next(iter(it["trade_list"]), "")
    cur = execute(
        "INSERT INTO spec_idc_changes (idc_id, set_id, row_id, node_id, kind, level, old_text, new_text, why, "
        "by_user, by_name, trade, at, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')",
        (it["id"], row["id"], row_id, node_id, kind, level, here["text"] if kind != "add" else "", text,
         (why or "").strip(), user["id"], _name(user), trade, _now()))
    return cur.lastrowid


def change(change_id: int) -> dict | None:
    r = query_one("SELECT * FROM spec_idc_changes WHERE id = ?", (change_id,))
    return dict(r) if r else None


def changes(idc_id: int, row_id: int | None = None) -> list[dict]:
    sql, args = "SELECT * FROM spec_idc_changes WHERE idc_id = ? AND state != 'withdrawn'", [idc_id]
    if row_id is not None:
        sql += " AND row_id = ?"
        args.append(row_id)
    out = []
    for r in query(sql + " ORDER BY id", args):
        c = dict(r)
        c["trade_name"] = specs_trades.name(c["trade"])
        c["kind_name"] = KINDS.get(c["kind"], c["kind"])
        if c["kind"] == "reword":
            from .specs_export import word_diff
            c["diff"] = word_diff(c["old_text"], c["new_text"])
        out.append(c)
    return out


def by_section(idc_id: int) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for c in changes(idc_id):
        n = out.setdefault(c["row_id"], {"n": 0, "open": 0})
        n["n"] += 1
        n["open"] += c["state"] == "open"
    return out


def withdraw(change_id: int, user: Mapping[str, Any]) -> None:
    c = change(change_id)
    if not c or c["by_user"] != user["id"] or c["state"] != "open":
        raise specs.SpecError("Only an open change of your own can be taken back.")
    execute("UPDATE spec_idc_changes SET state = 'withdrawn' WHERE id = ?", (change_id,))


def decide(row: Mapping[str, Any], change_id: int, accept: bool, answer: str,
           user: Mapping[str, Any]) -> dict:
    """A change accepted (written into the section, as the specification's
    own change, with who put it in) or rejected with the answer given."""
    from . import specs_review as review

    c = change(change_id)
    if not c or c["set_id"] != row["id"]:
        raise specs.SpecError("That change is not on this specification's IDC.")
    if c["state"] != "open":
        raise specs.SpecError("That change is decided already.")
    stale = False
    if accept:
        section = store.set_section(row["id"], c["row_id"])
        if section is None:
            raise specs.SpecError("That section is not in this specification any more.")
        nodes = specs.loads(section["body"])
        at = next((i for i, n in enumerate(nodes) if n["id"] == c["node_id"]), None)
        if at is None:
            raise specs.SpecError("The paragraph it changes has been taken out since: reject it instead.")
        now = {p["id"]: p["text"] for p in words_of(row, section)}
        stale = c["kind"] != "add" and now.get(c["node_id"], c["old_text"]) != c["old_text"]
        if c["kind"] == "reword":
            nodes[at] = {**nodes[at], "text": c["new_text"]}
        elif c["kind"] == "add":
            nodes.insert(at + 1, specs.node(c["level"] or nodes[at]["level"], c["new_text"]))
        else:
            del nodes[at]
        # The page's own history watch records the paragraph as changed.
        store.save_set_section(row["id"], c["row_id"], nodes)
    execute("UPDATE spec_idc_changes SET state = ?, answer = ?, decided_by_name = ?, decided_at = ? WHERE id = ?",
            ("accepted" if accept else "rejected", (answer or "").strip(), _name(user), _now(), change_id))
    review.note(row["id"], "idc", f"IDC change by {c['by_name']} {'accepted' if accept else 'rejected'}",
                c["old_text"], c["new_text"] if accept else (answer or "").strip(), row_id=c["row_id"])
    return {"stale": stale, "change": c}


# --- the documents checked against each other ---------------------------------------

PROJECT_FIELDS = (("name", "Project name"), ("code", "Project code"), ("client", "Client"),
                  ("city", "City"), ("country", "Country"))


def between(row: Mapping[str, Any]) -> list[dict]:
    """Where the project's specifications say different things: what the
    project is (its fields and the brief answers every trade shares), every
    question both trades answer, and a section both put in. Each with what
    this one and the other say, and where to change it."""
    from . import specs_questions

    others = [s for s in specs_trades.siblings(row) if s["id"] != row["id"]]
    if not others:
        return []
    labels = {o["key"]: o["label"] for o in store.options()}
    questions = specs_questions.definitions()
    mine_chosen = store.chosen_for(row, scope=False)
    mine_answers = specs_questions.answers_of(row)
    mine_sections = {s["number"]: s for s in store.set_sections(row["id"])}
    out = []
    for other in others:
        trade = specs_trades.name(specs_trades.clean(other.get("trade")))
        base = {"trade": trade, "other_id": other["id"]}
        for field, label in PROJECT_FIELDS:
            a, b = (row.get(field) or "").strip(), (other.get(field) or "").strip()
            if a and b and a.lower() != b.lower():
                out.append({**base, "kind": "project", "what": label, "here": a, "there": b, "key": field})
        theirs = store.chosen_for(other, scope=False)
        for key in sorted(specs_trades.SHARED_KEYS):
            a, b = mine_chosen.get(key) or "", theirs.get(key) or ""
            if a and b and _set(a) != _set(b):
                out.append({**base, "kind": "brief", "what": labels.get(key, key), "here": a.replace("|", ", "),
                            "there": b.replace("|", ", "), "key": key})
        their_answers = specs_questions.answers_of(other)
        for key in sorted(set(mine_answers) & set(their_answers)):
            if key.startswith("_") or "@" in key and key.split("@")[0].startswith("_"):
                continue
            a, b = str(mine_answers[key] or ""), str(their_answers[key] or "")
            if a and b and _set(a) != _set(b):
                q = questions.get(key.split("@")[0]) or {}
                label = q.get("label") or key.replace("_", " ")
                if "@" in key:
                    label += f" ({key.split('@')[1].replace('_', ' ')})"
                out.append({**base, "kind": "answer", "what": label, "here": a.replace("|", ", "),
                            "there": b.replace("|", ", "), "key": key})
        for s in store.set_sections(other["id"]):
            if s["number"] in mine_sections:
                out.append({**base, "kind": "section", "what": f"{s['number']} {s['title']}",
                            "here": "In this specification", "there": f"In the {trade.lower()} specification too",
                            "key": s["number"]})
    return out


def _set(value: str) -> frozenset:
    return frozenset(specs._norm(v) for v in str(value).split("|") if v.strip())


def summary_json(it: Mapping[str, Any]) -> str:
    return json.dumps({k: it[k] for k in ("n", "open", "accepted", "rejected")})
