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
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import (
    Blueprint, Response, abort, current_app, flash, g, jsonify, redirect, render_template, request, send_file, session,
    url_for,
)

from .. import (
    marine, marine_facility, marine_feed, marine_ifc, marine_inputs, marine_life, marine_ops, marine_plan, marine_risk, marine_sim,
    marine_triton, marine_value, marine_versions, marine_berths,
)
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

# Every change to an asset is kept in its history, in these words. Views missing here change nothing worth keeping.
CHANGES = {
    "save_scenario": "Saved a simulation scenario", "delete_scenario": "Deleted a simulation scenario",
    "save_berth_use": "Set a berth's use", "save_asset": "Changed the asset's details",
    "refresh": "Brought the simulated sensors up to date", "import_readings": "Imported readings from a CSV",
    "upload_model": "Uploaded the Revit model", "import_model_elements": "Imported elements from the model",
    "trim_sensors": "Kept sensors on one element per design", "remove_orphans": "Removed elements no longer in the model",
    "delete_model": "Removed the model",
    "add_element": "Added an element", "delete_element": "Removed an element", "delete_elements": "Removed all elements",
    "edit_element": "Changed an element", "add_sensor": "Added a sensor", "record_inspection": "Recorded an inspection",
    "delete_sensor": "Removed a sensor", "calibrate_sensor": "Calibrated a sensor",
    "acknowledge_alarm": "Acknowledged an alarm", "renew_feed_key": "Renewed the logger key", "reset_fake_feed": "Reset the fake logger",
}


@bp.after_request
def _keep_history(response):
    """Note who changed an asset, what, and what came of it, once the change went through."""
    action = CHANGES.get((request.endpoint or "").rsplit(".", 1)[-1])
    asset_id = (request.view_args or {}).get("asset_id")
    if request.method != "POST" or not action or asset_id is None or response.status_code >= 400 or not g.get("user"):
        return response
    try:
        db = get_db()
        if db.execute("SELECT 1 FROM marine_assets WHERE id = ?", (asset_id,)).fetchone() is None:
            return response                          # the asset itself went
        said = [m for c, m in session.get("_flashes", []) if c != "error"]
        if len(said) < len(session.get("_flashes", [])):
            return response                          # it said it could not: nothing changed
        what = request.form.get("name") or ""
        if request.endpoint.endswith(("element", "sensor", "inspection")) and "element_id" in request.view_args:
            row = db.execute("SELECT name FROM marine_elements WHERE id = ?", (request.view_args["element_id"],)).fetchone()
            what = row["name"] if row else what
        db.execute("INSERT INTO marine_changes (asset_id, user_id, action, detail) VALUES (?, ?, ?, ?)",
                   (asset_id, g.user["id"], action + (f": {what}" if what else ""), (said[-1] if said else "")[:400]))
        db.commit()
    except Exception:                                 # noqa: BLE001 - history must never break the change itself
        current_app.logger.exception("Keeping the history of asset %s failed", asset_id)
    return response


def history(asset_id: int, limit: int = 40) -> list:
    return query("SELECT c.*, u.name AS who FROM marine_changes c LEFT JOIN users u ON u.id = c.user_id"
                 " WHERE c.asset_id = ? ORDER BY c.id DESC LIMIT ?", (asset_id, limit))


# What the 3D view can open: a Revit model exported as IFC, or as glTF / GLB.
MODEL_TYPES = {".ifc": "ifc", ".glb": "glb", ".gltf": "gltf"}
MODEL_LIMIT = 200 * 1024 * 1024
SHAPES_LIMIT = 600 * 1024 * 1024
FEED_LIMIT = 4 * 1024 * 1024                         # one logger delivery


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
    db = get_db()
    twin = marine.assess_asset(db, asset)
    marine.sync_alarms(db, asset_id, twin)
    db.commit()
    return render_template("marine/asset.html", asset=asset, twin=twin, alarms=marine.alarms(db, asset_id), **_context())


def _check_alarms(asset_id: int) -> None:
    """After new real readings: open or close the asset's alarms now, not when someone next looks."""
    db = get_db()
    asset = db.execute("SELECT * FROM marine_assets WHERE id = ?", (asset_id,)).fetchone()
    marine.sync_alarms(db, asset_id, marine.assess_asset(db, asset))


@bp.post("/assets/<int:asset_id>/alarms/<int:alarm_id>/ack")
@login_required
def acknowledge_alarm(asset_id: int, alarm_id: int):
    _asset_or_404(asset_id)
    db = get_db()
    alarm = db.execute("SELECT * FROM marine_alarms WHERE id = ? AND asset_id = ?", (alarm_id, asset_id)).fetchone()
    if alarm is None:
        abort(404)
    note = (request.form.get("note") or "").strip()[:300]
    db.execute("UPDATE marine_alarms SET acked_by = ?, acked_at = datetime('now'), ack_note = ? WHERE id = ?",
               (g.user["id"], note, alarm_id))
    db.commit()
    flash(f"{alarm['label']}: acknowledged" + (f" ({note})" if note else "") + ".", "success")
    return redirect(url_for("marine.asset", asset_id=asset_id, _anchor="alarms"))


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
                           triton_projects=marine_triton.projects(), changes=history(asset_id),
                           versions=marine_versions.versions(get_db(), asset_id),
                           orphans=marine_versions.orphans(get_db(), asset_id, found),
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
    plan = marine_ops.live(asset_id, now, asset["terminal_type"], scenario=request.args.get("scenario", "normal"),
                           booked=_main_berth_calls(asset, now), fleet=marine_berths.crane_fleet(get_db(), asset_id))
    iso = lambda at: at.isoformat(timespec="minutes")  # noqa: E731
    return jsonify({
        "start": iso(plan["start"]), "now": iso(now), "equipment_name": plan["equipment_name"], "units": plan["units"], "limits": plan["limits"],
        "scenario": plan["scenario"],
        "scenarios": [{"key": k, "name": n, "words": w} for k, n, w in marine_ops.SCENARIOS],
        "hours": [{**h, "at": iso(h["at"])} for h in plan["hours"]],
        "calls": [{**c, "eta": iso(c["eta"]), "etd": iso(c["etd"])} for c in plan["calls"]],
        "events": [{**e, "at": iso(e["at"])} for e in plan["events"]],
    })


