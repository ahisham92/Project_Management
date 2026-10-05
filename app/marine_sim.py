"""MarineTwin's operations simulation: where a terminal's bottleneck is, and what moves it.

A container berth is a chain: ships wait for a berth, quay cranes (STS) work
them, terminal tractors carry each box between the crane and the yard, yard
cranes (RTG) stack it, and road trucks come through the gate to take it away or
bring the next one in. The chain runs at the pace of its slowest link, and that
link moves as soon as it is fixed. Adding cranes to a berth starved of tractors
does nothing; adding tractors when the yard cranes are also serving a queue at
the gate does little more.

So this is a small, hour-by-hour simulation of that chain over a few weeks of
ship calls. Every hour it works out what each link could do, works the ships at
the smallest of them, and records which link that was. Over the run, the link
that held the rate back most often (or, when ships queue at anchor, the berths)
is the bottleneck.

A scenario is a set of numbers the user edits: berths, cranes, tractors, yard
cranes, gate lanes, how many ships come and how big their calls are, how much
weather stops the cranes. Every scenario for an asset sees the same ships
arriving in the same order (the random draws are seeded by the asset, not by
the scenario), so a difference between two scenarios is the change, not luck.
For each run, the same scenario is also run with one more of each resource, so
the page can say which addition actually helps.

The model is deliberately simple and is labelled as such: it is for comparing
options and finding the constraint, not for sizing a terminal.
"""

from __future__ import annotations

import json
import math
import random
from datetime import datetime, timedelta
from typing import Any

# What a scenario is made of: key, label, unit, default, minimum, maximum, step, group.
PARAMS = [
    ("days", "Simulated period", "days", 28, 7, 90, 1, "Demand"),
    ("ships_per_week", "Ship calls", "per week", 6, 1, 40, 0.5, "Demand"),
    ("moves_per_call", "Containers per call", "containers", 1800, 100, 8000, 50, "Demand"),
    ("road_share", "Boxes leaving or arriving by road", "%", 70, 0, 100, 5, "Demand"),
    ("berths", "Berths", "", 2, 1, 8, 1, "Quay"),
    ("sts", "Quay cranes (STS)", "", 6, 1, 24, 1, "Quay"),
    ("max_sts_per_ship", "Most cranes on one ship", "", 4, 1, 8, 1, "Quay"),
    ("sts_rate", "Quay crane rate", "containers/h", 28, 10, 45, 1, "Quay"),
    ("sts_availability", "Quay crane availability", "%", 95, 50, 100, 1, "Quay"),
    ("weather_downtime", "Hours lost to wind", "%", 3, 0, 30, 0.5, "Quay"),
    ("trucks", "Terminal tractors", "", 18, 1, 120, 1, "Horizontal transport"),
    ("truck_cycle", "Tractor cycle, crane to yard and back", "min", 15, 5, 45, 1, "Horizontal transport"),
    ("rtgs", "Yard cranes (RTG)", "", 8, 1, 60, 1, "Yard"),
    ("rtg_rate", "Yard crane rate", "containers/h", 18, 8, 35, 1, "Yard"),
    ("yard_capacity", "Yard capacity", "TEU", 14000, 1000, 100000, 500, "Yard"),
    ("dwell_days", "Average dwell", "days", 4, 1, 14, 0.5, "Yard"),
    ("gate_lanes", "Gate lanes", "", 6, 1, 30, 1, "Gate"),
    ("gate_rate", "Trucks per lane", "per hour", 25, 5, 60, 1, "Gate"),
    ("gate_open", "Gate open from", "h", 6, 0, 23, 1, "Gate"),
    ("gate_close", "Gate closes at", "h", 22, 1, 24, 1, "Gate"),
]
DEFAULTS = {key: default for key, _, _, default, *_ in PARAMS}
INTEGER = {"days", "berths", "sts", "max_sts_per_ship", "trucks", "rtgs", "gate_lanes", "gate_open", "gate_close"}

TEU_PER_MOVE = 1.6
BERTHING_HOURS = 2            # pilotage, berthing and lashing on arrival; unlashing and sailing after
YARD_CONGESTED = 0.85         # above this yard occupancy, re-handling slows the yard cranes

