"""MarineTwin beyond the structure: the terminal's equipment, environment, carbon and safety.

A port asset is more than its piles and deck. The people who run it ask about
the cranes and the tractors (what is due for maintenance, what keeps breaking),
the air on the quay and in the offices, the carbon the terminal emits and the
certificates it has to keep current, and the safety of the people working there
and the security of the gate. Each of those is a module here, answering the same
three questions as the rest of MarineTwin: how it is now, what is coming, and
what to do.

**For the prototype every feed in this module is simulated**, deterministically
per asset (and, where it moves, per day or hour), in the shapes the real systems
would supply: the CMMS for maintenance, the building management system and the
air-quality stations, the energy meters and fuel log, the permit and incident
registers, access control and CCTV.

The limits are published ones where they exist: WHO 2021 air-quality guidelines,
ISO 10816-3 vibration zones, the usual office comfort ranges, the WBGT heat
stress thresholds, and LOLER's examination intervals for lifting equipment.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta
from typing import Any

from . import marine


def _rng(asset_id: int, *what: Any) -> random.Random:
    return random.Random("marinetwin-facility:" + ":".join(str(w) for w in (asset_id, *what)))


def _commissioned(asset: Any) -> date:
    try:
        return date.fromisoformat(str(asset["commissioned"])[:10])
    except (TypeError, ValueError):
        return date(2016, 1, 1)


def _state_of(value: float, alert: float | None, alarm: float | None, lower_worse: bool = False) -> str:
    if alarm is not None and (value <= alarm if lower_worse else value >= alarm):
        return "critical"
    if alert is not None and (value <= alert if lower_worse else value >= alert):
        return "warning"
    return "good"


def _worst(states: list[str]) -> str:
    return max(states, key=lambda s: marine.STATE_RANK.get(s, 0), default="good")


ORDER = {"critical": 0, "warning": 1, "good": 2}


def _sorted(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(actions, key=lambda a: ORDER.get(a["state"], 3))


# --- the asset register ---------------------------------------------------------------

# tag prefix, count, type, make and model, location, life (years), criticality, value (USD), PM interval (h)
FLEET = [
    ("STS", 3, "Ship-to-shore crane", "ZPMC 65 t twin-lift", "Quay", 25, "A", 11_500_000, 500),
    ("RTG", 8, "Rubber-tyred gantry", "Konecranes 41 t hybrid", "Yard", 20, "A", 2_100_000, 500),
    ("RS", 2, "Reach stacker", "Kalmar DRG450", "Yard", 12, "B", 650_000, 250),
    ("TT", 18, "Terminal tractor", "Terberg YT203", "Fleet", 10, "B", 140_000, 250),
    ("SS", 2, "Substation 11/0.4 kV", "ABB UniGear", "Services", 30, "A", 900_000, 4380),
    ("SP", 1, "Shore power unit", "Cavotec 6.6 kV", "Quay", 20, "B", 1_800_000, 2190),
    ("HM", 6, "High-mast lighting", "30 m LED", "Yard", 25, "C", 60_000, 4380),
    ("FP", 2, "Fire pump", "Diesel 250 m³/h", "Services", 20, "A", 120_000, 730),
    ("OCR", 2, "Gate OCR portal", "Camco", "Gate", 10, "B", 300_000, 2190),
    ("HVAC", 1, "Air handling, admin building", "Carrier", "Buildings", 15, "C", 250_000, 2190),
]
SERVICES = FLEET[4:]                     # substations, shore power, lighting, fire pumps, gate, HVAC
FLEET_BY_TERMINAL = {
    "container": FLEET,
    "general_cargo": [
        ("MHC", 2, "Mobile harbour crane", "Liebherr LHM 550", "Quay", 25, "A", 6_500_000, 500),
        ("FL", 8, "Forklift", "Kalmar DCG160", "Shed", 10, "B", 180_000, 250),
        ("RS", 2, "Reach stacker", "Kalmar DRG450", "Yard", 12, "B", 650_000, 250),
        ("TT", 10, "Terminal tractor", "Terberg YT203", "Fleet", 10, "B", 140_000, 250),
    ] + SERVICES,
    "roro": [
        ("RR", 2, "Linkspan / shore ramp", "Hydraulic linkspan 30 m", "Quay", 30, "A", 4_000_000, 1000),
        ("TM", 8, "Tug master", "Terberg RT223", "Fleet", 10, "B", 160_000, 250),
        ("SB", 4, "Driver shuttle bus", "Coaster 30 seat", "Fleet", 8, "C", 90_000, 250),
        ("RS", 1, "Reach stacker", "Kalmar DRG450", "Yard", 12, "B", 650_000, 250),
    ] + SERVICES,
    "bulk": [
        ("SU", 2, "Grab ship unloader", "Konecranes 1,500 t/h", "Quay", 25, "A", 9_000_000, 500),
        ("CV", 4, "Belt conveyor", "1,600 mm belt", "Yard", 20, "A", 1_200_000, 730),
        ("SR", 2, "Stacker-reclaimer", "FLSmidth", "Stockyard", 25, "A", 7_000_000, 500),
        ("WL", 3, "Wheel loader", "CAT 980", "Stockyard", 10, "B", 450_000, 250),
    ] + SERVICES,
}
FLEET_BY_TERMINAL["multipurpose"] = FLEET_BY_TERMINAL["general_cargo"][:1] + FLEET[:1] + FLEET_BY_TERMINAL["general_cargo"][1:]
CRANES = {"STS", "RTG", "MHC", "SU", "SR"}       # what carries a hoist gearbox worth monitoring
DOCUMENTS = {
    "MHC": ["O&M manual", "LOLER certificate", "Load test report"],
    "FL": ["O&M manual", "LOLER certificate"],
    "RR": ["O&M manual", "Load test report", "Hinge inspection record"],
    "TM": ["O&M manual"], "SB": ["O&M manual"], "WL": ["O&M manual"],
    "SU": ["O&M manual", "LOLER certificate", "Load test report"],
    "CV": ["O&M manual", "Belt splice record"], "SR": ["O&M manual", "LOLER certificate"],
    "STS": ["O&M manual", "LOLER certificate", "Load test report", "As-built drawings"],
    "RTG": ["O&M manual", "LOLER certificate"],
    "RS": ["O&M manual", "LOLER certificate"],
    "TT": ["O&M manual"],
    "SS": ["Single-line diagram", "Protection settings", "Test certificates"],
    "SP": ["O&M manual", "IEC 80005-1 compliance", "Single-line diagram"],
    "HM": ["Lighting design", "Structural certificate"],
    "FP": ["O&M manual", "Flow test record"],
    "OCR": ["O&M manual"],
    "HVAC": ["O&M manual", "Commissioning record"],
}


def register(asset: Any) -> list[dict[str, Any]]:
    """The equipment on the asset, one row per unit. Fixed for an asset: a register does not move."""
    asset_id = int(asset["id"])
    start = _commissioned(asset)
    rng = _rng(asset_id, "register")
    out = []
    terminal = asset["terminal_type"] if "terminal_type" in asset.keys() else "container"
    for prefix, count, kind, model, where, life, crit, value, pm in FLEET_BY_TERMINAL.get(terminal, FLEET):
        for n in range(1, count + 1):
            tag = f"{prefix}{n:02d}" if count > 3 else f"{prefix}{n}"
            installed = start + timedelta(days=rng.choice([0, 0, 0, 365, 730, 1460]))
            age = (date.today() - installed).days / 365.25
            out.append({
                "tag": tag, "kind": kind, "model": model, "where": where, "installed": installed,
                "age": round(age, 1), "life": life, "life_used": round(100 * age / life), "criticality": crit,
                "value": value, "pm_interval": pm, "prefix": prefix,
                "warranty": installed + timedelta(days=365 * (5 if crit == "A" else 2)),
                "documents": DOCUMENTS.get(prefix, []),
            })
    return out


# --- maintenance -------------------------------------------------------------------------

WO_TEXT = {
    "MHC": ["Slewing ring greasing", "Grab hydraulics leak", "Outrigger pad cracked", "Hoist rope inspection"],
    "FL": ["Mast chain adjustment", "Tyre replacement", "Hydraulic hose leak"],
    "RR": ["Hinge pin wear check", "Ramp hydraulic cylinder seal", "Flap tip plate cracked"],
    "TM": ["Fifth wheel lock adjustment", "Brake service"], "SB": ["Air conditioning fault", "Service"],
    "SU": ["Grab rope change", "Boom hoist brake pads", "Hopper liner worn"],
    "CV": ["Belt splice repair", "Idler bearing noise", "Belt misalignment"],
    "SR": ["Bucket wheel teeth worn", "Slew drive fault"], "WL": ["Bucket edge worn", "Service"],
    "STS": ["Hoist rope inspection and lubrication", "Spreader twistlock sensor replaced", "Boom hoist brake pads",
            "Trolley wheel bearing noise", "Gantry drive fault, inverter reset", "Anemometer calibration"],
    "RTG": ["Hydraulic leak on spreader", "Generator set service", "Tyre replacement, leg 3", "Gantry steering fault"],
    "RS": ["Boom cylinder seal leak", "Engine service"],
    "TT": ["Fifth wheel lock adjustment", "Brake service", "Tyre replacement", "Engine overheating"],
    "SS": ["Thermographic survey", "Breaker trip investigation"],
    "SP": ["Cable reel inspection", "Plug and socket inspection"],
    "HM": ["Lamp driver failure", "Raise and lower winch service"],
    "FP": ["Weekly run test", "Jockey pump pressure switch"],
    "OCR": ["Camera lens cleaning", "Plate recognition rate below 95%"],
    "HVAC": ["Filter change", "Chiller low refrigerant alarm"],
}
VIBRATION_LIMITS = (4.5, 7.1)        # mm/s RMS, ISO 10816-3 group 2 (rigid), zone C and zone D


def maintenance(asset: Any, today: date | None = None) -> dict[str, Any]:
    """Running hours against the service interval, reliability, condition monitoring and work orders."""
    today = today or date.today()
    asset_id = int(asset["id"])
    units = register(asset)
    rng = _rng(asset_id, "maintenance", today.isoformat())
    rows, actions = [], []
    late_tractors: list[str] = []
    for unit in units:
        hours_since = rng.uniform(0.1, 1.04) * unit["pm_interval"]
        to_next = round(unit["pm_interval"] - hours_since)
        mtbf = rng.uniform(250, 900) if unit["criticality"] != "C" and unit["pm_interval"] <= 500 else rng.uniform(2000, 8000)
        mttr = rng.uniform(2, 8)
        availability = 100 * mtbf / (mtbf + mttr)
        row = {**unit, "to_next": to_next, "mtbf": round(mtbf), "mttr": round(mttr, 1),
               "availability": round(availability, 1), "vibration": None, "states": []}
        if unit["prefix"] in CRANES:
            base = rng.uniform(1.2, 3.5)
            drift = rng.choice([0, 0, 0, 0.12, 0.3])          # mm/s a week, for a gearbox going bad
            row["vibration"] = round(base + drift * 8, 1)
            row["vibration_trend"] = [round(base + drift * w + rng.gauss(0, 0.15), 2) for w in range(9)]
            v_state = _state_of(row["vibration"], *VIBRATION_LIMITS)
            row["states"].append(v_state)
            if v_state != "good":
                weeks = (VIBRATION_LIMITS[1] - row["vibration"]) / drift if drift and v_state == "warning" else None
                actions.append({"state": v_state, "area": "Equipment", "tag": unit["tag"],
                                "text": f"{unit['tag']} hoist gearbox vibration is {row['vibration']} mm/s, "
                                        f"{'in ISO 10816 zone D' if v_state == 'critical' else 'in zone C'}"
                                        + (f" and rising; at this rate it reaches zone D in about {weeks:.0f} weeks" if weeks else "")
                                        + ". Take an oil sample and a vibration spectrum, and plan a bearing inspection"
                                        + (" before the next ship." if v_state == "critical" else " at the next service.")})
        if to_next < 0:
            state = "critical" if unit["criticality"] == "A" else "warning"
            row["states"].append(state)
            if unit["prefix"] in ("TT", "TM", "FL", "SB"):
                late_tractors.append(unit["tag"])
            else:
                actions.append({"state": state, "area": "Equipment", "tag": unit["tag"],
                                "text": f"{unit['tag']} ({unit['kind']}) is {-to_next} running hours past its "
                                        f"{unit['pm_interval']} h service. Book it into the next gap between ships."})
        elif to_next < 0.1 * unit["pm_interval"]:
            row["states"].append("warning")
        if availability < 98 and unit["criticality"] == "A":
            row["states"].append("warning")
        row["state"] = _worst(row["states"])
        rows.append(row)

    if late_tractors:
        actions.append({"state": "warning", "area": "Equipment", "tag": "fleet",
                        "text": f"{len(late_tractors)} fleet vehicle{'s are' if len(late_tractors) > 1 else ' is'} past the 250 h service "
                                f"({', '.join(late_tractors)}). Rotate them through the workshop on the night shift."})

    # Work orders open in the CMMS.
    orders = []
    for i in range(rng.randint(8, 14)):
        unit = rng.choice([u for u in units if u["prefix"] in WO_TEXT])
        kind = rng.choice(["Corrective", "Corrective", "Preventive", "Inspection"])
        priority = rng.choice(["P1", "P2", "P2", "P3", "P3"]) if kind == "Corrective" else "P3"
        age = rng.randint(0, 20)
        status = rng.choice(["Open", "In progress", "Waiting for parts"])
        orders.append({"number": f"WO-{today:%y}{asset_id:02d}{4100 + i * 7}", "tag": unit["tag"], "kind": kind,
                       "priority": priority, "text": rng.choice(WO_TEXT[unit["prefix"]]),
                       "opened": today - timedelta(days=age), "age": age, "status": status})
    orders.sort(key=lambda o: (o["priority"], -o["age"]))
    for o in orders:
        if o["priority"] == "P1" and o["age"] >= 2:
            actions.append({"state": "critical", "area": "Equipment", "tag": o["tag"],
                            "text": f"{o['number']} on {o['tag']} ({o['text'].lower()}) is a P1 open for {o['age']} days"
                                    + (", waiting for parts. Chase the order or take the part from a spare unit." if o["status"] == "Waiting for parts"
                                       else ". Escalate it to the maintenance manager.")})
    fleet = {}
    for row in rows:
        f = fleet.setdefault(row["kind"], {"kind": row["kind"], "units": 0, "availability": 0.0, "overdue": 0, "due": 0})
        f["units"] += 1
        f["availability"] += row["availability"]
        f["overdue"] += row["to_next"] < 0
        f["due"] += 0 <= row["to_next"] < 0.1 * row["pm_interval"]
    for f in fleet.values():
        f["availability"] = round(f["availability"] / f["units"], 1)
    return {"units": rows, "orders": orders, "fleet": list(fleet.values()), "actions": _sorted(actions),
            "overdue": sum(1 for r in rows if r["to_next"] < 0),
            "open_orders": len(orders), "p1": sum(1 for o in orders if o["priority"] == "P1"),
            "availability": round(sum(r["availability"] for r in rows if r["criticality"] == "A")
                                  / max(1, sum(1 for r in rows if r["criticality"] == "A")), 1),
            "replacement_value": sum(r["value"] for r in rows),
            "vibration_limits": VIBRATION_LIMITS}


# --- comfort and air quality --------------------------------------------------------------

# key: name, unit, alert, alarm, lower_worse, what the limit is
MEASURES = {
    "temp": ("Temperature", "°C", 26.0, 28.0, False, "comfort range 20–26 °C"),
    "rh": ("Relative humidity", "%", 60.0, 70.0, False, "comfort range 30–60%"),
    "co2": ("CO₂", "ppm", 1000.0, 1500.0, False, "fresh air: alert 1,000, act 1,500 ppm"),
    "noise_in": ("Noise", "dB(A)", 55.0, 65.0, False, "open office 55 dB(A)"),
    "pm25": ("PM2.5", "µg/m³", 15.0, 37.5, False, "WHO 2021 24-hour guideline 15, interim target 37.5"),
    "pm10": ("PM10", "µg/m³", 45.0, 75.0, False, "WHO 2021 24-hour guideline 45, interim target 75"),
    "no2": ("NO₂", "µg/m³", 25.0, 50.0, False, "WHO 2021 24-hour guideline 25, interim target 50"),
    "so2": ("SO₂", "µg/m³", 40.0, 125.0, False, "WHO 2021 24-hour guideline 40, interim target 125"),
    "noise_out": ("Noise", "dB(A)", 70.0, 85.0, False, "70 dB(A) at the boundary, 85 hearing protection"),
    "wbgt": ("Heat stress (WBGT)", "°C", 28.0, 32.0, False, "WBGT 28 °C work/rest cycles, 32 °C stop heavy work"),
}
STATIONS = [
    ("admin", "Admin building, open office", "indoor", ["temp", "rh", "co2", "noise_in"]),
    ("control", "Control room", "indoor", ["temp", "rh", "co2", "noise_in"]),
    ("berth", "Quay, berth 1", "outdoor", ["so2", "no2", "pm25", "noise_out", "wbgt"]),
    ("gate", "Gate", "outdoor", ["pm25", "pm10", "no2", "noise_out"]),
    ("yard", "Yard, RTG block C", "outdoor", ["pm25", "pm10", "wbgt"]),
]
# Which measures are judged on their 24-hour mean (air quality) rather than the latest hour.
DAILY_MEAN = {"pm25", "pm10", "no2", "so2"}


def _series(rng: random.Random, key: str, station: str, hours: list[datetime], ship_alongside: bool) -> list[float]:
    """One measure over the last day, with the shape it has in a port."""
    out = []
    bump = rng.choice([0, 0, 0, 1])                          # some days something is off
    for at in hours:
        h = at.hour + at.minute / 60
        day = math.sin(math.pi * max(0.0, min(1.0, (h - 6) / 13)))       # 0 at night, 1 mid-afternoon
        busy = 1.0 if 7 <= h <= 21 else 0.35                             # gate and yard traffic
        if key == "temp":
            v = 22.5 + 1.2 * day + (2.8 * day if bump and station == "control" else 0) + rng.gauss(0, 0.2)
        elif key == "rh":
            v = 48 - 6 * day + rng.gauss(0, 1.5)
        elif key == "co2":
            occupied = 1.0 if 8 <= h <= 17 else 0.0
            v = 450 + occupied * (450 + 300 * day) * (1.6 if bump and station == "control" else 1.0) + rng.gauss(0, 25)
        elif key == "noise_in":
            v = 38 + (12 if 8 <= h <= 17 else 0) + rng.gauss(0, 2)
        elif key == "pm25":
            v = 6 + 8 * busy * (1.3 if station == "gate" else 1.0) + 12 * bump * day + rng.gauss(0, 1.5)
        elif key == "pm10":
            v = 18 + 20 * busy + 25 * bump * day + rng.gauss(0, 3)
        elif key == "no2":
            v = 8 + 11 * busy * (1.3 if station == "gate" else 1.0) + (8 if ship_alongside and station == "berth" else 0) + 10 * bump + rng.gauss(0, 2)
        elif key == "so2":
            v = 4 + (14 + 40 * bump if ship_alongside else 0) * (0.6 + 0.4 * day) + rng.gauss(0, 2)
        elif key == "noise_out":
            v = 56 + 9 * busy + 6 * bump + rng.gauss(0, 2)
        elif key == "wbgt":
            v = 22 + 6.5 * day + 3 * bump * day + rng.gauss(0, 0.3)
        else:
            v = 0.0
        out.append(round(max(v, 0.0), 1))
    return out


ADVICE = {
    "temp": "Check the cooling in the {place}: setpoint, filters and the chiller's alarms.",
    "rh": "Check the dehumidification in the {place}.",
    "co2": "Raise the fresh-air rate in the {place}; the air handling unit's outdoor damper may be stuck.",
    "noise_in": "Find the source of the noise in the {place}.",
    "pm25": "Dust at the {place}: water the unpaved areas and check the tractors' exhausts.",
    "pm10": "Dust at the {place}: water the unpaved areas and sweep the gate approach.",
    "no2": "Exhaust at the {place}: cut idling at the gate and stagger the truck slots.",
    "so2": "Ship exhaust at the {place}: ask the ship alongside to plug into shore power or confirm its fuel is 0.1% sulphur.",
    "noise_out": "Noise at the {place}: hearing protection in the zone, and check the neighbours' boundary reading.",
    "wbgt": "Heat stress at the {place}: work/rest cycles, shade and water for everyone outside{stop}.",
}


def environment(asset: Any, now: datetime | None = None, ship_alongside: bool = True) -> dict[str, Any]:
    """Each station's measures over the last 24 hours, judged against their limits."""
    now = (now or datetime.now()).replace(minute=0, second=0, microsecond=0)
    asset_id = int(asset["id"])
    hours = [now - timedelta(hours=23 - i) for i in range(24)]
    stations, actions = [], []
    for key, place, inside, measures in STATIONS:
        rows = []
        for m in measures:
            name, unit, alert, alarm, lower, note = MEASURES[m]
            rng = _rng(asset_id, "env", now.date().isoformat(), key, m)
            values = _series(rng, m, key, hours, ship_alongside)
            latest, mean, peak = values[-1], sum(values) / len(values), max(values)
            judged = mean if m in DAILY_MEAN else latest
            state = _state_of(judged, alert, alarm, lower)
            rows.append({"key": m, "name": name, "unit": unit, "latest": latest, "mean": round(mean, 1), "peak": peak,
                         "alert": alert, "alarm": alarm, "note": note, "judged_on": "24-hour mean" if m in DAILY_MEAN else "latest hour",
                         "state": state, "values": values})
            if state != "good":
                text = ADVICE[m].format(place=place.lower() if inside == "indoor" else place.split(",")[0].lower(),
                                        stop="; stop heavy work in the afternoon" if state == "critical" else "")
                actions.append({"state": state, "area": "Comfort" if inside == "indoor" else "Air quality",
                                "text": f"{name} at {place} is {judged:,.1f} {unit} ({'24-hour mean' if m in DAILY_MEAN else 'now'}), "
                                        f"over {alarm if state == 'critical' else alert:,.0f} {unit}. {text}"})
        stations.append({"key": key, "place": place, "inside": inside, "measures": rows,
                         "state": _worst([r["state"] for r in rows])})
    timeline = [{"at": at, "past": True, **{f"{s['key']}_{r['key']}": r["values"][i] for s in stations for r in s["measures"]}}
                for i, at in enumerate(hours)]
    return {"now": now, "stations": stations, "actions": _sorted(actions), "timeline": timeline,
            "indoor": [s for s in stations if s["inside"] == "indoor"],
            "outdoor": [s for s in stations if s["inside"] == "outdoor"]}


