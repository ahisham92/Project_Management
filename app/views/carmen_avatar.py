"""Carmen's face.

Her photograph is not in the repository — it is a picture of a person, and a
picture of a person belongs with the installation's own data rather than in
source control where it would be copied everywhere the code goes. So it is
uploaded once and kept beside the database, and until somebody uploads one she
has a drawn monogram instead. Either way the page never has a broken image on
it.
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

# Drawn rather than fetched, so a fresh install looks finished on its first
# page load and nothing on the internet has to be reachable for it to.
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


def saved() -> Path | None:
    """Her photograph, if one has been uploaded."""
    for extension, _content in ((e, c) for _s, e, c in SIGNATURES):
        where = folder() / f"carmen.{extension}"
        if where.exists():
            return where
    return None


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

    for _signature, other, _kind in SIGNATURES:
        stale = folder() / f"carmen.{other}"
        if stale.exists():
            stale.unlink()

    where = folder() / f"carmen.{extension}"
    where.parent.mkdir(parents=True, exist_ok=True)
    where.write_bytes(data)
    return where.name


def forget() -> None:
    where = saved()
    if where is not None:
        where.unlink()
