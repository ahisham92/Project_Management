"""Turning what Carmen writes into what the chat shows.

She answers in plain text with a little Markdown in it, because that is what a
language model writes when it is asked for a list of deliverables and their
dates. A table typed as pipes and dashes and then drawn as pipes and dashes is
unreadable — the whole point of a table is that the columns line up.

So this is the one place the conversion happens, on the server, for both the
answer that arrives live and the answer read back out of a saved conversation.
Two implementations of the same thing is how a chat ends up looking different
depending on whether you have just asked the question or come back to it.

Everything is escaped first and built as tags afterwards, so nothing a model
writes — or anything quoted into it out of a document somebody attached — can
put markup on the page.
"""

from __future__ import annotations

import re
from typing import Iterable
from xml.sax.saxutils import escape

from markupsafe import Markup

BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
CODE = re.compile(r"`([^`]+)`")
BULLET = re.compile(r"^\s*[-*•]\s")
NUMBERED = re.compile(r"^\s*\d+[.)]\s")
# A row of pipes. The leading and trailing ones are optional, because half the
# world writes them and half does not.
ROW = re.compile(r"^\s*\|?(.+?)\|?\s*$")
RULE = re.compile(r"^[\s|:-]+$")


def to_html(text: str) -> Markup:
    """One answer, as the chat draws it."""
    lines = str(text or "").replace("\r\n", "\n").split("\n")
    out: list[str] = []
    at = 0
    while at < len(lines):
        line = lines[at]
        if not line.strip():
            at += 1
            continue

        if _is_table(lines, at):
            table, at = _table(lines, at)
            out.append(table)
            continue

        block, at = _block(lines, at)
        out.append(block)
    return Markup("".join(out))


def _is_table(lines: list[str], at: int) -> bool:
    """A table is a row of pipes with a rule of dashes under it."""
    return (at + 1 < len(lines) and "|" in lines[at]
            and "|" in lines[at + 1] and bool(RULE.match(lines[at + 1]))
            and "-" in lines[at + 1])


def _cells(line: str) -> list[str]:
    inside = ROW.match(line)
    return [cell.strip() for cell in (inside.group(1) if inside else line).split("|")]


def _table(lines: list[str], at: int) -> tuple[str, int]:
    """The table starting here, and the line after it."""
    headers = _cells(lines[at])
    at += 2                                   # the header and the rule under it

    body: list[list[str]] = []
    while at < len(lines) and "|" in lines[at] and lines[at].strip():
        body.append(_cells(lines[at]))
        at += 1

    head = "".join(f"<th>{_words(cell)}</th>" for cell in headers)
    rows = []
    for row in body:
        # A short row is padded rather than dropped: a model that misses a
        # trailing empty cell should not cost the reader the whole line.
        filled = (row + [""] * len(headers))[:len(headers)]
        rows.append("<tr>" + "".join(f"<td>{_words(cell)}</td>" for cell in filled) + "</tr>")

    return (f'<div class="table-scroll chat-table"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>', at)


def _block(lines: list[str], at: int) -> tuple[str, int]:
    """One paragraph or list, and the line after it."""
    if BULLET.match(lines[at]) or NUMBERED.match(lines[at]):
        numbered = bool(NUMBERED.match(lines[at]))
        items: list[str] = []
        while at < len(lines) and (BULLET.match(lines[at]) or NUMBERED.match(lines[at])):
            stripped = (NUMBERED if numbered else BULLET).sub("", lines[at], count=1)
            items.append(f"<li>{_words(stripped)}</li>")
            at += 1
        tag = "ol" if numbered else "ul"
        return f'<{tag} class="guide-list">{"".join(items)}</{tag}>', at

    said: list[str] = []
    while at < len(lines) and lines[at].strip() and not _is_table(lines, at) \
            and not BULLET.match(lines[at]) and not NUMBERED.match(lines[at]):
        said.append(lines[at])
        at += 1
    return "<p>" + "<br>".join(_words(line) for line in said) + "</p>", at


def _words(text: str) -> str:
    """One run of text: escaped, then the little markup that is honoured."""
    safe = escape(str(text or ""))
    safe = BOLD.sub(r"<strong>\1</strong>", safe)
    return CODE.sub(r"<code>\1</code>", safe)


def as_text(blocks: Iterable[str]) -> str:
    """The other direction, for anything that wants the words back."""
    return "\n".join(str(block or "") for block in blocks)
