"""What the office learns from what it issues.

Every issue is kept with its project's data (where it is, for whom, the kind,
every answer and choice, and each amendment it made to the MTD), apart from
the project itself, so a Jeddah issue and a Lagos issue can be laid side by
side years later. The amendments projects made are gathered for an
administrator to judge whether the MTD should say the same. The standards
register keeps each cited standard's current edition, as last checked.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any, Iterable, Mapping

from . import specs, specs_check, specs_questions
from . import specs_store as store
from .db import execute, insert, query, query_one


def _user_id() -> int | None:
    from flask import g

    user = g.get("user")
    return user["id"] if user is not None else None


# --- a project's data, kept with each issue ------------------------------------------------

def project_data(row: Mapping[str, Any]) -> dict:
    """What the project is, beside its words: where, for whom, which kind, and
    every answer and choice it was issued with."""
    answers = specs_questions.answers_of(row)
    chosen = store.chosen_for(row)
    return {"location": answers.get("proj_location", ""), "client": row.get("client") or "",
            "family": row.get("family") or "", "code": row.get("code") or "",
            "answers": answers, "chosen": chosen,
            "elements": [e for e in (chosen.get("elements") or "").split("|") if e]}


def amendments_of(row: Mapping[str, Any]) -> list[dict]:
    """Each section's amendments to the master it was copied from: the
    paragraphs reworded, added and taken out, with the master's words beside
    them; and the sections the project wrote that the MTD lacks."""
    chosen = store.chosen_for(row)
    family = row.get("family") or store.DEFAULT_FAMILY
    out = []
    for s in store.set_sections(row["id"]):
        nodes = specs.loads(s["body"])
        base = store.base_of(s)
        if base is None:
            out.append({"number": s["number"], "title": s["title"], "family": family, "own": True,
                        "section_id": None, "base_version": None, "nodes": nodes, "items": []})
            continue
        labels = {n["id"]: n["path"] or n["label"] for n in specs.number(nodes, chosen)}
        labels.update({n["id"]: n["path"] or n["label"]
                       for n in specs.number(base, chosen) if n["id"] not in labels})
        items, after = [], ""
        for m in specs.compare(base, nodes):
            if m["state"] == "same":
                after = m["id"]
                continue
            node = {"id": m["id"], "level": m["level"], "text": m["text"], "when": m.get("when", "")}
            items.append({"id": m["id"], "state": m["state"], "level": m["level"],
                          "label": labels.get(m["id"], ""), "text": m["text"],
                          "was": (m["was"] or {}).get("text", "") if m["state"] == "changed" else "",
                          "after": after, "node": node})
            if m["state"] != "removed":
                after = m["id"]
        if items:
            out.append({"number": s["number"], "title": s["title"], "family": family, "own": False,
                        "section_id": s["section_id"], "base_version": s["base_version"],
                        "items": items})
    return out


def keep(issue_id: int, row: Mapping[str, Any], fields: Mapping[str, str],
         snapshot: Mapping[str, Any]) -> None:
    """The issue put on the office's record, where it stays when the project goes."""
    data = snapshot.get("data") or {}
    insert("INSERT OR REPLACE INTO spec_issue_records (issue_id, set_id, name, code, family, "
           "location, client, revision, purpose, issue_date, issued_by, snapshot) "
           "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (issue_id, row["id"], row.get("name") or "", row.get("code") or "",
            row.get("family") or "", data.get("location", ""), row.get("client") or "",
            fields["revision"], fields.get("purpose", ""), fields.get("issue_date", ""),
            store._who(), json.dumps(snapshot, ensure_ascii=False)))


# --- the issued specifications, across projects ---------------------------------------------

def _record(r: Mapping[str, Any], snapshot: bool = False) -> dict:
    one = dict(r)
    shot = json.loads(one.pop("snapshot") or "{}")
    one["sections"] = len(shot.get("sections") or [])
    one["amended"] = sum(len(s.get("items") or []) for s in shot.get("amendments") or [])
    one["own"] = sum(1 for s in shot.get("amendments") or [] if s.get("own"))
    one["recorded"] = "data" in shot
    one["alive"] = bool(one.get("live"))
    if snapshot:
        one["snapshot"] = shot
    return one


