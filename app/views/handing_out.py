"""Handing a file to somebody, and keeping a copy of what was handed.

Every export goes through here rather than straight to `send_file`, for one
reason: a deck built on Tuesday is not the deck the same dates build today,
because the project has moved. "Let me see the presentation Ola sent the
client" cannot be answered by rebuilding one from the same query string — only
by keeping Ola's copy.

So the bytes that go out are the bytes that are kept, against the project, with
who asked for them and when. They are listed on Carmen's tab and can be opened
again by anybody who can see the project.
"""

from __future__ import annotations

import io
from typing import Any

from flask import g, send_file

WORD = ("application/vnd.openxmlformats-officedocument"
        ".wordprocessingml.document")
DECK = ("application/vnd.openxmlformats-officedocument"
        ".presentationml.presentation")
EXCEL = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"


def handed_out(project_id: int, data: bytes, filename: str, mimetype: str,
               kind: str, name: str, note: str = ""):
    """Sends a file, having written down that it went out.

    Keeping the copy must never be the reason a download fails, so anything
    that goes wrong writing it down is swallowed after being logged — the
    person asked for a document, and they get their document.
    """
    try:
        from ..service import keep_document

        keep_document(project_id, kind, name, filename, mimetype, data,
                      getattr(g, "user", None), note)
    except Exception:                                 # noqa: BLE001 - never block a download
        from flask import current_app

        current_app.logger.exception("Could not keep a copy of %s", filename)

    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True,
                     download_name=filename)


def named(project: Any, stem: str, extension: str) -> str:
    """A filename that sorts and reads: the project code, what it is, the day."""
    from ..service import today

    code = str((project or {}).get("code") or "project")
    return f"{code}-{stem}-{today().replace('-', '')}.{extension}"