# The links of the chain, as the page names them.
LINKS = {
    "berth": "Berths",
    "sts": "Quay cranes",
    "trucks": "Terminal tractors",
    "rtgs": "Yard cranes",
    "gate": "Gate",
    "weather": "Weather",
}
# What one more of something means, for the "what helps most" test.
STEPS = [
    ("berths", 1, "one more berth"),
    ("sts", 1, "one more quay crane"),
    ("trucks", 4, "four more tractors"),
    ("rtgs", 2, "two more yard cranes"),
    ("gate_lanes", 2, "two more gate lanes"),
]
# What the advice suggests when a link is the bottleneck.
REMEDY = {
    "berth": "Ships are queuing for a berth. Add berth capacity, or shorten the time at berth by working each ship with more cranes.",
    "sts": "The quay cranes set the pace. Add a crane, allow more cranes per ship, or raise the crane rate (twin-lift, better spreaders).",
    "trucks": "The quay cranes are waiting for tractors. Add tractors, or shorten their cycle by stacking each ship's boxes closer to its berth.",
    "rtgs": "The yard cranes cannot keep up with the quay and the gate together. Add yard cranes, or spread the gate's trucks over more hours.",
    "gate": "Road trucks queue at the gate. Open more lanes, open the gate longer, or book trucks into time slots.",
    "weather": "Wind stops the cranes more than any resource does. Nothing to add: plan ship windows around the forecast.",
}


# What the chain is called at each kind of terminal. The model is the same: ships, the
# equipment that works them, the transport to the storage area, the storage area's own
# handling, and the gate. Only the words, the default numbers and the unit change.
TERMINAL = {
    "container": {"unit": "TEU", "per_move": TEU_PER_MOVE, "move": "containers"},
    "general_cargo": {
        "unit": "freight tonnes", "per_move": 8.0, "move": "lifts",
        "links": {"sts": "Harbour cranes", "trucks": "Trailers", "rtgs": "Forklifts", "berth": "Berths"},
        "labels": {"sts": "Mobile harbour cranes", "max_sts_per_ship": "Most cranes on one ship", "sts_rate": "Crane rate",
                   "trucks": "Trailers", "truck_cycle": "Trailer cycle, crane to shed and back", "rtgs": "Forklifts",
                   "rtg_rate": "Forklift rate", "yard_capacity": "Storage", "moves_per_call": "Lifts per call"},
        "units": {"sts_rate": "lifts/h", "rtg_rate": "lifts/h", "yard_capacity": "freight tonnes", "moves_per_call": "lifts"},
        "defaults": {"sts": 3, "max_sts_per_ship": 2, "sts_rate": 18, "moves_per_call": 900, "trucks": 10, "rtgs": 8,
                     "rtg_rate": 14, "yard_capacity": 40000, "ships_per_week": 5},
    },
    "roro": {
        "unit": "vehicles", "per_move": 1.0, "move": "vehicles",
        "links": {"sts": "Ramp lanes", "trucks": "Drivers", "rtgs": "Yard marshals", "berth": "Berths"},
        "labels": {"sts": "Ramp lanes", "max_sts_per_ship": "Ramp lanes on one ship", "sts_rate": "Vehicles per lane",
                   "sts_availability": "Ramp availability", "trucks": "Drivers", "truck_cycle": "Driver cycle, ship to park and back by shuttle",
                   "rtgs": "Yard marshals", "rtg_rate": "Vehicles parked per marshal", "yard_capacity": "Parking spaces",
                   "moves_per_call": "Vehicles per call"},
        "units": {"sts_rate": "per hour", "rtg_rate": "per hour", "yard_capacity": "vehicles", "moves_per_call": "vehicles"},
        "defaults": {"sts": 2, "max_sts_per_ship": 2, "sts_rate": 120, "sts_availability": 98, "moves_per_call": 1600,
                     "trucks": 40, "truck_cycle": 18, "rtgs": 10, "rtg_rate": 60, "yard_capacity": 6000, "dwell_days": 6,
                     "ships_per_week": 3, "weather_downtime": 1},
        "remedy": {
            "sts": "The ramp lanes set the pace. Open a second ramp or a side ramp, or cut the time each vehicle spends on the ramp.",
            "trucks": "Vehicles wait on deck for drivers. Add drivers, or shorten their shuttle back to the ship.",
            "rtgs": "The park cannot take vehicles as fast as they come off. Add marshals, or pre-assign parking rows.",
        },
    },
    "bulk": {
        "unit": "tonnes", "per_move": 25.0, "move": "grabs",
        "links": {"sts": "Ship unloaders", "trucks": "Conveyors", "rtgs": "Stackers", "berth": "Berths"},
        "labels": {"sts": "Ship unloaders", "max_sts_per_ship": "Unloaders on one ship", "sts_rate": "Unloader rate",
                   "trucks": "Conveyor lines (in 1/10ths)", "truck_cycle": "Conveyor cycle", "rtgs": "Stacker-reclaimers",
                   "rtg_rate": "Stacker rate", "yard_capacity": "Stockpile", "moves_per_call": "Grabs per call (25 t)"},
        "units": {"sts_rate": "grabs/h", "rtg_rate": "grabs/h", "yard_capacity": "tonnes", "moves_per_call": "grabs"},
        "defaults": {"sts": 2, "max_sts_per_ship": 2, "sts_rate": 40, "moves_per_call": 2400, "trucks": 20, "truck_cycle": 12,
                     "rtgs": 2, "rtg_rate": 80, "yard_capacity": 400000, "dwell_days": 10, "ships_per_week": 2,
                     "road_share": 60},
        "remedy": {
            "sts": "The unloaders set the pace. Add an unloader, or raise the grab cycle rate.",
            "trucks": "The conveyors cannot take what the unloaders discharge. Raise the conveyor capacity.",
            "rtgs": "The stockyard machines cannot keep up. Add a stacker or spread the truck loading over more hours.",
        },
    },
}
TERMINAL["multipurpose"] = {**TERMINAL["general_cargo"]}


