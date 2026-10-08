"""Workload behind the front door.

Workload is an application of its own, mounted in front of ``/workload``. What
is worth pinning down is that the door offers it, that nothing reaches it
without project control's sign-in, that whoever is signed in here *is* the
Workload account — no second password — and that one account's unit stays
invisible to every other until its owner gives access.
"""

from __future__ import annotations

import pytest
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.test import Client

from app import workload_door


def text(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def mounted(app, tmp_path, monkeypatch):
    """The site as the host serves it: project control with Workload mounted."""
    import workload_app.wsgi as inner

    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "workload"))
    monkeypatch.setattr(inner, "_app", None)          # one per process; a fresh one per test
    return DispatcherMiddleware(app, workload_door.mounts(app))


@pytest.fixture()
def site(mounted):
    return Client(mounted)


def sign_in(site: Client, email="admin@example.com", password="changeme123") -> None:
    answer = site.post("/login", data={"email": email, "password": password})
    assert answer.status_code in (301, 302), text(answer)


def colleague(site: Client, mounted, username="osama", programs=("pm", "workload")) -> Client:
    """An account the administrator makes, signed in on a browser of its own."""
    made = site.post("/admin/users", data={
        "username": username, "name": username.title(), "password": "longenough1",
        "role": "user", "programs": list(programs)}, follow_redirects=True)
    assert made.status_code == 200, text(made)
    theirs = Client(mounted)
    answer = theirs.post("/login", data={"email": username, "password": "longenough1"})
    assert answer.status_code in (301, 302), text(answer)
    return theirs


def test_the_front_door_offers_workload(signed_in):
    page = text(signed_in.get("/"))
    assert "Open Selecao+" in page
    assert 'href="/workload/"' in page


def test_workload_is_mounted(app, mounted):
    assert workload_door.describe()["ready"] is True


def test_a_stranger_is_sent_to_sign_in_and_back(site):
    answer = site.get("/workload/")
    assert answer.status_code == 302
    assert answer.headers["Location"] == "/login?next=/workload/"
    assert site.get("/workload").status_code == 301


def test_an_api_call_without_a_session_is_refused(site):
    answer = site.get("/workload/api/units")
    assert answer.status_code == 401
    assert answer.json["error"] == "Sign in to use Selecao+."
    # Workload's own sign-in is not a way round the site's.
    assert site.post("/workload/api/auth/login",
                     json={"username": "a", "password": "b"}).status_code == 401


def test_a_forged_session_for_nobody_is_refused(app, site):
    with app.test_client() as other:
        with other.session_transaction() as kept:
            kept["user_id"] = 999_999
        cookie = other.get_cookie("session")
    site.set_cookie("session", cookie.value)
    assert site.get("/workload/api/units").status_code == 401


def test_a_header_cannot_say_who_you_are(site):
    answer = site.get("/workload/api/units", headers={
        "Workload-Site": "admin@example.com", "X-Workload-Site": "admin@example.com"})
    assert answer.status_code == 401


def test_signed_in_here_is_signed_in_there(site, tmp_path):
    sign_in(site)

    page = site.get("/workload/")
    assert page.status_code == 200
    body = text(page)
    assert "<title>Selecao+" in body
    # Its files are asked for relative to /workload/, and it has no login page here.
    assert 'src="app.js' in body and "login-form" not in body
    assert site.get("/workload/app.js").status_code == 200
    # The logo is served from under the mount too.
    assert site.get("/workload/logo.svg").status_code == 200
    assert site.get("/workload/brand/selecao-mark.svg").status_code == 200
    assert site.get("/workload/brand/selecao-icon-192.png").status_code == 200
    moved = site.get("/workload/login.html")
    assert moved.status_code == 303 and moved.headers["Location"] == "/workload/"

    who = site.get("/workload/api/auth/me").json
    assert who["user"]["site_login"] == "admin@example.com"
    assert who["site"]["home"] == "/" and who["site"]["logout"] == "/logout"

    made = site.post("/workload/api/units", json={"name": "Marine Structures"})
    assert made.status_code == 200, text(made)
    assert [u["name"] for u in site.get("/workload/api/units").json["units"]] \
        == ["Marine Structures"]
    # Beside the database, not inside the repository.
    assert list((tmp_path / "workload" / "users").glob("*/*.db"))


def test_a_unit_is_its_owners_alone(site, mounted):
    sign_in(site)
    assert site.post("/workload/api/units", json={"name": "Marine Structures"}).status_code == 200
    unit = site.get("/workload/api/units").json["units"][0]

    osama = colleague(site, mounted)
    assert osama.get("/workload/api/units").json["units"] == []
    assert osama.post(f"/workload/api/units/{unit['id']}/open", json={}).status_code == 404
    assert osama.get(f"/workload/api/units/{unit['id']}/download").status_code == 404
    # They have an account of their own, with nothing open in it.
    assert osama.get("/workload/api/status").json.get("open") in (False, None)


def test_correcting_an_address_in_the_admin_panel_loses_nobody_their_units(app, site, mounted):
    sign_in(site)
    osama = colleague(site, mounted)
    assert osama.post("/workload/api/units", json={"name": "Buildings"}).status_code == 200
    user_id = query(app, "SELECT id FROM users WHERE username = 'osama'")
    changed = site.post(f"/admin/users/{user_id}", data={
        "username": "osama.k", "name": "Osama K", "email": "osama.k@example.com",
        "role": "user", "programs": ["pm", "workload"]}, follow_redirects=True)
    assert changed.status_code == 200, text(changed)
    assert [u["name"] for u in osama.get("/workload/api/units").json["units"]] == ["Buildings"]
    assert osama.get("/workload/api/auth/me").json["user"]["site_login"] == "osama.k"


