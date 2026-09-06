"""Writes a PowerPoint deck (.pptx) using the standard library only.

Like `word.py` next door: a .pptx is a zip of XML parts, so a deck of titles,
bullets, figures and tables needs nothing installed. That matters here — the
whole app runs on Flask, waitress, openpyxl and anthropic — none of which needs
a compiler — and a presentation library would be the first one that does.

Everything is drawn as explicit shapes at explicit positions rather than filled
into a layout's placeholders. A layout is a promise about what a theme will do
with your text; an inch from the left edge is not. PowerPoint, Keynote, Google
Slides and LibreOffice all open what this produces and all put it in the same
place.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Any, Iterable, Sequence
from xml.sax.saxutils import escape

# English Metric Units: 914400 to the inch. A 16:9 slide, which is what a
# projector and a laptop both are now.
EMU = 914400
WIDTH = int(13.333 * EMU)
HEIGHT = int(7.5 * EMU)

MARGIN = int(0.6 * EMU)
ROW_HEIGHT = int(0.32 * EMU)
BODY_TOP = int(1.55 * EMU)

INK = "1F2933"
MUTED = "6B7A8C"
ACCENT = "2A78D6"
GOOD = "1E8E5A"
BAD = "C0392B"
RULE = "D8DEE6"

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _t(value: Any) -> str:
    return escape(str(value if value is not None else ""))


# --- the parts every deck needs ---------------------------------------------

_RELS_ROOT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

_APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
            xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Project Control</Application>
</Properties>"""

# A theme is required, and its shape is fixed: twelve colours, two fonts, and
# three each of fill, line, effect and background styles. None of it is used —
# every shape here states its own colour — but PowerPoint will not open a deck
# without one.
_THEME = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<a:theme xmlns:a="{A}" name="Project Control">
  <a:themeElements>
    <a:clrScheme name="Project Control">
      <a:dk1><a:srgbClr val="{INK}"/></a:dk1><a:lt1><a:srgbClr val="FFFFFF"/></a:lt1>
      <a:dk2><a:srgbClr val="{MUTED}"/></a:dk2><a:lt2><a:srgbClr val="F4F6F9"/></a:lt2>
      <a:accent1><a:srgbClr val="{ACCENT}"/></a:accent1><a:accent2><a:srgbClr val="{GOOD}"/></a:accent2>
      <a:accent3><a:srgbClr val="{BAD}"/></a:accent3><a:accent4><a:srgbClr val="E4A11B"/></a:accent4>
      <a:accent5><a:srgbClr val="7C5CBF"/></a:accent5><a:accent6><a:srgbClr val="0E8FA8"/></a:accent6>
      <a:hlink><a:srgbClr val="{ACCENT}"/></a:hlink><a:folHlink><a:srgbClr val="{MUTED}"/></a:folHlink>
    </a:clrScheme>
    <a:fontScheme name="Project Control">
      <a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>
      <a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>
    </a:fontScheme>
    <a:fmtScheme name="Project Control">
      <a:fillStyleLst>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      </a:fillStyleLst>
      <a:lnStyleLst>
        <a:ln w="6350"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
        <a:ln w="12700"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
        <a:ln w="19050"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill></a:ln>
      </a:lnStyleLst>
      <a:effectStyleLst>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
        <a:effectStyle><a:effectLst/></a:effectStyle>
      </a:effectStyleLst>
      <a:bgFillStyleLst>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
        <a:solidFill><a:schemeClr val="phClr"/></a:solidFill>
      </a:bgFillStyleLst>
    </a:fmtScheme>
  </a:themeElements>
</a:theme>"""

_MASTER = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldMaster xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}">
  <p:cSld>
    <p:bg><p:bgPr><a:solidFill><a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg>
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
        <a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2"
            accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6"
            hlink="hlink" folHlink="folHlink"/>
  <p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
  <p:txStyles>
    <p:titleStyle><a:lvl1pPr><a:defRPr sz="2600" b="1"/></a:lvl1pPr></p:titleStyle>
    <p:bodyStyle><a:lvl1pPr><a:defRPr sz="1600"/></a:lvl1pPr></p:bodyStyle>
    <p:otherStyle><a:lvl1pPr><a:defRPr sz="1400"/></a:lvl1pPr></p:otherStyle>
  </p:txStyles>
</p:sldMaster>"""

_MASTER_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
  <Relationship Id="rId2" Type="{R}/theme" Target="../theme/theme1.xml"/>
