"""MarineTwin's inputs: every figure the lifecycle, the extreme events and the sensors plan take,
in named sets the person can duplicate and amend.

Each field says where its typical figure comes from, so a number like the value of a container
is never a mystery. A set keeps only what differs from the typical figures, so it follows them
when they are improved; one set per asset is in use, and the pages run on it (the forms on a
page can still try a change for one run without saving it). With no set in use, the pages run on
the typical figures.
"""

from __future__ import annotations

import json
import math
from typing import Any

from . import marine_life, marine_ops, marine_plan, marine_risk

INDICATIVE = "Indicative figure for a West African container port, 2025 prices; use the project's own estimate when there is one."
PRICE_SOURCES = {
    "fender": "A 2 m cone fender with its frontal panel, supplied and fitted (Trelleborg, ShibataFenderTeam class). " + INDICATIVE,
    "bollard": "A 150 t cast bollard with its anchor bolts, fitted. " + INDICATIVE,
    "war_rebuild": "A bay of wall and deck with the cranes on it rebuilt after a direct hit; insurance seldom covers war. " + INDICATIVE,
}
LIFE_SOURCE = ("Typical design or service life: BS 6349-1-1 (maritime structures, 50 years), the maker's figure for fenders "
               "(PIANC WG 33 suggests 15–25 years), utilities by CIBSE Guide M. The warranty is the usual supplier's or "
               "contractor's defects period.")
RISK_SOURCE = "On unless switched off; what it does is described on the Lifecycle page under Risks."
EVENT_SOURCE = ("Indicative, from published port losses (e.g. Kobe 1995, Beirut 2020, Maersk NotPetya 2017, the "
                "Tohoku tsunami 2011, PIANC WG 153 on damage after earthquakes); change them for the site.")


def _berth_fields(terminal: str) -> list[dict[str, Any]]:
    unit = marine_ops.UNITS.get(terminal, "containers")
    one = unit[:-1] if unit.endswith("s") else unit
    return [
        {"key": "moves_per_day", "group": "The berth", "label": f"{unit.capitalize()} a day at full working", "unit": unit,
         "default": marine_life.MOVES_PER_DAY.get(terminal, 1000),
         "source": f"Three quay cranes at about 25 {unit} an hour each, round the clock: 3 × 25 × 24 = 1,800. "
                   "A berth with more or faster cranes handles more; for the whole quay, add its berths up."},
        {"key": "value_per_move", "group": "The berth", "label": f"Value of one {one}", "unit": "USD",
         "default": marine_life.VALUE_PER_MOVE.get(terminal, 80),
         "source": f"What the terminal earns for handling one {one}: the terminal handling charge, typically USD 90 to 150 "
                   "at West African and Gulf terminals (USD 110 is the middle). It is the terminal's income, not the cargo's value. "
                   "Every cost on the pages is also given in this unit, so one number compares them all."},
        {"key": "discount_rate", "group": "The berth", "label": "Discount rate for the return on investment", "unit": "% a year",
         "default": 8,
         "source": "The rate future savings are discounted at to compare them with money spent now; 6 to 10% is usual for port infrastructure."},
    ]


def fields(terminal: str = "container") -> list[dict[str, Any]]:
    """Every input, in the order the page shows them."""
    out = _berth_fields(terminal)
    for key, name in marine_life.PRICE_NAMES.items():
        out.append({"key": key, "group": "Repairs", "label": name, "unit": "USD", "default": marine_life.PRICES[key],
                    "source": PRICE_SOURCES.get(key, INDICATIVE)})
    for key, (life, warranty, covers) in marine_life.KIND_INFO.items():
        name = marine_life.KIND_NAME[key]
        out.append({"key": f"life_{key}", "group": "Lives and warranties", "label": f"{name}: expected life", "unit": "years",
                    "default": life, "source": LIFE_SOURCE})
        out.append({"key": f"warranty_{key}", "group": "Lives and warranties", "label": f"{name}: warranty", "unit": "years",
                    "default": warranty, "source": f"Covers {covers}. A wear repair inside it costs nothing.", "zero_ok": True})
    for key, (name, group, default, what) in marine_life.RISKS.items():
        out.append({"key": f"risk_{key}", "group": "Lifecycle risks", "label": name, "kind": "bool", "default": int(default),
                    "source": what})
    out += [
        {"key": "sea_level", "group": "Lifecycle risks", "label": "Sea-level rise over the design life", "kind": "choice",
         "choices": [(k, f"{k.capitalize()}: {v:.2f} m") for k, v in marine_life.SEA_LEVEL.items()], "default": "medium",
         "source": "IPCC AR6 projections to 2075: about 0.3 m on a middle path, 0.6 m on a high one."},
        {"key": "seismic", "group": "Lifecycle risks", "label": "Seismic zone", "kind": "choice",
         "choices": [(k, f"{k.capitalize()}: one in {round(1 / v)} years") for k, v in marine_life.SEISMIC.items()], "default": "low",
         "source": "The chance a year of an earthquake strong enough to damage the berth, from the national seismic hazard map."},
        {"key": "freeboard", "group": "Lifecycle risks", "label": "Cope above the highest storm tide today", "unit": "m",
         "default": marine_life.FREEBOARD, "source": "From the design: the cope level less the 1 in 100 year still water level."},
        {"key": "war_year", "group": "Lifecycle risks", "label": "Year of a war (blank: one is picked)", "unit": "year",
         "default": "", "source": "Only used when war is switched on."},
    ]
    for e in marine_risk.EVENTS:
        sub = e["name"]
        g = "Extreme events"
        out += [
            {"key": f"ev_{e['key']}_on", "group": g, "sub": sub, "label": "Include", "kind": "bool", "default": 1, "source": e["what"]},
            {"key": f"ev_{e['key']}_years", "group": g, "sub": sub, "label": "Happens about once in", "unit": "years",
             "default": e["years"], "source": EVENT_SOURCE},
        ]
        if e["radius"]:
            out.append({"key": f"ev_{e['key']}_radius", "group": g, "sub": sub, "label": "Area closed about the point hit",
                        "unit": "m radius", "default": e["radius"], "source": EVENT_SOURCE})
        if e["days"] or e["days_known"]:
            out += [{"key": f"ev_{e['key']}_days", "group": g, "sub": sub, "label": "Closed, not knowing early", "unit": "days",
                     "default": e["days"], "source": EVENT_SOURCE},
                    {"key": f"ev_{e['key']}_days_known", "group": g, "sub": sub, "label": "Closed, knowing early", "unit": "days",
                     "default": e["days_known"], "source": e["early"]}]
        if e["cost"] or e["cost_known"]:
            out += [{"key": f"ev_{e['key']}_cost", "group": g, "sub": sub, "label": "Repair, not knowing early", "unit": "USD",
                     "default": e["cost"], "source": EVENT_SOURCE},
                    {"key": f"ev_{e['key']}_cost_known", "group": g, "sub": sub, "label": "Repair, knowing early", "unit": "USD",
                     "default": e["cost_known"], "source": e["early"]}]
    for f in marine_plan.plan_inputs():
        out.append({**f, "group": "Sensors plan"})
    return out


