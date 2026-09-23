"""The client's Document Review Response form, read in and written back out.

The form is theirs, not ours. It arrives as a workbook with their letterhead in
it, their reference numbers, their wording of the assessment codes, and a table
whose columns are split between who may fill them in: the reviewer writes the
comment, we write the response, and the reviewer signs it off. What goes back
has to be that same workbook with our column filled in — not a copy of it, not
something that looks like it.

So reading and writing are done by different means on purpose.

**Reading** uses openpyxl, which is good at values and does not care what else
is in the file. Columns are found by their headings rather than their letters,
because the same form is issued with a column inserted from time to time and a
position hard-coded here would put every response in the wrong place.

**Writing patches the workbook's XML inside its own zip**, copying every other
part across byte for byte. This is the part worth being stubborn about: loading
this form with openpyxl and saving it again silently drops the drawings, both
logo images, the printer settings and the sheet's relationships. The client
would get back a form with their letterhead missing. Editing the one worksheet
part and leaving the rest alone keeps all of it, because the rest never gets
rewritten.

Values are written as inline strings. That keeps the shared string table out of
it, which is one fewer part to rewrite and one fewer way to corrupt a file
somebody has to open in front of their client.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping, Sequence
from xml.sax.saxutils import escape

import openpyxl

from .crs_sheet import CODES, normalise_code

# A blank form to start from, for a sheet raised in the app rather than
# uploaded. It is a real issued form with its rows emptied, so what goes out is
# the client's own document either way.
BLANK = Path(__file__).resolve().parent / "forms" / "review-response.xlsx"

# What a browser and a host should call one of these.
MIMETYPE = ("application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet")

# The columns of the comment table, by what the heading says rather than where
# it sits. First match wins, so the more particular wording goes first.
COLUMNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sn", ("s/n", "s.n", "sr no", "serial", "item no", "no.")),
    ("reviewer", ("reviewer's name", "reviewer name", "reviewer", "organization")),
    ("source", ("identification of comment", "source", "title /page", "clause")),
    ("observation", ("observations", "observation", "comments")),
    ("discipline", ("discipline",)),
    ("reference", ("reference number of doc", "reference number", "reference")),
    ("returned_code", ("returned code", "return code", "code")),
    ("response", ("response", "reply")),
    ("signoff", ("sign-off", "sign off", "signoff", "open/closed", "status")),
)

# The general information block, by the label in the cell to its left.
INFO: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("program", ("program name", "programme name")),
    ("project_name", ("project name",)),
    ("contractor", ("contractor",)),
    ("project_code", ("project code",)),
    ("report_no", ("report no",)),
    ("report_date", ("report date",)),
    ("contract_no", ("contract no",)),
    ("drf_ref", ("drf ref",)),
    ("drf_rev", ("drf rev",)),
    ("drf_date", ("drf date",)),
    ("stage", ("project stage",)),
    ("engineer", ("engineer in charge",)),
    ("discipline", ("discipline:",)),
    ("title", ("doc or dwg title", "document title")),
)

# Ours to fill in. The rest of the table is the reviewer's, and writing to it
# would be answering a comment by changing it.
MINE = ("response", "returned_code", "signoff")


class SheetError(ValueError):
    """A workbook that is not one of these forms, said in words."""


def _words(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _cell(value: Any) -> str:
    """A cell as text, with the times Excel adds to a date taken back off."""
    if value is None:
        return ""
    text = str(value).strip()
    return text[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2} 00:00:00", text) else text


def read(data: bytes) -> dict[str, Any]:
    """The form's header and its comments.

    Raises :class:`SheetError` for a workbook with no comment table in it,
    which is nearly always somebody uploading the wrong file.
    """
    try:
        book = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    except Exception as exc:                          # noqa: BLE001 - said in words below
        raise SheetError(f"That file would not open as a workbook: {exc}") from exc

    page = book.active
    header = _header_row(page)
    if header is None:
        raise SheetError(
            "No comment table found. The sheet should have a row of headings with "
            "“S/N” and “Observations / Comments” on it.")

    columns = _columns(page, header)
    missing = {"sn", "observation"} - set(columns)
    if missing:
        raise SheetError("The comment table has no “Observations / Comments” column.")

    info, info_at = _info(page, header)
    return {
        "info": info,
        # Where each of those values sits, so the same form can be filled in
        # for a sheet raised here rather than uploaded.
        "info_at": info_at,
        "columns": columns,
        "header_row": header,
        "comments": _comments(page, header, columns),
        "overall_code": _overall(page, header),
        "overall_at": _overall_at(page, header),
        "sheet_name": page.title,
    }


def _header_row(page: Any) -> int | None:
    """The row the comment table's headings are on."""
    for row in range(1, min(page.max_row, 80) + 1):
        said = {_words(page.cell(row=row, column=col).value)
                for col in range(1, min(page.max_column, 30) + 1)}
        if any(word in said for word in ("s/n", "s.n", "no.")) and \
                any("observation" in word or "comments" in word for word in said if word):
            return row
    return None


