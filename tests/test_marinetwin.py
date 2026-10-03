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
    assert len(twin["elements"]) == 10
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
    assert exported.startswith("sensor,at,value\n")
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
