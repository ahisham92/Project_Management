"""The specification writer: one master text, amended per project, issued alike.

A specification section is a tree of numbered paragraphs in the MasterSpec
shape the office already writes in::

    SECTION 032000 - CONCRETE REINFORCING
    PART 1 - GENERAL                         PRT
    1.1     RELATED DOCUMENTS                ART
        A.  Drawings and general ...         PR1
            1.  Steel reinforcement bars.    PR2
                a.  Special inspection ...   PR3
                    1)  ...                  PR4
    END OF SECTION 032000

Here a section is kept as a flat list of those paragraphs, each with the level
it sits at — never the number. Numbers are worked out when the section is shown
or written, so a paragraph added, dropped or switched off for a project can
never leave a gap or a duplicate "C." behind it.

**The master and the project copy.** The library holds the office's master
text of each section. A project takes a copy and amends it. Every paragraph
keeps the id it had in the master, so what a project changed is always known:
what it added, what it reworded, what it dropped — and when the master moves on,
the paragraphs the project never touched move on with it.

**Options.** A paragraph may say when it applies — ``{if leed=v4.1}`` — and the
project's choices decide whether it is in. **Variables** are words the projects
differ on, typed once as ``{{engineer}}`` and filled from the project.

**Word, in and out.** A section comes in from a ``.docx`` whatever styles it was
drafted in, and always goes out in the house template's styles, header and
footer: that is what makes every issued specification look the same.

Standard library only — a .docx is a zip of XML.
"""

from __future__ import annotations

import difflib
import json
import re
import secrets
import struct
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "forms" / "spec_template.docx"

# The numbered levels, outermost first, and the unnumbered kinds beside them.
LEVELS = ["PRT", "ART", "PR1", "PR2", "PR3", "PR4"]
NOTE = "CMT"                        # an editor's note: shown here, never issued
TABLE = "TBL"                       # rows of cells, text holds "a | b | c" lines
KINDS = LEVELS + [NOTE, TABLE]
DEPTH = {level: i for i, level in enumerate(LEVELS)}

# Where each level sits in the MasterSpec list: PART is list level 0, the
# article 3, and the paragraphs 4 to 7. A template that numbers them otherwise
# says so in its own paragraphs, and `template_info` reads it from there.
STANDARD_ILVL = {"PRT": 0, "ART": 3, "PR1": 4, "PR2": 5, "PR3": 6, "PR4": 7}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{%s}" % W_NS


class SpecError(ValueError):
    """Something about a section or a file that cannot be used, said in words."""


def new_id() -> str:
    return secrets.token_hex(4)


def node(level: str, text: str, when: str = "", ident: str | None = None) -> dict:
    return {"id": ident or new_id(), "level": level, "text": text, "when": when}


def loads(body: str | None) -> list[dict]:
    if not body:
        return []
    try:
        data = json.loads(body)
    except ValueError:
        return []
    return [n for n in data if isinstance(n, dict) and n.get("level") in KINDS]


def dumps(nodes: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps([{"id": n["id"], "level": n["level"], "text": n["text"],
                        "when": n.get("when", "")} for n in nodes], ensure_ascii=False)


# --- options and conditions -------------------------------------------------

CONDITION = re.compile(r"^\{if\s+([^}]*)\}\s*", re.I)
# A word filled in per project: ``{{engineer}}``. A question from the master
# carries the master's own words after a bar, kept until the project answers
# it, and may be asked per element: ``{{conc_strength@foundations|[40MPa] [45MPa]}}``.
VARIABLE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)(?:@([A-Za-z0-9_]+))?\s*(?:\|([^{}]*))?\}\}")


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


ELEMENTS = "elements"


def applies(when: str, chosen: Mapping[str, str]) -> bool:
    """Whether a paragraph's condition holds for a project's choices.

    ``key=value`` holds when the project chose that value; ``key=a|b`` when it
    chose either; ``key!=value`` when it chose anything else. Several
    conditions joined with ``&`` must all hold. Nothing is a condition that
    always holds. A key the project has not answered never holds, so a
    paragraph for a particular choice is left out until somebody makes it.

    A question that takes several answers stores them joined by ``|``, and a
    condition holds when any of them is one it names.

    Alternatives are joined with ``;``, any one of them holding will do:
    ``structures=Marine structures;exposure=Marine`` (``&`` binds tighter).
    """
    when = (when or "").strip()
    if not when:
        return True
    if ";" in when:
        return any(applies(alt, chosen) for alt in when.split(";") if alt.strip())
    for part in when.split("&"):
        part = part.strip()
        if not part:
            continue
        negate = "!=" in part
        key, _, wanted = part.partition("!=" if negate else "=")
        have = {_norm(v) for v in str(chosen.get(key.strip()) or "").split("|")} - {""}
        if key.strip() == ELEMENTS and not have:
            # A project that has not said what its elements are keeps every
            # paragraph written for one, rather than losing them all.
            continue
        options = {_norm(v) for v in wanted.split("|")}
        hit = bool(have & options)
        if hit == negate:
            return False
    return True


# A choice inside a paragraph: ``{steel_protection=Paint system: or painted}`` —
# the words after the colon are there only when the condition holds.
INLINE = re.compile(r"\{([A-Za-z0-9_]+)\s*(!?=)\s*([^:{}]+?)\s*:\s?([^{}]*)\}")


def choose(text: str, chosen: Mapping[str, str]) -> str:
    """The paragraph with its inline choices settled for a project: the words of
    each choice that holds kept, the rest dropped with the gap they leave."""
    if "{" not in (text or ""):
        return text or ""
    dropped = False

    def one(m: re.Match) -> str:
        nonlocal dropped
        if applies(f"{m.group(1)}{m.group(2)}{m.group(3)}", chosen):
            return m.group(4)
        dropped = True
        return ""

    out = INLINE.sub(one, text)
    if dropped:
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"\s+([.,;:)])", r"\1", out)
        out = re.sub(r"\(\s+", "(", out).strip()
    return out


def condition_parts(when: str) -> list[str]:
    """Each ``key=value`` of a condition, whether joined by ``&`` or ``;``."""
    return [p for p in re.split(r"[&;]", when or "") if p.strip()]


def inline_conditions(text: str) -> list[str]:
    """The conditions of a paragraph's inline choices, as ``key=value``."""
    return [f"{m.group(1)}{m.group(2)}{m.group(3)}" for m in INLINE.finditer(text or "")]


