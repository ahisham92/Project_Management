"""MarineTwin's pages: the assets, one asset's twin, and one element's sensors.

The calculations live in ``marine`` (condition, projection, advice) and in
Triton (the design it is judged against, through ``marine_triton``); these views
only gather and show them. Every page is behind the site's one sign-in and the
``marinetwin`` program the administrator gives an account.
"""

from __future__ import annotations

import csv
import io
import math
from datetime import date, datetime
from pathlib import Path

from flask import (
    Blueprint, Response, abort, flash, g, jsonify, redirect, render_template, request, send_file, url_for,
)

from .. import marine, marine_triton
from ..auth import login_required
from ..db import data_dir, get_db, query, query_one
from ..marine_charts import sensor_trend

bp = Blueprint("marine", __name__, url_prefix="/marinetwin")

# What the 3D view can open: a Revit model exported as IFC, or as glTF / GLB.
MODEL_TYPES = {".ifc": "ifc", ".glb": "glb", ".gltf": "gltf"}
MODEL_LIMIT = 200 * 1024 * 1024


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
        "suggested": marine.SUGGESTED,
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
    return render_template("marine/index.html", assets=assets, totals=totals,
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
    return redirect(url_for("marine.asset", asset_id=asset_id))


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
    asset = _asset_or_404(asset_id)
    twin = marine.assess_asset(get_db(), asset)
    return render_template("marine/asset.html", asset=asset, twin=twin, may_remove=_may_remove(asset),
                           triton_projects=marine_triton.projects(),
                           model_kind=MODEL_TYPES.get(Path(asset["model_file"]).suffix.lower(), ""),
                           **_context())


@bp.get("/assets/<int:asset_id>/twin.json")
@login_required
def twin_json(asset_id: int):
    """What the 3D view colours: each element, where it is, and how it stands."""
    asset = _asset_or_404(asset_id)
    twin = marine.assess_asset(get_db(), asset)

    def finite(value):
        return value if value is None or math.isfinite(value) else None

    return jsonify({
        "asset": {"id": asset["id"], "name": asset["name"], "kind": asset["kind"]},
        "model": url_for("marine.model", asset_id=asset_id) if asset["model_file"] else None,
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
    return redirect(url_for("marine.asset", asset_id=asset_id))


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
        return redirect(url_for("marine.asset", asset_id=asset_id))
    text = upload.read().decode("utf-8", errors="replace")
    result = marine.import_csv(get_db(), asset_id, text)
    get_db().commit()
    if result["written"]:
        flash(f"{result['written']:,} readings imported for {result['sensors']} sensors.", "success")
    for problem in result["problems"]:
        flash(problem, "error")
    return redirect(url_for("marine.asset", asset_id=asset_id))


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
        return redirect(url_for("marine.asset", asset_id=asset_id))
    stored = f"asset-{asset_id}{suffix}"
    target = models_dir() / stored
    upload.save(target)
    if target.stat().st_size > MODEL_LIMIT:
        target.unlink(missing_ok=True)
        flash("That model is over 200 MB. Export only the structure's own elements and try again.", "error")
        return redirect(url_for("marine.asset", asset_id=asset_id))
    if asset["model_file"] and asset["model_file"] != stored:
        (models_dir() / asset["model_file"]).unlink(missing_ok=True)
    get_db().execute("UPDATE marine_assets SET model_file = ?, model_name = ? WHERE id = ?",
                     (stored, upload.filename, asset_id))
    get_db().commit()
    flash(f"{upload.filename} is the model now. Elements are matched to it by their model reference.", "success")
    return redirect(url_for("marine.asset", asset_id=asset_id))


@bp.get("/assets/<int:asset_id>/model")
@login_required
def model(asset_id: int):
    asset = _asset_or_404(asset_id)
    path = models_dir() / asset["model_file"] if asset["model_file"] else None
    if path is None or not path.exists():
        abort(404)
    return send_file(path, download_name=asset["model_name"] or path.name, max_age=0)


@bp.post("/assets/<int:asset_id>/model/delete")
@login_required
def delete_model(asset_id: int):
    asset = _asset_or_404(asset_id)
    if asset["model_file"]:
        (models_dir() / asset["model_file"]).unlink(missing_ok=True)
    get_db().execute("UPDATE marine_assets SET model_file = '', model_name = '' WHERE id = ?", (asset_id,))
    get_db().commit()
    flash("The model was removed; the view draws the schematic again.", "success")
    return redirect(url_for("marine.asset", asset_id=asset_id))


# --- elements and sensors -----------------------------------------------------------

@bp.post("/assets/<int:asset_id>/elements")
@login_required
def add_element(asset_id: int):
    _asset_or_404(asset_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Give the element a name, as it is called in Triton or on the drawings.", "error")
        return redirect(url_for("marine.asset", asset_id=asset_id))
    if query_one("SELECT 1 FROM marine_elements WHERE asset_id = ? AND name = ?", (asset_id, name)):
        flash(f"There is already an element called {name} on this asset.", "error")
        return redirect(url_for("marine.asset", asset_id=asset_id))
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
    return redirect(url_for("marine.asset", asset_id=asset_id))


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
