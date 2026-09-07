"""Filling a Word document that somebody else wrote.

The issued minutes are laid out in code, which is fine until the practice moves
a column, changes a colour or adds a line to the signature block — and then it
is a change to the software, made by somebody who is not in the room. So the
layout can come from a `.docx` instead: download the template, open it in Word,
change whatever you like, upload it back, and every export is built by filling
it in.

**A placeholder is `{{name}}`.** `{{meeting.ref}}` in the template becomes the
meeting's reference. Anything that is not a placeholder is left exactly as it
was — fonts, colours, margins, the letterhead, the footer, the lot.

**A table row that carries a row placeholder repeats.** A row with
`{{item.subject}}` in it is written once per item; a row with
`{{attendee.name}}` once per person. Everything else in the table — the
headings, the shading, the widths — is the template's.

Two things are worth knowing about Word. It splits a line of text into runs
wherever it feels like it, so `{{meeting.ref}}` typed by hand can arrive as
`{{meet`, `ing.`, `ref}}`; every paragraph holding a `{{` is therefore joined
back into one run before anything is substituted, which means **a paragraph
with a placeholder in it takes the formatting of its first run**. Keep a
placeholder in a cell or a paragraph of its own and that is not a constraint
anybody notices. And a template is a document like any other: if it will not
open in Word, it will not open here either, so it is checked on the way in.
"""

from __future__ import annotations

import re
import zipfile
from io import BytesIO
from typing import Any, Iterable, Mapping, Sequence
from xml.sax.saxutils import escape

# The parts a template's text can live in. The body is the document; the header
# and footer carry the letterhead and the form code, and people put the project
# name in them, so they are filled too.
PARTS = ("word/document.xml", "word/header1.xml", "word/header2.xml",
         "word/header3.xml", "word/footer1.xml", "word/footer2.xml", "word/footer3.xml")

TOKEN = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
PARAGRAPH = re.compile(r"<w:p(?: [^>]*)?>.*?</w:p>|<w:p(?: [^>]*)?/>", re.S)
ROW = re.compile(r"<w:tr(?: [^>]*)?>.*?</w:tr>", re.S)
RUN = re.compile(r"<w:r(?: [^>]*)?>.*?</w:r>", re.S)
TEXT = re.compile(r"<w:t(?: [^>]*)?>(.*?)</w:t>", re.S)
BREAK = re.compile(r"<w:br\s*/>|<w:tab\s*/>")
PROPS = re.compile(r"<w:rPr>.*?</w:rPr>", re.S)


class TemplateError(ValueError):
    """A template that cannot be used, said in words."""


def is_docx(data: bytes) -> bool:
    """Whether these bytes are a Word document this can fill in."""
    if not data or data[:2] != b"PK":
        return False
    try:
        with zipfile.ZipFile(BytesIO(data)) as book:
            return "word/document.xml" in book.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def check(data: bytes) -> None:
    """Raises if the upload is not a Word document."""
    if not is_docx(data):
        raise TemplateError(
            "That is not a Word document. Download the template, change it in "
            "Word, save it as .docx and upload that.")


def placeholders(data: bytes) -> set[str]:
    """Every `{{name}}` the template asks for — what it will actually fill in.

    Read from the joined text of each paragraph rather than run by run, so a
    placeholder Word has split up still counts.
    """
    found: set[str] = set()
    try:
        with zipfile.ZipFile(BytesIO(data)) as book:
            inside = set(book.namelist())
            for part in PARTS:
                if part not in inside:
                    continue
                xml = book.read(part).decode("utf-8", "replace")
                for paragraph in PARAGRAPH.findall(xml):
                    found.update(TOKEN.findall(_words(paragraph)))
    except (zipfile.BadZipFile, OSError):
        return set()
    return found


# --- filling one in ---------------------------------------------------------

def fill(template: bytes, values: Mapping[str, Any],
         rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None) -> bytes:
    """The template with its placeholders replaced, as a .docx.

    `values` fills `{{name}}` anywhere. `rows` is keyed by the prefix a
    repeating row uses — `{"item": [...], "attendee": [...]}` — and each entry
    is one row's worth of fields under that prefix.
    """
    check(template)
    rows = rows or {}

    out = BytesIO()
    with zipfile.ZipFile(BytesIO(template)) as book, \
            zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as made:
        inside = set(book.namelist())
        for name in book.namelist():
            data = book.read(name)
            if name in PARTS and name in inside:
                xml = data.decode("utf-8", "replace")
                xml = _joined(xml)
                xml = _repeated(xml, rows)
                xml = _substituted(xml, values)
                data = xml.encode("utf-8")
            made.writestr(name, data)
    return out.getvalue()


def _words(fragment: str) -> str:
    """The readable text of a fragment of Word XML, breaks and all."""
    return "".join(TEXT.findall(BREAK.sub("\n", fragment)))


def _joined(xml: str) -> str:
    """Every paragraph holding a placeholder, rewritten as one run.

    Word splits a line into runs wherever it likes, so a placeholder typed by
    hand can arrive in three pieces. Joining first is what makes a template
    somebody has actually edited work.
    """
    def one(match: re.Match) -> str:
        paragraph = match.group(0)
        if "{{" not in _words(paragraph):
            return paragraph
        runs = RUN.findall(paragraph)
        if len(runs) < 2:
            return paragraph
        joined = "".join(_words(run) for run in runs)
        first = runs[0]
        look = PROPS.search(first)
        rebuilt = (f'<w:r>{look.group(0) if look else ""}'
                   f'<w:t xml:space="preserve">{escape(joined)}</w:t></w:r>')
        # The first run becomes the whole line; the rest go.
        seen = False
        parts = []
        at = 0
        for run in RUN.finditer(paragraph):
            parts.append(paragraph[at:run.start()])
            if not seen:
                parts.append(rebuilt)
                seen = True
            at = run.end()
        parts.append(paragraph[at:])
        return "".join(parts)

    return PARAGRAPH.sub(one, xml)


def _repeated(xml: str, rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    """Table rows that carry a row placeholder, written once per entry.

    A row asking for nothing — every entry gone, or a prefix nobody passed — is
    left alone rather than deleted: a template that empties itself when a
    meeting has no items is worse than one with a blank row in it.
    """
    for prefix, entries in rows.items():
        marker = "{{" + prefix + "."

        def one(match: re.Match, prefix=prefix, entries=entries, marker=marker) -> str:
            row = match.group(0)
            if marker not in _words(row).replace(" ", ""):
                return row
            if not entries:
                return ""
            return "".join(
                _substituted(row, {f"{prefix}.{key}": value
                                   for key, value in entry.items()})
                for entry in entries)

        xml = ROW.sub(one, xml)
    return xml


def _substituted(xml: str, values: Mapping[str, Any]) -> str:
    """`{{name}}` replaced wherever it appears, once the runs are joined."""
    def one(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            return match.group(0)             # not ours: leave it as it stands
        return _run_text(values[name])

    return TOKEN.sub(one, xml)


def _run_text(value: Any) -> str:
    """One value, as it goes inside a `<w:t>`.

    A line break in a discussion has to become a real break rather than the
    two characters `\\n`, which Word draws as nothing at all.
    """
    words = str(value if value is not None else "")
    lines = words.split("\n")
    if len(lines) == 1:
        return escape(words)
    joined = '</w:t><w:br/><w:t xml:space="preserve">'
    return joined.join(escape(line) for line in lines)


def used_by(rows: Iterable[str]) -> str:
    """A readable list of placeholders, for the page that explains them."""
    return ", ".join("{{" + name + "}}" for name in sorted(rows))
