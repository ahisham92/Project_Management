"""MarineTwin's lifecycle: the berth's whole design life played in a few minutes.

The Structure step says how the berth is now and where it is heading; this says
what that means over fifty years of work, and what it costs to look after it or
not. Month by month from the day it was commissioned:

* **the weather and the sea** — seasons, storms with their winds and surges,
  now and then a great storm, and the sea rising year on year, so a surge that
  stayed below the cope in year 5 comes over it in year 40;
* **the structure** — fenders wearing after about fifteen years and replaced one
  by one; the front wall losing steel at about the rate its allowance assumed,
  faster where low water corrosion sets in; the deck cracking, spalling and
  delaminating once chlorides reach the rebar; bollards cracking when old;
* **the utilities** — water and fire mains, drainage, power (substation and
  cables) and the mast lighting, each with its expected life; drains silt up,
  and blocked drains in heavy rain or a flood mean pipes and cable ducts full of
  water, flooding on the apron and power cuts;
* **the risks** the person chooses to include: earthquakes, power cuts from the
  grid, a ship striking the quay, fire, a cyber attack, a pandemic, and the
  force majeure of a war, felt indirectly (trade falls away) or directly (the
  berth is hit).

Each time something needs attention it is an **issue** with three answers:
*fix it* (pay for the repair and lose that part of the berth while it is done),
*close the area* (pay nothing now, lose its share of the berth every day), or
*wait* (it keeps working until it gets worse). Some issues are about adapting
rather than mending: raising the cope once the sea starts coming over it, or
buying backup generators after a long power cut. Three ways to play it:

* ``nothing`` — every issue is left; failed parts restrict the berth whether
  anyone decides it or not, and when enough of the wall has gone the berth is
  taken out of service;
* ``fix`` — every issue is fixed as soon as it is found;
* ``game`` — the person decides each one (``choices``); the run stops at the
  first issue nobody has answered yet, so the page can ask.

Everything is counted in what the berth is for: **moves** (container moves, or
lifts, vehicles, tonnes for other terminals). Lost moves are the moves the berth
could not handle, whatever the cause; a repair's price is turned into moves at
the value of a move, so one number says what each way of looking after the berth
cost. Money is the same number times the value of a move. A part repaired for
wear inside its warranty costs nothing. Rates, prices, lives, warranties and the
risks are the person's to change.

Like the other operational feeds this is **simulated**, deterministically per
asset: the same berth tells the same story every time, a choice changes only what
comes after it, and the hazards fall in the same months whichever way the berth
is looked after. The corrosion allowance and design life come from Triton through
``marine_triton`` (read only); everything else is a typical figure, labelled as
indicative.
"""

from __future__ import annotations

import math
import random
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import marine_ops, marine_triton

DAYS_IN_MONTH = 365.25 / 12
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# What the berth earns, per terminal: moves a day at full working, and what one move is worth (USD).
MOVES_PER_DAY = {"container": 1800, "general_cargo": 700, "roro": 1500, "bulk": 900, "multipurpose": 900}
VALUE_PER_MOVE = {"container": 110, "general_cargo": 60, "roro": 35, "bulk": 40, "multipurpose": 60}
# Typical repair prices (USD, indicative). A wall or deck price is for one bay.
PRICES = {
    "fender": 90_000,
    "bollard": 30_000,
    "wall_cp": 400_000,         # cathodic protection retrofit and coating at the splash zone
    "wall_plate": 1_600_000,    # plating the thinned steel, with cathodic protection
    "wall_rehab": 6_000_000,    # a new front wall for the bay
    "deck_patch": 150_000,      # patch repair and a silane coat
    "deck_repair": 700_000,     # breaking out and recasting spalled concrete
    "deck_replace": 2_800_000,  # a new deck slab for the bay
    "pipes": 650_000,           # renewing the water and fire mains along the berth
    "drain_clean": 25_000,      # jetting the drains and emptying the interceptors
    "drain_repair": 300_000,    # relining collapsed drains
    "power": 1_200_000,         # a new substation and the cables to the cranes
    "lighting": 220_000,        # new LED heads and drivers on the masts
    "raise_quay": 4_500_000,    # raising the cope and the apron edge by 0.6 m
    "generators": 450_000,      # backup generators for the cranes and the reefers
    "war_rebuild": 40_000_000,  # rebuilding after a direct hit
}
PRICE_NAMES = {
    "fender": "Replace a fender", "bollard": "Replace a bollard", "wall_cp": "Wall bay: cathodic protection",
    "wall_plate": "Wall bay: plate the thinned steel", "wall_rehab": "Wall bay: rebuild",
    "deck_patch": "Deck bay: patch and coat", "deck_repair": "Deck bay: concrete repair", "deck_replace": "Deck bay: new slab",
    "pipes": "Renew the water and fire mains", "drain_clean": "Clean the drains", "drain_repair": "Reline the drains",
    "power": "New substation and cables", "lighting": "Relamp the masts", "raise_quay": "Raise the quay 0.6 m",
    "generators": "Buy backup generators", "war_rebuild": "Rebuild after the hit",
}

# Expected life and warranty (years) of each kind of part, and what the warranty covers. A wear
# repair inside the warranty is the supplier's; damage from a storm, a ship or a war never is.
KIND_INFO = {
    "fender": (20, 5, "the rubber and the panel against defects"),
    "wall": (50, 2, "the contractor's defects period"),
    "deck": (50, 2, "the contractor's defects period"),
    "bollard": (30, 5, "the casting against defects"),
    "pipes": (30, 10, "the pipes and joints against defects"),
    "drainage": (40, 2, "the contractor's defects period"),
    "power": (25, 5, "the transformer and switchgear"),
    "lighting": (18, 5, "the LED heads and drivers"),
}

# The most of each kind the run follows; more elements than this are grouped along the berth.
MOST = {"fender": 40, "wall": 8, "deck": 8, "bollard": 16}
# Corrosion: a bay with cathodic protection loses steel at this share of its unprotected rate.
PROTECTED = 0.15
# Wall: half the allowance gone is a warning; all of it a load restriction; this much more, unsafe.
WALL_UNSAFE = 1.35
WALL_CONDEMNED = 1.8

