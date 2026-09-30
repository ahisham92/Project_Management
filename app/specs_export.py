"""A specification issued three ways: clean Word, Word with tracked changes, PDF.

**Clean Word** is :func:`app.specs.write_docx` — the house template, its
styles, header and footer — and stays the default.

**Word with tracked changes** is that same document, with every difference
from the master the project copied written as Word's own revisions, so the
Review pane lists them and Accept / Reject works on each. Both sides are
compared as issued — the same answers, the same references written out, the
same words filled in — so a paragraph the project's choices switch off is not
a deletion, and a reference is not a change just because it is written out.
A paragraph added reads as an insertion (its paragraph mark too), one dropped
as a deletion, one reworded as the words that changed within it, and one moved
to another level as a change of its paragraph formatting. A section the project
wrote itself, with no master behind it, is all insertion: every word of it is
the project's.

**PDF** draws the issued text on A4 in the house layout — SECTION heading,
PART headings, articles and paragraphs with hanging numbers (or the NBS
clauses and bullets), tables, END OF SECTION, the project's header lines and
the footer with the page of the section — with reportlab. A whole project is
one PDF, each section starting on a new page and numbered on its own.
"""

from __future__ import annotations

import difflib
import re
import zipfile
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from . import specs
from .specs import NOTE, TABLE, _run, _x

AUTHOR = "Specs Writer"
FORMATS = ("docx", "tracked", "pdf")

Resolve = Callable[[str], str] | None


def fmt_of(value: str | None) -> str:
    """The format asked for, or clean Word when it is anything else."""
    value = (value or "").strip().lower()
    return value if value in FORMATS else "docx"


def issued(text: str, chosen: Mapping[str, str], values: Mapping[str, str],
           resolve: Resolve = None) -> str:
    """A paragraph's words as they go out — exactly as write_docx writes them."""
    return specs.fill(resolve(text) if resolve else specs.choose(text, chosen), values)


def _heading(nbs: bool, number_: str, title: str) -> str:
    return ("" if nbs else "SECTION ") + f"{number_} - {title}"


# --- Word with tracked changes -----------------------------------------------------

