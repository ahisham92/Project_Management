"""MarineTwin's pages: the assets, one asset's twin, and one element's sensors.

The calculations live in ``marine`` (condition, projection, advice) and in
Triton (the design it is judged against, through ``marine_triton``); these views
only gather and show them. Every page is behind the site's one sign-in and the
``marinetwin`` program the administrator gives an account.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import date, datetime
from pathlib import Path

from flask import (
    Blueprint, Response, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file, url_for,
)

from .. import marine, marine_facility, marine_ifc, marine_life, marine_ops, marine_sim, marine_triton
from ..auth import login_required
from ..db import data_dir, get_db, query, query_one
from ..marine_charts import (
    carbon_months, env_chart, life_costs, sea_forecast, sensor_trend, sim_gate, sim_ships, wind_forecast,
)

bp = Blueprint("marine", __name__, url_prefix="/marinetwin")


@bp.after_request
def _redirect_for_the_voyage(response):
    """A form sent from the page's script (an upload showing its progress) gets where to go next as
    JSON, so the script can sail on to it; the flash message waits there as usual."""
    if request.headers.get("X-MarineTwin-Xhr") and response.status_code in (301, 302, 303):
        return jsonify(redirect=response.headers["Location"])
    return response

# What the 3D view can open: a Revit model exported as IFC, or as glTF / GLB.
MODEL_TYPES = {".ifc": "ifc", ".glb": "glb", ".gltf": "gltf"}
MODEL_LIMIT = 200 * 1024 * 1024
SHAPES_LIMIT = 600 * 1024 * 1024


def models_dir() -> Path:
    folder = data_dir() / "marinetwin" / "models"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _asset_or_404(asset_id: int):
    asset = query_one("SELECT * FROM marine_assets WHERE id = ?", (asset_id,))
    if asset is None:
        abort(404)
    return asset


def _element_or_404(asset_id: int, element_id: int):
    element = query_one("SELECT * FROM marine_elements WHERE id = ? AND asset_id = ?", (element_id, asset_id))
    if element is None:
        abort(404)
    return element


def _may_remove(asset) -> bool:
    return g.user["role"] == "admin" or asset["created_by"] == g.user["id"]


def _number(name: str, default=None):
    text = (request.form.get(name) or "").strip()
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        return default
    return value if math.isfinite(value) else default


def _choice(name: str, pairs, default: str) -> str:
    value = request.form.get(name) or default
    return value if value in dict(pairs) else default


def _day_field(name: str, default: str) -> str:
    text = (request.form.get(name) or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return default


def _context() -> dict:
    return {
        "asset_kinds": marine.ASSET_KINDS, "element_kinds": marine.ELEMENT_KINDS, "zones": marine.ZONES,
        "materials": marine.MATERIALS, "sensor_kinds": marine.SENSOR_KINDS, "grades": marine.GRADES,
        "suggested": marine.SUGGESTED, "terminal_types": marine.TERMINAL_TYPES,
        "terminal_name": marine.labels(marine.TERMINAL_TYPES),
        "kind_name": marine.labels(marine.ASSET_KINDS), "element_kind_name": marine.labels(marine.ELEMENT_KINDS),
        "zone_name": marine.labels(marine.ZONES), "triton_ready": marine_triton.available(),
    }


# --- the assets -------------------------------------------------------------------

@bp.get("/")
@login_required
def index():
    db = get_db()
    assets = []
    for asset in query("SELECT * FROM marine_assets ORDER BY name"):
        twin = marine.assess_asset(db, asset)
        assets.append({"asset": asset, "twin": twin})
    totals = {
        "assets": len(assets),
        "sensors": sum(a["twin"]["sensors"] for a in assets),
        "critical": sum(1 for a in assets if a["twin"]["state"] == "critical"),
        "warning": sum(1 for a in assets if a["twin"]["state"] == "warning"),
    }
    world = {"assets": [{"name": a["asset"]["name"], "lat": a["asset"]["latitude"], "lon": a["asset"]["longitude"],
                         "state": a["twin"]["state"], "href": url_for("marine.asset", asset_id=a["asset"]["id"]),
                         "terminal": marine.labels(marine.TERMINAL_TYPES).get(a["asset"]["terminal_type"], "")}
                        for a in assets if a["asset"]["latitude"] is not None]}
    return render_template("marine/index.html", assets=assets, totals=totals, world=world,
                           today=date.today().isoformat(), **_context())


@bp.post("/assets")
@login_required
def new_asset():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Give the asset a name.", "error")
        return redirect(url_for("marine.index"))
    asset_id = get_db().execute(
        "INSERT INTO marine_assets (name, kind, location, client, commissioned, design_life, corrosion_code, created_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, _choice("kind", marine.ASSET_KINDS, "quay_wall"), (request.form.get("location") or "").strip(),
         (request.form.get("client") or "").strip(), _day_field("commissioned", date.today().isoformat()),
         int(_number("design_life", 50) or 50),
         request.form.get("corrosion_code") if request.form.get("corrosion_code") in ("bs6349", "en1993_5") else "bs6349",
         g.user["id"])).lastrowid
    get_db().commit()
    flash(f"{name} is set up. Add its elements and sensors, or link it to its Triton design.", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id))


@bp.post("/demo")
@login_required
def demo():
    asset_id = marine.create_demo(get_db(), g.user["id"])
    get_db().commit()
    flash("A demonstration berth with simulated sensors has been set up.", "success")
    return redirect(url_for("marine.asset", asset_id=asset_id))


# --- one asset ----------------------------------------------------------------------

@bp.get("/assets/<int:asset_id>")
@login_required
def asset(asset_id: int):
    """Step 3, the structure: its health, the twin in 3D, what to do and every element."""
    asset = _asset_or_404(asset_id)
    twin = marine.assess_asset(get_db(), asset)
    return render_template("marine/asset.html", asset=asset, twin=twin, **_context())


@bp.get("/assets/<int:asset_id>/setup")
@login_required
def setup(asset_id: int):
    """Step 2, setting the asset up: the Revit model, where it is, its details, elements and readings."""
    asset = _asset_or_404(asset_id)
    twin = marine.assess_asset(get_db(), asset)
    found = _model_found(asset_id)
    site_map = None
    if asset["latitude"] is not None and asset["longitude"] is not None:
        placed = []
        for e in twin["elements"]:
            at = marine.geolocate(asset, e["element"]["x"], e["element"]["y"])
            placed.append({"name": e["element"]["name"], "kind": e["element"]["kind"], "state": e["state"],
                           "lat": round(at[0], 7), "lon": round(at[1], 7)})
        site_map = {"assets": [] if placed else [{"name": asset["name"], "lat": asset["latitude"], "lon": asset["longitude"],
                                                 "state": twin["state"], "terminal": ""}],
                    "elements": placed, "focus": [asset["latitude"], asset["longitude"]], "zoom": 17}
    return render_template("marine/setup.html", asset=asset, twin=twin, may_remove=_may_remove(asset),
                           site_map=site_map,
                           model_found=found, model_new=_new_in_model(asset_id, found) if found else [],
                           triton_projects=marine_triton.projects(),
                           model_kind=MODEL_TYPES.get(Path(asset["model_file"]).suffix.lower(), ""),
                           **_context())


@bp.get("/assets/<int:asset_id>/operations")
@login_required
def operations(asset_id: int):
    """The berth at work: what is happening now, what happens next, what to do."""
    asset = _asset_or_404(asset_id)
    ops = marine_ops.operations(get_db(), asset)
    # The other modules' urgent items belong on the same list: one place to see what to do.
    extra = (marine_facility.maintenance(asset)["actions"] + marine_facility.compliance(asset)["actions"]
             + marine_facility.safety(asset, ops["now"], ops["twin"])["actions"]
             + marine_facility.environment(asset, ops["now"], ops["alongside"] is not None)["actions"])
    ops["actions"] += [{**a, "when": "", "at": ops["now"]} for a in extra if a["state"] == "critical"]
    order = {"critical": 0, "warning": 1, "good": 2}
    ops["actions"].sort(key=lambda a: (order.get(a["state"], 3), a["area"] not in ("Vessels", "Cranes", "Mooring"), a["at"]))
    return render_template("marine/operations.html", asset=asset, ops=ops, twin=ops["twin"],
                           wind_chart=wind_forecast(ops["weather"], ops["limits"]),
                           sea_chart=sea_forecast(ops["weather"], ops["limits"]), **_context())


@bp.get("/assets/<int:asset_id>/live")
@login_required
def live(asset_id: int):
    """The port as a camera would see it: the next two days played back at 10× or faster."""
    asset = _asset_or_404(asset_id)
    return render_template("marine/live.html", asset=asset, **_context())


@bp.get("/assets/<int:asset_id>/live.json")
@login_required
def live_json(asset_id: int):
    """The timeline the live view plays: hourly weather and equipment, the ship calls, the events."""
    asset = _asset_or_404(asset_id)
    now = datetime.now()
    plan = marine_ops.live(asset_id, now, asset["terminal_type"])
    iso = lambda at: at.isoformat(timespec="minutes")  # noqa: E731
    return jsonify({
        "start": iso(plan["start"]), "now": iso(now), "equipment_name": plan["equipment_name"], "units": plan["units"], "limits": plan["limits"],
        "hours": [{**h, "at": iso(h["at"])} for h in plan["hours"]],
        "calls": [{**c, "eta": iso(c["eta"]), "etd": iso(c["etd"])} for c in plan["calls"]],
        "events": [{**e, "at": iso(e["at"])} for e in plan["events"]],
    })


def _life_rates() -> dict:
    """What the person changed (rates, prices, lives and warranties, the risks included), from the
    query string (the page's forms) or a JSON body."""
    body = request.get_json(silent=True) if request.is_json else None
    given = body.get("rates") if isinstance(body, dict) else None
    source = given if isinstance(given, dict) else request.args
    keys = ("moves_per_day", "value_per_move", *marine_life.PRICES,
            *(f"life_{k}" for k in marine_life.KIND_INFO), *(f"warranty_{k}" for k in marine_life.KIND_INFO),
            *(f"risk_{k}" for k in marine_life.RISKS), "sea_level", "seismic", "war_year", "freeboard")
    # A ticked box sends its hidden 0 and then its 1: the last one is what was meant.
    last = (lambda k: (source.getlist(k) or [None])[-1]) if hasattr(source, "getlist") else source.get
    return {k: str(last(k))[:20] for k in keys if last(k) not in (None, "")}


def _life_elements(asset_id: int):
    return query("SELECT name, kind, material, zone, model_ref, x, y, z FROM marine_elements WHERE asset_id = ?"
                 " ORDER BY x, name", (asset_id,))


@bp.get("/assets/<int:asset_id>/lifecycle")
@login_required
def lifecycle(asset_id: int):
    """The design life in a few minutes: doing nothing against fixing as you go, or deciding each issue."""
    asset = _asset_or_404(asset_id)
    given = _life_rates()
    both = marine_life.compare(asset, _life_elements(asset_id), given, given)
    rates = both["fix"]["rates"]
    return render_template("marine/lifecycle.html", asset=asset, both=both, rates=rates, given=given,
                           risks=both["fix"]["risks"], risk_list=marine_life.RISKS,
                           sea_levels=marine_life.SEA_LEVEL, seismic=marine_life.SEISMIC,
                           kinds=[(k, marine_life.KIND_NAME[k], rates[f"life_{k}"], rates[f"warranty_{k}"], v[2])
                                  for k, v in marine_life.KIND_INFO.items()],
                           prices=[(k, marine_life.PRICE_NAMES[k], rates[k]) for k in marine_life.PRICES],
                           chart=life_costs(marine_life.yearly(both["nothing"]), marine_life.yearly(both["fix"]),
                                            both["fix"]["units"]),
                           **_context())


@bp.route("/assets/<int:asset_id>/lifecycle.json", methods=["GET", "POST"])
@login_required
def lifecycle_json(asset_id: int):
    """One run of the design life: ``policy`` nothing, fix or game, and for a game the choices made so far."""
    asset = _asset_or_404(asset_id)
    body = request.get_json(silent=True) if request.is_json else None
    body = body if isinstance(body, dict) else {}
    policy = body.get("policy") or request.args.get("policy") or "fix"
    choices = body.get("choices") if isinstance(body.get("choices"), list) else []
    given = _life_rates()
    return jsonify(marine_life.run(asset, _life_elements(asset_id), policy, choices[:2000], given, risks=given))


# --- beyond the structure ----------------------------------------------------------

@bp.get("/assets/<int:asset_id>/simulation")
@login_required
def simulation(asset_id: int):
    """Scenarios side by side, the bottleneck in each, and a form to try another."""
    asset = _asset_or_404(asset_id)
    db = get_db()
    terminal = asset["terminal_type"]
    words = marine_sim.vocab(terminal)
    kept = marine_sim.scenarios(db, asset_id, terminal)
    results = []
    for sc in kept:
        results.append({**sc, "result": marine_sim.assess(asset_id, sc["params"], detail=False, terminal=terminal),
                        "changes": marine_sim.changes(kept[0]["params"], sc["params"], terminal) if sc is not kept[0] else []})
    try:
        shown_id = int(request.args.get("show") or results[-1]["id"])
    except ValueError:
        shown_id = results[-1]["id"]
    shown = next((r for r in results if r["id"] == shown_id), results[-1])
    detail = marine_sim.assess(asset_id, shown["params"], terminal=terminal)
    editing = next((r for r in results if str(r["id"]) == request.args.get("edit")), None)
    copying = next((r for r in results if str(r["id"]) == request.args.get("copy")), None)
    form = (editing or copying or shown)["params"]
    groups: dict[str, list] = {}
    for key, _, _, _, lo, hi, step, group in marine_sim.PARAMS:
        label, unit = words["labels"][key]
        groups.setdefault(group, []).append({"key": key, "label": label, "unit": unit, "min": lo, "max": hi,
                                             "step": step, "value": form[key]})
    return render_template("marine/simulation.html", asset=asset, results=results, shown=shown, detail=detail,
                           editing=editing, copying=copying, groups=groups, links=words["links"], words=words,
                           ships_chart=sim_ships(detail["timeline"], detail["params"]["berths"]),
                           gate_chart=sim_gate(detail["timeline"]), **_context())


@bp.post("/assets/<int:asset_id>/simulation")
@login_required
def save_scenario(asset_id: int):
    _asset_or_404(asset_id)
    name = (request.form.get("name") or "").strip()[:60] or "Scenario"
    try:
        scenario_id = int(request.form.get("scenario_id") or 0) or None
    except ValueError:
        scenario_id = None
    if scenario_id and query_one("SELECT 1 FROM marine_scenarios WHERE id = ? AND asset_id = ?", (scenario_id, asset_id)) is None:
        abort(404)
    saved = marine_sim.save(get_db(), asset_id, name, request.form.to_dict(), scenario_id, g.user["id"])
    get_db().commit()
    flash(f"{name} has been run.", "success")
    return redirect(url_for("marine.simulation", asset_id=asset_id, show=saved))


@bp.post("/assets/<int:asset_id>/simulation/<int:scenario_id>/delete")
@login_required
def delete_scenario(asset_id: int, scenario_id: int):
    first = query_one("SELECT MIN(id) AS id FROM marine_scenarios WHERE asset_id = ?", (asset_id,))
    if first and first["id"] == scenario_id:
        flash("The baseline stays: edit it instead.", "error")
    else:
        get_db().execute("DELETE FROM marine_scenarios WHERE id = ? AND asset_id = ?", (scenario_id, asset_id))
        get_db().commit()
    return redirect(url_for("marine.simulation", asset_id=asset_id))


@bp.get("/assets/<int:asset_id>/equipment")
@login_required
def equipment(asset_id: int):
    asset = _asset_or_404(asset_id)
    twin = marine.assess_asset(get_db(), asset)
    return render_template("marine/equipment.html", asset=asset, twin=twin,
                           upkeep=marine_facility.maintenance(asset), today_date=date.today(), **_context())


@bp.get("/assets/<int:asset_id>/environment")
@login_required
def environment(asset_id: int):
    asset = _asset_or_404(asset_id)
    now = datetime.now()
    alongside = any(s["eta"] <= now < s["etd"] for s in marine_ops.lineup(int(asset["id"]), now, asset["terminal_type"]))
    env = marine_facility.environment(asset, now, alongside)
    m = marine_facility.MEASURES
    outdoor = [s for s in env["stations"] if "pm25" in [r["key"] for r in s["measures"]]]
    charts = {
        "pm25": env_chart(env["timeline"], [(s["place"], f"{s['key']}_pm25") for s in outdoor], "pm25", "µg/m³",
                          [("WHO guideline 15", m["pm25"][2]), ("Interim target 37.5", m["pm25"][3])]),
        "co2": env_chart(env["timeline"], [(s["place"], f"{s['key']}_co2") for s in env["indoor"]], "co2", "ppm",
                         [("Alert 1,000", m["co2"][2]), ("Act 1,500", m["co2"][3])]),
    }
    return render_template("marine/environment.html", asset=asset, env=env, charts=charts, **_context())


@bp.get("/assets/<int:asset_id>/carbon")
@login_required
def carbon(asset_id: int):
    asset = _asset_or_404(asset_id)
    co2 = marine_facility.carbon(asset)
    return render_template("marine/carbon.html", asset=asset, co2=co2, chart=carbon_months(co2["months"]),
                           rules=marine_facility.compliance(asset), **_context())


@bp.get("/assets/<int:asset_id>/safety")
@login_required
def safety(asset_id: int):
    asset = _asset_or_404(asset_id)
    twin = marine.assess_asset(get_db(), asset)
    return render_template("marine/safety.html", asset=asset, safe=marine_facility.safety(asset, twin=twin), **_context())


@bp.get("/assets/<int:asset_id>/twin.json")
@login_required
def twin_json(asset_id: int):
    """What the 3D view colours: each element, where it is, and how it stands."""
    asset = _asset_or_404(asset_id)
    twin = marine.assess_asset(get_db(), asset)

    def finite(value):
        return value if value is None or math.isfinite(value) else None

    # The berth at work, for the scene: weather, tide, the ship alongside and the equipment.
    now = datetime.now()
    weather = marine_ops.metocean(asset_id, now, hours_back=0, hours_ahead=24)
    ships = marine_ops.lineup(asset_id, now, asset["terminal_type"])
    alongside = next((s for s in ships if s["eta"] <= now < s["etd"]), None)
    equipment = marine_ops.cranes(asset_id, now, weather[0]["gust"], asset["terminal_type"])
    return jsonify({
        "asset": {"id": asset["id"], "name": asset["name"], "kind": asset["kind"],
                  "terminal": asset["terminal_type"], "latitude": asset["latitude"], "longitude": asset["longitude"],
                  "rotation": asset["rotation"], "msl_cd": asset["msl_cd"], "location": asset["location"]},
        "now": {"at": now.isoformat(timespec="minutes"), "wind": weather[0]["wind"], "gust": weather[0]["gust"],
                "hs": weather[0]["hs"], "tide": weather[0]["tide"],
                "tides": [{"at": w["at"].isoformat(timespec="minutes"), "tide": w["tide"]} for w in weather],
                "source": "simulated"},
        "alongside": {"name": alongside["name"], "type": alongside["type"], "loa": alongside["loa"],
                      "beam": alongside["beam"], "draught": alongside["draught"]} if alongside else None,
        "next_ship": next(({"name": s["name"], "type": s["type"], "eta": s["eta"].isoformat(timespec="minutes"),
                            "loa": s["loa"], "beam": s["beam"], "draught": s["draught"]}
                           for s in ships if s["eta"] > now), None),
        "equipment": [{"name": c["name"], "state": c["state"]} for c in equipment],
        "model": url_for("marine.model", asset_id=asset_id) if asset["model_file"] else None,
        **_shapes_links(asset, twin["elements"]),
        "model_kind": MODEL_TYPES.get(Path(asset["model_file"]).suffix.lower(), ""),
        "elements": [{
            "id": e["element"]["id"], "name": e["element"]["name"], "kind": e["element"]["kind"],
            "material": e["element"]["material"], "zone": e["element"]["zone"],
            "ref": e["element"]["model_ref"] or e["element"]["name"],
            "x": e["element"]["x"], "y": e["element"]["y"], "z": e["element"]["z"],
            "state": e["state"], "health": e["health"], "design_ur": e["design_ur"],
            "ur_at_life": finite(e["ur_at_life"]),
            "href": url_for("marine.element", asset_id=asset_id, element_id=e["element"]["id"]),
            "sensors": [{"label": s["label"], "headline": s["headline"], "state": s["state"]} for s in e["sensors"]],
        } for e in twin["elements"]],
    })


@bp.post("/assets/<int:asset_id>/settings")
@login_required
def save_asset(asset_id: int):
    asset = _asset_or_404(asset_id)
    link = (request.form.get("triton") or "").strip()
    project_id, _, section_id = link.partition(":")
    lat, lon = _number("latitude"), _number("longitude")
    if lat is not None and lon is not None and -90 <= lat <= 90 and -180 <= lon <= 180:
        get_db().execute("UPDATE marine_assets SET latitude = ?, longitude = ? WHERE id = ?", (lat, lon, asset_id))
    elif not (request.form.get("latitude") or "").strip() and "latitude" in request.form:
        get_db().execute("UPDATE marine_assets SET latitude = NULL, longitude = NULL WHERE id = ?", (asset_id,))
    get_db().execute("UPDATE marine_assets SET terminal_type = ?, rotation = ?, msl_cd = ? WHERE id = ?",
                     (_choice("terminal_type", marine.TERMINAL_TYPES, asset["terminal_type"]),
                      _number("rotation", asset["rotation"]) % 360, _number("msl_cd", asset["msl_cd"]), asset_id))
    get_db().execute(
        "UPDATE marine_assets SET name = ?, kind = ?, location = ?, client = ?, commissioned = ?, design_life = ?,"
        " corrosion_code = ?, triton_project = ?, triton_section = ? WHERE id = ?",
        ((request.form.get("name") or asset["name"]).strip(), _choice("kind", marine.ASSET_KINDS, asset["kind"]),
         (request.form.get("location") or "").strip(), (request.form.get("client") or "").strip(),
         _day_field("commissioned", asset["commissioned"]), int(_number("design_life", asset["design_life"])),
         request.form.get("corrosion_code") if request.form.get("corrosion_code") in ("bs6349", "en1993_5")
         else asset["corrosion_code"], project_id, section_id, asset_id))
    get_db().commit()
    flash("Saved.", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="details"))


