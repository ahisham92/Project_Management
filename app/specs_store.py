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


def library_whole() -> list[dict]:
    return _whole(query("SELECT id, number, title, body FROM spec_sections ORDER BY number"))


def reader(sections: list[dict], chosen: Mapping[str, str],
           standards: bool = True) -> specs_check.Reader:
    """What turns a section's text as kept into the text as issued, for one
    set of sections: the references written out, the standards on the basis."""
    return specs_check.Reader(sections, chosen, standards_table() if standards else None)


def check_set(set_id: int) -> dict:
    row = spec_set(set_id)
    return specs_check.check(set_whole(set_id), chosen_for(row), values_for(row), options(),
                             standards_table())


def check_library() -> dict:
    everything = {o["key"]: "|".join(o["choice_list"]) for o in options()}
    everything["standards"] = ""
    report = specs_check.check(library_whole(), everything,
                               {v["key"]: v["default_value"] or v["key"] for v in variables()},
                               options(), standards_table())
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


def fix_library(action: str, **how: str) -> int:
    """The same, on the masters: each section changed is saved as a new version."""
    rows = library_whole()
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
        "sections": [{"number": s["number"], "title": s["title"], "body": specs.loads(s["body"])}
                     for s in (dict(r) for r in query("SELECT * FROM spec_sections ORDER BY number"))],
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
    return out.getvalue()


def unpack(data: bytes) -> dict:
    """A library file read in. Sections it has become new versions of the
    ones here (or new sections); questions, words and standards it has are
    added or updated; nothing here that it lacks is removed."""
    import io
    import zipfile

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        loaded = json.loads(z.read("library.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise specs.SpecError("That is not a Specs Writer library file.") from exc
    if not str(loaded.get("format", "")).startswith("specs-writer-library/"):
        raise specs.SpecError("That is not a Specs Writer library file.")
    counted = {"sections": 0, "options": 0, "variables": 0, "standards": 0}
    for s in loaded.get("sections", []):
        nodes = [specs.node(n["level"], n["text"], n.get("when", ""), n.get("id"))
                 for n in s.get("body", []) if n.get("level") in specs.KINDS]
        have = section_by_number(s["number"])
        if have:
            nodes = specs.align(specs.loads(have["body"]), nodes) if not _same_ids(have, nodes) else nodes
        save_section(s["number"], s.get("title", ""), nodes, note="Read from a library file",
                     section_id=have["id"] if have else None)
        counted["sections"] += 1
    conn = get_db()
    with conn:
        for o in loaded.get("options", []):
            last = conn.execute("SELECT COALESCE(MAX(position), 0) AS n FROM spec_options").fetchone()["n"]
            conn.execute(
                "INSERT INTO spec_options (key, label, choices, default_value, grp, kind, position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET label = excluded.label, "
                "choices = excluded.choices, default_value = excluded.default_value, "
                "grp = excluded.grp, kind = excluded.kind",
                (_clean_key(o["key"]), o.get("label", ""), o.get("choices", ""),
                 o.get("default_value", ""), o.get("grp", ""), o.get("kind", "one"), last + 1))
            counted["options"] += 1
        for v in loaded.get("variables", []):
            last = conn.execute("SELECT COALESCE(MAX(position), 0) AS n FROM spec_variables").fetchone()["n"]
            conn.execute(
                "INSERT INTO spec_variables (key, label, default_value, position) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET label = excluded.label, "
                "default_value = excluded.default_value",
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
    return counted


def _same_ids(have: Mapping[str, Any], nodes: list[dict]) -> bool:
    """Whether a file's section already carries this library's paragraph ids
    (it came from here), in which case they are kept as they are."""
    mine = {n["id"] for n in specs.loads(have["body"])}
    return bool(mine & {n["id"] for n in nodes})


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
