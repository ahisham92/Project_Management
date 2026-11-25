"""GeoProMax behind the front door.

GeoProMax, settlement, is an application of its own, mounted in front of
``/geopromax``. What is worth pinning down is that the door offers it, that it
answers only somebody signed in here and given GeoProMax, that it is told who is
asking, and that each person's projects stay their own.
"""

from __future__ import annotations

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client

from app import geopromax_door


def text(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def mounted(app, tmp_path, monkeypatch):
    import geopromax_app.wsgi as inner

    monkeypatch.setenv("GEOPROMAX_DATA_DIR", str(tmp_path / "geopromax"))
    monkeypatch.delenv("GEOPROMAX_DEV_ACCOUNT", raising=False)
    monkeypatch.setattr(inner, "_app", None)
    return DispatcherMiddleware(app, geopromax_door.mounts(app))


@pytest.fixture()
def site(mounted):
    return Client(mounted)


def sign_in(site: Client, email="admin@example.com", password="changeme123") -> None:
    answer = site.post("/login", data={"email": email, "password": password})
    assert answer.status_code in (301, 302), text(answer)


def test_the_front_page_offers_geopromax(signed_in):
    page = text(signed_in.get("/"))
    assert "GeoProMax" in page and 'href="/geopromax/"' in page


def test_a_stranger_is_sent_to_sign_in(site):
    answer = site.get("/geopromax/")
    assert answer.status_code == 302 and "/login" in answer.headers["Location"]
    assert site.get("/geopromax/api/projects").status_code == 401
    # its scripts and styles need no sign-in
    assert site.get("/geopromax/static/engine/settlement.js").status_code == 200


def test_signed_in_it_opens_and_keeps_a_project(site):
    sign_in(site)
    page = text(site.get("/geopromax/"))
    assert "GeoProMax" in page and '"/geopromax/api"' in page
    made = site.post("/geopromax/api/projects", json={"data": {"type": "settlement", "name": "Tank farm"}})
    assert made.status_code == 201, text(made)
    listing = site.get("/geopromax/api/projects").json["projects"]
    assert [p["name"] for p in listing] == ["Tank farm"]


def test_nobody_can_claim_to_be_someone_else(site):
    sign_in(site)
    answer = site.get("/geopromax/api/projects", environ_overrides={"geopromax.site": {"id": "999", "name": "x", "login": "x"}})
    assert answer.status_code == 200 and answer.json["projects"] == []


def test_an_account_not_given_geopromax_is_turned_away(site, mounted):
    sign_in(site)
    made = site.post("/admin/users", data={
        "username": "osama", "name": "Osama", "password": "longenough1",
        "role": "user", "programs": ["pm"]}, follow_redirects=True)
    assert made.status_code == 200
    theirs = Client(mounted)
    theirs.post("/login", data={"email": "osama", "password": "longenough1"})
    answer = theirs.get("/geopromax/")
    assert answer.status_code == 302 and "not=geopromax" in answer.headers["Location"]
    assert theirs.get("/geopromax/api/projects").status_code == 403
    assert 'href="/geopromax/"' not in text(theirs.get("/"))
