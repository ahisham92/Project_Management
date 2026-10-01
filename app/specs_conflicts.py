"""The engineer's own words against the project's answers.

A master paragraph carries its questions as fields (``{{rebar_cover_exterior|[50]}}``)
and is filled from the project's answers. When the engineer amends a paragraph
and types a value where a field was ("Cover: 40 mm" where the answer is 50),
or writes a paragraph of their own giving a property the answers already give,
the clause and the answer can say different things. This finds those places.

Nothing here changes any text: the check page shows each one with both values
side by side and the engineer decides (use the answer, change the answer, or
keep the words with a reason).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence

from . import specs, specs_check

# --- values: numbers with their units, and grades and classes ------------------------

# A unit and the quantity it measures, with the factor to the quantity's base unit.
UNITS = [
    (r"mm", "length", 1.0), (r"cm", "length", 10.0),
    (r"MPa|N/mm2|N/mm²|N/sq\.? ?mm", "stress", 1.0),
    (r"kg/m3|kg/m³|kg/cu\.? ?m", "density", 1.0),
    (r"%|percent|per cent", "percent", 1.0),
    (r"°C|deg(?:rees)? C|degC", "temperature", 1.0),
    (r"days?", "days", 1.0), (r"hours?|hrs?", "hours", 1.0),
    (r"µm|microns?|um", "film", 1.0), (r"mils?", "film", 25.4),
    (r"g/m2|g/m²", "coating", 1.0), (r"kN/m2|kN/m²|kPa", "pressure", 1.0),
]
_UNIT = "|".join(f"(?:{u})" for u, _q, _f in UNITS)
QUANTITY = re.compile(r"(?<![\w/.])(\d+(?:[.,]\d+)?)\s*(" + _UNIT + r")?(?![\w/])", re.I)

# Grades and classes, each family on its own: an answer of XS3 is contradicted by
# XS2 typed in, not by a C32/40 in the same clause.
CODES = [
    ("concrete class", re.compile(r"\bC\d{2,3}/\d{2,3}\b")),
    ("exposure class", re.compile(r"\bX(?:0|C[1-4]|D[1-3]|S[1-3]|F[1-4]|A[1-3])\b")),
    ("exposure class (ACI)", re.compile(r"\b(?:F[0-3]|S[0-3]|W[0-2]|C[0-2])\b")),
    ("steel grade", re.compile(r"\b(?:S(?:235|275|355|420|460)(?:J[0R2]|K2|N|M)?(?:\s?H)?|B500[ABC])\b")),
    ("bar grade", re.compile(r"\bGrade\s+(?:40|60|75|80|100|280|420|520|550|690)\b", re.I)),
]


def _unit_of(unit: str | None) -> tuple[str | None, float]:
    if not unit:
        return None, 1.0
    for pattern, quantity, factor in UNITS:
        if re.fullmatch(pattern, unit, re.I):
            return quantity, factor
    return None, 1.0


def quantities(text: str) -> list[dict]:
    """Each number in the text, with what it measures (None when it has no unit;
    "ratio" for a bare 0.40) and its value in that quantity's base unit."""
    out = []
    for m in QUANTITY.finditer(text or ""):
        raw = m.group(1).replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            continue
        quantity, factor = _unit_of(m.group(2))
        if quantity is None and re.fullmatch(r"0\.\d{1,3}", raw):
            quantity = "ratio"
        out.append({"value": round(number * factor, 6), "quantity": quantity,
                    "start": m.start(), "end": m.end(), "number": m.group(1), "said": m.group(0).strip()})
    return out


