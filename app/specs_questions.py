"""The questions a project answers once, each filling every clause it belongs to.

The master sections carry them in their text as ``{{key|master's words}}``, or
``{{key@element|master's words}}`` where the master asks it per element (the
concrete class for foundations, another for basement walls). What a question
says, its group and the answer to suggest are kept here, in the library; its
choices are the master's own, read at run time from the words it replaces, so
a project is only asked what its own sections need, with the answers they
offer. A project's answers are kept by key (``conc_strength``) and, where it
differs for an element, by key and element (``conc_strength@foundations``).
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import specs, specs_blanks
from .db import get_db, query

# The groups the questions come in, in the order they are asked.
GROUPS = [
    "Project information",
    "General requirements and submittals",
    "Quality, testing and inspection",
    "Concrete materials",
    "Concrete mixes and properties",
    "Placing, finishing and curing",
    "Formwork and accessories",
    "Reinforcement",
    "Post-tensioning and precast",
    "Structural steel",
    "Decking, framing and joists",
    "Stairs and railings",
    "Waterproofing",
    "Bridges",
    "Demolition, shoring and monitoring",
    "Repair and maintenance",
]
OTHER = "Other details"
FIELDS = ("key", "label", "grp", "help", "suggested", "per_element", "many", "optional", "position")
# What explains a question: a file that lacks them never clears them.
EXPLAINED = ("definition", "picture", "refs", "definition_kinds")
# Which questions a project answers per element rather than once for all.
SPLIT = "__split__"
FREE, NONE, SAME = "__free__", "__none__", "__same__"
# Kinds of concrete the master gives their own mix, named like elements.
KIND_LABELS = {"lightweight_slabs": "Lightweight concrete slabs", "stairs": "Stairs",
               "self_compacting": "Self-compacting concrete", "mass_concrete": "Mass concrete",
               "architectural_concrete": "Architectural concrete", "shotcrete": "Shotcrete",
               "bedding": "Bedding", "buried_structures": "Buried structures",
               "high_strength": "High-strength concrete", "cyclopean": "Cyclopean concrete",
               "pond_lining": "Pond linings", "equipment_bases": "Equipment bases",
               "hollow_core": "Hollow-core slabs", "double_tee": "Double tees"}


# --- the library's questions ------------------------------------------------------

def definitions() -> dict[str, dict]:
    return {r["key"]: dict(r) for r in query("SELECT * FROM spec_questions ORDER BY position, key")}


def save_definitions(rows: Iterable[Mapping[str, Any]], mode: str = "update") -> int:
    """Questions from a library file (or the builder) written in; ``add`` keeps
    the ones already here as they are. A question's explanation comes in when
    the file has one; a file without them leaves the ones here alone."""
    conn = get_db()
    count = 0
    columns = FIELDS + EXPLAINED
    keep = {f: f"COALESCE(NULLIF(excluded.{f}, {empty!r}), spec_questions.{f})"
            for f, empty in (("definition", ""), ("picture", ""), ("refs", "[]"),
                             ("definition_kinds", "{}"))}
    update = ", ".join(f"{f} = {keep.get(f, 'excluded.' + f)}" for f in columns[1:])
    with conn:
        for i, r in enumerate(rows):
            key = re.sub(r"[^a-z0-9_]", "", str(r.get("key", "")).lower())
            if not key:
                continue
            values = (key, r.get("label", "") or key.replace("_", " ").capitalize(),
                      r.get("grp") or r.get("group") or "", r.get("help") or "",
                      r.get("suggested") if r.get("suggested") is not None else None,
                      1 if r.get("per_element") else 0, 1 if r.get("many") else 0,
                      1 if r.get("optional") else 0, int(r.get("position", r.get("order", i)) or 0),
                      str(r.get("definition") or "").strip(), _slug(r.get("picture")),
                      json.dumps(clean_refs(r.get("refs")), ensure_ascii=False),
                      json.dumps(clean_kinds(r.get("definition_kinds")), ensure_ascii=False))
            conn.execute(
                f"INSERT INTO spec_questions ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
                "ON CONFLICT(key) DO " + ("NOTHING" if mode == "add" else "UPDATE SET " + update),
                values)
            count += 1
    return count


def packed() -> list[dict]:
    return [{**{k: d[k] for k in FIELDS}, "definition": d.get("definition") or "",
             "picture": d.get("picture") or "", "refs": refs_of(d),
             "definition_kinds": clean_kinds(d.get("definition_kinds"))}
            for d in definitions().values()]


# --- what explains a question ---------------------------------------------------------

REF_FIELDS = ("code", "clause", "title", "says")
DRAWINGS = Path(__file__).resolve().parent / "static" / "spec-drawings"
IMAGE_TYPES = {b"\x89PNG": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF8": "image/gif",
               b"RIFF": "image/webp"}
IMAGE_LIMIT = 4 * 1024 * 1024


def _slug(value: Any) -> str:
    slug = str(value or "").strip().lower()
    return slug if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", slug) else ""


def clean_refs(refs: Any) -> list[dict]:
    """What the codes say about a question, as a list of plain entries."""
    if isinstance(refs, str):
        try:
            refs = json.loads(refs or "[]")
        except ValueError:
            refs = []
    out = []
    for r in refs if isinstance(refs, list) else []:
        if not isinstance(r, Mapping) or not str(r.get("code") or "").strip():
            continue
        kinds = r.get("kinds") or []
        if isinstance(kinds, str):
            kinds = re.split(r"[\s,;/]+", kinds)
        out.append({**{f: str(r.get(f) or "").strip()[:600] for f in REF_FIELDS},
                    "kinds": [k.strip().upper() for k in kinds if k and k.strip()]})
    return out


def clean_kinds(given: Any) -> dict[str, str]:
    """A definition worded for one kind of project, by kind ("03A")."""
    if isinstance(given, str):
        try:
            given = json.loads(given or "{}")
        except ValueError:
            given = {}
    if not isinstance(given, Mapping):
        return {}
    return {str(k).strip().upper(): str(v).strip() for k, v in given.items()
            if str(k).strip() and str(v or "").strip()}


def definition_for(d: Mapping[str, Any], family: str = "") -> str:
    return clean_kinds(d.get("definition_kinds")).get((family or "").upper()) or d.get("definition") or ""


def refs_of(d: Mapping[str, Any]) -> list[dict]:
    return clean_refs(d.get("refs") or "[]")


def refs_from_lines(text: str) -> list[dict]:
    """Refs typed one per line: code | clause | title | what it says | kinds."""
    rows = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if not parts or not parts[0]:
            continue
        parts += [""] * (5 - len(parts))
        rows.append({"code": parts[0], "clause": parts[1], "title": parts[2], "says": parts[3],
                     "kinds": parts[4]})
    return clean_refs(rows)


def refs_as_lines(refs: list[dict]) -> str:
    return "\n".join(" | ".join([r["code"], r["clause"], r["title"], r["says"], " ".join(r["kinds"])])
                     for r in refs)


def drawing(slug: str) -> str:
    """One of the app's own drawings, to put in the page as it is."""
    slug = _slug(slug)
    path = DRAWINGS / f"{slug}.svg"
    if not slug or not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    return text[text.find("<svg"):] if "<svg" in text else ""


