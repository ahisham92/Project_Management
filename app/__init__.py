"""Project Control — a progress, schedule and budget platform for projects.

Run it with ``python run.py``; see the README for first-time setup.
"""

from __future__ import annotations

import os
from datetime import timedelta

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

    @app.context_processor
    def _context():
        return {"current_user": g.get("user"), "app_version": __version__}

    from .views.auth_views import bp as auth_bp
    from .views.portfolio_views import bp as portfolio_bp
    from .views.projects_views import bp as projects_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(portfolio_bp)
    app.register_blueprint(projects_bp)

    @app.errorhandler(403)
    def _forbidden(_error):
        return render_template("error.html", code=403,
                               message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def _not_found(_error):
        return render_template("error.html", code=404, message="That page could not be found."), 404

    return app