def records(family: str = "", search: str = "", latest: bool = False) -> list[dict]:
    """Every issue on record, newest first; or each project's latest only."""
    rows = query(
        "SELECT r.*, (SELECT COUNT(*) FROM spec_sets s WHERE s.id = r.set_id) AS live, "
        "(SELECT COUNT(*) FROM spec_issues i WHERE i.id = r.issue_id) AS has_files "
        "FROM spec_issue_records r ORDER BY r.issue_date DESC, r.id DESC")
    out, seen = [], set()
    needle = search.strip().lower()
    for r in rows:
        if family and r["family"] != family:
            continue
        if needle and not any(needle in (r[k] or "").lower()
                              for k in ("name", "code", "location", "client", "revision", "purpose")):
            continue
        if latest:
            if r["set_id"] in seen:
                continue
            seen.add(r["set_id"])
        out.append(_record(r))
    return out


def record(record_id: int) -> dict | None:
    r = query_one("SELECT r.*, (SELECT COUNT(*) FROM spec_sets s WHERE s.id = r.set_id) AS live, "
                  "(SELECT COUNT(*) FROM spec_issues i WHERE i.id = r.issue_id) AS has_files "
                  "FROM spec_issue_records r WHERE r.id = ?", (record_id,))
    return _record(r, snapshot=True) if r else None


def _label(key: str, labels: Mapping[str, dict]) -> str:
    base, _, element = key.partition("@")
    name = (labels.get(base) or {}).get("label") or base
    return f"{name} ({element.replace('_', ' ')})" if element else name


def _shown(key: str, value: Any, labels: Mapping[str, dict]) -> str:
    if value is None:
        return ""
    q = labels.get(key.partition("@")[0])
    try:
        return specs_questions.shown(q, value) if q else str(value)
    except Exception:                               # an answer the question no longer offers
        return str(value)


def compare(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict:
    """Two issues side by side, from any two projects or one project's two
    revisions: what each project is, how each answered, and section by section
    what the second says that the first did not."""
    from .specs_review import changes_since

    labels = specs_questions.definitions()
    da, db = a["snapshot"].get("data") or {}, b["snapshot"].get("data") or {}
    facts = [("Kind", a["family"], b["family"]), ("Location", a["location"], b["location"]),
             ("Client", a["client"], b["client"]), ("Document code", a["code"], b["code"]),
             ("Revision", a["revision"], b["revision"]), ("Issue date", a["issue_date"], b["issue_date"]),
             ("Elements", ", ".join(da.get("elements") or []), ", ".join(db.get("elements") or []))]
    ans_a, ans_b = da.get("answers") or {}, db.get("answers") or {}
    answers = []
    for key in sorted(set(ans_a) | set(ans_b), key=lambda k: _label(k, labels).lower()):
        if key == "proj_location":
            continue
        one, two = _shown(key, ans_a.get(key), labels), _shown(key, ans_b.get(key), labels)
        answers.append({"key": key, "label": _label(key, labels), "a": one, "b": two,
                        "same": one == two})
    cho_a, cho_b = da.get("chosen") or {}, db.get("chosen") or {}
    options = {o["key"]: o["label"] for o in store.options()}
    choices = [{"label": options.get(k, k), "a": cho_a.get(k, ""), "b": cho_b.get(k, ""),
                "same": cho_a.get(k, "") == cho_b.get(k, "")}
               for k in sorted(set(cho_a) | set(cho_b)) if k != "elements"]
    sections = changes_since(a["snapshot"].get("sections") or [], b["snapshot"].get("sections") or [])
    return {"facts": facts, "answers": answers, "choices": choices, "sections": sections,
            "recorded": bool(da) and bool(db)}


def answers_table(family: str = "") -> dict:
    """Every question across the projects as last issued: one column per
    project, one row per question, the differences marked."""
    labels = specs_questions.definitions()
    latest = [record(r["id"]) for r in records(family=family, latest=True)]
    latest = [r for r in latest if r and r["snapshot"].get("data")]
    keys: set[str] = set()
    for r in latest:
        keys.update(k for k in r["snapshot"]["data"].get("answers") or {} if k != "proj_location")
    rows = []
    for key in sorted(keys, key=lambda k: (((labels.get(k.partition("@")[0]) or {}).get("grp") or "~"),
                                           _label(k, labels).lower())):
        values = [_shown(key, (r["snapshot"]["data"].get("answers") or {}).get(key), labels) for r in latest]
        rows.append({"key": key, "label": _label(key, labels),
                     "group": (labels.get(key.partition("@")[0]) or {}).get("grp") or "",
                     "values": values, "differ": len({v for v in values if v}) > 1})
    return {"projects": latest, "rows": rows}


def answers_csv(table: Mapping[str, Any]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Group", "Question"] + [f"{p['name']} ({p['location'] or 'no location'}) Rev {p['revision']}"
                                        for p in table["projects"]])
    for r in table["rows"]:
        w.writerow([r["group"], r["label"]] + r["values"])
    return out.getvalue()


