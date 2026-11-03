"""Talus's page and API.

Every calculation runs in the browser (``static/engine``), so results appear
while the numbers are being typed and the page works on a phone. The server
only serves the page and keeps each person's projects.

Who is signed in is decided by the site Talus is mounted in (Project Control,
in front of ``/talus``), which puts the account into the request under
``SITE_KEY``. Talus has no sign-in of its own. Run alone for development with
``TALUS_DEV_ACCOUNT=me python -m talus_app``.
"""

from __future__ import annotations

import os
from typing import Any

from flask import Flask, abort, jsonify, render_template, request

from . import __version__
from .store import Store, StoreError

#: Where a mounting site says who is asking: {"id", "name", "login"}.
SITE_KEY = "talus.site"


def is_public(path: str) -> bool:
    """Answered without the site's sign-in: only the static files."""
    return path.startswith("/static/")


def create_app(store: Store | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config["JSON_SORT_KEYS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    app.extensions["talus.store"] = store or Store()

    def who() -> dict[str, Any] | None:
        site = request.environ.get(SITE_KEY)
        if site:
            return site
        dev = os.environ.get("TALUS_DEV_ACCOUNT")
        if dev:
            return {"id": dev, "name": dev, "login": dev}
        return None

    def owner() -> str:
        w = who()
        if not w:
            raise StoreError("Sign in to use Talus.", 401)
        return str(w["id"])

    def body() -> dict[str, Any]:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise StoreError("Send the project as JSON.", 415 if not request.is_json else 400)
        return data

    @app.errorhandler(StoreError)
    def problem(e: StoreError):
        return jsonify({"error": str(e), **e.extra}), e.status

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/")
    @app.get("/p/<int:pid>")
    def home(pid: int | None = None):
        w = who()
        if not w:
            abort(401)
        return render_template("index.html", who=w, version=__version__, open_id=pid,
                               site_root=request.environ.get("talus.site_root", ""))

    @app.get("/healthz")
    def health():
        return jsonify({"status": "ok", "version": __version__})

    st: Store = app.extensions["talus.store"]

    @app.get("/api/projects")
    def api_list():
        return jsonify({"projects": st.listing(owner())})

    @app.post("/api/projects")
    def api_create():
        return jsonify(st.create(owner(), body().get("data"))), 201

    @app.get("/api/projects/<int:pid>")
    def api_fetch(pid: int):
        return jsonify(st.fetch(owner(), pid))

    @app.put("/api/projects/<int:pid>")
    def api_save(pid: int):
        b = body()
        base = b.get("base_version")
        return jsonify(st.save(owner(), pid, b.get("data"), None if b.get("force") or base is None else int(base)))

    @app.delete("/api/projects/<int:pid>")
    def api_delete(pid: int):
        st.delete(owner(), pid)
        return jsonify({"deleted": pid})

    @app.post("/api/projects/<int:pid>/duplicate")
    def api_duplicate(pid: int):
        return jsonify(st.duplicate(owner(), pid)), 201

    @app.get("/api/projects/<int:pid>/versions")
    def api_versions(pid: int):
        return jsonify({"versions": st.history(owner(), pid)})

    @app.post("/api/projects/<int:pid>/versions/<int:vid>/restore")
    def api_restore(pid: int, vid: int):
        return jsonify(st.restore(owner(), pid, vid))

    return app