# --- who berths where ---------------------------------------------------------------------

def _berth_setup(asset):
    """The berths, the ship calls (and whether they are the person's), and the week they start."""
    db = get_db()
    elements = [dict(e) for e in _life_elements(int(asset["id"]))]
    stoppers = sum(1 for e in elements if e["kind"] == "crane_stopper")
    the_berths = marine_berths.berths(db, asset, marine_risk.berth_length(elements), stoppers)
    start = marine_berths.week_start(datetime.now())
    the_calls, own = marine_berths.calls(db, asset, the_berths, start)
    if own and the_calls:
        start = marine_berths.week_start(min(c["eta"] for c in the_calls))
    return the_berths, the_calls, own, start


def _call_json(c: dict) -> dict:
    iso = lambda at: at.isoformat(timespec="minutes") if isinstance(at, datetime) else at  # noqa: E731
    return {k: iso(v) for k, v in c.items() if not k.startswith("_")} | {"flag_name": marine_berths.flag_name(c.get("flag"))}


def _main_berth_calls(asset, now: datetime) -> list[dict] | None:
    """The person's own ship calls given to the live port's berth, for its line-up (none: the simulated one)."""
    the_berths, the_calls, own, start = _berth_setup(asset)
    main = next((b["n"] for b in the_berths if b.get("main")), None)
    if not own or main is None:
        return None
    plan = marine_berths.allocate(the_berths, the_calls, "windows", start)
    out = []
    for c in plan["placed"]:
        if main in c["berths"] and c["end"] > now - timedelta(hours=12) and c["begin"] < now + timedelta(hours=72):
            out.append({"name": c["ship"], "type": c["type"], "loa": c["loa"], "beam": c["beam"] or round(c["loa"] / 7.2, 1),
                        "draught": c["draught"], "displacement": (c["dwt"] or c["loa"] * 300) * 1.3, "windage": 30,
                        "eta": c["begin"], "etd": c["end"], "moves": c["moves"], "flag": c["flag"], "line": c["line"]})
    return out[:6] or None


@bp.get("/assets/<int:asset_id>/berthplan")
@login_required
def berthplan(asset_id: int):
    """Who berths where: the berths, the week's ships on a radar and a timeline, and the rule that places them."""
    asset = _asset_or_404(asset_id)
    the_berths, the_calls, own, start = _berth_setup(asset)
    policy = request.args.get("policy", "windows")
    every = marine_berths.compare(the_berths, the_calls, start)
    plan = every.get(policy) or every["windows"]
    best = min(every.values(), key=lambda r: (len(r["unplaced"]), r["wait_total"]))
    return render_template("marine/berthplan.html", asset=asset, berths=the_berths, calls=the_calls, own=own, start=start,
                           plan=plan, every=every, best=best, policies=marine_berths.POLICIES,
                           uses=marine_berths.USES, crane_kinds=marine_berths.CRANE_KINDS, flag=marine_berths.flag_svg,
                           units=marine_ops.UNITS.get(asset["terminal_type"], "containers"),
                           ukc=marine_berths.UKC, margin=marine_berths.LENGTH_MARGIN, rates=marine_berths.RATE, **_context())


@bp.get("/assets/<int:asset_id>/berthplan.json")
@login_required
def berthplan_json(asset_id: int):
    """The plan for the radar: the berths, and each call with its berth, its times and why."""
    asset = _asset_or_404(asset_id)
    the_berths, the_calls, own, start = _berth_setup(asset)
    plan = marine_berths.allocate(the_berths, the_calls, request.args.get("policy", "windows"), start)
    return jsonify({"start": start.isoformat(timespec="minutes"), "horizon": plan["horizon"], "policy": plan["policy"],
                    "now_h": round((datetime.now() - start).total_seconds() / 3600, 2),
                    "berths": [{k: b[k] for k in ("n", "name", "length", "depth", "cranes", "crane_kind", "use")} | {"main": bool(b.get("main"))}
                               for b in the_berths],
                    "placed": [_call_json(c) for c in plan["placed"]],
                    "unplaced": [_call_json(c) for c in plan["unplaced"]],
                    "flags": {code: marine_berths.flag_svg(code, 30) for code in {c.get("flag") or "" for c in the_calls}}})


@bp.post("/assets/<int:asset_id>/berthplan/layout")
@login_required
def berth_layout(asset_id: int):
    """The berths the 3D view found along the quay, so the plan numbers them the same way."""
    asset = _asset_or_404(asset_id)
    found = (request.get_json(silent=True) or {}).get("berths")
    if not isinstance(found, list) or not found or len(found) > 200:
        return jsonify({"error": "No berths sent."}), 400
    written = marine_berths.save_layout(get_db(), asset, found)
    get_db().commit()
    return jsonify({"saved": written})


@bp.post("/assets/<int:asset_id>/berthplan/berths/<int:n>")
@login_required
def save_berth(asset_id: int, n: int):
    asset = _asset_or_404(asset_id)
    if not 0 < n <= 200:
        abort(404)
    the_berths, *_ = _berth_setup(asset)
    marine_berths.keep_estimate(get_db(), asset, the_berths)
    marine_berths.save_berth(get_db(), asset_id, n, request.form)
    get_db().commit()
    flash(f"Berth {n} saved.", "success")
    return redirect(url_for("marine.berthplan", asset_id=asset_id, policy=request.form.get("policy", "windows"), _anchor="berths"))


