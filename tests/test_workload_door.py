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
    # common.js loads first and is served from under the mount as well.
    assert body.index('src="common.js') < body.index('src="meaning.js') < body.index('src="app.js')
    assert site.get("/workload/common.js").status_code == 200
    assert site.get("/workload/meaning.js").status_code == 200
    # Each tab's own look: look.js right after paths.js, look.css after the other sheets.
    assert body.index('src="paths.js') < body.index('src="look.js') < body.index('src="pocket.js')
    assert body.index('href="paths.css') < body.index('href="look.css')
    assert site.get("/workload/look.js").status_code == 200
    assert site.get("/workload/look.css").status_code == 200
    # Schedules and submissions: their scripts and sheet are served from under the mount too.
    # The short answer at the top of every tab: focus.js after look.js, focus.css after look.css.
    assert body.index('src="look.js') < body.index('src="focus.js') < body.index('src="pocket.js')
    assert body.index('href="look.css') < body.index('href="focus.css')
    for name in ("dates.js", "sheet.js", "subs.js", "sheet.css", "focus.js", "focus.css"):
        assert site.get(f"/workload/{name}").status_code == 200
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


def test_an_email_cannot_come_in_without_signing_in(site, mounted):
    """The Emails panel is gone, so its old address is shut like any other."""
    outlook = Client(mounted)
    email = {"key": "anything", "id": "<m1@example.com>", "from": "client@example.com",
             "subject": "RFI 12 - pile cap", "received": "2026-10-08T08:00:00Z"}
    taken = outlook.post("/workload/api/inbox/email", json=email)
    assert taken.status_code == 401
    assert taken.json["error"] == "Sign in to use Selecao+."


def test_a_nightly_export_reaches_workload_without_a_session(site):
    answer = site.post("/workload/api/nightly/timesheets", json={"key": "nope"})
    assert answer.status_code == 401
    assert "import key is not recognised" in answer.json["error"]


def test_a_nightly_budgets_export_reaches_workload_without_a_session(site):
    """The kit sends budgets to the same nightly address with a kind."""
    answer = site.post("/workload/api/nightly/timesheets",
                       json={"key": "nope", "kind": "budgets", "files": []})
    assert answer.status_code == 401
    assert "import key is not recognised" in answer.json["error"]


def _who_workload_is_told(app, tmp_path, monkeypatch, as_colleague=False) -> dict:
    """Sign in and return the site identity the door hands Workload."""
    import workload_app.wsgi as inner

    seen: dict = {}

    def spy(environ, start_response):
        seen.update(environ.get(inner.SITE_KEY) or {})
        start_response("200 OK", [("Content-Type", "application/json")])
        return [b"{}"]

    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "workload"))
    monkeypatch.setattr(inner, "_app", None)
    monkeypatch.setattr(inner, "application", spy)
    mounted = DispatcherMiddleware(app, workload_door.mounts(app))
    browser = Client(mounted)
    sign_in(browser)
    if as_colleague:
        browser = colleague(browser, mounted)
    assert browser.get("/workload/api/units").status_code == 200
    return seen


def test_with_signup_off_workload_is_told_the_email(app, tmp_path, monkeypatch):
    """Accounts made by the administrator: the email is theirs to link a team row by."""
    monkeypatch.setenv("ALLOW_SIGNUP", "false")
    told = _who_workload_is_told(app, tmp_path, monkeypatch)
    assert told["email"] == "admin@example.com"


def test_with_signup_on_workload_is_told_an_empty_email(app, tmp_path, monkeypatch):
    """Anybody could make an account under somebody else's address: pass none."""
    monkeypatch.setenv("ALLOW_SIGNUP", "true")
    told = _who_workload_is_told(app, tmp_path, monkeypatch)
    assert told["id"]
    # Present and empty, so Workload does not fall back to the login.
    assert told["email"] == ""


def test_an_ahm_admin_is_told_admin(app, tmp_path, monkeypatch):
    told = _who_workload_is_told(app, tmp_path, monkeypatch)
    assert told["admin"] is True


def test_anybody_else_is_told_not_admin(app, tmp_path, monkeypatch):
    """A plain AHM account is not an admin in Workload, whatever its browser sends."""
    told = _who_workload_is_told(app, tmp_path, monkeypatch, as_colleague=True)
    assert told["admin"] is False


def test_closing_the_response_reaches_workload(app, tmp_path, monkeypatch):
    """Workload tells phones from its response's close(); the door and the
    mount must hand that response through, not wrap it and drop close()."""
    import workload_app.wsgi as inner
    from werkzeug.test import EnvironBuilder

    monkeypatch.setenv("WORKLOAD_DATA_DIR", str(tmp_path / "workload"))
    monkeypatch.setattr(inner, "_app", None)
    mounted = DispatcherMiddleware(app, workload_door.mounts(app))
    browser = Client(mounted)
    sign_in(browser)
    told = []
    monkeypatch.setattr(inner.get_app(), "tell_pending",
                        lambda older_than=0.0: told.append(older_than))

    environ = EnvironBuilder(path="/workload/api/units", method="GET").get_environ()
    cookie = browser.get_cookie("session")
    assert cookie is not None
    environ["HTTP_COOKIE"] = f"session={cookie.value}"
    body = mounted(environ, lambda status, headers, exc_info=None: None)
    assert b"".join(body)
    told.clear()
    body.close()
    assert told == [0.0]


def test_bringing_in_a_first_upload_needs_a_sign_in(site):
    """The first-start routes are ordinary signed-in calls, never keyed."""
    for method, path in (("GET", "/workload/api/bring-in"),
                         ("POST", "/workload/api/bring-in/check"),
                         ("POST", "/workload/api/bring-in/apply"),
                         ("PUT", "/workload/api/bring-in/who"),
                         ("POST", "/workload/api/bring-in/who/keep")):
        answer = site.open(path, method=method, json=None if method == "GET" else {})
        assert answer.status_code == 401, (method, path)
        assert answer.json["error"] == "Sign in to use Selecao+."


def test_only_the_ahm_admin_changes_official_holidays(site, mounted):
    """Official holidays are one list for the whole site. Anybody signed in
    reads it; only the account AHM calls its admin may change it."""
    sign_in(site)
    theirs = colleague(site, mounted)
    read = theirs.get("/workload/api/official-holidays?country=EG&year=2026")
    assert read.status_code == 200, text(read)

    for path, body in (
            ("/workload/api/official-holidays",
             {"country": "EG", "date": "2026-12-24", "name": "Made-up day"}),
            ("/workload/api/official-holidays/EG/2026-12-24/undo", {})):
        refused = theirs.post(path, json=body)
        assert refused.status_code == 403, (path, text(refused))
        assert "administrator" in refused.json["error"]

    added = site.post("/workload/api/official-holidays",
                      json={"country": "EG", "date": "2026-12-24", "name": "Made-up day"})
    assert added.status_code == 200, text(added)
    undone = site.post("/workload/api/official-holidays/EG/2026-12-24/undo", json={})
    assert undone.status_code == 200, text(undone)