# --- carbon -----------------------------------------------------------------------------

DIESEL = 2.68          # kg CO2e per litre
GRID = 0.40            # kg CO2e per kWh, a typical Gulf grid; set per country
AUX_ENGINE = 0.70      # kg CO2e per kWh from a ship's auxiliary engines at berth
TARGET_CUT = 4.2       # % a year, a 1.5 °C-aligned linear reduction


def carbon(asset: Any, today: date | None = None) -> dict[str, Any]:
    """Twelve months of energy and fuel, as emissions by scope and per container move."""
    today = today or date.today()
    asset_id = int(asset["id"])
    rng = _rng(asset_id, "carbon")
    months = []
    first = date(today.year - 2, today.month, 1)
    for i in range(24):
        y, m = first.year + (first.month - 1 + i) // 12, (first.month - 1 + i) % 12 + 1
        season = 1 + 0.18 * math.sin(2 * math.pi * (m - 4) / 12)            # cooling load in summer
        moves = round(rng.uniform(52000, 68000))
        electricity = round((moves * rng.uniform(5.6, 6.2) + 260000 * season) * (1 - 0.003 * i))  # kWh: cranes, reefers, lighting, buildings
        diesel = round(moves * rng.uniform(0.98, 1.08) * (1 - 0.003 * i))     # litres: RTGs, tractors, reach stackers
        shore = round(rng.uniform(0.15, 0.35) * (1 + 0.08 * i) * 400000)      # kWh delivered to ships
        scope1 = diesel * DIESEL / 1000
        scope2 = electricity * GRID / 1000          # shore power is reported apart: it replaces the ships' own engines
        avoided = shore * (AUX_ENGINE - GRID) / 1000
        months.append({"month": date(y, m, 1), "moves": moves, "electricity": electricity, "diesel": diesel,
                       "shore": shore, "scope1": round(scope1, 1), "scope2": round(scope2, 1),
                       "total": round(scope1 + scope2, 1), "avoided": round(avoided, 1),
                       "intensity": round(1000 * (scope1 + scope2) / moves, 2)})
    before, months = months[:12], months[12:]
    total = sum(m["total"] for m in months)
    moves = sum(m["moves"] for m in months)
    previous = 1000 * sum(m["total"] for m in before) / sum(m["moves"] for m in before)
    change = 100 * (1000 * total / moves - previous) / previous
    on_track = change <= -TARGET_CUT * 0.75
    actions = []
    if not on_track:
        actions.append({"state": "warning", "area": "Carbon",
                        "text": f"Carbon per move {'fell' if change < 0 else 'rose'} {abs(change):.1f}% on the year before, against a {TARGET_CUT}% cut a year. "
                                f"Diesel is {100 * sum(m['scope1'] for m in months) / total:.0f}% of the total: "
                                f"price converting the tractors to electric or the RTGs to cable reel."})
    share_shore = sum(m["shore"] for m in months[-3:]) / 3
    return {"months": months, "total": round(total), "scope1": round(sum(m["scope1"] for m in months)),
            "scope2": round(sum(m["scope2"] for m in months)), "avoided": round(sum(m["avoided"] for m in months)),
            "moves": moves, "intensity": round(1000 * total / moves, 2), "change": round(change, 1),
            "previous_intensity": round(previous, 2),
            "target": TARGET_CUT, "on_track": on_track, "shore_monthly": round(share_shore),
            "factors": {"diesel": DIESEL, "grid": GRID, "aux": AUX_ENGINE}, "actions": actions}


