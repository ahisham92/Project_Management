"""MarineTwin's extreme events: everything that could hit the berth, one at a time.

The lifecycle plays fifty years with the risks mixed in; this takes each extreme event on its
own and says, for this berth:

* **what it damages** — which elements (from the model) and how badly, drawn on the 3D view,
  and the **area closed** while it is inspected and repaired;
* **the time** — the warning there is, how long the area stays closed, how long the repair
  takes and when the berth is back to full working;
* **the cost** — the containers the berth could not handle while it was closed (at the value
  of a container), plus the repair;
* **knowing early** — the same event when the warning was heard and acted on, and the damage
  was found by the sensors rather than by divers and surveyors weeks later: what that saves;
* **the way back** — the recovery steps, in order.

Every figure is an indicative default the person can change on the Inputs page (``ev_<key>_*``
keys); the chance of each is a return period in years. Which elements are damaged is drawn
deterministically per asset and event, so the same event always hits the same place.
"""

from __future__ import annotations

import math
import random
from typing import Any, Iterable

# Kinds of element, grouped the way the events hit them.
FRONT = ("fender", "ladder", "bollard")
WALL = ("pile", "combi_wall", "sheet_pile")
DECK = ("slab", "beam")
RAIL = ("crane_rail", "crane_stopper", "storm_pin")

GROUPS = ["Nature", "Ground", "Operations", "Fire and explosion", "Force majeure", "Trade"]


def _event(key, name, group, years, what, *, damage=(), radius=None, share=None, warn_h=0.0, warn_with="",
           days=0.0, days_known=0.0, repair_days=0.0, ramp_days=0.0, cost=0.0, cost_known=0.0,
           fall=0.0, fall_months=0.0, fall_known=None, power=False, weather=None, early="", sensors=(), steps=()):
    return {"key": key, "name": name, "group": group, "years": years, "what": what, "damage": list(damage),
            "radius": radius, "share": share, "warn_h": warn_h, "warn_with": warn_with, "days": days,
            "days_known": days_known, "repair_days": repair_days, "ramp_days": ramp_days, "cost": cost,
            "cost_known": cost_known, "fall": fall, "fall_months": fall_months,
            "fall_known": fall if fall_known is None else fall_known, "power": power, "weather": weather,
            "early": early, "sensors": list(sensors), "steps": list(steps)}


