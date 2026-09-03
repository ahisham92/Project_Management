"""Writes a Word document (.docx) using the standard library only.

A .docx is a zip of XML parts, so a document with headings, paragraphs and
tables needs nothing installed — which keeps the install to Flask, waitress and
openpyxl. Word, LibreOffice, Google Docs and Pages all open what this produces.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

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
    <w:pPr><w:spacing w:before="40" w:after="40"/></w:pPr>
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


def _text(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _runs(value: Any, *, bold: bool = False, italic: bool = False, color: str = "") -> str:
    """Runs for one piece of text, with line breaks preserved."""
    props = ""
    if bold or italic or color:
        props = "<w:rPr>{}{}{}</w:rPr>".format(
            "<w:b/>" if bold else "",
            "<w:i/>" if italic else "",
            f'<w:color w:val="{color}"/>' if color else "",
        )
    lines = str(value if value is not None else "").split("\n")
    parts = []
    for index, line in enumerate(lines):
        prefix = "<w:br/>" if index else ""
        parts.append(
            f'<w:r>{props}{prefix}<w:t xml:space="preserve">{_text(line)}</w:t></w:r>'
        )
    return "".join(parts)


class Document:
    """Builds one Word document. Call the add_* methods, then ``render()``."""

    def __init__(self, title: str = "", orientation: str = "portrait") -> None:
        self.title = title
        self.orientation = orientation if orientation in _PAGE else "portrait"
        self._body: list[str] = []

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

    def add_page_break(self) -> "Document":
        self._body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        return self

    # --- output -----------------------------------------------------------

    def document_xml(self) -> str:
        section = (
            f"<w:sectPr>{_PAGE[self.orientation]}"
            '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"'
            ' w:header="567" w:footer="567" w:gutter="0"/></w:sectPr>'
        )
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<w:document xmlns:w="{W}"><w:body>{"".join(self._body)}{section}</w:body></w:document>'
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
            archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
            archive.writestr("_rels/.rels", _ROOT_RELS)
            archive.writestr("docProps/core.xml", core)
            archive.writestr("docProps/app.xml", _APP)
            archive.writestr("word/_rels/document.xml.rels", _DOCUMENT_RELS)
            archive.writestr("word/styles.xml", _STYLES)
            archive.writestr("word/document.xml", self.document_xml())
        return buffer.getvalue()
