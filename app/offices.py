"""Which office does the work.

A trade is carried by one of the firm's offices, and a deliverable is worked by
whichever offices its trades belong to. That is one column in the database and
a handful of rollups here, but it is what turns "structural is 40% done" into
"Cairo is 40% through the scope it is carrying" — which is the question asked
when two offices share a programme.

Adding a third office is one line in ``OFFICES``: everything else reads this
list rather than naming Beirut and Cairo.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

OFFICES: tuple[tuple[str, str], ...] = (
    ("beirut", "Beirut"),
    ("cairo", "Cairo"),
)

KEYS: tuple[str, ...] = tuple(key for key, _name in OFFICES)
NAMES: dict[str, str] = dict(OFFICES)

# What an office with nobody in it is called on a screen. A trade with no office
# is not an error — it is one nobody has said yet — so it reads as that.
UNSET = "Not set"


def normalise(value: Any) -> str:
    """The office key, or blank for anything that is not one.

    Accepts what somebody would type: the key, the name, either case.
    """
    wanted = str(value or "").strip().lower()
    if wanted in NAMES:
        return wanted
    for key, name in OFFICES:
        if wanted == name.lower():
            return key
    return ""


def name_of(key: Any) -> str:
    """The office as it is written on a screen."""
    return NAMES.get(normalise(key), UNSET)


def of_trade(trade: Mapping[str, Any]) -> str:
    return normalise(trade.get("office"))


def by_id(trades: Iterable[Mapping[str, Any]]) -> dict[Any, str]:
    """Each trade id's office, for looking up while walking deliverables."""
    return {t["id"]: of_trade(t) for t in trades}


def shares(task: Mapping[str, Any], offices: Mapping[Any, str]) -> dict[str, float]:
    """How much of one deliverable each office is carrying.

    A deliverable is rarely one office's: the trades split it, and the offices
    inherit that split. 60% marine out of Beirut and 40% structural out of Cairo
    is a deliverable both offices are working, in those proportions.
    """
    out: dict[str, float] = {}
    for trade_id, share in (task.get("allocations") or {}).items():
        key = offices.get(trade_id, "")
        if share:
            out[key] = out.get(key, 0.0) + float(share)
    return out


def of_task(task: Mapping[str, Any], offices: Mapping[Any, str]) -> list[str]:
    """The offices working a deliverable, the largest share first."""
    got = shares(task, offices)
    return [key for key, _share in sorted(got.items(), key=lambda kv: -kv[1]) if key]


def label(keys: Sequence[str]) -> str:
    """The offices on one deliverable, as a phrase for a row or a tooltip."""
    named = [NAMES[key] for key in keys if key in NAMES]
    if not named:
        return UNSET
    return " + ".join(named)


def rollup(trade_rows: Sequence[Mapping[str, Any]], hours_per_month: float = 0.0) -> list[dict[str, Any]]:
    """The trade figures added up per office.

    Same shape as a trade row where the figures mean the same thing, so a
    template that can draw one can draw the other.
    """
    from .calc import budget_status

    order = {key: n for n, key in enumerate(KEYS)}
    buckets: dict[str, dict[str, Any]] = {}
    for row in trade_rows:
        key = normalise(row.get("office"))
        bucket = buckets.setdefault(key, {
            "office": key,
            "name": NAMES.get(key, UNSET),
            "trades": [],
            "scope_weight_pct": 0.0,
            "earned_contribution": 0.0,
            "planned_contribution": 0.0,
            "budget_hours": 0.0,
            "spent_hours": 0.0,
            "earned_hours": 0.0,
        })
        bucket["trades"].append(row.get("name") or "")
        for field in ("scope_weight_pct", "earned_contribution", "planned_contribution",
                      "budget_hours", "spent_hours", "earned_hours"):
            bucket[field] += float(row.get(field) or 0)

    out: list[dict[str, Any]] = []
    for bucket in buckets.values():
        scope = bucket["scope_weight_pct"]
        spent = bucket["spent_hours"]
        budget = bucket["budget_hours"]
        earned_hours = bucket["earned_hours"]
        earned_of = bucket["earned_contribution"] / scope if scope > 0 else 0.0
        planned_of = bucket["planned_contribution"] / scope if scope > 0 else 0.0
        cpi = earned_hours / spent if spent > 0 else None
        eac = budget / cpi if cpi else budget
        bucket.update(
            trade_count=len(bucket["trades"]),
            earned_pct_of_office=earned_of,
            planned_pct_of_office=planned_of,
            schedule_variance_pct=earned_of - planned_of,
            budget_months=budget / hours_per_month if hours_per_month else 0.0,
            hours_used_pct=spent / budget if budget > 0 else 0.0,
            hours_over_under=spent - earned_hours,
            remaining_hours=budget - spent,
            cpi=cpi,
            eac_hours=eac,
            vac_hours=budget - eac,
            budget_status=budget_status(spent, budget, cpi),
        )
        out.append(bucket)

    # Named offices in the order they are declared, then whatever is unassigned.
    out.sort(key=lambda b: order.get(b["office"], len(order) + 1))
    return out