# --- the amendments projects made, for the MTD ----------------------------------------------

def decisions() -> dict[tuple, dict]:
    out = {}
    for r in query("SELECT * FROM spec_amendment_reviews ORDER BY id"):
        out[(r["family"], r["number"], r["node_id"], r["set_id"])] = dict(r)
    return out


def _sources(family: str, live: bool) -> list[dict]:
    """Each project's amendments, with what to call the project: as it was
    last issued, or as it stands now."""
    out = []
    if live:
        for s in store.sets():
            if family and s.get("family") != family:
                continue
            row = store.spec_set(s["id"])
            out.append({"set_id": row["id"], "issue_id": None, "record_id": None, "name": row["name"],
                        "location": specs_questions.answers_of(row).get("proj_location", ""),
                        "revision": row.get("revision") or "", "issue_date": "", "live": True,
                        "amendments": amendments_of(row)})
        return out
    for r in records(family=family, latest=True):
        full = record(r["id"])
        out.append({"set_id": r["set_id"], "issue_id": r["issue_id"], "record_id": r["id"],
                    "name": r["name"], "location": r["location"], "revision": r["revision"],
                    "issue_date": r["issue_date"], "live": False,
                    "amendments": full["snapshot"].get("amendments") or []})
    return out


def from_projects(family: str = "", live: bool = False, show_decided: bool = False) -> dict:
    """The amendments every project made to the MTD, gathered by master
    paragraph: the MTD's words now, then each project's words, so an
    administrator sees what several projects changed the same way."""
    decided = decisions()
    by_section: dict[tuple, dict] = {}
    own: list[dict] = []
    for src in _sources(family, live):
        who = {k: src[k] for k in ("set_id", "issue_id", "record_id", "name", "location", "revision",
                                   "issue_date", "live")}
        for s in src["amendments"]:
            fam = s.get("family") or family
            if s.get("own"):
                master = store.section_by_number(s["number"], fam)
                if master is None:
                    own.append({**who, "number": s["number"], "title": s["title"], "family": fam,
                                "paragraphs": len(s.get("nodes") or [])})
                continue
            key = (fam, s["number"])
            group = by_section.setdefault(key, {"family": fam, "number": s["number"],
                                                "title": s["title"], "paragraphs": {}})
            for item in s["items"]:
                para = group["paragraphs"].setdefault(item["id"], {
                    "id": item["id"], "label": item["label"], "entries": []})
                para["label"] = para["label"] or item["label"]
                decision = decided.get((fam, s["number"], item["id"], src["set_id"]))
                para["entries"].append({**who, **{k: item[k] for k in ("state", "text", "was", "label")},
                                        "decision": decision})
    sections = []
    for (fam, number), group in sorted(by_section.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        master = store.section_by_number(number, fam)
        now = {n["id"]: n for n in specs.loads(master["body"])} if master else {}
        paragraphs = []
        for para in group["paragraphs"].values():
            current = now.get(para["id"])
            for e in para["entries"]:
                if e["state"] == "removed":
                    e["in_mtd"] = current is None
                else:
                    e["in_mtd"] = current is not None and specs.same(current, {"text": e["text"],
                                                                               "level": current["level"],
                                                                               "when": current.get("when", "")})
                e["open"] = not e["decision"] and not e["in_mtd"]
                e["diff"] = _diff(current["text"] if current else e["was"], e["text"]) \
                    if e["state"] == "changed" else []
            if not show_decided and not any(e["open"] for e in para["entries"]):
                continue
            paragraphs.append({**para, "mtd": current["text"] if current else "",
                               "projects": len({e["set_id"] for e in para["entries"]}),
                               "open": sum(e["open"] for e in para["entries"])})
        if paragraphs:
            paragraphs.sort(key=lambda p: (-p["projects"], p["label"]))
            sections.append({**group, "master": master, "paragraphs": paragraphs,
                             "open": sum(p["open"] for p in paragraphs)})
    sections.sort(key=lambda s: (-max(p["projects"] for p in s["paragraphs"]), s["family"], s["number"]))
    return {"sections": sections, "own": own}


def _diff(a: str, b: str) -> list:
    from . import specs_export

    return specs_export.word_diff(a or "", b or "")


def _entry(family: str, number: str, node_id: str, set_id: int, record_id: int | None) -> tuple[dict, dict]:
    """One project's amendment of one paragraph, with the project it came from."""
    if record_id:
        r = record(record_id)
        if r is None:
            raise specs.SpecError("That issue is not on record.")
        amendments, who = r["snapshot"].get("amendments") or [], {"name": r["name"], "revision": r["revision"]}
    else:
        row = store.spec_set(set_id)
        if row is None:
            raise specs.SpecError("That project is not there any more.")
        amendments, who = amendments_of(row), {"name": row["name"], "revision": row.get("revision") or ""}
    for s in amendments:
        if s["number"] == number and (s.get("family") or family) == family:
            for item in s.get("items") or []:
                if item["id"] == node_id:
                    return item, who
    raise specs.SpecError("That amendment is not in the project any more.")


def adopt(family: str, number: str, node_id: str, set_id: int, record_id: int | None,
          text: str | None = None) -> int:
    """A project's amendment written into the MTD: a new version of the
    master section, with the paragraph as the project has it (or as the
    administrator reworded it). Projects that took the section are offered the
    new version as for any other change to the master."""
    item, who = _entry(family, number, node_id, set_id, record_id)
    master = store.section_by_number(number, family)
    if master is None:
        raise specs.SpecError(f"The MTD has no section {number} for {family}.")
    nodes = specs.loads(master["body"])
    ids = [n["id"] for n in nodes]
    words = " ".join((text if text is not None else item["text"]).split()) if item["state"] != "removed" else ""
    if item["state"] == "removed":
        nodes = [n for n in nodes if n["id"] != node_id]
    elif node_id in ids:
        nodes = [{**n, "text": words, "level": item["level"]} if n["id"] == node_id else n for n in nodes]
    else:
        new = {**item["node"], "text": words}
        at = ids.index(item["after"]) + 1 if item["after"] in ids else len(nodes)
        # Under the paragraph it followed, after any of that paragraph's own sub-paragraphs.
        depth = specs.DEPTH.get(new["level"])
        while at < len(nodes) and depth is not None and \
                (specs.DEPTH.get(nodes[at]["level"]) or 99) > depth:
            at += 1
        nodes.insert(at, new)
    label = item["label"] or node_id
    note = f"From {who['name']}" + (f" Rev {who['revision']}" if who["revision"] else "") + \
           f": {('paragraph ' + label) if label else 'a paragraph'} " + \
           {"changed": "reworded", "added": "added", "removed": "taken out"}[item["state"]]
    section_id = store.save_section(number, master["title"], nodes, note=note,
                                    section_id=master["id"], family=family)
    version = store.section(section_id)["version"]
    _decide(family, number, node_id, set_id, record_id, "adopted", note, version)
    return version


def keep_out(family: str, number: str, node_id: str, set_id: int, record_id: int | None,
             note: str = "") -> None:
    """An amendment the MTD should not take: it stays the project's own."""
    _entry(family, number, node_id, set_id, record_id)
    _decide(family, number, node_id, set_id, record_id, "kept", note.strip()[:500], None)


def reopen(family: str, number: str, node_id: str, set_id: int) -> None:
    execute("DELETE FROM spec_amendment_reviews WHERE family = ? AND number = ? AND node_id = ? "
            "AND set_id = ? AND decision = 'kept'", (family, number, node_id, set_id))


def _decide(family, number, node_id, set_id, record_id, decision, note, version) -> None:
    issue_id = None
    if record_id:
        r = query_one("SELECT issue_id FROM spec_issue_records WHERE id = ?", (record_id,))
        issue_id = r["issue_id"] if r else None
    execute("DELETE FROM spec_amendment_reviews WHERE family = ? AND number = ? AND node_id = ? "
            "AND set_id = ?", (family, number, node_id, set_id))
    insert("INSERT INTO spec_amendment_reviews (family, number, node_id, set_id, issue_id, decision, "
           "note, version, user_id, decided_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
           (family, number, node_id, set_id, issue_id, decision, note, version, _user_id(),
            store._who()))


# --- the standards register -------------------------------------------------------------------

REGISTER_NOTE = "From the standards register"
STATUSES = ("current", "withdrawn", "unknown")
STALE_AFTER = timedelta(days=365)


def _display(ref: str) -> str:
    """A standard as cited, without its edition: ``ACI 318-19`` is ``ACI 318``."""
    m = specs_check.STANDARD.search(ref or "")
    if not m:
        return (ref or "").strip()
    body = " ".join(m.group("body").split())
    if specs_check.family(body) == "us":
        body = re.sub(r"-\d\d$", "", body)
    return body


def cited() -> dict[str, dict]:
    """Every standard the MTD and the projects cite, by key: how it is cited
    (each edition, and how often), and in which master sections and projects."""
    found: dict[str, dict] = {}

    def scan(text: str, where: str, kind: str) -> None:
        for m in specs_check.STANDARD.finditer(text or ""):
            ref = " ".join(m.group(0).split())
            key = specs_check.std_key(ref)
            one = found.setdefault(key, {"key": key, "standard": _display(ref), "editions": Counter(),
                                         "years": set(), "masters": set(), "projects": set()})
            one["editions"][ref] += 1
            year = specs_check.std_year(m)
            if year:
                one["years"].add(year)
            one["masters" if kind == "master" else "projects"].add(where)

    for s in query("SELECT number, family, body FROM spec_sections"):
        for n in specs.loads(s["body"]):
            scan(n["text"], f"{s['family']} {s['number']}", "master")
    for s in query("SELECT x.body, t.name FROM spec_set_sections x JOIN spec_sets t ON t.id = x.set_id"):
        for n in specs.loads(s["body"]):
            scan(n["text"], s["name"], "project")
    return found


def _year(edition: str) -> int | None:
    m = specs_check.STANDARD.search(edition or "")
    if m:
        year = specs_check.std_year(m)
        if year:
            return year
    years = [int(y) for y in re.findall(r"(?:19|20)\d\d", edition or "")]
    if years:
        return max(years)
    short = re.search(r"-(\d\d)$", (edition or "").strip())       # ACI CODE-318-25
    return 2000 + int(short.group(1)) if short else None


def statuses() -> dict[str, dict]:
    return {r["key"]: dict(r) for r in query("SELECT * FROM spec_standard_status")}


def register(show: str = "all") -> list[dict]:
    """Each cited standard with what the register says of it: up to date,
    cited in an older edition than the current one, withdrawn, not checked,
    or checked too long ago to trust."""
    known = statuses()
    today = date.today()
    rows = []
    for key, c in cited().items():
        k = known.get(key) or {}
        current_year = _year(k.get("current", ""))
        older = sorted(y for y in c["years"] if current_year and y < current_year)
        checked = k.get("checked") or ""
        try:
            stale = bool(checked) and today - date.fromisoformat(checked) > STALE_AFTER
        except ValueError:
            stale = True
        if not k:
            state = "unchecked"
        elif k.get("status") == "withdrawn":
            state = "withdrawn"
        elif k.get("status") == "unknown" or not k.get("current"):
            state = "unknown"
        elif older:
            state = "older"
        else:
            state = "current"
        rows.append({**c, "editions": c["editions"].most_common(), "masters": sorted(c["masters"]),
                     "projects": sorted(c["projects"]), "status": k, "state": state, "older": older,
                     "stale": stale, "places": sum(c["editions"].values())})
    if show == "attention":
        rows = [r for r in rows if r["state"] in ("older", "withdrawn", "unchecked", "unknown") or r["stale"]]
    order = {"withdrawn": 0, "older": 1, "unknown": 2, "unchecked": 3, "current": 4}
    rows.sort(key=lambda r: (order[r["state"]], -r["places"], r["standard"]))
    return rows


def register_csv() -> str:
    """The register as a list to check: each standard, the editions cited and
    what the register last said, with columns for the check to fill in."""
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["standard", "current", "status", "replaced_by", "source", "checked", "note",
                "editions_cited", "places"])
    for r in register():
        k = r["status"]
        w.writerow([r["standard"], k.get("current", ""), k.get("status", ""), k.get("replaced_by", ""),
                    k.get("source", ""), k.get("checked", ""), k.get("note", ""),
                    "; ".join(e for e, _ in r["editions"]), r["places"]])
    return out.getvalue()


