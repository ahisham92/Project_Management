"""MarineTwin's operations: what is happening at the berth now, what happens next, what to do.

The structure is only half of a berth. The other half is its operation: the
weather and sea it works in, the ships that come alongside, the cranes that work
them, and the hours lost when any of those stops. This module puts the two
together, because that is where the decisions are: a ship due on a fender the
last inspection found torn, a gale forecast while a bollard is near its rating,
cranes running on a rail that is off its line.

It answers three questions for one asset:

* **Now.** Wind, sea and tide; the ship alongside; the cranes; whether the berth
  is working normally, restricted or stopped, and why.
* **Next 72 hours.** The forecast against the operating limits, and each ship
  due: its berthing energy against the fenders it lands on, and its mooring
  loads in the forecast wind against the bollards that hold it.
* **What to do.** Actions with a time on them, most pressing first, whether the
  cause is the weather, a ship, a crane or the structure.

**For the prototype every operational feed is simulated**, deterministically per
asset and day so the page tells the same story all day. The shapes are what a
port would plug in later: a met forecast, the vessel line-up from the port
community system or AIS, crane status from the crane PLCs, and the downtime log.

The calculations are the standard simplified ones, labelled as indicative:
berthing energy to BS 6349-4 / PIANC WG 33 and wind load on a moored ship from
its windage area. Ratings (the fender's rated energy, the bollard's capacity)
come from Triton's quay furniture through ``marine_triton``, read-only.
"""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta
from typing import Any

from . import marine, marine_risk, marine_triton

# --- operating limits ----------------------------------------------------------------
# Typical values for a container berth; a port sets its own in its operating manual.
LIMITS = {
    "crane_stop_gust": 20.0,     # m/s, STS cranes stop working (3 s gust at boom height)
    "crane_stow_gust": 25.0,     # m/s, cranes parked on their storm pins and tied down
    "berthing_wind": 15.0,       # m/s mean, no berthing or unberthing above it
    "berthing_hs": 1.5,          # m, significant wave height, no berthing above it
    "mooring_wind": 20.0,        # m/s mean, extra lines and a tug on standby above it
}
LIMIT_NOTES = {
    "crane_stop_gust": "STS cranes stop",
    "crane_stow_gust": "cranes to storm pins",
    "berthing_wind": "no berthing",
    "mooring_wind": "extra lines, tug standby",
}

# Berthing energy, BS 6349-4:2014 / PIANC WG 33 (2002): E = ½ M V² Cm Ce Cs Cc.
ECCENTRICITY = 0.5               # Ce, contact at the quarter point
SOFTNESS = 1.0                   # Cs
BERTH_CONFIG_SOLID = 0.9         # Cc, a solid quay wall cushions the approach
BERTH_CONFIG_OPEN = 1.0          # Cc, an open piled jetty does not
ABNORMAL = 1.5                   # factor on the normal energy the fender has to absorb

# Wind on a moored ship: F = ½ ρ Cd A V².
AIR = 1.225                      # kg/m³
DRAG_BEAM = 1.2                  # beam-on wind on a ship with deck cargo
LINES_PER_BOLLARD = 2


def approach_speed(wind: float) -> float:
    """Design approach speed for a large ship (m/s), from the wind it berths in.

    Brolsma's curves (PIANC WG 33) for a ship over 50 000 t: about 0.10 m/s in good,
    sheltered conditions, 0.15 m/s in moderate ones, 0.20 m/s when it is difficult.
    """
    if wind < 10:
        return 0.10
    if wind < LIMITS["berthing_wind"]:
        return 0.15
    return 0.20


def berthing_energy(displacement_t: float, beam: float, draught: float, speed: float, solid: bool) -> dict[str, float]:
    """Normal and abnormal berthing energy (kNm) of one ship."""
    cm = 1 + 2 * draught / beam                       # Vasco Costa added mass
    cc = BERTH_CONFIG_SOLID if solid else BERTH_CONFIG_OPEN
    normal = 0.5 * displacement_t * speed ** 2 * cm * ECCENTRICITY * SOFTNESS * cc   # t·m²/s² = kNm
    return {"cm": round(cm, 2), "cc": cc, "speed": speed, "normal": round(normal), "abnormal": round(normal * ABNORMAL)}


def wind_on_ship(loa: float, windage: float, wind: float) -> float:
    """Beam-on wind load on a moored ship, in tonnes force."""
    area = loa * windage
    return 0.5 * AIR * DRAG_BEAM * area * wind ** 2 / 9.81 / 1000


# --- the simulated feeds -------------------------------------------------------------

