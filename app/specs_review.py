"""Review, approval and issue control for a project's specification.

Five things a department needs before a specification it issues can be
defended. **The team**: who may change a project, check it, approve and issue
it (a project with nobody listed stays open to everyone, as before).
**Sign-off**: each section prepared, checked and approved by name and date,
for the words as they will be issued; any change to those words asks for the
sign-off again. **The issue register**: every issue with its revision, purpose
and date, the files exactly as sent, and the issued words of each section, so
the next issue can show what changed. **Comments** pinned to paragraphs,
answered and closed. **History**: every answer and every paragraph changed,
by whom and when, before and after.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Iterable, Mapping

from flask import g

from . import specs, specs_export, specs_questions
from . import specs_store as store
from . import specs_issued as issued_data
from . import specs_packages as packages
from .db import execute, get_db, insert, query, query_one

ROLES = ("editor", "checker", "approver", "lead")
ROLE_NAMES = {"editor": "Editor", "checker": "Checker", "approver": "Approver", "lead": "Lead"}
ROLE_HINTS = {
    "editor": "changes the text and answers, and signs sections as prepared",
    "checker": "as an editor, and signs sections as checked",
    "approver": "as a checker, signs sections as approved and issues",
    "lead": "everything, and chooses the team",
}
RANK = {r: i + 1 for i, r in enumerate(ROLES)}
STAGES = ("prepared", "checked", "approved")
STAGE_NAMES = {"prepared": "Prepared", "checked": "Checked", "approved": "Approved"}
# For now (Ahmed, 2026-10-01) one person may sign a section as prepared,
# checked and approved, and anybody who may change the project signs all three.
# Set to False to have the checker and approver be someone else again, each
# with the role for it.
ONE_PERSON_SIGNS = True
# The least role that signs each stage, and does each thing.
NEEDS = {"edit": "editor", "prepared": "editor",
         "checked": "editor" if ONE_PERSON_SIGNS else "checker",
         "approved": "editor" if ONE_PERSON_SIGNS else "approver",
         "issue": "approver"}
PURPOSES = ("For information", "For review and comment", "For tender", "For construction",
            "As built")
# Someone who opened a section in the editor this recently is taken to be in it still.
EDITING_FOR = timedelta(minutes=30)


def _user_id() -> int | None:
    user = g.get("user")
    return user["id"] if user is not None else None


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


# --- the team ---------------------------------------------------------------------

def team(set_id: int) -> list[dict]:
    return [dict(r) for r in query(
        "SELECT m.user_id, m.role, u.name, u.email FROM spec_set_members m "
        "JOIN users u ON u.id = m.user_id WHERE m.set_id = ? ORDER BY u.name COLLATE NOCASE",
        (set_id,))]


def is_open(set_id: int) -> bool:
    """Whether anybody with THEMIS may change it. Never: a specification is
    its owner's (whoever started it) and administrators', and the team's they
    add; everybody else reads it, comments on it and may copy it."""
    return False


def owner_name(row: Mapping[str, Any]) -> str:
    """Whoever started the specification, who owns it."""
    if not row.get("created_by"):
        return ""
    u = query_one("SELECT name, email FROM users WHERE id = ?", (row["created_by"],))
    return (u["name"] or u["email"]) if u else ""


def role_of(row: Mapping[str, Any], user: Any) -> str | None:
    """The user's role on this project: an administrator and whoever started
    it lead it; otherwise the role the team gives them, or None."""
    if user is None:
        return None
    if user["role"] == "admin" or row["created_by"] == user["id"]:
        return "lead"
    found = query_one("SELECT role FROM spec_set_members WHERE set_id = ? AND user_id = ?",
                      (row["id"], user["id"]))
    return found["role"] if found and found["role"] in RANK else None


def may(row: Mapping[str, Any], user: Any, what: str) -> bool:
    """Whether the user may do ``what``: edit, prepared, checked, approved,
    issue, or team (choose the team)."""
    if user is None:
        return False
    role = role_of(row, user)
    if what == "team":
        return role == "lead"
    if is_open(row["id"]):
        return True
    return role is not None and RANK[role] >= RANK[NEEDS[what]]


def candidates() -> list[dict]:
    """The accounts that may open THEMIS, to choose a team from."""
    from .programs import may_open

    return [dict(u) for u in query("SELECT * FROM users ORDER BY name COLLATE NOCASE")
            if may_open(u, "specs")]


def save_team(set_id: int, roles: Mapping[int, str]) -> list[str]:
    """The team as chosen: each account's role, or '' for none. What changed, in words."""
    known = {u["id"]: u for u in candidates()}
    had = {m["user_id"]: m["role"] for m in team(set_id)}
    said = []
    for user_id, role in roles.items():
        if user_id not in known:
            continue
        role = role if role in RANK else ""
        was = had.get(user_id, "")
        if role == was:
            continue
        if role:
            execute("INSERT INTO spec_set_members (set_id, user_id, role, added_by) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT (set_id, user_id) DO UPDATE SET role = excluded.role",
                    (set_id, user_id, role, store._who()))
        else:
            execute("DELETE FROM spec_set_members WHERE set_id = ? AND user_id = ?", (set_id, user_id))
        name = known[user_id]["name"] or known[user_id]["email"]
        said.append(f"{name}: {ROLE_NAMES.get(role, 'not on the team')}")
        note(set_id, "team", name, ROLE_NAMES.get(was, ""), ROLE_NAMES.get(role, ""))
    return said