@bp.post("/assets/<int:asset_id>/delete")
@login_required
def delete_asset(asset_id: int):
    asset = _asset_or_404(asset_id)
    if not _may_remove(asset):
        abort(403)
    if asset["model_file"]:
        (models_dir() / asset["model_file"]).unlink(missing_ok=True)
    get_db().execute("DELETE FROM marine_assets WHERE id = ?", (asset_id,))
    get_db().commit()
    flash(f"{asset['name']} and all its readings were deleted.", "success")
    return redirect(url_for("marine.index"))


@bp.post("/assets/<int:asset_id>/refresh")
@login_required
def refresh(asset_id: int):
    _asset_or_404(asset_id)
    written = marine.refresh_simulated(get_db(), asset_id)
    get_db().commit()
    flash(f"Simulated sensors brought up to today ({written:,} readings).", "success")
    return redirect(url_for("marine.asset", asset_id=asset_id))


@bp.post("/assets/<int:asset_id>/readings")
@login_required
def import_readings(asset_id: int):
    _asset_or_404(asset_id)
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Choose a CSV file of readings.", "error")
        return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="readings"))
    text = upload.read().decode("utf-8", errors="replace")
    result = marine.import_csv(get_db(), asset_id, text)
    get_db().commit()
    if result["written"]:
        flash(f"{result['written']:,} readings imported for {result['sensors']} sensors.", "success")
    for problem in result["problems"]:
        flash(problem, "error")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="readings"))