@bp.get("/assets/<int:asset_id>/ships")
@login_required
def ships(asset_id: int):
    """The ships calling: a typical week to start from, every figure the person's to change."""
    asset = _asset_or_404(asset_id)
    the_berths, the_calls, own, start = _berth_setup(asset)
    if the_calls and the_calls[0].get("id") is None:
        # Every ship in the typical week is there to be changed: keep it, so each has its own form.
        marine_berths.keep_typical(get_db(), asset_id, the_calls)
        get_db().commit()
        the_berths, the_calls, own, start = _berth_setup(asset)
    plan = marine_berths.allocate(the_berths, the_calls, "windows", start)
    where = {(c["ship"], c["eta"]): c for c in plan["placed"] + plan["unplaced"]}
    return render_template("marine/ships.html", asset=asset, calls=the_calls, own=own, start=start, where=where,
                           fields=marine_berths.FIELDS, flags=marine_berths.FLAGS, flag=marine_berths.flag_svg,
                           berths=the_berths, units=marine_ops.UNITS.get(asset["terminal_type"], "containers"), **_context())


def _own_calls(asset):
    """Before the first change the typical week becomes the person's, so a change keeps the rest."""
    the_berths, the_calls, own, start = _berth_setup(asset)
    if the_calls and the_calls[0].get("id") is None:
        marine_berths.keep_typical(get_db(), int(asset["id"]), the_calls)


@bp.post("/assets/<int:asset_id>/ships")
@login_required
def add_ship(asset_id: int):
    asset = _asset_or_404(asset_id)
    call, why = marine_berths.clean_call(request.form)
    if call is None:
        flash(why, "error")
        return redirect(url_for("marine.ships", asset_id=asset_id, _anchor="add"))
    _own_calls(asset)
    marine_berths.insert_call(get_db(), asset_id, call)
    get_db().commit()
    flash(f"{call['ship']} added.", "success")
    return redirect(url_for("marine.ships", asset_id=asset_id))


@bp.post("/assets/<int:asset_id>/ships/<int:call_id>")
@login_required
def edit_ship(asset_id: int, call_id: int):
    _asset_or_404(asset_id)
    if query_one("SELECT id FROM marine_calls WHERE id = ? AND asset_id = ?", (call_id, asset_id)) is None:
        abort(404)
    call, why = marine_berths.clean_call(request.form)
    if call is None:
        flash(why, "error")
        return redirect(url_for("marine.ships", asset_id=asset_id))
    get_db().execute("UPDATE marine_calls SET ship = ?, imo = ?, flag = ?, type = ?, line = ?, loa = ?, beam = ?, draught = ?, dwt = ?,"
                     " moves = ?, eta = ?, window = ?, wish = ?, notes = ?, source = 'user' WHERE id = ? AND asset_id = ?",
                     (call["ship"], call["imo"], call["flag"], call["type"], call["line"], call["loa"], call["beam"], call["draught"],
                      call["dwt"], call["moves"], call["eta"], call["window"], call["wish"], call["notes"], call_id, asset_id))
    get_db().commit()
    flash(f"{call['ship']} saved.", "success")
    return redirect(url_for("marine.ships", asset_id=asset_id))


@bp.post("/assets/<int:asset_id>/ships/<int:call_id>/delete")
@login_required
def delete_ship(asset_id: int, call_id: int):
    _asset_or_404(asset_id)
    get_db().execute("DELETE FROM marine_calls WHERE id = ? AND asset_id = ?", (call_id, asset_id))
    get_db().commit()
    flash("Ship call removed.", "success")
    return redirect(url_for("marine.ships", asset_id=asset_id))


@bp.post("/assets/<int:asset_id>/ships/import")
@login_required
def import_ships(asset_id: int):
    """Ship calls from a CSV (the port community system's, or the lines' schedules), replacing the list or added to it."""
    _asset_or_404(asset_id)
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Pick a CSV file.", "error")
        return redirect(url_for("marine.ships", asset_id=asset_id, _anchor="import"))
    text_ = upload.read(5_000_000).decode("utf-8-sig", errors="replace")
    good, bad = marine_berths.import_csv(text_)
    if not good:
        flash("No ship calls read. " + " ".join(bad[:3]), "error")
        return redirect(url_for("marine.ships", asset_id=asset_id, _anchor="import"))
    if request.form.get("replace"):
        get_db().execute("DELETE FROM marine_calls WHERE asset_id = ?", (asset_id,))
    else:
        _own_calls(_asset_or_404(asset_id))
    for call in good:
        marine_berths.insert_call(get_db(), asset_id, call, "csv")
    get_db().commit()
    flash(f"{len(good):,} ship calls read." + (f" {len(bad)} rows skipped: " + " ".join(bad[:3]) if bad else ""),
          "success" if not bad else "warning")
    return redirect(url_for("marine.ships", asset_id=asset_id))


