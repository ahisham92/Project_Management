"""MarineTwin: the door, the twin's arithmetic, and its link to Triton.

The arithmetic is what a client would act on, so it is pinned with readings
whose answer is known: a loss curve the fit has to recover, an element whose
corrosion is running past its allowance, and the utilisation that follows.
"""

from __future__ import annotations

import gzip
import io
import math
from datetime import date

import pytest

from app import marine, marine_life, marine_triton
from app.db import connect


def text(response) -> str:
    return response.get_data(as_text=True)


def make_user(signed_in, programs):
    signed_in.post("/admin/users", data={"username": "sara", "password": "longenough1",
                                         "name": "Sara", "programs": list(programs)})


@pytest.fixture()
def demo(app, signed_in):
    answer = signed_in.post("/marinetwin/demo")
    assert answer.status_code == 302
    return answer.headers["Location"]


# --- the door -----------------------------------------------------------------

def test_the_front_door_and_the_top_bar_offer_marinetwin(signed_in):
    page = text(signed_in.get("/"))
    assert "Open MarineTwin" in page
    assert 'href="/marinetwin/"' in page


def test_marinetwin_is_refused_to_an_account_without_it(app, signed_in):
    make_user(signed_in, ("pm",))
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert sara.get("/marinetwin/").status_code == 403
    assert "Open MarineTwin" not in text(sara.get("/"))


def test_a_stranger_is_sent_to_sign_in(client):
    answer = client.get("/marinetwin/")
    assert answer.status_code == 302 and "/login" in answer.headers["Location"]


# --- the demonstration --------------------------------------------------------

def test_the_demonstration_berth_is_a_working_twin(signed_in, demo):
    page = text(signed_in.get(demo))
    assert "Demo berth" in page and "The twin" in page
    twin = signed_in.get(demo + "/twin.json").get_json()
    assert len(twin["elements"]) == 19
    kinds = {e["kind"] for e in twin["elements"]}
    assert {"pile", "slab", "beam", "fender", "bollard", "crane_rail", "ladder"} <= kinds
    assert {e["state"] for e in twin["elements"]} <= {"good", "warning", "critical", "neutral"}
    first = twin["elements"][0]
    element = text(signed_in.get(first["href"]))
    assert first["name"] in element and "<svg" in element
    assert "Demo berth" in text(signed_in.get("/marinetwin/"))


def test_the_simulator_tells_the_same_story_twice(app, demo):
    with app.app_context():
        conn = connect(app.config["DATABASE"])
        before = conn.execute("SELECT sensor_id, at, value FROM marine_readings ORDER BY 1, 2").fetchall()
        marine.refresh_simulated(conn, 1)
        after = conn.execute("SELECT sensor_id, at, value FROM marine_readings ORDER BY 1, 2").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]
    assert len(before) > 1000


def test_readings_round_trip_and_real_ones_replace_the_simulation(app, signed_in, demo):
    exported = text(signed_in.get(demo + "/readings.csv"))
    assert exported.startswith("sensor,at,value,note\n")
    csv = "sensor,at,value\nP01-SG1,2026-01-05 10:00,512\nP01-SG1,2026-01-06,530\nNOPE,2026-01-06,1\n"
    answer = signed_in.post(demo + "/readings", data={"file": (io.BytesIO(csv.encode()), "log.csv")},
                            content_type="multipart/form-data", follow_redirects=True)
    page = text(answer)
    assert "2 readings imported for 1 sensors" in page
    assert "no sensor called" in page
    with app.app_context():
        conn = connect(app.config["DATABASE"])
        row = conn.execute("SELECT id, simulated FROM marine_sensors WHERE label = 'P01-SG1'").fetchone()
        count = conn.execute("SELECT COUNT(*) FROM marine_readings WHERE sensor_id = ?", (row["id"],)).fetchone()[0]
    assert row["simulated"] == 0 and count == 2


def _asset_id(demo: str) -> int:
    return int(demo.rstrip("/").rsplit("/", 1)[-1])


def test_the_real_sensors_page_prices_the_kit_and_gives_a_key(app, signed_in, demo):
    page = text(signed_in.get(demo + "/sensors"))
    assert "Start with one element" in page and "The whole asset" in page
    assert "Junction box, IP68 stainless" in page and "Data logger (Campbell CR6" in page
    assert "Installed and working" in page and "Each year to keep it running" in page
    assert "/marinetwin/api/assets/" in page
    with app.app_context():
        key = connect(app.config["DATABASE"]).execute(
            "SELECT feed_key FROM marine_assets WHERE id = ?", (_asset_id(demo),)).fetchone()[0]
    assert key.startswith("mt_") and key in page
    assert "Connect real sensors" in text(signed_in.get(demo + "/setup"))


def test_the_kit_counts_boxes_and_loggers_from_the_channels():
    from app import marine_feed

    k = marine_feed.kit({"strain": 33, "inspection": 4, "displacement": 2})
    items = {line["item"]: line for line in k["lines"]}
    assert k["channels"] == 33 and k["boxes"] == 3 and k["loggers"] == 1
    assert items["Multiplexer (Campbell AM16/32B)"]["qty"] == 3
    assert any(i.startswith("Robotic total station") for i in items)
    assert k["hardware_low"] == sum(line["total_low"] for line in k["lines"])
    assert marine_feed.kit({})["lines"] == []


def test_a_logger_sends_readings_with_the_key_and_they_count_as_real(app, client, signed_in, demo):
    asset_id = _asset_id(demo)
    signed_in.get(demo + "/sensors")
    with app.app_context():
        key = connect(app.config["DATABASE"]).execute(
            "SELECT feed_key FROM marine_assets WHERE id = ?", (asset_id,)).fetchone()[0]
    url = f"/marinetwin/api/assets/{asset_id}/readings"
    body = {"device": "cabinet-1", "readings": [{"sensor": "P01-SG1", "at": "2026-10-04T10:00", "value": 400},
                                                 {"sensor": "P01-SG1", "at": "2026-10-04 11:00", "value": 410},
                                                 {"sensor": "NOPE", "at": "2026-10-04T11:00", "value": 1}]}
    assert client.post(url, json=body).status_code == 403
    assert client.post(url, json=body, headers={"Authorization": "Bearer wrong"}).status_code == 403
    answer = client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    assert answer.status_code == 200
    assert answer.get_json()["written"] == 2 and "NOPE" in answer.get_json()["problems"][0]
    csv = "sensor,at,value\nP01-SG1,2026-10-04T12:00,420\n"
    answer = client.post(f"{url}?key={key}&device=cabinet-1", data=csv, content_type="text/csv")
    assert answer.status_code == 200 and answer.get_json()["written"] == 1
    assert client.post(url, json={"readings": "x"}, headers={"X-MarineTwin-Key": key}).status_code == 422
    with app.app_context():
        conn = connect(app.config["DATABASE"])
        sensor = conn.execute("SELECT id, simulated, feed_device FROM marine_sensors WHERE label = 'P01-SG1'").fetchone()
        values = [r[0] for r in conn.execute("SELECT value FROM marine_readings WHERE sensor_id = ? ORDER BY at",
                                             (sensor["id"],))]
    assert sensor["simulated"] == 0 and sensor["feed_device"] == "cabinet-1" and values == [400, 410, 420]
    feed = signed_in.get(demo + "/feed.json").get_json()
    assert [s["label"] for s in feed["fed"]] == ["P01-SG1"] and feed["fed"][0]["latest"] == 420
    assert len(feed["deliveries"]) == 3 and feed["deliveries"][-1]["problems"] == 1
    # A new key shuts the old one out.
    signed_in.post(demo + "/feed/key")
    assert client.post(url, json=body, headers={"Authorization": f"Bearer {key}"}).status_code == 403


def test_the_fake_logger_is_a_runnable_script_and_its_sensors_can_go_back(app, client, signed_in, demo):
    import json as jsonlib

    script = text(signed_in.get(demo + "/fake_logger.py"))
    code = compile(script, "fake_logger.py", "exec")
    space: dict = {"__name__": "fake"}
    exec(code, space)
    config = space["CONFIG"]
    assert config["url"].endswith(f"/marinetwin/api/assets/{_asset_id(demo)}/readings")
    assert config["channels"] and config["device"] == "fake-logger"
    kinds = [c["kind"] for c in config["channels"]]
    assert len(kinds) == len(set(kinds))
    # Send what the script would, through the real door.
    readings = [{"sensor": c["sensor"], "at": "2026-10-04T09:00", "value": c["start"]} for c in config["channels"]]
    answer = client.post(config["url"].split("localhost", 1)[-1], data=jsonlib.dumps(
        {"device": config["device"], "readings": readings}), content_type="application/json",
        headers={"Authorization": "Bearer " + config["key"]})
    assert answer.get_json()["written"] == len(readings)
    assert "Put the fake logger" in text(signed_in.get(demo + "/sensors"))
    labels = [c["sensor"] for c in config["channels"]]
    signed_in.post(demo + "/feed/reset")
    with app.app_context():
        conn = connect(app.config["DATABASE"])
        back = conn.execute("SELECT simulated, feed_device FROM marine_sensors WHERE label IN (%s)"
                            % ",".join("?" * len(labels)), labels).fetchall()
    assert [tuple(r) for r in back] == [(1, "")] * len(labels)