@bp.get("/assets/<int:asset_id>/readings.csv")
@login_required
def export_readings(asset_id: int):
    """Every reading on the asset, in the same columns the import reads."""
    _asset_or_404(asset_id)
    rows = query(
        "SELECT s.label, r.at, r.value, r.note FROM marine_readings r JOIN marine_sensors s ON s.id = r.sensor_id"
        " JOIN marine_elements e ON e.id = s.element_id WHERE e.asset_id = ? ORDER BY s.label, r.at", (asset_id,))
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["sensor", "at", "value", "note"])
    writer.writerows([r["label"], r["at"], r["value"], r["note"]] for r in rows)
    body = out.getvalue()
    return Response(body, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=marinetwin-{asset_id}-readings.csv"})


# --- the Revit model ----------------------------------------------------------------

@bp.post("/assets/<int:asset_id>/model")
@login_required
def upload_model(asset_id: int):
    asset = _asset_or_404(asset_id)
    upload = request.files.get("model")
    suffix = Path(upload.filename).suffix.lower() if upload and upload.filename else ""
    if suffix not in MODEL_TYPES:
        flash("Upload the Revit model exported as IFC (.ifc) or glTF (.glb, .gltf).", "error")
        return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))
    stored = f"asset-{asset_id}{suffix}"
    target = models_dir() / stored
    upload.save(target)
    if target.stat().st_size > MODEL_LIMIT:
        target.unlink(missing_ok=True)
        flash("That model is over 200 MB. Export only the structure's own elements and try again.", "error")
        return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))
    if asset["model_file"] and asset["model_file"] != stored:
        (models_dir() / asset["model_file"]).unlink(missing_ok=True)
    get_db().execute("UPDATE marine_assets SET model_file = ?, model_name = ? WHERE id = ?",
                     (stored, upload.filename, asset_id))
    message = f"{upload.filename} is the model now. Elements are matched to it by their model reference."
    _found_path(asset_id).unlink(missing_ok=True)
    _forget_shapes(asset_id)
    if suffix == ".ifc":
        try:
            found = marine_ifc.read_file(target)
        except Exception:                             # noqa: BLE001 - an IFC we cannot read is still drawn
            current_app.logger.exception("Reading the IFC model failed for asset %s", asset_id)
            found = None
        if found is not None:
            _found_path(asset_id).write_text(json.dumps(found), encoding="utf-8")
            took = marine.apply_site(get_db(), asset_id, found)
            new = _new_in_model(asset_id, found)
            if took:
                message += " From the model MarineTwin took " + "; ".join(took) + "."
            if new:
                message += f" It also has {len(new)} element{'s' if len(new) > 1 else ''} MarineTwin does not track yet: import them below."
    get_db().commit()
    flash(message, "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))


def _found_path(asset_id: int) -> Path:
    return models_dir() / f"asset-{asset_id}.found.json"


def _model_found(asset_id: int) -> dict | None:
    path = _found_path(asset_id)
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except (OSError, ValueError):
        return None


def _new_in_model(asset_id: int, found: dict) -> list[dict]:
    have = {r["name"] for r in query("SELECT name FROM marine_elements WHERE asset_id = ?", (asset_id,))}
    new = {}
    for e in found.get("elements", []):
        if e["name"] not in have:
            new.setdefault(e["name"], e)
    return sorted(new.values(), key=lambda e: (e["kind"], e["name"]))


@bp.post("/assets/<int:asset_id>/model/import")
@login_required
def import_model_elements(asset_id: int):
    _asset_or_404(asset_id)
    found = _model_found(asset_id)
    if not found:
        flash("Upload the IFC model first.", "error")
        return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))
    kinds = request.form.getlist("kinds")
    if kinds:
        chosen = [e["name"] for e in _new_in_model(asset_id, found) if e["kind"] in kinds]
    else:
        chosen = request.form.getlist("names") or None
    try:
        done = marine.import_elements(get_db(), asset_id, found, chosen)
        get_db().commit()
    except Exception as exc:  # noqa: BLE001 - a model MarineTwin cannot take says why, not a server error
        get_db().rollback()
        current_app.logger.exception("Importing the model's elements failed for asset %s", asset_id)
        flash(f"The elements could not be imported ({type(exc).__name__}: {str(exc)[:200]}). Nothing was changed.", "error")
        return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))
    words = []
    if done["made"]:
        words.append(f"{len(done['made'])} element{'s' if len(done['made']) > 1 else ''} imported from the model, with their usual sensors")
    if done["linked"]:
        words.append(f"{len(done['linked'])} existing element{'s' if len(done['linked']) > 1 else ''} now matched by GlobalId")
    flash((". ".join(words) or "Nothing new to import") + ".", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))