def my_sets(user: Any) -> set[int]:
    """The projects the user is on the team of."""
    if user is None:
        return set()
    return {r["set_id"] for r in query("SELECT set_id FROM spec_set_members WHERE user_id = ?",
                                       (user["id"],))}


# --- the words as issued ------------------------------------------------------------

def _sections(set_id: int) -> list[dict]:
    return [dict(r) for r in query(
        "SELECT id, number, title, doc_code, body FROM spec_set_sections WHERE set_id = ? "
        "ORDER BY number", (set_id,))]


def issued_words(row: Mapping[str, Any], sections: list[dict] | None = None,
                 marked: bool = False) -> list[dict]:
    """Each section as it would go out now: its title, document code and the
    paragraphs it issues, each with its number and its words written out
    (``marked``, exactly as the files say them, what is still open said plainly)."""
    sections = sections if sections is not None else _sections(row["id"])
    chosen, values = store.chosen_for(row), store.values_for(row)
    reader = store.reader([{"id": s["id"], "number": s["number"], "title": s["title"],
                            "nodes": specs.loads(s["body"])} for s in sections], chosen)
    out = []
    for s in sections:
        resolve = reader.issued(s["number"])
        paragraphs = []
        for n in specs.number(specs.loads(s["body"]), chosen):
            if not n["included"] or n["level"] == specs.NOTE:
                continue
            paragraphs.append({"id": n["id"], "level": n["level"], "label": n["label"],
                               "path": n["path"],
                               "text": specs_export.issued(n["text"], chosen, values, resolve, marked)})
        out.append({"row_id": s["id"], "number": s["number"], "title": s["title"],
                    "doc_code": s["doc_code"], "nodes": paragraphs})
    return out


def still_open(row: Mapping[str, Any], sections: list[dict] | None = None) -> list[dict]:
    """The places an issue would still leave to be specified, as its files
    say them: a question not answered, or a choice or prompt the master left
    in brackets."""
    out = []
    for s in issued_words(row, sections, marked=True):
        for n in s["nodes"]:
            found = [m.group(0) for m in specs.OPEN.finditer(n["text"])]
            if found:
                out.append({"number": s["number"], "row_id": s["row_id"], "path": n.get("path") or "",
                            "node_id": n["id"], "open": found, "text": n["text"]})
    return out


def fingerprint(section: Mapping[str, Any]) -> str:
    """What a sign-off holds for: the section's words as issued."""
    data = json.dumps([section["title"], section["doc_code"],
                       [(n["level"], n["text"]) for n in section["nodes"]]], ensure_ascii=False)
    return hashlib.sha1(data.encode("utf-8")).hexdigest()[:20]


def fingerprints(row: Mapping[str, Any]) -> dict[int, str]:
    return {s["row_id"]: fingerprint(s) for s in issued_words(row)}