def drawings() -> list[str]:
    return sorted(p.stem for p in DRAWINGS.glob("*.svg")) if DRAWINGS.is_dir() else []


def save_explanation(key: str, definition: str, picture: str, refs: list[dict],
                     family: str = "") -> None:
    """An administrator's wording; with a kind, it is that kind's own definition
    (an empty one goes back to the shared wording)."""
    d = definitions().get(key) or {}
    kinds = clean_kinds(d.get("definition_kinds"))
    shared = d.get("definition") or ""
    if family:
        kinds[family.upper()] = (definition or "").strip()
        kinds = clean_kinds(kinds)
    else:
        shared = (definition or "").strip()
    get_db().execute("UPDATE spec_questions SET definition = ?, definition_kinds = ?, picture = ?, "
                     "refs = ? WHERE key = ?",
                     (shared, json.dumps(kinds, ensure_ascii=False), _slug(picture),
                      json.dumps(clean_refs(refs), ensure_ascii=False), key))
    get_db().commit()


def image_type(data: bytes) -> str | None:
    for magic, mime in IMAGE_TYPES.items():
        if data.startswith(magic) and (mime != "image/webp" or data[8:12] == b"WEBP"):
            return mime
    return None


def add_image(key: str, data: bytes, code: str = "", clause: str = "", caption: str = "",
              who: str = "") -> int | None:
    """A screenshot of a code's clause (or a picture) added to a question; the
    same picture twice is kept once. None when it is not a picture."""
    import hashlib

    mime = image_type(data)
    if mime is None or len(data) > IMAGE_LIMIT:
        return None
    sha = hashlib.sha256(data).hexdigest()
    code, clause = (code or "").strip()[:80], (clause or "").strip()[:80]
    have = query("SELECT id FROM spec_question_images WHERE key = ? AND code = ? AND clause = ? "
                 "AND sha = ?", (key, code, clause, sha))
    if have:
        return have[0]["id"]
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO spec_question_images (key, code, clause, caption, mime, sha, content, added_by) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (key, code, clause, (caption or "").strip()[:300], mime,
                                           sha, data, who))
    conn.commit()
    return cur.lastrowid