@bp.get("/assets/<int:asset_id>/model")
@login_required
def model(asset_id: int):
    asset = _asset_or_404(asset_id)
    path = models_dir() / asset["model_file"] if asset["model_file"] else None
    if path is None or not path.exists():
        abort(404)
    return send_file(path, download_name=asset["model_name"] or path.name, max_age=0)


# The 3D view reads a Revit IFC in the browser, which takes a while for a big model. It then keeps
# the shapes it built here, so the next visit opens in seconds. They are kept per model and per set
# of tracked elements (each tracked element is a shape of its own): change either and they are
# built again.

def _shapes_key(asset, elements) -> str:
    path = models_dir() / asset["model_file"]
    refs = sorted({str(e["element"]["model_ref"] or e["element"]["name"]).strip().lower() for e in elements}
                  | {str(e["element"]["name"]).strip().lower() for e in elements})
    seed = f"{asset['model_file']}|{path.stat().st_size if path.exists() else 0}|{path.stat().st_mtime_ns if path.exists() else 0}|" + "\n".join(refs)
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _shapes_path(asset_id: int, key: str) -> Path:
    return models_dir() / f"asset-{asset_id}.{key}.shapes"


def _forget_shapes(asset_id: int, keep: str | None = None) -> None:
    for old in models_dir().glob(f"asset-{asset_id}.*.shapes"):
        if keep is None or old.name != _shapes_path(asset_id, keep).name:
            old.unlink(missing_ok=True)


