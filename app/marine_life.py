"""MarineTwin's lifecycle: the berth's whole design life played in a few minutes.

The Structure step says how the berth is now and where it is heading; this says
what that means over fifty years of work, and what it costs to look after it or
not. Month by month from the day it was commissioned:

* **the weather** — seasons, storms that stop the cranes, and now and then a big
  one that knocks the fenders about;
* **the fenders** start to wear after about fifteen years and are replaced one
  by one as each needs it;
* **the front wall** loses steel to corrosion at about the rate its allowance
  assumed, faster in a bay where accelerated low water corrosion sets in, until
  a bay is past its allowance (load restriction behind it) or unsafe (closed);
* **the deck** stays sound until chlorides reach the rebar, then cracks, spalls
  (trucks kept off) and delaminates (closed);
* **the bollards** crack now and then once they are old.

Each time something needs attention it is an **issue** with three answers:
*fix it* (pay for the repair and lose that part of the berth while it is done),
*close the area* (pay nothing now, lose its share of the berth every day), or
*wait* (it keeps working until it gets worse). Three ways to play it:

* ``nothing`` — every issue is left; failed parts restrict the berth whether
  anyone decides it or not, and when enough of the wall has gone the berth is
  taken out of service;
* ``fix`` — every issue is fixed as soon as it is found;
* ``game`` — the person decides each one (``choices``); the run stops at the
  first issue nobody has answered yet, so the page can ask.

Everything is counted in what the berth is for: **moves** (container moves, or
lifts, vehicles, tonnes for other terminals). Lost moves are the moves the berth
could not handle; a repair's price is turned into moves at the value of a move,
so one number says what each way of looking after the berth cost. Money is the
same number times the value of a move. Rates and prices are the person's to
change.

Like the other operational feeds this is **simulated**, deterministically per
asset: the same berth tells the same story every time, and a choice changes only
what comes after it. The corrosion allowance and design life come from Triton
through ``marine_triton`` (read only); everything else is a typical figure,
labelled as indicative.
"""

from __future__ import annotations

import math
import random
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
}
PRICE_NAMES = {
    "fender": "Replace a fender", "bollard": "Replace a bollard", "wall_cp": "Wall bay: cathodic protection",
    "wall_plate": "Wall bay: plate the thinned steel", "wall_rehab": "Wall bay: rebuild",
    "deck_patch": "Deck bay: patch and coat", "deck_repair": "Deck bay: concrete repair", "deck_replace": "Deck bay: new slab",
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
}
# How much of a part's share of the berth each stage takes away while it is left.
RESTRICTION = {
    "fender": {2: 0.4, 3: 0.8},
    "wall": {2: 0.5, 3: 1.0},
    "deck": {2: 0.6, 3: 1.0},
    "bollard": {3: 1.0},
}
KIND_NAME = {"fender": "Fender", "wall": "Front wall", "deck": "Deck", "bollard": "Bollard"}
POLICIES = {"nothing": "Do nothing", "fix": "Fix as you go", "game": "You decide"}


def rates_for(terminal: str, given: dict[str, Any] | None = None) -> dict[str, float]:
    """The rates a run uses: the terminal's defaults, with whatever the person changed."""
    rates: dict[str, float] = {
        "moves_per_day": float(MOVES_PER_DAY.get(terminal, 1000)),
        "value_per_move": float(VALUE_PER_MOVE.get(terminal, 80)),
        **{k: float(v) for k, v in PRICES.items()},
    }
    for key, value in (given or {}).items():
        if key not in rates:
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            rates[key] = number
    return rates


# --- the parts the run follows ------------------------------------------------------------

@dataclass
class Part:
    id: str
    kind: str                       # fender, wall, deck, bollard
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
    failed: bool = False            # bollard
    stage: int = 0
    raised: int = 0                 # the highest stage an issue has been raised for
    occurrence: int = 0             # how many times it has been renewed
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


