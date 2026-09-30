"""The specification writer's records: the library, the options, the sets.

`specs` knows what a section is; this knows where one is kept. The master
sections are the office's library, edited by the administrator and versioned
on every save. A set is one project's specification: its header, its choices,
and its own copy of each section it issues.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Mapping

from flask import g

from . import specs, specs_check, specs_seed
from .db import execute, get_db, insert, merge_spec_seed, query, query_one


def _who() -> str:
    user = g.get("user")
    return (user["name"] or user["email"]) if user is not None else ""


def _row(row: Any) -> dict | None:
    return dict(row) if row is not None else None


# --- options and variables ----------------------------------------------------

def options() -> list[dict]:
    out = []
    for row in query("SELECT * FROM spec_options ORDER BY position, id"):
        one = dict(row)
        one["choice_list"] = [c.strip() for c in one["choices"].split("|") if c.strip()]
        out.append(one)
    return out


def variables() -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM spec_variables ORDER BY position, id")]


def _clean_key(key: str) -> str:
    return "".join(c for c in (key or "").strip().lower().replace(" ", "_")
                   if c.isalnum() or c == "_")


def save_options(rows: Iterable[Mapping[str, str]]) -> None:
    """The options as the form sent them: a blank key drops a row."""
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM spec_options")
        for position, row in enumerate(rows, start=1):
            key = _clean_key(row.get("key", ""))
            if not key:
                continue
            choices = "|".join(c.strip() for c in row.get("choices", "").replace(",", "|").split("|")
                               if c.strip())
            kind = "many" if (row.get("kind") or "").strip().lower() == "many" else "one"
            conn.execute(
                "INSERT OR REPLACE INTO spec_options (key, label, choices, default_value, grp, kind, "
                "position) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, row.get("label", "").strip() or key, choices,
                 row.get("default_value", "").strip(), (row.get("grp") or "").strip(), kind,
                 position))


def add_suggested() -> int:
    """The starting questions, choices and words a library lacks, added; what
    it already says is kept."""
    return merge_spec_seed(get_db())


def save_variables(rows: Iterable[Mapping[str, str]]) -> None:
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM spec_variables")
        for position, row in enumerate(rows, start=1):
            key = _clean_key(row.get("key", ""))
            if not key:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO spec_variables (key, label, default_value, position) "
                "VALUES (?, ?, ?, ?)",
                (key, row.get("label", "").strip() or key,
                 row.get("default_value", "").strip(), position))


def chosen_for(spec_set: Mapping[str, Any] | None) -> dict[str, str]:
    """A set's choices, with the default for anything it has not answered."""
    stored = json.loads(spec_set["options"] or "{}") if spec_set else {}
    return {o["key"]: stored[o["key"]] if o["key"] in stored else o["default_value"]
            for o in options()}


def values_for(spec_set: Mapping[str, Any] | None) -> dict[str, str]:
    stored = json.loads(spec_set["variables"] or "{}") if spec_set else {}
    values = {v["key"]: stored.get(v["key"]) or v["default_value"] for v in variables()}
    if spec_set:
        values.setdefault("project", spec_set["name"])
        values.setdefault("client", spec_set["client"])
    return values


# --- the house template -------------------------------------------------------

def template_bytes(family: str = "") -> bytes | None:
    """The template a kind of specification goes out in: its own if it has
    one, else the office's, else (None) the built-in one."""
    if family:
        row = query_one("SELECT content FROM spec_family_templates WHERE family = ?", (family,))
        if row:
            return bytes(row["content"])
    row = query_one("SELECT content FROM spec_template WHERE id = 1")
    return bytes(row["content"]) if row else None


def template_row(family: str = "") -> dict | None:
    if family:
        return _row(query_one("SELECT family, filename, user_name, added_at, length(content) AS size "
                              "FROM spec_family_templates WHERE family = ?", (family,)))
    return _row(query_one("SELECT id, filename, user_name, added_at, length(content) AS size "
                          "FROM spec_template WHERE id = 1"))


def family_templates() -> dict[str, dict]:
    return {r["family"]: dict(r) for r in query(
        "SELECT family, filename, user_name, added_at, length(content) AS size "
        "FROM spec_family_templates")}


def save_template(filename: str, data: bytes, family: str = "") -> None:
    specs.template_info(data)                          # refuses one that will not do
    if family:
        execute("INSERT OR REPLACE INTO spec_family_templates (family, filename, content, user_name, "
                "added_at) VALUES (?, ?, ?, ?, datetime('now'))", (family, filename, data, _who()))
        return
    execute("INSERT OR REPLACE INTO spec_template (id, filename, content, user_name, added_at) "
            "VALUES (1, ?, ?, ?, datetime('now'))", (filename, data, _who()))


def drop_template(family: str = "") -> None:
    if family:
        execute("DELETE FROM spec_family_templates WHERE family = ?", (family,))
        return
    execute("DELETE FROM spec_template WHERE id = 1")


# --- kinds of specification ---------------------------------------------------------

DEFAULT_FAMILY = "15A"


def families() -> list[dict]:
    """The kinds of specification, with how many sections the library has of
    each: the office's three, and any other a library file brought in."""
    counts = {r["family"]: r["n"] for r in query(
        "SELECT family, COUNT(*) AS n FROM spec_sections GROUP BY family")}
    out = [{"code": code, "name": name, "note": note, "sections": counts.pop(code, 0)}
           for code, name, note in specs_seed.FAMILIES]
    out += [{"code": code, "name": code, "note": "", "sections": n} for code, n in sorted(counts.items())
            if code]
    return out


def family_name(code: str) -> str:
    return next((f"{c} {name}" for c, name, _n in specs_seed.FAMILIES if c == code), code)


def clean_family(code: str | None) -> str:
    code = re.sub(r"[^0-9A-Za-z]", "", code or "").upper()[:8]
    return code or DEFAULT_FAMILY


# --- the library ----------------------------------------------------------------

def library(family: str | None = None) -> list[dict]:
    rows = query("SELECT id, family, number, title, version, updated_by, updated_at, note, body, "
                 "applies FROM spec_sections" + (" WHERE family = ?" if family else "")
                 + " ORDER BY family, number", (family,) if family else ())
    out = []
    for row in rows:
        one = dict(row)
        nodes = specs.loads(one.pop("body"))
        one["paragraphs"] = sum(1 for n in nodes if n["level"] not in ("PRT", "ART"))
        one["uses"] = sorted(specs.keys_used(nodes))
        out.append(one)
    return out


def section(section_id: int) -> dict | None:
    return _row(query_one("SELECT * FROM spec_sections WHERE id = ?", (section_id,)))