</Relationships>"""

_LAYOUT = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sldLayout xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}" type="blank" preserve="1">
  <p:cSld name="Blank">
    <p:spTree>
      <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
      <p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
        <a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>
    </p:spTree>
  </p:cSld>
  <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
</p:sldLayout>"""

_LAYOUT_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="{R}/slideMaster" Target="../slideMasters/slideMaster1.xml"/>
</Relationships>"""

_SLIDE_RELS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="{R}/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>
</Relationships>"""


# --- drawing on a slide -----------------------------------------------------

def _run(text: str, size: int, bold: bool = False, colour: str = INK,
         italic: bool = False) -> str:
    return (f'<a:r><a:rPr lang="en-GB" sz="{size * 100}" b="{1 if bold else 0}" '
            f'i="{1 if italic else 0}" dirty="0">'
            f'<a:solidFill><a:srgbClr val="{colour}"/></a:solidFill>'
            f'<a:latin typeface="Calibri"/></a:rPr>'
            f'<a:t>{_t(text)}</a:t></a:r>')


def _para(text: str, size: int, bold: bool = False, colour: str = INK,
          bullet: bool = False, align: str = "l", space_before: int = 0,
          italic: bool = False) -> str:
    marker = ('<a:buFont typeface="Arial"/><a:buChar char="•"/>' if bullet
              else "<a:buNone/>")
    indent = ' marL="228600" indent="-228600"' if bullet else ' marL="0" indent="0"'
    before = f'<a:spcBef><a:spcPts val="{space_before * 100}"/></a:spcBef>' if space_before else ""
    return (f'<a:p><a:pPr{indent} algn="{align}">{before}{marker}</a:pPr>'
            f'{_run(text, size, bold, colour, italic)}</a:p>')


def _textbox(shape_id: int, name: str, x: int, y: int, cx: int, cy: int,
             paragraphs: Sequence[str], anchor: str = "t") -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{_t(name)}"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square" anchor="{anchor}" lIns="0" tIns="0" rIns="0" bIns="0">'
        f'<a:normAutofit/></a:bodyPr><a:lstStyle/>{"".join(paragraphs)}</p:txBody></p:sp>'
    )


def _rect(shape_id: int, x: int, y: int, cx: int, cy: int, fill: str,
          line: str = "") -> str:
    stroke = (f'<a:ln w="12700"><a:solidFill><a:srgbClr val="{line}"/></a:solidFill></a:ln>'
              if line else "<a:ln><a:noFill/></a:ln>")
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="Block {shape_id}"/>'
        f'<p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="roundRect"><a:avLst>'
        f'<a:gd name="adj" fmla="val 8000"/></a:avLst></a:prstGeom>'
        f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>{stroke}</p:spPr>'
        f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>'
    )


def _cell(text: str, size: int, bold: bool, colour: str, align: str, fill: str) -> str:
    return (f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
            f'{_para(text, size, bold, colour, align=align)}</a:txBody>'
            f'<a:tcPr marL="68580" marR="68580" marT="45720" marB="45720" anchor="ctr">'
            f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill></a:tcPr></a:tc>')


def _table(shape_id: int, x: int, y: int, cx: int,
           headings: Sequence[str], rows: Sequence[Sequence[Any]],
           widths: Sequence[float] | None = None,
           right_from: int = 1) -> str:
    columns = len(headings)
    share = list(widths or [1.0] * columns)
    total = sum(share) or 1
    sizes = [int(cx * part / total) for part in share]

    grid = "".join(f'<a:gridCol w="{width}"/>' for width in sizes)
    head = "".join(_cell(text, 12, True, "FFFFFF",
                         "r" if index >= right_from else "l", ACCENT)
                   for index, text in enumerate(headings))
    body = []
    for number, row in enumerate(rows):
        shade = "FFFFFF" if number % 2 == 0 else "F4F6F9"
        body.append(f'<a:tr h="{ROW_HEIGHT}">' + "".join(
            _cell(value, 11, False, INK, "r" if index >= right_from else "l", shade)
            for index, value in enumerate(row)) + "</a:tr>")

    height = ROW_HEIGHT * (len(rows) + 1)
    return (
        f'<p:graphicFrame><p:nvGraphicFramePr>'
        f'<p:cNvPr id="{shape_id}" name="Table {shape_id}"/>'
        f'<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>'
        f'<p:nvPr/></p:nvGraphicFramePr>'
        f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{height}"/></p:xfrm>'
        f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
        f'<a:tbl><a:tblPr firstRow="1" bandRow="1"/><a:tblGrid>{grid}</a:tblGrid>'
        f'<a:tr h="{ROW_HEIGHT}">{head}</a:tr>{"".join(body)}</a:tbl>'
        f'</a:graphicData></a:graphic></p:graphicFrame>'
    )


def _slide(shapes: Sequence[str]) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<p:sld xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>'
        f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f'{"".join(shapes)}</p:spTree></p:cSld>'
        f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
    )