class _Marks:
    """Revision attributes: one author, one time, ids unique in the document."""

    def __init__(self, author: str, when: datetime | None = None) -> None:
        self.author = _x(author or AUTHOR)
        stamp = (when or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.date = stamp.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.next = 900

    def attrs(self) -> str:
        self.next += 1
        return f'w:id="{self.next}" w:author="{self.author}" w:date="{self.date}"'

    def ins(self, text: str, props: str = "") -> str:
        return f"<w:ins {self.attrs()}>{_run(text, props)}</w:ins>" if text else ""

    def dele(self, text: str, props: str = "") -> str:
        if not text:
            return ""
        rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
        return (f'<w:del {self.attrs()}><w:r>{rpr}<w:delText xml:space="preserve">{_x(text)}'
                "</w:delText></w:r></w:del>")


TOKEN = re.compile(r"\w+|\s+|[^\w\s]", re.U)


def word_diff(old: str, new: str) -> list[tuple[str, str, str]]:
    """The two wordings as ``(kind, old, new)`` pieces: ``equal`` or ``change``.

    Words are compared whole, punctuation on its own. A space alone between two
    changes is folded into them, so "the red brick" to "a blue block" reads as
    one deletion and one insertion rather than a word-by-word stutter.
    """
    a, b = TOKEN.findall(old or ""), TOKEN.findall(new or "")
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    pieces: list[list[str]] = []
    for tag, i1, i2, j1, j2 in ops:
        pieces.append(["equal" if tag == "equal" else "change", "".join(a[i1:i2]), "".join(b[j1:j2])])
    merged: list[list[str]] = []
    k = 0
    while k < len(pieces):
        kind, o, n = pieces[k]
        if (kind == "equal" and not o.strip() and merged and merged[-1][0] == "change"
                and k + 1 < len(pieces) and pieces[k + 1][0] == "change"):
            merged[-1][1] += o
            merged[-1][2] += n
        elif kind == "change" and merged and merged[-1][0] == "change":
            merged[-1][1] += o
            merged[-1][2] += n
        else:
            merged.append([kind, o, n])
        k += 1
    return [(k_, o, n) for k_, o, n in merged]


def _diff_runs(old: str, new: str, marks: _Marks, props: str = "") -> str:
    out = []
    for kind, o, n in word_diff(old, new):
        if kind == "equal":
            out.append(_run(n, props))
        else:
            out.append(marks.dele(o, props) + marks.ins(n, props))
    return "".join(out)


class _Layout:
    """How the house template writes a level: its style and its list level."""

    def __init__(self, info: Mapping[str, Any]) -> None:
        self.styles, self.num_id, self.ilvl = info["styles"], info["num_id"], info["ilvl"]
        self.nbs = info.get("layout") == "nbs"

    def ppr(self, level: str) -> str:
        style = self.styles[level] if level in self.styles else self.styles["PR1"]
        listed = not (self.nbs and level in ("PRT", "ART"))
        numpr = (f'<w:numPr><w:ilvl w:val="{self.ilvl[level]}"/><w:numId w:val="{self.num_id}"/>'
                 "</w:numPr>" if listed and self.num_id else "")
        return f'<w:pStyle w:val="{style}"/>{numpr}'


def _para(layout: _Layout, level: str, runs: str, marks: _Marks, mark: str = "",
          was_level: str | None = None) -> str:
    """One paragraph; ``mark`` is ``ins`` or ``del`` for its paragraph mark, and
    ``was_level`` the level it had in the master when it has moved."""
    rpr = f"<w:rPr><w:{mark} {marks.attrs()}/></w:rPr>" if mark else ""
    change = (f"<w:pPrChange {marks.attrs()}><w:pPr>{layout.ppr(was_level)}</w:pPr></w:pPrChange>"
              if was_level and was_level != level else "")
    return f"<w:p><w:pPr>{layout.ppr(level)}{rpr}{change}</w:pPr>{runs}</w:p>"


def _tracked_table(old: str | None, new: str | None, indent: int, room: int, marks: _Marks) -> str:
    """A table with its rows marked: rows added, rows dropped, cells reworded.
    ``old`` None is a table added whole, ``new`` None one dropped whole."""
    a = specs.rows_of(old) if old is not None else []
    b = specs.rows_of(new) if new is not None else []
    rows: list[tuple[str, list[str], list[str]]] = []          # (mode, old cells, new cells)
    key = lambda r: "|".join(specs._norm(c) for c in r)          # noqa: E731
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, [key(r) for r in a], [key(r) for r in b], autojunk=False).get_opcodes():
        if tag == "equal":
            rows += [("same", a[i1 + k], b[j1 + k]) for k in range(i2 - i1)]
        elif tag == "replace" and i2 - i1 == j2 - j1:
            rows += [("diff", a[i1 + k], b[j1 + k]) for k in range(i2 - i1)]
        else:
            rows += [("del", r, []) for r in a[i1:i2]]
            rows += [("ins", [], r) for r in b[j1:j2]]
    if not rows:
        return ""
    width = max(max(len(o), len(n)) for _, o, n in rows)
    column = max((room - indent) // width, 400)
    border = "".join(f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
                     for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
    grid = "".join(f'<w:gridCol w:w="{column}"/>' for _ in range(width))
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{column * width}" w:type="dxa"/>'
           f'<w:tblInd w:w="{indent}" w:type="dxa"/><w:tblBorders>{border}</w:tblBorders>'
           '<w:tblLayout w:type="fixed"/></w:tblPr>'
           f"<w:tblGrid>{grid}</w:tblGrid>"]
    props = '<w:sz w:val="20"/>'
    for mode, o, n in rows:
        o = o + [""] * (width - len(o))
        n = n + [""] * (width - len(n))
        trpr = f"<w:trPr><w:{mode} {marks.attrs()}/></w:trPr>" if mode in ("ins", "del") else ""
        cells = []
        for co, cn in zip(o, n):
            if mode == "same":
                runs = _run(cn, props)
            elif mode == "ins":
                runs = marks.ins(cn, props)
            elif mode == "del":
                runs = marks.dele(co, props)
            else:
                runs = _diff_runs(co, cn, marks, props)
            mark = f"<w:rPr><w:ins {marks.attrs()}/></w:rPr>" if mode == "ins" else ""
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{column}" w:type="dxa"/></w:tcPr>'
                         f'<w:p><w:pPr><w:spacing w:before="40" w:after="40"/>{mark}</w:pPr>'
                         f"{runs}</w:p></w:tc>")
        out.append(f"<w:tr>{trpr}{''.join(cells)}</w:tr>")
    out.append("</w:tbl>")
    return "".join(out)


