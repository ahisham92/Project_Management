"""Building a PDF from the same rows the Word document is built from.

The minutes go to a client in two formats and they have to be the same
document. So this renders the grids :mod:`app.minutes_doc` already describes —
the dictionaries with ``text``, ``bold``, ``size``, ``fill``, ``span`` and the
rest — rather than describing the layout a second time. A column width changed
in one place changes both.

reportlab does the drawing and pypdf staples the attachments on the end. Both
are pure Python wheels: nothing here needs a compiler, which is the rule the
rest of this app keeps.
"""

from __future__ import annotations

import io
from typing import Any, Iterable, Mapping, Sequence

# The template's own measurements, in points. A twip is a twentieth of a point,
# which is how the same grids serve both formats.
TWIPS = 20.0

FONT = "Helvetica"
BOLD = "Helvetica-Bold"
# Calibri and Verdana are not in a PDF's base fourteen and embedding a licensed
# font is not ours to do, so the nearest metric-compatible standard face is
# used. On paper the difference is a millimetre of line length.
HEADING_FONT = BOLD
HEADING_SIZE = 20

DEFAULT_SIZE = 9
LINE_SPACING = 1.18

MARGIN_LEFT = 56
MARGIN_RIGHT = 42
MARGIN_TOP = 96
MARGIN_BOTTOM = 78


class PdfError(RuntimeError):
    """A PDF that could not be built or read, said in words."""