@bp.get("/assets/<int:asset_id>/ships.csv")
@login_required
def ships_csv(asset_id: int):
    asset = _asset_or_404(asset_id)
    _, the_calls, _, _ = _berth_setup(asset)
    return Response(marine_berths.export_csv(the_calls), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="ship-calls-{asset_id}.csv"'})


@bp.post("/assets/<int:asset_id>/ships/reset")
@login_required
def reset_ships(asset_id: int):
    _asset_or_404(asset_id)
    get_db().execute("DELETE FROM marine_calls WHERE asset_id = ?", (asset_id,))
    get_db().commit()
    flash("Back to a typical week of ships.", "success")
    return redirect(url_for("marine.ships", asset_id=asset_id))


def _life_rates() -> dict:
    """What the person changed (rates, prices, lives and warranties, the risks included), from the
    query string (the page's forms) or a JSON body."""
    body = request.get_json(silent=True) if request.is_json else None
    given = body.get("rates") if isinstance(body, dict) else None
    source = given if isinstance(given, dict) else request.args
    keys = ("moves_per_day", "value_per_move", "rebuild_months", *marine_life.PRICES, *marine_life.DREDGE,
            *(f"life_{k}" for k in marine_life.KIND_INFO), *(f"warranty_{k}" for k in marine_life.KIND_INFO),
            *(f"risk_{k}" for k in marine_life.RISKS), "sea_level", "seismic", "war_year", "freeboard")
    # A ticked box sends its hidden 0 and then its 1: the last one is what was meant.
    last = (lambda k: (source.getlist(k) or [None])[-1]) if hasattr(source, "getlist") else source.get
    return {k: str(last(k))[:20] for k in keys if last(k) not in (None, "")}


def _given(asset_id: int) -> dict:
    """The inputs a page runs on: the set in use, with whatever the page's forms change for this run."""
    return {**marine_inputs.active(get_db(), asset_id), **_life_rates()}


@bp.app_template_global("marine_value")
def _value_for(asset) -> dict | None:
    """What MarineTwin is worth at this berth, for the strip under the steps (none when it cannot be worked out)."""
    try:
        return marine_value.summary(asset, _life_elements(int(asset["id"])), _given(int(asset["id"])))
    except Exception:  # noqa: BLE001 - the strip is a summary; the page itself must still open
        current_app.logger.exception("MarineTwin value for asset %s", asset["id"])
        return None


def _life_elements(asset_id: int):
    return query("SELECT name, kind, material, zone, model_ref, x, y, z FROM marine_elements WHERE asset_id = ?"
                 " ORDER BY x, name", (asset_id,))


@bp.get("/assets/<int:asset_id>/lifecycle")
@login_required
def lifecycle(asset_id: int):
    """The design life in a few minutes: doing nothing against fixing as you go, or deciding each issue."""
    asset = _asset_or_404(asset_id)
    given = _given(asset_id)
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
                           inputs_name=marine_inputs.active_name(get_db(), asset_id), **_context())


# --- the inputs and the extreme events -------------------------------------------------

@bp.get("/assets/<int:asset_id>/inputs")
@login_required
def inputs(asset_id: int):
    """The figures every page runs on, in named sets to duplicate and amend, each with its source."""
    asset = _asset_or_404(asset_id)
    terminal = asset["terminal_type"]
    kept = marine_inputs.sets(get_db(), asset_id)
    for one in kept:
        one["changes"] = marine_inputs.changes(one["values"], terminal)
    editing = next((s for s in kept if s["id"] and str(s["id"]) == request.args.get("edit")), None)
    copying = next((s for s in kept if str(s["id"]) == request.args.get("copy")), None)
    base = editing or copying or next(s for s in kept if s["active"])
    groups: dict[str, dict] = {}
    for f in marine_inputs.fields(terminal):
        value = base["values"].get(f["key"], f["default"])
        group = groups.setdefault(f["group"], {"plain": [], "subs": {}})
        one = {**f, "value": value, "changed": f["key"] in base["values"]}
        if f.get("sub"):
            group["subs"].setdefault(f["sub"], []).append(one)
        else:
            group["plain"].append(one)
    return render_template("marine/inputs.html", asset=asset, kept=kept, editing=editing, copying=copying, base=base,
                           groups=groups, **_context())


@bp.post("/assets/<int:asset_id>/inputs")
@login_required
def save_inputs(asset_id: int):
    asset = _asset_or_404(asset_id)
    name = (request.form.get("name") or "").strip()[:60] or "My inputs"
    try:
        set_id = int(request.form.get("set_id") or 0) or None
    except ValueError:
        set_id = None
    if set_id and query_one("SELECT 1 FROM marine_inputs WHERE id = ? AND asset_id = ?", (set_id, asset_id)) is None:
        abort(404)
    values = marine_inputs.clean(request.form.to_dict(flat=False), asset["terminal_type"])
    saved = marine_inputs.save(get_db(), asset_id, name, values, set_id, g.user["id"], use=bool(request.form.get("use")))
    get_db().commit()
    flash(f"{name} is kept{' and in use' if request.form.get('use') else ''}: {len(values)} figures changed from the typical.", "success")
    back = request.form.get("back")
    if back in ("lifecycle", "risks"):
        return redirect(url_for(f"marine.{back}", asset_id=asset_id))
    return redirect(url_for("marine.inputs", asset_id=asset_id, edit=saved))


@bp.post("/assets/<int:asset_id>/inputs/<int:set_id>/use")
@login_required
def use_inputs(asset_id: int, set_id: int):
    _asset_or_404(asset_id)
    if set_id and query_one("SELECT 1 FROM marine_inputs WHERE id = ? AND asset_id = ?", (set_id, asset_id)) is None:
        abort(404)
    marine_inputs.make_active(get_db(), asset_id, set_id)
    get_db().commit()
    flash(f"The pages now run on {marine_inputs.active_name(get_db(), asset_id)}.", "success")
    return redirect(url_for("marine.inputs", asset_id=asset_id))


@bp.post("/assets/<int:asset_id>/inputs/<int:set_id>/delete")
@login_required
def delete_inputs(asset_id: int, set_id: int):
    _asset_or_404(asset_id)
    get_db().execute("DELETE FROM marine_inputs WHERE id = ? AND asset_id = ?", (set_id, asset_id))
    get_db().commit()
    flash("The input set is deleted.", "success")
    return redirect(url_for("marine.inputs", asset_id=asset_id))


def _risk_run(asset_id: int):
    asset = _asset_or_404(asset_id)
    given = _given(asset_id)
    rates = marine_life.rates_for(asset["terminal_type"], given)
    life = int(asset["design_life"] or 50)
    return asset, given, marine_risk.catalogue(asset, _life_elements(asset_id), rates, given, life), rates