def images(key: str | None = None) -> list[dict]:
    sql = "SELECT id, key, code, clause, caption, mime, sha, added_by, added_at FROM spec_question_images"
    rows = query(sql + (" WHERE key = ?" if key else "") + " ORDER BY id", (key,) if key else ())
    return [dict(r) for r in rows]


def image(image_id: int) -> dict | None:
    rows = query("SELECT * FROM spec_question_images WHERE id = ?", (image_id,))
    return dict(rows[0]) if rows else None


def delete_image(image_id: int) -> None:
    get_db().execute("DELETE FROM spec_question_images WHERE id = ?", (image_id,))
    get_db().commit()


CODE_FAMILIES = ("American: ACI, ASTM, AISC", "British and European: BS, BS EN",
                 "Saudi Building Code")
# The codes each kind of specification is written to: 16A follows the Saudi
# Building Code, which is itself built on ACI 318.
BASIS = {"15A": (CODE_FAMILIES[0],), "03A": (CODE_FAMILIES[1],),
         "16A": (CODE_FAMILIES[2], CODE_FAMILIES[0])}
BRITISH = re.compile(r"^(BS|EN|PD|DD|NSCS|NSSS|National Structural|ICE|CIRIA|Concrete Society|SCI|"
                     r"Eurocode|UK NA)\b", re.I)


def code_family(ref: Mapping[str, Any]) -> str:
    """Which family of codes a reference is from, by its code's name."""
    code = (ref.get("code") or "").strip()
    if code.upper().startswith("SBC"):
        return CODE_FAMILIES[2]
    if BRITISH.match(code) or (ref.get("kinds") or []) == ["03A"]:
        return CODE_FAMILIES[1]
    return CODE_FAMILIES[0]


