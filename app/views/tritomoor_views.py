"""TritoMoor, the static mooring analysis program, at ``/tritomoor``.

TritoMoor is one self-contained HTML file: the vessel, the berth, the lines and
fenders, the wind, current and waves, and the static solution are all worked out
in the browser. So there is nothing to mount, only a file to hand over — but it
is handed over behind the same sign-in as everything else, and only to accounts
the administrator has given it.

The file is ``tritomoor/index.html`` beside ``app``. A newer TritoMoor arrives
the way everything else here does: replace the file and ``git pull``.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, redirect, send_file, url_for

from ..auth import login_required

bp = Blueprint("tritomoor", __name__)

PAGE = Path(__file__).resolve().parents[2] / "tritomoor" / "index.html"


def describe() -> dict:
    """What the front door needs to know: where it goes, and whether it is there."""
    return {"name": "TritoMoor", "href": "/tritomoor/", "ready": PAGE.is_file()}


@bp.get("/tritomoor")
@login_required
def bare():
    return redirect(url_for("tritomoor.index"))


@bp.get("/tritomoor/")
@login_required
def index():
    if not PAGE.is_file():
        abort(404)
    answer = send_file(PAGE, mimetype="text/html", max_age=0)
    answer.headers["Cache-Control"] = "no-cache"
    return answer