def read_check(data: bytes) -> list[dict]:
    """A check of current editions, as a .csv with the register's columns:
    standard, current, status, replaced_by, source, checked, note."""
    text = data.decode("utf-8-sig", errors="replace")
    rows = []
    for r in csv.DictReader(io.StringIO(text)):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        standard = r.get("standard", "")
        if not standard:
            continue
        status = r.get("status", "").lower() or ("current" if r.get("current") else "unknown")
        if status == "superseded":
            status = "current" if r.get("current") else "withdrawn"
        rows.append({"key": specs_check.std_key(standard), "standard": standard,
                     "current": r.get("current", ""), "status": status if status in STATUSES else "unknown",
                     "replaced_by": r.get("replaced_by", ""), "source": r.get("source", ""),
                     "checked": r.get("checked", "") or date.today().isoformat(),
                     "note": r.get("note", "")})
    if not rows:
        raise specs.SpecError("No standards found: the file needs a header row with at least "
                              "'standard', 'current' and 'status'.")
    return rows


def preview(rows: Iterable[Mapping[str, str]]) -> list[dict]:
    """What loading a check would change, row by row, so an administrator
    ticks what to take."""
    known, seen = statuses(), cited()
    out = []
    for r in rows:
        k = known.get(r["key"]) or {}
        c = seen.get(r["key"])
        year = _year(r["current"])
        older = sorted(y for y in (c["years"] if c else ()) if year and y < year)
        changed = any((k.get(f) or "") != (r[f] or "") for f in ("current", "status", "replaced_by"))
        effect = ""
        if r["status"] == "withdrawn":
            effect = "Every citation will be flagged as withdrawn" + (
                f", with {r['replaced_by']} offered instead" if r["replaced_by"] else "")
        elif older:
            effect = (f"Citations of the {', '.join(map(str, older))} edition"
                      f"{'s' if len(older) > 1 else ''} will be flagged, with {r['current']} offered")
        out.append({**r, "was": k, "cited": c is not None,
                    "places": sum(c["editions"].values()) if c else 0, "changed": changed or not k,
                    "effect": effect, "take": r["status"] != "unknown" and (changed or not k)})
    out.sort(key=lambda r: (not r["effect"], not r["changed"], not r["cited"], r["standard"]))
    return out