def _shapes_links(asset, elements) -> dict:
    if MODEL_TYPES.get(Path(asset["model_file"] or "").suffix.lower()) != "ifc":
        return {}
    key = _shapes_key(asset, elements)
    url = url_for("marine.model_shapes", asset_id=asset["id"], key=key)
    kept = _shapes_path(asset["id"], key).exists()
    return {"model_shapes": url if kept else None, "model_shapes_save": None if kept else url}


@bp.get("/assets/<int:asset_id>/model/shapes/<key>")
@login_required
def model_shapes(asset_id: int, key: str):
    _asset_or_404(asset_id)
    path = _shapes_path(asset_id, key) if key.isalnum() else None
    if path is None or not path.exists():
        abort(404)
    return send_file(path, mimetype="application/octet-stream", max_age=0)


@bp.post("/assets/<int:asset_id>/model/shapes/<key>")
@login_required
def keep_model_shapes(asset_id: int, key: str):
    asset = _asset_or_404(asset_id)
    if not asset["model_file"] or key != _shapes_key(asset, marine.assess_asset(get_db(), asset)["elements"]):
        return jsonify(kept=False, why="the model or its elements changed"), 409
    if (request.content_length or 0) > SHAPES_LIMIT:
        return jsonify(kept=False, why="too big"), 413
    target = _shapes_path(asset_id, key)
    partial = target.with_suffix(".part")
    size = 0
    with partial.open("wb") as out:                   # streamed: a big model's shapes never sit in memory
        while chunk := request.stream.read(1 << 20):
            if size == 0 and chunk[:2] != b"\x1f\x8b":
                break
            size += len(chunk)
            if size > SHAPES_LIMIT:
                break
            out.write(chunk)
    if size == 0 or size > SHAPES_LIMIT:
        partial.unlink(missing_ok=True)
        return jsonify(kept=False, why="not gzipped shapes" if size == 0 else "too big"), 400
    partial.replace(target)
    _forget_shapes(asset_id, keep=key)
    return jsonify(kept=True, bytes=size)