def explained(key: str, family: str = "") -> dict | None:
    """Everything the side panel shows for a question: what it means, its
    drawing, and what each code says, the project's own kind's codes first,
    with the screenshots added to each."""
    d = definitions().get(key)
    if d is None:
        return None
    family = (family or "").upper()
    shots = images(key)
    refs = []
    for r in refs_of(d):
        mine = not r["kinds"] or family in r["kinds"]
        refs.append({**r, "mine": mine,
                     "images": [i for i in shots if i["code"].lower() == r["code"].lower()
                                and i["clause"].lower() == r["clause"].lower()]})
    placed = {(i["code"].lower(), i["clause"].lower()) for r in refs for i in r["images"]}
    # Every code's clause is shown whatever the project's basis, one family of
    # codes under another: the one the project uses first.
    families: dict[str, dict] = {}
    basis = BASIS.get(family, ())
    for r in refs:
        name = code_family(r)
        one = families.setdefault(name, {"name": name, "refs": [], "mine": name in basis})
        one["refs"].append(r)
    order = list(basis) + [f for f in CODE_FAMILIES if f not in basis]
    return {**d, "definition": definition_for(d, family), "drawing": drawing(d.get("picture") or ""),
            "own_definition": family in clean_kinds(d.get("definition_kinds")),
            "refs": [r for r in refs if r["mine"]], "other_refs": [r for r in refs if not r["mine"]],
            "families": sorted(families.values(), key=lambda f: order.index(f["name"])),
            "pictures": [i for i in shots if not i["code"]],
            "loose": [i for i in shots if i["code"] and (i["code"].lower(), i["clause"].lower()) not in placed]}


# --- a project's answers ------------------------------------------------------------

def answers_of(spec_set: Mapping[str, Any] | None) -> dict[str, str]:
    if not spec_set:
        return {}
    try:
        return json.loads(spec_set["answers"] or "{}")
    except (KeyError, IndexError, ValueError):
        return {}


def values(spec_set: Mapping[str, Any] | None) -> dict[str, str]:
    """The answers as the text is filled from them."""
    return {k: v for k, v in answers_of(spec_set).items() if k != SPLIT}


def split_keys(answers: Mapping[str, str]) -> set[str]:
    return {k for k in (answers.get(SPLIT) or "").split("|") if k}


def save_answers(set_id: int, given: Mapping[str, str | None], split: Mapping[str, bool]) -> None:
    """Answers written in: ``given`` maps a key (or key@element) to its words,
    or to None to forget it; ``split`` says, for a per-element question, whether
    it is answered per element."""
    from .db import query_one
    row = query_one("SELECT answers FROM spec_sets WHERE id = ?", (set_id,))
    answers = json.loads(row["answers"] or "{}") if row else {}
    for key, words in given.items():
        if words is None:
            answers.pop(key, None)
        else:
            answers[key] = words
    keys = split_keys(answers)
    for key, on in split.items():
        (keys.add if on else keys.discard)(key)
        if not on:
            for k in [k for k in answers if k.startswith(key + "@")]:
                answers.pop(k)
    answers[SPLIT] = "|".join(sorted(keys))
    if not answers[SPLIT]:
        answers.pop(SPLIT)
    conn = get_db()
    with conn:
        conn.execute("UPDATE spec_sets SET answers = ?, updated_at = datetime('now') WHERE id = ?",
                     (json.dumps(answers, ensure_ascii=False), set_id))


# --- what a project is asked --------------------------------------------------------

def _balanced(text: str) -> str:
    """A choice without the stray bracket the master's typing left on it
    ("0.38 mm)", "(38 mm")."""
    if text.count("(") != text.count(")"):
        text = text.strip("()").strip()
        if text.count("(") != text.count(")"):
            text = text.replace("(", "").replace(")", "")
    if text.startswith("(") and text.endswith(")") and "(" not in text[1:-1] and ")" not in text[1:-1]:
        text = text[1:-1].strip()
    return text


def _pretty(key: str) -> str:
    words = re.sub(r"^[a-z]+_", "", key).replace("_", " ")
    return words[:1].upper() + words[1:]


