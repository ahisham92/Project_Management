"""Shared fixtures: a throwaway database seeded with the demo project."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# The app reads DATA_DIR at import time for the secret key, so point it at a
# temporary directory before anything else is imported.
_TMP = tempfile.mkdtemp(prefix="pm-tests-")
os.environ.setdefault("DATA_DIR", _TMP)
os.environ.setdefault("SECRET_KEY", "test-secret")

from app import create_app  # noqa: E402
from app.seed import seed as seed_database  # noqa: E402


@pytest.fixture()
def database(tmp_path: Path) -> str:
    path = tmp_path / "test.sqlite"
    seed_database(str(path), quiet=True)
    return str(path)


@pytest.fixture()
def app(database: str):
    application = create_app(database=database, testing=True)
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def signed_in(client):
    """A client already signed in as the seeded administrator."""
    client.post("/login", data={"email": "admin@example.com", "password": "changeme123"})
    return client