def _columns(page: Any, header: int) -> dict[str, int]:
    """Which column each field is in, by what its heading says."""
    out: dict[str, int] = {}
    for col in range(1, min(page.max_column, 30) + 1):
        said = _words(page.cell(row=header, column=col).value)
        if not said:
            continue
        for field, patterns in COLUMNS:
            if field in out:
                continue
            if any(said.startswith(p) or p in said for p in patterns):
                out[field] = col
                break
    return out


# Every wording the information block uses as a label, so a value is not
# mistaken for one on the way past. "Project Code" sits to the right of
# "Program Name"'s value, and without this the scan would stop on it.
ALL_LABELS: tuple[str, ...] = tuple(
    pattern for _field, patterns in INFO for pattern in patterns
) + ("assessment code", "supervision consultant", "contractor", "sign-off")


def _is_label(said: str) -> bool:
    return any(said.startswith(pattern) for pattern in ALL_LABELS)


def _info(page: Any, header: int) -> tuple[dict[str, str], dict[str, str]]:
    """The general information block, read by its labels.

    The value sits in the cell to the right of its label, which may be the
    start of a merged run — so the scan goes rightwards to the first thing with
    writing in it that is not itself another label.

    Returns what each field says and the cell it says it in. A blank form has
    the labels but no values, so the coordinate is found from the label rather
    than from finding something written there: it is the only way a form nobody
    has filled in can be filled in.
    """
    said_at: dict[tuple[int, int], str] = {}
    for row in range(1, header):
        for col in range(1, min(page.max_column, 20) + 1):
            said = _words(page.cell(row=row, column=col).value)
            if said:
                said_at[(row, col)] = said

    out: dict[str, str] = {}
    where: dict[str, str] = {}
    for field, patterns in INFO:
        for (row, col), said in sorted(said_at.items()):
            if field in where or not any(said.startswith(p) for p in patterns):
                continue
            # Past the end of the label's own merged run: "Program Name" is
            # written across two cells, and the second of them is not where its
            # value goes.
            at_col = _span_end(page, row, col) + 1
            while at_col <= min(page.max_column, 20):
                said_here = said_at.get((row, at_col), "")
                if said_here and _is_label(said_here):
                    break                              # the next label along
                value = _cell(page.cell(row=row, column=at_col).value)
                where[field] = f"{_letter(at_col)}{row}"
                if value:
                    out[field] = value
                break
    return out, where


def _span_end(page: Any, row: int, col: int) -> int:
    """The last column of the merged run this cell is part of, or its own."""
    for span in page.merged_cells.ranges:
        if span.min_row <= row <= span.max_row and span.min_col <= col <= span.max_col:
            return int(span.max_col)
    return col


def _overall(page: Any, header: int) -> str:
    """The assessment code for the submission as a whole, above the table."""
    at = _overall_at(page, header)
    if not at:
        return ""
    found = re.match(r"([A-Z]+)(\d+)", at)
    col = sum((ord(ch) - 64) * 26 ** n
              for n, ch in enumerate(reversed(found.group(1))))
    return _cell(page.cell(row=int(found.group(2)), column=col).value)


# How the form words the sentence the overall code sits beside.
STATEMENT = ("reviewed under this drf", "return code and actions", "hereby return")


def _overall_at(page: Any, header: int) -> str:
    """Where that code sits: the cell just past the statement above the table.

    Found by position rather than by what is written there, because a blank
    form has no code in it yet and that is exactly the form that needs one
    put in.
    """
    for row in range(1, header):
        for col in range(1, min(page.max_column, 20) + 1):
            said = _words(page.cell(row=row, column=col).value)
            if said and any(word in said for word in STATEMENT):
                return f"{_letter(_span_end(page, row, col) + 1)}{row}"

    # Nothing recognisable to sit beside: fall back to a code already written.
    for row in range(1, header):
        for col in range(8, min(page.max_column, 20) + 1):
            if _cell(page.cell(row=row, column=col).value) in CODES:
                return f"{_letter(col)}{row}"
    return ""


