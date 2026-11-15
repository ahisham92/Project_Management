"""JEDSA behind the front door.

JEDSA, structural analysis and design, is an application of its own, mounted in
front of ``/jedsa``. What is worth pinning down is that the door offers it, and
that it answers only somebody signed in here and given JEDSA.
"""

from __future__ import annotations

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client

from app import jedsa_door


def text(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def mounted(app, monkeypatch):
    import jedsa_app.wsgi as inner

    monkeypatch.delenv("JEDSA_DEV_ACCOUNT", raising=False)
    monkeypatch.setattr(inner, "_app", None)
    return DispatcherMiddleware(app, jedsa_door.mounts(app))


@pytest.fixture()
def site(mounted):
    return Client(mounted)


def sign_in(site: Client, email="admin@example.com", password="changeme123") -> None:
    answer = site.post("/login", data={"email": email, "password": password})
    assert answer.status_code in (301, 302), text(answer)


def test_the_front_page_offers_jedsa(signed_in):
    page = text(signed_in.get("/"))
    assert "JEDSA" in page and 'href="/jedsa/"' in page


def test_a_stranger_is_sent_to_sign_in(site):
    answer = site.get("/jedsa/")
    assert answer.status_code == 302 and "/login" in answer.headers["Location"]
    assert site.get("/jedsa/healthz").status_code == 200


def test_signed_in_it_opens_the_program(site):
    sign_in(site)
    answer = site.get("/jedsa/")
    assert answer.status_code == 200 and "<title>JEDSA" in text(answer)
    assert site.get("/jedsa").status_code == 301


def test_an_account_not_given_jedsa_is_turned_away(site, mounted):
    sign_in(site)
    made = site.post("/admin/users", data={
        "username": "osama", "name": "Osama", "password": "longenough1",
        "role": "user", "programs": ["pm"]}, follow_redirects=True)
    assert made.status_code == 200
    theirs = Client(mounted)
    theirs.post("/login", data={"email": "osama", "password": "longenough1"})
    answer = theirs.get("/jedsa/")
    assert answer.status_code == 302 and "not=jedsa" in answer.headers["Location"]
    assert 'href="/jedsa/"' not in text(theirs.get("/"))


def test_without_the_package_the_door_says_so(signed_in, monkeypatch):
    monkeypatch.setattr(jedsa_door, "_state", {"ready": False, "trouble": ""})
    page = text(signed_in.get("/jedsa/"))
    assert "JEDSA is not running here yet" in page