def answer(match: re.Match, values: Mapping[str, str]) -> str | None:
    """What a field says for a project, or None while it has no answer. A
    question's answer for the element comes first, then its answer for all
    elements; an answer of nothing (words left out) counts."""
    name, element, fallback = match.group(1), match.group(2), match.group(3)
    for key in ([f"{name}@{element}"] if element else []) + [name]:
        value = values.get(key)
        if value not in (None, "") or (value == "" and fallback is not None and key in values):
            return value
    return None


# The answer to a question of optional words: keep the master's words, each
# place its own (the same yes can keep ", piling" here and "or bolt" there).
KEEP = "__keep__"


def kept(fallback: str) -> str:
    """The master's optional words without their brackets."""
    return re.sub(r"^\[|\]$", "", fallback.strip()) if fallback.strip().startswith("[") else fallback


# Words still to be specified in an issued text: a bracketed choice or prompt
# the master left for the engineer ("[F0] [F1]", "<Insert rating>"). The issued
# file shows each one highlighted, so none goes out unnoticed.
_OPEN = r"\[(?:[^\[\]\n]|\[[^\[\]\n]{0,200}\]){1,400}\]|<[A-Za-z][^<>\n]{0,120}>"
OPEN = re.compile(rf"(?:{_OPEN})(?:[ ,;/]*(?:{_OPEN}))*")
# A choice the master offers after the standard it is taken from:
# "[ACI 318 (ACI 318M)] [F0] [F1]" is ACI 318 with one of the classes.
STANDARD = re.compile(r"(?:ACI|ASTM|AASHTO|ANSI|AWS|BS|EN|ISO|SASO|SBC|PCI|CRSI)\b[^\[\]]*")


def open_prompt(name: str, fallback: str | None) -> str:
    """An unanswered question as the issued file says it: plainly what is still
    to be specified, not the master's raw brackets."""
    fallback = (fallback or "").strip()
    options = [o.strip(" ,;") for o in re.findall(r"\[([^\[\]]*)\]", fallback)]
    options = [o for o in options if o]
    asks = [a.strip() for a in re.findall(r"<([^<>]*)>", fallback) if a.strip()]
    if len(options) == 1:
        # An optional phrase: kept word for word, with the value it asks for.
        phrase = re.search(r"\[([^\[\]]*)\]", fallback).group(1).strip()
        if asks:
            phrase += f" [{asks[0][0].upper()}{asks[0][1:]}]"
        return f"[keep or delete: \u201c{phrase}\u201d]"
    if options:
        before = ""
        if len(options) > 2 and STANDARD.fullmatch(options[0]):
            before, options = options[0] + " ", options[1:]
        return (before + "[choose: " + " / ".join(options)
                + (f", or {asks[0][0].lower()}{asks[0][1:]}" if asks else "") + "]")
    if asks:
        return f"[{asks[0][0].upper()}{asks[0][1:]}]"
    if fallback:
        return f"[{fallback}]" if not OPEN.fullmatch(fallback) else fallback
    return f"[{name.replace('_', ' ')}: to be specified]"


def fill(text: str, values: Mapping[str, str], marked: bool = False) -> str:
    """The text with every ``{{variable}}`` it has a value for filled in, and
    every question it has an answer for; an unanswered question keeps the
    master's words, or (``marked``, for the issued file) says plainly what is
    still to be specified."""
    left_out = False

    def one(match: re.Match) -> str:
        nonlocal left_out
        value = answer(match, values)
        if value is None:
            if marked:
                return open_prompt(match.group(1), match.group(3))
            return match.group(3) if match.group(3) is not None else match.group(0)
        if value == KEEP:
            left_out = True
            return kept(match.group(3) or "")
        if match.group(3):
            # One of the master's own choices goes in as the master wrote it,
            # with the space or comma it starts with ("[, piling]", "[ or bolt]").
            for raw in re.findall(r"\[([^\[\]]*)\]", match.group(3)):
                if raw.strip(" ,;") == value and raw != value:
                    return raw
        left_out = left_out or value == ""
        return value

    text = text or ""
    if marked:
        text = WRAPPED.sub(lambda m: f"{m.group(1).strip()} {m.group(2)}", text)
    out = VARIABLE.sub(one, text)
    if out != text:
        # A choice taken with the comma it ends on, before the full stop: "view,." reads "view."
        out = re.sub(r",(?=[.;])", "", out)
    if left_out:
        # Words left out leave no stray separators: "A; ; B." and "A; ." read "A; B." and "A."
        out = re.sub(r"(?:\s*;)+\s*(?=[.;,)]|$)", "", out)
        out = re.sub(r"([:(])\s*(?:;\s*)+", r"\1 ", out)
        out = re.sub(r"[ \t]{2,}", " ", out)
        out = re.sub(r"\s+([.,;:)])", r"\1", out)
        out = re.sub(r"\(\s+", "(", out).strip()
    if marked:
        # The master's own prompts said the issued file's way: "<Insert limits>" reads "[Insert limits]".
        out = re.sub(r"<([A-Za-z])([^<>\n]{0,120})>", lambda m: f"[{m.group(1).upper()}{m.group(2)}]", out)
    return out


# A question the master wrapped in brackets with its standard, the prompt after
# it: "[ACI 318 (ACI 318M) {{exposure}}] <Specify>" is the standard and the answer.
WRAPPED = re.compile(r"\[(" + STANDARD.pattern + r")\s*(\{\{[^{}]*\}\})\]\s*(?:<[A-Za-z][^<>\n]{0,120}>)?")


def fields(text: str) -> Iterator[re.Match]:
    """The words filled in per project, questions included."""
    return VARIABLE.finditer(text or "")


def unfilled(nodes: Iterable[Mapping[str, Any]], values: Mapping[str, str]) -> list[str]:
    """Variables used in the text that have no value yet (questions, which
    keep the master's words until answered, are counted elsewhere)."""
    missing: list[str] = []
    for n in nodes:
        for m in VARIABLE.finditer(n.get("text", "")):
            name = m.group(1)
            if m.group(3) is None and not values.get(name) and name not in missing:
                missing.append(name)
    return missing


def keys_used(nodes: Iterable[Mapping[str, Any]]) -> set[str]:
    used = set()
    for n in nodes:
        for part in condition_parts(n.get("when") or "") + inline_conditions(n.get("text", "")):
            key = re.split(r"!?=", part, maxsplit=1)[0].strip()
            if key:
                used.add(key)
    return used


# --- numbering ---------------------------------------------------------------

def _letter(n: int, upper: bool) -> str:
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out if upper else out.lower()


