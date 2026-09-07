"""Carmen's face.

She ships with a picture, so a fresh install has her on it rather than a
placeholder waiting for somebody to notice. An installation that would rather
use a different one puts a file beside the database and that wins — kept there
rather than in the repository, because a picture somebody uploads is theirs and
not something to copy everywhere the code goes.
"""

from __future__ import annotations

from pathlib import Path

# What may be uploaded, by the first bytes of the file rather than by whatever
# the browser claimed the type was.
SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
    (b"RIFF", "webp", "image/webp"),
)
MAX_BYTES = 3 * 1024 * 1024

# The one she comes with.
BUNDLED = Path(__file__).resolve().parent.parent / "static" / "carmen.jpg"

# Drawn rather than fetched, and only ever reached if the bundled picture has
# been deleted — so the page can never have a broken image on it.
MONOGRAM = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96" width="96" height="96">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#7c5cbf"/><stop offset="1" stop-color="#2a78d6"/>'
    "</linearGradient></defs>"
    '<rect width="96" height="96" rx="48" fill="url(#g)"/>'
    '<text x="48" y="62" font-family="system-ui, sans-serif" font-size="40" font-weight="600"'
    ' fill="#fff" text-anchor="middle">C</text></svg>'
).encode("utf-8")


def kind_of(data: bytes) -> tuple[str, str]:
    """The file's extension and content type, read from the file itself."""
    for signature, extension, content_type in SIGNATURES:
        if data.startswith(signature):
            return extension, content_type
    return "", ""


def folder() -> Path:
    from ..db import live_database

    return Path(live_database()).parent


def uploaded() -> Path | None:
    """A picture this installation chose, if there is one."""
    for extension in (e for _s, e, _c in SIGNATURES):
        where = folder() / f"carmen.{extension}"
        if where.exists():
            return where
    return None


def saved() -> Path | None:
    """The picture to serve: this installation's, or the one she ships with."""
    return uploaded() or (BUNDLED if BUNDLED.exists() else None)


def content_type(where: Path) -> str:
    for _signature, extension, kind in SIGNATURES:
        if where.suffix == f".{extension}":
            return kind
    return "application/octet-stream"


def store(data: bytes) -> str:
    """Keeps an uploaded picture, replacing any there already."""
    extension, _kind = kind_of(data)
    if not extension:
        raise ValueError("That is not a JPEG, PNG or WebP image")
    if len(data) > MAX_BYTES:
        raise ValueError("That picture is larger than 3 MB")

    for other in (e for _s, e, _c in SIGNATURES):
        stale = folder() / f"carmen.{other}"
        if stale.exists():
            stale.unlink()

    where = folder() / f"carmen.{extension}"
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_bytes(data)
    return where.name


def forget() -> None:
    """Back to the picture she ships with."""
    where = uploaded()
    if where is not None:
        where.unlink()
