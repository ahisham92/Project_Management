"""The front door: which application you are here for.

Three things live behind this address — the project control platform, the
comment response sheets, and Triton, the quay element designer, which is an
application of its own mounted in front of ``/triton``. They are one application and one database now, but
they are two different jobs on two different days, so the site opens on a
choice rather than dropping everybody into whichever one happened to be written
first.

The choice is shown after signing in, not before: both applications are for the
same team, so one sign-in covers the pair and the door does not have to explain
itself to a stranger.
"""

from __future__ import annotations

from flask import Blueprint, Response, render_template

from ..auth import login_required
from ..crs import describe as describe_crs
from ..triton_door import describe as describe_triton

bp = Blueprint("home", __name__)

# Every page here declares its own icon inline, so nothing asks for this — until
# a page that does not sits under the same domain. A browser with no icon to go
# on asks the root of the origin for one, whatever address the page itself is
# at, so the comment response sheet's request lands here.
MARK = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' rx='7' fill='#2a78d6'/>"
    "<text x='16' y='22' font-family='system-ui' font-size='14' font-weight='700'"
    " fill='white' text-anchor='middle'>PC</text></svg>"
)


@bp.get("/favicon.ico")
def favicon():
    return Response(MARK, mimetype="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@bp.get("/")
@login_required
def chooser():
    """Which of the two you are here for."""
    return render_template("chooser.html", classic=describe_crs(), triton=describe_triton())


@bp.get("/triton/")
@login_required
def triton_missing():
    """Only reached when Triton is not mounted in front of this address: say why."""
    return render_template("triton_missing.html", triton=describe_triton())
