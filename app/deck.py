"""Writes a PowerPoint deck (.pptx) using the standard library only.

Like `word.py` next door: a .pptx is a zip of XML parts, so a deck of covers,
figures, charts and tables needs nothing installed. That matters here — the whole
app runs on packages that need no compiler, and a presentation library would be
the first one that does.

Everything is drawn as explicit shapes at explicit positions rather than filled
into a layout's placeholders. A layout is a promise about what a theme will do
with your text; an inch from the left edge is not. PowerPoint, Keynote, Google
Slides and LibreOffice all open what this produces and all put it in the same
place.

**The charts are shapes too.** A deck of nothing but tables is a report somebody
has printed sideways, and a chart is the thing a client actually looks at. A
native chart part would need an embedded workbook and a second schema to get
wrong; a line drawn as a path is the same picture, renders identically
everywhere, and cannot corrupt the file.

The design rules the whole thing follows, so that adding a slide does not mean
inventing a look for it:

* **Dark, light, dark.** The cover and the closing are deep navy, the section
  dividers are too, and everything between them is white. That sandwich is what
  makes a deck read as a deck rather than as a run of pages.
* **One number is the point of any slide that has numbers on it.** Figures are
  set at 54pt against 10pt labels, because a headline at 18pt is not a headline.
* **No rule under a title, no stripe down the edge.** Space separates things.
* **Every slide carries something drawn** — a gauge, a curve, bars, a bar chart
  of dates. A slide of text is one nobody remembers.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Any, Iterable, Mapping, Sequence
from xml.sax.saxutils import escape

# English Metric Units: 914400 to the inch. A 16:9 slide, which is what a
# projector and a laptop both are now.
EMU = 914400
WIDTH = int(13.333 * EMU)
HEIGHT = int(7.5 * EMU)

MARGIN = int(0.75 * EMU)
COLUMN = WIDTH - 2 * MARGIN
BODY_TOP = int(1.85 * EMU)
FOOT = int(6.85 * EMU)

# The palette. A port programme, not a software product: deep water blue, the
# shallower teal beside it, and midnight for the dark slides. Semantic green and
# red are dark enough to sit with them rather than shout over them.
NAVY = "13293D"          # the dark slides
DEEP = "065A82"          # primary
TEAL = "1C7293"          # secondary
MIST = "9FB8C8"          # light type on dark
INK = "1B2A33"           # body text
MUTED = "6E7F8D"         # labels and captions
FAINT = "E8EDF1"         # hairlines and grid
WASH = "F5F8FA"          # the one background tint
GOOD = "1E7A5F"
BAD = "B3352B"
WARN = "B87503"

# Kept for anything that imported them by their old names.
ACCENT = DEEP
RULE = FAINT

HEAD_FONT = "Cambria"    # a serif head against a sans body: contrast, no risk
BODY_FONT = "Calibri"

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _t(value: Any) -> str:
    return escape(str(value if value is not None else ""))


def _num(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


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

def _run(text: str, size: float, bold: bool = False, colour: str = INK,
         italic: bool = False, font: str = BODY_FONT, spacing: int = 0) -> str:
    """One run of text. `spacing` is letter-spacing in hundredths of a point,
    which is what turns a small upper-case label into a label rather than into
    shouting."""
    return (f'<a:r><a:rPr lang="en-GB" sz="{int(size * 100)}" b="{1 if bold else 0}" '
            f'i="{1 if italic else 0}" spc="{spacing}" dirty="0">'
            f'<a:solidFill><a:srgbClr val="{colour}"/></a:solidFill>'
            f'<a:latin typeface="{font}"/><a:cs typeface="{font}"/></a:rPr>'
            f'<a:t>{_t(text)}</a:t></a:r>')


def _para(text: str, size: float, bold: bool = False, colour: str = INK,
          bullet: bool = False, align: str = "l", space_before: int = 0,
          italic: bool = False, font: str = BODY_FONT, spacing: int = 0,
          line: int = 0) -> str:
    marker = ('<a:buFont typeface="Arial"/><a:buChar char="•"/>' if bullet
              else "<a:buNone/>")
    indent = ' marL="228600" indent="-228600"' if bullet else ' marL="0" indent="0"'
    before = f'<a:spcBef><a:spcPts val="{space_before * 100}"/></a:spcBef>' if space_before else ""
    leading = f'<a:lnSpc><a:spcPct val="{line * 1000}"/></a:lnSpc>' if line else ""
    return (f'<a:p><a:pPr{indent} algn="{align}">{leading}{before}{marker}</a:pPr>'
            f'{_run(text, size, bold, colour, italic, font, spacing)}</a:p>')


def _label(text: str, colour: str = MUTED, size: float = 10,
           align: str = "l") -> str:
    """A small upper-case label: the one piece of typographic furniture the
    whole deck uses, so a figure never needs a box drawn round it to read as
    one."""
    return _para(str(text).upper(), size, True, colour, spacing=120, align=align)


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


def _shape(shape_id: int, x: int, y: int, cx: int, cy: int, geometry: str,
           fill: str = "", line: str = "", width: int = 12700,
           name: str = "Shape") -> str:
    """One shape of any preset geometry, filled, outlined or both."""
    body = (f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill
            else "<a:noFill/>")
    stroke = (f'<a:ln w="{width}" cap="rnd"><a:solidFill><a:srgbClr val="{line}"/>'
              f'</a:solidFill><a:round/></a:ln>' if line else "<a:ln><a:noFill/></a:ln>")
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{shape_id}" name="{_t(name)} {shape_id}"/>'
        f'<p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'{geometry}{body}{stroke}</p:spPr>'
        f'<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>'
    )


def _rect(shape_id: int, x: int, y: int, cx: int, cy: int, fill: str,
          line: str = "", radius: int = 0) -> str:
    geometry = (f'<a:prstGeom prst="roundRect"><a:avLst>'
                f'<a:gd name="adj" fmla="val {radius}"/></a:avLst></a:prstGeom>'
                if radius else '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>')
    return _shape(shape_id, x, y, cx, cy, geometry, fill, line, name="Block")


# The path space every drawn chart works in. Big enough that rounding to whole
# units never shows at projector size.
GRID = 100000


def _path(points: Sequence[tuple[float, float]], closed: bool = False) -> str:
    """A polyline through points given as fractions of the shape, 0-1, with
    y measured downwards as everything in OOXML is."""
    if not points:
        return ""
    steps = [f'<a:moveTo><a:pt x="{int(points[0][0] * GRID)}" '
             f'y="{int(points[0][1] * GRID)}"/></a:moveTo>']
    for x, y in points[1:]:
        steps.append(f'<a:lnTo><a:pt x="{int(x * GRID)}" y="{int(y * GRID)}"/></a:lnTo>')
    if closed:
        steps.append("<a:close/>")
    return (f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/>'
            f'<a:rect l="0" t="0" r="r" b="b"/><a:pathLst>'
            f'<a:path w="{GRID}" h="{GRID}">{"".join(steps)}</a:path>'
            f'</a:pathLst></a:custGeom>')


def _line(shape_id: int, x: int, y: int, cx: int, cy: int,
          points: Sequence[tuple[float, float]], colour: str,
          width: int = 28575, name: str = "Line") -> str:
    return _shape(shape_id, x, y, cx, cy, _path(points), "", colour, width, name)


def _area(shape_id: int, x: int, y: int, cx: int, cy: int,
          points: Sequence[tuple[float, float]], colour: str,
          name: str = "Area") -> str:
    """The same curve, closed to the baseline and filled — what makes a curve
    read as a quantity rather than as a squiggle."""
    if not points:
        return ""
    closed = [(points[0][0], 1.0), *points, (points[-1][0], 1.0)]
    return _shape(shape_id, x, y, cx, cy, _path(closed, closed=True), colour,
                  "", name=name)


def _cell(text: str, size: float, bold: bool, colour: str, align: str,
          fill: str, rule: str = "") -> str:
    edge = (f'<a:lnB w="9525" cap="flat"><a:solidFill><a:srgbClr val="{rule}"/>'
            f'</a:solidFill></a:lnB>' if rule else "")
    shade = (f'<a:solidFill><a:srgbClr val="{fill}"/></a:solidFill>' if fill
             else "<a:noFill/>")
    return (f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/>'
            f'{_para(text, size, bold, colour, align=align)}</a:txBody>'
            f'<a:tcPr marL="0" marR="137160" marT="68580" marB="68580" anchor="ctr">'
            f'{edge}{shade}</a:tcPr></a:tc>')


def _table(shape_id: int, x: int, y: int, cx: int,
           headings: Sequence[str], rows: Sequence[Sequence[Any]],
           widths: Sequence[float] | None = None,
           right_from: int = 1, row_height: int = int(0.36 * EMU)) -> str:
    """A table with no fill on it.

    The heading is a small label with a rule under it and the rows are separated
    by hairlines — the same table the app draws on screen. A blue block behind
    white headings is what a table looks like when somebody has reached for the
    default.
    """
    columns = len(headings)
    share = list(widths or [1.0] * columns)
    total = sum(share) or 1
    sizes = [int(cx * part / total) for part in share]

    grid = "".join(f'<a:gridCol w="{width}"/>' for width in sizes)
    head = "".join(_cell(str(text).upper(), 9, True, MUTED,
                         "r" if index >= right_from else "l", "", DEEP)
                   for index, text in enumerate(headings))
    body = []
    for row in rows:
        body.append(f'<a:tr h="{row_height}">' + "".join(
            _cell(value, 12, False, INK, "r" if index >= right_from else "l",
                  "", FAINT)
            for index, value in enumerate(row)) + "</a:tr>")

    height = row_height * (len(rows) + 1)
    return (
        f'<p:graphicFrame><p:nvGraphicFramePr>'
        f'<p:cNvPr id="{shape_id}" name="Table {shape_id}"/>'
        f'<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr>'
        f'<p:nvPr/></p:nvGraphicFramePr>'
        f'<p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{height}"/></p:xfrm>'
        f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
        f'<a:tbl><a:tblPr firstRow="1"/><a:tblGrid>{grid}</a:tblGrid>'
        f'<a:tr h="{row_height}">{head}</a:tr>{"".join(body)}</a:tbl>'
        f'</a:graphicData></a:graphic></p:graphicFrame>'
    )


def _slide(shapes: Sequence[str], background: str = "") -> str:
    ground = (f'<p:bg><p:bgPr><a:solidFill><a:srgbClr val="{background}"/></a:solidFill>'
              f'<a:effectLst/></p:bgPr></p:bg>' if background else "")
    return (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<p:sld xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld>{ground}<p:spTree>'
        f'<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
        f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
        f'<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
        f'{"".join(shapes)}</p:spTree></p:cSld>'
        f'<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>'
    )


class Deck:
    """A deck, built a slide at a time and saved as bytes."""

    def __init__(self, footer: str = "") -> None:
        self.slides: list[tuple[str, str]] = []      # (xml, background)
        self.footer = footer
        self.section = ""

    # --- the dark slides ----------------------------------------------------

    def cover(self, title: str, subtitle: str = "", note: str = "") -> "Deck":
        """The first slide. Deep navy, one line at 46pt, and nothing else —
        a cover that says four things says none of them."""
        shapes = [
            _textbox(2, "Eyebrow", MARGIN, int(1.5 * EMU), COLUMN, int(0.4 * EMU),
                     [_label(subtitle, MIST, 12)]),
            _textbox(3, "Title", MARGIN, int(2.35 * EMU), int(COLUMN * 0.82),
                     int(2.6 * EMU),
                     [_para(title, 46, True, "FFFFFF", font=HEAD_FONT, line=105)]),
        ]
        if note:
            shapes.append(_textbox(4, "Note", MARGIN, int(5.6 * EMU), int(COLUMN * 0.6),
                                   int(1.0 * EMU),
                                   [_para(note, 13, False, MIST, line=145)]))
        return self._add(shapes, numbered=False, background=NAVY)

    def divider(self, number: int, title: str, subtitle: str = "") -> "Deck":
        """A section opener. The big ghosted numeral is the deck's one motif,
        and it is what makes the middle of a long deck navigable."""
        self.section = title
        shapes = [
            _textbox(2, "Numeral", MARGIN, int(1.15 * EMU), int(4.0 * EMU),
                     int(3.6 * EMU),
                     [_para(f"{number:02d}", 150, True, "1D3B53", font=HEAD_FONT)]),
            _textbox(3, "Title", MARGIN, int(4.35 * EMU), int(COLUMN * 0.8),
                     int(1.1 * EMU),
                     [_para(title, 34, True, "FFFFFF", font=HEAD_FONT)]),
        ]
        if subtitle:
            shapes.append(_textbox(4, "Subtitle", MARGIN, int(5.45 * EMU),
                                   int(COLUMN * 0.72), int(0.9 * EMU),
                                   [_para(subtitle, 14, False, MIST, line=140)]))
        return self._add(shapes, numbered=False, background=NAVY)

    def closing(self, headline: str, lines: Sequence[str] = (), note: str = "") -> "Deck":
        shapes = [
            _textbox(2, "Headline", MARGIN, int(2.0 * EMU), int(COLUMN * 0.54),
                     int(3.2 * EMU),
                     [_para(headline, 32, True, "FFFFFF", font=HEAD_FONT, line=118)]),
        ]
        written = []
        for line in list(lines)[:5]:
            written.append(_para(str(line), 15, False, MIST, space_before=14, line=130))
        if written:
            shapes.append(_textbox(3, "Lines", MARGIN + int(COLUMN * 0.64),
                                   int(2.1 * EMU), int(COLUMN * 0.36), int(3.6 * EMU),
                                   written))
        if note:
            shapes.append(_textbox(4, "Note", MARGIN, int(6.4 * EMU), COLUMN,
                                   int(0.5 * EMU), [_label(note, "5B7285", 10)]))
        return self._add(shapes, numbered=False, background=NAVY)

    # --- the light slides ---------------------------------------------------

    def figures(self, title: str, blocks: Sequence[Mapping[str, Any]],
                note: str = "") -> "Deck":
        """A row of headline numbers.

        No boxes: a hairline over each one, the label above it and the figure at
        54pt. A number in a bordered tile reads as a form field; a number with
        air round it reads as the point of the slide.
        """
        shapes = list(self._head(title))
        count = max(1, min(len(blocks), 4))
        gap = int(0.45 * EMU)
        width = (COLUMN - gap * (count - 1)) // count
        top = BODY_TOP + int(0.5 * EMU)

        shape_id = 10
        for index, block in enumerate(blocks[:count]):
            x = MARGIN + index * (width + gap)
            shapes.append(_textbox(
                shape_id, f"Figure {index}", x, top, width, int(2.4 * EMU),
                [_label(block.get("label", "")),
                 _para(str(block.get("value", "")), 54, True,
                       str(block.get("colour") or INK), space_before=10,
                       font=HEAD_FONT),
                 _para(str(block.get("hint", "")), 12, False, MUTED,
                       space_before=8, line=130)]))
            shape_id += 1

        if note:
            shapes.append(_textbox(shape_id, "Note", MARGIN, int(5.35 * EMU),
                                   int(COLUMN * 0.78), int(1.2 * EMU),
                                   [_para(note, 15, False, INK, line=140)]))
        return self._add(shapes)

    def curve(self, title: str, series: Sequence[Mapping[str, Any]],
              marks: Sequence[Mapping[str, Any]] = (), note: str = "",
              caption: str = "") -> "Deck":
        """Two curves against each other, drawn rather than tabulated.

        Each series is {name, colour, points: [(x, y)]} with x and y from 0 to
        1 — the caller decides what the axes mean, because this knows nothing
        about dates or percentages.
        """
        shapes = list(self._head(title, caption))
        # The plot is inset from the margin to leave room for the percentages
        # down its left, which otherwise sit in the slide's own edge.
        left = MARGIN + int(0.55 * EMU)
        top = BODY_TOP + int(0.35 * EMU)
        width, height = int((COLUMN - int(0.55 * EMU)) * 0.78), int(3.6 * EMU)

        # Four gridlines and their labels. Fewer than five, so the eye reads
        # the shape of the curve rather than the ruling behind it.
        shape_id = 10
        for step in range(5):
            y = top + int(height * step / 4)
            shapes.append(_shape(shape_id, left, y, width, 9525,
                                 '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
                                 FAINT if step < 4 else MUTED, name="Grid"))
            shapes.append(_textbox(shape_id + 1, f"Tick {step}",
                                   left - int(0.62 * EMU), y - int(0.09 * EMU),
                                   int(0.5 * EMU), int(0.22 * EMU),
                                   [_para(f"{100 - step * 25}%", 9, False, MUTED,
                                          align="r")]))
            shape_id += 2

        for line in series:
            points = [(float(x), 1.0 - float(y)) for x, y in line.get("points") or ()]
            if len(points) < 2:
                continue
            colour = str(line.get("colour") or DEEP)
            if line.get("fill"):
                shapes.append(_area(shape_id, left, top, width, height, points,
                                    str(line["fill"])))
                shape_id += 1
            shapes.append(_line(shape_id, left, top, width, height, points, colour,
                                int(line.get("width") or 28575)))
            shape_id += 1

        # A dotted vertical at a date worth naming — today, usually.
        for mark in marks:
            at = min(1.0, max(0.0, _num(mark.get("at"))))
            x = left + int(width * at)
            shapes.append(_shape(shape_id, x, top, 9525, height,
                                 '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
                                 str(mark.get("colour") or MUTED), name="Mark"))
            label_at = min(max(x - int(0.7 * EMU), left), left + width - int(1.4 * EMU))
            shapes.append(_textbox(shape_id + 1, "Mark label", label_at,
                                   top + height + int(0.08 * EMU), int(1.4 * EMU),
                                   int(0.25 * EMU),
                                   [_label(mark.get("label", ""), MUTED, 9,
                                           align="ctr" if label_at != left else "l")]))
            shape_id += 2

        # The legend and the note share the right-hand column, so the chart
        # keeps the whole of the left and nothing is stacked under it.
        rail = left + width + int(0.55 * EMU)
        rail_width = WIDTH - MARGIN - rail
        for index, line in enumerate(series):
            y = top + index * int(0.62 * EMU)
            shapes.append(_shape(shape_id, rail, y + int(0.06 * EMU), int(0.16 * EMU),
                                 int(0.16 * EMU),
                                 '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
                                 str(line.get("colour") or DEEP), name="Swatch"))
            shapes.append(_textbox(shape_id + 1, f"Legend {index}",
                                   rail + int(0.28 * EMU), y, rail_width, int(0.6 * EMU),
                                   [_para(str(line.get("name") or ""), 13, True, INK),
                                    _para(str(line.get("hint") or ""), 11, False, MUTED,
                                          line=130)]))
            shape_id += 2
        if note:
            shapes.append(_textbox(shape_id, "Note", rail,
                                   top + len(list(series)) * int(0.62 * EMU)
                                   + int(0.3 * EMU),
                                   rail_width, int(2.0 * EMU),
                                   [_para(note, 12, False, INK, line=145)]))

        return self._add(shapes)

    def bars(self, title: str, rows: Sequence[Mapping[str, Any]], note: str = "",
             caption: str = "") -> "Deck":
        """A horizontal bar for each row: {label, value, shown, colour}.

        Horizontal because the labels are trade names and deliverable numbers,
        and a column chart with the names turned sideways is a chart nobody
        reads.
        """
        shapes = list(self._head(title, caption))
        rows = list(rows)[:8]
        if not rows:
            return self._nothing(shapes, "Nothing to show for this period")

        biggest = max((_num(row.get("value")) for row in rows), default=0.0) or 1.0
        top = BODY_TOP + int(0.45 * EMU)
        room = int(4.0 * EMU)
        pitch = min(int(0.62 * EMU), room // max(1, len(rows)))
        thick = int(pitch * 0.46)
        names = int(COLUMN * 0.30)
        track = COLUMN - names - int(1.35 * EMU)

        shape_id = 10
        for index, row in enumerate(rows):
            y = top + index * pitch
            shapes.append(_textbox(shape_id, f"Bar label {index}", MARGIN,
                                   y + int(thick * 0.1), names - int(0.2 * EMU),
                                   int(0.3 * EMU),
                                   [_para(str(row.get("label", ""))[:46], 12, False, INK)]))
            length = max(int(track * _num(row.get("value")) / biggest), 9525)
            shapes.append(_shape(shape_id + 1, MARGIN + names, y, track, thick,
                                 '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
                                 WASH, name="Track"))
            shapes.append(_shape(shape_id + 2, MARGIN + names, y, length, thick,
                                 '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
                                 str(row.get("colour") or DEEP), name="Bar"))
            shapes.append(_textbox(shape_id + 3, f"Bar value {index}",
                                   MARGIN + names + track + int(0.15 * EMU),
                                   y + int(thick * 0.1), int(1.15 * EMU),
                                   int(0.3 * EMU),
                                   [_para(str(row.get("shown", "")), 12, True,
                                          str(row.get("colour") or INK))]))
            shape_id += 4

        if note:
            shapes.append(_textbox(shape_id, "Note", MARGIN,
                                   top + len(rows) * pitch + int(0.35 * EMU),
                                   int(COLUMN * 0.8), int(0.9 * EMU),
                                   [_para(note, 13, False, MUTED, line=140)]))
        return self._add(shapes)

    def timeline(self, title: str, rows: Sequence[Mapping[str, Any]],
                 first: str, last: str, marks: Sequence[Mapping[str, Any]] = (),
                 note: str = "", caption: str = "",
                 shown: Sequence[str] = ()) -> "Deck":
        """A strip of dated bars — the critical path as a picture.

        Each row is {label, from, to, colour, shown} with dates as ISO strings.
        A run of dates in a table is a list of numbers; the same run drawn is
        the answer to "how long is this going to take".
        """
        from datetime import date

        def day(value: Any) -> date | None:
            try:
                return date.fromisoformat(str(value)[:10])
            except (TypeError, ValueError):
                return None

        opens, closes = day(first), day(last)
        rows = [r for r in list(rows)[:9] if day(r.get("from")) and day(r.get("to"))]
        if not opens or not closes or closes <= opens or not rows:
            return self._nothing(list(self._head(title, caption)),
                                 "Nothing is sequenced yet")

        span = (closes - opens).days or 1
        shapes = list(self._head(title, caption))
        top = BODY_TOP + int(0.55 * EMU)
        room = int(3.7 * EMU)
        pitch = min(int(0.5 * EMU), room // max(1, len(rows)))
        thick = int(pitch * 0.5)
        names = int(COLUMN * 0.34)
        track = COLUMN - names

        def across(value: Any) -> float:
            found = day(value)
            return min(1.0, max(0.0, ((found - opens).days / span) if found else 0.0))

        shape_id = 10
        for index, row in enumerate(rows):
            y = top + index * pitch
            shapes.append(_textbox(shape_id, f"Row {index}", MARGIN,
                                   y + int(thick * 0.05), names - int(0.2 * EMU),
                                   int(0.3 * EMU),
                                   [_para(str(row.get("label", ""))[:52], 11, False, INK)]))
            begins, ends = across(row.get("from")), across(row.get("to"))
            x = MARGIN + names + int(track * begins)
            length = max(int(track * (ends - begins)), int(0.07 * EMU))
            shapes.append(_shape(shape_id + 1, x, y, length, thick,
                                 '<a:prstGeom prst="roundRect"><a:avLst>'
                                 '<a:gd name="adj" fmla="val 24000"/></a:avLst></a:prstGeom>',
                                 str(row.get("colour") or DEEP), name="Bar"))
            shape_id += 2

        # The axis under it: the two ends, and anything worth naming between.
        base = top + len(rows) * pitch + int(0.12 * EMU)
        shapes.append(_shape(shape_id, MARGIN + names, base, track, 9525,
                             '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
                             FAINT, name="Axis"))
        shape_id += 1
        ends = tuple(shown) if len(tuple(shown)) == 2 else (first, last)
        for mark in ({"at": 0.0, "label": ends[0]}, {"at": 1.0, "label": ends[1]},
                     *[dict(m, at=across(m.get("on"))) for m in marks]):
            at = min(1.0, max(0.0, _num(mark.get("at"))))
            x = MARGIN + names + int(track * at)
            if mark.get("on"):
                shapes.append(_shape(shape_id, x, top, 9525,
                                     base - top, '<a:prstGeom prst="rect"><a:avLst/>'
                                     '</a:prstGeom>', str(mark.get("colour") or BAD),
                                     name="Today"))
                shape_id += 1
            shapes.append(_textbox(shape_id, "Axis label", x - int(0.6 * EMU),
                                   base + int(0.08 * EMU), int(1.2 * EMU),
                                   int(0.25 * EMU),
                                   [_label(mark.get("label", ""), MUTED, 9)]))
            shape_id += 1

        if note:
            shapes.append(_textbox(shape_id, "Note", MARGIN, base + int(0.55 * EMU),
                                   int(COLUMN * 0.8), int(0.9 * EMU),
                                   [_para(note, 13, False, MUTED, line=140)]))
        return self._add(shapes)

    def gauge(self, title: str, percent: float, headline: str,
              blocks: Sequence[Mapping[str, Any]] = (), note: str = "",
              caption: str = "") -> "Deck":
        """A half-ring dial with the figure in it, and stats down the side.

        A semicircle rather than a full ring: it has an unambiguous start and
        end, which is what a percentage complete actually is.
        """
        shapes = list(self._head(title, caption))
        share = min(1.0, max(0.0, _num(percent)))
        size = int(3.5 * EMU)
        left, top = MARGIN + int(0.15 * EMU), BODY_TOP + int(0.35 * EMU)

        # blockArc measures in sixty-thousandths of a degree from three
        # o'clock, clockwise. Half a turn from nine o'clock to three is 180° to
        # 360°, which never wraps past zero and so cannot come out inside out.
        def arc(shape_id: int, to: float, colour: str) -> str:
            end = 10800000 + int(10800000 * min(1.0, max(0.0, to)))
            return _shape(shape_id, left, top, size, size,
                          f'<a:prstGeom prst="blockArc"><a:avLst>'
                          f'<a:gd name="adj1" fmla="val 10800000"/>'
                          f'<a:gd name="adj2" fmla="val {end}"/>'
                          f'<a:gd name="adj3" fmla="val 17000"/></a:avLst></a:prstGeom>',
                          colour, name="Arc")

        shapes.append(arc(10, 1.0, FAINT))
        if share > 0.004:
            shapes.append(arc(11, share, DEEP))
        shapes.append(_textbox(12, "Gauge figure", left, top + int(size * 0.34),
                               size, int(1.2 * EMU),
                               [_para(f"{share * 100:.0f}%", 44, True, INK,
                                      align="ctr", font=HEAD_FONT)]))
        shapes.append(_textbox(13, "Gauge label", left, top + int(size * 0.58),
                               size, int(0.4 * EMU),
                               [_label(headline, MUTED, 10)]))

        # The figures sit beside it in their own column, spread over the whole
        # height of the dial so the slide is not top-heavy.
        rail = MARGIN + size + int(1.2 * EMU)
        rail_width = WIDTH - MARGIN - rail
        shown = list(blocks)[:3]
        shape_id = 20
        for index, block in enumerate(shown):
            y = top + index * int(1.15 * EMU)
            shapes.append(_textbox(shape_id, f"Stat {index}", rail, y, rail_width,
                                   int(1.2 * EMU),
                                   [_label(block.get("label", "")),
                                    _para(str(block.get("value", "")), 30, True,
                                          str(block.get("colour") or INK),
                                          space_before=4, font=HEAD_FONT),
                                    _para(str(block.get("hint", "")), 11, False, MUTED,
                                          space_before=2)]))
            shape_id += 1

        if note:
            shapes.append(_textbox(shape_id, "Note", MARGIN, int(6.05 * EMU),
                                   int(COLUMN * 0.86), int(0.6 * EMU),
                                   [_para(note, 13, False, MUTED, line=140)]))
        return self._add(shapes)

    def bullets(self, title: str, lines: Iterable[Any], note: str = "",
                caption: str = "") -> "Deck":
        """Numbered rows rather than a bulleted list: each one gets its number
        in the margin, which is what stops eight lines reading as a wall."""
        shapes = list(self._head(title, caption))
        written = [str(line) for line in list(lines)[:7]]
        if not written:
            return self._nothing(shapes, "Nothing falls due")

        top = BODY_TOP + int(0.4 * EMU)
        pitch = min(int(0.66 * EMU), int(4.2 * EMU) // max(1, len(written)))
        shape_id = 10
        for index, line in enumerate(written):
            y = top + index * pitch
            shapes.append(_textbox(shape_id, f"Number {index}", MARGIN, y,
                                   int(0.6 * EMU), int(0.4 * EMU),
                                   [_para(f"{index + 1:02d}", 16, True, MIST,
                                          font=HEAD_FONT)]))
            shapes.append(_textbox(shape_id + 1, f"Line {index}",
                                   MARGIN + int(0.72 * EMU), y,
                                   COLUMN - int(0.72 * EMU), int(0.55 * EMU),
                                   [_para(line, 15, False, INK, line=130)]))
            shape_id += 2

        if note:
            shapes.append(_textbox(shape_id, "Note", MARGIN,
                                   top + len(written) * pitch + int(0.3 * EMU),
                                   COLUMN, int(0.5 * EMU),
                                   [_para(note, 12, False, MUTED, italic=True)]))
        return self._add(shapes)

    def table(self, title: str, headings: Sequence[str], rows: Sequence[Sequence[Any]],
              widths: Sequence[float] | None = None, right_from: int = 1,
              note: str = "", caption: str = "") -> "Deck":
        shapes = list(self._head(title, caption))
        if not rows:
            return self._nothing(shapes, "Nothing in this period")
        shapes.append(_table(10, MARGIN, BODY_TOP + int(0.25 * EMU), COLUMN,
                             headings, rows, widths, right_from))
        if note:
            shapes.append(_textbox(11, "Note", MARGIN, int(6.4 * EMU),
                                   COLUMN, int(0.5 * EMU),
                                   [_para(note, 12, False, MUTED, italic=True)]))
        return self._add(shapes)

    # --- the plumbing -------------------------------------------------------

    def _nothing(self, shapes: list[str], said: str) -> "Deck":
        """An empty slide still says what is empty, and says it once."""
        shapes.append(_textbox(80, "Empty", MARGIN, BODY_TOP + int(0.6 * EMU),
                               COLUMN, int(0.7 * EMU),
                               [_para(said, 18, False, MUTED, font=HEAD_FONT)]))
        return self._add(shapes)

    def _head(self, title: str, caption: str = "") -> list[str]:
        """The heading of a light slide: the section in small caps above, the
        title at 30pt, and no rule under either of them."""
        shapes = []
        if self.section:
            shapes.append(_textbox(2, "Section", MARGIN, int(0.62 * EMU), COLUMN,
                                   int(0.3 * EMU), [_label(self.section, TEAL, 10)]))
        shapes.append(_textbox(3, "Heading", MARGIN, int(1.02 * EMU),
                               int(COLUMN * 0.75), int(0.65 * EMU),
                               [_para(title, 30, True, INK, font=HEAD_FONT)]))
        if caption:
            shapes.append(_textbox(4, "Caption", MARGIN + int(COLUMN * 0.76),
                                   int(1.12 * EMU), int(COLUMN * 0.24),
                                   int(0.6 * EMU),
                                   [_para(caption, 12, False, MUTED, align="r",
                                          line=130)]))
        return shapes

    def _add(self, shapes: Sequence[str], numbered: bool = True,
             background: str = "") -> "Deck":
        drawn = list(shapes)
        if numbered:
            drawn.append(_shape(89, MARGIN, FOOT - int(0.16 * EMU), COLUMN, 9525,
                                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>',
                                FAINT, name="Footrule"))
            drawn.append(_textbox(
                90, "Footer", MARGIN, FOOT, int(COLUMN * 0.8), int(0.3 * EMU),
                [_para(self.footer, 9, False, MUTED, spacing=40)]))
            drawn.append(_textbox(
                91, "Number", MARGIN + int(COLUMN * 0.8), FOOT, int(COLUMN * 0.2),
                int(0.3 * EMU),
                [_para(str(len(self.slides) + 1), 9, True, MUTED, align="r")]))
        self.slides.append((_slide(drawn, background), background))
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
            for number, (slide, _ground) in enumerate(self.slides, start=1):
                book.writestr(f"ppt/slides/slide{number}.xml", slide)
                book.writestr(f"ppt/slides/_rels/slide{number}.xml.rels", _SLIDE_RELS)
        return held.getvalue()
