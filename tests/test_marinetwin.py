"""MarineTwin: the door, the twin's arithmetic, and its link to Triton.

The arithmetic is what a client would act on, so it is pinned with readings
whose answer is known: a loss curve the fit has to recover, an element whose
corrosion is running past its allowance, and the utilisation that follows.
"""

from __future__ import annotations

import io
import math
from datetime import date

import pytest

from app import marine, marine_triton
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
    assert "Berth 1" in text(signed_in.get(demo))

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
    for heading in ("What is happening now", "What will happen next", "What should we do",
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
    assert "Baseline" in page and "Scenarios side by side" in page and "<svg" in page
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