# --- sign-off ---------------------------------------------------------------------------

def signoffs(set_id: int, prints: Mapping[int, str]) -> dict[int, dict[str, dict]]:
    """Each section's stages as signed, each marked current or not (the words
    changed since it was signed)."""
    out: dict[int, dict[str, dict]] = {}
    for r in query("SELECT * FROM spec_signoffs WHERE set_id = ?", (set_id,)):
        one = dict(r)
        one["current"] = prints.get(r["row_id"]) == r["fingerprint"]
        out.setdefault(r["row_id"], {})[r["stage"]] = one
    return out


def standing(stages: Mapping[str, Mapping[str, Any]] | None) -> str:
    """How far a section has got: '', prepared, checked or approved (current only)."""
    stages = stages or {}
    reached = ""
    for stage in STAGES:
        s = stages.get(stage)
        if not s or not s["current"]:
            break
        reached = stage
    return reached


def sign(row: Mapping[str, Any], row_ids: Iterable[int], stage: str) -> tuple[list[str], list[str]]:
    """The sections signed at this stage by the current user; returns the
    numbers signed and, for the rest, why not."""
    if stage not in STAGES:
        raise specs.SpecError("That is not a stage of sign-off.")
    user = g.get("user")
    if not may(row, user, stage):
        raise specs.SpecError(f"Your role on this project does not sign sections as {stage}.")
    words = {s["row_id"]: s for s in issued_words(row)}
    prints = {k: fingerprint(v) for k, v in words.items()}
    held = signoffs(row["id"], prints)
    done, refused = [], []
    for row_id in row_ids:
        s = words.get(row_id)
        if s is None:
            continue
        stages = held.get(row_id, {})
        mine = stages.get(stage)
        if mine and mine["current"]:
            refused.append(f"{s['number']} is already {stage} by {mine['name']}")
            continue
        at = STAGES.index(stage)
        if at:
            before = stages.get(STAGES[at - 1])
            if not before or not before["current"]:
                refused.append(f"{s['number']} is not {STAGES[at - 1]} yet"
                               + (" for its words as they stand" if before else ""))
                continue
            prepared = stages.get("prepared")
            if not ONE_PERSON_SIGNS and prepared and prepared["user_id"] == user["id"]:
                refused.append(f"{s['number']} was prepared by you: someone else "
                               f"signs it as {stage}")
                continue
        execute("INSERT INTO spec_signoffs (set_id, row_id, stage, user_id, name, at, fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (row_id, stage) DO UPDATE SET "
                "user_id = excluded.user_id, name = excluded.name, at = excluded.at, "
                "fingerprint = excluded.fingerprint",
                (row["id"], row_id, stage, user["id"], store._who(), _now(), prints[row_id]))
        note(row["id"], "signoff", STAGE_NAMES[stage], "", store._who(), row_id, s["number"])
        done.append(s["number"])
    return done, refused


def unsign(row: Mapping[str, Any], row_id: int, stage: str) -> bool:
    """A stage withdrawn, by whoever signed it or the lead, with the stages after it."""
    found = query_one("SELECT s.*, x.number FROM spec_signoffs s JOIN spec_set_sections x "
                      "ON x.id = s.row_id WHERE s.set_id = ? AND s.row_id = ? AND s.stage = ?",
                      (row["id"], row_id, stage))
    user = g.get("user")
    if found is None or user is None:
        return False
    if found["user_id"] != user["id"] and role_of(row, user) != "lead":
        raise specs.SpecError("Only whoever signed it, or the project's lead, takes a sign-off back.")
    later = STAGES[STAGES.index(stage):]
    execute(f"DELETE FROM spec_signoffs WHERE row_id = ? AND stage IN ({', '.join('?' * len(later))})",
            (row_id, *later))
    note(row["id"], "signoff", f"{STAGE_NAMES[stage]} taken back", found["name"], "", row_id,
         found["number"])
    return True


def signed_by(set_id: int, prints: Mapping[int, str]) -> dict[str, list[str]]:
    """Who signed the sections at each stage, for the issue record."""
    out: dict[str, list[str]] = {stage: [] for stage in STAGES}
    for stages in signoffs(set_id, prints).values():
        for stage, s in stages.items():
            if s["current"] and s["name"] not in out[stage]:
                out[stage].append(s["name"])
    return out