# Each kind's stages: (name, what it means, the repair: price key, days out, share of the part out while it is done).
STAGES: dict[str, dict[int, tuple[str, str, str, float, float]]] = {
    "fender": {
        1: ("worn", "Panel pads worn and the rubber cracking. It still works.", "fender", 3, 1.0),
        2: ("damaged", "Rubber split: ships berth slower on this section.", "fender", 4, 1.0),
        3: ("failed", "Fender torn off: no ship can berth on this section.", "fender", 5, 1.0),
    },
    "wall": {
        1: ("corroding", "Half the corrosion allowance gone. Protect it now and it lasts.", "wall_cp", 10, 0.3),
        2: ("past its allowance", "Steel thinner than designed: loads kept back from the edge behind it.", "wall_plate", 30, 1.0),
        3: ("unsafe", "Wall too thin to be safe: the bay is closed.", "wall_rehab", 120, 1.0),
    },
    "deck": {
        1: ("cracking", "Chlorides at the rebar: cracks and rust stains.", "deck_patch", 7, 0.5),
        2: ("spalling", "Concrete spalling: trucks kept off the bay.", "deck_repair", 21, 1.0),
        3: ("delaminated", "Deck delaminating: the bay is closed.", "deck_replace", 60, 1.0),
    },
    "bollard": {
        3: ("cracked", "Bollard cracked: ships cannot moor on it.", "bollard", 2, 1.0),
    },
    "pipes": {
        1: ("leaking", "The water and fire mains are near the end of their life and leaking.", "pipes", 10, 0.2),
        2: ("burst", "A main burst: no fire water on part of the berth, so work there stops.", "pipes", 14, 0.3),
    },
    "drainage": {
        1: ("silting up", "Drains silting up: heavy rain will back up onto the apron.", "drain_clean", 2, 0.1),
        2: ("blocked", "Drains blocked: the pipes stay full of water, the apron floods in rain and the cable ducts fill.", "drain_repair", 7, 0.3),
    },
    "power": {
        1: ("ageing", "Substation and cables near the end of their life: power cuts come more often.", "power", 14, 0.3),
        2: ("failed", "Power failed on the berth: the cranes stop.", "power", 21, 0.6),
    },
    "lighting": {
        2: ("failing", "Mast lights failing: night work slows down.", "lighting", 5, 0.2),
    },
    "quay": {
        2: ("overtopped", "The sea came over the quay. With the sea rising it will happen more often: raise the cope?", "raise_quay", 90, 0.3),
    },
    "backup": {
        2: ("no backup power", "A long power cut stopped the cranes. Backup generators would keep them working.", "generators", 5, 0.0),
    },
    "war": {
        3: ("hit", "Direct hit: cranes and the quay damaged. The berth is closed until it is rebuilt.", "war_rebuild", 270, 1.0),
    },
}
# How much of a part's share of the berth each stage takes away while it is left.
RESTRICTION = {
    "fender": {2: 0.4, 3: 0.8},
    "wall": {2: 0.5, 3: 1.0},
    "deck": {2: 0.6, 3: 1.0},
    "bollard": {3: 1.0},
    "pipes": {2: 1.0},
    "drainage": {},
    "power": {2: 1.0},
    "lighting": {2: 1.0},
    "quay": {},
    "backup": {},
    "war": {3: 1.0},
}
KIND_NAME = {"fender": "Fender", "wall": "Front wall", "deck": "Deck", "bollard": "Bollard", "pipes": "Water and fire mains",
             "drainage": "Drainage", "power": "Power supply", "lighting": "Mast lighting", "quay": "Quay level",
             "backup": "Backup power", "war": "Berth"}
POLICIES = {"nothing": "Do nothing", "fix": "Fix as you go", "game": "You decide"}
# Wear the warranty covers (not storms, ships, quakes or wars).
WEAR = {"fender", "bollard", "pipes", "power", "lighting", "wall", "deck"}

# --- the risks -------------------------------------------------------------------------------
# key: (name, group, on unless the person says otherwise, what it does)
RISKS = {
    "storms": ("Storms and wind", "Nature", True, "Storms stop the cranes for a day or two; a great storm about once in thirteen years batters the fenders."),
    "sea_level": ("Sea-level rise", "Nature", True, "The sea rises year on year, faster later; storm surges that come over the cope flood the apron and the ducts."),
    "earthquake": ("Earthquakes", "Nature", True, "A damaging earthquake now and then: inspections close the berth, and the wall, deck and pipes take damage."),
    "power_cuts": ("Power cuts", "Operations", True, "Grid cuts of a few hours stop the cranes; more often as the substation ages; generators cover them."),
    "vessel_strike": ("A ship strikes the quay", "Operations", True, "A ship comes in too fast: fenders torn off and the wall behind them damaged."),
    "fire": ("Fire", "Operations", True, "A fire on the apron: the deck bay damaged and closed, the lights and cables there lost."),
    "cyber": ("Cyber attack", "Operations", True, "The terminal's systems locked: the berth stops for a few days."),
    "pandemic": ("Pandemic", "Force majeure", False, "Trade falls by a quarter for a year or two."),
    "war_indirect": ("War, felt indirectly", "Force majeure", False, "A war in the region: shipping lines avoid it and trade falls by nearly half for a few years."),
    "war_direct": ("War, the port hit", "Force majeure", False, "The berth is hit: cranes, wall and deck damaged and the berth closed until it is rebuilt."),
}
SEA_LEVEL = {"low": 0.15, "medium": 0.30, "high": 0.60}            # metres of rise over the design life
SEISMIC = {"low": 0.004, "moderate": 0.015, "high": 0.04}           # a damaging earthquake, chance a year
FREEBOARD = 1.5                                                     # m from the highest storm tide to the cope


def settings_for(given: dict[str, Any] | None = None) -> dict[str, Any]:
    """Which risks a run includes and how strong: the defaults, with whatever the person changed.
    A risk is on with ``risk_<key>`` = 1 and off with 0; ``sea_level`` and ``seismic`` take a level;
    ``war_year`` fixes the year of a war (otherwise it falls in a year of the run's choosing)."""
    given = given or {}
    out: dict[str, Any] = {}
    for key, (_, _, default, _) in RISKS.items():
        value = given.get(f"risk_{key}")
        out[key] = default if value in (None, "") else str(value).lower() in ("1", "true", "on", "yes")
    out["sea_level"] = out["sea_level"] and (given.get("sea_level") if given.get("sea_level") in SEA_LEVEL else "medium")
    out["earthquake"] = out["earthquake"] and (given.get("seismic") if given.get("seismic") in SEISMIC else "low")
    try:
        year = int(float(given.get("war_year") or 0))
    except (TypeError, ValueError):
        year = 0
    out["war_year"] = year if year > 0 else None
    try:
        freeboard = float(given.get("freeboard") or FREEBOARD)
    except (TypeError, ValueError):
        freeboard = FREEBOARD
    out["freeboard"] = freeboard if math.isfinite(freeboard) and 0 < freeboard < 10 else FREEBOARD
    return out