def revisions(base: Sequence[Mapping[str, Any]] | None, nodes: Sequence[Mapping[str, Any]],
              chosen: Mapping[str, str], values: Mapping[str, str],
              resolve: Resolve = None) -> list[dict]:
    """The paragraphs as issued, each marked against the master as issued.

    ``kind`` is ``same``, ``ins``, ``del`` or ``diff``; ``old`` and ``new`` are
    the issued words (``old_level`` / ``level`` the levels). Paragraphs neither
    side issues — notes, or ones the answers switch off on both sides — are not
    listed at all.
    """
    base = list(base or [])
    marked = specs.compare(base, nodes) if base else [dict(n, state="added", was=None) for n in nodes]
    in_old = {n["id"]: n["included"] for n in specs.number(base, chosen)} if base else {}
    in_new = {n["id"]: n["included"] for n in specs.number(nodes, chosen)}
    by_id = {n["id"]: n for n in base}
    out = []
    for m in marked:
        if m["level"] == NOTE:
            continue
        old_node = by_id.get(m["id"]) if m["state"] != "added" else None
        new_node = m if m["state"] != "removed" else None
        old_on = bool(old_node) and in_old.get(m["id"], False) and old_node["level"] != NOTE
        new_on = bool(new_node) and in_new.get(m["id"], False)
        if not old_on and not new_on:
            continue
        old_text = issued(old_node["text"], chosen, values, resolve) if old_on else None
        new_text = issued(new_node["text"], chosen, values, resolve) if new_on else None
        if old_on and new_on:
            kind = ("same" if old_text == new_text and old_node["level"] == new_node["level"]
                    else "diff")
        else:
            kind = "ins" if new_on else "del"
        out.append({"id": m["id"], "kind": kind,
                    "level": (new_node or old_node)["level"],
                    "old_level": old_node["level"] if old_node else None,
                    "old": old_text, "new": new_text,
                    "indent": 0})
    # Tables sit indented under the paragraph before them, as write_docx has them.
    indents = {n["id"]: n["indent"] for n in specs.number(nodes, chosen)}
    indents_old = {n["id"]: n["indent"] for n in specs.number(base, chosen)} if base else {}
    for r in out:
        r["indent"] = indents.get(r["id"], indents_old.get(r["id"], 0))
    return out


def _replace_body(docx: bytes, body: str) -> bytes:
    """The document with its body swapped, every other part as it was."""
    z = zipfile.ZipFile(BytesIO(docx))
    document = z.read("word/document.xml").decode("utf-8")
    start = document.index("<w:body>") + len("<w:body>")
    sect = document.rindex("<w:sectPr")
    document = document[:start] + body + document[sect:]
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in z.infolist():
            content = z.read(item.filename)
            if item.filename == "word/document.xml":
                content = document.encode("utf-8")
            target.writestr(item, content)
    return out.getvalue()


