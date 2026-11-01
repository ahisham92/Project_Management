"""TritoMoor, the static mooring analysis program, served at ``/tritomoor``.

TritoMoor is one self-contained HTML file — every calculation, library and
drawing runs in the browser, so nothing is sent back here and nothing is kept
in this database. A project is saved as a ``.trito`` file on the user's own
machine, and work in progress stays in that browser, as it does offline.

**Projects are kept on the site.** Served from here, TritoMoor saves the open
project to the signed-in account as it is edited (``/tritomoor/api/projects``,
kept by ``tritomoor_store``), so it opens again from any machine. Saving to and
opening from a ``.trito`` file still works, and offline it is the only way.

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

from flask import Blueprint, Response, g, jsonify, redirect, request, url_for

from .. import tritomoor_store as store
from ..auth import login_required
from ..db import get_db

bp = Blueprint("tritomoor", __name__, url_prefix="/tritomoor")

PAGE = Path(__file__).resolve().parent.parent / "tritomoor" / "tritomoor.html"

BACK = (
    '<a href="/" title="Back to the choice of applications" '
    'style="display:inline-block;margin:0 0 4px;font:600 12px/1.2 system-ui,sans-serif;'
    'color:inherit;opacity:.7;text-decoration:none">&larr; All applications</a>'
)


# Told to the page so it keeps its projects here; offline the page has no such
# note and saves to files as it always did.
SITE = '<script>window.__TM_SITE={api:"/tritomoor/api",me:__TM_ME__};</script>'


def ready() -> bool:
    return PAGE.is_file()


def describe() -> dict:
    """What the front door needs to know: where it goes, and whether it is there."""
    return {"name": "TritoMoor", "href": "/tritomoor/", "ready": ready()}


@lru_cache(maxsize=2)
def _page(stamp: float) -> str:
    html = PAGE.read_text(encoding="utf-8")
    html = html.replace('<div class="brand">', '<div class="brand">' + BACK, 1)
    return html.replace("</head>", SITE + "</head>", 1)


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
    body = _page(PAGE.stat().st_mtime).replace("__TM_ME__", str(int(g.user["id"])), 1)
    return Response(body, mimetype="text/html",
                    headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})


# --- projects kept on the site ---------------------------------------------------

def _answer(work):
    """Runs one API call for the signed-in account and says plainly what went wrong."""
    if g.get("user") is None:
        return jsonify({"detail": "Sign in first."}), 401
    try:
        return jsonify(work(get_db(), int(g.user["id"])))
    except store.Problem as problem:
        return jsonify({"detail": str(problem), **problem.extra}), problem.status


def _body() -> dict:
    if not request.is_json:
        raise store.Problem("Send the project as JSON.", 415)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise store.Problem("Send the project as JSON.")
    return body


@bp.get("/api/projects")
def api_list():
    return _answer(lambda db, uid: {"projects": store.listing(db, uid)})


@bp.post("/api/projects")
def api_create():
    def work(db, uid):
        body = _body()
        return store.create(db, uid, body.get("data"), name=body.get("name"))
    return _answer(work)


@bp.get("/api/projects/<int:project_id>")
def api_fetch(project_id: int):
    return _answer(lambda db, uid: store.fetch(db, uid, project_id))


@bp.put("/api/projects/<int:project_id>")
def api_save(project_id: int):
    def work(db, uid):
        body = _body()
        base = body.get("base_version")
        force = bool(body.get("force"))
        return store.save(db, uid, project_id, data=body.get("data"), name=body.get("name"),
                          base_version=None if force or base is None else int(base), keep_previous=force)
    return _answer(work)


@bp.post("/api/projects/<int:project_id>/duplicate")
def api_duplicate(project_id: int):
    def work(db, uid):
        _body()
        return store.duplicate(db, uid, project_id)
    return _answer(work)


@bp.delete("/api/projects/<int:project_id>")
def api_delete(project_id: int):
    def work(db, uid):
        store.delete(db, uid, project_id)
        return {"deleted": project_id}
    return _answer(work)


@bp.get("/api/projects/<int:project_id>/versions")
def api_versions(project_id: int):
    return _answer(lambda db, uid: {"versions": store.history(db, uid, project_id)})


@bp.post("/api/projects/<int:project_id>/versions/<int:version_id>/restore")
def api_restore(project_id: int, version_id: int):
    def work(db, uid):
        _body()
        return store.restore(db, uid, project_id, version_id)
    return _answer(work)


@bp.get("/api/people")
def api_people():
    return _answer(lambda db, uid: {"people": store.people(db, uid)})


@bp.get("/api/projects/<int:project_id>/shares")
def api_shares(project_id: int):
    return _answer(lambda db, uid: {"shares": store.shares(db, uid, project_id)})


@bp.post("/api/projects/<int:project_id>/shares")
def api_share(project_id: int):
    def work(db, uid):
        body = _body()
        try:
            with_user = int(body.get("user_id"))
        except (TypeError, ValueError):
            raise store.Problem("Choose who to share it with.")
        return {"shares": store.share(db, uid, project_id, with_user, str(body.get("access") or "edit"))}
    return _answer(work)


@bp.delete("/api/projects/<int:project_id>/shares/<int:user_id>")
def api_unshare(project_id: int, user_id: int):
    return _answer(lambda db, uid: {"shares": store.unshare(db, uid, project_id, user_id)})
