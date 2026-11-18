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


# --- sharing ------------------------------------------------------------------------

def colleague(app, signed_in, username, programs=("tritomoor",)):
    make(signed_in, username=username, programs=programs)
    other = app.test_client()
    other.post("/login", data={"email": username, "password": "longenough1"})
    return other, other.get("/tritomoor/").status_code


def account_id(client):
    page = text(client.get("/tritomoor/"))
    return int(page.split("me:")[1].split("}")[0])


def test_sharing_to_edit_lets_a_colleague_work_on_it(app, signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    osama, _ = colleague(app, signed_in, "osama")
    osama_id = account_id(osama)
    people = signed_in.get("/tritomoor/api/people").get_json()["people"]
    assert osama_id in [p["id"] for p in people]
    shared = post(signed_in, f"/tritomoor/api/projects/{made['id']}/shares", {"user_id": osama_id, "access": "edit"})
    assert shared.status_code == 200 and shared.get_json()["shares"][0]["access"] == "edit"
    theirs = osama.get("/tritomoor/api/projects").get_json()["projects"]
    assert theirs[0]["id"] == made["id"] and theirs[0]["access"] == "edit" and theirs[0]["owner"]
    saved = osama.put(f"/tritomoor/api/projects/{made['id']}", json={"data": dict(PROJECT, lines=[1]), "base_version": 1})
    assert saved.status_code == 200
    assert signed_in.get(f"/tritomoor/api/projects/{made['id']}").get_json()["data"]["lines"] == [1]
    # but only the owner shares it on or deletes it
    assert post(osama, f"/tritomoor/api/projects/{made['id']}/shares", {"user_id": osama_id, "access": "edit"}).status_code == 403
    assert osama.delete(f"/tritomoor/api/projects/{made['id']}").status_code == 403


def test_view_only_opens_and_copies_but_does_not_save(app, signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    kirolos, _ = colleague(app, signed_in, "kirolos")
    kid = account_id(kirolos)
    post(signed_in, f"/tritomoor/api/projects/{made['id']}/shares", {"user_id": kid, "access": "view"})
    url = f"/tritomoor/api/projects/{made['id']}"
    assert kirolos.get(url).get_json()["access"] == "view"
    assert kirolos.put(url, json={"data": PROJECT, "base_version": 1}).status_code == 403
    assert kirolos.get(url + "/versions").status_code == 403
    copy = post(kirolos, url + "/duplicate", {}).get_json()
    assert copy["access"] == "owner"
    assert {p["id"] for p in kirolos.get("/tritomoor/api/projects").get_json()["projects"]} == {made["id"], copy["id"]}


def test_a_colleague_can_take_it_off_their_list_and_the_owner_can_stop_sharing(app, signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    sara, _ = colleague(app, signed_in, "sara")
    sid = account_id(sara)
    url = f"/tritomoor/api/projects/{made['id']}"
    post(signed_in, url + "/shares", {"user_id": sid, "access": "edit"})
    assert sara.delete(f"{url}/shares/{sid}").status_code == 200
    assert sara.get("/tritomoor/api/projects").get_json()["projects"] == []
    post(signed_in, url + "/shares", {"user_id": sid, "access": "edit"})
    assert signed_in.delete(f"{url}/shares/{sid}").get_json()["shares"] == []
    assert sara.get(url).status_code == 404


def test_it_cannot_be_shared_with_an_account_without_tritomoor(app, signed_in):
    made = post(signed_in, "/tritomoor/api/projects", {"data": PROJECT}).get_json()
    make(signed_in, username="nadia", programs=("pm",))
    nadia = app.test_client()
    nadia.post("/login", data={"email": "nadia", "password": "longenough1"})
    from app.db import connect
    with app.app_context():
        nid = connect(app.config["DATABASE"]).execute("SELECT id FROM users WHERE username = 'nadia'").fetchone()[0]
    assert nid not in [p["id"] for p in signed_in.get("/tritomoor/api/people").get_json()["people"]]
    refused = post(signed_in, f"/tritomoor/api/projects/{made['id']}/shares", {"user_id": nid, "access": "edit"})
    assert refused.status_code == 400 and "TritoMoor" in refused.get_json()["detail"]


def test_the_listing_describes_each_project_for_its_card(signed_in):
    fleet_project = dict(PROJECT, lines=[{}, {}], bollards=[{}] * 3, fenders=[{}] * 2,
                         report={"client": "Port authority", "projectNo": "P-101"},
                         fleet=[{"vessel": {"name": "Old tanker"}, "lines": [{}]}, {"vessel": {"name": "stale copy"}}],
                         fleetActive=1, vessel={"name": "Big tanker", "LOA": 250, "type": "tanker"},
                         analyses=[{"at": "2026-11-15T10:00:00Z", "vessel": "Big tanker", "kind": "design",
                                    "pass": False, "peak": 61.2, "allow": 50}, {"at": "earlier"}])
    post(signed_in, "/tritomoor/api/projects", {"data": fleet_project})
    card = signed_in.get("/tritomoor/api/projects").get_json()["projects"][0]
    assert [v["name"] for v in card["vessels"]] == ["Old tanker", "Big tanker"]
    assert [v["lines"] for v in card["vessels"]] == [1, 2] and card["vessels"][1]["loa"] == 250
    assert card["bollards"] == 3 and card["fenders"] == 2
    assert card["client"] == "Port authority" and card["number"] == "P-101"
    assert card["analyses"] == 2
    assert card["last_analysis"]["pass"] is False and card["last_analysis"]["peak"] == 61.2


def test_a_project_without_vessels_or_analyses_still_lists(signed_in):
    post(signed_in, "/tritomoor/api/projects", {"data": PROJECT})
    card = signed_in.get("/tritomoor/api/projects").get_json()["projects"][0]
    assert [v["name"] for v in card["vessels"]] == ["Example tanker"]
    assert card["analyses"] == 0 and card["last_analysis"] is None


def test_the_page_carries_scenarios_and_the_video_export(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    assert 'id="btnVideo"' in page and "Export video" in page
    assert "Scenarios &amp; video" in page or "Scenarios & video" in page
    assert "captureStream" in page and "MediaRecorder" in page
    assert "function lineReduction" in page and "function berthFrame" in page


def test_the_video_is_made_in_one_click_without_playing_it_through(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    assert ">Download video</button>" in page
    assert "function renderFile" in page and "new VideoEncoder" in page and "function mp4Of" in page


def test_the_video_shows_loading_water_level_and_directions(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    assert "function arrowList" in page and "S.arrows" in page
    assert "function section(x, s, sc2" in page and "Tfrom" in page


def test_the_page_draws_the_surroundings_waves_and_the_fender_squeeze(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    for part in ("function siteBlock", "function earclip", "uWave", "S.site",
                 "Hull to the berth face", "Fender squeezed", "m clear", "paintT"):
        assert part in page, part


def test_the_video_has_a_summary_mode_and_names_each_check(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    for part in ("mode: 'detailed'", "Summary: largest and smallest vessel", "function chip(x, s, X, Y)",
                 "function matrix(x, s)", "function calc(x, s, X, Y, W)", "function hullMin", "kind: 'gap'",
                 "uWaveA", "uCur", "lineRun", "clrRun"):
        assert part in page, part


def test_a_rendering_winch_brake_holds_its_load(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    assert "return L.brake + (T - L.brake) * 0.002;" in page


def test_the_video_shows_the_berth_and_the_mooring_before_the_cases(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    assert "kind: 'berthview'" in page and "kind: 'moor'" in page and "How she is moored" in page
    assert "She comes in from the sea" not in page
    assert "Governing line: " in page and "function moorList" in page


def test_the_video_holds_the_camera_in_a_load_case_and_shows_the_movement(signed_in):
    page = text(signed_in.get("/tritomoor/"))
    assert "cam0: CAM.caseView(I), cam1: CAM.caseView(I)" in page
    assert "Vessel movement in this case" in page and "S.ghostHouse" in page
    assert "the hull hits the berth" in page and "The hull is on the berth" in page