def write_tracked_docx(section: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]],
                       base: Sequence[Mapping[str, Any]] | None, project: Mapping[str, Any],
                       chosen: Mapping[str, str], values: Mapping[str, str],
                       template: bytes | None = None, resolve: Resolve = None,
                       author: str = "", when: datetime | None = None) -> tuple[bytes, int]:
    """The section as issued, in the house template, with every difference
    from its master as a Word revision. Returns the document and how many
    paragraphs carry a revision (0: it reads exactly as the master)."""
    clean = specs.write_docx(section, nodes, project, chosen, values, template, resolve=resolve)
    info = specs.template_info(template or specs.TEMPLATE.read_bytes())
    layout = _Layout(info)
    marks = _Marks(author, when)
    document = zipfile.ZipFile(BytesIO(clean)).read("word/document.xml").decode("utf-8")
    room = specs._text_width(document)

    number_ = section.get("number", "")
    title = (section.get("title") or "").upper()
    sct = layout.styles["SCT"]
    body = [f'<w:p><w:pPr><w:pStyle w:val="{sct}"/></w:pPr>'
            + ("" if layout.nbs else _run("SECTION ")) + _run(number_) + _run(" - ") + _run(title)
            + "</w:p>"]
    changed = 0
    for r in revisions(base, nodes, chosen, values, resolve):
        changed += r["kind"] != "same"
        if r["level"] == TABLE or r["old_level"] == TABLE:
            indent = 576 * (r["indent"] + 1)
            if r["kind"] == "same":
                body.append(specs._table(r["new"], indent, room))
            elif r["level"] != r["old_level"] and r["kind"] == "diff":
                # A table became a paragraph or the other way about: out, then in.
                body.append(_revised_as_two(r, layout, marks, indent, room))
            else:
                body.append(_tracked_table(r["old"], r["new"], indent, room, marks))
            continue
        if r["kind"] == "same":
            body.append(_para(layout, r["level"], _run(r["new"]), marks))
        elif r["kind"] == "ins":
            body.append(_para(layout, r["level"], marks.ins(r["new"]), marks, "ins"))
        elif r["kind"] == "del":
            body.append(_para(layout, r["old_level"], marks.dele(r["old"]), marks, "del"))
        else:
            body.append(_para(layout, r["level"], _diff_runs(r["old"], r["new"], marks), marks,
                              was_level=r["old_level"]))
    if not layout.nbs:
        body.append(specs._paragraph(layout.styles.get("EOS", sct), f"END OF SECTION {number_}"))
    return _replace_body(clean, "".join(body)), changed


def _revised_as_two(r: Mapping[str, Any], layout: _Layout, marks: _Marks, indent: int,
                    room: int) -> str:
    old = (_tracked_table(r["old"], None, indent, room, marks) if r["old_level"] == TABLE
           else _para(layout, r["old_level"], marks.dele(r["old"]), marks, "del"))
    new = (_tracked_table(None, r["new"], indent, room, marks) if r["level"] == TABLE
           else _para(layout, r["level"], marks.ins(r["new"]), marks, "ins"))
    return old + new


# --- PDF -----------------------------------------------------------------------------

PT = 1.0
TWIP = 1 / 20
INDENT = 576 * TWIP                    # one list step: 0.4 in
MARGIN = 72                            # 1 in, as the template's page
HEADER_FROM_EDGE = 36
FOOTER_FROM_EDGE = 36

# Where each level sits, as the template's numbering puts it: (text starts at,
# number starts at, size, space before) in points.
MASTERSPEC = {
    "SCT": (0, None, 12, 12), "PRT": (0, None, 12, 24), "ART": (43.2, 0, 12, 24),
    "PR1": (43.2, 14.4, 11, 12), "PR2": (72, 43.2, 11, 12), "PR3": (100.8, 72, 11, 12),
    "PR4": (129.6, 100.8, 12, 0), "EOS": (0, None, 12, 24),
}
NBS = {
    "SCT": (0, None, 12, 12), "PRT": (0, None, 12, 24), "ART": (0, None, 12, 12),
    "PR1": (43.2, 25.2, 11, 4.5), "PR2": (64.8, 46.8, 11, 1.5), "PR3": (86.4, 68.4, 11, 1.5),
    "PR4": (108, 90, 11, 1.5),
}
NBS_MARKS = {"PRT": "", "ART": "", "PR1": "\u2022", "PR2": "\u2013", "PR3": "\u00b7", "PR4": "\u00b7"}

# A serif face with the characters specifications use (≤ ≥ µ ± °), Times-like
# where there is one. Looked for on the machine; nothing is shipped with the app.
FONT_DIRS = ("/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/liberation2",
             "/usr/share/fonts/liberation", "/usr/share/fonts/truetype/dejavu",
             "/usr/share/fonts/dejavu", "/usr/share/fonts/truetype/freefont",
             "C:/Windows/Fonts", "/Library/Fonts", "/System/Library/Fonts/Supplemental")
FONT_FACES = (("LiberationSerif-Regular.ttf", "LiberationSerif-Bold.ttf"),
              ("times.ttf", "timesbd.ttf"),
              ("Times New Roman.ttf", "Times New Roman Bold.ttf"),
              ("DejaVuSerif.ttf", "DejaVuSerif-Bold.ttf"),
              ("FreeSerif.ttf", "FreeSerifBold.ttf"))