@bp.post("/assets/<int:asset_id>/model/delete")
@login_required
def delete_model(asset_id: int):
    asset = _asset_or_404(asset_id)
    if asset["model_file"]:
        (models_dir() / asset["model_file"]).unlink(missing_ok=True)
    _found_path(asset_id).unlink(missing_ok=True)
    _forget_shapes(asset_id)
    get_db().execute("UPDATE marine_assets SET model_file = '', model_name = '' WHERE id = ?", (asset_id,))
    get_db().commit()
    flash("The model was removed; the view draws the schematic again.", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))


# --- elements and sensors -----------------------------------------------------------

@bp.post("/assets/<int:asset_id>/elements")
@login_required
def add_element(asset_id: int):
    _asset_or_404(asset_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Give the element a name, as it is called in Triton or on the drawings.", "error")
        return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="add-an-element"))
    if query_one("SELECT 1 FROM marine_elements WHERE asset_id = ? AND name = ?", (asset_id, name)):
        flash(f"There is already an element called {name} on this asset.", "error")
        return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="add-an-element"))
    db = get_db()
    element_id = db.execute(
        "INSERT INTO marine_elements (asset_id, name, kind, material, zone, wall_mm, design_ur, triton_element,"
        " model_ref, x, y, z) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (asset_id, name, _choice("kind", marine.ELEMENT_KINDS, "pile"), _choice("material", marine.MATERIALS, "steel"),
         _choice("zone", marine.ZONES, "splash"), _number("wall_mm"), _number("design_ur"),
         (request.form.get("triton_element") or "").strip(), (request.form.get("model_ref") or "").strip(),
         _number("x", 0.0), _number("y", 0.0), _number("z", 0.0))).lastrowid
    kind = _choice("kind", marine.ELEMENT_KINDS, "pile")
    chosen = request.form.getlist("sensors")
    if request.form.get("suggested"):
        chosen = marine.suggested(kind) + chosen
    for sensor_kind in dict.fromkeys(chosen):
        spec = marine.SENSOR_KINDS.get(sensor_kind)
        if spec:
            # P01-SG1, F2-FR1. Limits left empty follow the kind's defaults, or Triton's ratings.
            db.execute("INSERT INTO marine_sensors (element_id, kind, label, simulated) VALUES (?, ?, ?, 1)",
                       (element_id, sensor_kind, f"{name}-{spec['tag']}1"))
    marine.refresh_simulated(db, asset_id)
    db.commit()
    flash(f"{name} added.", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="add-an-element"))