# --- what holds an issue --------------------------------------------------------------

def readiness(row: Mapping[str, Any], report: Mapping[str, Any] | None = None) -> dict:
    """What stands between this project and an issue."""
    words = issued_words(row)
    prints = {s["row_id"]: fingerprint(s) for s in words}
    held = signoffs(row["id"], prints)
    rows = []
    for s in words:
        rows.append({"row_id": s["row_id"], "number": s["number"], "title": s["title"],
                     "stages": held.get(s["row_id"], {}),
                     "standing": standing(held.get(s["row_id"]))})
    not_approved = [r for r in rows if r["standing"] != "approved"]
    open_n = open_comments(row["id"])
    waiting = store.open_items(row["id"], report) if report is not None else None
    reasons = []
    if row["hold_issue"] and waiting and waiting["total"]:
        reasons.append(f"{waiting['total']} item{'s' if waiting['total'] != 1 else ''} on the check "
                       "still to keep, amend or remove")
    if row["need_signoff"]:
        if not_approved:
            reasons.append(f"{len(not_approved)} section{'s' if len(not_approved) != 1 else ''} "
                           "not yet approved")
        if open_n:
            reasons.append(f"{open_n} review comment{'s' if open_n != 1 else ''} still open")
    return {"rows": rows, "prints": prints, "not_approved": not_approved, "open_comments": open_n,
            "waiting": waiting, "reasons": reasons, "words": words}


# --- the issue register ---------------------------------------------------------------

def issues(set_id: int) -> list[dict]:
    out = []
    for r in query("SELECT id, set_id, revision, purpose, issue_date, note, fmt, filename, mime, "
                   "LENGTH(content) AS size, signoffs, history_mark, issued_by, issued_at "
                   "FROM spec_issues WHERE set_id = ? ORDER BY id DESC", (set_id,)):
        one = dict(r)
        try:
            one["signed"] = json.loads(one.pop("signoffs") or "{}")
        except ValueError:
            one["signed"] = {}
        out.append(one)
    return out


def issue(set_id: int, issue_id: int, content: bool = False) -> dict | None:
    found = query_one("SELECT * FROM spec_issues WHERE id = ? AND set_id = ?", (issue_id, set_id))
    if found is None:
        return None
    one = dict(found)
    if not content:
        one.pop("content", None)
    try:
        one["snapshot"] = json.loads(one["snapshot"] or "{}")
        one["signed"] = json.loads(one["signoffs"] or "{}")
    except ValueError:
        one["snapshot"], one["signed"] = {}, {}
    return one


def last_issue(set_id: int) -> dict | None:
    found = query_one("SELECT id FROM spec_issues WHERE set_id = ? ORDER BY id DESC LIMIT 1", (set_id,))
    return issue(set_id, found["id"]) if found else None


def next_revision(current: str, taken: Iterable[str] = ()) -> str:
    """The revision after this one: 0 to 1, A to B, P01 to P02, C2 to C3."""
    taken = {t.strip().upper() for t in taken}
    current = (current or "").strip()
    if current.upper() not in taken:
        # The project's own revision has not been issued yet: that is the next.
        return current or "0"
    m = re.match(r"^(.*?)(\d+)$", current)
    if m:
        width = len(m.group(2))
        nxt = f"{m.group(1)}{int(m.group(2)) + 1:0{width}d}"
    elif re.match(r"^[A-Ya-y]$", current):
        nxt = chr(ord(current) + 1)
    else:
        nxt = current + "1"
    return nxt