def codes(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for family, rule in CODES:
        found = [re.sub(r"\s+", " ", m.group(0)).upper() for m in rule.finditer(text or "")]
        if found:
            out[family] = list(dict.fromkeys(found))
    return out


def disagree(answer: str, typed: str) -> bool:
    """Whether the words typed give a different value from the answer.

    Grades and classes of a family both give must be among the answer's. A
    number typed with a unit must be one of the answer's numbers of that
    quantity (or, if the answer gives its numbers without units, one of
    those); a number typed bare must be one of the answer's numbers. Words
    with no value in them never disagree: rewording is the engineer's to do."""
    a_codes, t_codes = codes(answer), codes(typed)
    for family, given in t_codes.items():
        if family in a_codes and not set(given) <= set(a_codes[family]):
            return True
    a, t = quantities(answer), quantities(typed)
    if not a or not t:
        return False
    for q in t:
        if q["quantity"] is None:
            pool = [x["value"] for x in a]
        else:
            pool = [x["value"] for x in a if x["quantity"] == q["quantity"]] or \
                [x["value"] for x in a if x["quantity"] is None]
            if not pool:
                continue                       # a different quantity altogether
        if not any(abs(q["value"] - v) < 1e-6 for v in pool):
            return True
    return False


def matched_answer(answer: str, typed: str) -> str:
    """The answer changed to say what was typed, keeping its own way of saying
    it: "100 mm, plus or minus 25 mm" with 75 typed reads "75 mm, plus or minus
    25 mm". The typed words themselves when that cannot be done."""
    a_codes, t_codes = codes(answer), codes(typed)
    out = answer
    changed = False
    for family, given in t_codes.items():
        if family in a_codes and len(a_codes[family]) == 1 and len(given) == 1:
            out = re.sub(re.escape(a_codes[family][0]), given[0], out, count=1, flags=re.I)
            changed = True
    a, t = quantities(out), quantities(typed)
    used: set[int] = set()
    edits = []
    for q in t:
        pool = [x for x in a if (x["quantity"] == q["quantity"] or x["quantity"] is None
                                 or q["quantity"] is None) and id(x) not in used]
        if not pool or any(abs(q["value"] - x["value"]) < 1e-6 for x in pool):
            continue
        x = pool[0]
        used.add(id(x))
        edits.append((x["start"], x["start"] + len(x["number"]), q["number"]))
    for start, end, number in sorted(edits, reverse=True):
        out = out[:start] + number + out[end:]
        changed = True
    if changed and not disagree(out, typed):
        return out
    return typed.strip(" ,;.")


# --- where the engineer's words stand against the master's -----------------------------

TOKEN = re.compile(r"\{\{[^{}]*\}\}|[A-Za-z0-9µ°²³]+(?:[./][A-Za-z0-9µ°²³]+)*|\S")


def _tokens(text: str) -> list[re.Match]:
    return list(TOKEN.finditer(text or ""))


def _key(tok: str) -> str:
    return tok if tok.startswith("{{") else tok.lower()


def typed_over(master: str, ours: str) -> tuple[list[dict], list[tuple[int, int]]]:
    """How a paragraph as amended differs from the master: each master field
    the engineer typed over, with the words typed in its place and where they
    are; and the other stretches of the amended text that are the engineer's
    own (start, end)."""
    a, b = _tokens(master), _tokens(ours)
    matcher = SequenceMatcher(None, [_key(m.group(0)) for m in a], [_key(m.group(0)) for m in b],
                              autojunk=False)
    over, own = [], []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        start = b[j1].start() if j1 < j2 else (b[j1 - 1].end() if j1 else 0)
        end = b[j2 - 1].end() if j1 < j2 else start
        fields = [m for m in a[i1:i2] if m.group(0).startswith("{{")]
        typed = ours[start:end]
        # A field still in the amended words is still filled from its answer.
        typed_fields = [m for m in b[j1:j2] if m.group(0).startswith("{{")]
        if fields and j1 < j2 and not typed_fields:
            for f in fields:
                over.append({"field": f.group(0), "typed": typed, "start": start, "end": end,
                             "fields_here": len(fields)})
        elif j1 < j2:
            own.append((start, end))
    return over, own


# --- topics: properties the answers give, for words written without a field ---------

# A property found in a sentence (by the checker's own rules), and the questions
# whose answers give it.
TOPICS = [
    ("Concrete cover", re.compile(r"^(?:rebar|precast|pt|conc)_\w*cover(?!\w*(?:tolerance|meter|code|ing|age))")),
    ("Water-cementitious ratio", re.compile(r"(?:^|_)(?:max_)?wcm?$")),
    ("Slump", re.compile(r"slump")),
    ("Cement content", re.compile(r"min_cement")),
    ("Air content", re.compile(r"(?:^|_)air(?:_|$)")),
    ("Compressive strength", re.compile(r"^conc_strength$")),
]
STRENGTH = ("Compressive strength", r"\bcompressive strength\b|\bstrength of concrete\b", {"MPa"}, "")
CODE_TOPICS = [
    ("concrete class", re.compile(r"^conc_class$"), None),
    ("exposure class", re.compile(r"exposure_class$"), None),
    ("exposure class (ACI)", re.compile(r"exposure_class$"), re.compile(r"\bexposure\b", re.I)),
    ("steel grade", re.compile(r"(?:^rebar_grade$|steel_grade)"), None),
    ("bar grade", re.compile(r"^rebar_grade$"), None),
]


def _answered(values: Mapping[str, str], rule: re.Pattern) -> list[tuple[str, str, str]]:
    """(key, element, answer) for each answer of a question the rule names."""
    out = []
    for full, words in values.items():
        key, _, element = full.partition("@")
        if rule.search(key) and words and words != specs.KEEP:
            out.append((key, element, str(words)))
    return out


def _blank_fields(text: str) -> str:
    """The text with its fields blanked out, every other character where it was."""
    return specs.VARIABLE.sub(lambda m: " " * len(m.group(0)), text or "")


def _inside(start: int, end: int, spans: Sequence[tuple[int, int]]) -> bool:
    return any(s <= start and end <= e for s, e in spans)


UNIT_AFTER = re.compile(r"\s*(" + _UNIT + r")(?![\w/])", re.I)


def with_unit(value: str, unit: str) -> str:
    """A value as the clause reads it: with the unit written after it, when the
    value has none of its own ("50" in "{{cover}} mm" reads "50 mm")."""
    value = (value or "").strip()
    if not unit or not quantities(value) or any(q["quantity"] not in (None, "ratio")
                                                for q in quantities(value)):
        return value
    return f"{value} {unit}"


# --- the check ----------------------------------------------------------------------------

def element_name(slug: str) -> str:
    return (slug or "").replace("_", " ").strip().capitalize()


def find(sections: Iterable[Mapping[str, Any]], bases: Mapping[int, list[dict] | None],
         chosen: Mapping[str, str], values: Mapping[str, str],
         labels: Mapping[str, str]) -> list[dict]:
    """Each place an issued paragraph the engineer amended or wrote says a value
    the answers say otherwise. ``sections`` each carry ``id``, ``number``,
    ``title`` and ``nodes``; ``bases`` maps a section's id to the master text
    it was copied from (None for the project's own section)."""
    found: list[dict] = []
    for s in sections:
        base = bases.get(s["id"])
        master = {n["id"]: n for n in base or []}
        for n in specs.number(s["nodes"], chosen):
            if not n["included"] or n["level"] in (specs.NOTE, "PRT", "ART"):
                continue
            was = master.get(n["id"])
            if was is not None and was["text"] == n["text"]:
                continue
            ours = n["text"] or ""
            if was is not None:
                over, own = typed_over(was["text"] or "", ours)
            else:
                over, own = [], [(0, len(ours))]
            taken: list[tuple[int, int]] = []
            for o in over:
                m = specs.VARIABLE.fullmatch(o["field"])
                if not m:
                    continue
                answer = specs.answer(m, values)
                if answer in (None, "", specs.KEEP):
                    continue
                if not disagree(answer, o["typed"]):
                    continue
                key, element = m.group(1), m.group(2) or ""
                own_answer = bool(element) and f"{key}@{element}" in values
                answer_key = f"{key}@{element}" if own_answer else key
                new_answer = matched_answer(answer, o["typed"])
                # Changing the answer puts the field back only where it then reads as typed.
                restores = specs.fill(o["field"], {**values, answer_key: new_answer}).strip() == o["typed"].strip()
                after = UNIT_AFTER.match(ours, o["end"])
                unit = after.group(1) if after else ""
                found.append(_conflict(s, n, kind="field", unit=unit, shown=specs.fill(ours, values), key=key, element=element if own_answer else "",
                                       place_element=element, label=labels.get(key) or key.replace("_", " "),
                                       answer=answer, filled=specs.fill(o["field"], values),
                                       typed=o["typed"].strip(), start=o["start"], end=o["end"],
                                       field=o["field"], new_answer=new_answer, restores=restores))
                taken.append((o["start"], o["end"]))
            if own:
                found += _topics(s, n, ours, own, taken, values, labels)
    return found


def _topics(s, n, ours: str, own: list[tuple[int, int]], taken: list[tuple[int, int]],
            values: Mapping[str, str], labels: Mapping[str, str]) -> list[dict]:
    out = []
    blank = _blank_fields(ours)
    props = {p[0]: p for p in specs_check.PROPERTIES}
    props[STRENGTH[0]] = STRENGTH
    for name, rule in TOPICS:
        if name not in props:
            continue
        _n, pattern, units, _v = props[name]
        given = _answered(values, rule)
        if not given:
            continue
        seen: set[int] = set()
        for hit in re.finditer(pattern, blank, re.I):
            window_at = hit.end()
            window = blank[window_at:window_at + specs_check.NEAR]
            for q in quantities(window):
                unit = q["quantity"]
                if "ratio" in units:
                    if unit != "ratio":
                        continue
                elif unit is None or unit not in {_unit_of(u)[0] for u in units}:
                    continue
                start, end = window_at + q["start"], window_at + q["end"]
                if start in seen or not _inside(start, end, own) or _inside(start, end, taken):
                    break
                seen.add(start)
                if all(disagree(a, q["said"]) for _k, _e, a in given):
                    out.append(_topic(s, n, name, given, q["said"], start, end, labels,
                                      specs.fill(ours, values)))
                break
    for family, rule, needs in CODE_TOPICS:
        given = [g for g in _answered(values, rule) if family in codes(g[2])]
        if not given:
            continue
        for m in next(r for f, r in CODES if f == family).finditer(blank):
            if needs and not needs.search(blank[max(0, m.start() - 60):m.end() + 20]):
                continue
            if not _inside(m.start(), m.end(), own) or _inside(m.start(), m.end(), taken):
                continue
            if all(disagree(a, m.group(0)) for _k, _e, a in given):
                out.append(_topic(s, n, family[:1].upper() + family[1:], given, m.group(0),
                                  m.start(), m.end(), labels, specs.fill(ours, values)))
    return out


def _says(label: str, answer: str, element: str) -> str:
    return f"{answer} ({label}" + (f", for {element_name(element)}" if element else "") + ")"


def _topic(s, n, name: str, given, typed: str, start: int, end: int, labels, text: str) -> dict:
    unit = re.sub(r"^[\d.,\s]+", "", typed) if quantities(typed) else ""
    answers = [{"key": k, "element": e, "label": labels.get(k) or k.replace("_", " "), "answer": a,
                "new_answer": matched_answer(a, typed), "answer_shown": with_unit(a, unit),
                "new_answer_shown": with_unit(matched_answer(a, typed), unit)} for k, e, a in given]
    shown = [_says(x["label"], x["answer_shown"], x["element"]) for x in answers[:4]]
    message = (f"{name}: your words say {typed}; the answer{'s say' if len(answers) > 1 else ' says'} "
               + ("; ".join(shown) + (f" and {len(answers) - 4} more" if len(answers) > 4 else "")))
    return specs_check._item(s, n, message, severity="warning", words=typed, shown=text, extra={"conflict": {
        "kind": "topic", "property": name, "typed": typed, "typed_shown": typed, "start": start,
        "end": end, "answers": answers}})


def _conflict(s, n, kind: str, unit: str, shown: str, key: str, element: str, place_element: str, label: str, answer: str,
              filled: str, typed: str, start: int, end: int, field: str, new_answer: str,
              restores: bool) -> dict:
    whose = f" for {element_name(element)}" if element else ""
    typed_shown, answer_shown = with_unit(typed, unit), with_unit(answer, unit)
    message = f"Your words say {typed_shown} where the answer to “{label}”{whose} is {answer_shown}"
    return specs_check._item(s, n, message, severity="warning", words=typed, shown=shown, extra={"conflict": {
        "kind": kind, "key": key, "element": element, "place_element": place_element, "label": label,
        "answer": answer, "filled": filled, "typed": typed, "start": start, "end": end,
        "field": field, "new_answer": new_answer, "restores": restores, "unit": unit,
        "typed_shown": typed_shown, "answer_shown": answer_shown,
        "new_answer_shown": with_unit(new_answer, unit)}})


# --- what the engineer decides ---------------------------------------------------------------

def with_answer(text: str, conflict: Mapping[str, Any], answer: Mapping[str, Any] | None = None) -> str:
    """The paragraph with the answer back where the words typed are: the field
    itself, so the clause follows the answer from now on; for words written
    without a field, the answer chosen."""
    start, end = conflict["start"], conflict["end"]
    if conflict["kind"] == "field":
        return text[:start] + conflict["field"] + text[end:]
    put = _value_in(answer["answer"], conflict["typed"]) if answer else conflict["typed"]
    return text[:start] + put + text[end:]


def _value_in(answer: str, typed: str) -> str:
    """The part of an answer that stands for the value typed: 40 mm out of
    "40 mm, plus or minus 10 mm" when 45 mm was typed; a class for a class."""
    for family, given in codes(typed).items():
        theirs = codes(answer).get(family)
        if theirs:
            return theirs[0]
    t = quantities(typed)
    for x in quantities(answer):
        if not t or x["quantity"] in (t[0]["quantity"], None):
            unit = re.sub(r"^[\d.,\s]+", "", t[0]["said"]) if t else ""
            if x["quantity"] is None and unit:
                return f"{x['number']} {unit}".strip() if " " in t[0]["said"] else f"{x['number']}{unit}"
            return x["said"]
    return answer