SHIPS = [
    # name, type, LOA m, beam m, draught m, displacement t, windage height m
    ("MSC Aurora", "Container", 300, 48.2, 14.0, 140000, 32),
    ("Maersk Kendal", "Container", 294, 32.3, 13.0, 95000, 28),
    ("CMA CGM Thalia", "Container", 334, 42.8, 14.5, 150000, 34),
    ("Ever Lucent", "Container", 366, 48.2, 15.0, 190000, 36),
    ("ONE Harmony", "Container", 260, 32.3, 12.5, 70000, 26),
    ("Hapag Riyadh", "Container", 368, 51.0, 15.5, 200000, 38),
    ("Gulf Pioneer", "General cargo", 180, 28.0, 10.0, 35000, 14),
    ("Arabian Star", "Bulk carrier", 229, 32.3, 13.5, 95000, 12),
]
# The fleets each kind of terminal sees.
FLEETS = {
    "container": SHIPS[:6],
    "general_cargo": [("Gulf Pioneer", "General cargo", 180, 28.0, 10.0, 35000, 14),
                      ("BBC Lagos", "Heavy lift", 154, 23.0, 8.8, 22000, 16),
                      ("Atlantic Trader", "General cargo", 190, 30.0, 10.5, 40000, 15),
                      ("Spliethoff Eems", "Multipurpose", 169, 25.2, 9.5, 28000, 15),
                      ("Africa Star", "Breakbulk", 200, 32.2, 11.0, 48000, 14)],
    "roro": [("Grande Lagos", "RoRo", 236, 32.3, 10.0, 52000, 30),
             ("Hoegh Target", "Car carrier", 200, 36.5, 9.5, 42000, 36),
             ("Grande Abidjan", "RoRo", 211, 32.3, 9.8, 46000, 28),
             ("Glovis Sun", "Car carrier", 199, 32.3, 9.2, 38000, 34),
             ("Celine", "RoRo", 235, 35.0, 8.0, 50000, 30)],
    "bulk": [("Arabian Star", "Bulk carrier", 229, 32.3, 13.5, 95000, 12),
             ("Cape Onne", "Bulk carrier", 190, 32.2, 12.0, 70000, 11),
             ("Star Kirkenes", "Bulk carrier", 200, 32.3, 12.8, 80000, 11),
             ("Ocean Grain", "Bulk carrier", 180, 30.0, 11.5, 60000, 10)],
}
FLEETS["multipurpose"] = FLEETS["container"][:3] + FLEETS["general_cargo"][:2] + FLEETS["roro"][:1]
# What works the ships at each kind of terminal, by name prefix and what it is called.
EQUIPMENT = {
    "container": ("STS", "quay cranes"), "general_cargo": ("MHC", "mobile harbour cranes"),
    "roro": ("RAMP", "ramp gangs"), "bulk": ("SU", "ship unloaders"), "multipurpose": ("MHC", "mobile harbour cranes"),
}
UNITS = {"container": "containers", "general_cargo": "lifts", "roro": "vehicles", "bulk": "tonnes ×10", "multipurpose": "lifts"}


def _rng(asset_id: int, day: str, what: str) -> random.Random:
    return random.Random(f"marinetwin-ops:{asset_id}:{day}:{what}")


def _hour(now: datetime) -> datetime:
    return now.replace(minute=0, second=0, microsecond=0)


def metocean(asset_id: int, now: datetime, hours_back: int = 24, hours_ahead: int = 72) -> list[dict[str, Any]]:
    """Hourly wind, gust, wave height, tide and current, from a day ago to three days ahead.

    A sea breeze cycle, and on most days a weather system passing through
    somewhere in the next three days, peaking at a random hour.
    """
    start = _hour(now) - timedelta(hours=hours_back)
    rng = _rng(asset_id, now.date().isoformat(), "metocean")
    base = rng.uniform(4, 8)
    storm_at = rng.uniform(hours_back + 6, hours_back + hours_ahead - 6)
    storm_peak = rng.choice([0, 6, 10, 13, 16]) + rng.uniform(0, 3)   # extra m/s at the peak
    storm_width = rng.uniform(5, 12)
    tide_phase = rng.uniform(0, 2 * math.pi)
    out = []
    for i in range(hours_back + hours_ahead + 1):
        at = start + timedelta(hours=i)
        breeze = 3 * max(0.0, math.sin(2 * math.pi * (at.hour - 9) / 24))
        storm = storm_peak * math.exp(-((i - storm_at) / storm_width) ** 2)
        wind = max(0.5, base + breeze + storm + rng.gauss(0, 0.6))
        gust = wind * rng.uniform(1.25, 1.4)
        hs = 0.25 + 0.012 * wind ** 1.6 + rng.gauss(0, 0.03)
        tide = 0.9 + 0.75 * math.sin(2 * math.pi * i / 12.42 + tide_phase)       # m above chart datum
        current = 0.35 * abs(math.cos(2 * math.pi * i / 12.42 + tide_phase)) + rng.gauss(0, 0.02)
        out.append({"at": at, "wind": round(wind, 1), "gust": round(gust, 1), "hs": round(max(hs, 0.1), 2),
                    "tide": round(tide, 2), "current": round(max(current, 0.0), 2),
                    "past": at <= _hour(now)})
    return out