# The catalogue. damage: (kinds, share of those in the area hit, state); radius: metres about the
# point hit that is closed (None: the whole quay); share: the share of the berth's work lost while
# closed, when it is not simply the area. days / cost: not knowing early; *_known: knowing early.
EVENTS = [
    _event("great_storm", "Great storm or cyclone", "Nature", 25,
           "Winds past the cranes' storm limit and big waves for a day or two: fenders and ladders torn, ships surging on their lines.",
           damage=[(("fender",), 0.15, "critical"), (("ladder",), 0.3, "critical"), (("bollard",), 0.05, "warning")],
           warn_h=72, warn_with="the weather forecast and the site's own weather station and wave buoy",
           days=7, days_known=3, repair_days=30, ramp_days=3, cost=2_500_000, cost_known=600_000,
           power=True, weather={"wind": 26, "hs": 3.2},
           early="Cranes stowed and pinned in time, ships sent to sea, stacks lashed and lowered: little more than the fenders to mend.",
           sensors=["weather_station", "wave_buoy", "fender_load"],
           steps=["Stow the cranes on their storm pins and send ships to sea", "Close the quay to traffic",
                  "Inspect fenders, ladders and bollards from the quay and a boat", "Reopen the berths that pass inspection",
                  "Replace the torn fenders and ladders, a section at a time"]),
    _event("storm_surge", "Storm surge on a raised sea", "Nature", 20,
           "A surge on a high tide comes over the cope: the apron floods, cable ducts and pits fill, power trips.",
           damage=[(("slab",), 0.2, "warning")], warn_h=36, warn_with="the tide gauge and the surge forecast",
           days=4, days_known=1.5, repair_days=14, ramp_days=2, cost=1_500_000, cost_known=500_000, power=True,
           weather={"wind": 18, "hs": 2.0},
           early="Drains cleared and ducts sealed before the surge, the switchgear made safe, reefers moved back.",
           sensors=["tide_gauge", "weather_station", "drain_level"],
           steps=["Clear the drains and seal the cable ducts", "Move the reefers and the dangerous goods back from the edge",
                  "Pump out the ducts and pits", "Test the cables and switchgear before power goes back on",
                  "Repair the apron where the water lifted it"]),
    _event("tsunami", "Tsunami", "Nature", 500,
           "Several waves over the quay: fenders and ladders gone, boxes and vehicles washed off, scour at the toe of the wall.",
           damage=[(("fender",), 0.6, "critical"), (("ladder",), 0.8, "critical"), (("bollard",), 0.2, "critical"),
                   (("slab",), 0.3, "warning"), (WALL, 0.1, "warning")],
           warn_h=2, warn_with="the regional tsunami warning and the site's tide gauge",
           days=60, days_known=30, repair_days=180, ramp_days=30, cost=25_000_000, cost_known=15_000_000, power=True,
           weather={"wind": 10, "hs": 4.0},
           early="People evacuated and ships at sea before the first wave; strain and tilt gauges show at once which bays still stand, so those reopen first.",
           sensors=["tide_gauge", "strain", "tilt", "accelerometer"],
           steps=["Evacuate the quay, ships to deep water", "Survey the toe for scour and the wall for movement",
                  "Clear debris and reopen sound bays", "Rebuild the fenders, ladders and apron", "Place rock where the toe was scoured"]),
    _event("quake_moderate", "Earthquake, moderate", "Nature", 75,
           "Strong shaking: the deck cracks, the crane rails go out of line, piles take some strain.",
           damage=[(("pile",), 0.1, "warning"), (("slab",), 0.15, "warning"), (("crane_rail",), 0.2, "warning")],
           warn_h=0, warn_with="",
           days=21, days_known=3, repair_days=45, ramp_days=7, cost=3_000_000, cost_known=2_000_000, power=True,
           early="Accelerometers, strain and tilt gauges tell within hours which bays are sound: they reopen in days instead of weeks of surveys.",
           sensors=["accelerometer", "strain", "tilt", "rail_survey"],
           steps=["Stop the cranes and clear the quay", "Read the accelerometers, strain and tilt gauges",
                  "Reopen the bays whose readings are back within limits", "Survey and realign the crane rails",
                  "Repair the cracked deck"]),
    _event("quake_major", "Earthquake, major", "Nature", 475,
           "The design earthquake: piles and walls yield, the deck breaks, the rails are lost, tie rods may fail.",
           damage=[(("pile",), 0.35, "critical"), (("slab", "beam"), 0.4, "critical"), (("combi_wall", "sheet_pile"), 0.25, "warning"),
                   (("crane_rail",), 0.5, "critical"), (("tie_rod",), 0.2, "critical")],
           days=180, days_known=120, repair_days=540, ramp_days=60, cost=60_000_000, cost_known=45_000_000, power=True,
           early="The gauges map the damage the same day: sound stretches reopen in weeks and repairs are designed from readings, not months of diving.",
           sensors=["accelerometer", "strain", "tilt", "settlement"],
           steps=["Evacuate and stop all work", "Map the damage from the sensors and a drone survey",
                  "Prop and close the failed bays", "Reopen the sound stretches with load limits",
                  "Rebuild the failed bays", "Realign or relay the crane rails"]),
    _event("liquefaction", "Ground settlement or liquefaction", "Ground", 200,
           "The fill behind the wall settles or liquefies: the apron sinks, the wall leans out, tie rods overload.",
           damage=[(("slab",), 0.4, "critical"), (("tie_rod",), 0.3, "critical"), (("sheet_pile", "combi_wall"), 0.3, "warning")],
           radius=150, days=90, days_known=45, repair_days=180, ramp_days=20, cost=12_000_000, cost_known=6_000_000,
           early="Settlement markers, piezometers and tilt gauges show the ground moving months before it fails: grouting in time saves the wall.",
           sensors=["settlement", "piezometer", "tilt"],
           steps=["Close the area and keep loads off", "Survey levels and the wall's lean",
                  "Grout or compact the fill", "Relevel and resurface the apron"]),
    _event("scour", "Scour at the toe of the wall", "Ground", 15,
           "Propeller wash from big ships digs out the seabed in front of the wall: piles lose support, the wall leans.",
           damage=[(("pile",), 0.4, "warning"), (("sheet_pile", "combi_wall"), 0.3, "warning")],
           radius=100, days=30, days_known=2, repair_days=40, ramp_days=5, cost=4_000_000, cost_known=800_000,
           early="Bed-level surveys and tilt gauges catch the scour while it is shallow: rock placed in front before the wall moves.",
           sensors=["bathymetry", "tilt"],
           steps=["Limit thrusters and propellers at the berth", "Survey the bed in front of the wall",
                  "Place rock or mattresses in the scour hole", "Check the wall has stopped moving"]),
    _event("alwc", "Low water corrosion found late", "Ground", 20,
           "Accelerated low water corrosion eats through the steel at low tide level far faster than the allowance assumed.",
           damage=[(WALL, 0.3, "critical")], radius=300,
           days=120, days_known=10, repair_days=150, ramp_days=10, cost=8_000_000, cost_known=1_000_000,
           early="Corrosion probes and half-cell readings show the rate climbing: cathodic protection fitted while the steel is still thick enough.",
           sensors=["corrosion", "half_cell"],
           steps=["Keep loads back from the edge on the affected stretch", "Measure the steel left by divers",
                  "Plate the thinned steel", "Fit cathodic protection along the whole front"]),
    _event("ship_strike", "Ship strikes the quay", "Operations", 10,
           "A ship comes in too fast or at an angle: fenders torn off, the front piles and the deck edge behind them damaged.",
           damage=[(("fender",), 1.0, "critical"), (("pile",), 0.3, "warning"), (("slab",), 0.2, "warning"), (("bollard",), 0.3, "warning")],
           radius=40, warn_h=0.25, warn_with="the berthing aid system (approach speed and angle on a display for the pilot)",
           days=30, days_known=10, repair_days=30, ramp_days=2, cost=1_800_000, cost_known=900_000,
           early="The pilot sees the approach is too fast in time to slow; fender load cells say at once which fenders took it.",
           sensors=["berthing_aid", "fender_load", "strain"],
           steps=["Stop berthing at the stretch", "Read the fender load cells and inspect from a boat",
                  "Replace the damaged fenders", "Repair the deck edge and check the piles", "Claim from the ship's insurer"]),
    _event("crane_collapse", "Quay crane collapse", "Operations", 30,
           "A crane blown along its rails or hit by a ship falls: the rail, the stoppers and the deck under it destroyed.",
           damage=[(("crane_rail", "crane_stopper", "storm_pin"), 1.0, "critical"), (("slab",), 0.5, "warning")],
           radius=60, warn_h=0.5, warn_with="the crane's anemometer and storm-pin alarms",
           days=60, days_known=20, repair_days=120, ramp_days=10, cost=12_000_000, cost_known=10_000_000,
           early="Wind alarms stow and pin the crane before the gust; the rail survey finds loose clips before they matter.",
           sensors=["weather_station", "rail_survey"],
           steps=["Make the wreck safe and close the stretch", "Remove the crane", "Relay the rail and stoppers",
                  "Repair the deck", "Bring a replacement crane"]),
    _event("grid_failure", "Long grid failure", "Operations", 15,
           "The grid goes for a week: electric cranes stop, reefers run on whatever generators there are.",
           share=0.8, days=7, days_known=0.5, repair_days=0, ramp_days=1, cost=200_000, cost_known=50_000, power=True,
           early="Power monitoring sees the supply failing; backup generators keep the cranes and reefers going.",
           sensors=["power_monitor"],
           steps=["Start the backup generators", "Keep the reefers powered first", "Work ships on diesel equipment",
                  "Bring cranes back one at a time when the grid returns"]),
    _event("flood_rain", "Extreme rainfall flooding", "Operations", 10,
           "A cloudburst on blocked drains: the apron under water, ducts flooded, trucks stopped.",
           damage=[(("slab",), 0.1, "warning")], share=0.5,
           days=3, days_known=0.5, repair_days=7, ramp_days=1, cost=400_000, cost_known=50_000,
           early="Drain level sensors show the drains silting up long before the storm: they are jetted in time.",
           sensors=["drain_level", "weather_station"],
           steps=["Pump the apron and pits", "Jet the drains and interceptors", "Dry and test the cables", "Repair washed-out paving"]),
    _event("extreme_heat", "Extreme heat", "Operations", 5,
           "A heatwave: rails expand and buckle, reefers draw more than the supply can give, people must rest.",
           damage=[(("crane_rail",), 0.15, "warning")], share=0.2,
           days=5, days_known=1, repair_days=5, ramp_days=1, cost=300_000, cost_known=100_000,
           early="Rail temperature and level readings show the rail moving: crane speed limited before it buckles.",
           sensors=["rail_survey", "weather_station"],
           steps=["Limit crane travel speed", "Shift work to the cooler hours", "Realign the rail where it moved"]),
    _event("cyber", "Cyber attack", "Operations", 20,
           "The terminal operating system locked by ransomware: no gate, no yard plan, no crane orders.",
           share=1.0, days=10, days_known=3, ramp_days=7, cost=3_000_000, cost_known=1_000_000,
           early="Network monitoring spots the intrusion before it spreads; clean backups and paper procedures keep work going.",
           sensors=["network_monitor"],
           steps=["Isolate the networks", "Switch to manual gate and yard procedures", "Restore from clean backups",
                  "Bring systems back one at a time"]),
    _event("labour_strike", "Strike", "Operations", 8,
           "Dockers or pilots stop work for days.",
           share=0.9, days=10, days_known=5, ramp_days=3,
           early="Not a sensor's job: early talks and contingency crews.",
           steps=["Keep talks open", "Use contingency crews for essential work", "Clear the backlog when work resumes"]),
    _event("fire_apron", "Fire on the apron", "Fire and explosion", 20,
           "A reefer, a truck or a stack catches fire: the deck under it spalls, the beams lose strength.",
           damage=[(("slab",), 0.6, "warning"), (("beam",), 0.3, "warning")],
           radius=50, warn_h=0.1, warn_with="thermal cameras and smoke detection on the stacks",
           days=21, days_known=7, repair_days=40, ramp_days=2, cost=1_200_000, cost_known=400_000,
           early="Thermal cameras catch the fire small; strain gauges say whether the deck kept its strength.",
           sensors=["thermal_camera", "strain"],
           steps=["Fight the fire and close the area", "Test the concrete for fire damage",
                  "Repair the spalled deck", "Replace cables and lights lost"]),
    _event("fire_vessel", "Fire on a ship alongside", "Fire and explosion", 40,
           "A ship's cargo burns at the berth for days: the quay edge, fenders and bollards beside her are damaged.",
           damage=[(("fender",), 0.5, "critical"), (("bollard",), 0.3, "warning"), (("slab",), 0.3, "warning")],
           radius=120, warn_h=0.5, warn_with="thermal cameras along the berth",
           days=30, days_known=10, repair_days=60, ramp_days=5, cost=3_000_000, cost_known=1_200_000,
           early="Seen early, the ship is towed off before the quay heats through.",
           sensors=["thermal_camera"],
           steps=["Fight the fire, tow the ship off if safe", "Cool and inspect the quay edge",
                  "Replace fenders and bollards", "Repair the deck edge"]),
    _event("dg_explosion", "Dangerous goods explosion", "Fire and explosion", 500,
           "Stored dangerous goods explode, as in Beirut 2020 or Tianjin 2015: everything near is destroyed.",
           damage=[(tuple(), 0.6, "critical")], radius=400,
           days=365, days_known=300, repair_days=720, ramp_days=90, cost=150_000_000, cost_known=120_000_000, power=True,
           early="Gas and temperature sensors in the dangerous goods yard, and an inventory that is tracked, stop it happening at all.",
           sensors=["gas_detector", "thermal_camera"],
           steps=["Evacuate and fight fires", "Make safe and clear wreckage", "Assess every structure",
                  "Rebuild", "Reopen in stages"]),
    _event("oil_spill", "Oil spill in the basin", "Fire and explosion", 15,
           "A ship spills fuel: berthing stops while booms are laid and the quay is cleaned.",
           share=0.7, days=5, days_known=2, ramp_days=1, cost=1_000_000, cost_known=300_000,
           early="Booms ready and hydrocarbon sensors at the berth catch it small.",
           sensors=["hydrocarbon"],
           steps=["Lay booms", "Skim and clean", "Clean fenders and the quay face", "Reopen berthing"]),
    _event("war_indirect", "War in the region", "Force majeure", 50,
           "Shipping lines avoid the region: trade falls by nearly half for years. Nothing is damaged.",
           fall=0.45, fall_months=36, fall_known=0.4,
           early="Little to save: keep the costs down and win back the lines first.",
           steps=["Cut costs to the trade left", "Keep the berth maintained", "Win back the lines when it ends"]),
    _event("war_direct", "War, the port hit", "Force majeure", 200,
           "A missile or bomb hits the berth: cranes, wall and deck destroyed around the impact.",
           damage=[(tuple(), 0.7, "critical")], radius=200,
           days=270, days_known=200, repair_days=540, ramp_days=60, cost=40_000_000, cost_known=32_000_000, power=True,
           early="Sensors map the damage at once so sound parts reopen; spares and contractors agreed in advance start the rebuild.",
           sensors=["strain", "tilt", "accelerometer"],
           steps=["Evacuate", "Make safe and clear unexploded ordnance", "Map the damage", "Reopen the sound parts",
                  "Rebuild the destroyed bays and cranes"]),
    _event("sabotage", "Sabotage or terrorism", "Force majeure", 100,
           "Explosives or deliberate damage at a pile cap or a crane.",
           damage=[(("pile",), 0.4, "critical"), (("slab", "beam"), 0.3, "warning")],
           radius=30, days=45, days_known=20, repair_days=90, ramp_days=7, cost=5_000_000, cost_known=3_000_000,
           early="CCTV, intrusion and vibration alarms raise it in time; strain gauges show what still carries load.",
           sensors=["cctv", "accelerometer", "strain"],
           steps=["Secure the site", "Make safe", "Assess the damage", "Repair", "Raise security"]),
    _event("pandemic", "Pandemic", "Trade", 30,
           "Trade falls by a quarter for a year and a half; crews short.",
           fall=0.25, fall_months=18, fall_known=0.2,
           early="Plans for shift bubbles and remote operation keep more of the work.",
           steps=["Shift bubbles and remote work", "Keep essential cargo moving", "Clear the backlog"]),
    _event("siltation", "Siltation of the berth pocket", "Trade", 5,
           "Silt builds up: ships must come in light, carrying fewer containers, until it is dredged.",
           fall=0.15, fall_months=4, fall_known=0.0, cost=2_000_000, cost_known=1_200_000,
           early="Regular bed-level surveys plan the dredging before the depth is lost.",
           sensors=["bathymetry"],
           steps=["Survey the depth", "Tell the lines the draught", "Dredge", "Survey again"]),
]
BY_KEY = {e["key"]: e for e in EVENTS}