@bp.get("/assets/<int:asset_id>/risks")
@login_required
def risks(asset_id: int):
    """Every extreme event at this berth: damage, area closed, time, cost, what knowing early saves, the way back."""
    asset, given, events, rates = _risk_run(asset_id)
    shown = next((e for e in events if e["key"] == request.args.get("event")), None) or max(events, key=lambda e: e["expected"])
    included = [e for e in events if e["on"]]
    totals = {"expected": sum(e["expected"] for e in included), "expected_saving": sum(e["expected_saving"] for e in included)}
    return render_template("marine/risks.html", asset=asset, events=events, shown=shown, totals=totals, rates=rates,
                           groups=marine_risk.GROUPS, units=marine_ops.UNITS.get(asset["terminal_type"], "containers"),
                           life=int(asset["design_life"] or 50), inputs_name=marine_inputs.active_name(get_db(), asset_id),
                           **_context())


def _plan_run(asset_id: int):
    asset = _asset_or_404(asset_id)
    given = _given(asset_id)
    rates = marine_life.rates_for(asset["terminal_type"], given)
    life = int(asset["design_life"] or 50)
    elements = [dict(e) for e in _life_elements(asset_id)]
    return asset, given, rates, life, elements


@bp.get("/assets/<int:asset_id>/plan")
@login_required
def plan(asset_id: int):
    """The sensors plan: what to buy and where it goes, what it costs over the life and what it pays back."""
    asset, given, rates, life, elements = _plan_run(asset_id)
    fixing = marine_life.run(asset, elements, "fix", rates=given, risks=given)
    result = marine_plan.assess(asset, elements, rates, given, life, repair_saving=fixing["totals"]["spend"])
    groups: dict[str, list] = {}
    for line in result["cost"]["lines"]:
        groups.setdefault(line["group"], []).append(line)
    try:
        year = min(max(int(request.args.get("year", 4)), 0), life)
    except ValueError:
        year = 4
    return render_template("marine/plan.html", asset=asset, r=result, groups=groups, rates=rates, life=life, year=year,
                           units=marine_ops.UNITS.get(asset["terminal_type"], "containers"),
                           inputs_name=marine_inputs.active_name(get_db(), asset_id), **_context())


@bp.get("/assets/<int:asset_id>/plan.json")
@login_required
def plan_json(asset_id: int):
    """Every planned sensor in a year of service: where, its assumed reading, its maintenance check."""
    asset, given, rates, life, elements = _plan_run(asset_id)
    try:
        year = min(max(float(request.args.get("year", 4)), 0), life)
    except ValueError:
        year = 4.0
    lay = marine_plan.layout(asset, elements, given)
    rows = marine_plan.year_view(asset, lay, year, None, given, life)
    return jsonify({"year": year, "sensors": [{k: s[k] for k in ("id", "tag", "key", "name", "host", "ref", "face", "value", "unit",
                                                                 "reading_state", "check", "check_note", "state")} for s in rows]})


@bp.get("/assets/<int:asset_id>/plan/<sensor_id>.json")
@login_required
def plan_sensor_json(asset_id: int, sensor_id: str):
    """One planned sensor's assumed readings over the design life."""
    asset, given, rates, life, elements = _plan_run(asset_id)
    lay = marine_plan.layout(asset, elements, given)
    s = next((x for x in lay["sensors"] if x["id"] == sensor_id), None)
    if s is None:
        abort(404)
    spec = marine.SENSOR_KINDS.get(s["reads"] or "", {})
    return jsonify({"id": s["id"], "tag": s["tag"], "name": s["name"], "host": s["host"], "unit": spec.get("unit", ""),
                    "reads": spec.get("name", ""), "points": marine_plan.series(asset, s, None, life)})


@bp.get("/assets/<int:asset_id>/plan/sensors.<fmt>")
@login_required
def plan_export(asset_id: int, fmt: str):
    """The planned sensors on their own: a CSV, or an IFC with just the sensors to link into Revit."""
    asset, given, rates, life, elements = _plan_run(asset_id)
    lay = marine_plan.layout(asset, elements, given)
    stem = "".join(ch if ch.isalnum() else "-" for ch in asset["name"]).strip("-").lower() or "asset"
    if fmt == "csv":
        body, mime = marine_plan.export_csv(lay, given), "text/csv"
    elif fmt == "ifc":
        body, mime = marine_plan.export_ifc(asset, lay, given), "application/x-step"
    else:
        abort(404)
    return Response(body, mimetype=mime, headers={"Content-Disposition": f'attachment; filename="{stem}-sensors.{fmt}"'})


@bp.get("/assets/<int:asset_id>/risks/<key>.json")
@login_required
def risk_json(asset_id: int, key: str):
    """One event for the 3D view: the elements it damages and the area it closes."""
    if key not in marine_risk.BY_KEY:
        abort(404)
    asset = _asset_or_404(asset_id)
    given = _given(asset_id)
    rates = marine_life.rates_for(asset["terminal_type"], given)
    e = marine_risk.assess(asset, _life_elements(asset_id), key, rates, given, int(asset["design_life"] or 50))
    return jsonify({"key": e["key"], "name": e["name"], "days": e["days"], "days_known": e["days_known"],
                    "whole": bool(e["share"] and not e["radius"] and e["days"]), "closed_m": e["closed_m"],
                    "damaged": e["damaged"], "closed": e["closed_refs"]})