def flag_of(name: str) -> str:
    """The flag a ship of the typical fleets flies."""
    from . import marine_berths
    for fleet in marine_berths.FLEET.values():
        for ship in fleet:
            if ship[0] == name:
                return ship[3]
    return ""


def lineup(asset_id: int, now: datetime, terminal: str = "container") -> list[dict[str, Any]]:
    """The ship alongside, if any, and the calls due in the next three days."""
    rng = _rng(asset_id, now.date().isoformat(), "lineup")
    ships = list(FLEETS.get(terminal, SHIPS))
    rng.shuffle(ships)
    out = []
    t = _hour(now) - timedelta(hours=rng.uniform(4, 20))     # the current call came in before now
    for i, (name, kind, loa, beam, draught, disp, windage) in enumerate(ships[:4]):
        stay = timedelta(hours=rng.uniform(14, 30))
        eta = t
        etd = eta + stay
        if i == 0 and rng.random() < 0.25:                    # some days the berth is empty this morning
            eta = _hour(now) + timedelta(hours=rng.uniform(3, 8))
            etd = eta + stay
        out.append({"name": name, "type": kind, "loa": loa, "beam": beam, "draught": draught, "flag": flag_of(name),
                    "displacement": disp, "windage": windage, "eta": eta, "etd": etd,
                    "moves": int(rng.uniform(0.5, 1.0) * loa * 6)})
        t = etd + timedelta(hours=rng.uniform(2, 10))
    return out


def cranes(asset_id: int, now: datetime, gust: float, terminal: str = "container", count: int = 3) -> list[dict[str, Any]]:
    rng = _rng(asset_id, now.date().isoformat(), "cranes")
    prefix = EQUIPMENT.get(terminal, EQUIPMENT["container"])[0]
    out = []
    for i in range(count if prefix != "RAMP" else 2):
        hours = rng.uniform(150, 520)                          # running hours to the next service
        broken = rng.random() < 0.12
        if prefix == "RAMP":
            # A ramp gang drives vehicles off and on: wind stops the berthing, not the ramp.
            state, why = ("down", rng.choice(["ramp hydraulic pump fault", "short of drivers"])) if broken else ("working", "")
        elif gust >= LIMITS["crane_stow_gust"]:
            state, why = "stowed", "on its storm pins: gusts over the stow limit"
        elif gust >= LIMITS["crane_stop_gust"]:
            state, why = "stopped", "wind stop: gusts over the operating limit"
        elif broken:
            state, why = "down", rng.choice(["spreader twistlock fault", "hoist brake alarm", "gantry drive fault"])
        else:
            state, why = "working", ""
        out.append({"name": f"{prefix}{i + 1}" if prefix != "RAMP" else f"Ramp gang {i + 1}", "state": state, "why": why, "service_in_h": round(hours),
                    "rate": round(rng.uniform(24, 32), 1)})
    return out


def downtime(asset_id: int, now: datetime, days: int = 30) -> dict[str, Any]:
    """Hours the berth lost in the last ``days``, by cause, and its occupancy."""
    rng = _rng(asset_id, now.date().isoformat(), "downtime")
    causes = {"Wind": 0.0, "Waves": 0.0, "Crane breakdown": 0.0, "Berth / fender damage": 0.0, "Waiting for ship": 0.0}
    for _ in range(days):
        if rng.random() < 0.2:
            causes["Wind"] += rng.uniform(2, 10)
        if rng.random() < 0.08:
            causes["Waves"] += rng.uniform(2, 8)
        if rng.random() < 0.15:
            causes["Crane breakdown"] += rng.uniform(1, 6)
        if rng.random() < 0.04:
            causes["Berth / fender damage"] += rng.uniform(4, 12)
        if rng.random() < 0.3:
            causes["Waiting for ship"] += rng.uniform(2, 9)
    lost = sum(v for k, v in causes.items() if k != "Waiting for ship")
    occupied = days * 24 - causes["Waiting for ship"]
    return {"days": days, "causes": {k: round(v, 1) for k, v in causes.items()}, "lost": round(lost, 1),
            "occupancy": round(100 * occupied / (days * 24)),
            "availability": round(100 * (days * 24 - lost) / (days * 24))}


# The situations the live port can play: the forecast as it is, or the same two days with
# something laid over them, to see how the port copes. Key, name, what it shows.
SCENARIOS = [
    ("normal", "Normal day", "The forecast as it is, the line-up as booked."),
    ("peak", "Peak week", "Ships back to back at every berth and waiting at anchor for a slot."),
    ("storm", "Storm", "A gale later today: cranes stop, then go to their storm pins; no berthing or sailing."),
    ("power_cut", "Power cut at night", "The grid drops for four hours in the evening: electric cranes stop and the yard lights go out."),
    ("crane_fault", "Crane breakdown", "Two of the berth's cranes break down in the first day; the ship is worked on what is left."),
    ("fog", "Fog", "Thick fog through the night and morning: the pilots stop bringing ships in; cranes keep working."),
]
# Every extreme event from the Risks page that closes the berth plays here too: it strikes a few
# hours in, and the two days show the warning (when there is one), the strike, the area closed and
# the cranes stopped. The 3D view draws its damage and closed area once it has struck.
STRIKE_CLOCK = 10      # an extreme event strikes at ten in the morning, in full daylight
EXTREME = [e for e in marine_risk.EVENTS if e["days"]]
SCENARIOS += [(e["key"], e["name"], e["what"]) for e in EXTREME]
SCENARIO_KEYS = {key for key, *_ in SCENARIOS}


