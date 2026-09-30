"""Reading an old Word 97–2003 ``.doc`` without Word.

A ``.doc`` is a small file system (the compound file) holding a stream of
text, a table of the pieces it is made of, the paragraph properties page by
page, and the style sheet. What a specification section needs from it is
little: each paragraph's text, its style's name, and where Word's own list
numbering put it. Those are read here and written out as the bare
``document.xml`` and ``styles.xml`` of a ``.docx``, so the same reader that
takes a ``.docx`` — styles, typed numbers, list levels and all — reads it.

Everything is the standard library: nothing to install on the server.
"""

from __future__ import annotations

import struct
import zipfile
from bisect import bisect_right
from io import BytesIO
from xml.sax.saxutils import escape

SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
END = 0xFFFFFFFA                     # this and above end a chain


class DocError(ValueError):
    pass


def is_doc(data: bytes) -> bool:
    return data[:8] == SIGNATURE


# --- the compound file -------------------------------------------------------------

def _u16(b: bytes, at: int) -> int:
    return struct.unpack_from("<H", b, at)[0]


def _u32(b: bytes, at: int) -> int:
    return struct.unpack_from("<I", b, at)[0]


def streams(data: bytes) -> dict[str, bytes]:
    """The streams at the top of a compound file, by name."""
    if not is_doc(data) or len(data) < 512:
        raise DocError("not a Word 97–2003 document")
    size = 1 << _u16(data, 0x1E)
    mini = 1 << _u16(data, 0x20)
    cutoff = _u32(data, 0x38)

    def sector(n: int) -> bytes:
        at = (n + 1) * size
        return data[at:at + size]

    # Where the allocation table's own sectors are.
    fat_sectors = [n for n in struct.unpack_from("<109I", data, 0x4C) if n < END]
    dif, count = _u32(data, 0x44), _u32(data, 0x48)
    while dif < END and count:
        block = sector(dif)
        entries = struct.unpack_from("<%dI" % (size // 4), block)
        fat_sectors += [n for n in entries[:-1] if n < END]
        dif, count = entries[-1], count - 1
    fat: list[int] = []
    for n in fat_sectors:
        fat += struct.unpack_from("<%dI" % (size // 4), sector(n))

    def chain(start: int, table: list[int]) -> list[int]:
        out, seen = [], set()
        while start < END and start < len(table) and start not in seen:
            seen.add(start)
            out.append(start)
            start = table[start]
        return out

    def read(start: int) -> bytes:
        return b"".join(sector(n) for n in chain(start, fat))

    directory = read(_u32(data, 0x30))
    entries = []
    for at in range(0, len(directory) - 127, 128):
        length = _u16(directory, at + 0x40)
        name = directory[at:at + max(length - 2, 0)].decode("utf-16-le", "replace")
        kind = directory[at + 0x42]
        entries.append((name, kind, _u32(directory, at + 0x74), _u32(directory, at + 0x78)))
    if not entries:
        raise DocError("the document's directory is empty")

    root_start = entries[0][2]
    ministream = read(root_start) if root_start < END else b""
    minifat_raw = read(_u32(data, 0x3C)) if _u32(data, 0x3C) < END else b""
    minifat = list(struct.unpack_from("<%dI" % (len(minifat_raw) // 4), minifat_raw))

    out: dict[str, bytes] = {}
    for name, kind, start, length in entries[1:]:
        if kind != 2 or name in out:
            continue
        if length < cutoff:
            body = b"".join(ministream[n * mini:(n + 1) * mini] for n in chain(start, minifat))
        else:
            body = read(start)
        out[name] = body[:length]
    return out


# --- the Word document inside it ---------------------------------------------------

# Paragraph properties this reads, by their sprm codes.
ILVL, ILFO, IN_TABLE, ROW_END, ITAP = 0x260A, 0x460B, 0x2416, 0x2417, 0x6649
VANISH = 0x083C                                    # sprmCFVanish: hidden text
INNER_ROW_END, INNER_CELL = 0x244C, 0x244B
SIZES = {0: 1, 1: 1, 2: 2, 3: 4, 4: 2, 5: 2, 7: 3}


def sprms(grpprl: bytes) -> dict[int, int]:
    """The single-value properties in a list of them; the rest are skipped."""
    out: dict[int, int] = {}
    at = 0
    while at + 2 <= len(grpprl):
        op = _u16(grpprl, at)
        at += 2
        spra = op >> 13
        if spra == 6:
            if op == 0xD608:                  # a table row's definition
                if at + 2 > len(grpprl):
                    break
                length = 2 + _u16(grpprl, at) - 1
            elif at < len(grpprl):
                length = 1 + grpprl[at]
            else:
                break
        else:
            length = SIZES[spra]
            value = grpprl[at:at + length]
            if len(value) == length:
                out[op] = int.from_bytes(value, "little")
        at += length
    return out


def _fib(word: bytes) -> dict:
    if len(word) < 64 or _u16(word, 0) != 0xA5EC:
        raise DocError("not a Word document")
    if _u16(word, 2) < 0x00C1:
        raise DocError("a Word 6 or Word 95 file, which is older than this reads")
    flags = _u16(word, 0x0A)
    if flags & 0x0100:
        raise DocError("the document is password-protected")
    csw = _u16(word, 32)
    at = 34 + csw * 2
    cslw = _u16(word, at)
    ccp_text = _u32(word, at + 2 + 3 * 4)
    at = at + 2 + cslw * 4
    count = _u16(word, at)
    pairs = [struct.unpack_from("<II", word, at + 2 + i * 8) for i in range(count)]
    return {"table": "1Table" if flags & 0x0200 else "0Table", "ccp_text": ccp_text,
            "stsh": pairs[1], "chpx": pairs[12], "papx": pairs[13], "clx": pairs[33],
            "lfo": pairs[74] if len(pairs) > 74 else (0, 0)}


def _lists(table: bytes, lfo: tuple[int, int]) -> dict[int, int]:
    """Which list each list override numbers with. Several overrides can
    carry on one list, and it is the list that says it is the same numbering."""
    fc, lcb = lfo
    raw = table[fc:fc + lcb]
    if len(raw) < 4:
        return {}
    count = min(_u32(raw, 0), (len(raw) - 4) // 16)
    return {i + 1: _u32(raw, 4 + 16 * i) for i in range(count)}


def _deleted(word: bytes, table: bytes, chpx: tuple[int, int]
             ) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The stretches of the file that tracked changes deleted, and the ones
    formatted as hidden text."""
    fc, lcb = chpx
    raw = table[fc:fc + lcb]
    n = (len(raw) - 4) // 8
    gone, veiled = [], []
    for i in range(n):
        page_no = _u32(raw, 4 * (n + 1) + 4 * i) & 0x3FFFFF
        page = word[page_no * 512:page_no * 512 + 512]
        if len(page) < 512:
            continue
        crun = page[511]
        fcs = struct.unpack_from("<%dI" % (crun + 1), page)
        for j in range(crun):
            where = page[4 * (crun + 1) + j] * 2
            if not where:
                continue
            props = sprms(page[where + 1:where + 1 + page[where]])
            if props.get(0x0800) == 1:              # deleted with tracked changes
                gone.append((fcs[j], fcs[j + 1]))
            if props.get(VANISH) in (1, 0x81):      # hidden text (0x81: the style's opposite)
                veiled.append((fcs[j], fcs[j + 1]))
    return gone, veiled


def _characters(word: bytes, table: bytes, clx: tuple[int, int], limit: int
                ) -> tuple[str, list[int]]:
    """The main text, and the file position of each of its characters."""
    fc, lcb = clx
    raw = table[fc:fc + lcb]
    at = 0
    while at < len(raw) and raw[at] == 0x01:
        at += 3 + struct.unpack_from("<h", raw, at + 1)[0]
    if at >= len(raw) or raw[at] != 0x02:
        raise DocError("the document's text table cannot be read")
    size = _u32(raw, at + 1)
    plc = raw[at + 5:at + 5 + size]
    n = (size - 4) // 12
    cps = struct.unpack_from("<%dI" % (n + 1), plc)
    chars: list[str] = []
    places: list[int] = []
    for i in range(n):
        start, stop = cps[i], min(cps[i + 1], limit)
        if start >= limit:
            break
        value = _u32(plc, 4 * (n + 1) + 8 * i + 2)
        compressed = bool(value & 0x40000000)
        offset = value & 0x3FFFFFFF
        count = stop - start
        if compressed:
            at_byte = offset // 2
            chars.append(word[at_byte:at_byte + count].decode("cp1252", "replace"))
            places += range(at_byte, at_byte + count)
        else:
            chars.append(word[offset:offset + 2 * count].decode("utf-16-le", "replace"))
            places += range(offset, offset + 2 * count, 2)
    return "".join(chars), places


def _paragraph_runs(word: bytes, table: bytes, papx: tuple[int, int]
                    ) -> tuple[list[int], list[tuple[int, int, dict]]]:
    """Every stretch of the file with its paragraph style and properties."""
    fc, lcb = papx
    raw = table[fc:fc + lcb]
    n = (len(raw) - 4) // 8
    runs: list[tuple[int, int, dict]] = []
    for i in range(n):
        page_no = _u32(raw, 4 * (n + 1) + 4 * i) & 0x3FFFFF
        page = word[page_no * 512:page_no * 512 + 512]
        if len(page) < 512:
            continue
        crun = page[511]
        fcs = struct.unpack_from("<%dI" % (crun + 1), page)
        for j in range(crun):
            where = page[4 * (crun + 1) + 13 * j] * 2
            istd, props = 0, {}
            if where:
                cb = page[where]
                if cb == 0:
                    body = page[where + 2:where + 2 + 2 * page[where + 1]]
                else:
                    body = page[where + 1:where + 1 + 2 * cb - 1]
                if len(body) >= 2:
                    istd, props = _u16(body, 0), sprms(body[2:])
            runs.append((fcs[j], istd, props))
    runs.sort(key=lambda r: r[0])
    return [r[0] for r in runs], runs


def _styles(table: bytes, stsh: tuple[int, int]) -> dict[int, dict]:
    """Each paragraph style's name, and the list it numbers with, if any."""
    fc, lcb = stsh
    raw = table[fc:fc + lcb]
    if len(raw) < 6:
        return {}
    header = _u16(raw, 0)
    count, base_size = _u16(raw, 2), _u16(raw, 4)
    at = 2 + header
    found: dict[int, dict] = {}
    for istd in range(count):
        if at + 2 > len(raw):
            break
        size = _u16(raw, at)
        std = raw[at + 2:at + 2 + size]
        at += 2 + size
        if not size or len(std) < base_size + 2:
            continue
        kind = _u16(std, 2) & 0x000F
        based_on = _u16(std, 2) >> 4
        length = _u16(std, base_size)
        name = std[base_size + 2:base_size + 2 + 2 * length].decode("utf-16-le", "replace")
        props: dict = {}
        upx = base_size + 2 + 2 * length + 2
        if kind == 1 and upx + 2 <= len(std):
            cb = _u16(std, upx)
            papx = std[upx + 2:upx + 2 + cb]
            if len(papx) >= 2:
                props = sprms(papx[2:])
        found[istd] = {"name": name.split(",")[0].strip(), "based_on": based_on, "props": props}
    for istd, style in found.items():
        seen, parent = {istd}, style["based_on"]
        while ILFO not in style["props"] and parent in found and parent not in seen:
            seen.add(parent)
            for key in (ILFO, ILVL):
                if key in found[parent]["props"] and key not in style["props"]:
                    style["props"][key] = found[parent]["props"][key]
            parent = found[parent]["based_on"]
    return found


def _clean(text: str) -> str:
    """Field codes dropped (their results kept) and Word's special marks made plain."""
    return "".join(c for c, _ in _clean_marked(text, [False] * len(text)))


def _clean_marked(text: str, mask: list[bool]) -> list[tuple[str, bool]]:
    """As ``_clean``, each character kept with its flag from ``mask``."""
    out: list[tuple[str, bool]] = []
    depth, shown = 0, [True]
    for c, flag in zip(text, mask):
        if c == "\x13":
            depth += 1
            shown.append(False)
        elif c == "\x14":
            if depth:
                shown[-1] = True
        elif c == "\x15":
            if depth:
                depth -= 1
                shown.pop()
        elif not all(shown):
            continue
        elif c in "\x01\x02\x03\x04\x05\x08\x1f":
            continue
        elif c in "\x0b\xa0":
            out.append((" ", flag))
        elif c == "\x1e":
            out.append(("-", flag))
        else:
            out.append((c, flag))
    return out


def _runs(marked: list[tuple[str, bool]]) -> str:
    """Runs of text, the hidden stretches marked hidden as Word had them."""
    out, at = [], 0
    while at < len(marked):
        flag, end = marked[at][1], at
        while end < len(marked) and marked[end][1] == flag:
            end += 1
        words = escape("".join(ch for ch, _ in marked[at:end]))
        props = "<w:rPr><w:vanish/></w:rPr>" if flag else ""
        out.append(f'<w:r>{props}<w:t xml:space="preserve">{words}</w:t></w:r>')
        at = end
    return "".join(out) or '<w:r><w:t xml:space="preserve"></w:t></w:r>'


def to_docx(data: bytes) -> bytes:
    """A ``.doc`` as the bare ``.docx`` its reader needs: paragraphs with their
    styles and list levels, tables, and the style sheet's names and lists."""
    files = streams(data)
    word = files.get("WordDocument")
    if word is None:
        raise DocError("not a Word document")
    fib = _fib(word)
    table = files.get(fib["table"], b"")
    text, places = _characters(word, table, fib["clx"], fib["ccp_text"])
    starts, runs = _paragraph_runs(word, table, fib["papx"])
    styles = _styles(table, fib["stsh"])
    lists = _lists(table, fib["lfo"])
    gone, veiled = _deleted(word, table, fib["chpx"])
    if gone:
        cut = [any(a <= fc < b for a, b in gone) for fc in places]
        text = "".join(c for c, drop in zip(text, cut) if not drop)
        places = [fc for fc, drop in zip(places, cut) if not drop]
    hidden = ([any(a <= fc < b for a, b in veiled) for fc in places] if veiled
              else [False] * len(places))

    def props_at(fc: int) -> tuple[int, dict]:
        i = bisect_right(starts, fc) - 1
        return (runs[i][1], runs[i][2]) if i >= 0 else (0, {})

    body: list[str] = []
    row: list[str] = []
    cell: list[str] = []
    rows: list[list[str]] = []

    def flush_table() -> None:
        if rows:
            trs = "".join("<w:tr>" + "".join(
                f"<w:tc><w:p><w:r><w:t xml:space=\"preserve\">{escape(c)}</w:t></w:r></w:p></w:tc>"
                for c in r) + "</w:tr>" for r in rows)
            body.append(f"<w:tbl>{trs}</w:tbl>")
            rows.clear()

    start = 0
    for i, c in enumerate(text):
        if c not in "\r\x07\x0c":
            continue
        marked = _clean_marked(text[start:i], hidden[start:i])
        piece = "".join(ch for ch, _ in marked)
        start = i + 1
        istd, props = props_at(places[i])
        in_table = props.get(IN_TABLE) or props.get(ITAP)
        if in_table:
            if props.get(ROW_END) or props.get(INNER_ROW_END):
                if row:
                    rows.append(row)
                row, cell = [], []
                continue
            cell.append("".join(ch for ch, veil in marked if not veil))
            if c == "\x07":
                row.append(" ".join(p for p in cell if p.strip()).strip())
                cell = []
            continue
        flush_table()
        style = styles.get(istd, {})
        level = props.get(ILVL, style.get("props", {}).get(ILVL, 0))
        lfo = lists.get(props.get(ILFO, 0), 0)
        numbered = (f'<w:numPr><w:ilvl w:val="{level}"/><w:numId w:val="{lfo}"/></w:numPr>'
                    if lfo else "")
        body.append(f'<w:p><w:pPr><w:pStyle w:val="S{istd}"/>{numbered}</w:pPr>'
                    f'{_runs(marked)}</w:p>')
    flush_table()

    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f'<w:document {ns}><w:body>{"".join(body)}</w:body></w:document>')
    sheet = []
    for istd, style in sorted(styles.items()):
        lfo = lists.get(style["props"].get(ILFO, 0), 0)
        numbered = (f'<w:pPr><w:numPr><w:numId w:val="{lfo}"/></w:numPr></w:pPr>'
                    if lfo else "")
        sheet.append(f'<w:style w:type="paragraph" w:styleId="S{istd}">'
                     f'<w:name w:val="{escape(style["name"], {chr(34): "&quot;"})}"/>{numbered}</w:style>')
    style_xml = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 f'<w:styles {ns}>{"".join(sheet)}</w:styles>')
    out = BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", style_xml)
    return out.getvalue()