class Deck:
    """A deck, built a slide at a time and saved as bytes."""

    def __init__(self, footer: str = "") -> None:
        self.slides: list[str] = []
        self.footer = footer

    # --- the kinds of slide this makes --------------------------------------

    def cover(self, title: str, subtitle: str = "", note: str = "") -> "Deck":
        shapes = [
            _rect(2, 0, 0, WIDTH, int(0.28 * EMU), ACCENT),
            _textbox(3, "Title", MARGIN, int(2.4 * EMU), WIDTH - 2 * MARGIN, int(1.6 * EMU),
                     [_para(title, 40, True, INK)]),
        ]
        if subtitle:
            shapes.append(_textbox(4, "Subtitle", MARGIN, int(4.0 * EMU),
                                   WIDTH - 2 * MARGIN, int(0.8 * EMU),
                                   [_para(subtitle, 20, False, ACCENT)]))
        if note:
            shapes.append(_textbox(5, "Note", MARGIN, int(4.9 * EMU),
                                   WIDTH - 2 * MARGIN, int(1.2 * EMU),
                                   [_para(note, 13, False, MUTED)]))
        return self._add(shapes, numbered=False)

    def figures(self, title: str, blocks: Sequence[dict[str, Any]], note: str = "") -> "Deck":
        """A row of headline numbers, each with a label and a line under it."""
        shapes = list(self._head(title))
        count = max(1, min(len(blocks), 4))
        gap = int(0.25 * EMU)
        width = (WIDTH - 2 * MARGIN - gap * (count - 1)) // count
        top, height = BODY_TOP + int(0.4 * EMU), int(1.9 * EMU)

        shape_id = 10
        for index, block in enumerate(blocks[:count]):
            x = MARGIN + index * (width + gap)
            shapes.append(_rect(shape_id, x, top, width, height, "F4F6F9", RULE))
            shapes.append(_textbox(
                shape_id + 1, f"Figure {index}", x + int(0.25 * EMU), top + int(0.22 * EMU),
                width - int(0.5 * EMU), height - int(0.4 * EMU),
                [_para(str(block.get("label", "")).upper(), 11, False, MUTED),
                 _para(str(block.get("value", "")), 30, True,
                       str(block.get("colour") or INK), space_before=6),
                 _para(str(block.get("hint", "")), 11, False, MUTED, space_before=4)]))
            shape_id += 2

        if note:
            shapes.append(_textbox(shape_id, "Note", MARGIN, top + height + int(0.4 * EMU),
                                   WIDTH - 2 * MARGIN, int(2.0 * EMU),
                                   [_para(note, 14, False, INK)]))
        return self._add(shapes)

    def bullets(self, title: str, lines: Iterable[Any], note: str = "") -> "Deck":
        shapes = list(self._head(title))
        written = [_para(str(line), 16, False, INK, bullet=True, space_before=8)
                   for line in list(lines)[:9]] or [_para("Nothing to report", 16, False, MUTED)]
        shapes.append(_textbox(10, "Bullets", MARGIN, BODY_TOP + int(0.3 * EMU),
                               WIDTH - 2 * MARGIN, int(4.4 * EMU), written))
        if note:
            shapes.append(_textbox(11, "Note", MARGIN, int(6.3 * EMU),
                                   WIDTH - 2 * MARGIN, int(0.7 * EMU),
                                   [_para(note, 12, False, MUTED, italic=True)]))
        return self._add(shapes)

    def table(self, title: str, headings: Sequence[str], rows: Sequence[Sequence[Any]],
              widths: Sequence[float] | None = None, right_from: int = 1,
              note: str = "") -> "Deck":
        shapes = list(self._head(title))
        if rows:
            shapes.append(_table(10, MARGIN, BODY_TOP + int(0.25 * EMU),
                                 WIDTH - 2 * MARGIN, headings, rows, widths, right_from))
        else:
            shapes.append(_textbox(10, "Empty", MARGIN, BODY_TOP + int(0.4 * EMU),
                                   WIDTH - 2 * MARGIN, int(0.6 * EMU),
                                   [_para("Nothing in this period", 16, False, MUTED)]))
        if note:
            shapes.append(_textbox(11, "Note", MARGIN, int(6.5 * EMU),
                                   WIDTH - 2 * MARGIN, int(0.6 * EMU),
                                   [_para(note, 12, False, MUTED, italic=True)]))
        return self._add(shapes)

    # --- the plumbing -------------------------------------------------------

    def _head(self, title: str) -> list[str]:
        return [
            _textbox(2, "Heading", MARGIN, int(0.55 * EMU), WIDTH - 2 * MARGIN,
                     int(0.7 * EMU), [_para(title, 26, True, INK)]),
            _rect(3, MARGIN, int(1.32 * EMU), int(1.1 * EMU), 25400, ACCENT),
        ]

    def _add(self, shapes: Sequence[str], numbered: bool = True) -> "Deck":
        drawn = list(shapes)
        if numbered and self.footer:
            drawn.append(_textbox(
                90, "Footer", MARGIN, int(6.85 * EMU), WIDTH - 2 * MARGIN, int(0.35 * EMU),
                [_para(f"{self.footer}  ·  {len(self.slides) + 1}", 10, False, MUTED)]))
        self.slides.append(_slide(drawn))
        return self

    def save(self, title: str = "Project Control") -> bytes:
        """The deck as a .pptx file."""
        if not self.slides:
            self.cover(title)

        count = len(self.slides)
        types = ["""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>
  <Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>
  <Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>
  <Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>"""]
        for number in range(1, count + 1):
            types.append(f'  <Override PartName="/ppt/slides/slide{number}.xml" '
                         f'ContentType="application/vnd.openxmlformats-officedocument.'
                         f'presentationml.slide+xml"/>')
        types.append("</Types>")

        # Slides are rId2 onwards; rId1 is the master.
        slide_ids = "".join(
            f'<p:sldId id="{255 + number}" r:id="rId{number + 1}"/>'
            for number in range(1, count + 1))
        presentation = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<p:presentation xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}" saveSubsetFonts="1">'
            f'<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            f'<p:sldIdLst>{slide_ids}</p:sldIdLst>'
            f'<p:sldSz cx="{WIDTH}" cy="{HEIGHT}"/>'
            f'<p:notesSz cx="{HEIGHT}" cy="{WIDTH}"/></p:presentation>'
        )
        rels = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rId1" Type="{R}/slideMaster" '
                f'Target="slideMasters/slideMaster1.xml"/>']
        for number in range(1, count + 1):
            rels.append(f'<Relationship Id="rId{number + 1}" Type="{R}/slide" '
                        f'Target="slides/slide{number}.xml"/>')
        rels.append(f'<Relationship Id="rId{count + 2}" Type="{R}/theme" '
                    f'Target="theme/theme1.xml"/></Relationships>')

        core = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<cp:coreProperties '
                f'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                f'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f'<dc:title>{_t(title)}</dc:title>'
                f'<dc:creator>Project Control</dc:creator>'
                f'<cp:lastModifiedBy>Project Control</cp:lastModifiedBy>'
                f'</cp:coreProperties>')

        held = BytesIO()
        with zipfile.ZipFile(held, "w", zipfile.ZIP_DEFLATED) as book:
            book.writestr("[Content_Types].xml", "\n".join(types))
            book.writestr("_rels/.rels", _RELS_ROOT)
            book.writestr("docProps/core.xml", core)
            book.writestr("docProps/app.xml", _APP)
            book.writestr("ppt/presentation.xml", presentation)
            book.writestr("ppt/_rels/presentation.xml.rels", "".join(rels))
            book.writestr("ppt/theme/theme1.xml", _THEME)
            book.writestr("ppt/slideMasters/slideMaster1.xml", _MASTER)
            book.writestr("ppt/slideMasters/_rels/slideMaster1.xml.rels", _MASTER_RELS)
            book.writestr("ppt/slideLayouts/slideLayout1.xml", _LAYOUT)
            book.writestr("ppt/slideLayouts/_rels/slideLayout1.xml.rels", _LAYOUT_RELS)
            for number, slide in enumerate(self.slides, start=1):
                book.writestr(f"ppt/slides/slide{number}.xml", slide)
                book.writestr(f"ppt/slides/_rels/slide{number}.xml.rels", _SLIDE_RELS)
        return held.getvalue()