def rates_for(terminal: str, given: dict[str, Any] | None = None) -> dict[str, float]:
    """The rates a run uses: the terminal's defaults, the prices, each kind's expected life and
    warranty, with whatever the person changed."""
    rates: dict[str, float] = {
        "moves_per_day": float(MOVES_PER_DAY.get(terminal, 1000)),
        "value_per_move": float(VALUE_PER_MOVE.get(terminal, 80)),
        **{k: float(v) for k, v in PRICES.items()},
        **{f"life_{k}": float(v[0]) for k, v in KIND_INFO.items()},
        **{f"warranty_{k}": float(v[1]) for k, v in KIND_INFO.items()},
    }
    for key, value in (given or {}).items():
        if key not in rates:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and (number > 0 or (key.startswith("warranty_") and number == 0)):
            rates[key] = number
    return rates


# --- the parts the run follows ------------------------------------------------------------

@dataclass
class Part:
    id: str
    kind: str                       # fender, wall, deck, bollard, pipes, drainage, power, lighting, quay, backup, war
    name: str
    refs: list[str]                 # the elements (model refs) it stands for, for the 3D view
    at: tuple[float, float]         # where along the berth, 0..1
    share: float = 0.0              # the share of the berth it takes when it is out
    # the state, for whichever kind it is
    age: float = 0.0                # years since it was new (or renewed)
    onset: float = 0.0              # fender: years before it starts to wear; deck: before the chlorides arrive
    rate: float = 0.0               # fender: wear a year after onset; wall: mm a year
    hits: float = 0.0               # fender: damage from bad berthings
    loss: float = 0.0               # wall: mm lost
    allowance: float = 1.0          # wall: mm it may lose
    alwc: float = 99.0              # wall: the year low water corrosion sets in
    protected: bool = False
    steps: tuple[float, float, float] = (99.0, 99.0, 99.0)   # deck: ages it cracks, spalls, delaminates
    failed: bool = False            # bollard, power, pipes: broken outright; quay, backup, war: the issue is raised
    silt: float = 0.0               # drainage
    life: float = 0.0               # utilities: the life this one will have, drawn about its expected life
    stage: int = 0
    raised: int = 0                 # the highest stage an issue has been raised for
    occurrence: int = 0             # how many times it has been renewed
    installed: int = 0              # the month it was put in (or last renewed)
    issue: dict[str, Any] | None = None
    closed: bool = False
    repair_days: float = 0.0
    repair_share: float = 0.0
    draws: list[float] = field(default_factory=list)


def _groups(elements: list[dict[str, Any]], most: int) -> list[list[dict[str, Any]]]:
    """Elements in order along the berth, in at most ``most`` groups of neighbours."""
    ordered = sorted(elements, key=lambda e: (e.get("x") or 0.0, e["name"]))
    if len(ordered) <= most:
        return [[e] for e in ordered]
    size = len(ordered) / most
    return [ordered[round(i * size):round((i + 1) * size)] for i in range(most)]


UTILITY_NAMES = {
    "pipes": re.compile(r"PIPE|WATER|FIRE|HYDRANT|MAIN", re.I),
    "drainage": re.compile(r"DRAIN|GULLY|INTERCEPT|SEWER|STORM", re.I),
    "power": re.compile(r"CABLE|DUCT|POWER|SUBST|ELEC|TRANSF", re.I),
    "lighting": re.compile(r"LIGHT|LAMP|MAST|LUMIN", re.I),
}


