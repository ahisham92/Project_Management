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
    the ones already here as they are."""
    conn = get_db()
    count = 0
    with conn:
        for i, r in enumerate(rows):
            key = re.sub(r"[^a-z0-9_]", "", str(r.get("key", "")).lower())
            if not key:
                continue
            values = (key, r.get("label", "") or key.replace("_", " ").capitalize(),
                      r.get("grp") or r.get("group") or "", r.get("help") or "",
                      r.get("suggested") if r.get("suggested") is not None else None,
                      1 if r.get("per_element") else 0, 1 if r.get("many") else 0,
                      1 if r.get("optional") else 0, int(r.get("position", r.get("order", i)) or 0))
            conn.execute(
                f"INSERT INTO spec_questions ({', '.join(FIELDS)}) VALUES ({', '.join('?' * len(FIELDS))}) "
                "ON CONFLICT(key) DO " + ("NOTHING" if mode == "add" else
                                          "UPDATE SET " + ", ".join(f"{f} = excluded.{f}"
                                                                    for f in FIELDS[1:])),
                values)
            count += 1
    return count


def packed() -> list[dict]:
    return [{k: d[k] for k in FIELDS} for d in definitions().values()]


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
                place = {"row_id": s["id"], "number": s["number"], "label": n["label"],
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
        g = groups.setdefault(q["group"], {"name": q["group"], "questions": [], "open": 0,
                                           "slug": re.sub(r"[^a-z0-9]+", "-", q["group"].lower()).strip("-")})
        g["questions"].append(q)
        g["open"] += not q["answered"]
    return list(groups.values())


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
        if q["rows"]:
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