def parts_for(elements: Iterable[Any], allowance: float, life: int, asset_id: int) -> list[Part]:
    """The parts of the berth the run follows, from its elements: fenders one by one (or in small
    groups), the front wall and the deck in bays, the bollards. A kind the model does not have is
    stood in for, evenly along the berth, so every berth has a story to tell."""
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
    parts: list[Part] = []
    for kind, found in by_kind.items():
        groups = _groups(found, MOST[kind])
        refs = lambda g: [x.get("model_ref") or x["name"] for x in g]  # noqa: E731
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

    fenders = [p for p in parts if p.kind == "fender"]
    bays = {k: [p for p in parts if p.kind == k] for k in ("wall", "deck", "bollard")}
    for p in parts:
        if p.kind == "fender":
            p.share = min(0.3, 1.2 / max(len(fenders), 8))
        elif p.kind == "bollard":
            p.share = 0.5 / max(len(bays["bollard"]), 8)
        else:
            p.share = 1 / len(bays[p.kind])
        p.allowance = allowance
        rng = random.Random(f"marinetwin-life:{asset_id}:{p.id}:draws")
        p.draws = [rng.random() for _ in range(12 * (life + 1) * 2)]
        _renew(p, asset_id, life, full=True)
    return parts


def _renew(p: Part, asset_id: int, life: int, full: bool, stage: int = 0) -> None:
    """A part as it is when new or just repaired. Its draws are fixed per part and renewal, so
    a choice changes what comes after it and nothing before."""
    rng = random.Random(f"marinetwin-life:{asset_id}:{p.id}:{p.occurrence}")
    p.stage = p.raised = 0
    p.issue = None
    p.closed = False
    if p.kind == "fender":
        p.age, p.hits = 0.0, 0.0
        p.onset = rng.uniform(14.0, 20.0)
        p.rate = rng.uniform(0.12, 0.26)
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


def _stage(p: Part) -> int:
    if p.kind == "fender":
        d = max(0.0, p.age - p.onset) * p.rate + p.hits
        return 3 if d >= 1.0 else 2 if d >= 0.75 else 1 if d >= 0.45 else 0
    if p.kind == "wall":
        u = p.loss / p.allowance
        return 3 if u >= WALL_UNSAFE else 2 if u >= 1.0 else 1 if u >= 0.5 else 0
    if p.kind == "deck":
        return sum(1 for s in p.steps if p.age >= s)
    return 3 if p.failed else 0


def condition(p: Part) -> int:
    """How worn the part is, 0 (as new) to 100 (gone), for the colours in the 3D view."""
    if p.kind == "fender":
        d = max(0.0, p.age - p.onset) * p.rate + p.hits
    elif p.kind == "wall":
        d = p.loss / p.allowance / WALL_UNSAFE
    elif p.kind == "deck":
        d = min(1.0, p.age / p.steps[2])
        d = d ** 3
    else:
        d = 1.0 if p.failed else min(0.4, p.age / 100)
    return int(round(100 * min(max(d, 0.0), 1.0)))


# --- the weather --------------------------------------------------------------------------

def weather(asset_id: int, months: int) -> list[dict[str, Any]]:
    """Each month's weather: rain, wind, the temperature, and any storm (1) or great storm (2)
    with the days it stops the berth. The wet season peaks mid-year."""
    rng = random.Random(f"marinetwin-life:{asset_id}:weather")
    out = []
    for m in range(months):
        season = math.cos(2 * math.pi * ((m % 12) - 6) / 12)          # 1 in July, -1 in January
        rain = max(0.0, 1.6 + 2.6 * season + rng.gauss(0, 1.0))
        wind = max(2.0, 6.5 + 1.8 * season + rng.gauss(0, 1.4))
        temp = 27.0 - 1.8 * season + rng.gauss(0, 0.6)
        storm, days = 0, 0.0
        roll = rng.random()
        if roll < 1 / 160:
            storm, days = 2, rng.uniform(4.0, 7.0)
            wind, rain = wind + 14, rain + 6
        elif roll < 0.10 + 0.08 * season:
            storm, days = 1, rng.uniform(0.5, 2.5)
            wind, rain = wind + 7, rain + 3
        out.append({"rain": round(rain, 1), "wind": round(wind, 1), "temp": round(temp, 1), "storm": storm,
                    "storm_days": round(days, 2)})
    return out


# --- the run ------------------------------------------------------------------------------