# What each sensor the events call on is, for the words on the page.
SENSOR_WORDS = {
    "weather_station": "weather station", "wave_buoy": "wave buoy", "fender_load": "fender load cells",
    "tide_gauge": "tide gauge", "drain_level": "drain level sensors", "strain": "strain gauges", "tilt": "tilt meters",
    "accelerometer": "accelerometers", "rail_survey": "rail alignment survey", "settlement": "settlement markers",
    "piezometer": "piezometers", "bathymetry": "bed-level surveys", "corrosion": "corrosion probes",
    "half_cell": "half-cell potential", "berthing_aid": "berthing aid system", "power_monitor": "power monitoring",
    "network_monitor": "network monitoring", "thermal_camera": "thermal cameras", "gas_detector": "gas detectors",
    "hydrocarbon": "hydrocarbon sensors", "cctv": "CCTV and intrusion alarms",
}
FIELDS = ("years", "days", "days_known", "cost", "cost_known", "radius")
DAYS_IN_MONTH = 365.25 / 12


def event_for(key: str, given: dict[str, Any] | None = None) -> dict[str, Any]:
    """One event with the person's changes (``ev_<key>_<field>``)."""
    e = dict(BY_KEY[key])
    for f in FIELDS:
        raw = (given or {}).get(f"ev_{key}_{f}")
        if raw in (None, ""):
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0 and (f != "years" or value >= 1):
            e[f] = value
    e["on"] = str((given or {}).get(f"ev_{key}_on", "1")).lower() not in ("0", "false", "off", "no")
    return e