def asked(sections: Iterable[Mapping[str, Any]], chosen: Mapping[str, str],
          spec_set: Mapping[str, Any] | None, elements: Iterable[str] = ()) -> list[dict]:
    """The questions a project's sections ask, grouped, each with the master's
    choices, where it is used, and what the project has answered.

    ``elements`` are the slugs of the project's elements: a question asked per
    element offers a row for each element both the text and the project have
    (every element the text has, when the project has named none)."""
    defs = definitions()
    answers = answers_of(spec_set)
    split = split_keys(answers)
    have = set(elements)
    from . import specs_seed
    known = {k[0] for k in getattr(specs_seed, "ELEMENT_KINDS", [])}
    found: "OrderedDict[str, dict]" = OrderedDict()
    for s in sections:
        nodes = specs.loads(s["body"])
        for n in specs.number(nodes, chosen):
            if not n["included"] or n["level"] == specs.NOTE:
                continue
            for m in specs.fields(n["text"]):
                if m.group(3) is None:
                    continue
                key, element = m.group(1), m.group(2)
                q = found.get(key)
                if q is None:
                    d = defs.get(key, {})
                    q = found[key] = {
                        "key": key, "label": d.get("label") or _pretty(key),
                        "group": d.get("grp") if d.get("grp") in GROUPS else OTHER,
                        "help": d.get("help") or "", "suggested": d.get("suggested"),
                        "per_element": bool(d.get("per_element")), "many": bool(d.get("many")),
                        "optional": bool(d.get("optional")), "position": d.get("position") or 0,
                        "choices": [], "free": [], "elements": [], "places": [], "all_single": True,
                        "switch": False,
                    }
                pieces = specs_blanks.pieces(m.group(3))
                if len(pieces) != 1 or pieces[0]["free"]:
                    q["all_single"] = False
                for piece in pieces:
                    text = _balanced(piece["text"].strip(" ,;"))
                    target = q["free"] if piece["free"] else q["choices"]
                    if text and text not in target:
                        target.append(text)
                if element and element not in q["elements"]:
                    q["elements"].append(element)
                place = {"row_id": s["id"], "number": s["number"], "label": n.get("path") or n["label"],
                         "article": re.sub(r"^\d+(\.\d+)?\s+", "", n.get("article") or "").strip().capitalize(),
                         "node_id": n["id"], "element": element}
                if place not in q["places"]:
                    q["places"].append(place)
    out = []
    for q in found.values():
        # Optional words the master puts in one bracket wherever it asks: a
        # yes or no, and yes keeps each place's own words.
        # A single word the master offers where it must be said ("[20 mm]") is
        # not a yes or no: it keeps its box for other words.
        q["single_choice_optional"] = q["yes_no"] = q["all_single"] and q["optional"]
        if q["yes_no"]:
            q["optional"] = True
            q["example"] = q["choices"][0] if q["choices"] else ""
            q["choices"] = [specs.KEEP]
            if q["suggested"] is not None:
                q["suggested"] = specs.KEEP if q["suggested"] not in ("", specs.KEEP, "No", "no") else ""
        # A row for each element the project has; a kind of concrete the master
        # sets apart (self-compacting, mass) that is not an element always has one.
        q["rows"] = ([e for e in q["elements"] if not have or e in have or e not in known]
                     if q["per_element"] or q["elements"] else [])
        q["split"] = q["key"] in split and bool(q["rows"])
        q["answer"] = answers.get(q["key"])
        q["answered"] = q["key"] in answers
        q["row_answers"] = {e: answers.get(f"{q['key']}@{e}") for e in q["rows"]}
        if q["suggested"] is None and q["choices"] and not q["optional"] and q["key"] not in defs:
            # A question the library does not describe: the master's first answer.
            q["suggested"] = q["choices"][0]
        q["sections"] = sorted({p["number"] for p in q["places"]})
        out.append(q)
    out += _switches(sections, spec_set)
    order = {g: i for i, g in enumerate(GROUPS + [OTHER])}
    out.sort(key=lambda q: (order[q["group"]], q["position"], q["label"]))
    return out