# What stands in for a character the font has not got.
STAND_IN = {"\u2264": "<=", "\u2265": ">=", "\u2260": "/=", "\u2248": "~", "\u2212": "-",
            "\u2192": "->", "\u2190": "<-", "\u221a": "sqrt", "\u2205": "dia.", "\u2300": "dia.",
            "\u2011": "-", "\u2010": "-", "\u2009": " ", "\u202f": " ", "\u2007": " ",
            "\u200b": "", "\u00ad": "", "\u2080": "0", "\u2081": "1", "\u2082": "2",
            "\u2083": "3", "\u2074": "4", "\u2070": "0", "\u2032": "'", "\u2033": '"',
            "\u2126": "Ohm", "\u03a9": "Ohm", "\u2030": " per mille", "\u221e": "infinity",
            "\u2022": "-", "\u2013": "-", "\u2014": "-", "\u2018": "'", "\u2019": "'",
            "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00b7": "."}


class ExportError(RuntimeError):
    """An export that could not be made, said in words."""


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str, frozenset | None]:
    """The regular and bold face names, and the characters they have (None:
    a standard PDF font, which has what Windows-1252 has)."""
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    for regular, bold in FONT_FACES:
        for folder in FONT_DIRS:
            r, b = Path(folder) / regular, Path(folder) / bold
            if r.is_file() and b.is_file():
                try:
                    face = TTFont("SpecSerif", str(r))
                    pdfmetrics.registerFont(face)
                    pdfmetrics.registerFont(TTFont("SpecSerif-Bold", str(b)))
                    pdfmetrics.registerFontFamily("SpecSerif", normal="SpecSerif",
                                                  bold="SpecSerif-Bold", italic="SpecSerif",
                                                  boldItalic="SpecSerif-Bold")
                except Exception:                   # a font that will not load: try the next
                    continue
                return "SpecSerif", "SpecSerif-Bold", frozenset(face.face.charToGlyph)
    return "Times-Roman", "Times-Bold", None


def _printable(text: str) -> str:
    """The text with anything the font cannot draw stood in for."""
    _, _, has = _fonts()
    out = []
    for ch in text or "":
        if ch in "\n\t":
            out.append(" ")
            continue
        ok = (ord(ch) in has) if has is not None else _cp1252(ch)
        out.append(ch if ok else STAND_IN.get(ch, "?"))
    return "".join(out)


def _cp1252(ch: str) -> bool:
    try:
        ch.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def _markup(text: str) -> str:
    return (_printable(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _header_lines(project: Mapping[str, Any]) -> list[tuple[str, str]]:
    left = [line.rstrip() for line in (project.get("header_left") or "").splitlines()]
    right = [line.rstrip() for line in (project.get("header_right") or "").splitlines()]
    return [(left[i] if i < len(left) else "", right[i] if i < len(right) else "")
            for i in range(max(len(left), len(right)))]


def _code_line(section: Mapping[str, Any], project: Mapping[str, Any]) -> str:
    revision = str(project.get("revision") or "").strip()
    code = (section.get("doc_code") or project.get("doc_code") or "").strip()
    return " ".join(bit for bit in (code, f"REV {revision}" if revision != "" else "") if bit)


def _section_flow(kit, section: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]],
                  chosen: Mapping[str, str], values: Mapping[str, str], resolve: Resolve,
                  nbs: bool, width: float) -> list:
    """One section's paragraphs as reportlab flowables."""
    Paragraph, ParagraphStyle = kit["Paragraph"], kit["ParagraphStyle"]
    regular, bold, _ = _fonts()
    places = NBS if nbs else MASTERSPEC
    justify = 0 if nbs else 4                         # TA_LEFT, TA_JUSTIFY

    def style(level: str, after: str | None) -> Any:
        left, mark, size, before = places.get(level, places["PR1"])
        if not nbs and level in ("PR2", "PR3") and after == level:
            before = 0                                # the template's contextual spacing
        if nbs and level in ("PR2", "PR3") and after == level:
            before = 1.5
        heading = nbs and level in ("SCT", "PRT", "ART")
        return ParagraphStyle(
            f"{level}-{before}", fontName=bold if heading else regular, fontSize=size,
            leading=round(size * 1.15, 2), leftIndent=left, firstLineIndent=0,
            bulletIndent=mark or 0, bulletFontName=regular, bulletFontSize=size,
            spaceBefore=before, alignment=0 if heading or level in ("SCT", "PRT", "EOS") else justify,
            keepWithNext=level in ("SCT", "PRT", "ART"), allowWidows=0, allowOrphans=0)

    number_ = section.get("number", "")
    title = (section.get("title") or "").upper()
    flow: list = [Paragraph(_markup(_heading(nbs, number_, title)), style("SCT", None))]
    previous: str | None = "SCT"
    typed_nbs = specs.is_nbs(nodes)
    for n in specs.number(nodes, chosen):
        if not n["included"] or n["level"] == NOTE:
            continue
        words = issued(n["text"], chosen, values, resolve)
        if n["level"] == TABLE:
            table = _table_flow(kit, words, n["indent"], width, regular)
            if table and flow:
                flow[-1].keepWithNext = True          # the words that lead into it go with it
            flow += table
            previous = TABLE
            continue
        label = n["label"] if (typed_nbs or not nbs) else NBS_MARKS[n["level"]]
        text = _markup(words)
        if n["level"] == "PRT" and label:
            text = f"{_markup(label)} {text}"
            label = ""
        if nbs and n["level"] == "PRT":
            text = text.upper()
        flow.append(Paragraph(text, style(n["level"], previous),
                              bulletText=_markup(label) if label else None))
        previous = n["level"]
    if not nbs:
        flow.append(Paragraph(_markup(f"END OF SECTION {number_}"), style("EOS", previous)))
    return flow