@bp.post("/assets/<int:asset_id>/elements/<int:element_id>/delete")
@login_required
def delete_element(asset_id: int, element_id: int):
    element = _element_or_404(asset_id, element_id)
    get_db().execute("DELETE FROM marine_elements WHERE id = ?", (element_id,))
    get_db().commit()
    flash(f"{element['name']} and its sensors were removed.", "success")
    return redirect(url_for("marine.asset", asset_id=asset_id))


@bp.get("/assets/<int:asset_id>/elements/<int:element_id>")
@login_required
def element(asset_id: int, element_id: int):
    asset = _asset_or_404(asset_id)
    element = _element_or_404(asset_id, element_id)
    db = get_db()
    twin = marine.assess_asset(db, asset)
    mine = next(e for e in twin["elements"] if e["element"]["id"] == element_id)
    readings = marine.readings_for(db, [s["id"] for s in mine["sensors"]])
    life = int(twin["durability"]["life"])
    charts = {s["id"]: sensor_trend(s, readings[s["id"]], asset, life) for s in mine["sensors"]}
    history = {s["id"]: [r for r in readings[s["id"]] if not s["simulated"] or r["note"]]
               for s in mine["sensors"] if s["kind"] == "inspection"}
    return render_template("marine/element.html", asset=asset, element=element, twin=twin, mine=mine,
                           charts=charts, life=life, history=history, grade_name=dict(marine.GRADES), **_context())


