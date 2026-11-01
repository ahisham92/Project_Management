"""SiteTwin behind the front door.

SiteTwin is an application of its own, mounted in front of ``/sitetwin``. What is
worth pinning down is that the door offers it, that it answers only somebody
signed in here and given SiteTwin, and that it is told who is asking.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client

from app import sitetwin_door

SMALL = (Path(__file__).parent / "fixtures" / "sitetwin_small.ifc").read_bytes()


def text(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def mounted(app, tmp_path, monkeypatch):
    import sitetwin_app.wsgi as inner

    monkeypatch.setenv("SITETWIN_DATA_DIR", str(tmp_path / "sitetwin"))
    monkeypatch.setattr(inner, "_app", None)
    return DispatcherMiddleware(app, sitetwin_door.mounts(app))


@pytest.fixture()
def site(mounted):
    return Client(mounted)


def sign_in(site: Client, email="admin@example.com", password="changeme123") -> None:
    answer = site.post("/login", data={"email": email, "password": password})
    assert answer.status_code in (301, 302), text(answer)


def test_the_front_page_offers_sitetwin(signed_in):
    page = text(signed_in.get("/"))
    assert "SiteTwin" in page and 'href="/sitetwin/"' in page


def test_a_stranger_is_sent_to_sign_in(site):
    answer = site.get("/sitetwin/")
    assert answer.status_code == 302 and "/login" in answer.headers["Location"]
    assert site.get("/sitetwin/api/projects").status_code == 401


def test_signed_in_it_opens_and_takes_a_model(site):
    sign_in(site)
    assert "Projects" in text(site.get("/sitetwin/"))
    made = site.post("/sitetwin/projects", data={"name": "Berth 3"})
    assert made.status_code == 302
    pid = made.headers["Location"].rstrip("/").split("/")[-1]
    up = site.post(f"/sitetwin/projects/{pid}/model",
                   data={"model": (io.BytesIO(SMALL), "berth3.ifc")})
    assert up.status_code == 302, text(up)
    project = site.get(f"/sitetwin/api/projects/{pid}").json["project"]
    assert project["location_from"] == "ifc" and project["model_name"] == "berth3.ifc"


def test_an_account_not_given_sitetwin_is_turned_away(site, mounted):
    sign_in(site)
    made = site.post("/admin/users", data={
        "username": "osama", "name": "Osama", "password": "longenough1",
        "role": "user", "programs": ["pm"]}, follow_redirects=True)
    assert made.status_code == 200
    theirs = Client(mounted)
    theirs.post("/login", data={"email": "osama", "password": "longenough1"})
    answer = theirs.get("/sitetwin/")
    assert answer.status_code == 302 and "not=sitetwin" in answer.headers["Location"]
    assert "SiteTwin" not in text(theirs.get("/"))
