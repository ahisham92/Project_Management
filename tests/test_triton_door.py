"""Triton behind the front door.

Triton is an application of its own, mounted in front of ``/triton``. What is
worth pinning down is that the door offers it, that nothing gets through to it
without project control's sign-in, and that its files land beside the database.
"""

from __future__ import annotations

import os
import signal

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client

from app import triton_door


def text(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def site(app, tmp_path, monkeypatch):
    """The site as the host serves it: project control with Triton mounted."""
    monkeypatch.setenv("TRITON_DATA_DIR", str(tmp_path / "triton"))
    return Client(DispatcherMiddleware(app, triton_door.mounts(app)))


def sign_in(site: Client) -> None:
    answer = site.post("/login", data={"email": "admin@example.com", "password": "changeme123"})
    assert answer.status_code in (301, 302)


def test_the_front_door_offers_triton(signed_in):
    page = text(signed_in.get("/"))
    assert "Triton" in page
    assert 'href="/triton/"' in page
    assert "door-shut" not in page


def test_triton_is_mounted(app):
    assert set(triton_door.mounts(app)) == {"/triton"}
    assert triton_door.describe()["ready"] is True


def test_a_stranger_is_sent_to_sign_in_and_back(site):
    answer = site.get("/triton/")
    assert answer.status_code == 302
    assert answer.headers["Location"] == "/login?next=/triton/"


def test_an_api_call_without_a_session_is_refused(site):
    answer = site.get("/triton/api/projects")
    assert answer.status_code == 401
    assert answer.json == {"detail": "Sign in to use Triton."}


def test_a_forged_session_for_nobody_is_refused(app, site):
    """A signed cookie for a user who does not exist is not a sign-in."""
    with app.test_client() as other:
        with other.session_transaction() as kept:
            kept["user_id"] = 999_999
        cookie = other.get_cookie("session")
    site.set_cookie("session", cookie.value)
    assert site.get("/triton/api/projects").status_code == 401


def test_signed_in_the_whole_of_triton_answers(site, tmp_path):
    sign_in(site)

    page = site.get("/triton/")
    assert page.status_code == 200
    body = text(page)
    assert "<title>Triton</title>" in body
    # Its files are asked for relative to /triton/, and there is a way back.
    assert 'href="static/style.css"' in body
    assert '<a class="home" href="/">&larr; Project Control</a>' in body
    assert site.get("/triton/static/app.js").status_code == 200

    made = site.post("/triton/api/projects", json={"info": {"name": "Quay wall"}})
    assert made.status_code in (200, 201), text(made)
    listed = site.get("/triton/api/projects").json
    assert [p["name"] for p in listed] == ["Quay wall"]
    # Beside the database, not inside the repository.
    assert any((tmp_path / "triton" / "projects").iterdir())


def test_the_address_without_a_slash_is_moved_to_one(site):
    answer = site.get("/triton")
    assert answer.status_code == 301
    assert answer.headers["Location"] == "/triton/"


def test_project_control_is_untouched(site):
    sign_in(site)
    assert site.get("/projects").status_code == 200


def test_files_go_beside_the_database_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("TRITON_DATA_DIR", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert triton_door.data_folder() == tmp_path / "triton"


def test_a_triton_that_will_not_import_leaves_the_site_up(app, signed_in, monkeypatch):
    def explode(_name):
        raise ModuleNotFoundError("No module named 'pandas'", name="pandas")

    monkeypatch.setattr(triton_door.importlib, "import_module", explode)
    monkeypatch.setattr(triton_door, "_state", {})

    assert triton_door.mounts(app) == {}
    page = text(signed_in.get("/"))
    assert "door-shut" in page and "not installed" in page
    missing = signed_in.get("/triton/")
    assert missing.status_code == 200
    assert "pandas" in text(missing)


def test_the_wsgi_entry_point_mounts_triton(monkeypatch):
    import importlib

    import wsgi

    again = importlib.reload(wsgi)
    assert "/triton" in again.application.mounts


@pytest.mark.skipif(not hasattr(os, "fork"), reason="needs fork")
def test_triton_answers_in_a_forked_worker(site):
    """PythonAnywhere's server loads the site and then forks its workers. Triton has to answer in
    the fork, where no thread started at import survives."""
    sign_in(site)
    pid = os.fork()
    if pid == 0:  # the worker
        signal.alarm(20)
        ok = site.get("/triton/").status_code == 200 and site.get("/triton/api/projects").status_code == 200
        os._exit(0 if ok else 1)
    _, code = os.waitpid(pid, 0)
    assert os.WIFEXITED(code) and os.WEXITSTATUS(code) == 0
