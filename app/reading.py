"""Reading what somebody attaches to a question.

Claude takes a PDF or plain text as a document of its own, and an image as an
image. It does not take a .docx or a .pptx — so those are unzipped here and the
words pulled out of the XML, which is the same OOXML :mod:`app.word` writes.
What comes back is either a content block the Messages API understands or a
plain string to put in front of the question.

Nothing here needs a library: a .docx is a zip of XML, and the standard library
opens both.
"""

from __future__ import annotations

import base64
import io
import re
import zipfile
from typing import Any

# What may be attached, by what is actually in the file rather than by its name.
# The last three are read here and sent as text; the rest go as they are.
KINDS: tuple[tuple[bytes, str, str, str], ...] = (
    (b"%PDF-", "pdf", "application/pdf", "document"),
    (b"\xff\xd8\xff", "jpg", "image/jpeg", "image"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png", "image"),
    (b"GIF8", "gif", "image/gif", "image"),
    (b"RIFF", "webp", "image/webp", "image"),
)

# A megabyte of prose is more than anybody means to attach to a question, and
# it is the point where the answer costs more than it is worth.
MAX_BYTES = 10 * 1024 * 1024
MAX_WORDS = 120_000        # characters of extracted text, not words


class ReadError(ValueError):
    """A file that cannot be read, said in words."""


def _text_of(xml: bytes, wanted: str = "w:t") -> str:
    """The words out of one OOXML part, with the tags taken off."""
    body = xml.decode("utf-8", "replace")
    # Paragraph and line breaks become newlines, so a table does not come out
    # as one run-on sentence.
    body = re.sub(r"</w:p>|<w:br[^>]*/>|</a:p>", "\n", body)
    body = re.sub(r"</w:tc>", "\t", body)
    found = re.findall(rf"<{wanted}[^>]*>(.*?)</{wanted}>", body, re.S)
    words = "".join(found)
    words = (words.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
             .replace("&quot;", '"').replace("&apos;", "'"))
    return words


def _office(data: bytes) -> tuple[str, str]:
    """The kind of Office file this is, and its words. ('', '') if it is not one."""
    if data[:2] != b"PK":
        return "", ""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            names = set(book.namelist())
            if "word/document.xml" in names:
                parts = [book.read("word/document.xml")]
                parts += [book.read(n) for n in sorted(names)
                          if n.startswith(("word/header", "word/footer"))]
                return "docx", "\n".join(_text_of(part) for part in parts)
            slides = sorted(n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n))
            if slides:
                said = []
                for n, slide in enumerate(slides, start=1):
                    words = _text_of(book.read(slide), "a:t")
                    said.append(f"--- Slide {n} ---\n{words}")
                return "pptx", "\n\n".join(said)
            if "xl/workbook.xml" in names:
                shared = []
                if "xl/sharedStrings.xml" in names:
                    shared = re.findall(r"<t[^>]*>(.*?)</t>",
                                        book.read("xl/sharedStrings.xml").decode("utf-8", "replace"),
                                        re.S)
                return "xlsx", "\n".join(shared)
    except (zipfile.BadZipFile, KeyError):
        return "", ""
    return "", ""


def looks_like(data: bytes, filename: str = "") -> str:
    """What kind of file this is: pdf, image, docx, pptx, xlsx, text — or ''."""
    if not data:
        return ""
    for signature, kind, _media, shape in KINDS:
        if data.startswith(signature):
            return "image" if shape == "image" else kind
    office, _words = _office(data)
    if office:
        return office
    try:
        data[:4096].decode("utf-8")
        return "text"
    except UnicodeDecodeError:
        return ""


def media_type(data: bytes) -> str:
    for signature, _kind, media, _shape in KINDS:
        if data.startswith(signature):
            return media
    return "text/plain"


def read(data: bytes, filename: str = "") -> dict[str, Any]:
    """One attachment, ready to put in a question.

    Returns what it is, how big, and either the content block the API takes or
    the words to put in front of the question.
    """
    if not data:
        raise ReadError("That file is empty")
    if len(data) > MAX_BYTES:
        raise ReadError(f"{filename or 'That file'} is "
                        f"{len(data) / 1024 / 1024:.1f} MB — attachments stop at "
                        f"{MAX_BYTES // 1024 // 1024} MB")

    kind = looks_like(data, filename)
    called = (filename or "attachment").strip()[:160]

    if kind == "pdf":
        return {
            "kind": "pdf", "name": called, "bytes": len(data),
            "block": {"type": "document",
                      "source": {"type": "base64", "media_type": "application/pdf",
                                 "data": base64.standard_b64encode(data).decode("ascii")},
                      "title": called},
        }

    if kind == "image":
        return {
            "kind": "image", "name": called, "bytes": len(data),
            "block": {"type": "image",
                      "source": {"type": "base64", "media_type": media_type(data),
                                 "data": base64.standard_b64encode(data).decode("ascii")}},
        }

    if kind in ("docx", "pptx", "xlsx"):
        _office_kind, words = _office(data)
        words = words.strip()
        if not words:
            raise ReadError(f"There are no words in {called} that can be read")
        return {"kind": kind, "name": called, "bytes": len(data),
                "words": words[:MAX_WORDS]}

    if kind == "text":
        words = data.decode("utf-8", "replace").strip()
        if not words:
            raise ReadError(f"There is nothing in {called}")
        return {"kind": "text", "name": called, "bytes": len(data),
                "words": words[:MAX_WORDS]}

    raise ReadError(
        f"{called} is not something that can be read. Attach a PDF, a Word or "
        "PowerPoint file, a spreadsheet, a picture, or plain text.")


def as_content(question: str, attachments: list[dict[str, Any]]) -> Any:
    """The user turn: the files, then the question.

    A PDF or a picture goes as itself; the words out of a Word or PowerPoint
    file go in front of the question, said to be what they are so the answer
    does not treat them as something the reader typed.
    """
    if not attachments:
        return question

    blocks: list[Any] = []
    said: list[str] = []
    for one in attachments:
        if one.get("block"):
            blocks.append(one["block"])
        elif one.get("words"):
            said.append(f"--- {one['name']} ({one['kind']}) ---\n{one['words']}")

    text = question
    if said:
        text = ("Attached:\n\n" + "\n\n".join(said)
                + f"\n\n--- end of what was attached ---\n\n{question}")
    blocks.append({"type": "text", "text": text})
    return blocks