# --- compliance ---------------------------------------------------------------------------

# what, regime, every (months), who it applies to
OBLIGATIONS = [
    ("Thorough examination, STS cranes", "LOLER 1998 reg. 9", 12, "STS"),
    ("Thorough examination, RTGs", "LOLER 1998 reg. 9", 12, "RTG"),
    ("Thorough examination, reach stackers", "LOLER 1998 reg. 9", 12, "RS"),
    ("Thorough examination, harbour cranes", "LOLER 1998 reg. 9", 12, "MHC"),
    ("Thorough examination, forklifts", "LOLER 1998 reg. 9", 12, "FL"),
    ("Thorough examination, ship unloaders", "LOLER 1998 reg. 9", 12, "SU"),
    ("Linkspan hinge and load inspection", "Owner's inspection regime", 12, "RR"),
    ("Principal inspection of the quay", "BS 6349-1-1 / owner's inspection regime", 72, None),
    ("General inspection of the quay", "BS 6349-1-1 / owner's inspection regime", 24, None),
    ("Port facility security assessment review", "ISPS Code, Part A 15", 12, None),
    ("Port facility security plan drill", "ISPS Code, Part B 18.5", 3, None),
    ("Environmental permit renewal", "Environmental authority", 36, None),
    ("Air quality report to the regulator", "Environmental permit condition", 3, None),
    ("Greenhouse gas emissions report", "GHG Protocol, corporate standard", 12, None),
    ("Fire pump and sprinkler test", "NFPA 25", 3, "FP"),
    ("Electrical installation inspection", "IEC 60364-6", 12, "SS"),
    ("Shore power safety inspection", "IEC/IEEE 80005-1", 12, "SP"),
    ("ISO 14001 surveillance audit", "ISO 14001:2015", 12, None),
    ("ISO 45001 surveillance audit", "ISO 45001:2018", 12, None),
    ("Port waste reception record", "MARPOL, port reception facilities", 1, None),
]