def section_by_number(number: str, family: str = DEFAULT_FAMILY) -> dict | None:
    return _row(query_one("SELECT * FROM spec_sections WHERE number = ? COLLATE NOCASE "
                          "AND family = ?", (number.strip(), family)))


def versions(section_id: int) -> list[dict]:
    return [dict(r) for r in query(
        "SELECT version, title, note, saved_by, saved_at FROM spec_section_versions "
        "WHERE section_id = ? ORDER BY version DESC", (section_id,))]


def version_body(section_id: int, version: int) -> list[dict] | None:
    row = query_one("SELECT body FROM spec_section_versions WHERE section_id = ? AND version = ?",
                    (section_id, version))
    return specs.loads(row["body"]) if row else None


def save_section(number: str, title: str, nodes: list[dict], note: str = "",
                 section_id: int | None = None, family: str | None = None) -> int:
    """A master section, new or saved over, kept as a new version either way.

    Saving text that is the same as the current version is not a new version:
    a history of identical saves says nothing.
    """
    number, title = number.strip(), title.strip().upper()
    if not number:
        raise specs.SpecError("A section needs its number, as in 032000.")
    if family is None:
        now = section(section_id) if section_id else None
        family = now["family"] if now else DEFAULT_FAMILY
    family = clean_family(family)
    clash = section_by_number(number, family)
    if clash and clash["id"] != section_id:
        raise specs.SpecError(f"Section {number} is already in the {family} library.")
    conn = get_db()
    body = specs.dumps(nodes)
    with conn:
        if section_id is None:
            cursor = conn.execute(
                "INSERT INTO spec_sections (family, number, title, body, version, note, updated_by) "
                "VALUES (?, ?, ?, ?, 1, ?, ?)", (family, number, title, body, note, _who()))
            section_id = int(cursor.lastrowid)
            version = 1
        else:
            now = conn.execute("SELECT * FROM spec_sections WHERE id = ?", (section_id,)).fetchone()
            if now is None:
                raise specs.SpecError("That section is not in the library any more.")
            if (now["body"] == body and now["title"] == title and now["number"] == number
                    and now["family"] == family):
                return section_id
            if now["body"] == body and now["title"] == title and now["number"] == number:
                conn.execute("UPDATE spec_sections SET family = ? WHERE id = ?", (family, section_id))
                return section_id
            version = int(now["version"]) + 1
            conn.execute(
                "UPDATE spec_sections SET family = ?, number = ?, title = ?, body = ?, version = ?, "
                "note = ?, updated_by = ?, updated_at = datetime('now') WHERE id = ?",
                (family, number, title, body, version, note, _who(), section_id))
        conn.execute(
            "INSERT INTO spec_section_versions (section_id, version, title, body, note, saved_by) "
            "VALUES (?, ?, ?, ?, ?, ?)", (section_id, version, title, body, note, _who()))
    return section_id


ALWAYS = "*"


def set_applies(section_id: int, applies: str) -> None:
    """When a library section belongs in a project: a condition on its choices,
    written as a paragraph's is (``fenders!=None``); ``*`` for every project of
    its kind; blank when it is only ever added by hand."""
    applies = re.sub(r"\s*([&|]|!?=)\s*", r"\1", (applies or "").strip())
    execute("UPDATE spec_sections SET applies = ? WHERE id = ?", (applies, section_id))


def fits(applies: str, chosen: Mapping[str, str]) -> bool:
    applies = (applies or "").strip()
    return bool(applies) and (applies == ALWAYS or specs.applies(applies, chosen))


def called_for(chosen: Mapping[str, str], family: str | None = None) -> dict[str, list[dict]]:
    """The library sections a project's choices call for and the ones they rule
    out, of one kind of specification; sections with no condition are in
    neither list."""
    out: dict[str, list[dict]] = {"in": [], "out": []}
    for s in library(family):
        if (s.get("applies") or "").strip():
            out["in" if fits(s["applies"], chosen) else "out"].append(s)
    return out


def import_to_library(filename: str, data: bytes, family: str = "") -> tuple[int, str]:
    """A Word section into the library: a new section, or a new version of one.

    Paragraphs that read the same as the master's keep their ids, so a project
    copy taken earlier still compares cleanly against it.
    """
    read = specs.read_docx(data)
    number = read["number"] or specs.number_from_filename(filename)
    if not number:
        raise specs.SpecError(f"{filename}: no section number in it or in its name.")
    family = clean_family(specs.family_from_filename(filename) or family)
    existing = section_by_number(number, family)
    if existing:
        nodes = specs.align(specs.loads(existing["body"]), read["nodes"])
        save_section(number, read["title"] or existing["title"], nodes,
                     note=f"Read from {filename}", section_id=existing["id"])
        return existing["id"], "updated"
    return save_section(number, read["title"], read["nodes"], note=f"Read from {filename}",
                        family=family), "added"


def delete_section(section_id: int) -> None:
    execute("DELETE FROM spec_sections WHERE id = ?", (section_id,))


def delete_sections(section_ids: Iterable[int]) -> list[dict]:
    """Several sections taken out of the library at once; the ones found."""
    gone = [s for s in (section(i) for i in section_ids) if s]
    for s in gone:
        delete_section(s["id"])
    return gone


# --- sets -----------------------------------------------------------------------

SET_FIELDS = ("name", "code", "client", "header_left", "header_right", "doc_code",
              "revision", "issue_date", "file_pattern")


def sets() -> list[dict]:
    return [dict(r) for r in query(
        "SELECT s.*, (SELECT COUNT(*) FROM spec_set_sections x WHERE x.set_id = s.id) AS sections, "
        "u.name AS creator FROM spec_sets s LEFT JOIN users u ON u.id = s.created_by "
        "ORDER BY s.updated_at DESC, s.id DESC")]


def spec_set(set_id: int) -> dict | None:
    return _row(query_one("SELECT * FROM spec_sets WHERE id = ?", (set_id,)))