def record_issue(row: Mapping[str, Any], fields: Mapping[str, str], fmt: str, filename: str,
                 mime: str, content: bytes, words: list[dict]) -> int:
    """An issue put on the register, with the files as sent and the words as issued."""
    prints = {s["row_id"]: fingerprint(s) for s in words}
    snapshot = {"project": {**{k: row[k] for k in store.SET_FIELDS + ("family",)}, "trade": row.get("trade") or "structures"},
                "sections": words, "data": issued_data.project_data(row),
                "amendments": issued_data.amendments_of(row), "bodies": packages.bodies(row)}
    mark = query_one("SELECT COALESCE(MAX(id), 0) AS n FROM spec_history WHERE set_id = ?",
                     (row["id"],))["n"]
    issue_id = insert(
        "INSERT INTO spec_issues (set_id, revision, purpose, issue_date, note, fmt, filename, mime, "
        "content, snapshot, signoffs, history_mark, user_id, issued_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], fields["revision"], fields.get("purpose", ""), fields.get("issue_date", ""),
         fields.get("note", ""), fmt, filename, mime, content,
         json.dumps(snapshot, ensure_ascii=False),
         json.dumps(signed_by(row["id"], prints), ensure_ascii=False), mark, _user_id(),
         store._who()))
    issued_data.keep(issue_id, row, fields, snapshot)
    note(row["id"], "issue", f"Rev {fields['revision']}", "",
         " · ".join(x for x in (fields.get("purpose", ""), fields.get("issue_date", "")) if x))
    return issue_id


def check_revision(set_id: int, revision: str) -> str:
    revision = " ".join((revision or "").split())
    if not revision:
        raise specs.SpecError("Give the revision this issue is.")
    if any(i["revision"].upper() == revision.upper() for i in issues(set_id)):
        raise specs.SpecError(f"Rev {revision} has been issued already: give the next revision.")
    return revision


def clean_date(value: str) -> str:
    value = (value or "").strip()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return date.today().isoformat()


# --- changes since an issue --------------------------------------------------------------

def changes_since(before: list[dict], now: list[dict]) -> list[dict]:
    """Section by section, what the words as issued now say that the issue did not."""
    old = {s["number"]: s for s in before}
    new = {s["number"]: s for s in now}
    out = []
    for number in sorted(set(old) | set(new)):
        a, b = old.get(number), new.get(number)
        if a is None:
            out.append({"number": number, "title": b["title"], "row_id": b["row_id"], "state": "added",
                        "paragraphs": [], "count": len(b["nodes"])})
            continue
        if b is None:
            out.append({"number": number, "title": a["title"], "row_id": None, "state": "removed",
                        "paragraphs": [], "count": len(a["nodes"])})
            continue
        paragraphs = []
        for m in specs.compare(a["nodes"], b["nodes"]):
            if m["state"] == "same":
                continue
            was = m["was"]["text"] if m["state"] == "changed" else (m["text"] if m["state"] == "removed" else "")
            now_text = m["text"] if m["state"] != "removed" else ""
            label = m.get("path") or m.get("label") or ""
            paragraphs.append({"id": m["id"], "state": m["state"], "label": label, "level": m["level"],
                               "old": was, "new": now_text,
                               "diff": specs_export.word_diff(was, now_text)
                               if m["state"] == "changed" else []})
        heading = [y for x, y in (("title", "title"), ("doc_code", "document code"))
                   if (a.get(x) or "") != (b.get(x) or "")]
        if paragraphs or heading:
            out.append({"number": number, "title": b["title"], "row_id": b["row_id"],
                        "state": "changed", "paragraphs": paragraphs, "count": len(paragraphs),
                        "heading": heading, "old_title": a["title"]})
    return out


def base_nodes(snapshot_section: Mapping[str, Any] | None) -> list[dict]:
    """An issued section's paragraphs as nodes, for Word's revision marks against it."""
    if not snapshot_section:
        return []
    return [{"id": n["id"], "level": n["level"], "text": n["text"], "when": ""}
            for n in snapshot_section["nodes"]]


# --- comments ------------------------------------------------------------------------------

def comments(set_id: int, row_id: int | None = None, state: str | None = None) -> list[dict]:
    """The threads, each with its replies, oldest first."""
    sql = "SELECT * FROM spec_comments WHERE set_id = ?"
    args: list[Any] = [set_id]
    if row_id is not None:
        sql += " AND row_id = ?"
        args.append(row_id)
    everything = [dict(r) for r in query(sql + " ORDER BY id", args)]
    threads = {c["id"]: dict(c, replies=[]) for c in everything if not c["parent_id"]}
    for c in everything:
        if c["parent_id"] and c["parent_id"] in threads:
            threads[c["parent_id"]]["replies"].append(c)
    out = list(threads.values())
    if state:
        out = [t for t in out if t["state"] == state]
    return out