def berth_length(elements: Iterable[Any]) -> float:
    """The length of the quay, metres: along the fenders where there are some, otherwise along
    everything, joining near neighbours (so a quay in several legs is measured round its bends)."""
    els = [dict(e) for e in elements]
    pts = [(e.get("x") or 0.0, e.get("y") or 0.0) for e in els if e.get("kind") == "fender"]
    if len(pts) < 4:
        pts = [(e.get("x") or 0.0, e.get("y") or 0.0) for e in els]
    if len(pts) < 2:
        return 300.0
    cell = 15.0
    while True:
        cells = sorted({(round(x / cell), round(y / cell)) for x, y in pts})
        if len(cells) <= 400:
            break
        cell *= 1.5
    pts = [(i * cell, j * cell) for i, j in cells]
    # A minimum spanning tree over the cells, leaving out jumps across open water.
    inside, best = {0}, [math.dist(pts[0], p) for p in pts]
    total = 0.0
    for _ in range(len(pts) - 1):
        k = min((i for i in range(len(pts)) if i not in inside), key=lambda i: best[i])
        if best[k] < 100:
            total += best[k]
        inside.add(k)
        for i in range(len(pts)):
            if i not in inside:
                best[i] = min(best[i], math.dist(pts[k], pts[i]))
    return max(total, 50.0)