def _comments(page: Any, header: int, columns: Mapping[str, int]) -> list[dict[str, Any]]:
    """The rows under the headings, to the first that has nothing on it.

    A form comes back with blank rows ruled in below the last comment, ready
    for more, so the table ends where the writing does rather than where the
    formatting does.
    """
    out: list[dict[str, Any]] = []
    blanks = 0
    for row in range(header + 1, page.max_row + 1):
        got = {field: _cell(page.cell(row=row, column=col).value)
               for field, col in columns.items()}
        if not any(got.get(f) for f in ("sn", "observation", "source", "reference")):
            blanks += 1
            # A gap of a few rules is a gap; ten of them is the end of the table.
            if blanks >= 10:
                break
            continue
        blanks = 0
        got["row"] = row
        got["returned_code"] = normalise_code(got.get("returned_code"))
        out.append(got)
    return out


# --- writing it back ----------------------------------------------------------

SHEET_PART = re.compile(r"xl/worksheets/sheet\d+\.xml$")


def write(data: bytes, comments: Sequence[Mapping[str, Any]],
          header_row: int, columns: Mapping[str, int],
          info: Mapping[str, str] | None = None,
          info_at: Mapping[str, str] | None = None,
          overall: str = "", overall_at: str = "",
          authored: bool = False) -> bytes:
    """The same workbook with our columns filled in.

    Every part but the one worksheet is copied across untouched, so the
    letterhead, the drawings, the printer settings and the styles are the
    client's own and not a rendering of them.

    `authored` says whose table this is. A sheet that came in on the client's
    form keeps their columns exactly as they wrote them and takes only our
    response, our code and the sign-off — answering a comment by editing it is
    not answering it. A sheet raised here is written whole, because there was
    no reviewer to have filled anything in.
    """
    source = zipfile.ZipFile(io.BytesIO(data))
    name = next((n for n in source.namelist() if SHEET_PART.match(n)), None)
    if name is None:
        raise SheetError("That workbook has no worksheet in it.")

    xml = source.read(name).decode("utf-8")
    xml = _patch(xml, comments, header_row, columns, authored)
    # The header, for a sheet raised here rather than uploaded. Skipped where
    # nobody said where the values go, which is a form we did not read.
    at = dict(info_at or {})
    for field, value in (info or {}).items():
        if field in at and value:
            xml = _cell_in(xml, at[field], str(value))
    if overall and overall_at:
        xml = _cell_in(xml, overall_at, overall)

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as made:
        for item in source.infolist():
            if item.filename == name:
                made.writestr(item, xml.encode("utf-8"))
            else:
                # Byte for byte: whatever is in there, we are not the ones to
                # re-encode it.
                made.writestr(item, source.read(item.filename))
    return out.getvalue()


def _letter(index: int) -> str:
    """1 -> A, 27 -> AA."""
    out = ""
    while index > 0:
        index, rest = divmod(index - 1, 26)
        out = chr(65 + rest) + out
    return out


def _inline(reference: str, style: str, text: str) -> str:
    """A cell holding a string of its own, rather than one from the shared table."""
    kept = f' s="{style}"' if style else ""
    if not text:
        return f'<c r="{reference}"{kept}/>'
    return (f'<c r="{reference}"{kept} t="inlineStr">'
            f"<is><t xml:space=\"preserve\">{escape(text)}</t></is></c>")


def _cell_in(xml: str, reference: str, text: str) -> str:
    """Set one cell anywhere on the sheet, by its own address."""
    row = int(re.search(r"\d+", reference).group(0))
    found = re.search(rf'<row r="{row}"[^>]*>.*?</row>', xml, flags=re.S)
    if found is None:
        return xml
    return xml.replace(found.group(0), _set(found.group(0), reference, text), 1)