def open_comments(set_id: int, row_id: int | None = None) -> int:
    sql = "SELECT COUNT(*) AS n FROM spec_comments WHERE set_id = ? AND parent_id IS NULL AND state = 'open'"
    args: list[Any] = [set_id]
    if row_id is not None:
        sql += " AND row_id = ?"
        args.append(row_id)
    return query_one(sql, args)["n"]


def open_by_section(set_id: int) -> dict[int, int]:
    return {r["row_id"]: r["n"] for r in query(
        "SELECT row_id, COUNT(*) AS n FROM spec_comments WHERE set_id = ? AND parent_id IS NULL "
        "AND state = 'open' GROUP BY row_id", (set_id,))}


def add_comment(row: Mapping[str, Any], body: str, row_id: int | None = None, node_id: str = "",
                parent_id: int | None = None) -> int:
    body = (body or "").strip()
    if not body:
        raise specs.SpecError("Write the comment first.")
    if len(body) > 4000:
        raise specs.SpecError("Keep a comment under 4,000 characters.")
    number = label = quote = ""
    if parent_id:
        parent = query_one("SELECT * FROM spec_comments WHERE id = ? AND set_id = ? AND parent_id IS NULL",
                           (parent_id, row["id"]))
        if parent is None:
            raise specs.SpecError("That comment is not here any more.")
        row_id, node_id, number = parent["row_id"], parent["node_id"], parent["number"]
    elif row_id:
        section = store.set_section(row["id"], row_id)
        if section is None:
            raise specs.SpecError("That section is not in this specification any more.")
        number = section["number"]
        if node_id:
            chosen = store.chosen_for(row)
            found = next((n for n in specs.number(specs.loads(section["body"]), chosen)
                          if n["id"] == node_id), None)
            if found is None:
                raise specs.SpecError("That paragraph is not in the section any more.")
            label = found["path"] or found["label"]
            quote = specs.fill(specs.choose(found["text"], chosen), store.values_for(row))[:400]
    comment_id = insert(
        "INSERT INTO spec_comments (set_id, row_id, number, node_id, parent_id, label, quote, body, "
        "user_id, author) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (row["id"], row_id, number, node_id or "", parent_id, label, quote, body, _user_id(),
         store._who()))
    note(row["id"], "comment", "Reply" if parent_id else "Comment" + (f" on {label}" if label else ""),
         "", body[:300], row_id, number)
    return comment_id


def comment(set_id: int, comment_id: int) -> dict | None:
    found = query_one("SELECT * FROM spec_comments WHERE id = ? AND set_id = ?", (comment_id, set_id))
    return dict(found) if found else None


def may_close(row: Mapping[str, Any], c: Mapping[str, Any]) -> bool:
    user = g.get("user")
    return user is not None and (c["user_id"] == user["id"] or role_of(row, user) == "lead"
                                 or may(row, user, "checked"))


def close_comment(row: Mapping[str, Any], comment_id: int, open_again: bool = False) -> None:
    c = comment(row["id"], comment_id)
    if c is None or c["parent_id"]:
        raise specs.SpecError("That comment is not here any more.")
    if not may_close(row, c):
        raise specs.SpecError("Whoever raised a comment, a checker or the lead closes it.")
    if open_again:
        execute("UPDATE spec_comments SET state = 'open', closed_by = '', closed_at = '' WHERE id = ?",
                (comment_id,))
    else:
        execute("UPDATE spec_comments SET state = 'closed', closed_by = ?, closed_at = ? WHERE id = ?",
                (store._who(), _now(), comment_id))
    note(row["id"], "comment", "Opened again" if open_again else "Closed", "", c["body"][:300],
         c["row_id"], c["number"])


# --- history ---------------------------------------------------------------------------------

FIELD_NAMES = {"name": "Project name", "package": "Package", "code": "Project code", "client": "Client",
               "header_left": "Page header, left", "header_right": "Page header, right",
               "doc_code": "Document code", "revision": "Revision", "issue_date": "Issue date",
               "file_pattern": "File names", "family": "Kind of specification",
               "hold_issue": "Hold the issue for the check",
               "need_signoff": "Hold the issue for sign-off"}