def test_a_model_is_ifc_or_gltf_and_is_served_back(signed_in, demo):
    bad = signed_in.post(demo + "/model", data={"model": (io.BytesIO(b"x"), "model.rvt")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "exported as IFC" in text(bad)
    signed_in.post(demo + "/model", data={"model": (io.BytesIO(b"glTF-bytes"), "berth.glb")},
                   content_type="multipart/form-data")
    twin = signed_in.get(demo + "/twin.json").get_json()
    assert twin["model_kind"] == "glb"
    assert signed_in.get(twin["model"]).data == b"glTF-bytes"
    signed_in.post(demo + "/model/delete")
    assert signed_in.get(demo + "/twin.json").get_json()["model"] is None


def test_an_element_and_its_sensors_can_be_added_and_removed(app, signed_in, demo):
    signed_in.post(demo + "/elements", data={"name": "B1", "kind": "beam", "material": "concrete",
                                             "zone": "atmospheric", "sensors": ["strain", "tilt"]})
    twin = signed_in.get(demo + "/twin.json").get_json()
    beam = next(e for e in twin["elements"] if e["name"] == "B1")
    assert [s["label"] for s in beam["sensors"]] == ["B1-SG1", "B1-T1"]
    element_id = beam["id"]
    signed_in.post(f"{demo}/elements/{element_id}/delete")
    assert all(e["name"] != "B1" for e in signed_in.get(demo + "/twin.json").get_json()["elements"])


# --- the arithmetic -----------------------------------------------------------

def test_the_fit_recovers_a_known_loss_curve():
    points = [(t, 0.2 * t ** 0.8) for t in (1, 2, 3, 4, 6, 8)]
    a, b = marine.fit_corrosion(points)
    assert a == pytest.approx(0.2, rel=1e-6) and b == pytest.approx(0.8, rel=1e-6)


def test_a_wild_exponent_is_clamped():
    a, b = marine.fit_corrosion([(1, 0.01), (2, 0.5), (3, 3.0)])
    assert b == 1.2


def _asset(**over):
    row = {"id": 1, "kind": "quay_wall", "commissioned": "2016-01-01", "design_life": 50,
           "corrosion_code": "bs6349", "triton_project": "", "triton_section": ""}
    row.update(over)
    return row


def _element(**over):
    row = {"id": 1, "name": "P01", "kind": "pile", "material": "steel", "zone": "splash",
           "wall_mm": 16.0, "design_ur": 0.8, "triton_element": ""}
    row.update(over)
    return row


def test_corrosion_running_past_its_allowance_is_acted_on():
    # 0.15 mm a year, linear: 7.5 mm by year 50 against a 4.5 mm allowance.
    readings = [{"at": f"{2016 + y}-01-01", "value": 0.15 * y} for y in range(1, 11)]
    sensor = {"id": 1, "kind": "corrosion", "label": "P01-UT1", "alert": None, "alarm": None, "simulated": 1}
    s = marine.assess_sensor(sensor, readings, _element(), _asset(), 4.5, 50, date(2026, 1, 2))
    assert s["state"] == "critical"
    assert s["projected_at_life"] == pytest.approx(7.5, rel=0.01)
    assert s["exhausted_year"] == pytest.approx(2046, abs=0.1)

    condition = marine.assess_element(_element(), [s], _asset(), 4.5, 50, None)
    # Triton designed 16 mm with 4.5 mm gone (11.5 mm left); the projection leaves 8.5 mm.
    assert condition["ur_at_life"] == pytest.approx(0.8 * 11.5 / 8.5, abs=0.01)
    assert condition["state"] == "critical"
    advice = marine.recommendations(_element(), condition, [s], _asset())
    assert any("Re-run P01 in Triton" in a["text"] for a in advice)
    assert any("ultrasonic thickness survey" in a["text"] for a in advice)


def test_strain_is_judged_against_its_limits_and_a_silent_sensor_is_said_to_be():
    sensor = {"id": 2, "kind": "strain", "label": "P01-SG1", "alert": 850.0, "alarm": 1250.0, "simulated": 1}
    readings = [{"at": "2026-01-01", "value": 400.0}, {"at": "2026-01-08", "value": 1300.0}]
    s = marine.assess_sensor(sensor, readings, _element(), _asset(), None, 50, date(2026, 1, 9))
    assert s["state"] == "critical" and s["score"] < 50
    quiet = marine.assess_sensor(sensor, readings[:1], _element(), _asset(), None, 50, date(2026, 6, 1))
    assert quiet["silent"]
    advice = marine.recommendations(_element(), {"ur_at_life": None}, [quiet], _asset())
    assert "has sent nothing since" in advice[0]["text"]


def test_concrete_carries_no_steel_allowance():
    assert marine_triton.allowance_for(_element(material="concrete"), {"casing": 4.5}) is None
    allowances = {"casing": 4.5, "combi_tube": 4.4, "sheet_pile_per_face": 2.5}
    assert marine_triton.allowance_for(_element(kind="combi_wall"), allowances) == 4.4
    assert marine_triton.allowance_for(_element(kind="beam", zone="immersed"), allowances) == 2.5


# --- the link to Triton -------------------------------------------------------

def test_a_linked_asset_takes_its_design_from_triton(app, signed_in, demo, tmp_path, monkeypatch):
    pytest.importorskip("triton.store")
    from triton.project import Project
    from triton.store import ProjectStore

    monkeypatch.setenv("TRITON_DATA_DIR", str(tmp_path / "triton"))
    store = ProjectStore(tmp_path / "triton")
    project = Project()
    project.info.name = "Berth 1"
    project.design.design_life_years = 60
    project.design.durability.corrosion.casing = 6.0
    store.save(project)
    section = project.sections[0]
    store.save_results(project.id, section.id, {
        "piles": [{"element": "P01", "kind": "pile", "utilisation": 0.93, "passed": True},
                  {"element": "P01", "kind": "pile", "utilisation": 0.5, "passed": True}],
        "summary": {"not": "a list"},
    })

    assert marine_triton.design_utilisation(project.id, section.id)["P01"]["ur"] == 0.93
    assert any(p["name"] == "Berth 1" for p in marine_triton.projects())
    assert "Berth 1" in text(signed_in.get(demo + "/setup"))

    signed_in.post(demo + "/settings", data={"name": "Demo berth — Quay 1", "kind": "quay_wall",
                                             "commissioned": "2018-03-01", "design_life": "50",
                                             "corrosion_code": "bs6349",
                                             "triton": f"{project.id}:{section.id}"})
    twin = signed_in.get(demo + "/twin.json").get_json()
    p01 = next(e for e in twin["elements"] if e["name"] == "P01")
    assert p01["design_ur"] == 0.93
    page = text(signed_in.get(p01["href"]))
    assert "from Triton" in page and "6.00 mm" in page and "over 60 years" in page


def test_without_triton_the_allowances_fall_back_to_bs6349(monkeypatch):
    import builtins

    real = builtins.__import__

    def refuse(name, *args, **kwargs):
        if name.startswith("triton"):
            raise ModuleNotFoundError(name)
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse)
    found = marine_triton.durability(_asset())
    assert found["allowances"]["casing"] == 4.5 and "not installed" in found["source"]
    assert marine_triton.projects() == [] and not marine_triton.available()
    assert math.isclose(found["allowances"]["sheet_pile_per_face"], 2.5)
    rated = marine_triton.ratings(_asset())
    assert rated["fender"] == 2012.0 and "not installed" in rated["source"]


# --- concrete, furniture and inspections --------------------------------------

def _sensor(kind, **over):
    row = {"id": 9, "kind": kind, "label": f"X-{kind}", "alert": None, "alarm": None, "simulated": 1}
    row.update(over)
    return row


RATINGS = {"fender": 2000.0, "bollard": 150.0, "source": "Triton project “Berth 1”"}


def test_a_fender_is_judged_against_its_rated_reaction_from_triton():
    readings = [{"at": "2026-01-01", "value": 600.0}, {"at": "2026-01-08", "value": 2100.0},
                {"at": "2026-01-15", "value": 500.0}]
    s = marine.assess_sensor(_sensor("fender_reaction"), readings, _element(kind="fender", material="rubber"),
                             _asset(), None, 50, date(2026, 1, 16), RATINGS)
    assert (s["alert"], s["alarm"]) == (1600.0, 2000.0)
    assert s["state"] == "critical" and "105% of its 2,000 kN rating" in s["headline"]
    advice = marine.recommendations(_element(name="F2", kind="fender"), {}, [s], _asset())
    assert "rated reaction of 2,000 kN (Triton project “Berth 1”)" in advice[0]["text"]
    # A limit set on the sensor itself wins over the rating.
    own = marine.assess_sensor(_sensor("fender_reaction", alert=2500.0, alarm=3000.0), readings,
                               _element(kind="fender"), _asset(), None, 50, date(2026, 1, 16), RATINGS)
    assert own["state"] == "good"


def test_a_bollard_near_its_capacity_is_watched():
    readings = [{"at": "2026-01-01", "value": 40.0}, {"at": "2026-01-08", "value": 130.0}]
    s = marine.assess_sensor(_sensor("bollard_load"), readings, _element(kind="bollard"), _asset(), None, 50,
                             date(2026, 1, 9), RATINGS)
    assert s["state"] == "warning" and s["alarm"] == 150.0


def test_half_cell_potentials_are_worse_the_more_negative_they_are():
    def judged(value):
        readings = [{"at": "2026-01-01", "value": -100.0}, {"at": "2026-04-01", "value": value}]
        return marine.assess_sensor(_sensor("half_cell"), readings, _element(material="concrete"), _asset(),
                                    None, 50, date(2026, 4, 2))["state"]
    assert judged(-150.0) == "good"
    assert judged(-250.0) == "warning"
    assert judged(-400.0) == "critical"


def test_chloride_heading_for_its_threshold_within_the_design_life_is_watched():
    # 0.05 % a year from 2016: 0.25 % now, 0.4 % three years on.
    readings = [{"at": f"{2016 + y}-06-01", "value": 0.05 * y} for y in range(1, 6)]
    s = marine.assess_sensor(_sensor("chloride"), readings, _element(kind="beam", material="concrete"), _asset(),
                             None, 50, date(2021, 6, 2))
    assert s["limit_year"] == pytest.approx(2024.4, abs=0.2)
    assert s["state"] == "warning" and "reaches 0.40 % cement around 2024" in s["headline"]
    advice = marine.recommendations(_element(name="COPE", kind="beam", material="concrete"), {}, [s], _asset())
    assert "silane" in advice[0]["text"]


def test_a_crane_rail_off_its_line_either_way_is_reported():
    for value in (11.0, -11.0):
        readings = [{"at": "2026-01-01", "value": 0.0}, {"at": "2026-02-01", "value": value}]
        s = marine.assess_sensor(_sensor("rail_gauge"), readings, _element(kind="crane_rail"), _asset(), None, 50,
                                 date(2026, 2, 2))
        assert s["state"] == "critical"


def test_an_inspection_reports_damage_nobody_instrumented(app, signed_in, demo):
    twin = signed_in.get(demo + "/twin.json").get_json()
    f3 = next(e for e in twin["elements"] if e["name"] == "F3")
    answer = signed_in.post(f"{demo}/elements/{f3['id']}/inspection",
                            data={"at": date.today().isoformat(), "grade": "5", "note": "Panel hanging off one chain"},
                            follow_redirects=True)
    page = text(answer)
    assert "grade 5, failed / unsafe" in page and "Panel hanging off one chain" in page
    twin = signed_in.get(demo + "/twin.json").get_json()
    f3 = next(e for e in twin["elements"] if e["name"] == "F3")
    assert f3["state"] == "critical"
    asset_page = text(signed_in.get(demo))
    assert "The last inspection graded F3 5 of 5" in asset_page and "replace the torn rubber" in asset_page
    # A later, better inspection supersedes it: the latest grade is the condition.
    signed_in.post(f"{demo}/elements/{f3['id']}/inspection", data={"at": date.today().isoformat(), "grade": "1"})
    twin = signed_in.get(demo + "/twin.json").get_json()
    assert next(e for e in twin["elements"] if e["name"] == "F3")["state"] != "critical"


def test_a_new_element_takes_the_usual_sensors_for_its_type(signed_in, demo):
    signed_in.post(demo + "/elements", data={"name": "F9", "kind": "fender", "material": "rubber",
                                             "zone": "splash", "suggested": "1"})
    signed_in.post(demo + "/elements", data={"name": "BEAM9", "kind": "beam", "material": "concrete",
                                             "zone": "splash", "suggested": "1"})
    twin = signed_in.get(demo + "/twin.json").get_json()
    labels = {e["name"]: [s["label"] for s in e["sensors"]] for e in twin["elements"]}
    assert labels["F9"] == ["F9-FR1", "F9-IN1"]
    assert labels["BEAM9"] == ["BEAM9-CL1", "BEAM9-CR1", "BEAM9-HC1"]


def test_triton_furniture_ratings_come_from_a_linked_project(tmp_path, monkeypatch):
    pytest.importorskip("triton.store")
    from triton.project import Project
    from triton.store import ProjectStore

    monkeypatch.setenv("TRITON_DATA_DIR", str(tmp_path / "triton"))
    project = Project()
    project.furniture.fenders.reaction = 1500.0
    project.furniture.bollards.capacity = 100.0
    ProjectStore(tmp_path / "triton").save(project)
    found = marine_triton.ratings(_asset(triton_project=project.id))
    assert (found["fender"], found["bollard"]) == (1500.0, 100.0)
    assert marine_triton.ratings(_asset())["bollard"] == 150.0


def test_a_fender_overloaded_months_ago_is_still_reported():
    readings = [{"at": "2025-01-06", "value": 2100.0}] + [
        {"at": f"2025-{m:02d}-01", "value": 500.0} for m in range(2, 13)] + [
        {"at": f"2026-01-{d:02d}", "value": 450.0} for d in (5, 12, 19, 26)]
    s = marine.assess_sensor(_sensor("fender_reaction"), readings, _element(kind="fender"), _asset(), None, 50,
                             date(2026, 1, 27), RATINGS)
    assert s["state"] == "warning" and s["exceedances"] == 1 and s["last_exceeded"] == "2025-01-06"
    advice = marine.recommendations(_element(name="F1", kind="fender"), {}, [s], _asset())
    assert "has gone over its rated reaction 1 time, last on 2025-01-06" in advice[0]["text"]


# --- operations ---------------------------------------------------------------

from datetime import datetime, timedelta  # noqa: E402

from app import marine_ops  # noqa: E402

NOW = datetime(2026, 10, 3, 9, 30)


def test_berthing_energy_follows_bs6349_4():
    # Cm = 1 + 2·14/40 = 1.7; E = ½ · 100 000 t · 0.15² · 1.7 · 0.5 · 1.0 · 0.9 = 861 kNm.
    e = marine_ops.berthing_energy(100000, 40, 14, 0.15, solid=True)
    assert e["cm"] == 1.7 and e["normal"] == 861 and e["abnormal"] == 1291
    assert marine_ops.berthing_energy(100000, 40, 14, 0.15, solid=False)["normal"] == 956


def test_wind_on_a_moored_ship():
    # ½ · 1.225 · 1.2 · (300 m × 30 m) · 20² / 9.81 = 270 t.
    assert marine_ops.wind_on_ship(300, 30, 20) == pytest.approx(269.7, abs=0.1)
    assert marine_ops.approach_speed(5) < marine_ops.approach_speed(12) < marine_ops.approach_speed(18)


def test_the_simulated_feeds_tell_the_same_story_all_day():
    assert marine_ops.metocean(7, NOW) == marine_ops.metocean(7, NOW)
    assert marine_ops.lineup(7, NOW) == marine_ops.lineup(7, NOW)
    assert marine_ops.metocean(7, NOW) != marine_ops.metocean(8, NOW)
    hours = marine_ops.metocean(7, NOW)
    assert len(hours) == 24 + 72 + 1 and sum(1 for h in hours if not h["past"]) == 72


def _weather(wind):
    start = NOW.replace(minute=0) - timedelta(hours=24)
    return [{"at": start + timedelta(hours=i), "wind": wind(i - 24), "gust": wind(i - 24) * 1.3,
             "hs": 0.3 + 0.05 * wind(i - 24), "tide": 1.0, "current": 0.2, "past": i <= 24} for i in range(97)]


def _ship(hours, **over):
    ship = {"name": "Test Ship", "type": "Container", "loa": 300, "beam": 48.2, "draught": 14.0,
            "displacement": 140000, "windage": 32, "eta": NOW + timedelta(hours=hours),
            "etd": NOW + timedelta(hours=hours + 20), "moves": 1500}
    ship.update(over)
    return ship


def _twin(fender_state="good"):
    def el(name, kind, state):
        return {"element": {"name": name, "kind": kind}, "state": state, "sensors": []}
    return {"elements": [el("F1", "fender", "good"), el("F2", "fender", fender_state),
                         el("BOL1", "bollard", "good"), el("BOL2", "bollard", "good")],
            "advice": [], "health": 80, "state": "good", "counts": {"critical": 0, "warning": 0}}


def _operations(monkeypatch, wind, ships, fender_state="good"):
    monkeypatch.setattr(marine_ops, "metocean", lambda *a, **k: _weather(wind))
    monkeypatch.setattr(marine_ops, "lineup", lambda *a, **k: ships)
    return marine_ops.operations(None, _asset(), NOW, _twin(fender_state))


def test_a_calm_day_needs_nothing(monkeypatch):
    ops = _operations(monkeypatch, lambda h: 6.0, [_ship(10, displacement=60000, loa=200, windage=20)])
    assert ops["status"] == "Normal"
    assert [a for a in ops["actions"] if a["area"] in ("Vessels", "Mooring")] == []
    assert ops["calls"][0]["state"] == "good"


def test_a_ship_due_on_a_damaged_fender_is_moved_along_the_berth(monkeypatch):
    ops = _operations(monkeypatch, lambda h: 6.0, [_ship(10, displacement=60000)], fender_state="critical")
    vessel = [a for a in ops["actions"] if a["area"] == "Vessels"]
    assert vessel and "F2" in vessel[0]["text"] and "clears F2" in vessel[0]["text"]
    assert "damaged fender" in ops["calls"][0]["flags"]


def test_a_gale_stows_the_cranes_holds_the_ship_and_doubles_the_lines(monkeypatch):
    gale = lambda h: 26.0 if 20 <= h <= 30 else 6.0   # noqa: E731
    ops = _operations(monkeypatch, gale, [_ship(24)])
    areas = [a["area"] for a in ops["actions"]]
    assert "Cranes" in areas and "Vessels" in areas and "Mooring" in areas
    assert any("storm pins" in a["text"] for a in ops["actions"])
    assert any("Hold her at anchor" in a["text"] for a in ops["actions"])
    assert ops["actions"][0]["state"] == "critical"
    assert ops["status"] == "Normal" and ops["windows"]["stow"] is not None


def test_a_big_ship_over_the_fender_rating_is_flagged(monkeypatch):
    ops = _operations(monkeypatch, lambda h: 12.0, [_ship(10, displacement=400000)])
    assert "berthing energy" in ops["calls"][0]["flags"]
    assert ops["calls"][0]["energy"]["abnormal"] > ops["ratings"]["fender_energy"]


def test_the_operations_page_answers_now_next_and_what_to_do(signed_in, demo):
    page = text(signed_in.get(demo + "/operations"))
    for heading in ('data-tab="Now"', 'data-tab="Next 72 hours"', 'data-tab="What to do"',
                    "Wind, next 72 hours", "Ships", "Cranes", "simulated"):
        assert heading in page
    assert "<svg" in page and 'href="' + demo + '/operations"' in text(signed_in.get(demo))


# --- simulation and the modules beyond the structure ------------------------------------

from app import marine_facility, marine_sim  # noqa: E402


def test_the_simulation_is_repeatable_and_every_scenario_sees_the_same_ships():
    a = marine_sim.run(3, marine_sim.DEFAULTS, detail=False)
    assert a == marine_sim.run(3, marine_sim.DEFAULTS, detail=False)
    more_cranes = marine_sim.run(3, {**marine_sim.DEFAULTS, "sts": 9}, detail=False)
    assert [(c["at"], c["moves"]) for c in a["calls"]] == [(c["at"], c["moves"]) for c in more_cranes["calls"]]


def test_scenario_numbers_are_kept_in_range():
    p = marine_sim.clean({"berths": "-3", "sts": "2", "max_sts_per_ship": "6", "trucks": "nan", "gate_open": "20", "gate_close": "4"})
    assert p["berths"] == 1 and p["max_sts_per_ship"] == 2 and p["trucks"] == marine_sim.DEFAULTS["trucks"]
    assert p["gate_close"] > p["gate_open"]


def test_too_few_tractors_is_found_as_the_bottleneck_and_more_of_them_helps():
    starved = {**marine_sim.DEFAULTS, "trucks": 8, "rtgs": 20, "gate_lanes": 12}
    r = marine_sim.assess(1, starved, detail=False)
    assert r["bottleneck"] == "trucks"
    assert r["helps"][0]["key"] == "trucks" and r["helps"][0]["saves"] > 0
    fixed = marine_sim.run(1, {**starved, "trucks": 40}, detail=False)
    assert fixed["kpis"]["turnaround"] < r["kpis"]["turnaround"]


def test_one_berth_for_many_ships_makes_the_berth_the_bottleneck():
    busy = {**marine_sim.DEFAULTS, "berths": 1, "sts": 6, "trucks": 60, "rtgs": 30, "gate_lanes": 20, "ships_per_week": 6}
    r = marine_sim.assess(1, busy, detail=False)
    assert r["bottleneck"] == "berth" and r["kpis"]["mean_wait"] > 10


def test_a_narrow_gate_queues_road_trucks():
    r = marine_sim.assess(1, {**marine_sim.DEFAULTS, "trucks": 40, "rtgs": 16, "gate_lanes": 1}, detail=False)
    assert r["bottleneck"] == "gate" and r["kpis"]["gate_backlog"] > 1000


def test_scenarios_are_kept_compared_and_deleted(signed_in, demo):
    page = text(signed_in.get(demo + "/simulation"))
    assert "Baseline" in page and "Compare scenarios" in page and "<svg" in page
    answer = signed_in.post(demo + "/simulation", data={**{k: v for k, v in marine_sim.DEFAULTS.items()},
                                                        "name": "More tractors", "trucks": "30"})
    assert answer.status_code == 302
    page = text(signed_in.get(answer.headers["Location"]))
    assert "More tractors" in page and "Terminal tractors 18 → 30" in page
    sid = answer.headers["Location"].split("show=")[1]
    signed_in.post(f"{demo}/simulation/{sid}/delete")
    assert "More tractors" not in text(signed_in.get(demo + "/simulation"))


def test_the_baseline_cannot_be_deleted(signed_in, demo):
    page = text(signed_in.get(demo + "/simulation"))
    baseline = page.split("show=")[1].split("&")[0].split('"')[0]
    answer = signed_in.post(f"{demo}/simulation/{baseline}/delete", follow_redirects=True)
    assert "The baseline stays" in text(answer) and "Baseline" in text(answer)


def test_maintenance_reports_overdue_service_and_bad_vibration():
    m = marine_facility.maintenance(_asset(), date(2026, 10, 3))
    assert len(m["units"]) == sum(f[1] for f in marine_facility.FLEET)
    for unit in m["units"]:
        if unit["to_next"] < 0 and unit["prefix"] != "TT":
            assert any(unit["tag"] in a["text"] for a in m["actions"])
        if unit["vibration"] is not None and unit["vibration"] >= marine_facility.VIBRATION_LIMITS[0]:
            assert any(f"{unit['tag']} hoist gearbox vibration" in a["text"] for a in m["actions"])


def test_air_quality_is_judged_on_its_daily_mean_against_who():
    env = marine_facility.environment(_asset(), datetime(2026, 10, 3, 15))
    for s in env["stations"]:
        for r in s["measures"]:
            judged = r["mean"] if r["key"] in marine_facility.DAILY_MEAN else r["latest"]
            expect = "critical" if judged >= r["alarm"] else "warning" if judged >= r["alert"] else "good"
            assert r["state"] == expect


def test_carbon_adds_up_by_scope():
    c = marine_facility.carbon(_asset(), date(2026, 10, 3))
    assert len(c["months"]) == 12
    m = c["months"][0]
    assert m["scope1"] == pytest.approx(m["diesel"] * marine_facility.DIESEL / 1000, abs=0.1)
    assert m["scope2"] == pytest.approx(m["electricity"] * marine_facility.GRID / 1000, abs=0.1)
    assert c["total"] == pytest.approx(c["scope1"] + c["scope2"], abs=2)


def test_an_overdue_lifting_examination_stops_the_crane():
    c = marine_facility.compliance(_asset(), date(2026, 10, 3))
    for item in c["items"]:
        assert item["state"] == ("critical" if item["days"] < 0 else "warning" if item["days"] <= 30 else "good")
    late = [a for a in c["actions"] if "LOLER" in a["text"] and a["state"] == "critical"]
    assert all("must not lift" in a["text"] for a in late)


def test_every_new_tab_opens(signed_in, demo):
    for path, words in (("/equipment", "Asset register"), ("/environment", "CO₂ indoors"),
                        ("/carbon", "Month by month"), ("/safety", "Incidents, last 90 days")):
        page = text(signed_in.get(demo + path))
        assert words in page and "Safety &amp; security" in page


# --- where it is: the Revit model's site, the map, and the terminal type -------------------

from pathlib import Path  # noqa: E402

from app import marine_ifc, marine_sim  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "marinetwin_berth.ifc"


def test_the_ifc_gives_the_site_its_datum_and_the_elements():
    found = marine_ifc.read_file(FIXTURE)
    site = found["site"]
    assert (site["latitude"], site["longitude"], site["source"]) == (pytest.approx(6.43872, abs=1e-5), pytest.approx(3.38945, abs=1e-5), "IfcSite")
    assert site["rotation"] == pytest.approx(20.0, abs=0.01) and site["epsg"] == "EPSG:32631"
    assert found["msl_cd"] == pytest.approx(0.9) and found["terminal_type"] == "roro"
    names = [e["name"] for e in found["elements"]]
    assert len(names) == 16 and not any("Lamp" in n for n in names)
    by = {e["name"]: e for e in found["elements"]}
    assert by["RR1"]["kind"] == "ramp"
    assert by["F1"]["rated_reaction"] == pytest.approx(1650) and by["BOL1"]["bollard_capacity"] == pytest.approx(100)
    assert by["P01"]["global_id"] and by["DK1"]["kind"] == "slab"


def test_without_a_site_latitude_the_map_conversion_is_used():
    text = FIXTURE.read_text().replace("(6,26,19,392000),(3,23,22,20000)", "$,$")
    site = marine_ifc.read(text)["site"]
    assert site["source"] != "IfcSite"
    assert (site["latitude"], site["longitude"]) == (pytest.approx(6.43856, abs=1e-4), pytest.approx(3.38118, abs=1e-4))


def test_utm_comes_back_as_latitude_and_longitude():
    lat, lon = marine_ifc.utm_to_latlon(542150, 711700, 31)
    assert (lat, lon) == (pytest.approx(6.43856, abs=1e-5), pytest.approx(3.38118, abs=1e-5))
    lat, lon = marine_ifc.utm_to_latlon(500000, 0, 31)
    assert (lat, lon) == (pytest.approx(0, abs=1e-6), pytest.approx(3, abs=1e-6))


def test_a_model_position_is_turned_onto_the_map():
    asset = {"latitude": 6.0, "longitude": 3.0, "rotation": 90.0}
    lat, lon = marine.geolocate(asset, 100.0, 0.0)          # x turned 90° points north
    assert lat == pytest.approx(6.0 + 100 / 111_320, abs=1e-7) and lon == pytest.approx(3.0, abs=1e-7)
    assert marine.geolocate({"latitude": None, "longitude": None, "rotation": 0}, 1, 1) is None


def test_uploading_the_model_sets_the_site_and_imports_its_elements(app, signed_in):
    signed_in.post("/marinetwin/assets", data={"name": "Berth 4", "kind": "quay_wall", "commissioned": "2024-01-01",
                                                   "design_life": "50", "corrosion_code": "bs6349"})
    with app.app_context():
        asset_id = connect(app.config["DATABASE"]).execute("SELECT id FROM marine_assets WHERE name = 'Berth 4'").fetchone()["id"]
    page = f"/marinetwin/assets/{asset_id}"
    answer = signed_in.post(page + "/model", data={"model": (io.BytesIO(FIXTURE.read_bytes()), "berth.ifc")},
                            content_type="multipart/form-data", follow_redirects=True)
    assert "16 elements" in text(answer) and "Import the ticked kinds" in text(answer)
    twin = signed_in.get(page + "/twin.json").get_json()
    assert twin["asset"]["terminal"] == "roro" and twin["asset"]["latitude"] == pytest.approx(6.43872)
    assert twin["asset"]["rotation"] == pytest.approx(20.0) and twin["asset"]["msl_cd"] == pytest.approx(0.9)
    signed_in.post(page + "/model/import", data={"names": ["P01", "F1", "RR1"]})
    twin = signed_in.get(page + "/twin.json").get_json()
    by = {e["name"]: e for e in twin["elements"]}
    assert set(by) == {"P01", "F1", "RR1"} and by["RR1"]["kind"] == "ramp"
    gid = {e["name"]: e["global_id"] for e in marine_ifc.read_file(FIXTURE)["elements"]}
    assert by["P01"]["ref"] == gid["P01"]
    signed_in.post(page + "/model/import")                   # the rest, and nothing twice
    assert len(signed_in.get(page + "/twin.json").get_json()["elements"]) == 16
    shown = text(signed_in.get(page + "/setup"))
    assert "Where it is" in shown and '"elements"' in shown and "RoRo (vehicles)" in shown
    assert "Berth 4" in text(signed_in.get("/marinetwin/"))


def _berth(app, signed_in, name):
    signed_in.post("/marinetwin/assets", data={"name": name, "kind": "quay_wall", "commissioned": "2024-01-01",
                                               "design_life": "50", "corrosion_code": "bs6349"})
    with app.app_context():
        asset_id = connect(app.config["DATABASE"]).execute("SELECT id FROM marine_assets WHERE name = ?", (name,)).fetchone()["id"]
    return f"/marinetwin/assets/{asset_id}"


def test_piles_sharing_a_name_each_become_an_element(app, signed_in):
    # Revit names every pile of a design section the same (MP1-DS03): they are numbered along the berth.
    shared = FIXTURE.read_text().replace(",'P01',", ",'P1',").replace(",'P02',", ",'P1',")
    found = marine_ifc.read(shared)
    names = sorted(e["name"] for e in found["elements"] if e.get("group") == "P1")
    assert names == ["P1-01", "P1-02"]
    page = _berth(app, signed_in, "Berth 6")
    signed_in.post(page + "/model", data={"model": (io.BytesIO(shared.encode()), "berth.ifc")}, content_type="multipart/form-data")
    answer = signed_in.post(page + "/model/import", data={"kinds": ["pile"]}, follow_redirects=True)
    assert answer.status_code == 200 and "imported from the model" in text(answer)
    made = {e["name"] for e in signed_in.get(page + "/twin.json").get_json()["elements"]}
    assert {"P1-01", "P1-02"} <= made and "F1" not in made
    assert "nothing" in text(signed_in.post(page + "/model/import", data={"kinds": ["pile"]}, follow_redirects=True)).lower()


def test_all_elements_can_be_removed_and_imported_again(app, signed_in):
    page = _berth(app, signed_in, "Berth 9")
    signed_in.post(page + "/model", data={"model": (io.BytesIO(FIXTURE.read_bytes()), "berth.ifc")}, content_type="multipart/form-data")
    signed_in.post(page + "/model/import")
    before = signed_in.get(page + "/twin.json").get_json()["elements"]
    assert before and "Remove all" in text(signed_in.get(page + "/setup"))
    answer = signed_in.post(page + "/elements/delete", follow_redirects=True)
    assert f"{len(before)} elements and their sensors were removed" in text(answer)
    assert signed_in.get(page + "/twin.json").get_json()["elements"] == []
    with app.app_context():
        from app.db import get_db
        orphans = get_db().execute("SELECT COUNT(*) FROM marine_readings r LEFT JOIN marine_sensors s ON s.id = r.sensor_id"
                                   " WHERE s.id IS NULL").fetchone()[0]
        assert orphans == 0
    signed_in.post(page + "/model/import")                   # the model stayed: it comes back
    assert len(signed_in.get(page + "/twin.json").get_json()["elements"]) == len(before)


def test_an_import_that_fails_says_so_instead_of_a_server_error(app, signed_in, monkeypatch):
    page = _berth(app, signed_in, "Berth 7")
    signed_in.post(page + "/model", data={"model": (io.BytesIO(FIXTURE.read_bytes()), "berth.ifc")}, content_type="multipart/form-data")

    def broken(*args, **kwargs):
        raise ValueError("a bad element")
    monkeypatch.setattr(marine, "import_elements", broken)
    answer = signed_in.post(page + "/model/import", follow_redirects=True)
    assert answer.status_code == 200 and "could not be imported" in text(answer) and "a bad element" in text(answer)


def test_an_upload_from_the_page_script_is_told_where_to_go(app, signed_in):
    page = _berth(app, signed_in, "Berth 8")
    answer = signed_in.post(page + "/model", data={"model": (io.BytesIO(FIXTURE.read_bytes()), "berth.ifc")},
                            content_type="multipart/form-data", headers={"X-MarineTwin-Xhr": "1"})
    assert answer.status_code == 200 and answer.get_json()["redirect"].endswith(page + "/setup#model")
    assert "16 elements" in text(signed_in.get(page + "/setup"))


def test_a_big_model_is_read_from_disk_without_loading_it(tmp_path):
    path = tmp_path / "berth.ifc"
    path.write_bytes(FIXTURE.read_bytes())
    assert len(marine_ifc.read_file(path)["elements"]) == 16
    (tmp_path / "empty.ifc").write_bytes(b"")
    assert marine_ifc.read_file(tmp_path / "empty.ifc")["elements"] == []


def test_the_world_map_carries_every_located_asset(signed_in, demo):
    page = text(signed_in.get("/marinetwin/"))
    assert "Where they are" in page and "6.43872" in page


def test_each_terminal_type_speaks_its_own_words():
    now = datetime(2026, 10, 3, 12)
    for terminal, prefix in (("container", "STS"), ("general_cargo", "MHC"), ("roro", "Ramp gang"), ("bulk", "SU")):
        cranes = marine_ops.cranes(1, now, gust=30.0, terminal=terminal)
        assert cranes and all(c["name"].startswith(prefix) for c in cranes)
        if terminal == "roro":
            assert all(c["state"] != "critical" or "wind" not in c.get("why", "") for c in cranes)
        ships = marine_ops.lineup(1, now, terminal)
        assert ships and {s["name"] for s in ships} <= {f[0] for f in marine_ops.FLEETS[terminal]}
        words = marine_sim.vocab(terminal)
        result = marine_sim.run(1, marine_sim.DEFAULTS, detail=False, terminal=terminal)
        assert result and words


def test_a_terminal_type_can_be_set_and_reshapes_the_pages(app, signed_in, demo):
    with app.app_context():
        asset = connect(app.config["DATABASE"]).execute("SELECT * FROM marine_assets").fetchone()
    form = {k: asset[k] if asset[k] is not None else "" for k in ("name", "kind", "location", "client", "commissioned",
                                                                   "design_life", "corrosion_code", "latitude", "longitude",
                                                                   "rotation", "msl_cd")}
    form["terminal_type"] = "roro"
    signed_in.post(demo + "/settings", data=form)
    assert signed_in.get(demo + "/twin.json").get_json()["asset"]["terminal"] == "roro"
    assert "ramp gangs" in text(signed_in.get(demo + "/operations")).lower()  # shown whether or not a ship is in
    assert signed_in.get(demo + "/simulation").status_code == 200


def test_every_page_shows_the_steps_from_the_asset_list(signed_in, demo):
    for path in ("", "/setup", "/live", "/lifecycle", "/operations", "/simulation", "/equipment", "/environment", "/carbon", "/safety"):
        page = text(signed_in.get(demo + path))
        assert page.count('class="mt-step ') == 8 and 'aria-current="page"' in page and "marinetwin-ui.js" in page
    front = text(signed_in.get("/marinetwin/"))
    assert front.count('class="mt-step ') == 8 and front.count("mt-step s") - front.count(" off") == 1


def test_setting_up_lands_on_the_setup_step(signed_in):
    answer = signed_in.post("/marinetwin/assets", data={"name": "Berth 9", "kind": "quay_wall", "commissioned": "2024-01-01"})
    assert answer.headers["Location"].endswith("/setup")
    page = text(signed_in.get(answer.headers["Location"]))
    assert 'data-tab="Revit model"' in page and "Revit Modelling Guide" in page


def test_the_top_bar_is_ahm_home_with_only_the_admin_links(signed_in, demo):
    page = text(signed_in.get(demo))
    bar = page[page.index('<header class="topbar">'):page.index("</header>")]
    assert ">AHM</span>" in bar and 'href="/"' in bar
    assert "Admin" in bar and "Backups" in bar
    for app_name in ("Portfolio", "Triton", "THEMIS", ">MarineTwin<", "How to use", "Project Control"):
        assert app_name not in bar


def test_dar_legend_names_are_recognised():
    kind = marine_ifc._kind_from_name
    assert [kind(n) for n in ("MP1-DS03", "RP", "RP2-DS01-L1", "FKS", "FKC-DS02", "SPW")] == \
        ["pile", "pile", "pile", "pile", "pile", "sheet_pile"]
    assert kind("Detail:Rebar chair") is None and kind("MPX") is None


def test_piles_sharing_a_design_are_monitored_through_one_of_them(app, signed_in):
    page = _berth(app, signed_in, "Berth 9")
    pile = {"kind": "pile", "material": "steel", "zone": "splash", "y": 0, "z": 0}
    found = {"elements": [{**pile, "name": f"MP1-DS03-0{i}", "group": "MP1-DS03", "global_id": f"g{i}", "x": i} for i in (1, 2, 3)]
             + [{**pile, "name": "MP2-DS01-01", "group": "MP2-DS01", "global_id": "h1", "x": 9},
                {**pile, "name": "MP2-DS01-02", "group": "MP2-DS01", "global_id": "h2", "x": 10, "sensors": ["strain"]},
                {**pile, "name": "P07", "global_id": "p7", "x": 12}]}
    with app.app_context():
        db = connect(app.config["DATABASE"])
        asset_id = int(page.rsplit("/", 1)[1])
        marine.import_elements(db, asset_id, found)
        db.commit()
    by = {e["name"]: e for e in signed_in.get(page + "/twin.json").get_json()["elements"]}
    assert by["MP1-DS03-01"]["sensors"] and not by["MP1-DS03-02"]["sensors"] and not by["MP1-DS03-03"]["sensors"]
    assert by["MP2-DS01-01"]["sensors"] and by["MP2-DS01-02"]["sensors"]   # listed in MT_Sensors: always fitted
    assert by["P07"]["sensors"]                                           # a pile of its own keeps its sensors


def test_uniquely_named_elements_of_one_design_share_their_sensors(app, signed_in):
    # The Revit add-in names every element (MP001, MP002, ...) and keeps the design in MT_Legend;
    # a slab without a legend is grouped with its like along each stretch of quay.
    page = _berth(app, signed_in, "Berth 11")
    pile = {"kind": "pile", "material": "steel", "zone": "splash", "y": 0, "z": 0}
    slab = {"kind": "slab", "material": "concrete", "zone": "atmospheric", "y": 0, "z": 0}
    fender = {"kind": "fender", "material": "rubber", "zone": "splash", "y": 0, "z": 0}
    found = {"elements": [{**pile, "name": f"MP{i:03d}", "legend": "MP1-DS03", "global_id": f"p{i}", "x": i} for i in range(1, 41)]
             + [{**slab, "name": f"DK{i:03d}", "global_id": f"d{i}", "x": i * 10} for i in range(1, 40)]
             + [{**fender, "name": f"F{i:02d}", "global_id": f"f{i}", "x": i * 20} for i in range(1, 6)]}
    with app.app_context():
        db = connect(app.config["DATABASE"])
        asset_id = int(page.rsplit("/", 1)[1])
        marine.import_elements(db, asset_id, found)
        db.commit()
    by = {e["name"]: e for e in signed_in.get(page + "/twin.json").get_json()["elements"]}
    assert sum(1 for n, e in by.items() if n.startswith("MP") and e["sensors"]) == 1
    assert sum(1 for n, e in by.items() if n.startswith("DK") and e["sensors"]) == 2      # 0-200 m and 200-400 m
    assert all(by[f"F{i:02d}"]["sensors"] for i in range(1, 6))                         # every fender is rated alone


def test_trimming_keeps_one_sensored_element_per_design_and_real_feeds(app, signed_in):
    page = _berth(app, signed_in, "Berth 12")
    pile = {"kind": "pile", "material": "steel", "zone": "splash", "y": 0, "z": 0, "sensors": ["corrosion", "strain"]}
    found = {"elements": [{**pile, "name": f"MP{i:03d}", "legend": "MP1-DS03", "global_id": f"p{i}", "x": i} for i in range(1, 11)]}
    with app.app_context():
        db = connect(app.config["DATABASE"])
        asset_id = int(page.rsplit("/", 1)[1])
        marine.import_elements(db, asset_id, found)             # listed in MT_Sensors: all ten fitted, as before the fix
        real = db.execute("SELECT s.id FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
                          " WHERE e.name = 'MP005' AND s.kind = 'strain'").fetchone()["id"]
        db.execute("UPDATE marine_sensors SET simulated = 0, feed_device = 'logger-1' WHERE id = ?", (real,))
        db.commit()
    assert "18 simulated sensors removed" in text(signed_in.post(page + "/sensors/trim", follow_redirects=True))
    by = {e["name"]: e for e in signed_in.get(page + "/twin.json").get_json()["elements"]}
    assert len(by["MP005"]["sensors"]) == 2 and not any(by[f"MP{i:03d}"]["sensors"] for i in range(1, 11) if i != 5)
    assert "already has its sensors" in text(signed_in.post(page + "/sensors/trim", follow_redirects=True))


def test_the_3d_view_keeps_the_shapes_it_built(app, signed_in):
    page = _berth(app, signed_in, "Berth 10")
    signed_in.post(page + "/model", data={"model": (io.BytesIO(FIXTURE.read_bytes()), "berth.ifc")}, content_type="multipart/form-data")
    twin = signed_in.get(page + "/twin.json").get_json()
    assert twin["model_shapes"] is None and twin["model_shapes_save"]
    shapes = gzip.compress(b"MTM1" + b"\0" * 64)
    assert signed_in.post(twin["model_shapes_save"], data=b"not gzip").status_code == 400
    assert signed_in.post(twin["model_shapes_save"], data=shapes).get_json()["kept"]
    twin = signed_in.get(page + "/twin.json").get_json()
    assert twin["model_shapes_save"] is None and signed_in.get(twin["model_shapes"]).data == shapes
    # New elements are shapes of their own: what was kept no longer fits, and is built again.
    signed_in.post(page + "/model/import", data={"kinds": ["fender"]})
    again = signed_in.get(page + "/twin.json").get_json()
    assert again["model_shapes"] is None and again["model_shapes_save"] != twin["model_shapes"]
    assert signed_in.post(twin["model_shapes"], data=shapes).status_code == 409
    signed_in.post(page + "/model", data={"model": (io.BytesIO(FIXTURE.read_bytes()), "berth.ifc")}, content_type="multipart/form-data")
    assert signed_in.get(twin["model_shapes"]).status_code == 404


def test_the_live_port_plays_two_days_at_the_berth(signed_in, demo):
    page = text(signed_in.get(demo + "/live"))
    assert 'data-mode="live"' in page and "/live.json" in page and "Duty log" in page
    plan = signed_in.get(demo + "/live.json").get_json()
    assert len(plan["hours"]) == 49 and plan["calls"] and plan["events"]
    hour = plan["hours"][0]
    assert {"wind", "gust", "hs", "tide", "rain", "visibility", "equipment", "berthing"} <= set(hour)
    starts = [c["eta"] for c in plan["calls"]]
    assert starts == sorted(starts)
    for before, after in zip(plan["calls"], plan["calls"][1:]):
        assert after["eta"] >= before["etd"]                       # one ship at a time on the berth


def test_ships_berth_only_inside_the_weather_limits():
    now = datetime(2026, 10, 4, 12)
    for asset_id in range(1, 30):
        plan = marine_ops.live(asset_id, now, "container")
        by_hour = {h["at"]: h for h in plan["hours"]}
        for c in plan["calls"]:
            if c["eta"] > plan["start"]:
                hour = by_hour[c["eta"].replace(minute=0, second=0, microsecond=0)]
                before = by_hour.get(hour["at"] - timedelta(hours=1), hour)
                assert hour["berthing"] and before["berthing"], (asset_id, c["name"])
        for h in plan["hours"]:
            for kit in h["equipment"]:
                if h["gust"] >= marine_ops.LIMITS["crane_stop_gust"]:
                    assert kit["state"] in ("stopped", "stowed")


def test_the_live_port_plays_each_situation():
    now = datetime(2026, 10, 4, 21)
    normal = marine_ops.live(3, now, "container")
    assert normal["scenario"]["key"] == "normal" and all(h["power"] for h in normal["hours"])
    cut = marine_ops.live(3, now, "container", scenario="power_cut")
    dark = [h for h in cut["hours"] if not h["power"]]
    assert len(dark) == 4 and dark[0]["at"].hour == 20 and dark[0]["at"] > cut["start"]
    assert all(k["state"] == "down" for h in dark for k in h["equipment"])
    assert any("Power cut" in e["text"] for e in cut["events"]) and any("Power restored" in e["text"] for e in cut["events"])
    # Ramp gangs drive diesel vehicles: a power cut does not stop them.
    roro = marine_ops.live(3, now, "roro", scenario="power_cut")
    assert not any(k["why"].startswith("power cut") for h in roro["hours"] for k in h["equipment"])
    storm = marine_ops.live(3, now, "container", scenario="storm")
    assert any(k["state"] == "stowed" for h in storm["hours"] for k in h["equipment"])
    assert not all(h["berthing"] for h in storm["hours"])
    fog = marine_ops.live(3, now, "container", scenario="fog")
    foggy = [h for h in fog["hours"] if h["fog"]]
    assert foggy and all(not h["berthing"] and h["visibility"] < 0.5 for h in foggy)
    fault = marine_ops.live(3, now, "container", scenario="crane_fault")
    assert sum(1 for h in fault["hours"] if h["equipment"][0]["state"] == "down") >= 20
    peak = marine_ops.live(3, now, "container", scenario="peak")
    assert peak["scenario"]["name"] == "Peak week" and len(peak["calls"]) >= len(normal["calls"])
    assert marine_ops.live(3, now, "container", scenario="nonsense")["scenario"]["key"] == "normal"


def test_situations_and_berth_uses_over_the_web(signed_in, demo):
    plan = signed_in.get(demo + "/live.json?scenario=storm").get_json()
    assert plan["scenario"]["key"] == "storm" and [s["key"] for s in plan["scenarios"]][0] == "normal"
    assert "data-scenario=\"fog\"" in text(signed_in.get(demo + "/live?scenario=fog"))
    assert "/live?scenario=power_cut" in text(signed_in.get(demo + "/simulation"))
    twin = signed_in.get(demo + "/twin.json").get_json()
    assert twin["asset"]["berth_uses"] == {} and "roro" in twin["asset"]["berth_use_names"]
    answer = signed_in.post(demo + "/berths", json={"berth": 6, "use": "roro"})
    assert answer.status_code == 200 and answer.get_json()["berth_uses"] == {"6": "roro"}
    signed_in.post(demo + "/berths", json={"berth": 7, "use": "mixed"})
    assert signed_in.get(demo + "/twin.json").get_json()["asset"]["berth_uses"] == {"6": "roro", "7": "mixed"}
    assert signed_in.post(demo + "/berths", json={"berth": 6, "use": "swimming"}).status_code == 400
    assert signed_in.post(demo + "/berths", json={"berth": "x", "use": "roro"}).status_code == 400


# --- the lifecycle --------------------------------------------------------------

def test_the_lifecycle_page_compares_doing_nothing_with_fixing(signed_in, demo):
    page = text(signed_in.get(demo + "/lifecycle"))
    assert 'data-mode="life"' in page and "/lifecycle.json" in page
    assert "Do nothing" in page and "Fix as you go" in page and "Saved by fixing" in page
    run = signed_in.get(demo + "/lifecycle.json?policy=nothing").get_json()
    assert run["finished"] and run["done"] == run["life"] * 12 == len(run["rows"]) == len(run["states"])
    assert len(run["states"][0]) == len(run["parts"])
    assert {p["kind"] for p in run["parts"]} >= {"fender", "wall", "deck", "bollard", "pipes", "drainage", "power", "lighting"}


def test_fixing_as_you_go_costs_less_and_lasts_longer(app, signed_in, demo):
    with app.app_context():
        from app.db import query, query_one
        asset_id = int(demo.rstrip("/").split("/")[-1])
        asset = query_one("SELECT * FROM marine_assets WHERE id = ?", (asset_id,))
        elements = query("SELECT * FROM marine_elements WHERE asset_id = ?", (asset_id,))
        both = marine_life.compare(asset, elements)
    nothing, fixing = both["nothing"]["totals"], both["fix"]["totals"]
    assert nothing["spend"] == 0 and nothing["fixes"] == 0
    assert fixing["fixes"] > 0 and fixing["spend"] > 0
    assert fixing["cost_moves"] < nothing["cost_moves"] and both["saved_moves"] > 0
    assert fixing["service_life"] > both["fix"]["life"]
    assert nothing["service_life"] < fixing["service_life"]
    # The cost in moves is the lost moves plus the repairs at the value of a move.
    value = both["fix"]["rates"]["value_per_move"]
    assert fixing["cost_moves"] == round(fixing["lost_all"] + fixing["spend"] / value)
    assert fixing["lost_all"] == pytest.approx(fixing["lost"] + fixing["lost_weather"] + fixing["lost_hazard"] + fixing["lost_demand"], abs=2)
    # Fenders start to wear after about fifteen years, not before.
    first = min(e["m"] for e in both["fix"]["events"] if e.get("part", "") and e["part"].startswith("F") and e["kind"] == "warning")
    assert first >= 14 * 12


def test_the_game_stops_at_each_issue_and_a_choice_changes_only_what_follows(app, signed_in, demo):
    first = signed_in.post(demo + "/lifecycle.json", json={"policy": "game", "choices": []}).get_json()
    assert not first["finished"] and first["pending"]
    issue = first["pending"][0]
    assert issue["m"] == first["done"] and set(issue["options"]) == {"fix", "close", "wait"}
    for act in ("fix", "close", "wait"):
        after = signed_in.post(demo + "/lifecycle.json",
                               json={"policy": "game", "choices": [[issue["id"], act, issue["m"]]]}).get_json()
        assert after["done"] > first["done"]
        assert after["rows"][:first["done"]] == first["rows"]          # the past is as it was
        mine = [e for e in after["events"] if e["m"] == issue["m"] and e.get("issue") == issue["id"]]
        assert {"fix": "fix", "close": "close", "wait": "wait"}[act] in {e["kind"] for e in mine}
    # Answering every issue with "fix" ends where fixing as you go does.
    choices = []
    for _ in range(200):
        run = signed_in.post(demo + "/lifecycle.json", json={"policy": "game", "choices": choices}).get_json()
        if run["finished"]:
            break
        choices += [[p["id"], "fix", p["m"]] for p in run["pending"]]
    fixing = signed_in.get(demo + "/lifecycle.json?policy=fix").get_json()
    assert run["finished"] and run["totals"]["cost_moves"] == fixing["totals"]["cost_moves"]


def test_the_rates_change_the_money_not_the_story(signed_in, demo):
    plain = signed_in.get(demo + "/lifecycle.json?policy=fix").get_json()
    dear = signed_in.get(demo + "/lifecycle.json?policy=fix&value_per_move=220&fender=1").get_json()
    assert dear["rates"]["value_per_move"] == 220 and dear["rates"]["fender"] == 1
    assert [e["m"] for e in dear["events"]] == [e["m"] for e in plain["events"]]
    assert dear["totals"]["spend"] < plain["totals"]["spend"]
    assert "220" in text(signed_in.get(demo + "/lifecycle?value_per_move=220"))


def _demo_asset(app, demo):
    from app.db import query, query_one
    with app.app_context():
        asset_id = int(demo.rstrip("/").split("/")[-1])
        return (query_one("SELECT * FROM marine_assets WHERE id = ?", (asset_id,)),
                query("SELECT * FROM marine_elements WHERE asset_id = ?", (asset_id,)))


def test_force_majeure_is_left_out_unless_asked_and_a_hit_closes_the_berth(app, signed_in, demo):
    asset, elements = _demo_asset(app, demo)
    plain = marine_life.run(asset, elements, "nothing")
    assert not plain["risks"]["war_direct"] and not plain["risks"]["war_indirect"] and plain["risks"]["storms"]
    assert not any(e.get("risk", "").startswith("war") for e in plain["events"])
    war = marine_life.run(asset, elements, "nothing", risks={"risk_war_direct": "1", "risk_war_indirect": "1", "war_year": "20"})
    hits = [e for e in war["events"] if e.get("risk") == "war_direct"]
    assert len(hits) == 1 and 19 * 12 <= hits[0]["m"] < 20 * 12
    assert war["totals"]["lost_demand"] > 0
    assert war["totals"]["cost_moves"] > plain["totals"]["cost_moves"]
    fixed = marine_life.run(asset, elements, "fix", risks={"risk_war_direct": "1", "war_year": "20"})
    assert any(e["kind"] == "fix" and e["part"] == "X1" for e in fixed["events"])      # rebuilt after the hit


def test_the_hazards_fall_in_the_same_months_however_the_berth_is_kept(app, signed_in, demo):
    asset, elements = _demo_asset(app, demo)
    asset = {**dict(asset), "id": 5}                    # a berth whose draws hold two earthquakes
    risks = {"seismic": "high", "sea_level": "high", "freeboard": "0.8"}
    nothing = marine_life.run(asset, elements, "nothing", risks=risks)
    fixing = marine_life.run(asset, elements, "fix", risks=risks)
    schedule = lambda r: [(m, h[0]) for m, w in enumerate(r["weather"]) for h in w["haz"]]  # noqa: E731
    assert schedule(nothing) == schedule(fixing)[:len(schedule(nothing))]
    quakes = [e["m"] for e in fixing["events"] if e.get("risk") == "earthquake"]
    assert quakes and quakes == [m for m, key in schedule(fixing) if key == "earthquake"]
    assert [w["slr"] for w in nothing["weather"]] == [w["slr"] for w in fixing["weather"]]
    assert nothing["weather"][-1]["slr"] == pytest.approx(0.6, abs=0.02)
    # A low cope and a rising sea: the sea comes over, and raising the quay is offered.
    assert any(e.get("risk") == "sea_level" for e in nothing["events"])
    assert any(e["kind"] == "fix" and e["part"] == "Q1" for e in fixing["events"])


def test_the_utilities_silt_wear_out_and_are_kept_up(app, signed_in, demo):
    asset, elements = _demo_asset(app, demo)
    fixing = marine_life.run(asset, elements, "fix")
    nothing = marine_life.run(asset, elements, "nothing")
    fixed = {e["part"] for e in fixing["events"] if e["kind"] == "fix"}
    assert {"U2", "U4"} <= fixed                                                  # drains cleaned, lights renewed
    assert any(e.get("risk") == "drainage" for e in nothing["events"])            # blocked drains flood the apron
    assert not any(e.get("risk") == "drainage" for e in fixing["events"])


def test_each_part_carries_its_life_and_warranty_and_a_wear_repair_in_warranty_is_free(app, signed_in, demo):
    asset, elements = _demo_asset(app, demo)
    plain = marine_life.run(asset, elements, "fix")
    fender = next(p for p in plain["parts"] if p["kind"] == "fender")
    assert fender["expected_life"] == 20 and fender["warranty"] == 5 and fender["covers"]
    generous = marine_life.run(asset, elements, "fix", rates={"warranty_fender": "40", "warranty_lighting": "40"})
    assert generous["totals"]["warranty_fixes"] > plain["totals"]["warranty_fixes"]
    assert generous["totals"]["spend"] < plain["totals"]["spend"]
    assert any(e.get("warranty") for e in generous["events"] if e["kind"] == "fix")


def test_the_risks_form_reads_the_box_ticked_after_its_hidden_zero(signed_in, demo):
    page = text(signed_in.get(demo + "/lifecycle?risk_war_direct=0&risk_war_direct=1&risk_storms=0&war_year=12"))
    assert "Risks to include" in page and "Expected life and warranty" in page
    run = signed_in.get(demo + "/lifecycle.json?policy=nothing&risk_war_direct=0&risk_war_direct=1&risk_storms=0&war_year=12").get_json()
    assert run["risks"]["war_direct"] and not run["risks"]["storms"] and run["risks"]["war_year"] == 12
    assert all(w["storm"] == 0 for w in run["weather"])


def test_an_assets_history_says_who_changed_what(app, signed_in):
    page = _berth(app, signed_in, "Berth 13")
    signed_in.post(page + "/elements", data={"name": "P01", "kind": "pile", "material": "steel", "zone": "splash"})
    signed_in.post(page + "/sensors/trim")
    with app.app_context():
        db = connect(app.config["DATABASE"])
        rows = db.execute("SELECT action, user_id FROM marine_changes WHERE asset_id = ? ORDER BY id",
                          (int(page.rsplit("/", 1)[1]),)).fetchall()
    assert [r["action"] for r in rows] == ["Added an element: P01", "Kept sensors on one element per design"]
    assert all(r["user_id"] for r in rows)
    assert "Added an element: P01" in text(signed_in.get(page + "/setup"))


def test_forecasts_come_with_a_range():
    points = [(t, 0.1 + 0.02 * t + (0.004 if i % 2 else -0.004)) for i, t in enumerate(range(1, 11))]
    early, late = marine.trend_range(points, 0.4, 2020)
    likely = marine.trend_year(points, 0.4, 2020)
    assert early < likely < late
    assert marine.trend_range([(1, 0.1), (2, 0.1), (3, 0.1), (4, 0.1)], 0.4, 2020) is None    # not rising
    fit = marine.fit_corrosion([(t, 0.1 * t ** 0.8 * (1.05 if t % 2 else 0.95)) for t in range(1, 11)])
    assert marine.corrosion_spread([(t, 0.1 * t ** 0.8 * (1.05 if t % 2 else 0.95)) for t in range(1, 11)], fit) > 1


def _feed(app, signed_in, demo):
    asset_id = _asset_id(demo)
    signed_in.get(demo + "/sensors")
    with app.app_context():
        key = connect(app.config["DATABASE"]).execute("SELECT feed_key FROM marine_assets WHERE id = ?", (asset_id,)).fetchone()[0]
    return f"/marinetwin/api/assets/{asset_id}/readings", {"X-MarineTwin-Key": key}


def test_readings_are_calibrated_and_impossible_ones_refused(app, client, signed_in, demo):
    url, headers = _feed(app, signed_in, demo)
    day = date.today().isoformat()
    with app.app_context():
        conn = connect(app.config["DATABASE"])
        sensor = conn.execute("SELECT s.id, e.id AS element_id FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
                              " WHERE s.label = 'P01-SG1'").fetchone()
    answer = client.post(url, headers=headers, json={"readings": [
        {"sensor": "P01-SG1", "at": f"{day}T01:00", "value": 100},
        {"sensor": "P01-SG1", "at": f"{day}T02:00", "value": 99999},           # a broken gauge
        {"sensor": "P01-SG1", "at": "2099-01-01T00:00", "value": 120}]})       # a logger clock gone wrong
    problems = answer.get_json()["problems"]
    assert answer.get_json()["written"] == 1 and "refused as a fault" in problems[0] and "future" in problems[1]
    page = f"{demo}/elements/{sensor['element_id']}"
    signed_in.post(f"{demo}/sensors/{sensor['id']}/calibration", data={"zero": "20", "factor": "2"})
    client.post(url, headers=headers, json={"readings": [{"sensor": "P01-SG1", "at": f"{day}T03:00", "value": 70}]})
    with app.app_context():
        rows = connect(app.config["DATABASE"]).execute(
            "SELECT at, value, raw FROM marine_readings WHERE sensor_id = ? ORDER BY at", (sensor["id"],)).fetchall()
    assert [(r["value"], r["raw"]) for r in rows] == [(160.0, 100.0), (100.0, 70.0)]   # (raw − 20) × 2, old ones redone
    assert "Save calibration" in text(signed_in.get(page))


def test_an_alarm_opens_with_the_reading_is_acknowledged_and_closes(app, client, signed_in, demo):
    url, headers = _feed(app, signed_in, demo)
    day = date.today().isoformat()
    client.post(url, headers=headers, json={"readings": [{"sensor": "P01-SG1", "at": f"{day}T01:00", "value": 1400}]})
    with app.app_context():
        alarm = connect(app.config["DATABASE"]).execute("SELECT * FROM marine_alarms WHERE label LIKE 'P01-SG1%'").fetchone()
    assert alarm["state"] == "critical" and alarm["closed_at"] is None          # opened by the feed, nobody looking
    signed_in.post(f"{demo}/alarms/{alarm['id']}/ack", data={"note": "inspecting at low tide"})
    page = text(signed_in.get(demo))
    assert "inspecting at low tide" in page and "Acknowledge" in page
    # The peak counts for a quarter, so bring the record back down with a quiet season of readings.
    later = [{"sensor": "P01-SG1", "at": f"{day}T{h:02d}:00", "value": 100} for h in range(2, 24)]
    client.post(url, headers=headers, json={"readings": later})
    with app.app_context():
        closed = connect(app.config["DATABASE"]).execute("SELECT closed_at FROM marine_alarms WHERE id = ?", (alarm["id"],)).fetchone()
    assert closed["closed_at"] is not None


def test_each_model_upload_is_a_version_compared_with_the_last(app, signed_in):
    from app import marine_ifc
    page = _berth(app, signed_in, "Berth 14")
    first = FIXTURE.read_bytes()
    signed_in.post(page + "/model", data={"model": (io.BytesIO(first), "berth-v1.ifc")}, content_type="multipart/form-data")
    signed_in.post(page + "/model/import")
    with app.app_context():
        conn = connect(app.config["DATABASE"])
        asset_id = int(page.rsplit("/", 1)[1])
        names = [r["name"] for r in conn.execute("SELECT name FROM marine_elements WHERE asset_id = ? ORDER BY name", (asset_id,))]
    assert names
    # The next export drops one element and renames none: the same GlobalIds come back.
    text_ifc = first.decode("utf-8", "replace")
    found = marine_ifc.read(first)
    gone = next(e for e in found["elements"] if not e.get("group"))
    second = "\n".join(line for line in text_ifc.split("\n") if f"'{gone['global_id']}'" not in line).encode()
    answer = text(signed_in.post(page + "/model", data={"model": (io.BytesIO(second), "berth-v2.ifc")},
                                 content_type="multipart/form-data", follow_redirects=True))
    assert "Version 2: 1 removed since the last one" in answer
    setup = text(signed_in.get(page + "/setup"))
    assert "Version 2" in setup and "berth-v1.ifc" in setup and "the model no longer has" in setup
    signed_in.post(page + "/model/orphans/remove")
    with app.app_context():
        left = {r["name"] for r in connect(app.config["DATABASE"]).execute("SELECT name FROM marine_elements WHERE asset_id = ?", (asset_id,))}
    assert gone["name"] not in left and len(left) == len(names) - 1


def test_comparing_exports_finds_moves_and_changes():
    from app import marine_versions
    a = [{"id": "g1", "name": "P01", "kind": "pile", "x": 0, "y": 0, "z": 0}, {"id": "g2", "name": "P02", "kind": "pile", "x": 5, "y": 0, "z": 0}]
    b = [{"id": "g1", "name": "P01", "kind": "pile", "x": 0, "y": 0.5, "z": 0}, {"id": "g2", "name": "MP02", "kind": "pile", "x": 5, "y": 0, "z": 0},
         {"id": "g3", "name": "P03", "kind": "pile", "x": 10, "y": 0, "z": 0}]
    diff = marine_versions.compare(a, b)
    assert diff["added"] == ["P03"] and diff["removed"] == [] and diff["moved"] == [{"name": "P01", "by": 0.5}]
    assert diff["changed"] == [{"name": "MP02", "what": ["name was P02"]}]
