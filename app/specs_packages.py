"""Packages of one project.

A project is often specified in packages (package 1 by one team, package 2
by another), each a specification of its own, owned by whoever started it.
Specifications with the same project code are packages of one project. What
one package says should not contradict what another has already issued: the
same section worded differently, or a question answered another way. Each
package is checked against the latest issue of every other package of its
project, and each difference is shown in red for its team to take the other
package's wording (accept) or keep their own (reject, with a reason). A
difference nobody has decided stays flagged on the package until somebody
does; a decision holds only for the two wordings it was made on.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from . import specs, specs_questions
from . import specs_store as store
from .db import execute, insert, query, query_one


def _user_id() -> int | None:
    from flask import g

    user = g.get("user")
    return user["id"] if user is not None else None


def project_key(code: str | None) -> str:
    """The project a specification belongs to: its code, spaces and case aside."""
    return "".join((code or "").split()).upper()


def package_name(row: Mapping[str, Any]) -> str:
    return (row.get("package") or "").strip() or row.get("name") or ""


def _latest_records(key: str, but: int) -> dict[int, dict]:
    """The latest issue of each other package of the project, by package."""
    out: dict[int, dict] = {}
    for r in query("SELECT * FROM spec_issue_records WHERE set_id IS NOT NULL AND set_id != ? "
                   "ORDER BY id", (but,)):
        if project_key(r["code"]) == key:
            out[r["set_id"]] = dict(r)            # later rows replace earlier ones
    return out


def peers(row: Mapping[str, Any]) -> list[dict]:
    """The other packages of this project: those still here, issued or not,
    and those deleted after they were issued (what they issued still binds)."""
    from . import specs_trades

    key = project_key(row.get("code"))
    if not key:
        return []
    # Packages are of one trade: the project's other trades' specifications
    # are not packages of this one (they are checked against it in an IDC).
    trade = specs_trades.clean(row.get("trade"))
    issued = _latest_records(key, row["id"])
    out, seen = [], set()
    for s in query("SELECT s.*, u.name AS owner FROM spec_sets s LEFT JOIN users u "
                   "ON u.id = s.created_by WHERE s.id != ? ORDER BY s.id", (row["id"],)):
        if project_key(s["code"]) != key:
            continue
        if specs_trades.clean(s["trade"]) != trade:
            seen.add(s["id"])
            continue
        seen.add(s["id"])
        rec = issued.get(s["id"])
        out.append({"set_id": s["id"], "name": s["name"], "package": package_name(dict(s)),
                    "owner": s["owner"] or "", "alive": True, "record": rec,
                    "revision": rec["revision"] if rec else "", "issue_date": rec["issue_date"] if rec else ""})
    for set_id, rec in issued.items():
        if set_id in seen:
            continue
        shot = json.loads(rec["snapshot"] or "{}")
        if specs_trades.clean((shot.get("project") or {}).get("trade")) != trade:
            continue
        out.append({"set_id": set_id, "name": rec["name"],
                    "package": ((shot.get("project") or {}).get("package") or "").strip() or rec["name"],
                    "owner": rec["issued_by"], "alive": False, "record": rec,
                    "revision": rec["revision"], "issue_date": rec["issue_date"]})
    return out


# --- the differences ---------------------------------------------------------------------------

def _mark(*parts: Any) -> str:
    data = json.dumps(parts, ensure_ascii=False)
    return hashlib.sha1(data.encode("utf-8")).hexdigest()[:16]


def decisions(set_id: int) -> dict[tuple, dict]:
    return {(r["peer_set_id"], r["kind"], r["number"], r["key"]): dict(r)
            for r in query("SELECT * FROM spec_package_decisions WHERE set_id = ?", (set_id,))}


def _theirs(shot: Mapping[str, Any]) -> tuple[dict[str, dict], bool]:
    """The other package's sections as issued: their paragraphs as written
    (answers not filled in) when the issue kept them, else as issued."""
    if shot.get("bodies"):
        return {s["number"]: s for s in shot["bodies"]}, True
    return {s["number"]: s for s in shot.get("sections") or []}, False


def _mine(row: Mapping[str, Any], raw: bool) -> dict[str, dict]:
    from .specs_review import issued_words

    if raw:
        return {s["number"]: {"row_id": s["id"], "number": s["number"], "title": s["title"],
                              "nodes": specs.loads(s["body"])}
                for s in store.set_sections(row["id"])}
    return {s["number"]: s for s in issued_words(row)}


def _labels(nodes: list[dict], chosen: Mapping[str, str]) -> dict[str, str]:
    try:
        return {n["id"]: n.get("path") or n.get("label") or "" for n in specs.number(nodes, chosen)}
    except Exception:                                  # issued words, numbered already
        return {n["id"]: n.get("path") or n.get("label") or "" for n in nodes}


def _text_items(row: Mapping[str, Any], peer: Mapping[str, Any], shot: Mapping[str, Any]) -> list[dict]:
    from . import specs_export

    theirs, raw = _theirs(shot)
    mine = _mine(row, raw)
    chosen = store.chosen_for(row)
    items = []
    for number in sorted(set(theirs) & set(mine)):
        t_nodes = [n for n in theirs[number]["nodes"] if n.get("level") != specs.NOTE]
        m_nodes = [n for n in mine[number]["nodes"] if n.get("level") != specs.NOTE]
        labels = _labels(t_nodes, chosen)
        labels.update({k: v for k, v in _labels(m_nodes, chosen).items() if v})
        after = ""
        for m in specs.compare(t_nodes, m_nodes):
            if m["state"] == "same":
                after = m["id"]
                continue
            state = {"changed": "changed", "added": "ours", "removed": "theirs"}[m["state"]]
            their_text = m["was"]["text"] if state == "changed" else (m["text"] if state == "theirs" else "")
            our_text = m["text"] if state != "theirs" else ""
            items.append({
                "kind": "text", "peer_set_id": peer["set_id"], "record_id": peer["record"]["id"],
                "number": number, "title": mine[number]["title"], "key": m["id"], "state": state,
                "label": labels.get(m["id"], ""), "level": m["level"], "ours": our_text,
                "theirs": their_text, "raw": raw, "after": after,
                "node": {"id": m["id"], "level": m["level"], "text": their_text,
                         "when": (m["was"] or m).get("when", "") if state != "ours" else ""},
                "diff": specs_export.word_diff(their_text, our_text) if state == "changed" else [],
                "mark": _mark(state, their_text, our_text)})
            if state != "theirs":
                after = m["id"]
    return items


def _answer_items(row: Mapping[str, Any], peer: Mapping[str, Any], shot: Mapping[str, Any],
                  labels: Mapping[str, dict], tiles: set[str], options: Mapping[str, str]) -> list[dict]:
    from .specs_issued import _label, _shown

    data = shot.get("data") or {}
    items = []
    ours = {k: v for k, v in specs_questions.answers_of(row).items() if k != specs_questions.SPLIT}
    theirs = {k: v for k, v in (data.get("answers") or {}).items() if k != specs_questions.SPLIT}
    for key in sorted(set(ours) & set(theirs), key=lambda k: _label(k, labels).lower()):
        a, b = str(ours[key] or "").strip(), str(theirs[key] or "").strip()
        if a == b or not a or not b:
            continue
        items.append({"kind": "answer", "peer_set_id": peer["set_id"], "record_id": peer["record"]["id"],
                      "number": "", "key": key, "label": _label(key, labels),
                      "ours": _shown(key, a, labels), "theirs": _shown(key, b, labels),
                      "value": b, "mark": _mark("answer", b, a)})
    # The choices that set the specification's basis and materials; the
    # elements each package covers are its own scope, not a difference.
    ours_c, theirs_c = store.chosen_for(row), data.get("chosen") or {}
    for key in sorted(set(ours_c) & set(theirs_c)):
        if key == "elements" or key in tiles:
            continue
        a, b = (ours_c.get(key) or "").strip(), (theirs_c.get(key) or "").strip()
        if a == b or not a or not b:
            continue
        items.append({"kind": "choice", "peer_set_id": peer["set_id"], "record_id": peer["record"]["id"],
                      "number": "", "key": key, "label": options.get(key, key),
                      "ours": a.replace("|", ", "), "theirs": b.replace("|", ", "), "value": b,
                      "mark": _mark("choice", b, a)})
    return items


def discrepancies(row: Mapping[str, Any]) -> dict:
    """Every difference between this package and the latest issue of each
    other package of its project, each open or as decided."""
    from .specs_seed import ELEMENTS

    found = peers(row)
    decided = decisions(row["id"])
    labels = specs_questions.definitions()
    tiles = {key for key, _g, _how, _icon in ELEMENTS}
    options = {o["key"]: o["label"] for o in store.options()}
    out, open_n, kept_n = [], 0, 0
    for peer in found:
        if not peer["record"]:
            continue
        shot = json.loads(peer["record"]["snapshot"] or "{}")
        items = _answer_items(row, peer, shot, labels, tiles, options) + _text_items(row, peer, shot)
        for item in items:
            d = decided.get((peer["set_id"], item["kind"], item["number"], item["key"]))
            item["decision"] = d if d and d["mark"] == item["mark"] else None
        sections: dict[str, dict] = {}
        for item in items:
            if item["kind"] == "text":
                sections.setdefault(item["number"], {"number": item["number"], "title": item["title"],
                                                     "items": []})["items"].append(item)
        n_open = sum(1 for i in items if not i["decision"])
        open_n += n_open
        kept_n += len(items) - n_open
        out.append({**peer, "answers": [i for i in items if i["kind"] != "text"],
                    "sections": list(sections.values()), "open": n_open, "kept": len(items) - n_open,
                    "total": len(items)})
    return {"peers": found, "against": out, "open": open_n, "kept": kept_n,
            "key": project_key(row.get("code"))}


def open_count(row: Mapping[str, Any]) -> int:
    if not project_key(row.get("code")):
        return 0
    return discrepancies(row)["open"]


# --- deciding -------------------------------------------------------------------------------

def _find(row: Mapping[str, Any], peer_set_id: int, kind: str, number: str, key: str) -> dict:
    for peer in discrepancies(row)["against"]:
        if peer["set_id"] != peer_set_id:
            continue
        items = peer["answers"] + [i for s in peer["sections"] for i in s["items"]]
        for item in items:
            if item["kind"] == kind and item["number"] == number and item["key"] == key:
                return {**item, "peer": peer}
    raise specs.SpecError("That difference is not there any more: the other package's issue or "
                          "this package has changed since.")


def accept(row: Mapping[str, Any], peer_set_id: int, kind: str, number: str, key: str) -> str:
    """This package made to say what the other package issued. What was done, in words."""
    item = _find(row, peer_set_id, kind, number, key)
    who = item["peer"]["package"]
    if kind == "answer":
        specs_questions.save_answers(row["id"], {key: item["value"]}, {})
        _forget(row["id"], peer_set_id, kind, number, key)
        return f"{item['label']} is now answered as {who} issued it: {item['theirs']}."
    if kind == "choice":
        chosen = store.chosen_for(row)
        chosen[key] = item["value"]
        execute("UPDATE spec_sets SET options = ?, updated_at = datetime('now') WHERE id = ?",
                (json.dumps(chosen, ensure_ascii=False), row["id"]))
        _forget(row["id"], peer_set_id, kind, number, key)
        return f"{item['label']} is now {item['theirs']}, as in {who}."
    section = next((s for s in store.set_sections(row["id"]) if s["number"] == number), None)
    if section is None:
        raise specs.SpecError(f"Section {number} is not in this package any more.")
    nodes = specs.loads(section["body"])
    ids = [n["id"] for n in nodes]
    if item["state"] == "ours":
        nodes = [n for n in nodes if n["id"] != key]
    elif item["state"] == "changed" and key in ids:
        nodes = [{**n, "text": item["theirs"]} if n["id"] == key else n for n in nodes]
    else:
        new = dict(item["node"])
        at = ids.index(item["after"]) + 1 if item["after"] in ids else len(nodes)
        depth = specs.DEPTH.get(new["level"])
        while at < len(nodes) and depth is not None and \
                (specs.DEPTH.get(nodes[at]["level"]) or 99) > depth:
            at += 1
        nodes.insert(at, new)
    store.save_set_section(row["id"], section["id"], nodes)
    _forget(row["id"], peer_set_id, kind, number, key)
    label = item["label"] or "a paragraph"
    return {"ours": f"Section {number}, {label}: taken out, as {who} has it.",
            "theirs": f"Section {number}, {label}: put in as {who} has it.",
            "changed": f"Section {number}, {label}: now worded as {who} has it."}[item["state"]]


def reject(row: Mapping[str, Any], peer_set_id: int, kind: str, number: str, key: str,
           note: str = "") -> None:
    """This package keeps its own wording or answer, for a reason given."""
    from .specs_store import _who

    item = _find(row, peer_set_id, kind, number, key)
    _forget(row["id"], peer_set_id, kind, number, key)
    insert("INSERT INTO spec_package_decisions (set_id, peer_set_id, kind, number, key, mark, "
           "decision, note, user_id, decided_by) VALUES (?, ?, ?, ?, ?, ?, 'kept', ?, ?, ?)",
           (row["id"], peer_set_id, kind, number, key, item["mark"], (note or "").strip()[:500],
            _user_id(), _who()))


def reopen(set_id: int, peer_set_id: int, kind: str, number: str, key: str) -> None:
    _forget(set_id, peer_set_id, kind, number, key)


def _forget(set_id: int, peer_set_id: int, kind: str, number: str, key: str) -> None:
    execute("DELETE FROM spec_package_decisions WHERE set_id = ? AND peer_set_id = ? AND kind = ? "
            "AND number = ? AND key = ?", (set_id, peer_set_id, kind, number, key))


def bodies(row: Mapping[str, Any]) -> list[dict]:
    """The sections as written, kept with an issue so another package can take a paragraph
    with its answers still to fill in."""
    return [{"number": s["number"], "title": s["title"], "nodes": specs.loads(s["body"])}
            for s in store.set_sections(row["id"])]