def query(app, sql: str):
    from app.db import connect

    conn = connect(app.config["DATABASE"])
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_access_is_given_to_somebody_who_signs_in_here(app, site, mounted):
    sign_in(site)
    site.post("/workload/api/units", json={"name": "Marine Structures"})
    assert site.post("/workload/api/team", json={
        "short_name": "Osama", "pattern": "*Osama*", "available_hours": 160}).status_code == 200
    osama = colleague(site, mounted)
    colleague(site, mounted, username="nour", programs=("pm",))    # not given Workload

    offered = site.get("/workload/api/team/access").json["site"]["people"]
    assert [p["login"] for p in offered] == ["osama"]              # not yourself, not nour
    nour = query(app, "SELECT id FROM users WHERE username = 'nour'")

    refused = site.post("/workload/api/team/access", json={"engineer": "Osama", "person": str(nour)})
    assert refused.status_code == 422, text(refused)
    given = site.post("/workload/api/team/access",
                      json={"engineer": "Osama", "person": offered[0]["id"]})
    assert given.status_code == 200, text(given)
    assert given.json["password"] is None

    mine = osama.get("/workload/api/me")
    assert mine.status_code == 200, text(mine)
    assert mine.json["unit"]["name"] == "Marine Structures"
    assert "member.js" in text(osama.get("/workload/"))
    # Their own figures and nothing else: the unit itself stays shut.
    assert osama.get("/workload/api/projects").status_code == 403
    assert osama.get("/workload/api/units").json["read_only"] is True


def test_an_account_without_the_program_is_turned_back(site, mounted):
    sign_in(site)
    nour = colleague(site, mounted, username="nour", programs=("pm",))
    assert "Open Selecao+" not in text(nour.get("/"))
    assert nour.get("/workload/api/units").status_code == 403
    answer = nour.get("/workload/")
    assert answer.status_code == 302 and answer.headers["Location"] == "/?not=workload"
    assert "has not been given Selecao+" in text(nour.get("/?not=workload"))


def test_units_from_before_the_move_come_across(site, tmp_path):
    """An account from Workload's own address, brought in with its password once."""
    import workload_app.wsgi as inner

    old = inner.get_app().accounts.create_user("ahmed", "a-good-long-password")
    inner.get_app().accounts.create_unit(old["id"], "Marine Structures", "missing.xlsx")

    sign_in(site)
    assert site.get("/workload/api/units").json["units"] == []
    linked = site.post("/workload/api/auth/link",
                       json={"username": "ahmed", "password": "a-good-long-password"})
    assert linked.status_code == 200, text(linked)
    assert [u["name"] for u in site.get("/workload/api/units").json["units"]] \
        == ["Marine Structures"]


def test_without_the_package_the_door_says_so(app, signed_in, monkeypatch):
    monkeypatch.setattr(workload_door, "_import", lambda: (None, "Workload needs openpyxl"))
    monkeypatch.setattr(workload_door, "_state", {})
    assert workload_door.mounts(app) == {}
    page = text(signed_in.get("/"))
    assert "not installed" in page
    assert "Workload needs openpyxl" in text(signed_in.get("/workload/"))


def test_an_outlook_email_comes_in_with_its_key_and_nothing_else(site, mounted):
    """An Outlook flow has no AHM session: the key in its body is all it brings."""
    sign_in(site)
    assert site.post("/workload/api/units", json={"name": "Marine Structures"}).status_code == 200
    unit = site.get("/workload/api/units").json["units"][0]
    assert site.post(f"/workload/api/units/{unit['id']}/open", json={}).status_code == 200
    made = site.post("/workload/api/inbox-key", json={})
    assert made.status_code == 200, text(made)
    key = made.json["key_value"]

    outlook = Client(mounted)
    email = {"id": "<m1@example.com>", "from": "client@example.com", "subject": "RFI 12 - pile cap",
             "preview": "Please confirm the pile cap reinforcement by Friday.",
             "received": "2026-10-08T08:00:00Z"}
    taken = outlook.post("/workload/api/inbox/email", json={"key": key, **email})
    assert taken.status_code == 200, text(taken)
    assert taken.json["ok"] is True
    # It landed in the senior's own inbox.
    assert site.get("/workload/api/inbox").status_code == 200

    # A wrong key is Workload's to refuse, not the door's.
    wrong = outlook.post("/workload/api/inbox/email", json={"key": "nope", **email})
    assert wrong.status_code == 401
    assert "not recognised" in wrong.json["error"]
    # Nothing else gets past without signing in: not reading the inbox, not
    # another method on the same address.
    assert outlook.get("/workload/api/inbox").status_code == 401
    assert outlook.get("/workload/api/inbox/email").json["error"] == "Sign in to use Selecao+."


def test_a_nightly_export_reaches_workload_without_a_session(site):
    answer = site.post("/workload/api/nightly/timesheets", json={"key": "nope"})
    assert answer.status_code == 401
    assert "import key is not recognised" in answer.json["error"]
