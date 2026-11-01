"""TritoMoor, the eighth door: one self-contained page behind the one sign-in."""

from __future__ import annotations


def text(response) -> str:
    return response.get_data(as_text=True)


def make(signed_in, username="sara", programs=("pm",), password="longenough1"):
    return signed_in.post("/admin/users", data={
        "username": username, "password": password, "name": "Sara", "programs": list(programs)})


def test_the_door_is_on_the_front_page(signed_in):
    page = text(signed_in.get("/"))
    assert "TritoMoor" in page
    assert 'href="/tritomoor/"' in page
    assert 'class="door" href="/tritomoor/"' in page


def test_the_program_is_served_whole_with_a_way_back(signed_in):
    answer = signed_in.get("/tritomoor/")
    assert answer.status_code == 200
    page = text(answer)
    assert "<title>TritoMoor" in page
    assert "All applications" in page
    assert page.rstrip().endswith("</html>")


def test_the_bare_address_goes_to_the_page(signed_in):
    answer = signed_in.get("/tritomoor")
    assert answer.status_code in (301, 302, 308)
    assert answer.headers["Location"].endswith("/tritomoor/")


def test_a_stranger_is_sent_to_sign_in(client):
    answer = client.get("/tritomoor/")
    assert answer.status_code in (301, 302)
    assert "/login" in answer.headers["Location"]


def test_an_account_not_given_tritomoor_is_refused(app, signed_in):
    make(signed_in, programs=("pm",))
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert "/tritomoor/" not in text(sara.get("/"))
    assert sara.get("/tritomoor/").status_code in (302, 403)


def test_the_administrator_can_give_it(app, signed_in):
    assert 'value="tritomoor"' in text(signed_in.get("/admin/?tab=new"))


# --- projects kept on the site ------------------------------------------------------

PROJECT = {"name": "Tin Can berth", "vessel": {"name": "Example tanker"}, "berth": {"type": "alongside"},
           "environment": {}, "lines": []}


def post(client, path, body):
    return client.post(path, json=body)


def test_the_page_is_told_it_is_on_the_site(signed_in):
    assert "window.__TM_SITE" in text(signed_in.get("/tritomoor/"))


def test_a_project_is_saved_listed_opened_and_renamed(signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    assert made["name"] == "Tin Can berth" and made["version"] == 1 and made["vessel"] == "Example tanker"
    listed = signed_in.get("/tritomoor/api/projects").get_json()["projects"]
    assert [p["id"] for p in listed] == [made["id"]]
    changed = dict(PROJECT, berth={"type": "med"})
    saved = signed_in.put(f"/tritomoor/api/projects/{made['id']}",
                          json={"data": changed, "name": "Renamed", "base_version": 1}).get_json()
    assert saved["version"] == 2 and saved["name"] == "Renamed" and saved["berth"] == "med"
    opened = signed_in.get(f"/tritomoor/api/projects/{made['id']}").get_json()
    assert opened["data"]["berth"]["type"] == "med" and opened["data"]["name"] == "Renamed"


def test_a_save_from_a_stale_copy_is_refused_until_forced(signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    url = f"/tritomoor/api/projects/{made['id']}"
    assert signed_in.put(url, json={"data": dict(PROJECT, lines=[1]), "base_version": 1}).status_code == 200
    stale = signed_in.put(url, json={"data": dict(PROJECT, lines=[2]), "base_version": 1})
    assert stale.status_code == 409 and stale.get_json()["current"]["version"] == 2
    forced = signed_in.put(url, json={"data": dict(PROJECT, lines=[2]), "base_version": 1, "force": True})
    assert forced.status_code == 200 and forced.get_json()["version"] == 3
    # what the other computer saved is kept as an earlier version
    kept = signed_in.get(url + "/versions").get_json()["versions"]
    assert any(v["version"] == 2 for v in kept)


def test_an_earlier_version_can_be_brought_back(signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    url = f"/tritomoor/api/projects/{made['id']}"
    signed_in.put(url, json={"data": dict(PROJECT, lines=["new"]), "base_version": 1})
    first = signed_in.get(url + "/versions").get_json()["versions"][-1]
    assert first["version"] == 1
    back = post(signed_in, f"{url}/versions/{first['id']}/restore", {}).get_json()
    assert back["data"]["lines"] == [] and back["version"] == 3


def test_copy_and_delete(signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    copy = post(signed_in, f"/tritomoor/api/projects/{made['id']}/duplicate", {}).get_json()
    assert copy["name"] == "Tin Can berth (copy)"
    assert signed_in.delete(f"/tritomoor/api/projects/{made['id']}").status_code == 200
    assert [p["id"] for p in signed_in.get("/tritomoor/api/projects").get_json()["projects"]] == [copy["id"]]


def test_something_that_is_not_a_project_is_refused(signed_in):
    answer = post(signed_in, "/tritomoor/api/projects", {"data": {"hello": 1}})
    assert answer.status_code == 400


def test_a_project_belongs_to_its_account_alone(app, signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    make(signed_in, username="karim", programs=("tritomoor",))
    karim = app.test_client()
    karim.post("/login", data={"email": "karim", "password": "longenough1"})
    assert karim.get("/tritomoor/api/projects").get_json()["projects"] == []
    assert karim.get(f"/tritomoor/api/projects/{made['id']}").status_code == 404
    assert karim.put(f"/tritomoor/api/projects/{made['id']}", json={"data": PROJECT}).status_code == 404


def test_the_api_wants_a_sign_in_and_json(app, signed_in):
    assert app.test_client().get("/tritomoor/api/projects").status_code == 401
    assert signed_in.post("/tritomoor/api/projects", data={"data": "x"}).status_code == 415
