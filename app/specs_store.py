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
        # The answers to the master's questions fill its text the same way.
        from . import specs_questions
        for key, words in specs_questions.values(spec_set).items():
            values.setdefault(key, words)
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
              "revision", "issue_date", "file_pattern", "package")


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
    # A copy is a package of its own: it does not take the other's package name.
    values["package"] = (fields.get("package") or "").strip()
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
    if fields.get("need_signoff"):
        # Held for sign-off and closed comments, as the new-project form offers.
        execute("UPDATE spec_sets SET need_signoff = 1 WHERE id = ?", (set_id,))
    if source:
        conn = get_db()
        with conn:
            conn.execute(
                "INSERT INTO spec_set_sections (set_id, section_id, base_version, number, title, "
                "doc_code, body, updated_by) SELECT ?, section_id, base_version, number, title, "
                "doc_code, body, ? FROM spec_set_sections WHERE set_id = ?",
                (set_id, _who(), copy_from))
            conn.execute("UPDATE spec_sets SET answers = ?, covered = ?, city = ?, country = ?, "
                         "lat = ?, lng = ? WHERE id = ?",
                         (source.get("answers") or "{}", source.get("covered") or "{}",
                          source.get("city") or "", source.get("country") or "",
                          source.get("lat"), source.get("lng"), set_id))
    if (fields.get("city") or "").strip() or (fields.get("country") or "").strip():
        set_place(set_id, fields.get("city") or "", fields.get("country") or "")
    return set_id


def place_of(row: Mapping[str, Any] | None) -> tuple[str, str]:
    """A project's city and country: its own fields, or for a project started
    before they were asked, read from the one-line location it was given."""
    from . import specs_places, specs_questions

    if not row:
        return "", ""
    city, country = (row.get("city") or "").strip(), (row.get("country") or "").strip()
    if city or country:
        return city, country
    return specs_places.split_location(specs_questions.answers_of(row).get("proj_location", ""))


def set_place(set_id: int, city: str, country: str) -> None:
    """The project's city and country, its point on the map, and the one-line
    location the sections are written with."""
    from . import specs_places, specs_questions

    city, country = " ".join((city or "").split()), " ".join((country or "").split())
    found = specs_places.locate(city, country)
    execute("UPDATE spec_sets SET city = ?, country = ?, lat = ?, lng = ? WHERE id = ?",
            (city, country, found[0] if found else None, found[1] if found else None, set_id))
    line = specs_places.join_location(city, country)
    specs_questions.save_answers(set_id, {"proj_location": line or None}, {})


def set_point(set_id: int, lat: float, lng: float) -> None:
    """A point the browser found for a city the site's own list does not have."""
    execute("UPDATE spec_sets SET lat = ?, lng = ? WHERE id = ?", (lat, lng, set_id))


def covered_of(row: Mapping[str, Any] | None) -> dict[str, dict]:
    """How the engineer settled each answer the library has nothing written for."""
    try:
        out = json.loads((row or {}).get("covered") or "{}")
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


COVER_HOW = ("section", "own", "not_needed")


def set_cover(set_id: int, key: str, value: str, how: str | None, section: str = "",
              note: str = "") -> None:
    """One uncovered answer settled (``how``: covered by a section already in,
    by a section of the project's own, or not needed), or opened again (None)."""
    row = spec_set(set_id)
    if row is None:
        return
    covered = covered_of(row)
    mark = f"{key}={specs._norm(value)}"
    if how in COVER_HOW:
        covered[mark] = {"how": how, "section": section.strip(), "note": note.strip(),
                         "value": value.strip(), "by": _who()}
    else:
        covered.pop(mark, None)
    execute("UPDATE spec_sets SET covered = ? WHERE id = ?",
            (json.dumps(covered, ensure_ascii=False), set_id))


def uncovered_for(row: Mapping[str, Any], chosen: Mapping[str, str]) -> dict[str, list[dict]]:
    """The answers the project's library has nothing written for, split into
    the ones still to settle and the ones the engineer settled, each with its
    question's key so it can be settled."""
    covered = covered_of(row)
    labels = {o["label"]: o["key"] for o in options()}
    out: dict[str, list[dict]] = {"open": [], "settled": []}
    for label, value, elsewhere in uncovered(chosen, row["family"]):
        key = labels.get(label, "")
        one = {"key": key, "label": label, "value": value, "elsewhere": elsewhere,
               "mark": f"{key}={specs._norm(value)}"}
        if one["mark"] in covered:
            one["settled"] = covered[one["mark"]]
            out["settled"].append(one)
        else:
            out["open"].append(one)
    return out


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
    if "signoff_shown" in fields:
        execute("UPDATE spec_sets SET need_signoff = ? WHERE id = ?",
                (1 if fields.get("need_signoff") else 0, set_id))
    if fields.get("family"):
        execute("UPDATE spec_sets SET family = ? WHERE id = ?", (clean_family(fields["family"]), set_id))