def _switches(sections: Iterable[Mapping[str, Any]], spec_set: Mapping[str, Any] | None) -> list[dict]:
    """The master's yes-or-no (and pick-one) questions that decide whether
    paragraphs of these sections are issued at all, asked with the rest:
    the ones written from the master's notes, which carry one of the groups
    above (the project's basic questions have their own step)."""
    from . import specs_store
    used: set[str] = set()
    for s in sections:
        used |= specs.keys_used(specs.loads(s["body"]))
    stored = json.loads(spec_set["options"] or "{}") if spec_set else {}
    out = []
    for o in specs_store.options():
        if o["key"] not in used or o.get("grp") not in GROUPS:
            continue
        out.append({
            "key": o["key"], "label": o["label"] or _pretty(o["key"]), "group": o["grp"],
            "help": "", "suggested": o["default_value"] or None, "per_element": False,
            "many": o.get("kind") == "many", "optional": False, "position": -1, "switch": True,
            "choices": o["choice_list"], "free": [], "elements": [], "places": [], "rows": [],
            "split": False, "yes_no": False, "single_choice_optional": False,
            "answer": stored.get(o["key"]), "answered": o["key"] in stored, "row_answers": {},
            "sections": []})
    return out


def save_switches(set_id: int, given: Mapping[str, str | None]) -> None:
    from .db import query_one
    row = query_one("SELECT options FROM spec_sets WHERE id = ?", (set_id,))
    stored = json.loads(row["options"] or "{}") if row else {}
    for key, value in given.items():
        if value is not None:
            stored[key] = value
    conn = get_db()
    with conn:
        conn.execute("UPDATE spec_sets SET options = ?, updated_at = datetime('now') WHERE id = ?",
                     (json.dumps(stored, ensure_ascii=False), set_id))


def grouped(questions: list[dict]) -> list[dict]:
    groups: "OrderedDict[str, dict]" = OrderedDict()
    for q in questions:
        g = groups.setdefault(q["group"], {"name": q["group"], "questions": [], "open": 0, "need": 0,
                                           "slug": re.sub(r"[^a-z0-9]+", "-", q["group"].lower()).strip("-")})
        g["questions"].append(q)
        g["open"] += not q["answered"]
        g["need"] += not q["answered"] and q.get("suggested") is None
    return list(groups.values())


# The questions told as the project is built: from the site and the paperwork,
# through what goes into the batch plant and the mix, the moulds and the steel,
# to the pour, the frame, keeping water out, proving it and looking after it.
# Each chapter takes whole groups, in this order.
STORY = [
    ("the-project", "The project", "Where it is, who is who, and what this specification is for.",
     ["Project information"]),
    ("before-work-starts", "Before work starts", "What the contractor submits and what is agreed "
     "before anything is built.", ["General requirements and submittals"]),
    ("preparing-the-site", "Preparing the site", "Taking down what is there, holding up what stays, "
     "and watching it move.", ["Demolition, shoring and monitoring"]),
    ("the-ingredients", "The ingredients", "Cement, sand, coarse aggregate, water and admixtures: "
     "what goes into the batch plant.", ["Concrete materials"]),
    ("the-mix", "The mix", "Each element's concrete: its class, strength, exposure, water/cement "
     "ratio, slump and air.", ["Concrete mixes and properties"]),
    ("the-moulds", "The moulds", "The formwork the concrete takes its shape from, and what is cast "
     "into it.", ["Formwork and accessories"]),
    ("the-steel-inside", "The steel inside", "Reinforcement, post-tensioning and the precast units.",
     ["Reinforcement", "Post-tensioning and precast"]),
    ("the-pour", "The pour", "Placing, finishing and curing: from the truck to the hardened "
     "surface.", ["Placing, finishing and curing"]),
    ("the-steel-frame", "The steel frame", "Structural steel, decking and joists, stairs and "
     "railings.", ["Structural steel", "Decking, framing and joists", "Stairs and railings"]),
    ("keeping-water-out", "Keeping water out", "Membranes, waterstops and how the structure stays "
     "dry.", ["Waterproofing"]),
    ("bridges", "Bridges", "What a bridge asks beyond the rest.", ["Bridges"]),
    ("proving-it", "Proving it", "Tests, inspections and what happens when a result falls short.",
     ["Quality, testing and inspection"]),
    ("looking-after-it", "Looking after it", "Repairs and maintenance once the structure is in "
     "service.", ["Repair and maintenance"]),
    ("other-details", OTHER, "Questions the library does not place in a chapter.", [OTHER]),
]
CHAPTER_OF = {g: c[0] for c in STORY for g in c[3]}


