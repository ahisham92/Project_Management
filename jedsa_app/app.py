"""JEDSA's page.

JEDSA is one self-contained HTML file (``page/jedsa.html``): every analysis
runs in the browser and a model is saved as a file on the person's own machine,
so it keeps working offline once opened. The server only hands out the page.

Who is signed in is decided by the site JEDSA is mounted in (Project Control,
in front of ``/jedsa``), which puts the account into the request under
``SITE_KEY``. JEDSA has no sign-in of its own. Run alone for development with
``JEDSA_DEV_ACCOUNT=me python -m jedsa_app``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, send_file

from . import __version__

#: Where a mounting site says who is asking: {"id", "name", "login"}.
SITE_KEY = "jedsa.site"

PAGE = Path(__file__).resolve().parent / "page" / "jedsa.html"


def is_public(path: str) -> bool:
    """Answered without the site's sign-in: only the health check."""
    return path == "/healthz"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)

    def who() -> dict[str, Any] | None:
        site = request.environ.get(SITE_KEY)
        if site:
            return site
        dev = os.environ.get("JEDSA_DEV_ACCOUNT")
        if dev:
            return {"id": dev, "name": dev, "login": dev}
        return None

    @app.after_request
    def headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        return resp

    @app.get("/")
    def home():
        if not who():
            abort(401)
        resp = send_file(PAGE, mimetype="text/html", max_age=0)
        # a new copy of the page is picked up on the next visit, not a week later
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/healthz")
    def health():
        return jsonify({"status": "ok", "version": __version__, "page": PAGE.is_file()})

    return app