def vocab(terminal: str) -> dict[str, Any]:
    """The words and numbers for a terminal type: labels for each number, link names, unit."""
    t = TERMINAL.get(terminal, TERMINAL["container"])
    labels = {key: (t.get("labels", {}).get(key, label), t.get("units", {}).get(key, unit)) for key, label, unit, *_ in PARAMS}
    links = {**LINKS, **t.get("links", {})}
    steps = []
    for key, step, words in STEPS:
        name = {"berths": "berth", "sts": links["sts"], "trucks": links["trucks"], "rtgs": links["rtgs"],
                "gate_lanes": "gate lanes"}[key].lower()
        if key == "gate_lanes":
            steps.append(words)
        elif key in ("berths", "sts"):
            steps.append(f"one more {name.rstrip('s')}" if key == "sts" else words)
        else:
            steps.append(f"{'four' if step == 4 else 'two'} more {name}")
    return {"labels": labels, "links": links, "unit": t["unit"], "per_move": t["per_move"], "move": t["move"],
            "defaults": {**DEFAULTS, **t.get("defaults", {})}, "remedy": {**REMEDY, **t.get("remedy", {})},
            "steps": dict(zip([k for k, *_ in STEPS], steps))}


def clean(form: dict[str, Any] | None) -> dict[str, Any]:
    """A scenario's numbers, each within its range; anything missing takes the default."""
    out = {}
    for key, _, _, default, lo, hi, _, _ in PARAMS:
        raw = (form or {}).get(key, default)
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = default
        if not math.isfinite(value):
            value = default
        value = min(max(value, lo), hi)
        out[key] = int(round(value)) if key in INTEGER else value
    if out["gate_close"] <= out["gate_open"]:
        out["gate_close"] = min(24, out["gate_open"] + 1)
    out["max_sts_per_ship"] = min(out["max_sts_per_ship"], out["sts"])
    return out


def _ships(asset_id: int, p: dict[str, Any], start: datetime) -> list[dict[str, Any]]:
    """The ship calls. One random stream per asset, so every scenario sees the same ships.

    Arrival gaps are drawn as uniform numbers and turned into exponential gaps at
    this scenario's call rate, so more calls a week means the same pattern, closer
    together, rather than a different pattern.
    """
    rng = random.Random(f"marinetwin-sim:{asset_id}")
    rate = p["ships_per_week"] / (7 * 24)                 # calls per hour
    hours = p["days"] * 24
    t, ships = 0.0, []
    for i in range(10000):
        u, size = rng.random(), rng.random()
        t += -math.log(1 - u) / rate
        if t >= hours:
            break
        moves = max(100, round(p["moves_per_call"] * (0.6 + 0.8 * size)))
        ships.append({"n": i + 1, "arrive": t, "moves": moves, "left": moves,
                      "at": start + timedelta(hours=t)})
    return ships


def _weather(asset_id: int, p: dict[str, Any]) -> list[bool]:
    """Which hours wind stops the cranes: spells of a few hours, about the given share."""
    rng = random.Random(f"marinetwin-sim-weather:{asset_id}")
    hours = p["days"] * 24
    stopped = [False] * hours
    share = p["weather_downtime"] / 100
    if share <= 0:
        return stopped
    spell = 6.0
    for h in range(hours):
        # A spell starts with the probability that gives the right share overall.
        if rng.random() < share / spell:
            for k in range(h, min(hours, h + int(rng.uniform(3, 2 * spell - 3)) + 1)):
                stopped[k] = True
    return stopped