def parts_for(elements: Iterable[Any], allowance: float, life: int, asset_id: int,
              rates: dict[str, float] | None = None) -> list[Part]:
    """The parts of the berth the run follows, from its elements: fenders one by one (or in small
    groups), the front wall and the deck in bays, the bollards, and the utilities (from elements
    named for them, such as the model's pipes). A kind the model does not have is stood in for,
    evenly along the berth, so every berth has a story to tell."""
    rates = rates or rates_for("container")
    rows = [dict(e) for e in elements]
    xs = [r.get("x") or 0.0 for r in rows] or [0.0]
    lo, hi = min(xs), max(xs)
    span = hi - lo if hi - lo > 1e-6 else 1.0

    def where(group: list[dict[str, Any]]) -> tuple[float, float]:
        a = ((group[0].get("x") or 0.0) - lo) / span
        b = ((group[-1].get("x") or 0.0) - lo) / span
        return (round(a, 4), round(b, 4))

    by_kind: dict[str, list[dict[str, Any]]] = {
        "fender": [r for r in rows if r["kind"] == "fender"],
        "wall": [r for r in rows if r["kind"] in ("combi_wall", "sheet_pile")] or [r for r in rows if r["kind"] == "pile"],
        "deck": [r for r in rows if r["kind"] in ("slab", "beam")],
        "bollard": [r for r in rows if r["kind"] == "bollard"],
    }
    stand_in = {"fender": 10, "wall": 6, "deck": 6, "bollard": 8}
    tags = {"fender": "F", "wall": "W", "deck": "D", "bollard": "B"}
    bay = lambda kind, i: f"{KIND_NAME[kind]} bay {i + 1}"  # noqa: E731
    refs = lambda g: [x.get("model_ref") or x["name"] for x in g]  # noqa: E731
    parts: list[Part] = []
    for kind, found in by_kind.items():
        groups = _groups(found, MOST[kind])
        if kind in ("wall", "deck") and found and len(groups) < 3:
            # One deck slab, or a wall of a panel or two, is still followed in three bays along the berth.
            entries = [(bay(kind, i), refs(found), (i / 3, (i + 1) / 3)) for i in range(3)]
        elif groups:
            entries = [(g[0]["name"] if len(g) == 1 else bay(kind, i) if kind in ("wall", "deck") else f"{g[0]['name']}–{g[-1]['name']}",
                        refs(g), where(g)) for i, g in enumerate(groups)]
        else:
            n = stand_in[kind]
            entries = [(bay(kind, i) if kind in ("wall", "deck") else f"{tags[kind]}{i + 1:02d}", [],
                        (i / n, (i + 1) / n) if kind in ("wall", "deck") else ((i + 0.5) / n, (i + 0.5) / n))
                       for i in range(n)]
        for i, (name, covers, at) in enumerate(entries):
            parts.append(Part(id=f"{tags[kind]}{i + 1}", kind=kind, name=name, refs=covers, at=at))
    # The utilities: one of each along the whole berth, standing for the model's elements named for it.
    taken: set[str] = set()
    for kind, pattern, tag in (("pipes", UTILITY_NAMES["pipes"], "U1"), ("drainage", UTILITY_NAMES["drainage"], "U2"),
                               ("power", UTILITY_NAMES["power"], "U3"), ("lighting", UTILITY_NAMES["lighting"], "U4")):
        found = [r for r in rows if r["kind"] in ("other", "pipe") and pattern.search(r["name"]) and r["name"] not in taken]
        taken |= {r["name"] for r in found}
        parts.append(Part(id=tag, kind=kind, name=KIND_NAME[kind], refs=refs(found), at=(0.0, 1.0)))
    # And what the berth may have to adapt: its level against the sea, its power against cuts, and (if
    # a war reaches it) the berth as a whole.
    parts.append(Part(id="Q1", kind="quay", name=KIND_NAME["quay"], refs=[], at=(0.0, 1.0)))
    parts.append(Part(id="G1", kind="backup", name=KIND_NAME["backup"], refs=[], at=(0.0, 1.0)))
    parts.append(Part(id="X1", kind="war", name="The berth", refs=[], at=(0.0, 1.0)))

    fenders = [p for p in parts if p.kind == "fender"]
    bays = {k: [p for p in parts if p.kind == k] for k in ("wall", "deck", "bollard")}
    shares = {"pipes": 0.2, "drainage": 0.2, "power": 0.3, "lighting": 0.15, "quay": 0.0, "backup": 0.0, "war": 1.0}
    for p in parts:
        if p.kind == "fender":
            p.share = min(0.3, 1.2 / max(len(fenders), 8))
        elif p.kind == "bollard":
            p.share = 0.5 / max(len(bays["bollard"]), 8)
        elif p.kind in shares:
            p.share = shares[p.kind]
        else:
            p.share = 1 / len(bays[p.kind])
        p.allowance = allowance
        rng = random.Random(f"marinetwin-life:{asset_id}:{p.id}:draws")
        p.draws = [rng.random() for _ in range(12 * (life + 1) * 2)]
        _renew(p, asset_id, life, full=True, rates=rates)
    return parts


def _renew(p: Part, asset_id: int, life: int, full: bool, stage: int = 0, rates: dict[str, float] | None = None) -> None:
    """A part as it is when new or just repaired. Its draws are fixed per part and renewal, so
    a choice changes what comes after it and nothing before."""
    rng = random.Random(f"marinetwin-life:{asset_id}:{p.id}:{p.occurrence}")
    rates = rates or {}
    p.stage = p.raised = 0
    p.issue = None
    p.closed = False
    if p.kind == "fender":
        p.age, p.hits = 0.0, 0.0
        # Wear starts at about three quarters of the expected life (fifteen of twenty years).
        expected = rates.get("life_fender", 20.0)
        p.onset = expected * rng.uniform(0.7, 1.0)
        p.rate = rng.uniform(0.12, 0.26) * 20.0 / expected
    elif p.kind == "wall":
        if full:
            p.loss = 0.0
            p.rate = p.allowance / life * rng.uniform(0.85, 1.3)
            p.alwc = rng.uniform(14.0, 30.0) if rng.random() < 0.35 else 99.0
        elif stage == 2:
            p.loss = 0.3 * p.allowance          # plates put the steel back
        elif stage == 3:
            p.loss = 0.0
    elif p.kind == "deck":
        p.age = 0.0
        start = rng.uniform(16.0, 28.0) if full or stage == 3 else rng.uniform(12.0, 20.0) if stage == 1 else rng.uniform(15.0, 22.0)
        crack = start + rng.uniform(3.0, 6.0)
        spall = crack + rng.uniform(4.0, 7.0)
        p.steps = (crack, spall, spall + rng.uniform(5.0, 9.0))
        p.onset = start
    elif p.kind == "bollard":
        p.age, p.failed = 0.0, False
    elif p.kind == "drainage":
        if full or stage == 2:
            p.age = 0.0
        p.silt = 0.0
        p.rate = 1 / rng.uniform(2.5, 4.0)       # silt a year: blocked-ish in three years or so
    elif p.kind in ("pipes", "power", "lighting"):
        p.age, p.failed = 0.0, False
        p.life = rates.get(f"life_{p.kind}", KIND_INFO[p.kind][0]) * rng.uniform(0.85, 1.15)
    elif p.kind in ("quay", "backup", "war"):
        p.failed = False


def _stage(p: Part) -> int:
    if p.kind == "fender":
        d = max(0.0, p.age - p.onset) * p.rate + p.hits
        return 3 if d >= 1.0 else 2 if d >= 0.75 else 1 if d >= 0.45 else 0
    if p.kind == "wall":
        u = p.loss / p.allowance
        return 3 if u >= WALL_UNSAFE else 2 if u >= 1.0 else 1 if u >= 0.5 else 0
    if p.kind == "deck":
        return sum(1 for s in p.steps if p.age >= s)
    if p.kind == "bollard":
        return 3 if p.failed else 0
    if p.kind == "drainage":
        return 2 if p.silt >= 1.6 else 1 if p.silt >= 1.0 else 0
    if p.kind in ("pipes", "power"):
        return 2 if p.failed or p.age >= p.life * 1.05 else 1 if p.age >= p.life * 0.85 else 0
    if p.kind == "lighting":
        return 2 if p.failed or p.age >= p.life else 0
    if p.kind == "war":
        return 3 if p.failed else 0
    return 2 if p.failed else 0                       # quay, backup: raised by what happened