@bp.route("/assets/<int:asset_id>/lifecycle.json", methods=["GET", "POST"])
@login_required
def lifecycle_json(asset_id: int):
    """One run of the design life: ``policy`` nothing, fix or game, and for a game the choices made so far."""
    asset = _asset_or_404(asset_id)
    body = request.get_json(silent=True) if request.is_json else None
    body = body if isinstance(body, dict) else {}
    policy = body.get("policy") or request.args.get("policy") or "fix"
    choices = body.get("choices") if isinstance(body.get("choices"), list) else []
    given = _given(asset_id)
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
                           situations=marine_ops.SCENARIOS,
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
    fleet = marine_berths.crane_fleet(get_db(), asset_id)
    equipment = marine_ops.cranes(asset_id, now, weather[0]["gust"], asset["terminal_type"], len(fleet) if fleet else 3)
    return jsonify({
        "asset": {"id": asset["id"], "name": asset["name"], "kind": asset["kind"],
                  "terminal": asset["terminal_type"], "latitude": asset["latitude"], "longitude": asset["longitude"],
                  "rotation": asset["rotation"], "msl_cd": asset["msl_cd"], "location": asset["location"],
                  "berth_uses": _berth_uses(asset), "berth_use_names": dict(marine.BERTH_USES)},
        "now": {"at": now.isoformat(timespec="minutes"), "wind": weather[0]["wind"], "gust": weather[0]["gust"],
                "hs": weather[0]["hs"], "tide": weather[0]["tide"],
                "tides": [{"at": w["at"].isoformat(timespec="minutes"), "tide": w["tide"]} for w in weather],
                "source": "simulated"},
        "alongside": {"name": alongside["name"], "type": alongside["type"], "loa": alongside["loa"],
                      "beam": alongside["beam"], "draught": alongside["draught"]} if alongside else None,
        "next_ship": next(({"name": s["name"], "type": s["type"], "eta": s["eta"].isoformat(timespec="minutes"),
                            "loa": s["loa"], "beam": s["beam"], "draught": s["draught"]}
                           for s in ships if s["eta"] > now), None),
        "equipment": [{"name": c["name"], "state": c["state"], "why": c["why"], "service_in_h": c["service_in_h"],
                       **({"berth": fleet[k]} if fleet and k < len(fleet) else {})} for k, c in enumerate(equipment)],
        "model": url_for("marine.model", asset_id=asset_id) if asset["model_file"] else None,
        **_shapes_links(asset, twin["elements"]),
        "model_kind": MODEL_TYPES.get(Path(asset["model_file"]).suffix.lower(), ""),
        "surroundings": _surroundings_link(asset),
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


def _berth_uses(asset) -> dict[str, str]:
    try:
        uses = json.loads(asset["berth_uses"] or "{}")
    except (TypeError, ValueError):
        return {}
    valid = dict(marine.BERTH_USES)
    return {str(k): v for k, v in uses.items() if v in valid} if isinstance(uses, dict) else {}


@bp.post("/assets/<int:asset_id>/berths")
@login_required
def save_berth_use(asset_id: int):
    """What one berth without crane stoppers is used for, set from the live port."""
    asset = _asset_or_404(asset_id)
    data = request.get_json(silent=True) or {}
    berth, use = str(data.get("berth", "")).strip(), data.get("use")
    if not berth.isdigit() or not 0 < int(berth) <= 200 or use not in dict(marine.BERTH_USES):
        return jsonify({"error": "Pick a berth and one of its uses."}), 400
    uses = {**_berth_uses(asset), berth: use}
    get_db().execute("UPDATE marine_assets SET berth_uses = ? WHERE id = ?", (json.dumps(uses), asset_id))
    get_db().commit()
    return jsonify({"berth_uses": uses})


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
    _surroundings_path(asset_id).unlink(missing_ok=True)
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
    if result["written"]:
        _check_alarms(asset_id)
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
    before = _model_found(asset_id)                   # the last read, for a model uploaded before versions were kept
    _found_path(asset_id).unlink(missing_ok=True)
    _forget_shapes(asset_id)
    found = None
    if suffix == ".ifc":
        try:
            found = marine_ifc.read_file(target)
        except Exception:                             # noqa: BLE001 - an IFC we cannot read is still drawn
            current_app.logger.exception("Reading the IFC model failed for asset %s", asset_id)
            found = None
        if found is not None:
            _found_path(asset_id).write_text(json.dumps(found), encoding="utf-8")
            took = marine.apply_site(get_db(), asset_id, found)
            marine.regroup(get_db(), asset_id, found)
            new = _new_in_model(asset_id, found)
            if took:
                message += " From the model MarineTwin took " + "; ".join(took) + "."
            if new:
                message += f" It also has {len(new)} element{'s' if len(new) > 1 else ''} MarineTwin does not track yet: import them below."
    version = marine_versions.record(get_db(), asset_id, g.user["id"], upload.filename, target.stat().st_size, found,
                                     before=[marine_versions._slim(e) for e in before["elements"]] if before else None)
    if version["compared"]:
        what = [f"{version[k]:,} {k}" for k in ("added", "removed", "moved", "changed") if version[k]]
        message += f" Version {version['number']}: " + (", ".join(what) if what else "no element changed") + " since the last one."
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


@bp.post("/assets/<int:asset_id>/sensors/trim")
@login_required
def trim_sensors(asset_id: int):
    """One monitored element per design: the others' simulated sensors go."""
    asset = _asset_or_404(asset_id)
    db = get_db()
    found = None
    if Path(asset["model_file"]).suffix.lower() == ".ifc" and (models_dir() / asset["model_file"]).exists():
        try:
            found = marine_ifc.read_file(models_dir() / asset["model_file"])   # again: older reads kept no legend
            _found_path(asset_id).write_text(json.dumps(found), encoding="utf-8")
        except Exception:                             # noqa: BLE001 - fall back on what the last read found
            current_app.logger.exception("Reading the IFC model failed for asset %s", asset_id)
    found = found or _model_found(asset_id)
    if found:
        marine.regroup(db, asset_id, found)
    done = marine.trim_sensors(db, asset_id)
    db.commit()
    flash(f"{done['removed']:,} simulated sensor{'s' if done['removed'] != 1 else ''} removed: one element per design keeps them. "
          f"{done['left']:,} sensor{'s' if done['left'] != 1 else ''} left." if done["removed"]
          else f"Every design already has its sensors on one element ({done['left']:,} sensors).", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))


@bp.post("/assets/<int:asset_id>/model/orphans/remove")
@login_required
def remove_orphans(asset_id: int):
    """Remove the tracked elements the model no longer has, unless they carry real readings."""
    _asset_or_404(asset_id)
    db = get_db()
    gone = [o for o in marine_versions.orphans(db, asset_id, _model_found(asset_id)) if not o["real"]]
    for i in range(0, len(gone), 500):
        ids = [o["id"] for o in gone[i:i + 500]]
        marks = ",".join("?" * len(ids))
        mine = f"SELECT id FROM marine_sensors WHERE element_id IN ({marks})"
        db.execute(f"DELETE FROM marine_readings WHERE sensor_id IN ({mine})", ids)
        db.execute(f"DELETE FROM marine_sensors WHERE element_id IN ({marks})", ids)
        db.execute(f"DELETE FROM marine_elements WHERE id IN ({marks})", ids)
    db.commit()
    flash(f"{len(gone):,} element{'s' if len(gone) != 1 else ''} no longer in the model removed; any with real readings were kept."
          if gone else "No element to remove: those left carry real readings.", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="versions"))


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


