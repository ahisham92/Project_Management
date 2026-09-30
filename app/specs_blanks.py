"""The blanks a project still has to fill: MasterSpec's choices left in
[square brackets] and its <Insert ...> places, found in the project's own
copy of each section and filled in there.

A run of brackets side by side is one blank with several answers to pick
from: "[Project site] <Insert location>" is either the words "Project site"
or a location typed in. The answer is written into the paragraph in place of
the whole run, so the project's text says it (and shows as an amendment to
the master, which it is).
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping

from . import specs

# One bracketed choice, or one <Insert ...> place.
PIECE = r"(?:\[[^\[\]{}]{1,300}\]|<[^<>{}]{2,120}>)"
# A run of them with only spaces, "or" and commas between.
RUN = re.compile(PIECE + r"(?:(?:\s*,?\s*(?:or\s+)?)" + PIECE + r")*")
FREE = re.compile(r"^(?:insert|enter|specify|state|provide|add)\b", re.I)
FIELD = re.compile(r"\{[^{}]*\}")


def pieces(run: str) -> list[dict]:
    """The answers a run offers: each bracketed choice, and a place to type
    for each <Insert ...> or [Insert ...]."""
    out = []
    for m in re.finditer(PIECE, run):
        inner = m.group(0)[1:-1].strip()
        free = m.group(0).startswith("<") or bool(FREE.match(inner))
        out.append({"text": inner, "free": free})
    return out


def _key(row_id: int, node_id: str, run: str, nth: int) -> str:
    return hashlib.sha1(f"{row_id}\x01{node_id}\x01{run}\x01{nth}".encode()).hexdigest()[:12]


def _runs(text: str) -> list[re.Match]:
    """The runs in a paragraph, leaving out anything inside a field such as
    {ref:...} or a choice {key=value: ...}."""
    fields = [(m.start(), m.end()) for m in FIELD.finditer(text)]
    return [m for m in RUN.finditer(text)
            if not any(a <= m.start() < b for a, b in fields)]


def find(sections: Iterable[Mapping[str, Any]], chosen: Mapping[str, str]) -> list[dict]:
    """Every blank in the paragraphs a project issues, section by section."""
    out = []
    for s in sections:
        nodes = specs.loads(s["body"])
        for n in specs.number(nodes, chosen):
            if not n["included"] or n["level"] in (specs.NOTE, specs.TABLE):
                continue
            seen: dict[str, int] = {}
            for m in _runs(n["text"]):
                run = m.group(0)
                nth = seen.get(run, 0)
                seen[run] = nth + 1
                out.append({
                    "key": _key(s["id"], n["id"], run, nth), "row_id": s["id"],
                    "number": s["number"], "title": s["title"], "node_id": n["id"],
                    "label": n["label"], "path": n["path"], "article": n.get("article", ""),
                    "run": run, "nth": nth, "text": n["text"], "start": m.start(), "end": m.end(),
                    "options": pieces(run),
                })
    return out


def fill(text: str, run: str, nth: int, answer: str) -> str:
    """The paragraph with the nth copy of that run replaced by the answer."""
    count = 0
    for m in _runs(text):
        if m.group(0) != run:
            continue
        if count == nth:
            answer = " ".join((answer or "").split())
            before, after = text[:m.start()], text[m.end():]
            if not answer:
                # Left blank on purpose: the run goes, and the space before it.
                before = before.rstrip() if after[:1] in (".", ",", ";", ":", ")", "") else before
                if before.endswith(" ") and after.startswith(" "):
                    after = after[1:]
            return before + answer + after
        count += 1
    return text
