"""The trades THEMIS writes specifications for.

Each account has a trade (a structural engineer, a geotechnical engineer).
A project is given the trades it needs, and each trade writes its own
specification of it: one specification per trade, joined as one project by
``spec_sets.trade_group`` (the id of the first of them) and shown as tabs.
Each master section belongs to one trade's library, and the brief asks each
trade its own questions beside the ones every trade shares (the standards,
the design life, the exposure, what the project builds). Marine works are not
a trade: they are a scope within each one, as they are in structures.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .db import execute, query, query_one

STRUCTURES = "structures"
GEOTECHNICAL = "geotechnical"
# (code, name, what it writes, short mark used on chips and in the MTD's file names)
TRADES = (
    (STRUCTURES, "Structures", "Concrete, reinforcement, steel, precast, waterproofing and marine furniture.", "ST"),
    (GEOTECHNICAL, "Geotechnical", "Ground investigation, earthworks, ground improvement, piles, retaining "
                                   "walls, pavements, tunnels, dams and marine works.", "GE"),
)
CODES = tuple(t[0] for t in TRADES)
DEFAULT = STRUCTURES

# The brief questions every trade answers: what the project is, and what it is
# written to. An option with no trade of its own is shared when it is one of
# these, and is structures' otherwise (the brief written before trades).
SHARED_KEYS = frozenset({"standards", "english", "stage", "contract", "design_life", "seismic",
                         "leed", "conformity", "structures", "exposure", "climate"})


def clean(code: str | None, default: str = DEFAULT) -> str:
    code = (code or "").strip().lower()
    return code if code in CODES else default


def name(code: str | None) -> str:
    return next((n for c, n, _w, _m in TRADES if c == (code or "").strip().lower()), "")


def mark(code: str | None) -> str:
    return next((m for c, _n, _w, m in TRADES if c == (code or "").strip().lower()), "")


def choices() -> list[dict]:
    return [{"code": c, "name": n, "note": w, "mark": m} for c, n, w, m in TRADES]


def from_filename(filename: str) -> str:
    """The trade the MTD's file name gives: "STD15A_SPC_316323_GE_..." is
    geotechnical, "..._MR_..." (marine works issued with the ground works) too,
    "..._ST_..." structures; '' when it says none."""
    import re

    m = re.search(r"_(ST|GE|MR)_", filename or "", re.I)
    if not m:
        return ""
    return STRUCTURES if m.group(1).upper() == "ST" else GEOTECHNICAL


# --- accounts -------------------------------------------------------------------

def of_user(user: Mapping[str, Any] | None) -> str:
    """The account's trade, '' when nobody has said."""
    if user is None:
        return ""
    try:
        return clean(user["themis_trade"], "")
    except (KeyError, IndexError):
        return ""


def users_of(trade: str) -> list[dict]:
    """The accounts that may open THEMIS whose trade is this one."""
    from .specs_review import candidates

    return [u for u in candidates() if clean(u.get("themis_trade"), "") == trade]


def set_user_trade(user_id: int, trade: str | None) -> None:
    execute("UPDATE users SET themis_trade = ? WHERE id = ?", (clean(trade, ""), user_id))


# --- the brief ------------------------------------------------------------------

def option_trade(o: Mapping[str, Any]) -> str:
    """Which trade's brief asks this question: '' for every trade's."""
    own = (o.get("trade") or "").strip().lower()
    if own in CODES:
        return own
    if own == "all" or o.get("key") in SHARED_KEYS:
        return ""
    return STRUCTURES


def options_for(options: Iterable[Mapping[str, Any]], trade: str | None) -> list[dict]:
    """The brief questions one trade answers: its own and the shared ones."""
    trade = clean(trade)
    return [dict(o) for o in options if option_trade(o) in ("", trade)]


# --- a project's trades ---------------------------------------------------------

def group_of(row: Mapping[str, Any]) -> int:
    return int(row.get("trade_group") or row["id"])