def _table_flow(kit, text: str, indent: int, width: float, font: str) -> list:
    """A table ruled in 10 pt, set in from the margin as far as its paragraph.

    The indent is a first column with no rules, which keeps the table one
    flowable, so the paragraph leading into it can be kept on its page."""
    rows = specs.rows_of(text)
    if not rows:
        return []
    Paragraph, ParagraphStyle = kit["Paragraph"], kit["ParagraphStyle"]
    cell = ParagraphStyle("cell", fontName=font, fontSize=10, leading=11.5)
    left = INDENT * min(indent + 1, 4)
    columns = max(len(r) for r in rows)
    each = (width - left) / columns
    data = [[""] + [Paragraph(_markup(c), cell) for c in r + [""] * (columns - len(r))]
            for r in rows]
    class Whole(kit["Table"]):
        """A short table is not cut: it goes over to the next page whole. (Not
        a KeepTogether, which would not chain with the paragraph before it.)"""

        def split(self, availWidth, availHeight):      # noqa: N803 - reportlab's names
            return [] if len(rows) <= 20 else super().split(availWidth, availHeight)

    table = Whole(data, colWidths=[left] + [each] * columns, hAlign="LEFT", spaceBefore=12)
    table.setStyle(kit["TableStyle"]([
        ("GRID", (1, 0), (-1, -1), 0.5, kit["colors"].black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.75), ("RIGHTPADDING", (0, 0), (-1, -1), 3.75),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return [table]


def write_pdf(items: Iterable[tuple[Mapping[str, Any], Sequence[Mapping[str, Any]], Resolve]],
              project: Mapping[str, Any], chosen: Mapping[str, str], values: Mapping[str, str],
              template: bytes | None = None, title: str = "") -> bytes:
    """Sections as issued, as one A4 PDF: each ``(section, nodes, resolve)``
    starts on a new page and is numbered "Page X of Y" within itself."""
    from . import pdf as house_pdf
    from reportlab.platypus import Flowable
    from reportlab.pdfbase.pdfmetrics import stringWidth

    kit = house_pdf._bits()
    regular, _, _ = _fonts()
    page_w, page_h = kit["A4"]
    lines = _header_lines(project)
    top = max(MARGIN, HEADER_FROM_EDGE + len(lines) * 11.5 + 12)
    frame_w = page_w - 2 * MARGIN
    nbs_template = False
    if template:
        try:
            nbs_template = specs.template_info(template).get("layout") == "nbs"
        except specs.SpecError:
            nbs_template = False

    items = list(items)
    footers: list[tuple[str, str, str]] = []

    class Start(Flowable):
        """Where a section begins: the pages from here are its pages."""

        def __init__(self, index: int, heading: str) -> None:
            super().__init__()
            self.index, self.heading = index, heading

        def wrap(self, *_):
            return 0, 0

        def draw(self):
            canvas = self.canv
            canvas._spec_section = self.index
            key = f"s{self.index}"
            canvas.bookmarkPage(key)
            canvas.addOutlineEntry(_printable(self.heading), key, level=0)

    story: list = []
    for i, (section, nodes, resolve) in enumerate(items):
        nbs = nbs_template or specs.is_nbs(nodes)
        heading = _heading(nbs, section.get("number", ""), (section.get("title") or "").upper())
        footers.append(((section.get("title") or "").upper(), section.get("number", ""),
                        _code_line(section, project)))
        if i:
            story.append(kit["PageBreak"]())
        story.append(Start(i, heading))
        story += _section_flow(kit, section, nodes, chosen, values, resolve, nbs, frame_w)
    if not story:
        raise ExportError("There is nothing to write: no sections.")

    def draw(canvas, pages_by_section: dict[int, int], page_in_section: int) -> None:
        index = getattr(canvas, "_spec_section", 0)
        sec_title, number_, code_line = footers[index]
        canvas.saveState()
        canvas.setLineWidth(0.5)
        # The running header: the project's lines, left and right, ruled under.
        y = page_h - HEADER_FROM_EDGE - 8
        canvas.setFont(regular, 10)
        for left, right in lines:
            canvas.drawString(MARGIN, y, _printable(left))
            if right:
                canvas.drawRightString(page_w - MARGIN, y, _printable(right))
            y -= 11.5
        if lines:
            canvas.line(MARGIN, y + 11.5 - 2.5, page_w - MARGIN, y + 11.5 - 2.5)
        # The footer: title, then "NUMBER - Page X of Y"; the code and revision under.
        canvas.setFont(regular, 9)
        y = FOOTER_FROM_EDGE + (10.35 if code_line else 0) + 2
        right = f"{number_} - Page {page_in_section} of {pages_by_section[index]}"
        room = frame_w - stringWidth(right, regular, 9) - 18
        shown = full = _printable(sec_title)
        while shown and stringWidth(shown, regular, 9) > room:
            full = full[:-1].rstrip()
            shown = full + "..." if full else ""
        canvas.line(MARGIN, y + 9, page_w - MARGIN, y + 9)
        canvas.drawString(MARGIN, y, shown)
        canvas.drawRightString(page_w - MARGIN, y, _printable(right))
        if code_line:
            canvas.drawString(MARGIN, y - 10.35, _printable(code_line))
        canvas.restoreState()

    class Counted(kit["Canvas"]):
        """Holds each page back until it is known how many each section has."""

        def __init__(self, *args, **kw):
            super().__init__(*args, **kw)
            self._held: list[dict] = []

        def showPage(self):                            # noqa: N802 - reportlab's name
            self._held.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            totals: dict[int, int] = {}
            for state in self._held:
                k = state.get("_spec_section", 0)
                totals[k] = totals.get(k, 0) + 1
            seen: dict[int, int] = {}
            for state in self._held:
                self.__dict__.update(state)
                k = state.get("_spec_section", 0)
                seen[k] = seen.get(k, 0) + 1
                draw(self, totals, seen[k])
                super().showPage()
            super().save()

    out = BytesIO()
    doc = kit["BaseDocTemplate"](
        out, pagesize=kit["A4"], leftMargin=MARGIN, rightMargin=MARGIN, topMargin=top,
        bottomMargin=MARGIN, title=_printable(title or (footers[0][0] if len(footers) == 1 else "")),
        author=AUTHOR)
    frame = kit["Frame"](MARGIN, MARGIN, frame_w, page_h - top - MARGIN, id="body",
                         leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([kit["PageTemplate"](id="page", frames=[frame])])
    doc.build(story, canvasmaker=Counted)
    return out.getvalue()


def pdf_name(pattern: str, section: Mapping[str, Any]) -> str:
    return specs.file_name(pattern, section).removesuffix(".docx") + ".pdf"


def tracked_name(pattern: str, section: Mapping[str, Any]) -> str:
    """The issued name with "(tracked)" on it, so it is never taken for the clean copy."""
    return specs.file_name(pattern, section).removesuffix(".docx") + " (tracked).docx"
