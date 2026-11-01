"""TritoMoor, the static mooring analysis program, served at ``/tritomoor``.

TritoMoor is one self-contained HTML file — every calculation, library and
drawing runs in the browser, so nothing is sent back here and nothing is kept
in this database. A project is saved as a ``.trito`` file on the user's own
machine, and work in progress stays in that browser, as it does offline.

The file lives in ``app/tritomoor/tritomoor.html``. **Updating TritoMoor** is
replacing that file and a ``git pull``; nothing else changes.

It is behind the one sign-in like every other door, and only for accounts the
administrator has given TritoMoor (``programs.BLUEPRINTS``), so knowing the
address does not get anybody in. The only thing added on the way out is a link
back to the choice of applications, beside its name.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from flask import Blueprint, Response, redirect, url_for

from ..auth import login_required

bp = Blueprint("tritomoor", __name__, url_prefix="/tritomoor")

PAGE = Path(__file__).resolve().parent.parent / "tritomoor" / "tritomoor.html"

BACK = (
    '<a href="/" title="Back to the choice of applications" '
    'style="display:inline-block;margin:0 0 4px;font:600 12px/1.2 system-ui,sans-serif;'
    'color:inherit;opacity:.7;text-decoration:none">&larr; All applications</a>'
)


def ready() -> bool:
    return PAGE.is_file()


def describe() -> dict:
    """What the front door needs to know: where it goes, and whether it is there."""
    return {"name": "TritoMoor", "href": "/tritomoor/", "ready": ready()}


@lru_cache(maxsize=2)
def _page(stamp: float) -> str:
    html = PAGE.read_text(encoding="utf-8")
    return html.replace('<div class="brand">', '<div class="brand">' + BACK, 1)


@bp.get("")
@login_required
def bare():
    return redirect(url_for("tritomoor.index"))


@bp.get("/")
@login_required
def index():
    if not ready():
        return Response("TritoMoor is not installed on this site: app/tritomoor/tritomoor.html is missing.",
                        status=503, mimetype="text/plain")
    body = _page(PAGE.stat().st_mtime)
    return Response(body, mimetype="text/html",
                    headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