def _hit(asset_id: int, e: dict[str, Any], elements: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str], tuple[float, float] | None]:
    """Which elements the event damages and which lie in the area it closes, drawn the same way
    every time for this asset and event."""
    rng = random.Random(f"{asset_id}:{e['key']}")
    centre = None
    if e["radius"]:
        front = [x for x in elements if x["kind"] in ("fender", "pile")] or elements
        if front:
            c = rng.choice(sorted(front, key=lambda x: (x.get("x") or 0, x["name"])))
            centre = (c.get("x") or 0.0, c.get("y") or 0.0)
    area = [x for x in elements if centre is None or math.dist(centre, (x.get("x") or 0.0, x.get("y") or 0.0)) <= e["radius"]]
    if not e["radius"] and not e["damage"]:
        area = []
    damaged: dict[str, dict[str, Any]] = {}
    for kinds, share, state in e["damage"]:
        for x in area:
            if (not kinds or x["kind"] in kinds) and x["name"] not in damaged and rng.random() < share:
                damaged[x["name"]] = {"ref": x.get("model_ref") or x["name"], "name": x["name"], "kind": x["kind"], "state": state}
    if e["damage"] and area and not damaged:
        # Whatever the dice say, the event hits something: the nearest of the kinds it damages first.
        kinds, _, state = e["damage"][0]
        near = [x for x in area if not kinds or x["kind"] in kinds] or area
        x = min(near, key=lambda x: math.dist(centre or (0.0, 0.0), (x.get("x") or 0.0, x.get("y") or 0.0)))
        damaged[x["name"]] = {"ref": x.get("model_ref") or x["name"], "name": x["name"], "kind": x["kind"], "state": state}
    closed = [x.get("model_ref") or x["name"] for x in area] if e["radius"] else []
    return list(damaged.values()), closed, centre


