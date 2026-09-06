"""Project Control — a progress, schedule and budget platform for projects.

Run it with ``python run.py``; see the README for first-time setup.
"""

from __future__ import annotations

import os
import time
from datetime import timedelta
from threading import Lock, Thread

from flask import Flask, g, render_template

from . import filters
from .auth import load_user, secret_key
from .db import close_db, database_path, init_db

__version__ = "2.0.0"


def create_app(database: str | None = None, testing: bool = False) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DATABASE=database or str(database_path()),
        SECRET_KEY=secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        # Sent only over HTTPS once the app is served over TLS.
        SESSION_COOKIE_SECURE=os.environ.get("HTTPS_ONLY", "").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
        TESTING=testing,
    )

    init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)
    filters.register(app)

    @app.before_request
    def _before():
        load_user()
        _nightly(app)

    @app.context_processor
    def _context():
        return {"current_user": g.get("user"), "app_version": __version__}

    if not os.environ.get("SECRET_KEY"):
        # The key is generated and kept in the data directory. That is fine on a
        # machine that keeps its files, but on a host with an ephemeral disk it
        # is regenerated on every restart and signs everyone out.
        app.logger.warning(
            "SECRET_KEY is not set — a generated one is stored in the data directory. "
            "Set SECRET_KEY when hosting this for a team, or everyone is signed out on restart."
        )

    from .views.auth_views import bp as auth_bp
    from .views.meetings_views import bp as meetings_bp
    from .views.portfolio_views import bp as portfolio_bp
    from .views.projects_views import bp as projects_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(meetings_bp)

    @app.get("/healthz")
    def _healthz():
        """A cheap liveness check for whatever platform the app is hosted on."""
        try:
            from .db import connect

            connect(app.config["DATABASE"]).execute("SELECT 1").fetchone()
        except Exception:  # noqa: BLE001 - the check itself must never raise
            return {"status": "error"}, 503
        return {"status": "ok", "version": __version__}

    @app.errorhandler(403)
    def _forbidden(_error):
        return render_template("error.html", code=403,
                               message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def _not_found(_error):
        return render_template("error.html", code=404, message="That page could not be found."), 404

    return app


# The last time the nightly backup was even considered. Checking the database
# on every request for something that happens once a day is waste; checking it
# once every few minutes is not.
_LOOKED_AT = 0.0
_ASKING = Lock()
_LOOK_EVERY = 300                                     # seconds


def _nightly(app: Flask) -> None:
    """Runs the nightly backup if the hour has passed and nothing has run.

    A scheduled task is the proper way to do this and the README says so. This
    is the second belt: on a host whose scheduler runs in UTC, or whose free
    plan allows one task a day, or where somebody forgot, a backup that is owed
    is taken the next time anybody opens a page. Two of them cannot collide —
    whichever gets there first writes the run, and the other sees it.
    """
    global _LOOKED_AT

    if app.config.get("TESTING") or os.environ.get("BACKUP_ON_REQUEST", "").lower() == "off":
        return

    now = time.monotonic()
    if now - _LOOKED_AT < _LOOK_EVERY or not _ASKING.acquire(blocking=False):
        return
    try:
        _LOOKED_AT = now
        from .service import backup_due

        if not backup_due():
            return
    except Exception:                                 # noqa: BLE001 - never break a page
        return
    finally:
        _ASKING.release()

    # Off the request: uploading a database to Drive is not something a reader
    # should wait for. The thread opens its own application context because the
    # request's is gone by the time it runs.
    def _run() -> None:
        with app.app_context():
            try:
                from .service import backup_if_due

                backup_if_due()
            except Exception:                         # noqa: BLE001 - it records its own failures
                app.logger.exception("The nightly backup could not be taken")

    Thread(target=_run, name="nightly-backup", daemon=True).start()