def apply_check(rows: Iterable[Mapping[str, str]]) -> int:
    """The ticked rows of a check written into the register, and the withdrawn
    list brought into line with it, so the checker flags every out-of-date
    citation in every project with the current edition offered. The engineer
    still decides each one."""
    n = 0
    for r in rows:
        execute("INSERT OR REPLACE INTO spec_standard_status (key, standard, current, status, "
                "replaced_by, source, note, checked, checked_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["key"], r["standard"], r["current"], r["status"], r["replaced_by"], r["source"],
                 r["note"], r["checked"], store._who()))
        _sync_withdrawn(r)
        n += 1
    return n


def save_status(key: str, fields: Mapping[str, str]) -> None:
    row = {"key": key, "standard": fields.get("standard", "").strip() or key,
           "current": fields.get("current", "").strip(),
           "status": fields.get("status", "unknown") if fields.get("status") in STATUSES else "unknown",
           "replaced_by": fields.get("replaced_by", "").strip(), "source": fields.get("source", "").strip(),
           "note": fields.get("note", "").strip(), "checked": date.today().isoformat()}
    apply_check([row])


def _sync_withdrawn(r: Mapping[str, str]) -> None:
    """The register's word on one standard, as rows of the withdrawn list
    (which is what the checker reads): its own earlier rows replaced."""
    for w in store.withdrawn():
        if w["note"].startswith(REGISTER_NOTE) and specs_check.std_key(w["old"]) == r["key"]:
            execute("DELETE FROM spec_withdrawn WHERE id = ?", (w["id"],))
    when = f"{REGISTER_NOTE}, checked {r['checked']}" + (f": {r['source']}" if r["source"] else "")
    position = (query_one("SELECT COALESCE(MAX(position), 0) AS n FROM spec_withdrawn")["n"] or 0) + 1
    if r["status"] == "withdrawn":
        insert("INSERT INTO spec_withdrawn (old, new, note, position) VALUES (?, ?, ?, ?)",
               (_display(r["standard"]), r["replaced_by"], f"{when}. Withdrawn", position))
        return
    year = _year(r["current"])
    if r["status"] == "current" and year:
        insert("INSERT INTO spec_withdrawn (old, new, note, position) VALUES (?, ?, ?, ?)",
               (f"{_display(r['standard'])}:{year - 1}", r["current"],
                f"{when}. Current edition {r['current']}", position))


def as_rows(form_rows: str) -> list[dict]:
    """The rows of a check carried through the preview form."""
    try:
        rows = json.loads(form_rows or "[]")
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("key")]


def group_by(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, list]:
    out: dict[str, list] = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out