def compliance(asset: Any, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    rng = _rng(int(asset["id"]), "compliance")
    items, actions = [], []
    present = {u["prefix"] for u in register(asset)}
    for what, regime, every, applies in OBLIGATIONS:
        if applies and applies not in present:
            continue
        # When it was last done: usually on time, sometimes slipping.
        slip = rng.choice([0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 0.97, 1.15])
        last = today - timedelta(days=round(slip * every * 30.44))
        due = last + timedelta(days=round(every * 30.44))
        days = (due - today).days
        state = "critical" if days < 0 else "warning" if days <= 30 else "good"
        items.append({"what": what, "regime": regime, "every": every, "last": last, "due": due, "days": days,
                      "state": state, "applies": applies})
        if state == "critical":
            actions.append({"state": "critical", "area": "Compliance",
                            "text": f"{what} was due {due:%d/%m/%Y}, {-days} days ago ({regime})."
                                    + (" Equipment past its thorough examination must not lift until it is done." if "LOLER" in regime else
                                       " Book it now and record why it slipped.")})
        elif state == "warning":
            actions.append({"state": "warning", "area": "Compliance",
                            "text": f"{what} is due {'today' if days == 0 else f'{due:%d/%m/%Y}, in {days} days'} ({regime}). Book it."})
    items.sort(key=lambda i: i["days"])
    return {"items": items, "actions": _sorted(actions),
            "overdue": sum(1 for i in items if i["state"] == "critical"),
            "due_soon": sum(1 for i in items if i["state"] == "warning")}


# --- safety and security --------------------------------------------------------------------

INCIDENTS = [
    ("Near miss", "Quay, under STS2", "Tractor entered the crane's lane while a box was being landed."),
    ("Near miss", "Yard, block C", "Pedestrian crossed the RTG travel path outside the walkway."),
    ("First aid", "Workshop", "Cut to the hand changing a hydraulic hose."),
    ("Near miss", "Quay, berth 1", "Mooring line parted while the ship was making fast; nobody in the snap-back zone."),
    ("Property damage", "Yard, block A", "Reach stacker struck a light mast base."),
    ("Medical treatment", "Lashing platform, STS1", "Lasher's finger trapped by a twistlock cone."),
    ("Environmental", "Quay, berth 2", "Hydraulic oil spill from RTG07, about 20 litres, contained with the spill kit."),
    ("Near miss", "Gate", "Truck driver left the cab in the inspection lane."),
    ("Lost time", "Quay, berth 1", "Slip on the quay ladder rungs during line handling; sprained ankle."),
    ("First aid", "Yard, block D", "Dust in the eye during high winds."),
]
PERMITS = [
    ("Hot work", "RTG workshop", "Welding a cracked spreader flipper"),
    ("Work at height", "STS2 boom", "Boom hoist rope inspection"),
    ("Confined space", "Fire pump pit", "Jockey pump replacement"),
    ("Electrical isolation", "Substation SS1", "Breaker maintenance"),
    ("Diving", "Berth 1, under the deck", "Underwater inspection of piles P03 to P06"),
]
CAMERA_ZONES = ["Gate", "Quay north", "Quay south", "Yard A", "Yard B", "Yard C", "Yard D", "Perimeter east",
                "Perimeter west", "Workshop", "Substation", "Admin building"]


def safety(asset: Any, now: datetime | None = None, twin: dict[str, Any] | None = None) -> dict[str, Any]:
    """Incidents and their rates, permits open now, and the state of security."""
    now = now or datetime.now()
    today = now.date()
    asset_id = int(asset["id"])
    rng = _rng(asset_id, "safety", today.isoformat())
    hist = _rng(asset_id, "safety-history")

    # The last 90 days of incidents; a long history drives the rates.
    log = []
    for i, (kind, where, text) in enumerate(INCIDENTS):
        days_ago = hist.randint(1, 30 if kind == "Near miss" else 88)    # near misses are reported most often
        status = "Closed" if days_ago > 21 or hist.random() < 0.4 else "Investigating"
        log.append({"date": today - timedelta(days=days_ago), "kind": kind, "where": where, "text": text,
                    "status": status, "age": days_ago})
    log.sort(key=lambda r: r["date"], reverse=True)
    hours_year = 1_150_000                                       # hours worked across the terminal in 12 months
    lti_year, recordable_year = hist.randint(1, 3), hist.randint(3, 7)
    last_lti = next((r for r in log if r["kind"] == "Lost time"), None)
    kpis = {
        "days_since_lti": (today - last_lti["date"]).days if last_lti else 365,
        "ltifr": round(lti_year * 1_000_000 / hours_year, 2),
        "trifr": round(recordable_year * 1_000_000 / hours_year, 2),
        "near_misses": sum(1 for r in log if r["kind"] == "Near miss" and r["age"] <= 30),
        "open": sum(1 for r in log if r["status"] == "Investigating"),
        "hours": hours_year,
    }

    permits = []
    for kind, where, text in rng.sample(PERMITS, rng.randint(2, 4)):
        issued = now - timedelta(hours=rng.uniform(1, 9))
        expires = issued + timedelta(hours=rng.choice([8, 10, 12]))
        permits.append({"kind": kind, "where": where, "text": text, "issued": issued, "expires": expires,
                        "left_h": round((expires - now).total_seconds() / 3600, 1)})

    level = 2 if rng.random() < 0.08 else 1
    offline = rng.sample(CAMERA_ZONES, rng.choice([0, 1, 1, 2]))
    cameras = {"total": 64, "online": 64 - len(offline) * rng.randint(1, 3), "offline_zones": offline}
    access = {"entries": rng.randint(1400, 2200), "denied": rng.randint(4, 30), "tailgating": rng.randint(0, 3)}
    alarms = [{"at": now - timedelta(hours=rng.uniform(0, 24)), "zone": rng.choice(["Perimeter east", "Perimeter west", "Quay south fence"]),
               "outcome": rng.choice(["False alarm, wildlife", "False alarm, wind", "Patrol attended, nothing found"])}
              for _ in range(rng.randint(0, 4))]
    alarms.sort(key=lambda a: a["at"], reverse=True)
    proximity = rng.randint(0, 9)                               # people detected in a crane's exclusion zone, 24 h

    actions = []
    for r in log:
        if r["status"] == "Investigating" and r["age"] > 14:
            actions.append({"state": "warning", "area": "Safety",
                            "text": f"The {r['kind'].lower()} on {r['date']:%d/%m} at {r['where']} has been under investigation for {r['age']} days. Close it out with its root cause and actions."})
        if r["kind"] in ("Lost time", "Medical treatment") and r["status"] == "Investigating":
            actions.append({"state": "critical", "area": "Safety",
                            "text": f"{r['kind']} on {r['date']:%d/%m} at {r['where']}: {r['text']} Complete the investigation and brief every shift."})
    for p in permits:
        if p["left_h"] <= 1.5:
            actions.append({"state": "warning", "area": "Safety",
                            "text": f"The {p['kind'].lower()} permit at {p['where']} expires in {max(p['left_h'], 0):.1f} h. Extend it or close the job out."})
    if proximity >= 5:
        actions.append({"state": "warning", "area": "Safety",
                        "text": f"People were detected in a crane's exclusion zone {proximity} times in 24 h. Run a toolbox talk on the quay walkways and check the barriers."})
    if offline:
        actions.append({"state": "critical" if "Gate" in offline or level > 1 else "warning", "area": "Security",
                        "text": f"CCTV is offline in {', '.join(offline)}. Raise a P1 with the security contractor and put a patrol on {'that zone' if len(offline) == 1 else 'those zones'} until it is back."})
    if level > 1:
        actions.append({"state": "critical", "area": "Security",
                        "text": "The port facility is at ISPS security level 2. Apply the plan's level 2 measures: search rates up, restricted areas manned, ships notified."})
    if access["tailgating"]:
        actions.append({"state": "warning", "area": "Security",
                        "text": f"{access['tailgating']} tailgating event{'s' if access['tailgating'] > 1 else ''} at the gate turnstiles today. Review the footage and brief the gate staff."})

    # The structure's own safety items: ladders and anything graded unsafe.
    structural = []
    if twin:
        for e in twin["elements"]:
            if e["element"]["kind"] in ("ladder",) or (e["element"]["kind"] in ("bollard", "fender") and e["state"] == "critical"):
                structural.append({"name": e["element"]["name"], "kind": e["element"]["kind"], "state": e["state"]})
                if e["element"]["kind"] == "ladder" and e["state"] != "good":
                    actions.append({"state": e["state"], "area": "Safety",
                                    "text": f"Quay ladder {e['element']['name']} is graded for attention. It is a means of escape from the water: repair it, and until then mark it out of use and point to the nearest other ladder."})
    return {"kpis": kpis, "log": log, "permits": permits, "level": level, "cameras": cameras, "access": access,
            "alarms": alarms, "proximity": proximity, "structural": structural, "actions": _sorted(actions)}
