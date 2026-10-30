"""Iris behind the front door.

Iris is an application of its own, mounted in front of ``/iris``. What is worth
pinning down is that the door offers it, that its phone pages answer only
somebody signed in here (and given Iris), that a tool can still reach its API
with nothing but its own token, and that one account never sees another's tools.
"""

from __future__ import annotations

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client

from app import iris_door


def text(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def mounted(app, tmp_path, monkeypatch):
    """The site as the host serves it: project control with Iris mounted."""
    import iris_app.wsgi as inner

    monkeypatch.setenv("IRIS_DATA_DIR", str(tmp_path / "iris"))
    monkeypatch.setattr(inner, "_app", None)          # one per process; a fresh one per test
    return DispatcherMiddleware(app, iris_door.mounts(app))


@pytest.fixture()
def site(mounted):
    return Client(mounted)


def sign_in(site: Client, email="admin@example.com", password="changeme123") -> None:
    answer = site.post("/login", data={"email": email, "password": password})
    assert answer.status_code in (301, 302), text(answer)


def colleague(site: Client, mounted, username="osama", programs=("pm", "iris")) -> Client:
    made = site.post("/admin/users", data={
        "username": username, "name": username.title(), "password": "longenough1",
        "role": "user", "programs": list(programs)}, follow_redirects=True)
    assert made.status_code == 200, text(made)
    theirs = Client(mounted)
    answer = theirs.post("/login", data={"email": username, "password": "longenough1"})
    assert answer.status_code in (301, 302), text(answer)
    return theirs


def connect_tool(site: Client, phone: Client) -> tuple[dict, int]:
    """A tool asks to be connected and the signed-in phone accepts it."""
    started = site.post("/iris/api/tool/pair", json={"name": "Sketch ProMax", "machine": "PC-01",
                                                     "commands": ["Stop"]}).json
    accepted = phone.post("/iris/api/me/pair", json={"code": started["code"]})
    assert accepted.status_code == 200, text(accepted)
    done = site.get(f"/iris/api/tool/pair/{started['pair_id']}",
                    headers={"X-Pair-Secret": started["secret"]}).json
    assert done["status"] == "connected"
    return {"Authorization": "Bearer " + done["token"]}, accepted.json["id"]


def test_the_front_door_offers_iris(signed_in):
    page = text(signed_in.get("/"))
    assert "Open Iris" in page
    assert 'href="/iris/"' in page


def test_iris_is_mounted(mounted):
    assert iris_door.describe()["ready"] is True


def test_a_stranger_is_sent_to_sign_in_and_back(site):
    answer = site.get("/iris/")
    assert answer.status_code == 302
    assert answer.headers["Location"] == "/login?next=/iris/"
    assert site.get("/iris").status_code == 301
    assert site.get("/iris/api/me/tools").status_code == 401


def test_the_pairing_page_and_app_files_need_no_sign_in(site):
    assert site.get("/iris/pair").status_code == 200
    assert site.get("/iris/sw.js").status_code == 200
    assert site.get("/iris/manifest.webmanifest").json["start_url"] == "/iris/"
    assert site.get("/iris/static/iris-crypto.js").status_code == 200


def test_a_browser_cannot_claim_to_be_somebody(site):
    # Whoever the request says it is, without the site's session it is nobody.
    answer = site.get("/iris/api/me/tools", headers={"Iris-Site": '{"id": "1"}'})
    assert answer.status_code == 401


def test_signed_in_phone_connects_a_tool_and_answers(site):
    sign_in(site)
    assert "Iris" in text(site.get("/iris/"))
    auth, tool_id = connect_tool(Client(site.application), site)

    tool = Client(site.application)                    # no session, only its token
    q = tool.post("/iris/api/tool/messages", headers=auth, json={"kind": "question", "body": "v1.q"}).json
    feed = site.get(f"/iris/api/me/tools/{tool_id}/messages").json["messages"]
    assert [m["body"] for m in feed] == ["v1.q"]
    site.post(f"/iris/api/me/tools/{tool_id}/messages", json={"kind": "answer", "reply_to": q["id"], "body": "v1.a"})
    assert [m["body"] for m in tool.get("/iris/api/tool/inbox", headers=auth).json["messages"]] == ["v1.a"]
    assert tool.get("/iris/api/tool/inbox", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_accounts_see_only_their_own_tools(site, mounted):
    sign_in(site)
    _, tool_id = connect_tool(Client(mounted), site)
    theirs = colleague(site, mounted)
    assert theirs.get("/iris/api/me/tools").json["tools"] == []
    assert theirs.get(f"/iris/api/me/tools/{tool_id}/messages").status_code == 404


def test_an_account_without_iris_is_turned_away(site, mounted):
    sign_in(site)
    theirs = colleague(site, mounted, username="karim", programs=("pm",))
    assert theirs.get("/iris/").headers["Location"] == "/?not=iris"
    assert theirs.get("/iris/api/me/tools").status_code == 403
    assert "Open Iris" not in text(theirs.get("/"))