# --- the surroundings from the map ------------------------------------------------------
# Roads, buildings, railways and water around the site, from OpenStreetMap. The browser asks
# Overpass for them (PythonAnywhere's free plan cannot reach it from the server) and keeps what it
# got here, so the next visit, and everyone else's, draws them at once. The key is the site's
# location: move the site and the next visit fetches the new place's surroundings.
SURROUNDINGS_LIMIT = 12 * 1024 * 1024


def _surroundings_key(asset) -> str | None:
    if asset["latitude"] is None or asset["longitude"] is None:
        return None
    return f"v2:{asset['latitude']:.4f}:{asset['longitude']:.4f}"


def _surroundings_path(asset_id: int) -> Path:
    return models_dir() / f"asset-{asset_id}.surroundings.json"


def _kept_surroundings_key(asset_id: int) -> str | None:
    path = _surroundings_path(asset_id)
    if not path.exists():
        return None
    try:
        with path.open("rb") as f:
            head = f.read(200).decode("utf-8", "ignore")
        return json.loads(head[: head.index(",")] + "}").get("key") if head.startswith('{"key"') else None
    except (ValueError, OSError):
        return None


def _surroundings_link(asset) -> dict | None:
    key = _surroundings_key(asset)
    if key is None:
        return None
    return {"url": url_for("marine.surroundings", asset_id=asset["id"]), "key": key,
            "kept": _kept_surroundings_key(asset["id"]) == key}


@bp.get("/assets/<int:asset_id>/surroundings.json")
@login_required
def surroundings(asset_id: int):
    asset = _asset_or_404(asset_id)
    key = _surroundings_key(asset)
    if key is None or _kept_surroundings_key(asset_id) != key:
        abort(404)
    return send_file(_surroundings_path(asset_id), mimetype="application/json", max_age=0)


@bp.post("/assets/<int:asset_id>/surroundings.json")
@login_required
def keep_surroundings(asset_id: int):
    asset = _asset_or_404(asset_id)
    key = _surroundings_key(asset)
    if key is None:
        return jsonify(kept=False, why="the site has no location"), 409
    if (request.content_length or 0) > SURROUNDINGS_LIMIT:
        return jsonify(kept=False, why="too big"), 413
    got = request.get_json(silent=True)
    if not isinstance(got, dict) or got.get("key") != key:
        return jsonify(kept=False, why="not for this site's location"), 409
    lists = ("buildings", "roads", "rail", "water", "coast")
    if any(not isinstance(got.get(k, []), list) for k in lists):
        return jsonify(kept=False, why="not surroundings"), 400
    # The key first, so a visit can tell what is kept without reading the whole file.
    body = {"key": key, **{k: got.get(k, []) for k in lists}, "source": str(got.get("source", ""))[:200]}
    target = _surroundings_path(asset_id)
    partial = target.with_suffix(".part")
    partial.write_text(json.dumps(body, separators=(",", ":")), encoding="utf-8")
    partial.replace(target)
    return jsonify(kept=True)


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


# To bring a model's elements in again (after a new export, or to take the newer import's sensors),
# all of them go at once, with their sensors and readings; the model file stays.
@bp.post("/assets/<int:asset_id>/elements/delete")
@login_required
def delete_elements(asset_id: int):
    _asset_or_404(asset_id)
    db = get_db()
    # Children first, by set: sensors have no index on element_id, so a cascade per element would
    # scan them all once for each of thousands of elements.
    mine = "SELECT s.id FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id WHERE e.asset_id = ?"
    db.execute(f"DELETE FROM marine_readings WHERE sensor_id IN ({mine})", (asset_id,))
    db.execute(f"DELETE FROM marine_sensors WHERE id IN ({mine})", (asset_id,))
    gone = db.execute("DELETE FROM marine_elements WHERE asset_id = ?", (asset_id,)).rowcount
    db.commit()
    flash(f"{gone} element{'s' if gone != 1 else ''} and their sensors were removed. Import them again from the model below."
          if gone else "There were no elements to remove.", "success")
    return redirect(url_for("marine.setup", asset_id=asset_id, _anchor="model"))


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


@bp.post("/assets/<int:asset_id>/sensors/<int:sensor_id>/calibration")
@login_required
def calibrate_sensor(asset_id: int, sensor_id: int):
    """A sensor's zero and gauge factor. Its real readings are worked out again from what the logger sent."""
    db = get_db()
    sensor = db.execute("SELECT s.*, e.id AS element_id FROM marine_sensors s JOIN marine_elements e"
                        " ON e.id = s.element_id WHERE s.id = ? AND e.asset_id = ?", (sensor_id, asset_id)).fetchone()
    if sensor is None:
        abort(404)
    zero, factor = _number("zero", 0.0), _number("factor", 1.0)
    if zero is None or factor is None or factor == 0:
        flash("The zero must be a number and the factor a number other than 0.", "error")
        return redirect(url_for("marine.element", asset_id=asset_id, element_id=sensor["element_id"]))
    db.execute("UPDATE marine_sensors SET zero = ?, factor = ? WHERE id = ?", (zero, factor, sensor_id))
    redone = 0
    if not sensor["simulated"] and sensor["kind"] != "inspection":
        # A reading with no raw value was taken with no calibration at all: its value is what was sent.
        redone = db.execute("UPDATE marine_readings SET raw = COALESCE(raw, value), value = (COALESCE(raw, value) - ?) * ?"
                            " WHERE sensor_id = ?", (zero, factor, sensor_id)).rowcount
    db.commit()
    flash(f"{sensor['label']}: zero {zero:g}, factor {factor:g}" + (f"; {redone:,} readings worked out again." if redone else "."), "success")
    return redirect(url_for("marine.element", asset_id=asset_id, element_id=sensor["element_id"]))