def condition(p: Part) -> int:
    """How worn the part is, 0 (as new) to 100 (gone), for the colours in the 3D view."""
    if p.kind == "fender":
        d = max(0.0, p.age - p.onset) * p.rate + p.hits
    elif p.kind == "wall":
        d = p.loss / p.allowance / WALL_UNSAFE
    elif p.kind == "deck":
        d = min(1.0, p.age / p.steps[2]) ** 3
    elif p.kind == "drainage":
        d = p.silt / 1.6
    elif p.kind in ("pipes", "power", "lighting"):
        d = 1.0 if p.failed else (p.age / p.life) ** 2 if p.life else 0.0
    elif p.kind in ("quay", "backup", "war"):
        d = 1.0 if p.failed else 0.0
    else:
        d = 1.0 if p.failed else min(0.4, p.age / 100)
    return int(round(100 * min(max(d, 0.0), 1.0)))


# --- the weather, the sea and the hazards -------------------------------------------------

def weather(asset_id: int, months: int, settings: dict[str, Any] | None = None, life: int = 50) -> list[dict[str, Any]]:
    """Each month's weather and what befell the berth: rain, wind, the temperature, any storm (1)
    or great storm (2) with the days it stops the berth and its surge, the sea's rise so far, and
    the hazards of the risks included (``haz``: a list of [key, severity 0..1]). Drawn in full
    whatever is included, so switching a risk off changes only that risk."""
    settings = settings or settings_for()
    rng = random.Random(f"marinetwin-life:{asset_id}:weather")
    haz_rng = random.Random(f"marinetwin-life:{asset_id}:hazards")
    rise = SEA_LEVEL.get(settings.get("sea_level") or "", 0.0)
    quake_p = SEISMIC.get(settings.get("earthquake") or "", 0.0)
    years = max(1, months // 12)
    # The wars, if any: the year it starts (the person's, or one drawn), how long trade suffers.
    war_year = settings.get("war_year") or haz_rng.randint(max(5, years // 3), max(6, years * 4 // 5))
    war_length = haz_rng.randint(24, 48)
    hit_month = (war_year - 1) * 12 + haz_rng.randint(3, 9)
    pandemic_at, pandemic_length = None, haz_rng.randint(12, 24)
    out = []
    for m in range(months):
        season = math.cos(2 * math.pi * ((m % 12) - 6) / 12)          # 1 in July, -1 in January
        rain = max(0.0, 1.6 + 2.6 * season + rng.gauss(0, 1.0))
        wind = max(2.0, 6.5 + 1.8 * season + rng.gauss(0, 1.4))
        temp = 27.0 - 1.8 * season + rng.gauss(0, 0.6) + 0.02 * m / 12      # and a little warmer each decade
        storm, days, surge = 0, 0.0, 0.0
        roll = rng.random()
        surge_draw = rng.random()
        if roll < 1 / 160:
            storm, days, surge = 2, rng.uniform(4.0, 7.0), 0.8 + 0.8 * surge_draw
            wind, rain = wind + 14, rain + 6
        elif roll < 0.10 + 0.08 * season:
            storm, days, surge = 1, rng.uniform(0.5, 2.5), 0.1 + 0.6 * surge_draw
            wind, rain = wind + 7, rain + 3
        if not settings.get("storms"):
            storm, days, surge = 0, 0.0, 0.0
        slr = rise * (m / months) ** 1.5 if months else 0.0                  # faster later
        # The hazards: every draw made every month, used only when the risk is included.
        draws = [haz_rng.random() for _ in range(9)]
        haz: list[list[Any]] = []
        if quake_p and draws[0] < quake_p / 12:
            haz.append(["earthquake", round(0.3 + 0.7 * draws[1], 2)])
        if settings.get("power_cuts") and draws[2] < 0.15:
            haz.append(["power_cut", round(1 + 11 * draws[3], 1)])                 # hours
        if settings.get("vessel_strike") and draws[4] < 0.015 / 12:
            haz.append(["vessel_strike", round(draws[1], 2)])
        if settings.get("fire") and draws[5] < 0.006 / 12:
            haz.append(["fire", round(draws[3], 2)])
        if settings.get("cyber") and m >= 60 and draws[6] < 0.01 / 12:
            haz.append(["cyber", round(2 + 4 * draws[1], 1)])                    # days
        if settings.get("pandemic") and pandemic_at is None and m >= 60 and draws[7] < 0.015 / 12:
            pandemic_at = m
        demand = 1.0
        if pandemic_at is not None and pandemic_at <= m < pandemic_at + pandemic_length:
            demand *= 0.75
            if m == pandemic_at:
                haz.append(["pandemic", 0.25])
        war_from = (war_year - 1) * 12
        if settings.get("war_indirect") and war_from <= m < war_from + war_length:
            demand *= 0.55
            if m == war_from:
                haz.append(["war_indirect", 0.45])
        if settings.get("war_direct") and m == hit_month:
            haz.append(["war_direct", 1.0])
        out.append({"rain": round(rain, 1), "wind": round(wind, 1), "temp": round(temp, 1), "storm": storm,
                    "storm_days": round(days, 2), "surge": round(surge, 2), "slr": round(slr, 3), "haz": haz,
                    "demand": round(demand, 3)})
    return out


# --- the run ------------------------------------------------------------------------------

def _price(p: Part, price_key: str, rates: dict[str, float], m: int, wear: bool = True) -> tuple[float, bool]:
    """What a repair costs, and whether the warranty pays it instead."""
    years = (m - p.installed) / 12
    covered = wear and p.kind in WEAR and years < rates.get(f"warranty_{p.kind}", 0.0)
    return (0.0 if covered else rates[price_key]), covered


def _is_wear(p: Part) -> bool:
    """Whether a part needs mending from wear (which a warranty covers) rather than damage."""
    if p.kind == "fender":
        return p.hits < 0.5
    return p.kind in WEAR and (not p.failed or p.kind == "bollard")


def _options(p: Part, stage: int, rates: dict[str, float], m: int) -> dict[str, Any]:
    """What each answer to an issue costs, in moves (and money)."""
    name, meaning, price_key, days, out = STAGES[p.kind][stage]
    per_day = rates["moves_per_day"]
    price, covered = _price(p, price_key, rates, m, wear=_is_wear(p))
    lost_fixing = per_day * days * out * p.share
    worse = [STAGES[p.kind][s][0] for s in STAGES[p.kind] if s > stage]
    return {
        "fix": {"price": round(price), "price_moves": round(price / rates["value_per_move"]), "days": days,
                "lost_moves": round(lost_fixing), "what": PRICE_NAMES[price_key], "warranty": covered},
        "close": {"per_day": round(per_day * p.share, 1)},
        "wait": {"next": worse[0] if worse else "",
                 "per_day": round(per_day * p.share * RESTRICTION[p.kind].get(stage, 0.0), 1)},
    }


def run(asset: Any, elements: Iterable[Any], policy: str = "fix", choices: Iterable[Any] = (),
        rates: dict[str, Any] | None = None, life: int | None = None, allowance: float | None = None,
        risks: dict[str, Any] | None = None) -> dict[str, Any]:
    """The berth's design life, month by month, looked after by ``policy``.

    ``choices`` (for ``game``) are ``[issue id, "fix" | "close" | "wait", month]``: the answer to an
    issue in the month it was raised, or a later "fix" (or "close") of one left open. The run stops
    at the first issue raised without an answer and returns it as ``pending``. ``risks`` are what
    ``settings_for`` reads (the risks included, the sea's rise, the earthquakes).
    """
    policy = policy if policy in POLICIES else "fix"
    durability = marine_triton.durability(asset)
    life = int(life or durability["life"] or asset["design_life"] or 50)
    allowances = durability["allowances"]
    allowance = float(allowance or allowances.get("combi_tube") or allowances.get("casing") or 0) or 4.5
    rates = rates_for(asset["terminal_type"] or "container", rates)
    settings = settings_for(risks)
    months = life * 12
    asset_id = int(asset["id"])
    parts = parts_for(elements, allowance, life, asset_id, rates)
    by_kind = {k: [p for p in parts if p.kind == k] for k in KIND_NAME}
    one = {k: v[0] for k, v in by_kind.items() if len(v) == 1 and k in ("pipes", "drainage", "power", "lighting", "quay", "backup", "war")}
    sky = weather(asset_id, months, settings, life)
    answers: dict[tuple[str, int], str] = {}
    for c in choices or ():
        try:
            issue_id, action, month = str(c[0]), str(c[1]), int(c[2])
        except (TypeError, ValueError, IndexError):
            continue
        if action in ("fix", "close", "wait"):
            answers[(issue_id, month)] = action

    per_day, value = rates["moves_per_day"], rates["value_per_move"]
    rows: list[list[float]] = []
    states: list[list[int]] = []
    events: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    spend = handled = lost = lost_weather = lost_hazard = lost_demand = 0.0
    by_risk: dict[str, int] = {}
    condemned_at: int | None = None
    fixes = closures = covered_fixes = 0
    freeboard = settings["freeboard"]
    backup = False

    def log(m: int, kind: str, text: str, part: Part | None = None, **more: Any) -> None:
        events.append({"m": m, "kind": kind, "text": text, "part": part.id if part else None, **more})

    def count(key: str) -> None:
        by_risk[key] = by_risk.get(key, 0) + 1

    def fix(p: Part, m: int) -> float:
        nonlocal fixes, covered_fixes, freeboard, backup
        stage = p.stage if p.stage in STAGES[p.kind] else max(STAGES[p.kind])
        _, _, price_key, days, out = STAGES[p.kind][stage]
        price, covered = _price(p, price_key, rates, m, wear=_is_wear(p))
        p.repair_days = days
        p.repair_share = out * p.share
        p.occurrence += 1
        p.installed = m if p.kind not in ("wall", "deck") or stage >= 2 else p.installed
        issue_id = p.issue["id"] if p.issue else None
        if p.kind == "quay":
            freeboard += 0.6
        if p.kind == "backup":
            backup = True
        _renew(p, asset_id, life, full=p.kind in ("fender", "bollard"), stage=stage, rates=rates)
        if p.kind == "wall":
            p.protected = True
        # What is left is what the repair left: protected steel still has its loss, and that is not news.
        p.stage = p.raised = _stage(p)
        fixes += 1
        covered_fixes += covered
        paid = "Under warranty: the supplier paid" if covered else f"Paid {_money(price)} ({round(price / value):,} {units})"
        log(m, "fix", f"{p.name}: {PRICE_NAMES[price_key].split(': ')[-1].lower()}, {days} days. {paid}.", p,
            cost=round(price), issue=issue_id, warranty=covered)
        return price

    units = marine_ops.UNITS.get(asset["terminal_type"] or "container", "containers")
    targets = [p for p in parts if p.kind in ("wall", "deck")]
    for m in range(months):
        year = m / 12
        w = sky[m]
        dt = 1 / 12
        stop_days = 0.0            # days the whole berth stands (inspections, cyber, floods)
        if condemned_at is None:
            # What befell the berth this month.
            pick = lambda pool, k, salt: [pool[int(p_.draws[(2 * m + salt) % len(p_.draws)] * len(pool)) % len(pool)]  # noqa: E731
                                          for p_ in pool[:k]] if pool else []
            for key, sev in w["haz"]:
                if key == "earthquake":
                    days = 3 + 20 * sev
                    stop_days += days
                    hit = pick(targets, 1 + int(3 * sev), 0)
                    for p in hit:
                        if p.kind == "wall":
                            p.loss += sev * 0.25 * p.allowance
                        else:
                            p.age += 10 * sev
                    if sev > 0.6 and "pipes" in one:
                        one["pipes"].failed = True
                    log(m, "hazard", f"Earthquake (severity {sev:.1f}): berth closed {days:.0f} days for inspection; "
                                     f"{', '.join(sorted({p.name for p in hit}))} damaged.", None, risk="earthquake")
                    count("earthquake")
                elif key == "power_cut":
                    hours = sev * (2 if "power" in one and one["power"].stage >= 1 else 1)
                    if backup:
                        hours *= 0.2
                    stop_days += hours / 24
                    count("power_cuts")
                    if hours >= 8 and not backup:
                        g = one.get("backup")
                        if g is not None and not g.failed and g.issue is None:
                            g.failed = True
                        log(m, "hazard", f"Power cut of {hours:.0f} hours: the cranes stood.", None, risk="power_cuts")
                elif key == "vessel_strike":
                    fenders = by_kind["fender"]
                    if fenders:
                        f = fenders[int(sev * len(fenders)) % len(fenders)]
                        f.hits += 1.2
                        bay_ = min(by_kind["wall"], key=lambda b: abs((b.at[0] + b.at[1]) / 2 - f.at[0])) if by_kind["wall"] else None
                        if bay_:
                            bay_.loss += 0.2 * bay_.allowance
                        stop_days += 2
                        log(m, "hazard", f"A ship struck the quay at {f.name}: the fender torn off"
                                         f"{' and ' + bay_.name + ' damaged' if bay_ else ''}.", f, risk="vessel_strike")
                        count("vessel_strike")
                elif key == "fire":
                    decks = by_kind["deck"]
                    if decks:
                        d = decks[int(sev * len(decks)) % len(decks)]
                        d.age = max(d.age, d.steps[1] + 0.1)
                        if "lighting" in one:
                            one["lighting"].failed = True
                        stop_days += 3
                        log(m, "hazard", f"Fire on the apron at {d.name}: the concrete spalled and the lights there were lost.", d, risk="fire")
                        count("fire")
                elif key == "cyber":
                    stop_days += sev
                    log(m, "hazard", f"Cyber attack: the terminal's systems were locked for {sev:.0f} days.", None, risk="cyber")
                    count("cyber")
                elif key == "pandemic":
                    log(m, "hazard", "Pandemic: trade falls by a quarter for a year or two.", None, risk="pandemic")
                    count("pandemic")
                elif key == "war_indirect":
                    log(m, "hazard", "War in the region: shipping lines stay away and trade falls by nearly half.", None, risk="war_indirect")
                    count("war_indirect")
                elif key == "war_direct":
                    x = one.get("war")
                    if x is not None:
                        x.failed = True
                    for p in pick(targets, 3, 1):
                        if p.kind == "wall":
                            p.loss = max(p.loss, WALL_UNSAFE * p.allowance)
                        else:
                            p.age = max(p.age, p.steps[2] + 0.1)
                    log(m, "hazard", "The port was hit: cranes, the quay wall and the deck damaged.", None, risk="war_direct")
                    count("war_direct")
            # The sea over the quay: a storm's surge on the risen sea, above the freeboard.
            over = w["surge"] + w["slr"] - freeboard
            flooded = 0.0
            if w["storm"] and over > 0:
                flooded = w["storm_days"] + 1 + 4 * over
                q = one.get("quay")
                if q is not None and not q.failed and q.issue is None:
                    q.failed = True
                if "drainage" in one:
                    one["drainage"].silt += 0.5
                if "power" in one:
                    # Sea water in the ducts: power off until they are pumped out, and the cables older for it.
                    stop_days += 3
                    one["power"].age += 3
                log(m, "hazard", f"The sea came over the quay (surge {w['surge']:.1f} m on a sea {w['slr'] * 100:.0f} cm higher): "
                                 f"the apron flooded for {flooded:.0f} days and the ducts filled.", None, risk="sea_level")
                count("sea_level")
            # Blocked drains in heavy rain: the pipes full of water, the apron flooding.
            if "drainage" in one and one["drainage"].stage >= 2 and w["rain"] > 4.5:
                days = 1 + (w["rain"] - 4.5) * 0.8
                flooded += days
                if "power" in one and one["power"].draws[(2 * m) % len(one["power"].draws)] < 0.15:
                    stop_days += 1
                    one["power"].age += 1
                log(m, "hazard", f"Heavy rain on blocked drains: pipes full of water, the apron flooded {days:.0f} days.",
                    one["drainage"], risk="drainage")
                count("drainage")
            stop_days += flooded

            # The parts age.
            for p in parts:
                if p.repair_days > 0:
                    continue
                if p.kind == "fender":
                    p.age += dt
                    if w["storm"] and not p.closed and p.age > 3:
                        u = p.draws[(2 * m) % len(p.draws)]
                        if u < (0.02 if w["storm"] == 1 else 0.25):
                            p.hits += 0.15 + 0.25 * p.draws[(2 * m + 1) % len(p.draws)]
                elif p.kind == "wall":
                    speed = p.rate * (2.5 if year >= p.alwc else 1.0) * (PROTECTED if p.protected else 1.0)
                    p.loss += speed * dt
                elif p.kind == "deck":
                    p.age += dt
                elif p.kind == "bollard":
                    p.age += dt
                    if not p.failed and p.age > 15:
                        hazard = 0.0008 * (p.age - 15) / 10 * (6 if w["storm"] else 1)
                        p.failed = p.draws[(2 * m) % len(p.draws)] < hazard
                elif p.kind == "drainage":
                    p.age += dt
                    p.silt += p.rate * dt * (1.6 if w["rain"] > 4 else 1.0)
                elif p.kind in ("pipes", "power", "lighting"):
                    p.age += dt
                p.stage = _stage(p)
                if p.kind == "wall" and not p.protected and p.alwc <= year < p.alwc + dt:
                    log(m, "info", f"{p.name}: low water corrosion found, the steel is going faster than designed.", p)
                if p.stage > p.raised and p.stage in STAGES[p.kind]:
                    p.raised = p.stage
                    name, meaning, *_ = STAGES[p.kind][p.stage]
                    p.issue = {"id": f"{p.id}.{p.occurrence}.{p.stage}", "part": p.id, "name": p.name, "kind": p.kind,
                               "stage": p.stage, "state": name, "text": meaning, "m": m,
                               "options": _options(p, p.stage, rates, m)}
                    log(m, "warning" if p.stage == 1 else "critical", f"{p.name} {name}. {meaning}", p, issue=p.issue["id"])

            # The decisions this month.
            stop = False
            for p in parts:
                if p.issue is None or p.repair_days > 0:
                    continue
                raised_now = p.issue["m"] == m
                if policy == "fix":
                    action = "fix" if raised_now else None
                elif policy == "nothing":
                    action = "wait" if raised_now else None
                else:
                    action = answers.get((p.issue["id"], m))
                    if action is None and raised_now:
                        pending.append(p.issue)
                        stop = True
                        continue
                if action == "fix":
                    spend += fix(p, m)
                elif action == "close" and not p.closed:
                    p.closed = True
                    closures += 1
                    log(m, "close", f"{p.name} closed off: −{p.share * per_day:,.0f} {units} a day until it is fixed.", p,
                        issue=p.issue["id"])
                elif action == "wait" and raised_now and policy == "game":
                    log(m, "wait", f"{p.name}: left for now.", p, issue=p.issue["id"])
            if stop:
                break

            # Enough of the wall gone and the berth is taken out of service.
            unsafe = [p for p in by_kind["wall"] if p.stage >= 3 and p.repair_days <= 0]
            walls = by_kind["wall"]
            if len(unsafe) >= max(2, math.ceil(len(walls) / 3)) or any(p.loss / p.allowance >= WALL_CONDEMNED for p in walls if p.repair_days <= 0):
                condemned_at = m
                log(m, "condemned", "Berth out of service: too much of the front wall is no longer safe. "
                                    "It needs rebuilding before ships can come back.")

        # How each part stands, for the 3D view: worn 0-99, +1000 being repaired, +2000 closed off, +10000 × the
        # stage of its open issue (none once it is mended, even where the mending leaves its loss).
        states.append([min(condition(p), 99) + (1000 if p.repair_days > 0 else 0) + (2000 if p.closed else 0)
                       + (10000 * p.stage if p.issue else 0) for p in parts])

        # What the berth could do this month.
        if condemned_at is not None:
            factor = 0.0
        else:
            out = 0.0
            for p in parts:
                if p.repair_days > 0:
                    share = min(p.repair_days, DAYS_IN_MONTH) / DAYS_IN_MONTH * p.repair_share
                    p.repair_days = max(0.0, p.repair_days - DAYS_IN_MONTH)
                    out += share
                elif p.closed:
                    out += p.share
                else:
                    out += p.share * RESTRICTION[p.kind].get(p.stage, 0.0)
            factor = max(0.0, 1.0 - out)
        could = per_day * DAYS_IN_MONTH
        working = could * factor
        weather_lost = per_day * w["storm_days"] * factor
        hazard_lost = min(per_day * stop_days * factor, max(0.0, working - weather_lost))
        demand_lost = (working - weather_lost - hazard_lost) * (1 - w["demand"])
        month_handled = working - weather_lost - hazard_lost - demand_lost
        month_lost = could * (1 - factor)
        handled += month_handled
        lost += month_lost
        lost_weather += weather_lost
        lost_hazard += hazard_lost
        lost_demand += demand_lost
        if w["storm"] == 2 and condemned_at is None:
            log(m, "weather", f"Great storm: the berth stopped for {w['storm_days']:.0f} days and the fenders took a battering.")
        rows.append([m, round(factor, 4), round(month_handled), round(month_lost), round(weather_lost), round(spend),
                     round(hazard_lost), round(demand_lost)])

    done = len(rows)
    finished = not pending
    if pending:
        # The month that asked is played again once it is answered: nothing of it counts yet.
        events = [e for e in events if e["m"] < done]
        spend = rows[-1][5] if rows else 0.0
    # How long the berth will last, from the wall: when the first bay will be unsafe at today's rate.
    if condemned_at is not None:
        service_life = condemned_at / 12
    elif finished:
        ahead = []
        for p in by_kind["wall"]:
            speed = p.rate * (2.5 if life >= p.alwc else 1.0) * (PROTECTED if p.protected else 1.0)
            ahead.append(max(0.0, (WALL_UNSAFE * p.allowance - p.loss) / speed) if speed > 0 else 999.0)
        service_life = life + (min(ahead) if ahead else 999.0)
    else:
        service_life = None
    everything_lost = lost + lost_weather + lost_hazard + lost_demand
    cost_moves = everything_lost + spend / value
    return {
        "policy": policy, "policy_name": POLICIES[policy], "life": life, "months": months, "done": done,
        "finished": finished, "pending": pending,
        "start_year": int(str(asset["commissioned"])[:4]),
        "allowance": round(allowance, 2), "allowance_source": durability["source"],
        "rates": rates, "risks": settings, "units": units,
        "stage_names": {k: {s: v[0] for s, v in stages.items()} for k, stages in STAGES.items()},
        "parts": [{"id": p.id, "kind": p.kind, "name": p.name, "refs": p.refs, "at": list(p.at), "share": round(p.share, 4),
                   "expected_life": rates.get(f"life_{p.kind}"), "warranty": rates.get(f"warranty_{p.kind}"),
                   "covers": KIND_INFO.get(p.kind, (0, 0, ""))[2]}
                  for p in parts],
        "open": [p.issue for p in parts if p.issue is not None and p.repair_days <= 0 and not pending],
        "rows": rows, "states": states, "weather": sky[:done], "events": events,
        "totals": {"handled": round(handled), "lost": round(lost), "lost_weather": round(lost_weather),
                   "lost_hazard": round(lost_hazard), "lost_demand": round(lost_demand), "lost_all": round(everything_lost),
                   "spend": round(spend), "spend_moves": round(spend / value), "cost_moves": round(cost_moves),
                   "cost": round(cost_moves * value), "fixes": fixes, "closures": closures, "warranty_fixes": covered_fixes,
                   "hazards": by_risk,
                   "service_life": None if service_life is None else round(min(service_life, 150), 1),
                   "condemned_year": None if condemned_at is None else round(condemned_at / 12, 1)},
    }


def _money(usd: float) -> str:
    if usd >= 1e6:
        return f"${usd / 1e6:,.1f}M"
    if usd >= 1e3:
        return f"${usd / 1e3:,.0f}k"
    return f"${usd:,.0f}"


def compare(asset: Any, elements: list[Any], rates: dict[str, Any] | None = None,
            risks: dict[str, Any] | None = None) -> dict[str, Any]:
    """Doing nothing against fixing as you go, for the summary under the video."""
    nothing = run(asset, elements, "nothing", rates=rates, risks=risks)
    fixing = run(asset, elements, "fix", rates=rates, risks=risks)
    return {"nothing": nothing, "fix": fixing,
            "saved_moves": nothing["totals"]["cost_moves"] - fixing["totals"]["cost_moves"],
            "saved": nothing["totals"]["cost"] - fixing["totals"]["cost"]}


def yearly(result: dict[str, Any]) -> list[dict[str, float]]:
    """Cumulative cost in moves at the end of each year (every move lost, plus repairs in moves)."""
    value = result["rates"]["value_per_move"]
    out = []
    lost = 0.0
    for row in result["rows"]:
        lost += row[3] + row[4] + row[6] + row[7]
        if row[0] % 12 == 11:
            out.append({"year": (row[0] + 1) // 12, "lost": lost, "spend": row[5] / value, "cost": lost + row[5] / value,
                        "factor": row[1]})
    return out
