"""Writes a Word document (.docx) using the standard library only.

A .docx is a zip of XML parts, so a document with headings, paragraphs and
tables needs nothing installed — which keeps the install to Flask, waitress,
openpyxl and anthropic. Word, LibreOffice, Google Docs and Pages all open what this produces.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

# The same, for a document that carries a letterhead: a header part, a footer
# part, and the PNG the footer draws.
_CONTENT_TYPES_LETTERHEAD = _CONTENT_TYPES.replace(
    "</Types>",
    '  <Default Extension="png" ContentType="image/png"/>\n'
    '  <Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>\n'
    '  <Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>\n'
    "</Types>")

_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

_DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DOCUMENT_RELS_LETTERHEAD = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="{_R}/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="{_R}/header" Target="header1.xml"/>
  <Relationship Id="rId3" Type="{_R}/footer" Target="footer1.xml"/>
</Relationships>"""

_FOOTER_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="{_R}/image" Target="media/logo.png"/>
</Relationships>"""

_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Project Control</Application>
</Properties>"""

# One paragraph style per thing this writer can emit. Sizes are in half-points.
_STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
  <w:docDefaults>
    <w:rPrDefault><w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/>
      <w:sz w:val="20"/><w:szCs w:val="20"/>
    </w:rPr></w:rPrDefault>
    <w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="252" w:lineRule="auto"/></w:pPr></w:pPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/><w:qFormat/>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:qFormat/>
    <w:pPr><w:spacing w:after="60"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle">
    <w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:qFormat/>
    <w:pPr><w:spacing w:after="240"/></w:pPr>
    <w:rPr><w:color w:val="555555"/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="0"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:qFormat/>
    <w:pPr><w:keepNext/><w:spacing w:before="160" w:after="60"/><w:outlineLvl w:val="1"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Caption">
    <w:name w:val="caption"/><w:basedOn w:val="Normal"/><w:qFormat/>
    <w:rPr><w:color w:val="666666"/><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Cell">
    <w:name w:val="Cell"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="40" w:after="40" w:line="220" w:lineRule="atLeast"/></w:pPr>
    <w:rPr><w:sz w:val="18"/></w:rPr>
  </w:style>
  <!-- The letterhead line across the top of every page. Verdana 20pt, as the
       template has it, so a document produced here and one typed by hand sit
       in the same folder without looking like two different things. -->
  <w:style w:type="paragraph" w:customStyle="1" w:styleId="01DarHeading">
    <w:name w:val="01 DarHeading"/><w:basedOn w:val="Normal"/>
    <w:pPr><w:tabs><w:tab w:val="center" w:pos="4320"/><w:tab w:val="right" w:pos="8640"/></w:tabs>
      <w:spacing w:after="0" w:line="540" w:lineRule="exact"/></w:pPr>
    <w:rPr><w:rFonts w:ascii="Verdana" w:hAnsi="Verdana" w:cs="Times New Roman"/>
      <w:bCs/><w:sz w:val="40"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Header">
    <w:name w:val="header"/><w:basedOn w:val="Normal"/><w:uiPriority w:val="99"/>
    <w:pPr><w:tabs><w:tab w:val="center" w:pos="4680"/><w:tab w:val="right" w:pos="9360"/></w:tabs>
      <w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Footer">
    <w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:uiPriority w:val="99"/>
    <w:pPr><w:tabs><w:tab w:val="center" w:pos="4680"/><w:tab w:val="right" w:pos="9360"/></w:tabs>
      <w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>
  </w:style>
  <w:style w:type="table" w:styleId="TableGrid">
    <w:name w:val="Table Grid"/>
    <w:tblPr><w:tblBorders>
      <w:top w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
      <w:left w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
      <w:bottom w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
      <w:right w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
      <w:insideH w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
      <w:insideV w:val="single" w:sz="4" w:space="0" w:color="BFBFBF"/>
    </w:tblBorders></w:tblPr>
  </w:style>