def run(asset_id: int, params: dict[str, Any], start: datetime | None = None, detail: bool = True,
        terminal: str = "container") -> dict[str, Any]:
    p = clean(params)
    per_move = TERMINAL.get(terminal, TERMINAL["container"])["per_move"]
    start = (start or datetime(2026, 1, 5)).replace(minute=0, second=0, microsecond=0)
    hours = p["days"] * 24
    ships = _ships(asset_id, p, start)
    stopped = _weather(asset_id, p)
    sts_up = p["sts"] * p["sts_availability"] / 100
    truck_cap = p["trucks"] * 60 / p["truck_cycle"]
    gate_hours = [p["gate_open"] <= h % 24 < p["gate_close"] for h in range(hours)]
    open_per_day = max(1, p["gate_close"] - p["gate_open"])

    queue: list[dict[str, Any]] = []
    berthed: list[dict[str, Any]] = []
    done: list[dict[str, Any]] = []
    gate_queue = 0.0
    yard_in: list[float] = [0.0] * hours                  # TEU into the yard each hour
    dwell_h = int(p["dwell_days"] * 24)
    capacity_teu = p["yard_capacity"]
    binding = {k: 0 for k in LINKS}
    worked_hours = 0
    used = {"sts": 0.0, "trucks": 0.0, "rtgs": 0.0, "gate": 0.0, "berth": 0.0}
    timeline = []
    arrived = 0
    gate_backlog_max = 0.0
    yard_peak = 0.0

    for h in range(hours):
        while arrived < len(ships) and ships[arrived]["arrive"] <= h:
            queue.append(ships[arrived])
            arrived += 1
        while queue and len(berthed) < p["berths"]:
            ship = queue.pop(0)
            ship["berthed"] = max(h, ship["arrive"])
            ship["start_work"] = ship["berthed"] + BERTHING_HOURS / 2
            berthed.append(ship)
        used["berth"] += len(berthed)

        # The yard: occupancy over the dwell, and how much it slows the yard cranes.
        occupancy = sum(yard_in[max(0, h - dwell_h):h]) / capacity_teu if capacity_teu else 0
        yard_peak = max(yard_peak, occupancy)
        yard_factor = 1.0 if occupancy <= YARD_CONGESTED else max(0.5, 1 - 2 * (occupancy - YARD_CONGESTED))
        rtg_cap = p["rtgs"] * p["rtg_rate"] * yard_factor

        working = [s for s in berthed if s["start_work"] <= h and s["left"] > 0]
        # Quay cranes: the earliest ship first, up to the most one ship can take.
        cranes_free = sts_up
        for s in working:
            s["cranes"] = min(p["max_sts_per_ship"], cranes_free)
            cranes_free -= s["cranes"]
        crane_cap = 0.0 if stopped[h] else sum(s["cranes"] for s in working) * p["sts_rate"]
        vessel_demand = sum(min(s["left"], s["cranes"] * p["sts_rate"]) for s in working) if not stopped[h] else 0.0

        # Road trucks: the boxes the ships bring and take, spread over the gate's hours.
        road_moves_per_day = p["road_share"] / 100 * p["ships_per_week"] * p["moves_per_call"] / 7
        gate_demand = road_moves_per_day / open_per_day if gate_hours[h] else 0.0
        gate_queue += gate_demand
        gate_cap = p["gate_lanes"] * p["gate_rate"] if gate_hours[h] else 0.0

        vessel_moves = 0.0
        if working:
            worked_hours += 1
            limits = {"sts": vessel_demand, "trucks": truck_cap, "rtgs": rtg_cap}
            vessel_moves = min(limits.values())
            if stopped[h]:
                binding["weather"] += 1
            else:
                link = min(limits, key=limits.get)
                binding[link] += 1
            share = vessel_moves / vessel_demand if vessel_demand else 0
            for s in working:
                s["left"] = max(0.0, s["left"] - min(s["left"], s["cranes"] * p["sts_rate"]) * share)
        # The yard cranes serve the ships first, then the gate with what is left.
        gate_moves = min(gate_queue, gate_cap, max(0.0, rtg_cap - vessel_moves))
        gate_queue -= gate_moves
        gate_backlog_max = max(gate_backlog_max, gate_queue)
        yard_in[h] = (vessel_moves / 2 + gate_moves / 2) * per_move
        used["sts"] += vessel_moves
        used["trucks"] += vessel_moves
        used["rtgs"] += vessel_moves + gate_moves
        used["gate"] += gate_moves

        for s in list(berthed):
            if s["left"] <= 0.5 and s["start_work"] <= h:
                s["left"] = 0
                s["departed"] = h + 1 + BERTHING_HOURS / 2
                berthed.remove(s)
                done.append(s)
        if detail:
            timeline.append({"at": start + timedelta(hours=h), "waiting": len(queue), "alongside": len(berthed),
                             "gate_queue": round(gate_queue), "yard": round(100 * occupancy, 1),
                             "moves": round(vessel_moves), "past": False})

    # What was achieved.
    calls = []
    for s in ships[:arrived]:
        wait = (s.get("berthed", hours) - s["arrive"])
        service = (s["departed"] - s["berthed"]) if "departed" in s else None
        calls.append({"n": s["n"], "at": s["at"], "moves": s["moves"], "wait": round(wait, 1),
                      "service": round(service, 1) if service is not None else None,
                      "rate": round(s["moves"] / service) if service else None,
                      "finished": "departed" in s})
    finished = [c for c in calls if c["finished"]]
    waits = [c["wait"] for c in calls]
    moves_done = used["sts"]
    capacity = {
        "berth": p["berths"] * hours,
        "sts": sts_up * p["sts_rate"] * hours,
        "trucks": truck_cap * hours,
        "rtgs": p["rtgs"] * p["rtg_rate"] * hours,
        "gate": p["gate_lanes"] * p["gate_rate"] * sum(gate_hours),
    }
    utilisation = {k: round(100 * used[k] / capacity[k], 1) if capacity[k] else 0.0 for k in capacity}
    mean_wait = sum(waits) / len(waits) if waits else 0.0
    mean_service = sum(c["service"] for c in finished) / len(finished) if finished else 0.0

    # The pressure on each link: how often it held the rate back while ships were worked;
    # for the berths, how long ships waited against how long they were worked; for the
    # gate, the worst backlog against a day's road trucks.
    held = {k: (100 * v / worked_hours if worked_hours else 0.0) for k, v in binding.items()}
    held["berth"] = min(100.0, 100 * mean_wait / mean_service) if mean_service else (100.0 if mean_wait > 0 else 0.0)
    gate_daily = p["road_share"] / 100 * p["ships_per_week"] * p["moves_per_call"] / 7
    held["gate"] = min(100.0, 100 * gate_backlog_max / gate_daily) if gate_daily else 0.0
    ranked = sorted(held.items(), key=lambda kv: -kv[1])

    result = {
        "params": p,
        "kpis": {
            "calls": len(calls), "finished": len(finished),
            "moves": round(moves_done), "teu": round(moves_done * per_move),
            "teu_per_year": round(moves_done * per_move * 365 / p["days"]),
            "mean_wait": round(mean_wait, 1), "max_wait": round(max(waits), 1) if waits else 0.0,
            "mean_service": round(mean_service, 1),
            "turnaround": round(mean_wait + mean_service, 1),
            "berth_rate": round(sum(c["moves"] for c in finished) / sum(c["service"] for c in finished)) if finished else 0,
            "waiting_at_end": len(queue), "gate_backlog": round(gate_backlog_max),
            "yard_peak": round(100 * yard_peak),
        },
        "utilisation": utilisation,
        "held": {k: round(v) for k, v in held.items()},
        "ranked": [(k, round(v)) for k, v in ranked if v > 0],
        "calls": calls,
    }
    if detail:
        result["timeline"] = timeline
    return result


