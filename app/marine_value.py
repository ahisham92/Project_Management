"""What MarineTwin is worth to the berth's owner, and what they stand to lose without it.

Three sums from the other pages, on the same inputs: the design life looked after as wear is found
(Lifecycle: fix as you go against doing nothing), the extreme events met knowing early (Risks), and
what the sensors that make both possible cost over the life (Sensors plan)."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable

from . import marine_life, marine_plan, marine_risk

_CACHE: dict[str, dict[str, Any]] = {}


def summary(asset: Any, elements: Iterable[Any], given: dict[str, Any] | None = None) -> dict[str, Any]:
    """The value, worked out once for each berth, model and set of inputs."""
    els = [dict(e) for e in elements]
    given = dict(given or {})
    stamp = hashlib.sha1(json.dumps([int(asset["id"]), given, [(e.get("model_ref"), e.get("kind"), e.get("x")) for e in els]],
                                    sort_keys=True, default=str).encode()).hexdigest()
    if stamp in _CACHE:
        return _CACHE[stamp]
    life = int(asset["design_life"] or 50)
    both = marine_life.compare(asset, els, given, given)
    rates = both["fix"]["rates"]
    events = [e for e in marine_risk.catalogue(asset, els, rates, given, life) if e["on"]]
    plan = marine_plan.assess(asset, els, rates, given, life, repair_saving=both["fix"]["totals"]["spend"])
    nothing = both["nothing"]["totals"]
    wear = max(0.0, both["saved"])
    risk_saving = sum(e["expected_saving"] for e in events)
    sensors = plan["cost"]["total"]
    value = wear + risk_saving
    worst = sorted(events, key=lambda e: -e["blind"]["total"])[:3]
    out = {
        "life": life, "value": round(value), "wear": round(wear), "risk_saving": round(risk_saving),
        "risk_blind": round(sum(e["expected"] for e in events)), "events": len(events),
        "sensors": round(sensors), "net": round(value - sensors), "times": round(value / sensors) if sensors else None,
        "payback": plan["payback"],
        "nothing_cost": nothing["cost"], "condemned_year": nothing["condemned_year"],
        "rebuild_cost": nothing["rebuild_cost"], "rebuild_months": nothing["rebuild_months"],
        "silt": nothing["silt"], "dredges": both["fix"]["totals"]["dredges"],
        "worst": [{"name": e["name"], "blind": e["blind"]["total"], "known": e["known"]["total"]} for e in worst],
        "units": both["fix"]["units"], "value_per_move": rates["value_per_move"],
    }
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[stamp] = out
    return out


def money(usd: float) -> str:
    if usd >= 1e9:
        return f"${usd / 1e9:,.1f}B"
    if usd >= 1e6:
        return f"${usd / 1e6:,.1f}M"
    if usd >= 1e3:
        return f"${usd / 1e3:,.0f}k"
    return f"${usd:,.0f}"