def create_set(fields: Mapping[str, str], copy_from: int | None = None) -> int:
    """A new project specification, blank or started from another one.

    Started from another, it takes that one's header, choices and sections —
    amendments and all — which is how a project that is like the last one
    starts from the last one rather than from the master.
    """
    name = (fields.get("name") or "").strip()
    if not name:
        raise specs.SpecError("Give the specification a project name.")
    source = spec_set(copy_from) if copy_from else None
    values = {k: (fields.get(k) or (source[k] if source else "") or "").strip() for k in SET_FIELDS}
    values["name"] = name
    values["file_pattern"] = values["file_pattern"] or "SPC-{number}"
    values["revision"] = values["revision"] or "0"
    family = clean_family(fields.get("family") or (source["family"] if source else ""))
    # A new project of a kind starts on that kind's basis: British standards
    # and English for 03A, American for 15A, and so on.
    answers = (source["options"] if source else
               json.dumps(specs_seed.FAMILY_DEFAULTS.get(family, {}), ensure_ascii=False))
    set_id = insert(
        f"INSERT INTO spec_sets ({', '.join(SET_FIELDS)}, family, options, variables, declined, "
        f"created_by) VALUES ({', '.join('?' * len(SET_FIELDS))}, ?, ?, ?, ?, ?)",
        [values[k] for k in SET_FIELDS] + [family, answers,
                                           source["variables"] if source else "{}",
                                           source["declined"] if source else "[]",
                                           g.user["id"] if g.get("user") else None])
    if source:
        conn = get_db()
        with conn:
            conn.execute(
                "INSERT INTO spec_set_sections (set_id, section_id, base_version, number, title, "
                "doc_code, body, updated_by) SELECT ?, section_id, base_version, number, title, "
                "doc_code, body, ? FROM spec_set_sections WHERE set_id = ?",
                (set_id, _who(), copy_from))
    return set_id


def update_set(set_id: int, fields: Mapping[str, str], chosen: Mapping[str, str],
               values: Mapping[str, str]) -> None:
    current = spec_set(set_id)
    if current is None:
        raise specs.SpecError("That specification is not here any more.")
    merged = {k: (fields.get(k, current[k]) or "").strip() for k in SET_FIELDS}
    if not merged["name"]:
        raise specs.SpecError("The project name cannot be blank.")
    merged["file_pattern"] = merged["file_pattern"] or "SPC-{number}"
    execute(
        f"UPDATE spec_sets SET {', '.join(f'{k} = ?' for k in SET_FIELDS)}, options = ?, "
        "variables = ?, updated_at = datetime('now') WHERE id = ?",
        [merged[k] for k in SET_FIELDS]
        + [json.dumps(dict(chosen), ensure_ascii=False), json.dumps(dict(values), ensure_ascii=False),
           set_id])
    if "hold_shown" in fields:                   # the page's tick box: absent when unticked
        execute("UPDATE spec_sets SET hold_issue = ? WHERE id = ?",
                (1 if fields.get("hold_issue") else 0, set_id))
    if fields.get("family"):
        execute("UPDATE spec_sets SET family = ? WHERE id = ?", (clean_family(fields["family"]), set_id))


def delete_set(set_id: int) -> None:
    execute("DELETE FROM spec_sets WHERE id = ?", (set_id,))


def _touch(set_id: int) -> None:
    get_db().execute("UPDATE spec_sets SET updated_at = datetime('now') WHERE id = ?", (set_id,))


def set_sections(set_id: int) -> list[dict]:
    """A set's sections, each with how it stands against its master."""
    out = []
    for row in query("SELECT x.*, s.version AS master_version, COALESCE(s.applies, '') AS applies "
                     "FROM spec_set_sections x "
                     "LEFT JOIN spec_sections s ON s.id = x.section_id "
                     "WHERE x.set_id = ? ORDER BY x.number", (set_id,)):
        one = dict(row)
        nodes = specs.loads(one["body"])
        base = (version_body(one["section_id"], one["base_version"])
                if one["section_id"] else None)
        counted = specs.amendments(base or [], nodes) if base is not None else None
        one["added"] = counted["added"] if counted else None
        one["changed"] = counted["changed"] if counted else None
        one["removed"] = counted["removed"] if counted else None
        bits = [f"{counted[k]} {w}" for k, w in (("added", "added"), ("changed", "changed"),
                                                   ("removed", "dropped")) if counted and counted[k]]
        one["summary"] = ", ".join(bits)
        one["behind"] = bool(one["section_id"] and one["master_version"]
                             and one["master_version"] > one["base_version"])
        one["own"] = not one["section_id"]
        out.append(one)
    return out


def set_section(set_id: int, row_id: int) -> dict | None:
    return _row(query_one("SELECT x.*, s.version AS master_version FROM spec_set_sections x "
                          "LEFT JOIN spec_sections s ON s.id = x.section_id "
                          "WHERE x.id = ? AND x.set_id = ?", (row_id, set_id)))


def add_sections(set_id: int, section_ids: Iterable[int]) -> int:
    """Copies of these master sections into a set; ones it has are left alone."""
    section_ids = list(section_ids)
    added = 0
    conn = get_db()
    with conn:
        for section_id in section_ids:
            master = conn.execute("SELECT * FROM spec_sections WHERE id = ?", (section_id,)).fetchone()
            if master is None:
                continue
            cursor = conn.execute(
                "INSERT OR IGNORE INTO spec_set_sections (set_id, section_id, base_version, number, "
                "title, body, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (set_id, master["id"], master["version"], master["number"], master["title"],
                 master["body"], _who()))
            added += cursor.rowcount
        _touch(set_id)
    _decline(set_id, drop=section_ids)
    return added


def declined(row: Mapping[str, Any] | None) -> set[int]:
    """The library sections a project took out although its answers call for
    them: they are not put back each time the answers are saved."""
    try:
        return {int(i) for i in json.loads((row or {}).get("declined") or "[]")}
    except (TypeError, ValueError):
        return set()


def _decline(set_id: int, add: Iterable[int] = (), drop: Iterable[int] = ()) -> None:
    row = spec_set(set_id)
    if row is None:
        return
    now = (declined(row) | set(add)) - set(drop)
    if now != declined(row):
        execute("UPDATE spec_sets SET declined = ? WHERE id = ?", (json.dumps(sorted(now)), set_id))


def auto_add(set_id: int) -> dict[str, list[dict]]:
    """The library sections this project's answers call for, added; and the
    ones it has that its answers now rule out, named but left in (taking a
    section out would lose its amendments, so that is the engineer's call).

    Sections the engineer took out by hand stay out.
    """
    row = spec_set(set_id)
    chosen = chosen_for(row)
    called = called_for(chosen, row["family"])
    have = {r["section_id"] for r in query("SELECT section_id FROM spec_set_sections "
                                           "WHERE set_id = ?", (set_id,)) if r["section_id"]}
    numbers = {r["number"].lower() for r in query("SELECT number FROM spec_set_sections "
                                                  "WHERE set_id = ?", (set_id,))}
    skip = declined(row)
    wanted = [s for s in called["in"] if s["id"] not in have and s["id"] not in skip
              and s["number"].lower() not in numbers]
    if wanted:
        add_sections(set_id, [s["id"] for s in wanted])
    return {"added": wanted, "out": [s for s in called["out"] if s["id"] in have]}


def ruled_out(set_id: int) -> set[int]:
    """The library sections this project has that its answers rule out."""
    row = spec_set(set_id)
    have = {r["section_id"] for r in query("SELECT section_id FROM spec_set_sections "
                                           "WHERE set_id = ?", (set_id,)) if r["section_id"]}
    return {s["id"] for s in called_for(chosen_for(row), row["family"])["out"] if s["id"] in have}