KIND_NAMES = {"project": "Project", "answer": "Answer", "text": "Text", "section": "Section",
              "signoff": "Sign-off", "issue": "Issue", "comment": "Comment", "team": "Team", "idc": "IDC"}


def note(set_id: int, kind: str, what: str, before: str = "", after: str = "",
         row_id: int | None = None, number: str = "") -> None:
    execute("INSERT INTO spec_history (set_id, row_id, number, kind, what, before, after, user_id, who) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (set_id, row_id, number, kind, what, before or "", after or "", _user_id(), store._who()))


def state(set_id: int) -> dict | None:
    """What a change is looked for in: the project's fields and answers, and
    each section's title, code and text as kept."""
    row = store.spec_set(set_id)
    if row is None:
        return None
    return {"set_id": set_id, "row": row,
            "sections": {s["id"]: s for s in _sections(set_id)}}


def _json(text: str | None) -> dict:
    try:
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _shown(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", ", ")


def record(before: Mapping[str, Any] | None, after: Mapping[str, Any] | None) -> int:
    """Every difference between two states of a project written to its
    history, as the current user's. How many rows were written."""
    if not before or not after:
        return 0
    rows: list[tuple] = []
    a, b = before["row"], after["row"]
    for field, name in FIELD_NAMES.items():
        if str(a.get(field, "")) != str(b.get(field, "")):
            old, new = a.get(field, ""), b.get(field, "")
            if field in ("hold_issue", "need_signoff"):
                old, new = ("on" if old else "off"), ("on" if new else "off")
            rows.append((None, "", "project", name, str(old), str(new)))
    labels = {o["key"]: o["label"] for o in store.options()}
    labels.update({v["key"]: v["label"] for v in store.variables()})
    for column in ("options", "variables"):
        old, new = _json(a.get(column)), _json(b.get(column))
        for key in sorted(set(old) | set(new)):
            if (old.get(key) or "") != (new.get(key) or ""):
                rows.append((None, "", "answer", labels.get(key, key), _shown(old.get(key)),
                             _shown(new.get(key))))
    old, new = _json(a.get("answers")), _json(b.get("answers"))
    if old != new:
        questions = specs_questions.definitions()
        for key in sorted(set(old) | set(new)):
            if key == specs_questions.SPLIT or old.get(key) == new.get(key):
                continue
            base, _, element = key.partition("@")
            label = (questions.get(base) or {}).get("label") or base.replace("_", " ")
            if element:
                label += f" ({element.replace('_', ' ')})"
            rows.append((None, "", "answer", label, _shown(old.get(key)), _shown(new.get(key))))
    chosen_a, chosen_b = store.chosen_for(a), store.chosen_for(b)
    olds, news = before["sections"], after["sections"]
    for row_id in sorted(set(olds) | set(news), key=lambda r: (olds.get(r) or news.get(r))["number"]):
        x, y = olds.get(row_id), news.get(row_id)
        if x is None:
            rows.append((row_id, y["number"], "section", "Added", "", f"{y['number']} {y['title']}"))
            continue
        if y is None:
            rows.append((None, x["number"], "section", "Taken out", f"{x['number']} {x['title']}", ""))
            continue
        for field, name in (("title", "Title"), ("doc_code", "Document code")):
            if (x[field] or "") != (y[field] or ""):
                rows.append((row_id, y["number"], "text", name, x[field] or "", y[field] or ""))
        if x["body"] == y["body"]:
            continue
        old_nodes, new_nodes = specs.loads(x["body"]), specs.loads(y["body"])
        old_labels = {n["id"]: n["path"] or n["label"] for n in specs.number(old_nodes, chosen_a)}
        new_labels = {n["id"]: n["path"] or n["label"] for n in specs.number(new_nodes, chosen_b)}
        for m in specs.compare(old_nodes, new_nodes):
            if m["state"] == "same":
                continue
            where = (new_labels.get(m["id"]) if m["state"] != "removed" else old_labels.get(m["id"])) \
                or specs.MARK.get(m["level"], m["level"])
            if m["state"] == "changed":
                was = m["was"]
                old_text = (f"[if {was['when']}] " if was.get("when") else "") + was["text"]
                new_text = (f"[if {m['when']}] " if m.get("when") else "") + m["text"]
                rows.append((row_id, y["number"], "text", f"{where} reworded", old_text, new_text))
            elif m["state"] == "added":
                rows.append((row_id, y["number"], "text", f"{where} added", "", m["text"]))
            else:
                rows.append((row_id, y["number"], "text", f"{where} taken out", m["text"], ""))
    if not rows:
        return 0
    who, user_id, now = store._who(), _user_id(), _now()
    conn = get_db()
    with conn:
        conn.executemany(
            "INSERT INTO spec_history (set_id, row_id, number, kind, what, before, after, user_id, who, at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(after["set_id"], r[0], r[1], r[2], r[3], r[4], r[5], user_id, who, now) for r in rows])
    return len(rows)


def history(set_id: int, row_id: int | None = None, kind: str = "", who: str = "",
            since: int = 0, before_id: int | None = None, most: int = 200) -> list[dict]:
    sql = "SELECT * FROM spec_history WHERE set_id = ? AND id > ?"
    args: list[Any] = [set_id, since]
    if row_id is not None:
        sql += " AND row_id = ?"
        args.append(row_id)
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if who:
        sql += " AND who = ?"
        args.append(who)
    if before_id:
        sql += " AND id < ?"
        args.append(before_id)
    return [dict(r) for r in query(sql + " ORDER BY id DESC LIMIT ?", args + [most])]


def history_people(set_id: int) -> list[str]:
    return [r["who"] for r in query("SELECT DISTINCT who FROM spec_history WHERE set_id = ? AND who != '' "
                                    "ORDER BY who COLLATE NOCASE", (set_id,))]


def last_change(set_id: int) -> dict | None:
    found = query_one("SELECT * FROM spec_history WHERE set_id = ? AND kind IN ('project', 'answer', "
                      "'text', 'section') ORDER BY id DESC LIMIT 1", (set_id,))
    return dict(found) if found else None


# --- two people at once -----------------------------------------------------------------------

def seen_mark(*parts: Any) -> str:
    """A short mark of what a page showed when it was opened: a save sent with
    a different one was made over somebody else's."""
    data = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(data.encode("utf-8")).hexdigest()[:16]


def section_mark(section: Mapping[str, Any]) -> str:
    return seen_mark(section["body"], section["title"], section["doc_code"])


def project_mark(row: Mapping[str, Any]) -> str:
    return seen_mark([row[k] for k in store.SET_FIELDS], row["family"], row["options"],
                     row["variables"], specs_questions.answers_of(row).get("proj_location", ""))


def start_editing(row_id: int) -> list[dict]:
    """The current user marked as having this section open in the editor; the
    others who have it open, with since when."""
    user = g.get("user")
    if user is None:
        return []
    execute("INSERT INTO spec_editing (row_id, user_id, name, since) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (row_id, user_id) DO UPDATE SET since = excluded.since",
            (row_id, user["id"], store._who(), _now()))
    return editing(row_id)


def editing(row_id: int) -> list[dict]:
    """The others who have this section open in the editor now."""
    user = g.get("user")
    cutoff = (datetime.utcnow() - EDITING_FOR).strftime("%Y-%m-%d %H:%M:%S")
    return [dict(r) for r in query(
        "SELECT * FROM spec_editing WHERE row_id = ? AND since >= ? AND user_id != ? ORDER BY since",
        (row_id, cutoff, user["id"] if user is not None else -1))]


def stop_editing(row_id: int) -> None:
    user = g.get("user")
    if user is not None:
        execute("DELETE FROM spec_editing WHERE row_id = ? AND user_id = ?", (row_id, user["id"]))


def minutes_ago(stamp: str) -> str:
    try:
        then = datetime.strptime(stamp[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return stamp
    minutes = int((datetime.utcnow() - then).total_seconds() // 60)
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    return f"{hours} hour{'s' if hours != 1 else ''} ago" if hours < 48 else stamp[:16]