def _next_hour(start: datetime, hours: int, at: int, lead: int = 1) -> int:
    """Hours from the start to the next time the clock shows ``at`` o'clock, at least ``lead`` ahead."""
    return next((i for i in range(lead, hours) if (start + timedelta(hours=i)).hour == at), lead)


def _scenario_hours(scenario: str, start: datetime, hours: int) -> dict[str, Any]:
    """When the scenario's event happens on this timeline, in hours from the start: in daylight, so it
    can be seen (fog at dawn, when it forms)."""
    morning = _next_hour(start, hours, STRIKE_CLOCK)
    return {"storm": (_next_hour(start, hours, 8), _next_hour(start, hours, 8) + 14),
            "power_cut": (_next_hour(start, hours, 20, 3), _next_hour(start, hours, 20, 3) + 4),   # at night, as it shows the lights
            "fog": (_next_hour(start, hours, 5), _next_hour(start, hours, 5) + 6),
            "crane_fault": (morning, morning + 24)}.get(scenario, (None, None))


def crane_share(extreme: dict[str, Any]) -> float:
    """The share of the quay's cranes an extreme event stops, counted from the start of the quay. The
    3D view stops the ones in the closed area instead where the event closes an area round a point."""
    return extreme["share"] if extreme["share"] is not None else 1.0 if not extreme["radius"] else 0.5