# --- real sensors: the kit, and the door a logger sends readings through --------------------------

@bp.get("/assets/<int:asset_id>/sensors")
@login_required
def sensors(asset_id: int):
    """Connecting real sensors: what the kit costs, what the person does, and the live feed."""
    asset = _asset_or_404(asset_id)
    db = get_db()
    key = marine_feed.key_for(db, asset_id)
    db.commit()
    logged = [k for k, v in marine_feed.SENSOR_KIT.items() if v["route"] == "logger"]
    elements = query(
        "SELECT e.id, e.name, COUNT(s.id) AS n, SUM(s.kind IN (%s)) AS wired FROM marine_elements e"
        " JOIN marine_sensors s ON s.element_id = e.id WHERE e.asset_id = ? GROUP BY e.id ORDER BY e.name"
        % ",".join("?" * len(logged)), (*logged, asset_id))
    pilot_id = request.args.get("element", type=int)
    if pilot_id is None or not any(e["id"] == pilot_id for e in elements):
        # The pilot: the element a logger reads most sensors on.
        pilot_id = max(elements, key=lambda e: (e["wired"] or 0, -e["id"]))["id"] if elements else None
    pilot_counts = marine_feed.counts_for(db, asset_id, pilot_id) if pilot_id else {}
    channels = marine_feed.fake_channels(db, asset)
    base = request.url_root.rstrip("/")
    return render_template(
        "marine/sensors.html", asset=asset, key=key,
        endpoint=f"{base}{url_for('marine.feed_readings', asset_id=asset_id)}",
        whole=marine_feed.kit(marine_feed.counts_for(db, asset_id)), pilot=marine_feed.kit(pilot_counts),
        pilot_id=pilot_id, elements=elements, channels=channels, sensor_kit=marine_feed.SENSOR_KIT,
        route_words=marine_feed.ROUTE_WORDS, money=marine_feed.money, feed=marine_feed.status(db, asset_id),
        fake_device=marine_feed.FAKE_DEVICE, **_context())


@bp.get("/assets/<int:asset_id>/feed.json")
@login_required
def feed_status(asset_id: int):
    _asset_or_404(asset_id)
    return jsonify(marine_feed.status(get_db(), asset_id))


@bp.post("/assets/<int:asset_id>/feed/key")
@login_required
def renew_feed_key(asset_id: int):
    _asset_or_404(asset_id)
    marine_feed.key_for(get_db(), asset_id, renew=True)
    get_db().commit()
    flash("A new key is made. Loggers using the old one are shut out until they get the new one.", "success")
    return redirect(url_for("marine.sensors", asset_id=asset_id, _anchor="live-feed"))


@bp.post("/assets/<int:asset_id>/feed/reset")
@login_required
def reset_fake_feed(asset_id: int):
    _asset_or_404(asset_id)
    n = marine_feed.back_to_simulation(get_db(), asset_id)
    get_db().commit()
    flash(f"{n} sensor{'s' if n != 1 else ''} the fake logger fed went back to simulation." if n
          else "The fake logger has not fed any sensors yet.", "success")
    return redirect(url_for("marine.sensors", asset_id=asset_id, _anchor="live-feed"))


@bp.get("/assets/<int:asset_id>/fake_logger.py")
@login_required
def fake_logger(asset_id: int):
    asset = _asset_or_404(asset_id)
    db = get_db()
    key = marine_feed.key_for(db, asset_id)
    db.commit()
    body = marine_feed.fake_script(request.url_root.rstrip("/"), query_one(
        "SELECT * FROM marine_assets WHERE id = ?", (asset_id,)), key, marine_feed.fake_channels(db, asset))
    return Response(body, mimetype="text/x-python",
                    headers={"Content-Disposition": "attachment; filename=fake_logger.py"})


@bp.post("/api/assets/<int:asset_id>/readings")
def feed_readings(asset_id: int):
    """Where a logger sends its readings: HTTPS POST with the asset's key, as JSON
    (``{"device": …, "readings": [{"sensor", "at", "value", "note"}]}``) or as CSV text in the import's
    columns. Not behind the sign-in, since a logger cannot sign in: the key is what lets it in."""
    asset = query_one("SELECT * FROM marine_assets WHERE id = ?", (asset_id,))
    given = request.headers.get("X-MarineTwin-Key") or request.args.get("key") or ""
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        given = auth[7:]
    if asset is None or not marine_feed.key_matches(asset, given):
        return jsonify(ok=False, error="Unknown asset or wrong key."), 403
    if (request.content_length or 0) > FEED_LIMIT:
        return jsonify(ok=False, error="Too much at once; send smaller batches."), 413
    device = (request.args.get("device") or request.headers.get("X-MarineTwin-Device") or "")[:60]
    db = get_db()
    if request.is_json:
        payload = request.get_json(silent=True)
        if payload is None:
            return jsonify(ok=False, error="The body is not valid JSON."), 400
        result = marine_feed.receive(db, asset_id, payload, device)
    else:
        result = marine_feed.receive_csv(db, asset_id, request.get_data(as_text=True), device)
    if result["written"]:
        _check_alarms(asset_id)
    db.commit()
    return jsonify(ok=not result["problems"], written=result["written"], sensors=result["sensors"],
                   problems=result["problems"]), 200 if result["written"] or not result["problems"] else 422