</w:styles>"""

# A4 with 2 cm margins, in twentieths of a point.
_PAGE = {
    "portrait": '<w:pgSz w:w="11906" w:h="16838"/>',
    "landscape": '<w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>',
}
_USABLE_TWIPS = {"portrait": 9638, "landscape": 15570}   # page width less margins


# Two blank lines above the title, as the template has it, so the letterhead
# sits where a reader expects it rather than tight against the page edge.
def _header_part(heading: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:hdr xmlns:w="{W}">'
        f'<w:p><w:pPr><w:pStyle w:val="01DarHeading"/></w:pPr></w:p>'
        f'<w:p><w:pPr><w:pStyle w:val="01DarHeading"/></w:pPr></w:p>'
        f'<w:p><w:pPr><w:pStyle w:val="01DarHeading"/></w:pPr>'
        f'<w:r><w:t xml:space="preserve">{_text(heading)}</w:t></w:r></w:p>'
        f'<w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr></w:p>'
        f"</w:hdr>"
    )


def _footer_part(logo: tuple[int, int] | None, note: str = "") -> str:
    """The page number, a line of small print, and the logo on the right.

    The logo is anchored rather than inline so the text beside it keeps its own
    baseline — an inline image in a footer pushes the page number down the page.
    """
    drawing = ""
    if logo:
        width, height = logo
        drawing = (
            '<w:r><w:rPr><w:noProof/></w:rPr><w:drawing>'
            '<wp:anchor xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
            ' distT="0" distB="0" distL="114300" distR="114300" simplePos="0"'
            ' relativeHeight="251658240" behindDoc="0" locked="0" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/>'
            '<wp:positionH relativeFrom="column"><wp:posOffset>4485640</wp:posOffset></wp:positionH>'
            '<wp:positionV relativeFrom="paragraph"><wp:posOffset>15875</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{width}" cy="{height}"/>'
            '<wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            '<wp:docPr id="1" name="Logo"/>'
            '<wp:cNvGraphicFramePr><a:graphicFrameLocks'
            f' xmlns:a="{A}" noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic xmlns:a="{A}">'
            '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            '<pic:nvPicPr><pic:cNvPr id="1" name="Logo"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip xmlns:r="{_R}" r:embed="rId1"/>'
            '<a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            '<pic:spPr><a:xfrm><a:off x="0" y="0"/>'
            f'<a:ext cx="{width}" cy="{height}"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
            "</pic:pic></a:graphicData></a:graphic></wp:anchor></w:drawing></w:r>"
        )

    # PAGE and NUMPAGES as real fields, so they follow the document rather than
    # being a number typed once and wrong by the second page.
    page_number = (
        '<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
        '<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="666666"/></w:rPr>'
        '<w:t xml:space="preserve">Page </w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="666666"/></w:rPr><w:t>1</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        '<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="666666"/></w:rPr>'
        '<w:t xml:space="preserve"> of </w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        '<w:r><w:instrText xml:space="preserve"> NUMPAGES </w:instrText></w:r>'
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        '<w:r><w:rPr><w:sz w:val="16"/><w:color w:val="666666"/></w:rPr><w:t>1</w:t></w:r>'
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        "</w:p>"
    )
    small_print = (
        f'<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>'
        f'<w:r><w:rPr><w:sz w:val="14"/><w:color w:val="888888"/></w:rPr>'
        f'<w:t xml:space="preserve">{_text(note)}</w:t></w:r></w:p>' if note else ""
    )
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:ftr xmlns:w="{W}">'
        f'<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr>{drawing}</w:p>'
        f"{page_number}{small_print}</w:ftr>"
    )


def _text(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _runs(value: Any, *, bold: bool = False, italic: bool = False, color: str = "",
          size: Any = None, font: str = "") -> str:
    """Runs for one piece of text, with line breaks preserved.

    `size` is in points; Word wants half-points, which is a good way to make
    everything twice the size it should be if the conversion lives at the call
    site instead of here.
    """
    props = ""
    if bold or italic or color or size or font:
        half = f'<w:sz w:val="{int(round(float(size) * 2))}"/>' if size else ""
        props = "<w:rPr>{}{}{}{}{}</w:rPr>".format(
            f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>' if font else "",
            "<w:b/>" if bold else "",
            "<w:i/>" if italic else "",
            f'<w:color w:val="{color}"/>' if color else "",
            half,
        )
    lines = str(value if value is not None else "").split("\n")
    parts = []
    for index, line in enumerate(lines):
        prefix = "<w:br/>" if index else ""
        parts.append(
            f'<w:r>{props}{prefix}<w:t xml:space="preserve">{_text(line)}</w:t></w:r>'
        )
    return "".join(parts)


def _png_size(data: bytes, height_cm: float = 2.17) -> tuple[int, int] | None:
    """A PNG's size in EMU, scaled to a fixed height.

    Read out of the file's own header rather than passed in, so a replacement
    logo of a different shape is not stretched to the old one's proportions.
    """
    if not data or len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    import struct

    width, height = struct.unpack(">II", data[16:24])
    if not height:
        return None
    emu = int(height_cm * 360000)
    return int(emu * width / height), emu


class Document:
    """Builds one Word document. Call the add_* methods, then ``render()``."""

    def __init__(self, title: str = "", orientation: str = "portrait",
                 heading: str = "", logo: bytes = b"", footer_note: str = "") -> None:
        self.title = title
        self.orientation = orientation if orientation in _PAGE else "portrait"
        self._body: list[str] = []
        # A letterhead: a line across the top of every page, and a logo and a
        # page number along the bottom. Given none of these, the document comes
        # out plain, as everything else in the app still wants.
        self.heading = heading
        self.logo = logo
        self.footer_note = footer_note

    @property
    def letterhead(self) -> bool:
        return bool(self.heading or self.logo or self.footer_note)

    # --- content ----------------------------------------------------------

    def add_title(self, text: str, subtitle: str = "") -> "Document":
        self._body.append(f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr>{_runs(text)}</w:p>')
        if subtitle:
            self._body.append(
                f'<w:p><w:pPr><w:pStyle w:val="Subtitle"/></w:pPr>{_runs(subtitle)}</w:p>'
            )
        return self

    def add_heading(self, text: str, level: int = 1) -> "Document":
        style = "Heading1" if level <= 1 else "Heading2"
        self._body.append(f'<w:p><w:pPr><w:pStyle w:val="{style}"/></w:pPr>{_runs(text)}</w:p>')
        return self

    def add_paragraph(self, text: str = "", *, bold: bool = False, italic: bool = False,
                      style: str = "") -> "Document":
        props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        self._body.append(f"<w:p>{props}{_runs(text, bold=bold, italic=italic)}</w:p>")
        return self

    def add_fields(self, pairs: Iterable[tuple[str, Any]]) -> "Document":
        """A two-column block of label/value lines — the meeting header."""
        rows = [(label, value) for label, value in pairs if str(value or "").strip()]
        if not rows:
            return self
        return self.add_table(
            headers=(), rows=[[label, value] for label, value in rows], widths=(28, 72),
            label_column=True,
        )

    def add_table(self, headers: Sequence[str], rows: Sequence[Sequence[Any]],
                  widths: Sequence[float] = (), label_column: bool = False) -> "Document":
        """A grid. ``widths`` are percentages; they are normalised if they are not."""
        columns = max([len(headers)] + [len(r) for r in rows]) if (headers or rows) else 0
        if not columns:
            return self

        share = list(widths) if len(widths) == columns else [100 / columns] * columns
        total = sum(share) or 1
        usable = _USABLE_TWIPS[self.orientation]
        twips = [max(400, int(usable * (w / total))) for w in share]

        parts = [
            '<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/>'
            '<w:tblW w:w="5000" w:type="pct"/>'
            '<w:tblLayout w:type="fixed"/>'
            '<w:tblCellMar><w:top w:w="60" w:type="dxa"/><w:left w:w="90" w:type="dxa"/>'
            '<w:bottom w:w="60" w:type="dxa"/><w:right w:w="90" w:type="dxa"/></w:tblCellMar>'
            "</w:tblPr><w:tblGrid>",
            "".join(f'<w:gridCol w:w="{w}"/>' for w in twips),
            "</w:tblGrid>",
        ]

        if headers:
            parts.append(self._row(headers, twips, header=True))
        for row in rows:
            parts.append(self._row(row, twips, label_column=label_column))
        parts.append("</w:tbl>")

        self._body.append("".join(parts))
        # Word wants a paragraph after a table; without one, two tables in a row
        # are merged into one when the file is opened.
        self._body.append("<w:p/>")
        return self

    def _row(self, cells: Sequence[Any], twips: Sequence[int], *, header: bool = False,
             label_column: bool = False) -> str:
        padded = list(cells) + [""] * (len(twips) - len(cells))
        parts = ['<w:tr>']
        if header:
            parts.append("<w:trPr><w:tblHeader/></w:trPr>")   # repeats on every page
        for index, (value, width) in enumerate(zip(padded, twips)):
            bold = header or (label_column and index == 0)
            shading = '<w:shd w:val="clear" w:color="auto" w:fill="EFF3F8"/>' if header else ""
            parts.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shading}'
                '<w:vAlign w:val="top"/></w:tcPr>'
                f'<w:p><w:pPr><w:pStyle w:val="Cell"/></w:pPr>{_runs(value, bold=bold)}</w:p></w:tc>'
            )
        parts.append("</w:tr>")
        return "".join(parts)

    def add_grid(self, columns: Sequence[int], rows: Sequence[Sequence[Any]],
                 cell_margin: int = 56, borders: bool = True,
                 indent: int = 0) -> "Document":
        """A table laid out in twips rather than percentages.

        The template's tables are drawn to fixed column widths — a name column
        that grows because somebody has a long surname is exactly what makes two
        sets of minutes look like two different documents — so this takes the
        widths as they are and does not normalise them.

        A cell is a string, or a dict: ``text``, ``span``, ``fill``, ``bold``,
        ``align``, ``valign``, ``size``, ``underline`` (a signature line),
        ``style``, ``font``.
        """
        width = sum(columns)
        frame = (
            '<w:tblBorders>'
            '<w:top w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
            '<w:left w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
            '<w:bottom w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
            '<w:right w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
            '<w:insideH w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
            '<w:insideV w:val="single" w:sz="8" w:space="0" w:color="auto"/>'
            "</w:tblBorders>" if borders else ""
        )
        parts = [
            f'<w:tbl><w:tblPr><w:tblW w:w="{width}" w:type="dxa"/>'
            f'<w:tblInd w:w="{indent}" w:type="dxa"/>{frame}'
            f'<w:tblLayout w:type="fixed"/>'
            f'<w:tblCellMar><w:left w:w="{cell_margin}" w:type="dxa"/>'
            f'<w:right w:w="{cell_margin}" w:type="dxa"/></w:tblCellMar>'
            "</w:tblPr><w:tblGrid>",
            "".join(f'<w:gridCol w:w="{c}"/>' for c in columns),
            "</w:tblGrid>",
        ]
        for row in rows:
            parts.append(self._grid_row(row, columns))
        parts.append("</w:tbl>")
        self._body.append("".join(parts))
        self._body.append("<w:p/>")
        return self

    def _grid_row(self, cells: Sequence[Any], columns: Sequence[int]) -> str:
        header = any(isinstance(c, dict) and c.get("repeat") for c in cells)
        parts = ["<w:tr><w:trPr><w:cantSplit/>"
                 + ("<w:tblHeader/>" if header else "") + "</w:trPr>"]

        at = 0
        for cell in cells:
            spec = cell if isinstance(cell, dict) else {"text": cell}
            span = max(1, int(spec.get("span", 1)))
            width = sum(columns[at:at + span]) or columns[min(at, len(columns) - 1)]
            at += span

            shading = (f'<w:shd w:val="clear" w:color="auto" w:fill="{spec["fill"]}"/>'
                       if spec.get("fill") else "")
            spanning = f'<w:gridSpan w:val="{span}"/>' if span > 1 else ""
            # A cell with a bottom rule and nothing else is a line to sign on.
            edge = ('<w:tcBorders><w:bottom w:val="single" w:sz="8" w:space="0"'
                    ' w:color="auto"/></w:tcBorders>' if spec.get("underline") else "")
            valign = f'<w:vAlign w:val="{spec.get("valign", "center")}"/>'

            align = (f'<w:jc w:val="{spec["align"]}"/>' if spec.get("align") else "")
            style = f'<w:pStyle w:val="{spec.get("style", "Cell")}"/>'
            parts.append(
                f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{spanning}{shading}'
                f'{edge}{valign}</w:tcPr>'
                f'<w:p><w:pPr>{style}{align}</w:pPr>'
                + _runs(spec.get("text", ""), bold=bool(spec.get("bold")),
                        size=spec.get("size"), font=spec.get("font", ""))
                + "</w:p></w:tc>"
            )
        parts.append("</w:tr>")
        return "".join(parts)

    def add_page_break(self) -> "Document":
        self._body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        return self

    # --- output -----------------------------------------------------------

    def document_xml(self) -> str:
        references = ('<w:headerReference w:type="default" r:id="rId2"/>'
                      '<w:footerReference w:type="default" r:id="rId3"/>'
                      if self.letterhead else "")
        section = (
            f"<w:sectPr>{references}{_PAGE[self.orientation]}"
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"'
            ' w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}" xmlns:r="{_R}">'
            f'<w:body>{"".join(self._body)}{section}</w:body></w:document>'
        )

    def render(self) -> bytes:
        """The .docx file, as bytes ready to send."""
        core = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties'
            ' xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>{_text(self.title)}</dc:title>"
            "</cp:coreProperties>"
        )
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml",
                             _CONTENT_TYPES_LETTERHEAD if self.letterhead else _CONTENT_TYPES)
            archive.writestr("_rels/.rels", _ROOT_RELS)
            archive.writestr("docProps/core.xml", core)
            archive.writestr("docProps/app.xml", _APP)
            archive.writestr("word/_rels/document.xml.rels",
                             _DOCUMENT_RELS_LETTERHEAD if self.letterhead else _DOCUMENT_RELS)
            archive.writestr("word/styles.xml", _STYLES)
            archive.writestr("word/document.xml", self.document_xml())
            if self.letterhead:
                archive.writestr("word/header1.xml", _header_part(self.heading))
                archive.writestr("word/footer1.xml",
                                 _footer_part(_png_size(self.logo), self.footer_note))
                archive.writestr("word/_rels/footer1.xml.rels", _FOOTER_RELS)
                if self.logo:
                    archive.writestr("word/media/logo.png", self.logo)
        return buffer.getvalue()