def live(asset_id: int, now: datetime, terminal: str = "container", hours: int = 48,
         scenario: str = "normal", booked: list[dict[str, Any]] | None = None,
         fleet: list[int] | None = None, closed: set[int] | None = None) -> dict[str, Any]:
    """The berth over the next ``hours``, hour by hour, for the live view to play back.

    The same simulated feeds as the Operations page (weather, the line-up, the cranes), put on
    one timeline: rain with the weather, berthing held back while the wind or the waves are over
    the limits (the ship waits at anchor), the cranes stopping in gusts or breaking down, and
    the events a duty manager would log along the way.
    """
    start = _hour(now)
    scenario = scenario if scenario in SCENARIO_KEYS else "normal"
    weather = metocean(asset_id, now, hours_back=0, hours_ahead=hours)
    s_from, s_to = _scenario_hours(scenario, start, hours)
    extreme = marine_risk.BY_KEY.get(scenario)
    if extreme:
        s_from, s_to = _next_hour(start, hours, STRIKE_CLOCK), hours + 1
        if extreme["weather"]:
            # The storm that brings it: up over a few hours to its peak, holding for half a day, easing.
            peak = extreme["weather"]
            for i, w in enumerate(weather):
                rise = min(1.0, max(0.0, (i - s_from + 4) / 4)) * min(1.0, max(0.0, (s_from + 16 - i) / 6))
                if rise > 0:
                    w["wind"] = round(max(w["wind"], peak["wind"] * rise), 1)
                    w["gust"] = round(max(w["gust"], w["wind"] * 1.32), 1)
                    w["hs"] = round(max(w["hs"], peak["hs"] * rise), 2)
    if scenario == "storm":
        # A gale front: up over a few hours to gusts past the stow limit, holding, then easing.
        for i, w in enumerate(weather):
            rise = min(1.0, max(0.0, (i - s_from) / 4)) * min(1.0, max(0.0, (s_to + 4 - i) / 6))
            if rise > 0:
                w["wind"] = round(max(w["wind"], 8 + 13 * rise), 1)
                w["gust"] = round(max(w["gust"], w["wind"] * 1.32), 1)
                w["hs"] = round(max(w["hs"], 0.4 + 2.2 * rise), 2)
    rng = _rng(asset_id, now.date().isoformat(), "rain")
    showers = [(rng.uniform(0, hours), rng.uniform(0.8, 2.5), rng.uniform(1, 8)) for _ in range(rng.randint(1, 4))]
    prefix, equipment_name = EQUIPMENT.get(terminal, EQUIPMENT["container"])
    events: list[dict[str, Any]] = []

    def log(at: datetime, kind: str, text: str) -> None:
        events.append({"at": at, "kind": kind, "text": text})

    # Breakdowns come and go: each machine may fail once or twice, for a few hours.
    reasons = ["ramp hydraulic pump fault", "short of drivers"] if prefix == "RAMP" else \
        ["spreader twistlock fault", "hoist brake alarm", "gantry drive fault", "trolley rope inspection"]
    faults = []
    # The cranes along the quay, each with its berth (``fleet``: the berth of each, as the 3D view found
    # them); without it, the main berth's three.
    for k in range(2 if prefix == "RAMP" else len(fleet) if fleet else 3):
        name = f"Ramp gang {k + 1}" if prefix == "RAMP" else f"{prefix}{k + 1}"
        breaks = [(rng.uniform(0, hours), rng.uniform(1, 6), rng.choice(reasons)) for _ in range(rng.choice([0, 0, 1, 1, 2]))]
        if scenario == "crane_fault" and k < 2:
            # The first fails for a day, the second for a shift in the middle of it.
            breaks.append((s_from, s_to - s_from, reasons[2 if prefix != "RAMP" else 0]) if k == 0
                          else (s_from + 8, 7, reasons[1 if prefix != "RAMP" else 1]))
        faults.append((name, breaks))
    # Electric machines stop when the grid drops; ramp gangs drive diesel vehicles and carry on.
    electric = prefix in ("STS", "SU")
    hourly = []
    stopped_before: dict[str, tuple[str, str]] = {}
    for i, w in enumerate(weather):
        storm_rain = max(0.0, (w["wind"] - 11) * 1.4)
        shower = sum(rate * math.exp(-((i - at) / width) ** 2) for at, width, rate in showers)
        rain = round(storm_rain + shower if storm_rain + shower > 0.3 else 0.0, 1)
        # An event that closes an area round one point takes the supply down with it only there: the
        # cranes in that area are already stopped. A grid-wide cut is for the events that reach the
        # whole terminal (the grid itself, a quake, a storm, a missile).
        grid_wide = bool(extreme) and extreme["power"] and (extreme["radius"] is None or extreme["key"] == "war_direct")
        power = not (scenario == "power_cut" and s_from <= i < s_to) and \
            not (grid_wide and s_from <= i < s_from + 12)
        struck = bool(extreme) and i >= s_from
        fog = scenario == "fog" and s_from <= i < s_to
        kit = []
        for k, (name, breaks) in enumerate(faults):
            fault = next((why for at, length, why in breaks if at <= i < at + length), None)
            share = crane_share(extreme) if extreme else 0.5
            # ``closed``: the cranes the 3D view found standing in the event's closed area (by their
            # place in the list); without it, the event's share of them from the start of the quay.
            if struck and (k in closed if closed is not None else k < max(1, round(share * len(faults)))):
                kit.append({"name": name, "state": "down", "why": f"{extreme['name'].lower()}: area closed"})
            elif not power and electric:
                kit.append({"name": name, "state": "down", "why": "power cut, no grid supply"})
            elif prefix != "RAMP" and w["gust"] >= LIMITS["crane_stow_gust"]:
                kit.append({"name": name, "state": "stowed", "why": "on storm pins, gusts over the stow limit"})
            elif prefix != "RAMP" and w["gust"] >= LIMITS["crane_stop_gust"]:
                kit.append({"name": name, "state": "stopped", "why": "wind stop, gusts over the operating limit"})
            elif fault:
                kit.append({"name": name, "state": "down", "why": fault})
            else:
                kit.append({"name": name, "state": "working", "why": ""})
        hourly.append({"at": w["at"], "wind": w["wind"], "gust": w["gust"], "hs": w["hs"], "tide": w["tide"],
                       "rain": rain, "visibility": 0.2 if fog else round(max(0.4, 10 - rain * 0.9), 1),
                       "equipment": [{"name": c["name"], "state": c["state"], "why": c["why"],
                                      **({"berth": fleet[k]} if fleet and prefix != "RAMP" else {})} for k, c in enumerate(kit)],
                       "berthing": w["wind"] < LIMITS["berthing_wind"] and w["hs"] < LIMITS["berthing_hs"] and not fog and not struck,
                       "power": power, "fog": fog})
        if extreme and i == 0 and extreme["warn_h"] >= 1:
            log(w["at"], "warning", f"Warning: {extreme['name'].lower()} expected, from {extreme['warn_with']}. Getting ready.")
        if extreme and i == max(0, s_from - 1) and 0 < extreme["warn_h"] < 1:
            log(w["at"], "warning", f"Alarm from {extreme['warn_with']}: minutes to act.")
        if extreme and i == s_from:
            log(w["at"], "critical", f"{extreme['name']}: {extreme['what']}")
            log(w["at"], "critical", ("The whole quay is closed" if not extreme["radius"] else f"About {2 * extreme['radius']:.0f} m of the quay closed")
                + f" for about {extreme['days']:.0f} days ({extreme['days_known']:.0f} knowing early). No berthing.")
            if extreme["steps"]:
                log(w["at"] + timedelta(hours=1), "info", "Recovery: " + "; ".join(extreme["steps"][:3]).lower() + ".")
        if scenario == "power_cut" and i == s_from:
            log(w["at"], "critical", "Power cut: the grid supply is lost. Electric cranes stop, the yard lights go out; reefers on the standby generators.")
        if scenario == "power_cut" and i == s_to:
            log(w["at"], "good", "Power restored: cranes back on and the yard lit again.")
        if fog and i == s_from:
            log(w["at"], "warning", "Fog down to 200 m: the pilots stop bringing ships in or out.")
        if scenario == "fog" and i == s_to:
            log(w["at"], "good", "Fog lifting: pilotage resumes.")
        stopped = {c["name"]: (c["state"], c["why"]) for c in kit if c["state"] != "working"}
        changes: dict[tuple[str, str], list[str]] = {}
        for c in kit:
            if c["name"] in stopped and stopped_before.get(c["name"]) != stopped[c["name"]]:
                changes.setdefault(stopped[c["name"]], []).append(c["name"])
            elif c["name"] in stopped_before and c["name"] not in stopped:
                changes.setdefault(("working", ""), []).append(c["name"])
        for (state, why), names in changes.items():
            who = " and ".join([", ".join(names[:-1]), names[-1]] if len(names) > 1 else names)
            if state == "working":
                log(w["at"], "good", f"{who} back at work.")
            else:
                log(w["at"], "critical" if state in ("stowed", "down") else "warning", f"{who} {state}: {why}.")
        stopped_before = stopped
        if i and rain and not hourly[i - 1]["rain"]:
            log(w["at"], "info", f"Rain starting, {rain:.1f} mm/h.")

    def allowed(at: datetime) -> datetime | None:
        """The first time from ``at`` that a ship may berth or sail: the hour of the manoeuvre and
        the hour before it (the approach with the pilot and tugs) both within the limits."""
        for i, h in enumerate(hourly):
            if h["at"] >= _hour(at) and h["berthing"] and (i == 0 or hourly[i - 1]["berthing"]):
                return max(h["at"], at)
        return None

    calls = []
    booked = [dict(b) for b in booked] if booked else lineup(asset_id, now, terminal)
    if scenario == "peak":
        # Back to back: each ship is due as the one before sails, and waits for the berth if early.
        for prev, s in zip(booked, booked[1:]):
            stay = s["etd"] - s["eta"]
            s["eta"] = min(s["eta"], prev["etd"] - timedelta(hours=3))
            s["etd"] = s["eta"] + stay
    for s in booked:
        eta, etd, waited = s["eta"], s["etd"], None
        if eta >= start:
            if calls and eta < calls[-1]["etd"] + timedelta(hours=2):
                eta = calls[-1]["etd"] + timedelta(hours=2)  # the berth is still busy: it waits its turn
            berth_at = allowed(eta)
            if berth_at is None:
                continue
            if berth_at > eta:
                waited = eta
            eta, etd = berth_at, berth_at + (s["etd"] - s["eta"])
        elif calls:
            continue
        if eta >= start:
            if waited:
                log(waited, "warning", f"{s['name']} waits at anchor: no berthing in this wind and sea.")
            log(eta - timedelta(hours=1), "info", f"{s['name']} ({s['type']}, {s['loa']} m) takes the pilot.")
            log(eta, "good", f"{s['name']} all fast.")
        if etd <= start + timedelta(hours=hours):
            sail_at = allowed(etd) or etd
            if sail_at > etd:
                log(etd, "warning", f"{s['name']} held alongside: too windy to sail.")
            etd = sail_at
            log(etd, "info", f"{s['name']} sails.")
        calls.append({"name": s["name"], "type": s["type"], "loa": s["loa"], "beam": s["beam"], "draught": s["draught"],
                      "eta": eta, "etd": etd, "moves": s["moves"], "held": waited is not None,
                      "flag": s.get("flag") or flag_of(s["name"]), "line": s.get("line", "")})
    if scenario == "peak":
        log(start, "warning", "Peak week: every berth booked back to back, ships waiting at anchor for a slot.")
    if scenario == "storm":
        log(start + timedelta(hours=s_from), "warning", "Gale warning: wind rising to storm force within hours.")
    events.sort(key=lambda e: e["at"])
    name, words = next((n, w) for k, n, w in SCENARIOS if k == scenario)
    return {"start": start, "hours": hourly, "calls": calls, "events": events,
            "equipment_name": equipment_name, "units": UNITS.get(terminal, "containers"), "limits": LIMITS,
            "scenario": {"key": scenario, "name": name, "words": words, "strikes_at": s_from if extreme else None}}