def story(questions: list[dict]) -> list[dict]:
    """The questions as chapters of the project's story, in the order it is
    built; each chapter as ``grouped`` gives a group, with its lead line and
    the groups it holds. Chapters with nothing asked are left out."""
    by_group = {g["name"]: g for g in grouped(questions)}
    out = []
    for slug, name, lead, groups in STORY:
        held = [by_group[g] for g in groups if g in by_group]
        if not held:
            continue
        qs = [q for g in held for q in g["questions"]]
        out.append({"name": name, "slug": slug, "lead": lead, "questions": qs,
                    "groups": [g["name"] for g in held], "group_slugs": [g["slug"] for g in held],
                    "open": sum(g["open"] for g in held), "need": sum(g["need"] for g in held)})
    for i, c in enumerate(out, 1):
        c["number"] = i
    return out


def joined(words: list[str]) -> str:
    """Several answers as a sentence says them: "A, B and C"."""
    words = [w for w in words if w]
    return words[0] if len(words) == 1 else (", ".join(words[:-1]) + " and " + words[-1] if words else "")


def read_form(form, questions: list[dict]) -> tuple[dict[str, str | None], dict[str, bool]]:
    """A group's answers as its page sent them: for each question the button
    picked (one of the master's choices, typed words, or left out), several
    ticked for a question that takes several, and a row per element when it
    is answered per element."""
    given: dict[str, str | None] = {}
    split: dict[str, bool] = {}

    def one(name: str, q: dict) -> str | None:
        typed = (form.get(f"t_{name}") or "").strip()
        if q["many"]:
            picked = [p for p in form.getlist(f"q_{name}") if p not in (FREE, NONE, SAME)]
            if NONE in form.getlist(f"q_{name}"):
                return ""
            if typed:
                picked.append(typed)
            return joined(picked) if picked else None
        pick = form.get(f"q_{name}", "")
        if pick == SAME:
            return None
        if pick == NONE:
            return ""
        if pick in ("", FREE):
            return " ".join(typed.split()) or None
        return pick

    for q in questions:
        key = q["key"]
        if q.get("switch"):
            picked = [p for p in form.getlist(f"q_{key}") if p in q["choices"]]
            if picked:
                given[key] = "|".join(picked) if q["many"] else picked[0]
            continue
        value = one(key, q)
        if value is not None:
            given[key] = value
        if q["rows"] and f"split_{key}" in form:
            on = form.get(f"split_{key}") == "1"
            split[key] = on
            if on:
                for e in q["rows"]:
                    given[f"{key}@{e}"] = one(f"{key}@{e}", q)
    return given, split


def picked(q: Mapping[str, Any], current: str | None, answered: bool,
           same: bool = False) -> tuple[list[str], str]:
    """What a question's buttons show as picked, and the words in its box:
    its answer, or else the suggested one (not on a per-element row, which
    starts as the same as all)."""
    if answered:
        value = current or ""
    elif not same and q.get("suggested") is not None:
        value = q["suggested"]
    else:
        return [], ""
    if q.get("many") and value:
        picks = [c for c in q["choices"] if c in value]
        rest = value
        for c in picks:
            rest = rest.replace(c, "")
        rest = re.sub(r"^(?:\s*(?:,|and)\s*)+|(?:\s*(?:,|and)\s*)+$", "", rest.strip())
        return picks, rest
    if value in q["choices"] or value == "":
        return [value], ""
    return [], value


def shown(q: Mapping[str, Any], value: str | None) -> str:
    """An answer as the engineer reads it on the page."""
    if value is None:
        return ""
    if value == specs.KEEP:
        return "Yes"
    if value == "":
        return "No" if q.get("yes_no") else "Left out"
    return value