def number(nodes: Sequence[Mapping[str, Any]], chosen: Mapping[str, str] | None = None) -> list[dict]:
    """Every paragraph with its label and whether it is in, in order.

    A paragraph left out takes the ones under it with it — a list of products
    under a heading that does not apply does not apply either — and nothing
    left out uses up a number.
    """
    chosen = chosen or {}
    nbs = is_nbs(nodes)
    counters = [0] * len(LEVELS)
    marks = [""] * len(LEVELS)                     # each level's own mark: "2.4", "B", "1" ...
    out: list[dict] = []
    cut_at: int | None = None                      # depth of the paragraph that was cut
    part, article = "", ""                         # the headings each paragraph sits under
    for n in nodes:
        level = n["level"]
        depth = DEPTH.get(level)
        if depth is not None and cut_at is not None and depth <= cut_at:
            cut_at = None
        included = cut_at is None and applies(n.get("when", ""), chosen)
        if depth is not None and cut_at is None and not included:
            cut_at = depth
        label, path = "", ""
        if depth is not None and included:
            counters[depth] += 1
            for deeper in range(depth + 1, len(LEVELS)):
                counters[deeper] = 0
            c = counters[depth]
            if nbs:
                # NBS: the clause number is typed in the heading, groups are
                # unnumbered and the lines under a clause are bulleted.
                clause = CLAUSE.match(n["text"]) if level == "ART" else None
                label = {"PRT": "", "ART": "", "PR1": "\u2022", "PR2": "\u2013",
                         "PR3": "\u00b7", "PR4": "\u00b7"}[level]
                marks[depth] = (clause.group(1) if clause else "") if level == "ART" else (
                    str(c) if level != "PRT" else "")
            else:
                label = {
                    "PRT": f"PART {c} -",
                    "ART": f"{counters[0] or 1}.{c}",
                    "PR1": f"{_letter(c, True)}.",
                    "PR2": f"{c}.",
                    "PR3": f"{_letter(c, False)}.",
                    "PR4": f"{c})",
                }[level]
                marks[depth] = label.rstrip(".)").replace("PART ", "").rstrip(" -")
            for deeper in range(depth + 1, len(LEVELS)):
                marks[deeper] = ""
            # How a cross-reference names it: Article 2.4, Paragraph 2.4.B.1.
            path = ".".join(m for m in marks[1:depth + 1] if m) if depth >= 1 else marks[0]
        if level == "PRT":
            part, article = (f"{label} {n['text']}" if label else n["text"]), ""
        elif level == "ART":
            article = f"{label} {n['text']}" if label else n["text"]
        out.append({**n, "label": label, "included": included, "path": path,
                    "indent": _indent(out, n), "part": part, "article": article})
    return out


# An NBS clause heading starts with its three-figure number: "110 QUALITY ASSURANCE".
CLAUSE = re.compile(r"^(\d{3}[A-Z]?)\b")