GROUPS = ["The berth", "Repairs", "Lives and warranties", "Lifecycle risks", "Extreme events", "Sensors plan"]


def clean(form: dict[str, Any], terminal: str = "container") -> dict[str, str]:
    """What the form changed from the typical figures, each value checked."""
    out: dict[str, str] = {}
    for f in fields(terminal):
        raw = form.get(f["key"])
        if isinstance(raw, list):
            raw = raw[-1] if raw else None
        if raw is None:
            continue
        raw = str(raw).strip()
        kind = f.get("kind", "number")
        if kind == "bool":
            value = "1" if raw.lower() in ("1", "true", "on", "yes") else "0"
            if value != str(int(f["default"])):
                out[f["key"]] = value
        elif kind == "choice":
            if raw in dict(f["choices"]) and raw != f["default"]:
                out[f["key"]] = raw
        else:
            if raw == "":
                continue
            try:
                number = float(raw)
            except ValueError:
                continue
            if not math.isfinite(number) or number < 0 or (number == 0 and not f.get("zero_ok")):
                continue
            if f["default"] == "" or abs(number - float(f["default"])) > 1e-9:
                out[f["key"]] = f"{number:g}"
    return out


def _row(r: Any) -> dict[str, Any]:
    try:
        vals = json.loads(r["vals"] or "{}")
    except ValueError:
        vals = {}
    return {"id": r["id"], "name": r["name"], "values": vals if isinstance(vals, dict) else {}, "active": bool(r["active"]),
            "created_at": r["created_at"], "updated_at": r["updated_at"]}


def sets(conn: Any, asset_id: int) -> list[dict[str, Any]]:
    """The asset's input sets, the typical figures first (always there, never stored)."""
    rows = [_row(r) for r in conn.execute("SELECT * FROM marine_inputs WHERE asset_id = ? ORDER BY id", (asset_id,))]
    typical = {"id": 0, "name": "Typical figures", "values": {}, "active": not any(r["active"] for r in rows),
               "created_at": None, "updated_at": None}
    return [typical, *rows]


def active(conn: Any, asset_id: int) -> dict[str, str]:
    """The values of the set in use, or nothing (the typical figures)."""
    r = conn.execute("SELECT * FROM marine_inputs WHERE asset_id = ? AND active = 1 ORDER BY id LIMIT 1", (asset_id,)).fetchone()
    return _row(r)["values"] if r else {}


def active_name(conn: Any, asset_id: int) -> str:
    r = conn.execute("SELECT name FROM marine_inputs WHERE asset_id = ? AND active = 1 ORDER BY id LIMIT 1", (asset_id,)).fetchone()
    return r["name"] if r else "Typical figures"


def save(conn: Any, asset_id: int, name: str, values: dict[str, str], set_id: int | None = None,
         user_id: int | None = None, use: bool = False) -> int:
    text = json.dumps(values, sort_keys=True)
    if set_id:
        conn.execute("UPDATE marine_inputs SET name = ?, vals = ?, updated_at = datetime('now') WHERE id = ? AND asset_id = ?",
                     (name, text, set_id, asset_id))
    else:
        set_id = conn.execute("INSERT INTO marine_inputs (asset_id, name, vals, created_by) VALUES (?, ?, ?, ?)",
                              (asset_id, name, text, user_id)).lastrowid
    if use:
        make_active(conn, asset_id, set_id)
    return set_id


def make_active(conn: Any, asset_id: int, set_id: int) -> None:
    """Run the pages on this set (0: the typical figures)."""
    conn.execute("UPDATE marine_inputs SET active = (id = ?) WHERE asset_id = ?", (set_id, asset_id))


def changes(values: dict[str, str], terminal: str = "container") -> list[str]:
    """What a set changes, in words."""
    out = []
    for f in fields(terminal):
        if f["key"] in values:
            label = f"{f['sub']}: {f['label'].lower()}" if f.get("sub") else f["label"]
            value = values[f["key"]]
            if f.get("kind") == "bool":
                value = "on" if value == "1" else "off"
            elif f.get("kind") == "choice":
                value = dict(f["choices"]).get(value, value)
            else:
                value = f"{float(value):,g}" + (f" {f['unit']}" if f.get("unit") else "")
            out.append(f"{label} {value}")
    return out