def remove_by_master(set_id: int, section_ids: Iterable[int]) -> int:
    """The project's copies of these library sections taken out; how many."""
    wanted = set(section_ids)
    rows = [r for r in query("SELECT id, section_id FROM spec_set_sections WHERE set_id = ?", (set_id,))
            if r["section_id"] in wanted]
    for r in rows:
        remove_set_section(set_id, r["id"])
    return len(rows)


def save_set_section(set_id: int, row_id: int, nodes: list[dict], title: str | None = None,
                     doc_code: str | None = None) -> None:
    current = set_section(set_id, row_id)
    if current is None:
        raise specs.SpecError("That section is not in this specification any more.")
    execute("UPDATE spec_set_sections SET body = ?, title = ?, doc_code = ?, updated_by = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (specs.dumps(nodes), (title if title is not None else current["title"]).strip().upper(),
             (doc_code if doc_code is not None else current["doc_code"]).strip(), _who(), row_id))
    _touch(set_id)


def base_of(row: Mapping[str, Any]) -> list[dict] | None:
    """The master text a project section was copied from, as it was then."""
    if not row.get("section_id"):
        return None
    return version_body(row["section_id"], row["base_version"])


def reset_to_master(set_id: int, row_id: int) -> None:
    row = set_section(set_id, row_id)
    master = section(row["section_id"]) if row and row["section_id"] else None
    if master is None:
        raise specs.SpecError("This section has no master to go back to.")
    execute("UPDATE spec_set_sections SET body = ?, base_version = ?, title = ?, updated_by = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (master["body"], master["version"], master["title"], _who(), row_id))
    _touch(set_id)


def bring_up_to_date(set_id: int, row_id: int) -> None:
    """The newer master brought in, the project's amendments kept."""
    row = set_section(set_id, row_id)
    master = section(row["section_id"]) if row and row["section_id"] else None
    if master is None:
        raise specs.SpecError("This section has no master to bring in.")
    base = base_of(row) or []
    merged = specs.merge(base, specs.loads(master["body"]), specs.loads(row["body"]))
    execute("UPDATE spec_set_sections SET body = ?, base_version = ?, updated_by = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (specs.dumps(merged), master["version"], _who(), row_id))
    _touch(set_id)


def remove_set_section(set_id: int, row_id: int) -> None:
    row = set_section(set_id, row_id)
    execute("DELETE FROM spec_set_sections WHERE id = ? AND set_id = ?", (row_id, set_id))
    _touch(set_id)
    master = section(row["section_id"]) if row and row["section_id"] else None
    if master and fits(master["applies"], chosen_for(spec_set(set_id))):
        _decline(set_id, add=[master["id"]])


def import_to_set(set_id: int, filename: str, data: bytes) -> tuple[int, str]:
    """A project's own Word section — an old one, or one amended outside.

    It is lined up against the master of the same number, so what it changed
    shows up as amendments; a section the library does not have comes in as
    the project's own.
    """
    read = specs.read_docx(data)
    number = read["number"] or specs.number_from_filename(filename)
    if not number:
        raise specs.SpecError(f"{filename}: no section number in it or in its name.")
    have = query_one("SELECT * FROM spec_set_sections WHERE set_id = ? AND number = ? COLLATE NOCASE",
                     (set_id, number))
    project = spec_set(set_id)
    master = section_by_number(number, project["family"] if project else DEFAULT_FAMILY)
    if have:
        nodes = specs.align(specs.loads(have["body"]), read["nodes"])
        save_set_section(set_id, have["id"], nodes, title=read["title"] or have["title"])
        return have["id"], "updated"
    if master:
        nodes = specs.align(specs.loads(master["body"]), read["nodes"])
        row_id = insert(
            "INSERT INTO spec_set_sections (set_id, section_id, base_version, number, title, body, "
            "updated_by) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (set_id, master["id"], master["version"], master["number"],
             (read["title"] or master["title"]).upper(), specs.dumps(nodes), _who()))
    else:
        row_id = insert(
            "INSERT INTO spec_set_sections (set_id, number, title, body, updated_by) "
            "VALUES (?, ?, ?, ?, ?)",
            (set_id, number, read["title"].upper(), specs.dumps(read["nodes"]), _who()))
    _touch(set_id)
    return row_id, "added"


def new_own_section(set_id: int, number: str, title: str) -> int:
    number = number.strip()
    if not number:
        raise specs.SpecError("A section needs its number.")
    if query_one("SELECT 1 FROM spec_set_sections WHERE set_id = ? AND number = ? COLLATE NOCASE",
                 (set_id, number)):
        raise specs.SpecError(f"Section {number} is already in this specification.")
    starter = [specs.node("PRT", "GENERAL"), specs.node("ART", "SUMMARY"),
               specs.node("PRT", "PRODUCTS"), specs.node("PRT", "EXECUTION")]
    row_id = insert("INSERT INTO spec_set_sections (set_id, number, title, body, updated_by) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (set_id, number, title.strip().upper(), specs.dumps(starter), _who()))
    _touch(set_id)
    return row_id


def promote(set_id: int, row_id: int) -> int:
    """A project's section made the master: the library takes its text.

    For the section a project wrote that the library lacks, or an amendment
    good enough that every project should have it.
    """
    row = set_section(set_id, row_id)
    if row is None:
        raise specs.SpecError("That section is not in this specification any more.")
    nodes = specs.loads(row["body"])
    family = (spec_set(set_id) or {}).get("family") or DEFAULT_FAMILY
    master = section_by_number(row["number"], family)
    section_id = save_section(row["number"], row["title"], nodes,
                              note="Taken from a project specification",
                              section_id=master["id"] if master else None, family=family)
    fresh = section(section_id)
    execute("UPDATE spec_set_sections SET section_id = ?, base_version = ? WHERE id = ?",
            (section_id, fresh["version"], row_id))
    return section_id


# --- standards ------------------------------------------------------------------

def equivalents() -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM spec_standards ORDER BY position, id")]


def withdrawn() -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM spec_withdrawn ORDER BY position, id")]


def save_standards(pairs: Iterable[Mapping[str, str]], gone: Iterable[Mapping[str, str]]) -> None:
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM spec_standards")
        for i, row in enumerate(pairs, start=1):
            if (row.get("bs") or "").strip() and (row.get("us") or "").strip():
                conn.execute("INSERT INTO spec_standards (topic, bs, us, position) VALUES (?, ?, ?, ?)",
                             (row.get("topic", "").strip(), row["bs"].strip(), row["us"].strip(), i))
        conn.execute("DELETE FROM spec_withdrawn")
        for i, row in enumerate(gone, start=1):
            if (row.get("old") or "").strip():
                conn.execute("INSERT INTO spec_withdrawn (old, new, note, position) VALUES (?, ?, ?, ?)",
                             (row["old"].strip(), (row.get("new") or "").strip(),
                              (row.get("note") or "").strip(), i))


def standards_table() -> specs_check.Standards:
    if "spec_standards" not in g:
        g.spec_standards = specs_check.Standards(equivalents(), withdrawn())
    return g.spec_standards


# --- reading a set whole: references, basis, checks -------------------------------

def _whole(rows: Iterable[Mapping[str, Any]]) -> list[dict]:
    return [{"id": r["id"], "number": r["number"], "title": r["title"],
             "nodes": specs.loads(r["body"])} for r in rows]


def set_whole(set_id: int) -> list[dict]:
    return _whole(query("SELECT id, number, title, body FROM spec_set_sections WHERE set_id = ? "
                        "ORDER BY number", (set_id,)))


def library_whole(family: str | None = None) -> list[dict]:
    return _whole(query("SELECT id, number, title, body FROM spec_sections"
                        + (" WHERE family = ?" if family else "") + " ORDER BY number",
                        (family,) if family else ()))


def reader(sections: list[dict], chosen: Mapping[str, str],
           standards: bool = True) -> specs_check.Reader:
    """What turns a section's text as kept into the text as issued, for one
    set of sections: the references written out, the standards on the basis."""
    return specs_check.Reader(sections, chosen, standards_table() if standards else None)


ADVICE = ("repeated",)
GROUPS = ("model", "references", "outdated", "standards", "discrepancies", "repeated", "setup")


def check_set(set_id: int) -> dict:
    """The checker's report for a project, each item keyed and marked with what
    the engineer decided about it, if anything."""
    report = _check_set(set_id)
    settled = {r["key"]: dict(r) for r in query(
        "SELECT key, state, settled_by, settled_at FROM spec_check_settled WHERE set_id = ?",
        (set_id,))}
    report["open"] = {}
    for group in GROUPS:
        for item in report[group]:
            item["key"] = _item_key(group, item)
            item["settled"] = settled.get(item["key"])
        report["open"][group] = sum(1 for i in report[group] if not i["settled"])
    return report


def _item_key(group: str, item: Mapping[str, Any]) -> str:
    """What names a check item from one check to the next: what it says about
    which paragraph. Change the paragraph's words and it is a new item."""
    import hashlib

    where = item.get("node_id") or item.get("path") or ""
    basis = "|".join((group, item.get("section") or "", where, item.get("message") or "",
                      item.get("text") or ""))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def settle(set_id: int, key: str, state: str, message: str = "") -> None:
    """An item accepted or rejected; a blank state opens it again."""
    if state not in ("accepted", "rejected", ""):
        raise specs.SpecError("An item is accepted or rejected.")
    with get_db() as conn:
        conn.execute("DELETE FROM spec_check_settled WHERE set_id = ? AND key = ?", (set_id, key))
        if state:
            conn.execute("INSERT INTO spec_check_settled (set_id, key, state, message, settled_by) "
                         "VALUES (?, ?, ?, ?, ?)", (set_id, key, state, message[:300], _who()))


def open_items(set_id: int, report: Mapping[str, Any] | None = None) -> dict:
    """What still waits for an accept or reject: check items and language
    suggestions (each change counted once, however many places it is in)."""
    report = report if report is not None else check_set(set_id)
    # Paragraphs said twice are advice on keeping the text tidy; they do not hold an issue.
    checks = sum(n for group, n in report["open"].items() if group not in ADVICE)
    changes = {(f["kind"], f["old"].lower(), f["new"].lower(), f["message"] if not f["old"] else "")
               for f in language_set(set_id)}
    return {"checks": checks, "language": len(changes), "total": checks + len(changes)}


def _check_set(set_id: int) -> dict:
    row = spec_set(set_id)
    chosen = chosen_for(row)
    report = specs_check.check(set_whole(set_id), chosen, values_for(row), options(),
                               standards_table())
    # Sections the answers call for that are missing, and ones they rule out.
    have = {r["section_id"] for r in set_sections(set_id) if r["section_id"]}
    called = called_for(chosen, row["family"])
    skip = declined(row)
    for s in called["in"]:
        if s["id"] not in have:
            why = "every project of its kind has it" if s["applies"] == ALWAYS else \
                f"the choices call for it ({s['applies']})"
            report["setup"].append(_fit(s, why + (", and it was taken out of this specification: "
                                                  "accept if that was meant" if s["id"] in skip else
                                                  ", and it is not in this specification: add it"),
                                        "warning"))
    for s in called["out"]:
        if s["id"] in have:
            report["setup"].append(_fit(s, "it is in this specification, but it is for "
                                           + s["applies"] + ", which the choices rule out"))
    report["model"] = model_items(model_for(row))
    for label, value, elsewhere in uncovered(chosen, row["family"]):
        report["setup"].append({
            "section": "", "row_id": None, "path": "", "severity": "warning", "text": "",
            "fix": None, "message": f"{label}: {value}. Nothing in the {row['family']} library is "
                                    "written for this answer: check the sections cover it, or add "
                                    "a section for it" + (f" ({', '.join(elsewhere)} has one to "
                                                          "borrow)" if elsewhere else "")})
    report["counts"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    return report


NOT_AN_ELEMENT = {"", "none", "no"}


def _covers() -> dict[str, list[tuple[str, bool, set[str]]]]:
    """Every condition the library is written for, by kind: section and
    paragraph conditions and inline choices, split into their parts."""
    out: dict[str, list[tuple[str, bool, set[str]]]] = {}
    for row in query("SELECT family, applies, body FROM spec_sections"):
        conditions = [row["applies"] or ""]
        for n in specs.loads(row["body"]):
            conditions.append(n.get("when") or "")
            conditions += specs.inline_conditions(n.get("text", ""))
        parts = out.setdefault(row["family"], [])
        for condition in conditions:
            for part in condition.split("&"):
                if "=" not in part:
                    continue
                negate = "!=" in part
                key, _, wanted = part.partition("!=" if negate else "=")
                parts.append((key.strip(), negate, {specs._norm(w) for w in wanted.split("|")}))
    return out


def uncovered(chosen: Mapping[str, str], family: str | None = None
              ) -> list[tuple[str, str, list[str]]]:
    """Answers that call for something no library section or paragraph of the
    project's kind is written for: a project element the library has nothing
    to say about. Each comes with the other kinds that do have something.

    The basis questions (standards, English, stage and the like) change how
    everything reads rather than what is specified, so they are left out, and
    so is each question's default, and the kind's own starting answer: the
    sections as they stand are written for those.
    """
    covers = _covers()
    mine = (covers.get(family, []) if family else [p for ps in covers.values() for p in ps])
    starts = specs_seed.FAMILY_DEFAULTS.get(family or "", {})

    def covered(parts, key, v):
        return any(k == key and ((v in w) != negate) for k, negate, w in parts)

    out = []
    for o in options():
        if (o.get("grp") or "") == "Basis":
            continue
        # The plain case (the question's default) is what the sections say as they stand.
        plain = {specs._norm(v) for v in (o.get("default_value") or "").split("|")}
        plain.add(specs._norm(starts.get(o["key"], "")))
        for value in (chosen.get(o["key"]) or "").split("|"):
            v = specs._norm(value)
            if v in NOT_AN_ELEMENT or v in plain:
                continue
            if not covered(mine, o["key"], v):
                elsewhere = sorted(f for f, parts in covers.items()
                                   if family and f != family and covered(parts, o["key"], v))
                out.append((o["label"], value.strip(), elsewhere))
    return out


def _fit(s: Mapping[str, Any], message: str, severity: str = "info") -> dict:
    return {"section": s["number"], "row_id": None, "path": "", "severity": severity,
            "message": f"Section {s['number']} {specs_check.title_case(s['title'])}: {message}",
            "text": "", "fix": None}


def check_library(family: str | None = None) -> dict:
    everything = {o["key"]: "|".join(o["choice_list"]) for o in options()}
    everything["standards"] = ""
    report = specs_check.check(library_whole(family), everything,
                               {v["key"]: v["default_value"] or v["key"] for v in variables()},
                               options(), standards_table())
    report.setdefault("model", [])
    return report


def _rewrite(rows: list[dict], change) -> int:
    """``change(text, section)`` applied to every paragraph; what changed is counted."""
    total = 0
    for s in rows:
        edited, count = [], 0
        for n in s["nodes"]:
            text, k = change(n["text"], s)
            count += k
            edited.append(dict(n, text=text))
        if count:
            s["nodes"] = edited
            s["changed"] = count
            total += count
    return total


def fix_set(set_id: int, action: str, **how: str) -> int:
    """One of the checker's fixes, applied to this project's copies only."""
    rows = set_whole(set_id)
    if how.get("row_id"):
        rows = [r for r in rows if r["id"] == int(how["row_id"])]
    count = _apply(action, rows, set_whole(set_id), chosen_for(spec_set(set_id)), how)
    for s in rows:
        if s.get("changed"):
            save_set_section(set_id, s["id"], s["nodes"])
    if action == "variable" and count:
        _ensure_variable(how["name"], how.get("value", ""))
        current = spec_set(set_id)
        values = json.loads(current["variables"] or "{}")
        values[how["name"]] = how.get("value", "")
        execute("UPDATE spec_sets SET variables = ? WHERE id = ?",
                (json.dumps(values, ensure_ascii=False), set_id))
    return count


def fix_library(action: str, family: str | None = None, **how: str) -> int:
    """The same, on the masters: each section changed is saved as a new version."""
    rows = library_whole(family)
    everything = {o["key"]: "|".join(o["choice_list"]) for o in options()}
    count = _apply(action, rows, rows, everything, how)
    note = {"link": "Typed references made live", "replace": f"{how.get('old')} replaced by {how.get('new')}",
            "variable": f"{how.get('value')} made {{{{{how.get('name')}}}}}"}.get(action, "")
    for s in rows:
        if s.get("changed"):
            master = section(s["id"])
            save_section(master["number"], master["title"], s["nodes"], note=note, section_id=s["id"])
    if action == "variable" and count:
        _ensure_variable(how["name"], how.get("value", ""), default=True)
    return count


def _apply(action: str, rows: list[dict], everything: list[dict], chosen: Mapping[str, str],
           how: Mapping[str, str]) -> int:
    if action == "link":
        where = specs_check.index(everything, chosen)
        return _rewrite(rows, lambda text, s: specs_check.link_typed(text, s["number"], where))
    if action == "replace":
        old, new = how.get("old", ""), how.get("new", "")
        if not old or not new:
            raise specs.SpecError("Say which standard replaces which.")
        return _rewrite(rows, lambda text, s: specs_check.replace_standard(text, old, new))
    if action == "variable":
        name = _clean_key(how.get("name", ""))
        value = how.get("value", "")
        if not name or not value:
            raise specs.SpecError("Give the variable a name.")
        how = dict(how, name=name)
        prop = how.get("property", "")
        return _rewrite(rows, lambda text, s: specs_check.make_variable(text, value, name, prop))
    raise specs.SpecError("That is not a fix this knows.")


def _ensure_variable(name: str, value: str, default: bool = False) -> None:
    name = _clean_key(name)
    have = query_one("SELECT * FROM spec_variables WHERE key = ?", (name,))
    if have is None:
        last = query_one("SELECT COALESCE(MAX(position), 0) AS n FROM spec_variables")["n"]
        execute("INSERT INTO spec_variables (key, label, default_value, position) VALUES (?, ?, ?, ?)",
                (name, name.replace("_", " ").capitalize(), value if default else "", last + 1))
    elif default and not have["default_value"]:
        execute("UPDATE spec_variables SET default_value = ? WHERE key = ?", (value, name))


# --- the library as one file -----------------------------------------------------

def pack() -> bytes:
    """The whole library — sections, questions, words, standards — as one file,
    to back up, to move to another site, or to start one from."""
    import io
    import zipfile

    data = {
        "format": "specs-writer-library/1",
        "sections": [{"family": s["family"], "number": s["number"], "title": s["title"],
                      "applies": s.get("applies") or "", "body": specs.loads(s["body"])}
                     for s in (dict(r) for r in query("SELECT * FROM spec_sections "
                                                      "ORDER BY family, number"))],
        "options": [{k: o[k] for k in ("key", "label", "choices", "default_value", "grp", "kind")}
                    for o in options()],
        "variables": [{k: v[k] for k in ("key", "label", "default_value")} for v in variables()],
        "standards": [{k: r[k] for k in ("topic", "bs", "us")} for r in equivalents()],
        "withdrawn": [{k: r[k] for k in ("old", "new", "note")} for r in withdrawn()],
        "wording": [{k: r[k] for k in ("find", "replace", "note", "cond", "unless_next")}
                    for r in wording()],
    }
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("library.json", json.dumps(data, ensure_ascii=False, indent=1))
        template = template_bytes()
        if template:
            z.writestr("template.docx", template)
        for family in family_templates():
            z.writestr(f"templates/{family}.docx", template_bytes(family))
    return out.getvalue()


LOAD_MODES = ("update", "add", "replace")


def unpack(data: bytes, mode: str = "update") -> dict:
    """A library file read in, one of three ways.

    ``update``: sections it has become new versions of the ones here (or new
    sections); questions and words it has are added or updated; nothing here
    that it lacks is removed. ``add``: only what is not here yet comes in,
    and nothing here is changed. ``replace``: as ``update``, and then every
    section of the kinds the file carries that the file does not have is
    taken out of the library (projects keep their own copies).
    """
    if mode not in LOAD_MODES:
        mode = "update"
    import io
    import zipfile

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        loaded = json.loads(z.read("library.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise specs.SpecError("That is not a Specs Writer library file.") from exc
    if not str(loaded.get("format", "")).startswith("specs-writer-library/"):
        raise specs.SpecError("That is not a Specs Writer library file.")
    counted = {"sections": 0, "options": 0, "variables": 0, "standards": 0,
               "added": 0, "updated": 0, "same": 0, "kept": 0, "removed": []}
    in_file: dict[str, set[str]] = {}
    for s in loaded.get("sections", []):
        nodes = [specs.node(n["level"], n["text"], n.get("when", ""), n.get("id"))
                 for n in s.get("body", []) if n.get("level") in specs.KINDS]
        family = clean_family(s.get("family") or loaded.get("family"))
        in_file.setdefault(family, set()).add(s["number"].strip().upper())
        have = section_by_number(s["number"], family)
        counted["sections"] += 1
        if have and mode == "add":
            counted["kept"] += 1
            continue
        if have:
            nodes = specs.align(specs.loads(have["body"]), nodes) if not _same_ids(have, nodes) else nodes
        section_id = save_section(s["number"], s.get("title", ""), nodes,
                                  note="Read from a library file",
                                  section_id=have["id"] if have else None, family=family)
        if "applies" in s:
            set_applies(section_id, s["applies"])
        if not have:
            counted["added"] += 1
        elif section(section_id)["version"] != have["version"]:
            counted["updated"] += 1
        else:
            counted["same"] += 1
    if mode == "replace":
        for family, numbers in in_file.items():
            for r in library(family):
                if r["number"].upper() not in numbers:
                    delete_section(r["id"])
                    counted["removed"].append(f"{family} {r['number']}")
    conn = get_db()
    with conn:
        for o in loaded.get("options", []):
            last = conn.execute("SELECT COALESCE(MAX(position), 0) AS n FROM spec_options").fetchone()["n"]
            conn.execute(
                "INSERT INTO spec_options (key, label, choices, default_value, grp, kind, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO "
                + ("NOTHING" if mode == "add" else
                   "UPDATE SET label = excluded.label, choices = excluded.choices, "
                   "default_value = excluded.default_value, grp = excluded.grp, kind = excluded.kind"),
                (_clean_key(o["key"]), o.get("label", ""), o.get("choices", ""),
                 o.get("default_value", ""), o.get("grp", ""), o.get("kind", "one"), last + 1))
            counted["options"] += 1
        for v in loaded.get("variables", []):
            last = conn.execute("SELECT COALESCE(MAX(position), 0) AS n FROM spec_variables").fetchone()["n"]
            conn.execute(
                "INSERT INTO spec_variables (key, label, default_value, position) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO " + ("NOTHING" if mode == "add" else
                                          "UPDATE SET label = excluded.label, "
                                          "default_value = excluded.default_value"),
                (_clean_key(v["key"]), v.get("label", ""), v.get("default_value", ""), last + 1))
            counted["variables"] += 1
        if loaded.get("standards") is not None:
            have = {(r["bs"], r["us"]) for r in conn.execute("SELECT bs, us FROM spec_standards")}
            for r in loaded["standards"]:
                if (r["bs"], r["us"]) not in have:
                    conn.execute("INSERT INTO spec_standards (topic, bs, us, position) VALUES (?, ?, ?, 999)",
                                 (r.get("topic", ""), r["bs"], r["us"]))
                    counted["standards"] += 1
        if loaded.get("withdrawn") is not None:
            have = {r["old"] for r in conn.execute("SELECT old FROM spec_withdrawn")}
            for r in loaded["withdrawn"]:
                if r["old"] not in have:
                    conn.execute("INSERT INTO spec_withdrawn (old, new, note, position) VALUES (?, ?, ?, 999)",
                                 (r["old"], r.get("new", ""), r.get("note", "")))
                    counted["standards"] += 1
        if loaded.get("wording") is not None:
            have = {r["find"].lower() for r in conn.execute("SELECT find FROM spec_wording")}
            for r in loaded["wording"]:
                if (r.get("find") or "").lower() not in have:
                    conn.execute("INSERT INTO spec_wording (find, replace, note, cond, unless_next, "
                                 "position) VALUES (?, ?, ?, ?, ?, 999)",
                                 (r["find"], r.get("replace", ""), r.get("note", ""),
                                  r.get("cond", ""), r.get("unless_next", "")))
    if "template.docx" in z.namelist() and template_bytes() is None:
        save_template("house-template.docx", z.read("template.docx"))
    # A kind's own template comes with its sections: it is how they look.
    for name in z.namelist():
        m = re.fullmatch(r"templates/([0-9A-Za-z]{1,8})\.docx", name)
        if m and not (mode == "add" and template_row(clean_family(m.group(1)))):
            save_template(f"{m.group(1)}-template.docx", z.read(name), family=clean_family(m.group(1)))
    return counted


def _same_ids(have: Mapping[str, Any], nodes: list[dict]) -> bool:
    """Whether a file's section already carries this library's paragraph ids
    (it came from here), in which case they are kept as they are."""
    mine = {n["id"] for n in specs.loads(have["body"])}
    return bool(mine & {n["id"] for n in nodes})


# --- what the project's model says ----------------------------------------------------

def model_for(row: Mapping[str, Any] | None) -> dict | None:
    try:
        return json.loads(row["model"]) if row and row.get("model") else None
    except ValueError:
        return None


def save_model(set_id: int, found: Mapping[str, Any] | None) -> None:
    execute("UPDATE spec_sets SET model = ? WHERE id = ?",
            (json.dumps(dict(found), ensure_ascii=False) if found else "", set_id))


def apply_model(set_id: int, found: Mapping[str, Any]) -> list[str]:
    """The model's elements ticked in this project's answers — added to what
    is ticked, nothing unticked — and its concrete class taken for the words
    the project fills in when it has none of its own. What changed, in words."""
    row = spec_set(set_id)
    stored = json.loads(row["options"] or "{}")
    chosen = chosen_for(row)
    kinds = {o["key"]: o for o in options()}
    changed = []
    for e in found.get("elements", []):
        o = kinds.get(e["key"])
        if o is None or specs._norm(e["value"]) not in {specs._norm(c) for c in o["choice_list"]}:
            continue
        if o["kind"] == "many":
            now = [v for v in (chosen.get(e["key"]) or "").split("|")
                   if v and specs._norm(v) not in ("none", "")]
            if specs._norm(e["value"]) in {specs._norm(v) for v in now}:
                continue
            stored[e["key"]] = "|".join(now + [e["value"]])
        else:
            if specs._norm(chosen.get(e["key"])) == specs._norm(e["value"]):
                continue
            stored[e["key"]] = e["value"]
        changed.append(f"{o['label']}: {e['value']}")
    values = json.loads(row["variables"] or "{}")
    grade = found.get("concrete_class") or ""
    if grade and not values.get("concrete_class"):
        values["concrete_class"] = grade
        changed.append(f"Structural concrete strength class: {grade}")
    execute("UPDATE spec_sets SET options = ?, variables = ?, updated_at = datetime('now') "
            "WHERE id = ?", (json.dumps(stored, ensure_ascii=False),
                             json.dumps(values, ensure_ascii=False), set_id))
    return changed


MODEL_SEVERITY = {"unrealistic": "error", "check": "warning", "missing": "info"}


def model_items(found: Mapping[str, Any] | None) -> list[dict]:
    """The grades the model gives that do not look right, as check items."""
    out = []
    for kind, what in (("concrete", "Concrete"), ("steel", "Steel")):
        for m in (found or {}).get(kind, []):
            if m.get("state") not in MODEL_SEVERITY:
                continue
            used = ", ".join(m.get("used_in") or [])
            out.append({"section": "", "row_id": None, "path": "", "node_id": "",
                        "severity": MODEL_SEVERITY[m["state"]], "fix": None,
                        "text": m.get("material", ""), "words": m.get("grade") or "",
                        "message": f"{what} \"{m.get('material', '')}\""
                                   + (f" ({used})" if used else "") + ": " + (m.get("note") or ""),
                        "where": "The model" + (f", {found.get('filename')}" if found.get("filename") else "")})
    return out


# --- language and wording ------------------------------------------------------------

def wording() -> list[dict]:
    return [dict(r) for r in query("SELECT * FROM spec_wording ORDER BY position, id")]


def save_wording(rows: Iterable[Mapping[str, str]]) -> None:
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM spec_wording")
        for i, row in enumerate(rows, start=1):
            if (row.get("find") or "").strip():
                conn.execute(
                    "INSERT INTO spec_wording (find, replace, note, cond, unless_next, position) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (row["find"].strip(), (row.get("replace") or "").strip(),
                     (row.get("note") or "").strip(), (row.get("cond") or "").strip(),
                     (row.get("unless_next") or "").strip(), i))


def ignored(scope: int) -> list[str]:
    return [r["words"] for r in query("SELECT words FROM spec_ignored WHERE scope = ?", (scope,))]


def ignore(scope: int, words: str) -> None:
    if words.strip():
        execute("INSERT OR IGNORE INTO spec_ignored (scope, words) VALUES (?, ?)",
                (scope, words.strip().lower()))


def _rules() -> list[dict]:
    return [dict(r, when=r["cond"]) for r in wording()]


def language_set(set_id: int) -> list[dict]:
    from . import specs_language

    chosen = chosen_for(spec_set(set_id))
    return specs_language.findings(set_whole(set_id), chosen, chosen.get("english", ""),
                                   _rules(), ignored(set_id))


def language_library() -> list[dict]:
    from . import specs_language

    defaults = chosen_for(None)
    everything = {o["key"]: "|".join(o["choice_list"]) for o in options()}
    # The library is read with every paragraph on, in the office's own English,
    # and without the project scope's rewording, which belongs to projects.
    rules = [r for r in _rules() if not r["cond"]]
    return specs_language.findings(library_whole(), everything, defaults.get("english", ""),
                                   rules, ignored(0))


def accept_language(rows: list[dict], how: Mapping[str, str]) -> int:
    """A suggestion taken in the paragraph it was made for, or — asked for —
    the same words changed in every paragraph."""
    from . import specs_language

    old, new = how.get("old", ""), how.get("new", "")
    if not old:
        raise specs.SpecError("There is nothing there to change; edit the paragraph itself.")
    if how.get("everywhere"):
        return _rewrite(rows, lambda text, s: specs_language.accept_everywhere(text, old, new))
    node_id, row_id = how.get("node_id", ""), int(how.get("row_id") or 0)
    at = int(how["at"]) if str(how.get("at", "")).isdigit() else None
    for s in rows:
        if s["id"] != row_id:
            continue
        for n in s["nodes"]:
            if n["id"] == node_id:
                n["text"], count = specs_language.accept(n["text"], old, new, at)
                if count:
                    s["changed"] = count
                return count
    return 0


def accept_set(set_id: int, how: Mapping[str, str]) -> int:
    rows = set_whole(set_id)
    count = accept_language(rows, how)
    for s in rows:
        if s.get("changed"):
            save_set_section(set_id, s["id"], s["nodes"])
    return count


def accept_library(how: Mapping[str, str]) -> int:
    rows = library_whole()
    count = accept_language(rows, how)
    for s in rows:
        if s.get("changed"):
            master = section(s["id"])
            save_section(master["number"], master["title"], s["nodes"],
                         note=f"\"{how.get('old')}\" made \"{how.get('new')}\"", section_id=s["id"])
    return count


# Kinds of suggestion that can be taken all at once: each is one word or one
# quantity, where the suggestion is the whole answer. Grammar is read one by one.
BULK = ("english", "spelling", "units")


def _accept_found(rows: list[dict], found: list[dict], kind: str) -> int:
    from . import specs_language

    if kind not in BULK:
        raise specs.SpecError("Those are taken one at a time.")
    todo = [f for f in found if f["kind"] == kind and f["old"] and f["new"]
            and "disagree" not in f["message"]]
    count = 0
    for s in rows:
        for n in s["nodes"]:
            mine = sorted((f for f in todo if f["row_id"] == s["id"] and f["node_id"] == n["id"]),
                          key=lambda f: -f["at"])
            for f in mine:
                n["text"], k = specs_language.accept(n["text"], f["old"], f["new"], f["at"])
                if k:
                    s["changed"] = s.get("changed", 0) + k
                    count += k
    return count


def accept_all_set(set_id: int, kind: str) -> int:
    rows = set_whole(set_id)
    count = _accept_found(rows, language_set(set_id), kind)
    for s in rows:
        if s.get("changed"):
            save_set_section(set_id, s["id"], s["nodes"])
    return count


def accept_all_library(kind: str) -> int:
    rows = library_whole()
    count = _accept_found(rows, language_library(), kind)
    for s in rows:
        if s.get("changed"):
            master = section(s["id"])
            save_section(master["number"], master["title"], s["nodes"],
                         note=f"All {kind} suggestions accepted", section_id=s["id"])
    return count
