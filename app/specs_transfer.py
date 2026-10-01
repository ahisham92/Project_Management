"""A project, or a template made from one, as a .themis file to pass to a
colleague on another THEMIS.

The file is a zip holding ``themis.json``: the project's header, kind,
answers and choices, and every section of its own text. Each section names the
master it was taken from by kind and number (ids differ from one site to the
next) with a fingerprint of the master text it was copied from, so the site
that reads it lines the section up against the same master version when it
has it, and against its current master when it does not.

A template is the same file without what belongs to one project: no name,
code, client, package, page header, document code, revision, date or place.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any, Mapping

from flask import g

from . import specs, specs_store as store
from .db import execute, get_db, insert, query

FORMAT = "themis"
VERSION = 1
EXTENSION = ".themis"
MOST = 50 * 1024 * 1024        # far more than any real project
NAME = "themis.json"

# What a template leaves behind: the things that belong to one project.
PROJECT_ONLY = ("name", "code", "client", "package", "header_left", "header_right", "doc_code",
                "revision", "issue_date", "city", "country", "lat", "lng")
CARRIED = store.SET_FIELDS + ("family", "options", "variables", "answers", "covered", "city",
                              "country", "lat", "lng", "hold_issue", "need_signoff")


def _sha(body: str | None) -> str:
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()[:20] if body else ""


def _json(text: str | None, default: Any) -> Any:
    try:
        out = json.loads(text or "")
    except (TypeError, ValueError):
        return default
    return out if isinstance(out, type(default)) else default


def export(set_id: int, template: bool = False) -> tuple[bytes, str]:
    """The project (or a template of it) as a .themis file, and its file name."""
    row = store.spec_set(set_id)
    if row is None:
        raise specs.SpecError("That specification is not here any more.")
    project = {k: row.get(k) for k in CARRIED}
    for k in ("options", "variables", "answers", "covered"):
        project[k] = _json(row.get(k), {})
    declined = []
    for r in query("SELECT id, family, number FROM spec_sections"):
        if r["id"] in store.declined(row):
            declined.append({"family": r["family"], "number": r["number"]})
    project["declined"] = declined
    if template:
        for k in PROJECT_ONLY:
            project.pop(k, None)
        project["answers"].pop("proj_location", None)
    sections = []
    for s in query("SELECT x.*, m.family AS master_family, m.number AS master_number, "
                   "v.body AS base_body FROM spec_set_sections x "
                   "LEFT JOIN spec_sections m ON m.id = x.section_id "
                   "LEFT JOIN spec_section_versions v ON v.section_id = x.section_id "
                   "AND v.version = x.base_version WHERE x.set_id = ? ORDER BY x.number", (set_id,)):
        sections.append({
            "number": s["number"], "title": s["title"],
            "doc_code": "" if template else s["doc_code"],
            "body": specs.loads(s["body"]),
            "master": ({"family": s["master_family"], "number": s["master_number"],
                        "version": s["base_version"], "sha": _sha(s["base_body"])}
                       if s["section_id"] and s["master_number"] else None),
        })
    user = g.get("user")
    doc = {"format": FORMAT, "version": VERSION, "kind": "template" if template else "project",
           "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
           "exported_by": (user["name"] or user["email"]) if user is not None else "",
           "from": {"name": row["name"], "code": row["code"], "family": row["family"]},
           "project": project, "sections": sections}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(NAME, json.dumps(doc, ensure_ascii=False, indent=1))
    stem = "".join(c if c.isalnum() or c in "-_ " else "-" for c in (row["code"] or row["name"])).strip()
    stem = stem or "specification"
    return buffer.getvalue(), f"{stem} - {'template' if template else 'project'}{EXTENSION}"


def read(data: bytes) -> dict:
    """What a .themis file holds, checked; SpecError when it is not one."""
    if len(data) > MOST:
        raise specs.SpecError("That file is too large to be a THEMIS project.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            doc = json.loads(z.read(NAME).decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError, UnicodeDecodeError):
        raise specs.SpecError("That is not a .themis file: export one from a project's page "
                              "(Send to a colleague) and import that.") from None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise specs.SpecError("That file was not made by THEMIS.")
    if int(doc.get("version") or 0) > VERSION:
        raise specs.SpecError("That file was made by a newer THEMIS than this one: ask for this "
                              "site to be updated first.")
    if not isinstance(doc.get("project"), dict) or not isinstance(doc.get("sections"), list):
        raise specs.SpecError("That .themis file is incomplete.")
    return doc


def _base(master: Mapping[str, Any] | None) -> tuple[int | None, int]:
    """The local master a section lines up with, and the version of it."""
    if not isinstance(master, dict) or not master.get("number"):
        return None, 0
    local = store.section_by_number(str(master["number"]), str(master.get("family") or ""))
    if local is None:
        return None, 0
    want = master.get("sha") or ""
    if want:
        for v in query("SELECT version, body FROM spec_section_versions WHERE section_id = ? "
                       "ORDER BY version DESC", (local["id"],)):
            if _sha(v["body"]) == want:
                return local["id"], v["version"]
    return local["id"], local["version"]


def import_file(data: bytes, fields: Mapping[str, str]) -> tuple[int, dict]:
    """A new project from a .themis file, owned by whoever imports it. The
    name (and for a template the code and client) come from ``fields`` where
    given. Returns the new project's id and a summary of what came in."""
    doc = read(data)
    p = doc["project"]
    family = store.clean_family(str(p.get("family") or ""))
    values = {k: str(p.get(k) or "") for k in store.SET_FIELDS}
    for k in ("name", "code", "client", "package"):
        given = " ".join((fields.get(k) or "").split())
        if given:
            values[k] = given
    if not values["name"].strip():
        raise specs.SpecError("Give the project a name: a template does not carry one.")
    values["file_pattern"] = values["file_pattern"] or "SPC-{number}"
    values["revision"] = values["revision"] or "0"
    declined = []
    for d in p.get("declined") or []:
        if isinstance(d, dict):
            local = store.section_by_number(str(d.get("number") or ""), str(d.get("family") or ""))
            if local:
                declined.append(local["id"])
    user = g.get("user")
    set_id = insert(
        f"INSERT INTO spec_sets ({', '.join(store.SET_FIELDS)}, family, options, variables, declined, "
        "answers, covered, hold_issue, need_signoff, created_by) "
        f"VALUES ({', '.join('?' * len(store.SET_FIELDS))}, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [values[k] for k in store.SET_FIELDS] + [
            family,
            json.dumps(p.get("options") if isinstance(p.get("options"), dict) else {}, ensure_ascii=False),
            json.dumps(p.get("variables") if isinstance(p.get("variables"), dict) else {}, ensure_ascii=False),
            json.dumps(sorted(declined)),
            json.dumps(p.get("answers") if isinstance(p.get("answers"), dict) else {}, ensure_ascii=False),
            json.dumps(p.get("covered") if isinstance(p.get("covered"), dict) else {}, ensure_ascii=False),
            1 if p.get("hold_issue", 1) else 0, 1 if p.get("need_signoff") else 0,
            user["id"] if user is not None else None])
    city = fields.get("city") or str(p.get("city") or "")
    country = fields.get("country") or str(p.get("country") or "")
    if city.strip() or country.strip():
        store.set_place(set_id, city, country)
        if p.get("lat") is not None and not fields.get("city") and not fields.get("country"):
            try:
                store.set_point(set_id, float(p["lat"]), float(p["lng"]))
            except (TypeError, ValueError, KeyError):
                pass
    linked = own = 0
    seen = set()
    conn = get_db()
    with conn:
        for s in doc["sections"]:
            if not isinstance(s, dict):
                continue
            number = str(s.get("number") or "").strip()
            if not number or number.lower() in seen:
                continue
            seen.add(number.lower())
            section_id, base = _base(s.get("master"))
            linked += section_id is not None
            own += section_id is None
            body = [{"id": str(n["id"]), "level": n.get("level") or "PR1", "text": str(n.get("text") or ""),
                     "when": str(n.get("when") or "")}
                    for n in (s.get("body") if isinstance(s.get("body"), list) else [])
                    if isinstance(n, dict) and n.get("id")]
            conn.execute(
                "INSERT INTO spec_set_sections (set_id, section_id, base_version, number, title, "
                "doc_code, body, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (set_id, section_id, base, number, str(s.get("title") or ""),
                 str(s.get("doc_code") or ""), specs.dumps(body),
                 (user["name"] or user["email"]) if user is not None else ""))
    execute("UPDATE spec_sets SET updated_at = datetime('now') WHERE id = ?", (set_id,))
    return set_id, {"kind": doc.get("kind") or "project", "sections": linked + own, "linked": linked,
                    "own": own, "by": doc.get("exported_by") or "", "at": doc.get("exported_at") or ""}