def what_helps(asset_id: int, params: dict[str, Any], base: dict[str, Any] | None = None,
               terminal: str = "container") -> list[dict[str, Any]]:
    """The same scenario with one more of each resource: how much each addition shortens a ship's stay."""
    base = base or run(asset_id, params, detail=False, terminal=terminal)
    words_for = vocab(terminal)["steps"]
    out = []
    for key, step, _ in STEPS:
        words = words_for[key]
        trial = dict(base["params"])
        trial[key] = trial[key] + step
        if key == "sts":
            trial["max_sts_per_ship"] = base["params"]["max_sts_per_ship"]
        r = run(asset_id, trial, detail=False, terminal=terminal)
        out.append({"key": key, "words": words,
                    "turnaround": r["kpis"]["turnaround"], "saves": round(base["kpis"]["turnaround"] - r["kpis"]["turnaround"], 1),
                    "teu": r["kpis"]["teu"], "more_teu": r["kpis"]["teu"] - base["kpis"]["teu"],
                    "gate_backlog": r["kpis"]["gate_backlog"]})
    gate_daily = base["params"]["road_share"] / 100 * base["params"]["ships_per_week"] * base["params"]["moves_per_call"] / 7
    for x in out:
        # One score for "how much better": shorter ship stays, more boxes, a shorter gate
        # queue. A longer gate queue is not counted against it: it means the fix worked and
        # the bottleneck moved on to the yard, which the page says as a side effect.
        x["score"] = round(
            100 * x["saves"] / max(base["kpis"]["turnaround"], 1)
            + 100 * x["more_teu"] / max(base["kpis"]["teu"], 1)
            + 50 * max(0, base["kpis"]["gate_backlog"] - x["gate_backlog"]) / max(gate_daily, 1), 1)
        x["gate_worse"] = x["gate_backlog"] - base["kpis"]["gate_backlog"] if x["gate_backlog"] > base["kpis"]["gate_backlog"] + 50 else 0
    out.sort(key=lambda x: -x["score"])
    return out