def _patch(xml: str, comments: Sequence[Mapping[str, Any]], header_row: int,
           columns: Mapping[str, int], authored: bool = False) -> str:
    """Set our cells on each comment's row, leaving everything else alone.

    A row the workbook does not have yet is one we are creating, and the whole
    of it is ours to write — a sheet raised here has no reviewer to have filled
    the left-hand columns in. On a row that came from the client, only our own
    columns are touched: answering a comment by editing it is not answering it.
    """
    there = {int(found.group(1))
             for found in re.finditer(r'<row r="(\d+)"', xml)}

    wanted: dict[int, dict[str, str]] = {}
    for nth, comment in enumerate(comments, start=1):
        # A comment that came off this form knows which row it was on. One
        # raised here does not, and takes the table in the order it is given:
        # the list is the table.
        row = int(comment.get("row") or 0) or header_row + nth
        if row <= header_row:
            continue
        mine = columns.keys() if (authored or row not in there) else MINE
        cells: dict[str, str] = {}
        for field in mine:
            if field not in columns or field not in comment:
                continue
            value = comment.get(field)
            if field == "signoff":
                value = _signoff(value)
            cells[_letter(columns[field])] = str(value or "")
        wanted[row] = cells

    def one_row(match: re.Match) -> str:
        row_xml = match.group(0)
        number = int(match.group(1))
        cells = wanted.get(number)
        if not cells:
            return row_xml
        for letter, text in cells.items():
            row_xml = _set(row_xml, f"{letter}{number}", text)
        return row_xml

    xml = re.sub(r'<row r="(\d+)"[^>]*>.*?</row>', one_row, xml, flags=re.S)
    return _add_rows(xml, {n: c for n, c in wanted.items() if n not in there}, there,
                     header_row)


def _add_rows(xml: str, adding: Mapping[int, Mapping[str, str]],
              there: set[int], header_row: int) -> str:
    """Rows the workbook does not have, ruled like the ones it does.

    Copied from the last row of the table rather than invented, so a comment
    added here is the same height, border and font as one that came in on the
    form.
    """
    if not adding:
        return xml

    below = sorted(n for n in there if n > header_row)
    pattern = None
    if below:
        found = re.search(rf'<row r="{below[-1]}"[^>]*>.*?</row>', xml, flags=re.S)
        pattern = found.group(0) if found else None
    if pattern is None:
        return xml                                     # nothing to copy a shape from

    made = []
    for number in sorted(adding):
        row_xml = re.sub(r'(<row r=")\d+(")', rf'\g<1>{number}\g<2>', pattern, count=1)
        row_xml = re.sub(r'(<c r="[A-Z]+)\d+(")', rf'\g<1>{number}\g<2>', row_xml)
        # Emptied, then filled with what this comment says.
        row_xml = re.sub(r'(<c [^>]*?)(?: t="[^"]*")?>.*?</c>', r'\1/>', row_xml, flags=re.S)
        for letter, text in adding[number].items():
            row_xml = _set(row_xml, f"{letter}{number}", text)
        made.append(row_xml)

    return xml.replace("</sheetData>", "".join(made) + "</sheetData>", 1)


def _set(row_xml: str, reference: str, text: str) -> str:
    """Replace one cell in a row, keeping the style it already had."""
    found = re.search(rf'<c r="{reference}"(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</c>)',
                      row_xml, flags=re.S)
    if found is None:
        # No cell there at all. Put one in, in column order, so the row stays
        # in the order a reader expects.
        return _insert(row_xml, reference, text)
    style = re.search(r's="(\d+)"', found.group("attrs"))
    return row_xml.replace(found.group(0),
                           _inline(reference, style.group(1) if style else "", text), 1)


def _insert(row_xml: str, reference: str, text: str) -> str:
    letter = re.match(r"([A-Z]+)", reference).group(1)
    made = _inline(reference, "", text)
    for other in re.finditer(r'<c r="([A-Z]+)\d+"', row_xml):
        if other.group(1) > letter:
            at = other.start()
            return row_xml[:at] + made + row_xml[at:]
    return row_xml.replace("</row>", made + "</row>", 1)


def _signoff(value: Any) -> str:
    """Open and closed in the words the form uses."""
    said = str(value or "").strip().lower()
    if said == "closed":
        return "Closed"
    return "Open" if said == "open" else str(value or "")


def blank_form() -> bytes:
    """The blank form, for a sheet raised in the app rather than uploaded."""
    if not BLANK.exists():
        raise SheetError("No blank review response form is installed.")
    return BLANK.read_bytes()


def keep_as_blank(data: bytes, where: Path = BLANK) -> None:
    """Keep a workbook as the blank form to raise new sheets from."""
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_bytes(data)


__all__ = ["read", "write", "blank_form", "keep_as_blank", "SheetError", "MIMETYPE",
           "COLUMNS", "INFO", "MINE"]
