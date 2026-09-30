"""The specification writer's records: the library, the options, the sets.

`specs` knows what a section is; this knows where one is kept. The master
sections are the office's library, edited by the administrator and versioned
on every save. A set is one project's specification: its header, its choices,
and its own copy of each section it issues.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from flask import g

from . import specs
from .db import execute, get_db, insert, query, query_one


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
            conn.execute(
                "INSERT OR REPLACE INTO spec_options (key, label, choices, default_value, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, row.get("label", "").strip() or key, choices,
                 row.get("default_value", "").strip(), position))


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
    return {o["key"]: stored.get(o["key"]) or o["default_value"] for o in options()}


def values_for(spec_set: Mapping[str, Any] | None) -> dict[str, str]:
    stored = json.loads(spec_set["variables"] or "{}") if spec_set else {}
    values = {v["key"]: stored.get(v["key"]) or v["default_value"] for v in variables()}
    if spec_set:
        values.setdefault("project", spec_set["name"])
        values.setdefault("client", spec_set["client"])
    return values


# --- the house template -------------------------------------------------------

def template_bytes() -> bytes | None:
    row = query_one("SELECT content FROM spec_template WHERE id = 1")
    return bytes(row["content"]) if row else None


def template_row() -> dict | None:
    return _row(query_one("SELECT id, filename, user_name, added_at, length(content) AS size "
                          "FROM spec_template WHERE id = 1"))


def save_template(filename: str, data: bytes) -> None:
    specs.template_info(data)                          # refuses one that will not do
    execute("INSERT OR REPLACE INTO spec_template (id, filename, content, user_name, added_at) "
            "VALUES (1, ?, ?, ?, datetime('now'))", (filename, data, _who()))


def drop_template() -> None:
    execute("DELETE FROM spec_template WHERE id = 1")


# --- the library ----------------------------------------------------------------

def library() -> list[dict]:
    rows = query("SELECT id, number, title, version, updated_by, updated_at, note, body "
                 "FROM spec_sections ORDER BY number")
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


def section_by_number(number: str) -> dict | None:
    return _row(query_one("SELECT * FROM spec_sections WHERE number = ? COLLATE NOCASE",
                          (number.strip(),)))


def versions(section_id: int) -> list[dict]:
    return [dict(r) for r in query(
        "SELECT version, title, note, saved_by, saved_at FROM spec_section_versions "
        "WHERE section_id = ? ORDER BY version DESC", (section_id,))]


def version_body(section_id: int, version: int) -> list[dict] | None:
    row = query_one("SELECT body FROM spec_section_versions WHERE section_id = ? AND version = ?",
                    (section_id, version))
    return specs.loads(row["body"]) if row else None


def save_section(number: str, title: str, nodes: list[dict], note: str = "",
                 section_id: int | None = None) -> int:
    """A master section, new or saved over, kept as a new version either way.

    Saving text that is the same as the current version is not a new version:
    a history of identical saves says nothing.
    """
    number, title = number.strip(), title.strip().upper()
    if not number:
        raise specs.SpecError("A section needs its number, as in 032000.")
    clash = section_by_number(number)
    if clash and clash["id"] != section_id:
        raise specs.SpecError(f"Section {number} is already in the library.")
    conn = get_db()
    body = specs.dumps(nodes)
    with conn:
        if section_id is None:
            cursor = conn.execute(
                "INSERT INTO spec_sections (number, title, body, version, note, updated_by) "
                "VALUES (?, ?, ?, 1, ?, ?)", (number, title, body, note, _who()))
            section_id = int(cursor.lastrowid)
            version = 1
        else:
            now = conn.execute("SELECT * FROM spec_sections WHERE id = ?", (section_id,)).fetchone()
            if now is None:
                raise specs.SpecError("That section is not in the library any more.")
            if now["body"] == body and now["title"] == title and now["number"] == number:
                return section_id
            version = int(now["version"]) + 1
            conn.execute(
                "UPDATE spec_sections SET number = ?, title = ?, body = ?, version = ?, note = ?, "
                "updated_by = ?, updated_at = datetime('now') WHERE id = ?",
                (number, title, body, version, note, _who(), section_id))
        conn.execute(
            "INSERT INTO spec_section_versions (section_id, version, title, body, note, saved_by) "
            "VALUES (?, ?, ?, ?, ?, ?)", (section_id, version, title, body, note, _who()))
    return section_id


def import_to_library(filename: str, data: bytes) -> tuple[int, str]:
    """A Word section into the library: a new section, or a new version of one.

    Paragraphs that read the same as the master's keep their ids, so a project
    copy taken earlier still compares cleanly against it.
    """
    read = specs.read_docx(data)
    number = read["number"] or specs.number_from_filename(filename)
    if not number:
        raise specs.SpecError(f"{filename}: no section number in it or in its name.")
    existing = section_by_number(number)
    if existing:
        nodes = specs.align(specs.loads(existing["body"]), read["nodes"])
        save_section(number, read["title"] or existing["title"], nodes,
                     note=f"Read from {filename}", section_id=existing["id"])
        return existing["id"], "updated"
    return save_section(number, read["title"], read["nodes"], note=f"Read from {filename}"), "added"


def delete_section(section_id: int) -> None:
    execute("DELETE FROM spec_sections WHERE id = ?", (section_id,))


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
    set_id = insert(
        f"INSERT INTO spec_sets ({', '.join(SET_FIELDS)}, options, variables, created_by) "
        f"VALUES ({', '.join('?' * len(SET_FIELDS))}, ?, ?, ?)",
        [values[k] for k in SET_FIELDS] + [source["options"] if source else "{}",
                                           source["variables"] if source else "{}",
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


def delete_set(set_id: int) -> None:
    execute("DELETE FROM spec_sets WHERE id = ?", (set_id,))


def _touch(set_id: int) -> None:
    get_db().execute("UPDATE spec_sets SET updated_at = datetime('now') WHERE id = ?", (set_id,))


def set_sections(set_id: int) -> list[dict]:
    """A set's sections, each with how it stands against its master."""
    out = []
    for row in query("SELECT x.*, s.version AS master_version FROM spec_set_sections x "
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
    return added


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
    execute("DELETE FROM spec_set_sections WHERE id = ? AND set_id = ?", (row_id, set_id))
    _touch(set_id)


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
    master = section_by_number(number)
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
    master = section_by_number(row["number"])
    section_id = save_section(row["number"], row["title"], nodes,
                              note="Taken from a project specification",
                              section_id=master["id"] if master else None)
    fresh = section(section_id)
    execute("UPDATE spec_set_sections SET section_id = ?, base_version = ? WHERE id = ?",
            (section_id, fresh["version"], row_id))
    return section_id