LINK_OF = {"berths": "berth", "sts": "sts", "trucks": "trucks", "rtgs": "rtgs", "gate_lanes": "gate"}


def assess(asset_id: int, params: dict[str, Any], detail: bool = True, terminal: str = "container") -> dict[str, Any]:
    """A run, what one more of each resource would do, and the bottleneck that follows.

    The bottleneck is the resource whose addition helps most: the pressure figures
    show where the rate was held back, but a queue at the berths or the gate is
    often the symptom of a link further down the chain, and only trying the
    additions tells the two apart.
    """
    result = run(asset_id, params, detail=detail, terminal=terminal)
    helps = what_helps(asset_id, params, result, terminal)
    best = helps[0] if helps else None
    if best and best["score"] >= 2:
        bottleneck = LINK_OF[best["key"]]
    elif result["held"].get("weather", 0) >= 15:
        bottleneck = "weather"
    else:
        bottleneck = None
    result.update({"helps": helps, "bottleneck": bottleneck,
                   "remedy": vocab(terminal)["remedy"].get(bottleneck, "Nothing holds the terminal back: one more of any resource changes little.")})
    return result


# --- scenarios kept for an asset --------------------------------------------------

def scenarios(conn: Any, asset_id: int, terminal: str = "container") -> list[dict[str, Any]]:
    """The asset's scenarios, the baseline first; a baseline is made on first use."""
    rows = conn.execute("SELECT * FROM marine_scenarios WHERE asset_id = ? ORDER BY id", (asset_id,)).fetchall()
    if not rows:
        conn.execute("INSERT INTO marine_scenarios (asset_id, name, params) VALUES (?, ?, ?)",
                     (asset_id, "Baseline", json.dumps(vocab(terminal)["defaults"])))
        conn.commit()
        rows = conn.execute("SELECT * FROM marine_scenarios WHERE asset_id = ? ORDER BY id", (asset_id,)).fetchall()
    return [{"id": r["id"], "name": r["name"], "params": clean(json.loads(r["params"])),
             "created_at": r["created_at"]} for r in rows]


def save(conn: Any, asset_id: int, name: str, params: dict[str, Any], scenario_id: int | None = None,
         user_id: int | None = None) -> int:
    p = json.dumps(clean(params))
    if scenario_id:
        conn.execute("UPDATE marine_scenarios SET name = ?, params = ? WHERE id = ? AND asset_id = ?",
                     (name, p, scenario_id, asset_id))
        return scenario_id
    return conn.execute("INSERT INTO marine_scenarios (asset_id, name, params, created_by) VALUES (?, ?, ?, ?)",
                        (asset_id, name, p, user_id)).lastrowid


def changes(base: dict[str, Any], other: dict[str, Any], terminal: str = "container") -> list[str]:
    """What a scenario changes from the baseline, in words."""
    out = []
    words = vocab(terminal)["labels"]
    for key, *_ in PARAMS:
        label, unit = words[key]
        if base.get(key) != other.get(key):
            out.append(f"{label} {_num(base[key])} → {_num(other[key])}{(' ' + unit) if unit and unit != '%' else unit}")
    return out


def _num(v: Any) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"