def set_revision(set_id: int, revision: str, issue_date: str) -> None:
    """The revision and date the project was last issued as, on every page of it."""
    execute("UPDATE spec_sets SET revision = ?, issue_date = ?, updated_at = datetime('now') "
            "WHERE id = ?", (revision, issue_date, set_id))


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


def remove_set_section(set_id: int, row_id: int) -> list[str]:
    """A section taken out of a project. When adding it by hand set answers,
    those answers go back to what they were (it was added by mistake); what
    changed back, in words."""
    row = set_section(set_id, row_id)
    execute("DELETE FROM spec_set_sections WHERE id = ? AND set_id = ?", (row_id, set_id))
    _touch(set_id)
    master = section(row["section_id"]) if row and row["section_id"] else None
    undone = _unset_answers(set_id, master["id"]) if master else []
    if master and fits(master["applies"], chosen_for(spec_set(set_id))):
        _decline(set_id, add=[master["id"]])
    return undone


def _set_by(row: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(row.get("set_by") or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def answer_for(set_id: int, section_id: int) -> list[str]:
    """A section added by hand is taken as the answer that calls for it: the
    project's answers are set so its condition holds, as if the engineer had
    chosen them, and what they were before is kept so that taking the section
    out again puts them back. What was set, in words."""
    row = spec_set(set_id)
    master = section(section_id)
    applies = (master or {}).get("applies") or ""
    if not master or applies in ("", ALWAYS):
        return []
    chosen = chosen_for(row)
    if specs.applies(applies, chosen):
        return []
    kinds = {o["key"]: o for o in options()}
    stored = json.loads(row["options"] or "{}")
    before: dict[str, str] = {}
    said = []
    for part in applies.split("&"):
        part = part.strip()
        negate = "!=" in part
        key, _, wanted = part.partition("!=" if negate else "=")
        key = key.strip()
        o = kinds.get(key)
        if o is None or specs.applies(part, {**chosen, **stored}):
            continue
        names = [w.strip() for w in wanted.split("|") if w.strip()]
        norm = {specs._norm(w) for w in names}
        if negate:
            pick = [c for c in o["choice_list"] if specs._norm(c) not in norm
                    and specs._norm(c) != "none"] or [c for c in o["choice_list"]
                                                     if specs._norm(c) not in norm]
        else:
            pick = [c for c in o["choice_list"] if specs._norm(c) in norm] or names
        if not pick:
            continue
        now = stored.get(key, chosen.get(key, "")) or ""
        before.setdefault(key, now)
        if o["kind"] == "many":
            have = [v for v in now.split("|") if v and specs._norm(v) != "none"]
            stored[key] = "|".join(have + [pick[0]])
        else:
            stored[key] = pick[0]
        said.append(f"{o['label']}: {pick[0]}")
    if not said:
        return []
    set_by = _set_by(row)
    set_by.setdefault(str(section_id), {}).update(
        {k: v for k, v in before.items() if k not in set_by.get(str(section_id), {})})
    execute("UPDATE spec_sets SET options = ?, set_by = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(stored, ensure_ascii=False), json.dumps(set_by, ensure_ascii=False), set_id))
    return said


def _unset_answers(set_id: int, section_id: int) -> list[str]:
    """The answers adding this section by hand set, put back as they were
    unless somebody has changed them since or another section still needs them."""
    row = spec_set(set_id)
    set_by = _set_by(row)
    before = set_by.pop(str(section_id), None)
    if not before:
        return []
    stored = json.loads(row["options"] or "{}")
    kinds = {o["key"]: o for o in options()}
    still = [s for s in (section(r["section_id"]) for r in query(
        "SELECT section_id FROM spec_set_sections WHERE set_id = ? AND section_id IS NOT NULL",
        (set_id,))) if s]
    said = []
    for key, was in before.items():
        trial = {**chosen_for(row), key: was}
        if any(fits(s["applies"], chosen_for(row)) and not fits(s["applies"], trial) for s in still):
            continue
        stored[key] = was
        o = kinds.get(key)
        said.append(f"{o['label'] if o else key}: {was or 'not answered'}")
    execute("UPDATE spec_sets SET options = ?, set_by = ?, updated_at = datetime('now') WHERE id = ?",
            (json.dumps(stored, ensure_ascii=False), json.dumps(set_by, ensure_ascii=False), set_id))
    return said


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


def blanks(set_id: int) -> list[dict]:
    """The [choices] and <Insert ...> places still open in a project's text."""
    from . import specs_blanks

    return specs_blanks.find(set_sections(set_id), chosen_for(spec_set(set_id)))


def fill_blanks(set_id: int, answers: Mapping[str, tuple[str, bool]]) -> int:
    """Answers written into the project's paragraphs, each in place of its
    blank: ``answers`` maps a blank's key to (the words, whether the same
    words go wherever that same blank appears). How many blanks were filled."""
    from . import specs_blanks

    found = blanks(set_id)
    by_key = {b["key"]: b for b in found}
    todo: dict[tuple[int, str], dict[tuple[str, int], str]] = {}
    # A blank's own answer comes before one given for "wherever it appears".
    for key, (words, everywhere) in sorted(answers.items(), key=lambda kv: kv[1][1]):
        b = by_key.get(key)
        if b is None:
            continue
        targets = [x for x in found if x["run"] == b["run"]] if everywhere else [b]
        for t in targets:
            todo.setdefault((t["row_id"], t["node_id"]), {}).setdefault((t["run"], t["nth"]), words)
    filled = 0
    for (row_id, node_id), fills in todo.items():
        row = set_section(set_id, row_id)
        if row is None:
            continue
        nodes = specs.loads(row["body"])
        for n in nodes:
            if n["id"] != node_id:
                continue
            # Later copies of a run first, so the earlier ones keep their places.
            for (run, nth), words in sorted(fills.items(), key=lambda kv: -kv[0][1]):
                was = n["text"]
                n["text"] = specs_blanks.fill(n["text"], run, nth, words)
                filled += n["text"] != was
        save_set_section(set_id, row_id, nodes)
    return filled


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
    settled = {r["key"]: _settled_row(r) for r in query(
        "SELECT key, state, message, settled_by, settled_at, detail FROM spec_check_settled "
        "WHERE set_id = ?", (set_id,))}
    report["open"] = {}
    seen = set()
    for group in GROUPS:
        for item in report[group]:
            item["key"] = _item_key(group, item)
            item["settled"] = settled.get(item["key"])
            seen.add(item["key"])
        report["open"][group] = sum(1 for i in report[group] if not i["settled"])
    # What was amended or removed and is no longer found: kept, to show what was done.
    report["done"] = {group: [] for group in GROUPS}
    for key, row in settled.items():
        detail = row["detail"]
        if key in seen or row["how"] == "kept" or detail.get("group") not in report["done"]:
            continue
        report["done"][detail["group"]].append({
            **{k: detail.get(k) or "" for k in ("section", "title", "part", "article", "path",
                                                "node_id")},
            "row_id": detail.get("row_id"), "message": detail.get("message") or row["message"],
            "severity": "info", "text": "", "words": "", "fix": None, "key": key,
            "settled": row, "done": True})
    return report


# What each stored state means now. An item accepted or rejected before items were
# kept, amended or removed was settled with its text as it stood: it was kept.
SETTLED_AS = {"kept": "kept", "amended": "amended", "removed": "removed",
              "accepted": "kept", "rejected": "kept"}


def _settled_row(r: Mapping[str, Any]) -> dict:
    row = dict(r)
    row["how"] = SETTLED_AS.get(row["state"], "kept")
    try:
        row["detail"] = json.loads(row.get("detail") or "{}") or {}
    except ValueError:
        row["detail"] = {}
    return row


def _item_key(group: str, item: Mapping[str, Any]) -> str:
    """What names a check item from one check to the next: what it says about
    which paragraph. Change the paragraph's words and it is a new item."""
    import hashlib

    where = item.get("node_id") or item.get("path") or ""
    basis = "|".join((group, item.get("section") or "", where, item.get("message") or "",
                      item.get("text") or ""))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def settle(set_id: int, key: str, state: str, message: str = "",
           detail: Mapping[str, Any] | None = None) -> None:
    """An item kept, amended or removed; a blank state opens it again. (Accepted
    and rejected, from before, are taken as kept.)"""
    if state not in SETTLED_AS and state != "":
        raise specs.SpecError("An item is kept, amended or removed.")
    with get_db() as conn:
        conn.execute("DELETE FROM spec_check_settled WHERE set_id = ? AND key = ?", (set_id, key))
        if state:
            conn.execute("INSERT INTO spec_check_settled (set_id, key, state, message, settled_by, "
                         "detail) VALUES (?, ?, ?, ?, ?, ?)",
                         (set_id, key, state, message[:300], _who(),
                          json.dumps(detail or {}, ensure_ascii=False) if detail else ""))


def open_items(set_id: int, report: Mapping[str, Any] | None = None) -> dict:
    """What still waits for the engineer: check items to keep, amend or remove,
    and language suggestions to accept or reject (each change counted once,
    however many places it is in)."""
    report = report if report is not None else check_set(set_id)
    # Paragraphs said twice are advice on keeping the text tidy; they do not hold an issue.
    checks = sum(n for group, n in report["open"].items() if group not in ADVICE)
    changes = {(f["kind"], f["old"].lower(), f["new"].lower(), f["message"] if not f["old"] else "")
               for f in language_set(set_id)}
    return {"checks": checks, "language": len(changes), "total": checks + len(changes)}


# --- keeping, amending or removing what a check item is about ---------------------------

WHERE_KEYS = ("section", "title", "part", "article", "path")
# A heading or a table is amended, never cut down a sentence at a time.
WHOLE_ONLY = ("PRT", "ART", specs.TABLE)


def _targets(item: Mapping[str, Any]) -> list[dict]:
    """The paragraphs an item is about: its own, or each of its places."""
    if item.get("done"):
        return list((item["settled"]["detail"] or {}).get("places") or [])
    places = item.get("places") or [item]
    return [p for p in places if p.get("row_id") and p.get("node_id")]


def _place(p: Mapping[str, Any], s: Mapping[str, Any], n: Mapping[str, Any]) -> dict:
    return {**{k: p.get(k) or "" for k in WHERE_KEYS}, "row_id": s["id"], "node_id": n["id"]}


def label(p: Mapping[str, Any]) -> str:
    """Where a paragraph is, as a flash says it: "1.2.B.4 of 032000"."""
    return f"{p['path']} of {p['section']}" if p.get("path") else (p.get("section") or "the section")


def labels(places: list[Mapping[str, Any]]) -> str:
    names = list(dict.fromkeys(label(p) for p in places))
    if len(names) > 4:
        return ", ".join(names[:3]) + f" and {len(names) - 3} more"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _node(s: Mapping[str, Any], node_id: str) -> dict | None:
    return next((n for n in s["nodes"] if n["id"] == node_id), None)


def _under(nodes: list[Mapping[str, Any]], node_id: str) -> list[str]:
    """The paragraphs under one, which go with it when it goes (an editor's note
    just before the next paragraph is that paragraph's, so it stays)."""
    out, depth = [], None
    for x in nodes:
        if depth is None:
            if x["id"] == node_id:
                depth = specs.DEPTH.get(x["level"], len(specs.LEVELS))
            continue
        d = specs.DEPTH.get(x["level"])
        if d is not None and d <= depth:
            break
        out.append(x)
    while out and out[-1]["level"] == specs.NOTE:
        out.pop()
    return [x["id"] for x in out]


def _removal(item: Mapping[str, Any], p: Mapping[str, Any], s: Mapping[str, Any],
             n: Mapping[str, Any], where: Mapping[str, dict]) -> dict | None:
    """What Remove would take out of one paragraph: the sentence the item is
    about, or the whole paragraph when that is all there is."""
    if n["level"] in WHOLE_ONLY:
        return None
    words = p.get("words") or ""
    at = specs_check.locate(n["text"], item["message"], words, s["number"], where)
    if at is None and words:
        return None
    left, gone = specs_check.without_sentence(n["text"], at) if at is not None else ("", n["text"])
    return {"sentence": gone, "left": left, "whole": not left,
            "under": len(_under(s["nodes"], n["id"])) if not left else 0}


def check_actions(set_id: int, report: Mapping[str, Any]) -> None:
    """What the check page can do with each item, as ``item["act"]``: each of its
    paragraphs as kept, the amendment proposed for it, and what Remove would
    take out (``None`` where Remove is not offered)."""
    rows = set_whole(set_id)
    where = specs_check.index(rows, chosen_for(spec_set(set_id)))
    found = {(s["id"], n["id"]): (s, n) for s in rows for n in s["nodes"]}
    for group in GROUPS:
        for item in report[group] + report.get("done", {}).get(group, []):
            places = []
            for p in _targets(item):
                hit = found.get((p.get("row_id"), p.get("node_id")))
                if hit is None:
                    continue
                s, n = hit
                proposed = n["text"] if item.get("done") else specs_check.propose(
                    n["text"], item["message"], item.get("fix"), s["number"], where)
                places.append({**_place(p, s, n), "current": n["text"], "proposed": proposed,
                               "table": n["level"] == specs.TABLE,
                               "remove": None if item.get("done") else _removal(item, p, s, n, where)})
            several = len(places) > 1
            can_remove = bool(places) and all(p["remove"] for p in places) and (
                not several or bool(specs_check.missing_number(item["message"])))
            item["act"] = {"places": places, "can_remove": can_remove,
                           "missing": bool(specs_check.missing_number(item["message"])),
                           "proposes": any(p["proposed"] != p["current"] for p in places),
                           "confirm": _confirm(item, places) if can_remove else ""}


def _confirm(item: Mapping[str, Any], places: list[dict]) -> str:
    """What the browser asks before Remove: what goes."""
    if len(places) == 1:
        p, r = places[0], places[0]["remove"]
        if r["whole"]:
            ask = f"Remove paragraph {label(p)}?\n\n“{r['sentence']}”\n\n"
            ask += "It is the only sentence in the paragraph, so the whole paragraph goes"
            ask += (f", with the {r['under']} paragraph{'s' if r['under'] != 1 else ''} under it."
                    if r["under"] else ".")
            return ask
        return f"Remove this sentence from {label(p)}?\n\n“{r['sentence']}”"
    number = specs_check.missing_number(item["message"])
    whole = [p for p in places if p["remove"]["whole"]]
    ask = f"Remove the sentence that refers to Section {number} in each of the {len(places)} places?\n\n"
    ask += "\n".join(f"{label(p)}: “{specs_check._brief(p['remove']['sentence'], 90)}”"
                     for p in places[:8])
    if whole:
        ask += (f"\n\nIn {len(whole)} of them it is the only sentence, so the whole paragraph goes"
                f" ({labels(whole)}).")
    return ask


def _find(report: Mapping[str, Any], key: str) -> tuple[str, dict | None]:
    for group in GROUPS:
        for item in report[group] + report.get("done", {}).get(group, []):
            if item["key"] == key:
                return group, item
    return "", None


def _tidy(text: str, table: bool) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return text if table else re.sub(r"\s+", " ", text)


def amend_item(set_id: int, key: str, edits: Iterable[tuple[int, str, str]]) -> dict:
    """An item's paragraphs given the text the engineer settled on, and the item
    settled as amended. ``edits`` are ``(row_id, node_id, text)``.

    When the check still finds the same thing in the same paragraphs, the
    amendment is what was meant, so that is settled as amended too."""
    report = check_set(set_id)
    group, item = _find(report, key)
    if item is None:
        raise specs.SpecError("That item is no longer on the check: the text it was about has "
                              "changed since. Here is the check as it stands.")
    targets = {(p.get("row_id"), p.get("node_id")): p for p in _targets(item)}
    earlier = {(p.get("row_id"), p.get("node_id")): p.get("before")
               for p in ((item.get("settled") or {}).get("detail") or {}).get("places") or []}
    rows = {s["id"]: s for s in set_whole(set_id)}
    places = []
    for row_id, node_id, text in edits:
        s = rows.get(row_id)
        n = _node(s, node_id) if s else None
        if n is None or (row_id, node_id) not in targets:
            raise specs.SpecError("That paragraph is not in the section any more, or is not one "
                                  "this item is about.")
        text = _tidy(text, n["level"] == specs.TABLE)
        if not text:
            raise specs.SpecError("An amendment cannot be empty. To take the words out, use Remove.")
        places.append({**_place(targets[(row_id, node_id)], s, n),
                       "before": earlier.get((row_id, node_id)) or n["text"], "after": text})
        if text != n["text"]:
            n["text"] = text
            s["changed"] = True
    if not places:
        raise specs.SpecError("Nothing to amend.")
    for s in rows.values():
        if s.get("changed"):
            save_set_section(set_id, s["id"], s["nodes"])
    detail = {"group": group, "message": item["message"],
              **{k: item.get(k) or "" for k in WHERE_KEYS + ("node_id",)},
              "row_id": item.get("row_id"), "places": places}
    mine = {(p["row_id"], p["node_id"]) for p in places}
    after = check_set(set_id)
    still = [i for i in after[group] if i["message"] == item["message"] and not i["settled"]
             and _targets(i) and {(t["row_id"], t["node_id"]) for t in _targets(i)} <= mine]
    settle(set_id, key, "")
    for i in still:
        settle(set_id, i["key"], "amended", i["message"], detail)
    if not still:
        settle(set_id, key, "amended", item["message"], detail)
    # The key the amendment is now kept under, for the page to show it.
    return {**detail, "key": still[0]["key"] if still else key}


def remove_items(set_id: int, keys: Iterable[str]) -> list[dict]:
    """The sentence each item is about taken out of its paragraphs (the whole
    paragraph, and the ones under it, when it was the only sentence), and the
    item settled as removed. What was done comes back, one entry per item."""
    keys = list(keys)
    report = check_set(set_id)
    rows = set_whole(set_id)
    where = specs_check.index(rows, chosen_for(spec_set(set_id)))
    by_id = {s["id"]: s for s in rows}
    done = []
    for key in keys:
        group, item = _find(report, key)
        if item is None or item.get("done"):
            continue
        targets = _targets(item)
        if len(targets) > 1 and not specs_check.missing_number(item["message"]):
            raise specs.SpecError("Only a reference to a missing section is removed in every place "
                                  "at once. Amend the others one by one.")
        places = []
        for p in targets:
            s = by_id.get(p.get("row_id"))
            n = _node(s, p.get("node_id")) if s else None
            if n is None:
                continue
            r = _removal(item, p, s, n, where)
            if r is None:
                continue
            place = {**_place(p, s, n), "before": n["text"], "after": r["left"],
                     "removed": r["sentence"], "whole": r["whole"], "under": 0}
            if r["left"]:
                n["text"] = r["left"]
            else:
                gone = {n["id"], *_under(s["nodes"], n["id"])}
                place["under"] = len(gone) - 1
                s["nodes"] = [x for x in s["nodes"] if x["id"] not in gone]
            s["changed"] = True
            places.append(place)
        if not places:
            if len(keys) == 1:
                raise specs.SpecError("The words this item is about were not found in the paragraph "
                                      "as it stands. Amend it instead.")
            continue
        detail = {"group": group, "message": item["message"],
                  **{k: item.get(k) or "" for k in WHERE_KEYS + ("node_id",)},
                  "row_id": item.get("row_id"), "places": places}
        done.append({"key": key, "group": group, "item": item, "detail": detail})
    for s in rows:
        if s.get("changed"):
            save_set_section(set_id, s["id"], s["nodes"])
    for one in done:
        settle(set_id, one["key"], "removed", one["item"]["message"], one["detail"])
    return done


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
    settled = covered_of(row)
    labels = {o["label"]: o["key"] for o in options()}
    for label, value, elsewhere in uncovered(chosen, row["family"]):
        if f"{labels.get(label, '')}={specs._norm(value)}" in settled:
            continue
        report["setup"].append({
            "section": "", "row_id": None, "path": "", "severity": "warning", "text": "",
            "fix": None, "message": f"{label}: {value}. Nothing in the {row['family']} library is "
                                    "written for this answer, so no section describes it yet. "
                                    "On the project page's Sections step, say which section covers "
                                    "it, write one of the project's own, or mark it not needed" + (f" ({', '.join(elsewhere)} has one to "
                                                          "borrow)" if elsewhere else "")})
    # The master's questions not answered yet leave its [choices] in the text.
    from . import specs_questions
    slug = getattr(specs_seed, "element_slug", None)
    elements = [slug(e) for e in (chosen.get("elements") or "").split("|") if e.strip()] if slug else []
    for g in specs_questions.grouped(specs_questions.asked(set_sections(set_id), chosen, row, elements)):
        if g["open"]:
            report["setup"].append({
                "section": "", "row_id": None, "path": "", "severity": "warning", "text": "",
                "fix": None, "message": f"Details: questions in {g['name']} are not all answered yet, "
                                        "so the master's choices are still in the text there "
                                        f"({', '.join(q['label'] for q in g['questions'] if not q['answered'])})"})
    report["counts"] = {k: len(v) for k, v in report.items() if isinstance(v, list)}
    return report


def _lower(label: str) -> str:
    """A question's label inside a sentence: lower case, bar its acronyms."""
    return " ".join(w if (w.isupper() and len(w) > 1) else w.lower() for w in label.split())


def _either(values: list[str]) -> str:
    return values[0] if len(values) == 1 else ", ".join(values[:-1]) + " or " + values[-1]


def plain_condition(when: str, family: str = "", labels: Mapping[str, dict] | None = None) -> str:
    """Why a section or paragraph is in, in words the engineer reads rather
    than the condition it is written with: ``cast_in_place=Yes`` reads "You
    said the project has cast-in-place concrete"."""
    when = (when or "").strip()
    if not when:
        return "Added by hand"
    if when == ALWAYS:
        return f"Every {family} project has it".replace("  ", " ")
    labels = labels if labels is not None else {o["key"]: o for o in options()}
    said = []
    for part in when.split("&"):
        part = part.strip()
        if "=" not in part:
            continue
        negate = "!=" in part
        key, _, wanted = part.partition("!=" if negate else "=")
        key = key.strip()
        values = [w.strip() for w in wanted.split("|") if w.strip()]
        o = labels.get(key) or {}
        label = o.get("label") or key.replace("_", " ").capitalize()
        yes_no = {specs._norm(c) for c in (o.get("choice_list") or [])} == {"yes", "no"} or \
            {specs._norm(v) for v in values} <= {"yes", "no"}
        if key == "elements":
            things = _either([_lower(v) for v in values])
            said.append(f"the project has no {things}" if negate else f"the project has {things}")
        elif yes_no and len(values) == 1:
            has = (specs._norm(values[0]) == "yes") != negate
            said.append(f"the project has {'' if has else 'no '}{_lower(label)}")
        elif negate:
            said.append(f"{_lower(label)} is not {_either(values)}")
        else:
            said.append(f"you chose {_either(values)} for {_lower(label)}")
    if not said:
        return when
    text = " and ".join([said[0]] + [p.replace("the project has", "it has", 1) for p in said[1:]])
    return "You said " + text if text.startswith("the project") else text[0].upper() + text[1:]


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
        "questions": _questions_packed(),
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
        # The screenshots of the codes each question carries.
        from . import specs_questions
        shots = []
        for i in specs_questions.images():
            name = f"question-images/{i['id']}.{i['mime'].split('/')[-1]}"
            z.writestr(name, specs_questions.image(i["id"])["content"])
            shots.append({**{k: i[k] for k in ("key", "code", "clause", "caption")}, "file": name})
        if shots:
            z.writestr("question-images.json", json.dumps(shots, ensure_ascii=False, indent=1))
    return out.getvalue()


def _questions_packed() -> list[dict]:
    from . import specs_questions
    return specs_questions.packed()


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
    z, loaded = _library_file(data)
    counted = _new_count()
    in_file: dict[str, set[str]] = {}
    for s in loaded.get("sections", []):
        _load_section(s, loaded, mode, counted, in_file)
    _load_the_rest(z, loaded, mode, counted, in_file)
    return counted


def _library_file(data: bytes):
    """The file's zip and its library.json, or SpecError when it is not one."""
    import io
    import zipfile

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        loaded = json.loads(z.read("library.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise specs.SpecError("That is not a THEMIS library file.") from exc
    if not isinstance(loaded, dict) or not str(loaded.get("format", "")).startswith(
            "specs-writer-library/"):
        raise specs.SpecError("That is not a THEMIS library file.")
    return z, loaded


def _new_count() -> dict:
    return {"sections": 0, "options": 0, "variables": 0, "standards": 0,
            "added": 0, "updated": 0, "same": 0, "kept": 0, "removed": []}


def _load_section(s: Mapping[str, Any], loaded: Mapping[str, Any], mode: str, counted: dict,
                  in_file: dict[str, set[str]]) -> None:
    """One section of a library file read in (the part of a load that takes time)."""
    nodes = [specs.node(n["level"], n["text"], n.get("when", ""), n.get("id"))
             for n in s.get("body", []) if n.get("level") in specs.KINDS]
    family = clean_family(s.get("family") or loaded.get("family"))
    in_file.setdefault(family, set()).add(s["number"].strip().upper())
    have = section_by_number(s["number"], family)
    counted["sections"] += 1
    if have and mode == "add":
        counted["kept"] += 1
        return
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


def _load_the_rest(z, loaded: Mapping[str, Any], mode: str, counted: dict,
                   in_file: Mapping[str, set[str]]) -> None:
    """The end of a load, once every section is in: what ``replace`` takes out,
    then the questions, words, standards, wording and templates."""
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
    from . import specs_questions
    counted["questions"] = specs_questions.save_definitions(loaded.get("questions") or [], mode)
    if "question-images.json" in z.namelist():
        # The same screenshot already here is kept once.
        for i in json.loads(z.read("question-images.json").decode("utf-8")) or []:
            if isinstance(i, dict) and i.get("key") and i.get("file") in z.namelist():
                specs_questions.add_image(str(i["key"]), z.read(i["file"]), i.get("code", ""),
                                          i.get("clause", ""), i.get("caption", ""), _who())
    if "template.docx" in z.namelist() and template_bytes() is None:
        save_template("house-template.docx", z.read("template.docx"))
    # A kind's own template comes with its sections: it is how they look.
    for name in z.namelist():
        m = re.fullmatch(r"templates/([0-9A-Za-z]{1,8})\.docx", name)
        if m and not (mode == "add" and template_row(clean_family(m.group(1)))):
            save_template(f"{m.group(1)}-template.docx", z.read(name), family=clean_family(m.group(1)))


# A library file loaded a few sections at a time, so the page can show how far
# it has got. The file waits in the data directory as a pending load (<id>.zip,
# with <id>.json saying how far it is); each step reads the next few sections
# in, and the last one does the rest of what `unpack` does. A load left waiting
# longer than this (the page closed half way) is cleared by the next load.
LOAD_STALE = 10 * 60


def _loads_dir():
    from .db import data_dir

    folder = data_dir() / "specs-loads"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _load_paths(load_id: str):
    if not re.fullmatch(r"[0-9a-f]{16,64}", load_id or ""):
        raise specs.SpecError("That load is not waiting any more: load the file again.")
    folder = _loads_dir()
    return folder / f"{load_id}.zip", folder / f"{load_id}.json"


# The file of the load being stepped, as read, so each step need not read it
# again (in this process; another one reads it from the pending file).
_READ: dict[str, tuple] = {}


def drop_load(load_id: str) -> None:
    """A pending load's files removed (finished, failed, or given up)."""
    _READ.pop(load_id, None)
    try:
        paths = _load_paths(load_id)
    except specs.SpecError:
        return
    for path in paths:
        path.unlink(missing_ok=True)


def clear_stale_loads(older_than: float = LOAD_STALE) -> list[str]:
    """Pending loads nobody has stepped for a while, removed; their ids."""
    import time

    cutoff, gone = time.time() - older_than, set()
    for path in _loads_dir().iterdir():
        if path.suffix in (".zip", ".json", ".tmp"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    gone.add(path.stem)
            except OSError:
                pass
    return sorted(gone)


def begin_load(data: bytes, mode: str = "update", filename: str = "") -> dict:
    """A library file checked and put by as a pending load: its id and how
    many sections it has. Nothing in the library changes yet."""
    import secrets

    if mode not in LOAD_MODES:
        mode = "update"
    _z, loaded = _library_file(data)
    clear_stale_loads()
    load_id = secrets.token_hex(12)
    held, state = _load_paths(load_id)
    total = len(loaded.get("sections", []))
    held.write_bytes(data)
    _save_state(state, {"mode": mode, "filename": filename, "done": 0, "total": total,
                        "counted": _new_count(), "in_file": {}})
    return {"id": load_id, "total": total}


def _save_state(path, state: dict) -> None:
    import os

    part = path.with_suffix(".tmp")
    part.write_text(json.dumps(state), encoding="utf-8")
    os.replace(part, path)


def step_load(load_id: str, seconds: float = 0.5, most: int | None = None) -> dict:
    """The next few sections of a pending load read in: as many as fit in
    about ``seconds`` (at least one), or ``most``. The step that reads the
    last one also does the rest, as `unpack` does, and clears the load.

    Returns ``done`` and ``total`` sections, a ``message``, and ``finished``
    with the ``counted`` `unpack` would return. A load that fails is cleared
    and its error raised; the sections read in before it stay in, as they do
    with `unpack`.
    """
    import os
    import time

    held, state_path = _load_paths(load_id)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        read = _READ.get(load_id)
        data = None if read else held.read_bytes()
    except (OSError, ValueError) as exc:
        drop_load(load_id)
        raise specs.SpecError("That load is not waiting any more: load the file again.") from exc
    try:
        if not read:
            _READ.clear()
            read = _READ[load_id] = _library_file(data)
        z, loaded = read
        sections = loaded.get("sections", [])
        counted, mode = state["counted"], state["mode"]
        in_file = {k: set(v) for k, v in state["in_file"].items()}
        done, total = int(state["done"]), len(sections)
        start, n, last = time.monotonic(), 0, None
        while done < total and (most is None or n < most) and (
                n == 0 or time.monotonic() - start < seconds):
            last = sections[done]
            _load_section(last, loaded, mode, counted, in_file)
            done, n = done + 1, n + 1
        if done >= total:
            _load_the_rest(z, loaded, mode, counted, in_file)
            drop_load(load_id)
            return {"done": total, "total": total, "finished": True, "counted": counted,
                    "filename": state.get("filename", ""), "mode": mode,
                    "message": f"Read all {total} section{'s' if total != 1 else ''}, "
                               "the questions, words and standards."}
        state.update(done=done, counted=counted, in_file={k: sorted(v) for k, v in in_file.items()})
        _save_state(state_path, state)
        os.utime(held)
    except BaseException:
        drop_load(load_id)
        raise
    title = f"{last['number']} {last.get('title', '')}".strip() if last else ""
    return {"done": done, "total": total, "finished": False, "counted": counted,
            "filename": state.get("filename", ""), "mode": mode,
            "message": f"Read {done} of {total} sections" + (f": {title}" if title else "") + "."}


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
            stored[e["key"]] = chosen[e["key"]] = "|".join(now + [e["value"]])
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
    """Words whose suggestion is rejected. Kept as they stand, spaces and all:
    the grammar check's " :" (a space before the colon) is not the ":" the
    comma check suggests, and stripping it made the rejection match nothing."""
    if words.strip():
        execute("INSERT OR IGNORE INTO spec_ignored (scope, words) VALUES (?, ?)",
                (scope, words.lower()))


def reject_all(scope: int, found: list[dict], kind: str, old: str | None = None) -> int:
    """Every suggestion of a kind (or of one group of it) rejected; how many words."""
    words = {f["old"] for f in found if f["kind"] == kind and f["old"]
             and (old is None or f["old"] == old)}
    for w in words:
        ignore(scope, w)
    return len(words)


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


def _accept_found(rows: list[dict], found: list[dict], kind: str, old: str | None = None,
                  new: str | None = None) -> int:
    """Every suggestion of a kind taken (or of one group of it: the same words
    with the same suggestion), where there is a suggestion to take. Figures
    that disagree, and wording only the engineer can write, are left."""
    from . import specs_language

    todo = [f for f in found if f["kind"] == kind and f["old"] and f["new"]
            and "disagree" not in f["message"]
            and (old is None or f["old"] == old) and (new is None or f["new"] == new)]
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


def accept_all_set(set_id: int, kind: str, old: str | None = None, new: str | None = None) -> int:
    rows = set_whole(set_id)
    count = _accept_found(rows, language_set(set_id), kind, old, new)
    for s in rows:
        if s.get("changed"):
            save_set_section(set_id, s["id"], s["nodes"])
    return count


def accept_all_library(kind: str, old: str | None = None, new: str | None = None) -> int:
    rows = library_whole()
    count = _accept_found(rows, language_library(), kind, old, new)
    for s in rows:
        if s.get("changed"):
            master = section(s["id"])
            save_section(master["number"], master["title"], s["nodes"],
                         note=f"All {kind} suggestions accepted", section_id=s["id"])
    return count