@bp.post("/assets/<int:asset_id>/elements/<int:element_id>/edit")
@login_required
def edit_element(asset_id: int, element_id: int):
    element = _element_or_404(asset_id, element_id)
    get_db().execute(
        "UPDATE marine_elements SET kind = ?, material = ?, zone = ?, wall_mm = ?, design_ur = ?, triton_element = ?,"
        " model_ref = ?, x = ?, y = ?, z = ? WHERE id = ?",
        (_choice("kind", marine.ELEMENT_KINDS, element["kind"]), _choice("material", marine.MATERIALS, element["material"]),
         _choice("zone", marine.ZONES, element["zone"]), _number("wall_mm"), _number("design_ur"),
         (request.form.get("triton_element") or "").strip(), (request.form.get("model_ref") or "").strip(),
         _number("x", element["x"]), _number("y", element["y"]), _number("z", element["z"]), element_id))
    get_db().commit()
    flash("Saved.", "success")
    return redirect(url_for("marine.element", asset_id=asset_id, element_id=element_id))


@bp.post("/assets/<int:asset_id>/elements/<int:element_id>/sensors")
@login_required
def add_sensor(asset_id: int, element_id: int):
    element = _element_or_404(asset_id, element_id)
    kind = request.form.get("kind")
    if kind not in marine.SENSOR_KINDS:
        abort(400)
    tag = marine.SENSOR_KINDS[kind]["tag"]
    taken = {r["label"] for r in query("SELECT label FROM marine_sensors WHERE element_id = ?", (element_id,))}
    label = (request.form.get("label") or "").strip() or next(
        f"{element['name']}-{tag}{n}" for n in range(1, 100) if f"{element['name']}-{tag}{n}" not in taken)
    get_db().execute(
        "INSERT INTO marine_sensors (element_id, kind, label, alert, alarm, simulated) VALUES (?, ?, ?, ?, ?, ?)",
        (element_id, kind, label, _number("alert"), _number("alarm"), 1 if request.form.get("simulated") else 0))
    marine.refresh_simulated(get_db(), asset_id)
    get_db().commit()
    flash(f"{label} added.", "success")
    return redirect(url_for("marine.element", asset_id=asset_id, element_id=element_id))


@bp.post("/assets/<int:asset_id>/elements/<int:element_id>/inspection")
@login_required
def record_inspection(asset_id: int, element_id: int):
    """What an inspector found: a grade from 1 (as new) to 5 (failed), and a note."""
    element = _element_or_404(asset_id, element_id)
    try:
        grade = int(request.form.get("grade") or 0)
    except ValueError:
        grade = 0
    if grade not in dict(marine.GRADES):
        flash("Pick a grade from 1 to 5.", "error")
        return redirect(url_for("marine.element", asset_id=asset_id, element_id=element_id))
    at = _day_field("at", date.today().isoformat())
    marine.record_inspection(get_db(), element, at, grade, request.form.get("note") or "")
    get_db().commit()
    flash(f"Inspection of {element['name']} recorded: grade {grade}, {dict(marine.GRADES)[grade].lower()}.", "success")
    return redirect(url_for("marine.element", asset_id=asset_id, element_id=element_id))


@bp.post("/assets/<int:asset_id>/sensors/<int:sensor_id>/delete")
@login_required
def delete_sensor(asset_id: int, sensor_id: int):
    sensor = query_one("SELECT s.*, e.id AS element_id FROM marine_sensors s JOIN marine_elements e"
                       " ON e.id = s.element_id WHERE s.id = ? AND e.asset_id = ?", (sensor_id, asset_id))
    if sensor is None:
        abort(404)
    get_db().execute("DELETE FROM marine_sensors WHERE id = ?", (sensor_id,))
    get_db().commit()
    flash(f"{sensor['label']} and its readings were removed.", "success")
    return redirect(url_for("marine.element", asset_id=asset_id, element_id=sensor["element_id"]))