# --- putting it together ----------------------------------------------------------

def _when(at: datetime, now: datetime) -> str:
    hours = (at - now).total_seconds() / 3600
    if -1 < hours < 1:
        return "now"
    day = "today" if at.date() == now.date() else "tomorrow" if at.date() == (now + timedelta(days=1)).date() else at.strftime("%A")
    return f"{day} {at:%H:00}"


def operations(conn: Any, asset: Any, now: datetime | None = None, twin: dict[str, Any] | None = None) -> dict[str, Any]:
    """Now, next and what to do for one asset."""
    now = now or datetime.now()
    twin = twin or marine.assess_asset(conn, asset, now.date())
    asset_id = int(asset["id"])
    ratings = marine_triton.ratings(asset)
    fender_energy = ratings.get("fender_energy")
    solid = asset["kind"] == "quay_wall"

    weather = metocean(asset_id, now)
    current = next(w for w in reversed(weather) if w["past"])
    ahead = [w for w in weather if not w["past"]]
    terminal = asset["terminal_type"] if "terminal_type" in asset.keys() else "container"
    ships = lineup(asset_id, now, terminal)
    alongside = next((s for s in ships if s["eta"] <= now < s["etd"]), None)
    due = [s for s in ships if s["eta"] > now and s["eta"] <= now + timedelta(hours=72)]
    crane_list = cranes(asset_id, now, current["gust"], terminal)
    lost = downtime(asset_id, now)

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for e in twin["elements"]:
        by_kind.setdefault(e["element"]["kind"], []).append(e)
    fenders = by_kind.get("fender", [])
    bollards = by_kind.get("bollard", [])
    rails = by_kind.get("crane_rail", [])
    damaged = [f for f in fenders if f["state"] == "critical"]
    usable_bollards = max(1, len([b for b in bollards if b["state"] != "critical"]))

    actions: list[dict[str, Any]] = []

    def act(state: str, when: datetime | None, area: str, text: str) -> None:
        actions.append({"state": state, "when": _when(when, now) if when else "", "at": when or now,
                        "area": area, "text": text})

    # Weather windows over the next 72 hours.
    def first(rows, test):
        return next((w for w in rows if test(w)), None)

    stow = first(ahead, lambda w: w["gust"] >= LIMITS["crane_stow_gust"])
    stop = first(ahead, lambda w: w["gust"] >= LIMITS["crane_stop_gust"])
    no_berth = first(ahead, lambda w: w["wind"] >= LIMITS["berthing_wind"] or w["hs"] >= LIMITS["berthing_hs"])
    peak = max(ahead, key=lambda w: w["gust"])
    if stow:
        act("critical", stow["at"] - timedelta(hours=3), "Cranes",
            f"Gusts reach {stow['gust']:.0f} m/s {_when(stow['at'], now)}, over the {LIMITS['crane_stow_gust']:.0f} m/s stow limit. "
            f"Park the {EQUIPMENT.get(terminal, EQUIPMENT['container'])[1]} on their storm pins and fit the tie-downs by {_when(stow['at'] - timedelta(hours=1), now)}"
            + ("; the storm pins were last graded " + ", ".join(f"{e['element']['name']} {e['state']}" for e in by_kind.get('storm_pin', [])) if by_kind.get("storm_pin") else "") + ".")
    elif stop:
        act("warning", stop["at"], "Cranes",
            f"Gusts reach {stop['gust']:.0f} m/s {_when(stop['at'], now)}: the cranes will stop at {LIMITS['crane_stop_gust']:.0f} m/s. "
            f"Plan the stowage so whichever ship is alongside then can sail with what is loaded.")
    if current["gust"] >= LIMITS["crane_stop_gust"]:
        status, reason = "Stopped", f"gusts {current['gust']:.0f} m/s, over the crane limit"
    elif current["wind"] >= LIMITS["berthing_wind"] or current["hs"] >= LIMITS["berthing_hs"]:
        status, reason = "Restricted", "no berthing in this wind or sea; cranes working"
    else:
        status, reason = "Normal", "within every operating limit"

    # Each ship due: berthing conditions, berthing energy on the fenders, mooring on the bollards.
    calls = []
    landing: list[dict[str, Any]] = []                 # ships due onto a fender graded for action
    for ship in ([alongside] if alongside else []) + due:
        at_eta = min(weather, key=lambda w: abs((w["at"] - ship["eta"]).total_seconds()))
        energy = berthing_energy(ship["displacement"], ship["beam"], ship["draught"], approach_speed(at_eta["wind"]), solid)
        during = [w for w in weather if ship["eta"] <= w["at"] <= ship["etd"]] or [at_eta]
        worst_wind = max(during, key=lambda w: w["wind"])
        pull = wind_on_ship(ship["loa"], ship["windage"], worst_wind["wind"])
        per_bollard = pull / usable_bollards
        flags = []
        is_alongside = ship is alongside
        if not is_alongside and (at_eta["wind"] >= LIMITS["berthing_wind"] or at_eta["hs"] >= LIMITS["berthing_hs"]):
            flags.append(("critical", "berthing conditions"))
            calm = first([w for w in ahead if w["at"] > ship["eta"]],
                         lambda w: w["wind"] < LIMITS["berthing_wind"] - 2 and w["hs"] < LIMITS["berthing_hs"] - 0.2)
            act("critical", ship["eta"] - timedelta(hours=6), "Vessels",
                f"{ship['name']} is due {_when(ship['eta'], now)} into {at_eta['wind']:.0f} m/s wind and {at_eta['hs']:.1f} m waves, "
                f"over the berthing limits. Hold her at anchor" + (f" until about {_when(calm['at'], now)}, when it eases" if calm else "") + ".")
        if fender_energy and not is_alongside:
            ratio = energy["abnormal"] / fender_energy
            if ratio > 1:
                flags.append(("critical", "berthing energy"))
                act("critical", ship["eta"] - timedelta(hours=2), "Vessels",
                    f"{ship['name']} ({ship['displacement']:,} t) berthing at {energy['speed']:.2f} m/s carries {energy['abnormal']:,} kNm abnormal energy, "
                    f"over the fenders' {fender_energy:,.0f} kNm rating. Berth her with tugs at no more than 0.10 m/s and a berthing aid display.")
            if damaged:
                flags.append(("critical", "damaged fender"))
                landing.append(ship)
        if bollards and ratings.get("bollard"):
            share = per_bollard / ratings["bollard"]
            near = [b for b in bollards if b["state"] in ("warning", "critical")]
            if share > 0.8 or (worst_wind["wind"] >= LIMITS["mooring_wind"]):
                flags.append(("warning" if share <= 1 else "critical", "mooring"))
                act("critical" if share > 1 else "warning", worst_wind["at"] - timedelta(hours=3), "Mooring",
                    f"In {worst_wind['wind']:.0f} m/s {_when(worst_wind['at'], now)}, beam-on wind pulls {ship['name']} off the berth with about {pull:,.0f} t, "
                    f"{per_bollard:,.0f} t on each of {usable_bollards} bollards against their {ratings['bollard']:,.0f} t rating. "
                    f"Double up the breast lines and have a tug on standby"
                    + (f"; keep the extra lines off {', '.join(b['element']['name'] for b in near)}, already near its rating" if near else "") + ".")
        calls.append({**ship, "alongside": is_alongside, "when": _when(ship["eta"], now), "until": _when(ship["etd"], now),
                      "wind_at_eta": at_eta["wind"], "hs_at_eta": at_eta["hs"], "energy": energy,
                      "fender_energy": fender_energy, "pull": round(pull), "per_bollard": round(per_bollard, 1),
                      "state": max((f[0] for f in flags), key=lambda s: marine.STATE_RANK[s], default="good"),
                      "flags": [f[1] for f in flags]})

    if landing:
        names = ", ".join(f["element"]["name"] for f in damaged)
        one = len(damaged) == 1
        ships_due = "; ".join(f"{s['name']} {_when(s['eta'], now)}" for s in landing)
        act("critical", landing[0]["eta"] - timedelta(hours=4), "Vessels",
            f"{names} {'is' if one else 'are'} graded for action and {len(landing)} ship{'s' if len(landing) > 1 else ''} "
            f"will land on the fender line ({ships_due}). Replace {'it' if one else 'them'} before the first, "
            f"or shift each ship's berthing position so her parallel body clears {names}.")

    # Cranes.
    for crane in crane_list:
        if crane["state"] == "down":
            act("warning", now, "Cranes", f"{crane['name']} is down ({crane['why']}). "
                f"{'Re-plan ' + alongside['name'] + ' on the other cranes' if alongside else 'Fix it before the next ship'}, and log the hours.")
        elif crane["service_in_h"] < 200:
            act("good", now + timedelta(hours=crane["service_in_h"] / 2), "Cranes",
                f"{crane['name']} is {crane['service_in_h']} running hours from its service: book it into the gap between ships.")
    for rail in rails:
        if rail["state"] in ("warning", "critical"):
            act(rail["state"], now, "Cranes",
                f"The crane rail {rail['element']['name']} is out of line ({'; '.join(s['headline'] for s in rail['sensors'] if s['state'] != 'good')}). "
                f"Limit gantry speed over that length until it is realigned.")

    # The structure's own actions come along, under their heading.
    for advice in twin["advice"]:
        if advice["state"] == "critical":
            act("critical", None, "Structure", f"{advice['element']}: {advice['text']}")

    # Most severe first; within that, what has a time on it by its time, then the structure's standing actions.
    order = {"critical": 0, "warning": 1, "good": 2}
    actions.sort(key=lambda a: (order.get(a["state"], 3), a["area"] == "Structure", a["at"]))
    return {
        "now": now, "status": status, "reason": reason, "current": current, "weather": weather, "ahead": ahead,
        "peak": peak, "alongside": alongside, "calls": calls, "cranes": crane_list,
        "cranes_working": sum(1 for c in crane_list if c["state"] == "working"),
        "downtime": lost, "actions": actions, "limits": LIMITS, "limit_notes": LIMIT_NOTES,
        "ratings": ratings, "twin": twin, "terminal": terminal,
        "equipment_name": EQUIPMENT.get(terminal, EQUIPMENT["container"])[1], "units": UNITS.get(terminal, "containers"),
        "windows": {"stop": stop, "stow": stow, "no_berth": no_berth},
    }