def siblings(row: Mapping[str, Any]) -> list[dict]:
    """Every specification of this project, one per trade (this one too), in
    the order of the trades."""
    group = group_of(row)
    # Named by who leads it: its lead on the team, else whoever started it.
    rows = [dict(r) for r in query(
        "SELECT s.*, COALESCE((SELECT u2.name FROM spec_set_members m JOIN users u2 ON u2.id = m.user_id "
        "WHERE m.set_id = s.id AND m.role = 'lead' ORDER BY m.rowid LIMIT 1), u.name) AS owner "
        "FROM spec_sets s LEFT JOIN users u ON u.id = s.created_by "
        "WHERE s.id = ? OR s.trade_group = ? OR s.id = ? ORDER BY s.id", (row["id"], group, group))]
    order = {c: i for i, c in enumerate(CODES)}
    return sorted(rows, key=lambda r: (order.get(clean(r.get("trade")), 99), r["id"]))


def tabs(row: Mapping[str, Any]) -> list[dict]:
    """The project's trade tabs: each trade it has, then the ones it could add."""
    have = {clean(s.get("trade")): s for s in siblings(row)}
    out = []
    for c, n, _w, m in TRADES:
        s = have.get(c)
        out.append({"code": c, "name": n, "mark": m, "set_id": s["id"] if s else None,
                    "here": bool(s) and s["id"] == row["id"], "owner": (s or {}).get("owner") or ""})
    return out


def sibling(row: Mapping[str, Any], trade: str) -> dict | None:
    return next((s for s in siblings(row) if clean(s.get("trade")) == trade), None)


def join(set_id: int, group: int) -> None:
    execute("UPDATE spec_sets SET trade_group = ? WHERE id = ?", (group, set_id))


def add_trade(row: Mapping[str, Any], trade: str, lead_id: int | None = None) -> int:
    """Another trade's specification of this project: the project's name,
    code, client, place, kind and page header, and the shared brief answers
    so far; its own sections follow from its own brief."""
    import json

    from . import specs, specs_store as store
    from .specs_review import save_team

    trade = clean(trade)
    if sibling(row, trade):
        raise specs.SpecError(f"This project already has a {name(trade).lower()} specification.")
    fields = {k: row.get(k) or "" for k in store.SET_FIELDS}
    fields.update({"package": "", "city": row.get("city") or "", "country": row.get("country") or "",
                   "family": row["family"], "trade": trade})
    if row.get("need_signoff"):
        fields["need_signoff"] = "1"
    set_id = store.create_set(fields)
    group = group_of(row)
    join(row["id"], group)
    join(set_id, group)
    # What the project is, decided once: the shared answers come across.
    shared = {k: v for k, v in json.loads(row.get("options") or "{}").items() if k in SHARED_KEYS}
    if shared:
        new = store.spec_set(set_id)
        mine = json.loads(new["options"] or "{}")
        mine.update(shared)
        execute("UPDATE spec_sets SET options = ? WHERE id = ?", (json.dumps(mine, ensure_ascii=False), set_id))
    if lead_id:
        save_team(set_id, {int(lead_id): "lead"})
    return set_id


def project_trades(rows: Iterable[Mapping[str, Any]]) -> dict[int, list[dict]]:
    """For a list of specifications, every trade each one's project has, by
    specification id: [{code, name, mark, set_id}]."""
    rows = list(rows)
    groups: dict[int, list[Mapping[str, Any]]] = {}
    for r in rows:
        groups.setdefault(group_of(r), []).append(r)
    return {r["id"]: [{"code": clean(s.get("trade")), "name": name(clean(s.get("trade"))),
                       "mark": mark(clean(s.get("trade"))), "set_id": s["id"]}
                      for s in sorted(groups[group_of(r)], key=lambda x: CODES.index(clean(x.get("trade"))))]
            for r in rows}


def lead_choices() -> dict[str, list[dict]]:
    """For the new-project page: who could lead each trade's specification."""
    return {c: [{"id": u["id"], "name": u["name"] or u["email"]} for u in users_of(c)] for c in CODES}


def user_name(user_id: int) -> str:
    row = query_one("SELECT name, email FROM users WHERE id = ?", (user_id,))
    return (row["name"] or row["email"]) if row else ""
