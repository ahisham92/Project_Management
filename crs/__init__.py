"""The comment response sheet as it was, mounted in front of ``/crs/classic``.

The application itself is one HTML file: markup, styles and a good deal of
JavaScript, including its own reader and writer for ``.xlsx`` workbooks. It
needs nothing from a server but somewhere to be served from, and it keeps its
work in the browser's own storage rather than in a database.

So this package is thin on purpose. It hands over the file, and it makes sure
whoever asked for it has signed in to project control first — one sign-in for
the pair, which is what the front door promises. Beyond that it does not touch
the sheet or know anything about what is in it.

**The work is kept in each browser.** That is how the application was written,
and it is why it is no longer the one at ``/crs``: everyone gets their own copy,
two people do not see one another's sheets, and clearing a browser's data clears
the sheets with it. The sheets that are shared live in the database with
everything else now. This is kept mounted so that whatever is still in
somebody's browser can be opened and exported rather than lost.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask, Response, redirect, send_from_directory, session

HERE = Path(__file__).resolve().parent
PAGE = "crs.html"

# The page does not ask for one, so every browser asks for /crs/favicon.ico and
# is told no. Drawn here rather than added to the file, which is the
# application as its author wrote it and better left alone.
MARK = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' rx='7' fill='%230f4c81'/>"
    "<text x='16' y='21' font-family='system-ui' font-size='11' font-weight='700'"
    " fill='white' text-anchor='middle'>CRS</text></svg>"
).replace("%23", "#")


def create_app(secret: str | None = None) -> Flask:
    """The comment response sheet as a WSGI application.

    The secret is project control's, so the session cookie it sets is one this
    application can read. Nothing else is shared: no database, no models, no
    imports in either direction.
    """
    app = Flask(__name__, static_folder=None)
    app.config.update(
        SECRET_KEY=secret or _secret(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("HTTPS_ONLY", "").lower() == "true",
    )

    @app.get("/")
    def sheet():
        if not session.get("user_id"):
            # Back to the front door, which knows how to ask for a sign-in and
            # will send them here again once they have.
            return redirect("/login?next=/crs/classic")
        # No caching: the file is replaced by a git pull, and a stale copy in
        # somebody's browser is a bug report nobody can reproduce.
        answer = send_from_directory(HERE / "static", PAGE)
        answer.headers["Cache-Control"] = "no-store"
        return answer

    @app.get("/favicon.ico")
    def favicon():
        return Response(MARK, mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})

    return app


def _secret() -> str:
    """Project control's key, so both applications read the same session."""
    try:
        from app.auth import secret_key

        return secret_key()
    except Exception:                                 # noqa: BLE001 - see below
        # Standing alone rather than beside project control is allowed: the
        # sheet still works, it just cannot tell who is signed in.
        return os.environ.get("SECRET_KEY") or "crs-on-its-own"