def assess(asset: Any, elements: Iterable[Any], key: str, rates: dict[str, float], given: dict[str, Any] | None = None,
           life: int = 50, length: float | None = None) -> dict[str, Any]:
    """One event at this berth: what it damages and closes, the time, the cost not knowing and
    knowing early, the saving, and what it is expected to cost over the design life."""
    e = event_for(key, given)
    els = [dict(x) for x in elements]
    length = length or berth_length(els)
    damaged, closed_refs, centre = _hit(asset["id"], e, els)
    if e["share"] is not None:
        share = e["share"]
    elif e["radius"]:
        share = min(1.0, 2 * e["radius"] / length)
    elif e["days"]:
        share = 1.0
    else:
        share = 0.0
    per_day, value = rates["moves_per_day"], rates["value_per_move"]

    def cost(days: float, repair: float, fall: float) -> dict[str, Any]:
        lost = per_day * share * (days + 0.5 * e["ramp_days"]) + per_day * fall * e["fall_months"] * DAYS_IN_MONTH
        return {"days": days, "lost": round(lost), "lost_value": round(lost * value), "repair": round(repair),
                "total": round(lost * value + repair)}

    blind = cost(e["days"], e["cost"], e["fall"])
    known = cost(e["days_known"], e["cost_known"], e["fall_known"])
    chance = 1 / e["years"]
    by_kind: dict[str, int] = {}
    for d in damaged:
        by_kind[d["kind"]] = by_kind.get(d["kind"], 0) + 1
    return {
        **e, "share": share, "closed_m": round(min(length, 2 * e["radius"])) if e["radius"] else (round(length * share) if share else 0),
        "length": round(length), "blind": blind, "known": known, "saving": blind["total"] - known["total"],
        "chance": chance, "in_life": 1 - (1 - chance) ** life,
        "expected": round(chance * life * blind["total"]), "expected_saving": round(chance * life * (blind["total"] - known["total"])),
        "damaged": damaged, "by_kind": by_kind, "closed_refs": closed_refs, "centre": centre,
        "back_in": e["days"] + e["ramp_days"], "back_in_known": e["days_known"] + e["ramp_days"],
        "sensor_words": [SENSOR_WORDS.get(s, s) for s in e["sensors"]],
    }


def catalogue(asset: Any, elements: Iterable[Any], rates: dict[str, float], given: dict[str, Any] | None = None,
              life: int = 50) -> list[dict[str, Any]]:
    els = [dict(x) for x in elements]
    length = berth_length(els)
    return [assess(asset, els, e["key"], rates, given, life, length) for e in EVENTS]
