"""The front door: which application you are here for.

Two things live behind this address now — the project control platform, and the
comment response sheets. They are separate applications with separate data, so
the site opens on a choice rather than dropping everybody into whichever one
happened to be written first.

The choice is shown after signing in, not before: both applications are for the
same team, so one sign-in covers the pair and the door does not have to explain
itself to a stranger.
"""

from __future__ import annotations

from flask import Blueprint, render_template

from ..auth import login_required
from ..crs import describe as describe_crs

bp = Blueprint("home", __name__)


@bp.get("/")
@login_required
def chooser():
    """Which of the two applications you want."""
    return render_template("chooser.html", crs=describe_crs())


@bp.get("/crs")
@login_required
def crs_missing():
    """Shown only when no comment response sheet application is installed.

    A real one is mounted in front of this address and takes the whole of
    ``/crs`` with it, so reaching this page means there is nothing mounted —
    and the useful thing to say is what to do about it rather than 404.
    """
    # 200, not 501: the request succeeded and this page is the answer. A status
    # in the 500s would have monitoring shouting about a door that is simply
    # not wired up yet, which is a state, not a fault.
    return render_template("crs_missing.html", crs=describe_crs())