def _options(p: Part, stage: int, rates: dict[str, float]) -> dict[str, Any]:
    """What each answer to an issue costs, in moves (and money)."""
    name, meaning, price_key, days, out = STAGES[p.kind][stage]
    per_day = rates["moves_per_day"]
    price = rates[price_key]
    lost_fixing = per_day * days * out * p.share
    worse = [STAGES[p.kind][s][0] for s in STAGES[p.kind] if s > stage]
    return {
        "fix": {"price": round(price), "price_moves": round(price / rates["value_per_move"]), "days": days,
                "lost_moves": round(lost_fixing), "what": PRICE_NAMES[price_key]},
        "close": {"per_day": round(per_day * p.share, 1)},
        "wait": {"next": worse[0] if worse else "",
                 "per_day": round(per_day * p.share * RESTRICTION[p.kind].get(stage, 0.0), 1)},
    }


def run(asset: Any, elements: Iterable[Any], policy: str = "fix", choices: Iterable[Any] = (),
        rates: dict[str, Any] | None = None, life: int | None = None, allowance: float | None = None) -> dict[str, Any]:
    """The berth's design life, month by month, looked after by ``policy``.

    ``choices`` (for ``game``) are ``[issue id, "fix" | "close" | "wait", month]``: the answer to an
    issue in the month it was raised, or a later "fix" (or "close") of one left open. The run stops
    at the first issue raised without an answer and returns it as ``pending``.
    """
    policy = policy if policy in POLICIES else "fix"
    durability = marine_triton.durability(asset)
    life = int(life or durability["life"] or asset["design_life"] or 50)
    allowances = durability["allowances"]
    allowance = float(allowance or allowances.get("combi_tube") or allowances.get("casing") or 0) or 4.5
    rates = rates_for(asset["terminal_type"] or "container", rates)
    months = life * 12
    asset_id = int(asset["id"])
    parts = parts_for(elements, allowance, life, asset_id)
    sky = weather(asset_id, months)
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
    spend = handled = lost = lost_weather = 0.0
    condemned_at: int | None = None
    fixes = closures = 0

    def log(m: int, kind: str, text: str, part: Part | None = None, **more: Any) -> None:
        events.append({"m": m, "kind": kind, "text": text, "part": part.id if part else None, **more})

    def fix(p: Part, m: int) -> float:
        nonlocal fixes
        stage = max(p.stage, 1) if p.kind != "bollard" else 3
        _, _, price_key, days, out = STAGES[p.kind][stage]
        price = rates[price_key]
        p.repair_days = days
        p.repair_share = out * p.share
        p.occurrence += 1
        issue_id = p.issue["id"] if p.issue else None
        _renew(p, asset_id, life, full=p.kind in ("fender", "bollard"), stage=stage)
        if p.kind == "wall":
            p.protected = True
        # What is left is what the repair left: protected steel still has its loss, and that is not news.
        p.stage = p.raised = _stage(p)
        fixes += 1
        log(m, "fix", f"{p.name}: {PRICE_NAMES[price_key].split(': ')[-1].lower()}, {days} days. Paid {_money(price)} "
                      f"({round(price / value):,} moves).", p, cost=round(price), issue=issue_id)
        return price

    for m in range(months):
        year = m / 12
        w = sky[m]
        dt = 1 / 12
        if condemned_at is None:
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
                p.stage = _stage(p)
                if p.kind == "wall" and not p.protected and p.alwc <= year < p.alwc + dt:
                    log(m, "info", f"{p.name}: low water corrosion found, the steel is going faster than designed.", p)
                if p.stage > p.raised:
                    p.raised = p.stage
                    name, meaning, *_ = STAGES[p.kind][p.stage]
                    p.issue = {"id": f"{p.id}.{p.occurrence}.{p.stage}", "part": p.id, "name": p.name, "kind": p.kind,
                               "stage": p.stage, "state": name, "text": meaning, "m": m,
                               "options": _options(p, p.stage, rates)}
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
                    log(m, "close", f"{p.name} closed off: −{p.share * per_day:,.0f} moves a day until it is fixed.", p,
                        issue=p.issue["id"])
                elif action == "wait" and raised_now and policy == "game":
                    log(m, "wait", f"{p.name}: left for now.", p, issue=p.issue["id"])
            if stop:
                break

            # Enough of the wall gone and the berth is taken out of service.
            unsafe = [p for p in parts if p.kind == "wall" and p.stage >= 3 and p.repair_days <= 0]
            walls = [p for p in parts if p.kind == "wall"]
            if len(unsafe) >= max(2, math.ceil(len(walls) / 3)) or any(p.loss / p.allowance >= WALL_CONDEMNED for p in walls if p.repair_days <= 0):
                condemned_at = m
                log(m, "condemned", "Berth out of service: too much of the front wall is no longer safe. "
                                    "It needs rebuilding before ships can come back.")

        # How each part stands, for the 3D view: worn 0-100, +1000 being repaired, +2000 closed, +10000 a stage.
        states.append([condition(p) + (1000 if p.repair_days > 0 else 0) + (2000 if p.closed else 0) + 10000 * p.stage
                       for p in parts])

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
        weather_lost = per_day * w["storm_days"] * factor
        month_handled = could * factor - weather_lost
        month_lost = could * (1 - factor)
        handled += month_handled
        lost += month_lost
        lost_weather += weather_lost
        if w["storm"] == 2 and condemned_at is None:
            log(m, "weather", f"Great storm: the berth stopped for {w['storm_days']:.0f} days and the fenders took a battering.")
        rows.append([m, round(factor, 4), round(month_handled), round(month_lost), round(weather_lost), round(spend)])

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
        for p in parts:
            if p.kind != "wall":
                continue
            speed = p.rate * (2.5 if life >= p.alwc else 1.0) * (PROTECTED if p.protected else 1.0)
            ahead.append(max(0.0, (WALL_UNSAFE * p.allowance - p.loss) / speed) if speed > 0 else 999.0)
        service_life = life + (min(ahead) if ahead else 999.0)
    else:
        service_life = None
    cost_moves = lost + spend / value
    return {
        "policy": policy, "policy_name": POLICIES[policy], "life": life, "months": months, "done": done,
        "finished": finished, "pending": pending,
        "start_year": int(str(asset["commissioned"])[:4]),
        "allowance": round(allowance, 2), "allowance_source": durability["source"],
        "rates": rates, "units": marine_ops.UNITS.get(asset["terminal_type"] or "container", "moves"),
        "parts": [{"id": p.id, "kind": p.kind, "name": p.name, "refs": p.refs, "at": list(p.at), "share": round(p.share, 4)}
                  for p in parts],
        "open": [p.issue for p in parts if p.issue is not None and p.repair_days <= 0 and not pending],
        "rows": rows, "states": states, "weather": sky[:done], "events": events,
        "totals": {"handled": round(handled), "lost": round(lost), "lost_weather": round(lost_weather),
                   "spend": round(spend), "spend_moves": round(spend / value), "cost_moves": round(cost_moves),
                   "cost": round(cost_moves * value), "fixes": fixes, "closures": closures,
                   "service_life": None if service_life is None else round(min(service_life, 150), 1),
                   "condemned_year": None if condemned_at is None else round(condemned_at / 12, 1)},
    }