def _bits():
    """reportlab, imported here so the app still starts without it."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch          # noqa: F401 - handy for callers
        from reportlab.platypus import (BaseDocTemplate, Frame, KeepTogether,  # noqa: F401
                                        PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                        TableStyle)
    except ImportError as exc:                        # pragma: no cover - install problem
        raise PdfError(
            "The PDF library is not installed in the Python that serves this app. "
            "Run: pip install -r requirements.txt, then reload the web app."
        ) from exc
    return {
        "colors": colors, "A4": A4, "ParagraphStyle": ParagraphStyle,
        "BaseDocTemplate": BaseDocTemplate, "Frame": Frame, "PageBreak": PageBreak,
        "PageTemplate": PageTemplate, "Paragraph": Paragraph, "Spacer": Spacer,
        "Table": Table, "TableStyle": TableStyle,
    }


def _escape(value: Any) -> str:
    """Text for a reportlab paragraph: its own markup escaped, breaks kept."""
    text = str(value if value is not None else "")
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br/>")


class Document:
    """A PDF built the way :class:`app.word.Document` builds a .docx.

    Same calls, same grids, so the two writers stay in step. What it does not
    have is anything the Word version does not: this is a second rendering of
    one document, not a second document.
    """

    def __init__(self, title: str = "", heading: str = "", logo: bytes = b"",
                 footer_note: str = "", footer_code: str = "",
                 landscape_page: bool = False) -> None:
        self.title = title
        self.heading = heading
        self.logo = logo
        self.footer_note = footer_note
        self.footer_code = footer_code
        self.landscape = landscape_page
        self._flow: list[Any] = []
        self._kit = _bits()

    # --- the pieces a caller adds -------------------------------------------

    # The Word writer's named styles, so one body of code can write both.
    STYLES: dict[str, dict[str, Any]] = {
        "Caption": {"size": 8, "colour": "#666666"},
        "Normal": {},
    }

    def add_paragraph(self, text: str = "", *, style: str = "", bold: bool = False,
                      italic: bool = False, size: float = DEFAULT_SIZE,
                      colour: str = "#000000", space_after: float = 6) -> "Document":
        named = self.STYLES.get(style or "Normal", {})
        size = float(named.get("size", size))
        colour = str(named.get("colour", colour))
        kit = self._kit
        face = BOLD if bold else FONT
        if italic:
            face = "Helvetica-BoldOblique" if bold else "Helvetica-Oblique"
        style = kit["ParagraphStyle"](
            "body", fontName=face, fontSize=size, leading=size * LINE_SPACING,
            textColor=kit["colors"].HexColor(colour), spaceAfter=space_after)
        self._flow.append(kit["Paragraph"](_escape(text) or "&nbsp;", style))
        return self

    def add_heading(self, text: str, level: int = 1) -> "Document":
        return self.add_paragraph(text, bold=True, size=13 if level == 1 else 11,
                                  space_after=4)

    def add_space(self, height: float = 8) -> "Document":
        self._flow.append(self._kit["Spacer"](1, height))
        return self

    def add_page_break(self) -> "Document":
        self._flow.append(self._kit["PageBreak"]())
        return self

    def add_grid(self, columns: Sequence[int], rows: Sequence[Sequence[Any]],
                 borders: bool = True, indent: float = 0) -> "Document":
        """One table, from the same column twips and cell dicts as the Word.

        ``span`` merges to the right, ``fill`` shades, ``repeat`` marks a header
        row that reappears when the table runs over a page — the three things
        the template's grids actually use.
        """
        kit = self._kit
        widths = [c / TWIPS for c in columns]
        available = self._width() - indent
        scale = available / sum(widths) if sum(widths) > available else 1.0
        widths = [w * scale for w in widths]

        body: list[list[Any]] = []
        style: list[tuple] = [
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]
        if borders:
            style.append(("GRID", (0, 0), (-1, -1), 0.5, kit["colors"].HexColor("#000000")))
        repeat = 0

        for r, row in enumerate(rows):
            cells: list[Any] = []
            column = 0
            for cell in row:
                spec = cell if isinstance(cell, Mapping) else {"text": cell}
                span = max(1, int(spec.get("span") or 1))
                size = float(spec.get("size") or DEFAULT_SIZE)
                face = BOLD if spec.get("bold") else FONT
                align = {"center": "CENTER", "right": "RIGHT"}.get(
                    str(spec.get("align") or ""), "LEFT")
                para = kit["ParagraphStyle"](
                    f"c{r}-{column}", fontName=face, fontSize=size,
                    leading=size * LINE_SPACING,
                    alignment={"LEFT": 0, "CENTER": 1, "RIGHT": 2}[align])
                text = _escape(spec.get("text", ""))
                if spec.get("underline"):
                    # A rule to sign on: the line is the cell's bottom border,
                    # drawn under the whole width rather than under the words,
                    # because a signature needs the room.
                    style.append(("LINEBELOW", (column, r), (column + span - 1, r), 0.6,
                                  kit["colors"].HexColor("#000000")))
                cells.append(kit["Paragraph"](text or "&nbsp;", para))
                if span > 1:
                    style.append(("SPAN", (column, r), (column + span - 1, r)))
                    cells.extend([""] * (span - 1))
                if spec.get("fill"):
                    style.append(("BACKGROUND", (column, r), (column + span - 1, r),
                                  kit["colors"].HexColor("#" + str(spec["fill"]).lstrip("#"))))
                if spec.get("valign"):
                    style.append(("VALIGN", (column, r), (column + span - 1, r),
                                  str(spec["valign"]).upper()))
                if spec.get("repeat") and r + 1 > repeat:
                    repeat = r + 1
                column += span
            while len(cells) < len(widths):
                cells.append("")
            body.append(cells[:len(widths)])

        table = kit["Table"](body, colWidths=widths, repeatRows=repeat, hAlign="LEFT")
        table.setStyle(kit["TableStyle"](style))
        self._flow.append(table)
        return self

    # --- the page itself ----------------------------------------------------

    def _size(self) -> tuple[float, float]:
        width, height = self._kit["A4"]
        return (height, width) if self.landscape else (width, height)

    def _width(self) -> float:
        return self._size()[0] - MARGIN_LEFT - MARGIN_RIGHT

    def _furniture(self, canvas, doc) -> None:
        """The letterhead across the top and the footer along the bottom."""
        width, height = self._size()
        canvas.saveState()

        if self.heading:
            canvas.setFont(HEADING_FONT, HEADING_SIZE)
            canvas.setFillColorRGB(0, 0, 0)
            canvas.drawString(MARGIN_LEFT, height - MARGIN_TOP + 34, self.heading)

        if self.logo:
            try:
                from reportlab.lib.utils import ImageReader

                image = ImageReader(io.BytesIO(self.logo))
                shape = image.getSize()
                tall = 46.0
                wide = tall * (shape[0] / shape[1]) if shape[1] else tall
                canvas.drawImage(image, width - MARGIN_RIGHT - wide, 26, wide, tall,
                                 mask="auto")
            except Exception:                          # noqa: BLE001 - a plainer page
                pass

        # The form code bottom left, the page number in the middle: where a
        # reader looks for each of them.
        canvas.setFont(FONT, DEFAULT_SIZE)
        canvas.setFillColorRGB(0, 0, 0)
        if self.footer_code:
            canvas.drawString(MARGIN_LEFT, 46, self.footer_code)
        canvas.drawCentredString(width / 2, 46, str(canvas.getPageNumber()))
        if self.footer_note:
            canvas.setFont(FONT, 7)
            canvas.setFillColorRGB(0.53, 0.53, 0.53)
            canvas.drawString(MARGIN_LEFT, 34, self.footer_note)
        canvas.restoreState()

    def render(self) -> bytes:
        kit = self._kit
        out = io.BytesIO()
        width, height = self._size()
        doc = kit["BaseDocTemplate"](
            out, pagesize=(width, height), title=self.title or "Document",
            author="Project Control", leftMargin=MARGIN_LEFT, rightMargin=MARGIN_RIGHT,
            topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM)
        frame = kit["Frame"](MARGIN_LEFT, MARGIN_BOTTOM, self._width(),
                             height - MARGIN_TOP - MARGIN_BOTTOM, id="body",
                             leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        doc.addPageTemplates([kit["PageTemplate"](id="page", frames=[frame],
                                                  onPage=self._furniture)])
        doc.build(self._flow or [kit["Spacer"](1, 1)])
        return out.getvalue()


# --- stapling things together -----------------------------------------------

def page_count(data: bytes) -> int:
    """How many pages a PDF has; 0 if it cannot be read as one."""
    try:
        from pypdf import PdfReader

        return len(PdfReader(io.BytesIO(data)).pages)
    except Exception:                                  # noqa: BLE001 - not a PDF
        return 0


def is_pdf(data: bytes) -> bool:
    """Whether this is a PDF, by what is in the file rather than its name."""
    return bool(data) and data[:5] == b"%PDF-"


def join(*documents: bytes) -> bytes:
    """One PDF from several, in the order given.

    Anything that will not open is skipped rather than failing the export: an
    attachment somebody uploaded wrongly should cost that attachment, not the
    minutes.
    """
    try:
        from pypdf import PdfWriter
    except ImportError as exc:                         # pragma: no cover
        raise PdfError("The PDF library is not installed in the Python that serves "
                       "this app. Run: pip install -r requirements.txt.") from exc

    kept = [d for d in documents if d]
    if len(kept) == 1:
        return kept[0]

    writer = PdfWriter()
    for data in kept:
        try:
            writer.append(io.BytesIO(data))
        except Exception:                              # noqa: BLE001 - skip the bad one
            continue
    out = io.BytesIO()
    writer.write(out)
    writer.close()
    return out.getvalue()