def is_nbs(nodes: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a section is written the NBS way (the British 03A sections):
    clause headings that carry their own numbers rather than 1.1, 1.2 ..."""
    heads = [n["text"] for n in nodes if n.get("level") == "ART"]
    return bool(heads) and sum(1 for t in heads if CLAUSE.match(t)) * 2 >= len(heads)


def _indent(before: list[dict], n: Mapping[str, Any]) -> int:
    """How far in a paragraph sits on the page, in steps."""
    if n["level"] in DEPTH:
        return max(DEPTH[n["level"]] - 1, 0)
    for prior in reversed(before):
        if prior["level"] in DEPTH:
            return max(DEPTH[prior["level"]], 1)
    return 1


def rows_of(text: str) -> list[list[str]]:
    return [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in (text or "").splitlines() if line.strip()]


# --- the text the editor shows ------------------------------------------------

MARK = {"PRT": "#", "ART": "##", "PR1": "-", "PR2": "--", "PR3": "---", "PR4": "----",
        NOTE: "//"}
LINE = re.compile(r"^(#{1,2}|-{1,4}|//)\s*(.*)$")


def to_text(nodes: Sequence[Mapping[str, Any]]) -> str:
    """A section as the plain text it is edited in.

    ``#`` is a PART, ``##`` an article, ``-`` to ``----`` the paragraphs under
    it, ``//`` an editor's note and ``|`` a table row. A condition leads the
    text: ``-- {if leed=v4.1} Product data for ...``.
    """
    lines: list[str] = []
    for n in nodes:
        if n["level"] == TABLE:
            lines.extend("| " + " | ".join(row) + " |" for row in rows_of(n["text"]))
            continue
        when = f"{{if {n['when']}}} " if n.get("when") else ""
        if n["level"] == "PRT" and lines:
            lines.append("")
        lines.append(f"{MARK[n['level']]} {when}{n['text']}")
    return "\n".join(lines) + ("\n" if lines else "")


def from_text(text: str) -> list[dict]:
    """The text the editor sent back, as paragraphs without ids yet."""
    nodes: list[dict] = []
    table: list[str] | None = None
    for raw in (text or "").replace("\r\n", "\n").split("\n"):
        line = raw.strip()
        if not line:
            table = None
            continue
        if line.startswith("|"):
            if table is None:
                table = []
                nodes.append({"level": TABLE, "text": "", "when": ""})
            table.append(line)
            nodes[-1]["text"] = "\n".join(table)
            continue
        table = None
        match = LINE.match(line)
        if not match:
            if nodes and nodes[-1]["level"] != TABLE:
                nodes[-1]["text"] = (nodes[-1]["text"] + " " + line).strip()
            else:
                nodes.append({"level": "PR1", "text": line, "when": ""})
            continue
        mark, rest = match.groups()
        level = {v: k for k, v in MARK.items()}[mark]
        when = ""
        cond = CONDITION.match(rest)
        if cond:
            when, rest = cond.group(1).strip(), rest[cond.end():]
        rest = rest.strip()
        if level in ("PRT", "ART"):
            rest = rest.rstrip(":").strip().upper()
        nodes.append({"level": level, "text": rest, "when": when})
    return nodes


# --- keeping ids across an edit -----------------------------------------------

def _key(n: Mapping[str, Any]) -> str:
    return f"{n['level']}\u0001{_norm(n['text'])}\u0001{_norm(n.get('when'))}"


def align(old: Sequence[Mapping[str, Any]], new: Sequence[Mapping[str, Any]]) -> list[dict]:
    """The new paragraphs, each given the id of the old one it is.

    Unchanged paragraphs keep theirs outright. A paragraph that was reworded
    where it stood keeps its id too, so it reads as an amendment of the master
    paragraph rather than a deletion beside an addition. Anything else is new.
    """
    old = list(old)
    new = [dict(n) for n in new]
    matcher = difflib.SequenceMatcher(a=[_key(n) for n in old], b=[_key(n) for n in new],
                                      autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                new[j1 + k]["id"] = old[i1 + k]["id"]
        elif tag == "replace":
            taken: set[int] = set()
            for j in range(j1, j2):
                best, score = None, 0.0
                for i in range(i1, i2):
                    if i in taken:
                        continue
                    ratio = difflib.SequenceMatcher(
                        a=_norm(old[i]["text"]), b=_norm(new[j]["text"])).ratio()
                    if old[i]["level"] == new[j]["level"]:
                        ratio += 0.1
                    if ratio > score:
                        best, score = i, ratio
                if best is not None and score >= 0.55:
                    taken.add(best)
                    new[j]["id"] = old[best]["id"]
    seen: set[str] = set()
    for n in new:
        if not n.get("id") or n["id"] in seen:
            n["id"] = new_id()
        seen.add(n["id"])
        n.setdefault("when", "")
    return new


# --- what a project changed ---------------------------------------------------

def same(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    return (a["level"] == b["level"] and _norm(a["text"]) == _norm(b["text"])
            and _norm(a.get("when")) == _norm(b.get("when")))


def compare(base: Sequence[Mapping[str, Any]], ours: Sequence[Mapping[str, Any]]) -> list[dict]:
    """The project's paragraphs, each marked against the master it came from.

    ``state`` is ``same``, ``changed`` (with the master's wording beside it),
    ``added``, or ``removed`` for a master paragraph the project dropped —
    listed where it used to be, so the gap can be seen.
    """
    by_id = {n["id"]: n for n in base}
    ours_ids = {n["id"] for n in ours}
    out: list[dict] = []
    # A dropped master paragraph goes back in after whatever preceded it.
    dropped_after: dict[str | None, list[dict]] = {}
    previous: str | None = None
    for n in base:
        if n["id"] not in ours_ids:
            dropped_after.setdefault(previous, []).append(n)
        else:
            previous = n["id"]
    for n in dropped_after.get(None, []):
        out.append({**n, "state": "removed", "was": None})
    for n in ours:
        master = by_id.get(n["id"])
        if master is None:
            out.append({**n, "state": "added", "was": None})
        elif same(master, n):
            out.append({**n, "state": "same", "was": None})
        else:
            out.append({**n, "state": "changed", "was": master})
        for gone in dropped_after.get(n["id"], []):
            out.append({**gone, "state": "removed", "was": None})
    return out


def amendments(base: Sequence[Mapping[str, Any]], ours: Sequence[Mapping[str, Any]]) -> dict:
    marked = compare(base, ours)
    return {
        "added": sum(1 for m in marked if m["state"] == "added"),
        "changed": sum(1 for m in marked if m["state"] == "changed"),
        "removed": sum(1 for m in marked if m["state"] == "removed"),
        "marked": marked,
    }


def merge(base: Sequence[Mapping[str, Any]], master: Sequence[Mapping[str, Any]],
          ours: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Brings a newer master into a project copy without losing the amendments.

    ``base`` is the master the project copied, ``master`` the master now, and
    ``ours`` the project's text. A paragraph the project never touched becomes
    whatever the master now says, or goes if the master dropped it. A paragraph
    the project reworded or added stays as the project has it, and one the
    project dropped stays dropped. New master paragraphs come in where the
    master put them.
    """
    base_by = {n["id"]: n for n in base}
    master_by = {n["id"]: n for n in master}
    ours_by = {n["id"]: n for n in ours}

    def ours_version(n: Mapping[str, Any]) -> dict | None:
        was = base_by.get(n["id"])
        if was is None:
            return dict(n)                          # the project added it
        if not same(was, n):
            return dict(n)                          # the project amended it
        now = master_by.get(n["id"])
        return dict(now) if now is not None else None

    result: list[dict] = []
    placed: set[str] = set()
    # Walk the master, putting in each paragraph as the project should have it,
    # and after each, whatever the project added after it.
    ours_order = [n["id"] for n in ours]
    for m in master:
        if m["id"] in ours_by:
            kept = ours_version(ours_by[m["id"]])
            if kept is not None:
                result.append(kept)
            placed.add(m["id"])
        elif m["id"] not in base_by:
            result.append(dict(m))                  # new in the master
            placed.add(m["id"])
        else:
            placed.add(m["id"])                     # the project dropped it
            continue
        # The project's own paragraphs that followed this one.
        if m["id"] in ours_by:
            k = ours_order.index(m["id"]) + 1
            while k < len(ours_order) and ours_order[k] not in master_by:
                extra = ours_by[ours_order[k]]
                kept = ours_version(extra)
                if kept is not None and extra["id"] not in placed:
                    result.append(kept)
                placed.add(extra["id"])
                k += 1
    # Anything of the project's that still has nowhere to go, at the head.
    lead = [ours_version(n) for n in ours if n["id"] not in placed]
    return [n for n in lead if n is not None] + result


# --- reading a Word document ------------------------------------------------

SECTION_LINE = re.compile(r"^SECTION\s*(\d[0-9A-Za-z.\- ]*?|[A-Z]\d{2}[A-Z]?)\s*[-–—]+\s*(.+)$", re.I)
# An NBS section's title line: "E30 - REINFORCEMENT FOR IN SITU CONCRETE".
NBS_LINE = re.compile(r"^([A-Z]\d{2}[A-Z]?)\s*[-–—]+\s*(.+)$")
PART_LINE = re.compile(r"^PART\s+\d+(?:\.\d+)?\s*[-–—]+\s*(.+)$", re.I)
END_LINE = re.compile(r"^END\s+OF\s+SECTION\b", re.I)
MANUAL = [
    (re.compile(r"^\d+\.\d+\s+(.+)$"), "ART"),
    (re.compile(r"^[A-Z]\.\s+(.+)$"), "PR1"),
    (re.compile(r"^\d{1,2}\.\s+(.+)$"), "PR2"),
    (re.compile(r"^[a-z]\.\s+(.+)$"), "PR3"),
    (re.compile(r"^\d{1,2}\)\s+(.+)$"), "PR4"),
]
STYLE_LEVEL = {"sct": "SCT", "prt": "PRT", "art": "ART", "pr1": "PR1", "pr2": "PR2",
               "pr3": "PR3", "pr4": "PR4", "pr5": "PR4", "eos": "EOS", "cmt": NOTE,
               # The same levels under the names an older MasterSpec used.
               "p1": "PR1", "p2": "PR2", "p3": "PR3", "p4": "PR4"}
ILVL_LEVEL = {v: k for k, v in STANDARD_ILVL.items()}


def _deleted(p: ET.Element) -> set[int]:
    return {id(t) for d in p.iter(W + "del") for t in d.iter(W + "t")}


def _on(el: ET.Element | None) -> bool:
    """Whether a Word on/off property is on: present, and not set to off."""
    return el is not None and (el.get(W + "val") or "true").lower() not in ("0", "false", "off")


def _texts(p: ET.Element, hidden_styles: set[str] = frozenset(), para_hidden: bool = False
           ) -> tuple[str, str]:
    """The words of a paragraph (or table cell) Word shows, and the ones it hides.

    Text is hidden by the run's own formatting, by its character style, or by
    the paragraph's style, and a run can switch the last two off again.
    """
    gone = _deleted(p)
    shown: list[str] = []
    hidden: list[str] = []
    for r in p.iter(W + "r"):
        rpr = r.find(W + "rPr")
        vanish = rpr.find(W + "vanish") if rpr is not None else None
        if vanish is not None:
            is_hidden = _on(vanish)
        else:
            rstyle = rpr.find(W + "rStyle") if rpr is not None else None
            is_hidden = para_hidden or (rstyle is not None and rstyle.get(W + "val") in hidden_styles)
        out = hidden if is_hidden else shown
        for el in r:
            if el.tag == W + "t" and el.text and id(el) not in gone:
                out.append(el.text)
            elif el.tag in (W + "tab", W + "br", W + "cr"):
                out.append(" ")
    clean = [re.sub(r"\s+", " ", "".join(x)).strip() for x in (shown, hidden)]
    return clean[0], clean[1]


def _paragraph_text(p: ET.Element, hidden_styles: set[str] = frozenset()) -> str:
    return _texts(p, hidden_styles)[0]


def _hidden_styles(z: zipfile.ZipFile) -> set[str]:
    """The styles that hide their text, directly or through the style they are based on."""
    try:
        root = ET.fromstring(z.read("word/styles.xml"))
    except (KeyError, ET.ParseError):
        return set()
    own: dict[str, bool | None] = {}
    based: dict[str, str] = {}
    for st in root.iter(W + "style"):
        sid = st.get(W + "styleId") or ""
        vanish = st.find(f"{W}rPr/{W}vanish")
        own[sid] = _on(vanish) if vanish is not None else None
        b = st.find(W + "basedOn")
        if b is not None:
            based[sid] = b.get(W + "val") or ""
    out = set()
    for sid in own:
        seen, at = set(), sid
        while at in own and at not in seen:
            seen.add(at)
            if own[at] is not None:
                if own[at]:
                    out.add(sid)
                break
            at = based.get(at, "")
    return out


def _styles(z: zipfile.ZipFile) -> dict[str, str]:
    try:
        root = ET.fromstring(z.read("word/styles.xml"))
    except KeyError:
        return {}
    names = {}
    for st in root.iter(W + "style"):
        sid = st.get(W + "styleId") or ""
        name = st.find(W + "name")
        names[sid] = (name.get(W + "val") if name is not None else sid) or sid
    return names


def _spec_list(z: zipfile.ZipFile) -> str:
    """The Word list a MasterSpec document numbers its parts and articles with."""
    try:
        styles = z.read("word/styles.xml").decode("utf-8")
    except (KeyError, UnicodeDecodeError):
        return ""
    for sid, name in re.findall(r'<w:style [^>]*w:styleId="([^"]+)"[^>]*>\s*<w:name w:val="([^"]+)"',
                                styles):
        if name.upper() in ("PRT", "ART"):
            block = re.search(r'w:styleId="%s".*?</w:style>' % re.escape(sid), styles, re.S)
            found = re.search(r'<w:numId w:val="(\d+)"/>', block.group(0)) if block else None
            if found and found.group(1) != "0":
                return found.group(1)
    return ""


def read_docx(data: bytes) -> dict:
    """A section read out of a Word document, whatever it was drafted in.

    The MasterSpec styles (SCT, PRT, ART, PR1 ...) say outright what each
    paragraph is. A section typed in Normal or List Paragraph does not, so the
    level comes from what is typed at the start of it ("1.2", "A.", "b.") or
    from where Word's own numbering put it. The numbers themselves are dropped
    — they are worked out again on the way out.
    """
    from . import specs_doc

    if specs_doc.is_doc(data):
        # An old Word 97-2003 file: read into the parts of a .docx first.
        try:
            data = specs_doc.to_docx(data)
        except (specs_doc.DocError, struct.error, IndexError, KeyError) as exc:
            raise SpecError(f"That .doc could not be read ({exc}). Save it as .docx in Word "
                            "and read that in instead.") from exc
    try:
        z = zipfile.ZipFile(BytesIO(data))
        root = ET.fromstring(z.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise SpecError("That is not a Word document (.doc or .docx) this can read.") from exc
    style_names = _styles(z)
    hidden_styles = _hidden_styles(z)
    body = root.find(W + "body")
    if body is None:
        raise SpecError("That Word document has no body to read.")

    number_, title = "", ""
    nbs = False
    nodes: list[dict] = []
    # How deep the last paragraph that said where it sat went. A list that
    # is not the specification's own hangs one level under it.
    anchor = -1
    spec_list = _spec_list(z)
    for el in body:
        if el.tag == W + "tbl":
            rows = []
            for tr in el.iter(W + "tr"):
                cells = [_paragraph_text(tc, hidden_styles).replace("|", "/")
                         for tc in tr.findall(W + "tc")]
                if any(cells):
                    rows.append("| " + " | ".join(cells) + " |")
            if rows:
                nodes.append(node(TABLE, "\n".join(rows)))
            continue
        if el.tag != W + "p":
            continue
        ppr = el.find(W + "pPr")
        ps = ppr.find(W + "pStyle") if ppr is not None else None
        style_id = (ps.get(W + "val") or "") if ps is not None else ""
        text, hidden = _texts(el, hidden_styles, style_id in hidden_styles)
        if not text and not hidden:
            continue
        if not text:
            # Word hides the whole paragraph: keep it, but as a note that is never issued.
            nodes.append(node(NOTE, hidden))
            continue
        ilvl, num = None, ""
        if ppr is not None:
            lv = ppr.find(f"{W}numPr/{W}ilvl")
            ni = ppr.find(f"{W}numPr/{W}numId")
            ilvl = int(lv.get(W + "val")) if lv is not None and (lv.get(W + "val") or "").isdigit() else None
            num = ni.get(W + "val", "") if ni is not None else ""
        style = style_names.get(style_id, style_id).strip().lower()
        kind = STYLE_LEVEL.get(style)
        if not number_ and not nodes and style in ("heading 1", "title") and NBS_LINE.match(text):
            # An NBS section: headings for its groups and clauses, lists under them.
            m = NBS_LINE.match(text)
            number_, title, nbs = m.group(1), m.group(2).strip(), True
            continue
        if nbs:
            if style == "heading 2":
                kind = "PRT"
            elif style == "heading 3":
                kind = "ART" if CLAUSE.match(text) else "PR1"
            elif style == "heading 1":
                kind = "PRT"
            elif ilvl is not None and kind is None:
                kind = LEVELS[min(DEPTH["PR1"] + ilvl, DEPTH["PR4"])]
            elif kind is None:
                kind = "PR1"
            if kind in ("PRT", "ART"):
                text = text.rstrip(":").strip()
                text = text.upper() if kind == "PRT" else text
            nodes.append(node(kind, text))
            if hidden:
                nodes.append(node(NOTE, f"Hidden in Word: {hidden}"))
            continue
        if kind in ("PRT", "ART") and num and not spec_list:
            spec_list = num

        if kind == "SCT" or (not number_ and SECTION_LINE.match(text)):
            m = SECTION_LINE.match(text)
            if m:
                number_, title = m.group(1).strip(), m.group(2).strip()
            else:
                title = title or text
            continue
        if kind == "EOS" or END_LINE.match(text):
            continue
        if kind == NOTE:
            nodes.append(node(NOTE, " ".join(x for x in (text, hidden) if x)))
            continue

        part = PART_LINE.match(text)
        if part:
            kind, text = "PRT", part.group(1)
        else:
            for pattern, level in MANUAL:
                m = pattern.match(text)
                if not m:
                    continue
                # A typed number wins over a paragraph style when it goes deeper,
                # which is how "1. Demonstrate compliance" typed into a PR1
                # becomes the list under it that it was meant to be.
                if kind == level or (kind == "ART" and level == "ART"):
                    text = m.group(1)
                elif kind in ("PRT", "ART"):
                    pass
                elif kind is None or level == "ART" or DEPTH[level] > DEPTH.get(kind, -1):
                    kind, text = level, m.group(1)
                break
        listed = False
        heading = (len(text) <= 60 and text.upper() == text and not text.endswith(".")
                   and any(c.isalpha() for c in text))
        if kind is None and ilvl is not None and num and num == spec_list and ilvl in ILVL_LEVEL:
            kind = ILVL_LEVEL[ilvl]
        if kind is None and heading:
            kind = "ART"
        if kind is None and ilvl is not None:
            depth = min(max(anchor + 1, DEPTH["PR1"]) + (ilvl if ilvl < 3 else 0), DEPTH["PR4"])
            kind, listed = LEVELS[depth], True
        if kind is None:
            kind = LEVELS[anchor] if anchor >= DEPTH["PR1"] else "PR1"
        if kind in ("PRT", "ART"):
            text = text.rstrip(":").strip().upper()
        nodes.append(node(kind, text))
        if hidden:
            # Words Word hides inside a paragraph it shows stay out of the issue too.
            nodes.append(node(NOTE, f"Hidden in Word: {hidden}"))
        if kind in DEPTH and not listed:
            anchor = DEPTH[kind]

    if not number_ and not nodes:
        raise SpecError("Nothing in that document reads as a specification section.")
    return {"number": number_, "title": title.upper(), "nodes": nodes}


def number_from_filename(name: str) -> str:
    """"SPC-FD-032000-ST.docx" is section 032000; "STD15A_SPC_071352.13_ST_..." is
    071352.13; "STD03A_SPC_J30A_ST_..." is the NBS section J30A."""
    name = re.sub(r"(?i)STD\d{2}[A-Z]\d*", "", name or "")
    m = re.search(r"(?<![\d.])(\d{5,6}(?:\.\d{2})?)(?![\d])", name)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|[_\- ])([A-Z]\d{2}[A-Z]?)(?=[_\- .]|$)", name)
    return m.group(1) if m else ""


# The office's kinds of specification are named in its files: "STD15A_SPC_..."
# or a document code such as "...-SPC-16A-ST-01".
FAMILY_MARK = re.compile(r"(?:STD|SPC[-_])(\d{2}A)(?=[\d_\-])", re.I)


def family_from_filename(name: str) -> str:
    m = FAMILY_MARK.search(name or "")
    return m.group(1).upper() if m else ""


# --- writing a Word document --------------------------------------------------

def _x(text: str) -> str:
    return escape(text or "", {'"': "&quot;"})


def _run(text: str, props: str = "") -> str:
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{_x(text)}</w:t></w:r>'


def _field(instruction: str, shown: str, props: str) -> str:
    rpr = f"<w:rPr>{props}</w:rPr>"
    return (f'<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r>{rpr}<w:instrText xml:space="preserve"> {instruction} </w:instrText></w:r>'
            f'<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r>{rpr}<w:t>{shown}</w:t></w:r>'
            f'<w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r>')


def template_info(data: bytes) -> dict:
    """What a house template is: whether it opens, and how it numbers.

    The list a MasterSpec template numbers its paragraphs with is found from
    the paragraphs in it that use it, or failing that from the ART style; and
    the list level of each style likewise, falling back to the standard ones.
    """
    try:
        z = zipfile.ZipFile(BytesIO(data))
        document = z.read("word/document.xml").decode("utf-8")
        styles = z.read("word/styles.xml").decode("utf-8") if "word/styles.xml" in z.namelist() else ""
    except (zipfile.BadZipFile, KeyError, UnicodeDecodeError) as exc:
        raise SpecError("That is not a Word document (.docx) this can use.") from exc

    names = {sid: name for sid, name in re.findall(
        r'<w:style [^>]*w:styleId="([^"]+)"[^>]*>\s*<w:name w:val="([^"]+)"', styles)}
    ids = {name.upper(): sid for sid, name in names.items()}
    missing = [level for level in ("SCT", "PRT", "ART", "PR1", "PR2", "PR3")
               if level not in ids]
    nbs = [ids.get(h) for h in ("HEADING 1", "HEADING 2", "HEADING 3", "LIST PARAGRAPH")]
    if missing and all(nbs):
        # An NBS template (the British sections): headings for the title, the
        # groups and the clauses, and one bulleted list under them.
        listed = re.search(r'<w:pStyle w:val="%s"/>(?:(?!</w:pPr>).)*?<w:numId w:val="(\d+)"/>'
                           % re.escape(nbs[3]), document, re.S)
        return {"layout": "nbs", "num_id": listed.group(1) if listed else "",
                "styles": {"SCT": nbs[0], "PRT": nbs[1], "ART": nbs[2], "PR1": nbs[3],
                           "PR2": nbs[3], "PR3": nbs[3], "PR4": nbs[3]},
                "ilvl": {"PRT": 0, "ART": 0, "PR1": 0, "PR2": 1, "PR3": 2, "PR4": 2}}
    if missing:
        raise SpecError("That template does not have the specification styles in it "
                        f"({', '.join(missing)} are missing). Upload a section that "
                        "was written in the MasterSpec styles.")

    ilvl: dict[str, int] = {}
    num_id = ""
    for style_id, level, num in re.findall(
            r'<w:pStyle w:val="([^"]+)"/>(?:(?!</w:pPr>).)*?<w:numPr><w:ilvl w:val="(\d+)"/>'
            r'<w:numId w:val="(\d+)"/>', document, re.S):
        name = names.get(style_id, style_id).upper()
        if name in STANDARD_ILVL and num != "0":
            ilvl.setdefault(name, int(level))
            num_id = num_id or num
    if not num_id:
        art = re.search(r'<w:style [^>]*w:styleId="%s".*?</w:style>' % re.escape(ids["ART"]),
                        styles, re.S)
        found = re.search(r'<w:numId w:val="(\d+)"/>', art.group(0)) if art else None
        num_id = found.group(1) if found else ""
    levels = {name: ilvl.get(name, STANDARD_ILVL[name]) for name in STANDARD_ILVL}
    return {"layout": "masterspec", "styles": ids, "num_id": num_id, "ilvl": levels}


HIGHLIGHT = '<w:highlight w:val="yellow"/>'


def _runs(text: str, props: str = "") -> str:
    """The words as runs, what is still to be specified highlighted."""
    out, last = [], 0
    for m in OPEN.finditer(text):
        if m.start() > last:
            out.append(_run(text[last:m.start()], props))
        out.append(_run(m.group(0), props + HIGHLIGHT))
        last = m.end()
    if last < len(text) or not out:
        out.append(_run(text[last:], props))
    return "".join(out)


def _paragraph(style_id: str, text: str, num: tuple[str, int] | None = None) -> str:
    numpr = (f'<w:numPr><w:ilvl w:val="{num[1]}"/><w:numId w:val="{num[0]}"/></w:numPr>'
             if num and num[0] else "")
    return f'<w:p><w:pPr><w:pStyle w:val="{style_id}"/>{numpr}</w:pPr>{_runs(text)}</w:p>'


def _table(text: str, indent: int, room: int = 9026) -> str:
    rows = rows_of(text)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    column = max((room - indent) // width, 400)
    border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                     for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join(f'<w:gridCol w:w="{column}"/>' for _ in range(width))
    # tblPr's children in the schema's order: width, indent, borders, layout.
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{column * width}" w:type="dxa"/><w:tblInd w:w="{indent}" w:type="dxa"/>'
           f'<w:tblBorders>{border}</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{grid}</w:tblGrid>']
    for row in rows:
        cells = row + [""] * (width - len(row))
        props = '<w:sz w:val="20"/>'
        out.append("<w:tr>" + "".join(
            f'<w:tc><w:tcPr><w:tcW w:w="{column}" w:type="dxa"/></w:tcPr>'
            f'<w:p><w:pPr><w:spacing w:before="40" w:after="40"/></w:pPr>'
            f"{_run(cell, props)}</w:p></w:tc>" for cell in cells) + "</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def _text_width(document: str) -> int:
    size = re.search(r'<w:pgSz [^>]*w:w="(\d+)"', document)
    left = re.search(r'<w:pgMar [^>]*w:left="(\d+)"', document)
    right = re.search(r'<w:pgMar [^>]*w:right="(\d+)"', document)
    if size and left and right:
        return int(size.group(1)) - int(left.group(1)) - int(right.group(1))
    return 9026


def _header_xml(root_open: str, closing: str, lines: Sequence[tuple[str, str]], width: int) -> str:
    props = '<w:color w:val="000000"/><w:sz w:val="20"/>'
    out = []
    for i, (left, right) in enumerate(lines):
        border = ('<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="1" w:color="000000"/></w:pBdr>'
                  if i == len(lines) - 1 else "")
        tabs = f'<w:tabs><w:tab w:val="right" w:pos="{width}"/></w:tabs>'
        body = _run(left, props)
        if right:
            body += f"<w:r><w:rPr>{props}</w:rPr><w:tab/></w:r>" + _run(right, props)
        out.append(f'<w:p><w:pPr><w:pStyle w:val="Normal"/>{border}{tabs}'
                   f"<w:rPr>{props}</w:rPr></w:pPr>{body}</w:p>")
    if not out:
        out.append('<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr></w:p>')
    return root_open + "".join(out) + closing


def _footer_xml(root_open: str, closing: str, title: str, number_: str, code_line: str,
                width: int) -> str:
    props = '<w:sz w:val="18"/><w:szCs w:val="18"/>'
    tabs = f'<w:tabs><w:tab w:val="right" w:pos="{width}"/></w:tabs>'
    first = (f'<w:p><w:pPr><w:pStyle w:val="Normal"/><w:pBdr><w:top w:val="single" w:sz="4" '
             f'w:space="0" w:color="000000"/></w:pBdr>{tabs}<w:rPr>{props}</w:rPr></w:pPr>'
             + _run(title, props) + f"<w:r><w:rPr>{props}</w:rPr><w:tab/></w:r>"
             + _run(f"{number_} - Page ", props) + _field("PAGE", "1", props)
             + _run(" of ", props) + _field("NUMPAGES \\* ARABIC", "1", props) + "</w:p>")
    second = (f'<w:p><w:pPr><w:pStyle w:val="Normal"/>{tabs}<w:rPr>{props}</w:rPr></w:pPr>'
              + _run(code_line, props) + "</w:p>") if code_line else ""
    return root_open + first + second + closing


def _part_root(xml: str, tag: str) -> tuple[str, str]:
    m = re.match(r"(.*?<w:%s(?: [^>]*)?>)" % tag, xml, re.S)
    if not m:
        raise SpecError("The template's header or footer cannot be read.")
    return m.group(1), f"</w:{tag}>"


def _targets(z: zipfile.ZipFile, document: str) -> tuple[str | None, str | None]:
    """The header and footer parts the document's last page layout uses."""
    try:
        rels = z.read("word/_rels/document.xml.rels").decode("utf-8")
    except KeyError:                                   # a bare package: no header or footer
        return None, None
    sect = document[document.rfind("<w:sectPr"):]
    found = []
    for kind in ("header", "footer"):
        ref = re.search(r'<w:%sReference [^>]*w:type="default"[^>]*r:id="([^"]+)"' % kind, sect) \
            or re.search(r'<w:%sReference [^>]*r:id="([^"]+)"[^>]*w:type="default"' % kind, sect)
        target = None
        if ref:
            rel = re.search(r'<Relationship [^>]*Id="%s"[^>]*Target="([^"]+)"' % re.escape(ref.group(1)), rels) \
                or re.search(r'<Relationship [^>]*Target="([^"]+)"[^>]*Id="%s"' % re.escape(ref.group(1)), rels)
            if rel:
                target = "word/" + rel.group(1).lstrip("/").removeprefix("word/")
        found.append(target)
    return found[0], found[1]


def write_docx(section: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]],
               project: Mapping[str, Any], chosen: Mapping[str, str],
               values: Mapping[str, str], template: bytes | None = None,
               resolve: Callable[[str], str] | None = None, marked: bool = True) -> bytes:
    """One section as a Word document in the house template.

    ``section`` carries ``number``, ``title`` and ``doc_code``; ``project``
    the header lines and revision. What is written is what applies to this
    project, variables filled in, notes left out, numbered by Word's own list
    so the numbers stay right when somebody edits the issued file.
    ``resolve`` turns the text as kept into the text as issued — the
    cross-references written out and the standards put on the project's
    basis — before the variables are filled.
    """
    data = template or TEMPLATE.read_bytes()
    info = template_info(data)
    styles, num_id, ilvl = info["styles"], info["num_id"], info["ilvl"]
    z = zipfile.ZipFile(BytesIO(data))
    document = z.read("word/document.xml").decode("utf-8")

    number_ = section.get("number", "")
    title = (section.get("title") or "").upper()
    room = _text_width(document)
    body: list[str] = []
    sct = styles["SCT"]
    nbs = info.get("layout") == "nbs"
    body.append(f'<w:p><w:pPr><w:pStyle w:val="{sct}"/></w:pPr>'
                + ("" if nbs else _run("SECTION ")) + _run(number_) + _run(" - ") + _run(title)
                + "</w:p>")
    for n in number(nodes, chosen):
        if not n["included"] or n["level"] == NOTE:
            continue
        text = fill(resolve(n["text"]) if resolve else choose(n["text"], chosen), values, marked)
        if n["level"] == TABLE:
            body.append(_table(text, 576 * (n["indent"] + 1), room))
            continue
        # An NBS group or clause heading carries its own number, typed.
        listed = not (nbs and n["level"] in ("PRT", "ART"))
        body.append(_paragraph(styles[n["level"]] if n["level"] in styles else styles["PR1"],
                               text, (num_id, ilvl[n["level"]]) if listed else None))
    if not nbs:
        eos = styles.get("EOS", sct)
        body.append(_paragraph(eos, f"END OF SECTION {number_}"))

    start = document.index("<w:body>") + len("<w:body>")
    sect = document.rindex("<w:sectPr")
    document = document[:start] + "".join(body) + document[sect:]
    width = _text_width(document)

    header_part, footer_part = _targets(z, document)
    left = [line.rstrip() for line in (project.get("header_left") or "").splitlines()]
    right = [line.rstrip() for line in (project.get("header_right") or "").splitlines()]
    lines = [(left[i] if i < len(left) else "", right[i] if i < len(right) else "")
             for i in range(max(len(left), len(right)))]
    revision = str(project.get("revision") or "").strip()
    code = (section.get("doc_code") or project.get("doc_code") or "").strip()
    code_line = " ".join(bit for bit in (code, f"REV {revision}" if revision != "" else "") if bit)

    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in z.infolist():
            name = item.filename
            content = z.read(name)
            if name == "word/document.xml":
                content = document.encode("utf-8")
            elif name == header_part:
                opened, closing = _part_root(content.decode("utf-8"), "hdr")
                content = _header_xml(opened, closing, lines, width).encode("utf-8")
            elif name == footer_part:
                opened, closing = _part_root(content.decode("utf-8"), "ftr")
                content = _footer_xml(opened, closing, title, number_, code_line, width).encode("utf-8")
            elif name in EDITABLE_PARTS:
                content = editable(name, content)
            elif name == "docProps/core.xml":
                content = re.sub(r"<dc:title>.*?</dc:title>|<dc:title/>",
                                 f"<dc:title>{_x(f'SECTION {number_} - {title}')}</dc:title>",
                                 content.decode("utf-8"), flags=re.S).encode("utf-8")
            target.writestr(item, content)
    return out.getvalue()


EDITABLE_PARTS = ("word/settings.xml", "[Content_Types].xml")


def editable(name: str, content: bytes) -> bytes:
    """A part of the issued file with nothing that stops it being edited: no
    document protection, no read-only recommendation, and a Word document
    rather than a template (a house template saved as .dotx stays one)."""
    text = content.decode("utf-8")
    if name == "word/settings.xml":
        text = re.sub(r"<w:(?:documentProtection|writeProtection)\b[^>]*/>", "", text)
        text = re.sub(r"<w:(?:documentProtection|writeProtection)\b.*?</w:(?:documentProtection|writeProtection)>",
                      "", text, flags=re.S)
    else:
        text = re.sub(r"wordprocessingml\.template\.main\+xml|ms-word\.(?:document|template)\.macroEnabled(?:Template)?\.main\+xml",
                      "wordprocessingml.document.main+xml", text)
    return text.encode("utf-8")


def file_name(pattern: str, section: Mapping[str, Any]) -> str:
    """What an issued section is called: the project's pattern, filled in."""
    pattern = pattern or "SPC-{number}"
    name = pattern.replace("{number}", section.get("number", "")).replace(
        "{title}", section.get("title", ""))
    name = re.sub(r'[\\/:*?"<>|]+', "-", name).strip() or "section"
    return name + ".docx"