def _money(usd: float) -> str:
    if usd >= 1e6:
        return f"${usd / 1e6:,.1f}M"
    if usd >= 1e3:
        return f"${usd / 1e3:,.0f}k"
    return f"${usd:,.0f}"


def compare(asset: Any, elements: list[Any], rates: dict[str, Any] | None = None) -> dict[str, Any]:
    """Doing nothing against fixing as you go, for the summary under the video."""
    nothing = run(asset, elements, "nothing", rates=rates)
    fixing = run(asset, elements, "fix", rates=rates)
    return {"nothing": nothing, "fix": fixing,
            "saved_moves": nothing["totals"]["cost_moves"] - fixing["totals"]["cost_moves"],
            "saved": nothing["totals"]["cost"] - fixing["totals"]["cost"]}


def yearly(result: dict[str, Any]) -> list[dict[str, float]]:
    """Cumulative cost in moves at the end of each year (lost moves plus repairs in moves)."""
    value = result["rates"]["value_per_move"]
    out = []
    lost = 0.0
    for row in result["rows"]:
        lost += row[3]
        if row[0] % 12 == 11:
            out.append({"year": (row[0] + 1) // 12, "lost": lost, "spend": row[5] / value, "cost": lost + row[5] / value,
                        "factor": row[1]})
    return out
