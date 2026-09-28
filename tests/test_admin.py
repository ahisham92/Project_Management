"""The admin panel: accounts made by the administrator, and programs per account."""

from __future__ import annotations

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client

from app import triton_door


def text(response) -> str:
    return response.get_data(as_text=True)


def make(signed_in, username="sara", programs=("triton",), password="longenough1"):
    return signed_in.post("/admin/users", data={
        "username": username, "password": password, "name": "Sara", "programs": list(programs)})


def test_public_sign_up_is_closed(client, monkeypatch):
    monkeypatch.setenv("ALLOW_SIGNUP", "false")
    assert "Create account" not in text(client.get("/login"))
    answer = client.post("/register", data={"email": "x@example.com", "name": "X", "password": "longenough1"})
    assert answer.status_code == 302 and "/login" in answer.headers["Location"]


def test_only_admins_reach_the_panel(app, signed_in):
    assert "Users (" in text(signed_in.get("/admin/"))
    make(signed_in)
    other = app.test_client()
    other.post("/login", data={"email": "sara", "password": "longenough1"})
    assert other.get("/admin/").status_code == 404
    assert app.test_client().get("/admin/").status_code == 302


def test_admin_lists_accounts_and_creates_one_that_signs_in_by_username(app, signed_in):
    answer = make(signed_in, programs=("pm", "triton"))
    assert answer.status_code == 302
    page = text(signed_in.get("/admin/"))
    assert "sara" in page and "admin@example.com" in page
    assert "Project Management, Triton" in page

    sara = app.test_client()
    assert sara.post("/login", data={"email": "SARA", "password": "longenough1"}).status_code == 302
    home = text(sara.get("/"))
    assert "Open Project Management" in home and "Open Triton" in home
    assert "Open the Comment Response Sheet" not in home


def test_duplicate_or_bad_usernames_are_refused(signed_in):
    make(signed_in)
    assert "already taken" in text(make(signed_in) and signed_in.get("/admin/?tab=new"))
    assert "3 to 40" in text(signed_in.post("/admin/users", data={"username": "a b", "password": "longenough1"},
                                            follow_redirects=True))


def test_a_program_not_given_is_blocked_by_address(app, signed_in):
    make(signed_in, programs=("triton",))
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert sara.get("/projects").status_code == 403
    assert sara.get("/projects/1/", follow_redirects=True).status_code == 403
    assert sara.get("/crs", follow_redirects=True).status_code == 403
    assert "Portfolio" not in text(sara.get("/"))


def test_triton_is_blocked_for_an_account_without_it(app, signed_in, tmp_path, monkeypatch):
    monkeypatch.setenv("TRITON_DATA_DIR", str(tmp_path / "triton"))
    make(signed_in, programs=("pm",))
    site = Client(DispatcherMiddleware(app, triton_door.mounts(app)))
    site.post("/login", data={"email": "sara", "password": "longenough1"})
    assert site.get("/triton/api/projects").status_code == 403
    answer = site.get("/triton/")
    assert answer.status_code == 302 and answer.headers["Location"] == "/?not=triton"


def test_existing_accounts_keep_every_program(app, client):
    client.post("/register", data={"email": "old@example.com", "name": "Old", "password": "longenough1"})
    home = text(client.get("/"))
    assert "Open Project Management" in home and "Open Triton" in home


def test_admin_edits_programs_resets_password_and_deletes(app, signed_in):
    make(signed_in, programs=())
    from app.db import query_one
    with app.app_context():
        sara_id = query_one("SELECT id FROM users WHERE username = 'sara'")["id"]
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert "not been given any programs" in text(sara.get("/"))

    signed_in.post(f"/admin/users/{sara_id}", data={"username": "sara", "name": "Sara", "programs": ["crs"]})
    assert "Open the Comment Response Sheet" in text(sara.get("/"))

    signed_in.post(f"/admin/users/{sara_id}/password", data={"password": "brandnew123"})
    fresh = app.test_client()
    assert fresh.post("/login", data={"email": "sara", "password": "brandnew123"}).status_code == 302

    signed_in.post(f"/admin/users/{sara_id}/delete")
    with app.app_context():
        assert query_one("SELECT 1 FROM users WHERE id = ?", (sara_id,)) is None


def test_admin_cannot_demote_or_delete_themself(app, signed_in):
    from app.db import query_one
    with app.app_context():
        me = query_one("SELECT id FROM users WHERE email = 'admin@example.com'")["id"]
    signed_in.post(f"/admin/users/{me}", data={"username": "", "name": "Admin", "email": "admin@example.com"})
    signed_in.post(f"/admin/users/{me}/delete")
    with app.app_context():
        row = query_one("SELECT role FROM users WHERE id = ?", (me,))
    assert row["role"] == "admin"
