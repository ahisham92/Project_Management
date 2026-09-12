"""The register of everything issued, and what each piece of it costs.

A deliverable is a line on a programme. It is not a thing anybody hands over.
What gets handed over is a report, a set of drawings, a specification, a bill of
quantities — and those are what carry numbers, go out on transmittals, and come
back with comments. The register is that list, and this module is the arithmetic
underneath it.

**What a deliverable submits, and in what proportion.** A design package is not
one document. It is typically a report, a specification and a set of drawings,
and they are not worth the same. Two packages on the same programme are rarely
the same shape either: a design basis is one report, a general arrangement
package is forty drawings and nothing else. So the mix is set once for the
project and any deliverable can say something different.

There are two ways to say it, and the better one is counting. **Say how many** —
six drawings, one report — and the weights work themselves out from what one of
each costs: a drawing is 35 hours, a report is 120, and Setup holds those
figures. Six drawings and a report is 210 against 120, so 64% drawings and 36%
report, and nobody had to guess at a percentage. Leave the count blank and type
a percentage instead, and the expected number is worked back the other way:
35% of a 1,000-hour line is 350 hours of drawings, which is ten of them.

Either way the register then has something to be measured against. Ten drawings
expected at 35 hours each, seven issued, 290 hours booked — that is 41 hours a
drawing against a standard of 35, and it is the earliest honest read on whether
this package is going to land.

**A kind's share divides across its documents.** One design basis is one report
and all of it; a general arrangement package is forty drawings, and the share
splits between them. By default evenly, because forty drawings of unknown
difficulty are best assumed equal; a drawing that is plainly bigger than the
others carries a weight and takes more.

**A document's share divides across the trades issuing it.** This is the part a
programme cannot tell you. A design basis report is written by every discipline
at once — one document, four trades — while a dredging drawing is Marine's
alone. The deliverable's own trade split is the sensible default, and a document
that is not like its deliverable says so.

Multiply those three and every drawing in the register has hours against it.
Book time to the document rather than the line and the deliverable's actual cost
stops being an estimate.

**Numbers are produced, not typed.** A convention such as
``{project}-{trade}-{kind}-{seq:4}`` is set in Setup, and the register fills it
in. The sequence counts what already exists under the same prefix, so a
convention that groups by trade numbers each trade from one without anybody
maintaining a counter, and changing the convention does not renumber history —
what went out went out under the number it went out under.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

# What an engineering office issues, before anybody edits the list. `code` is
# what goes in a document number; `share` is the default mix, which is the
# shape of a design package rather than a rule — a deliverable that is all
# drawings says so and the rest of them stay where they are.
DEFAULT_KINDS: tuple[dict[str, Any], ...] = (
    {"key": "report", "name": "Report", "code": "RPT", "share": 35.0, "many": 0,
     "hours": 120.0},
    {"key": "drawings", "name": "Drawings", "code": "DWG", "share": 60.0, "many": 1,
     "hours": 35.0},
    {"key": "specifications", "name": "Specifications", "code": "SPC", "share": 5.0, "many": 0,
     "hours": 20.0},
    {"key": "boq", "name": "Bill of quantities", "code": "BOQ", "share": 0.0, "many": 0,
     "hours": 40.0},
    {"key": "mom", "name": "Method of measurement", "code": "MOM", "share": 0.0, "many": 0,
     "hours": 24.0},
    {"key": "calculations", "name": "Calculations", "code": "CAL", "share": 0.0, "many": 1,
     "hours": 30.0},
    {"key": "document", "name": "Document", "code": "DOC", "share": 0.0, "many": 0,
     "hours": 16.0},
)

# Where a document is in its life. Planned and issued are the two that matter to
# the register; the rest are what the client did with it, which the deliverable's
# own workflow already tracks in more detail.
STATUSES: tuple[tuple[str, str], ...] = (
    ("planned", "Planned"),
    ("drafting", "Drafting"),
    ("checking", "Internal check"),
    ("issued", "Issued"),
    ("code_a", "Code A"),
    ("code_b", "Code B"),
    ("code_c", "Code C"),
    ("superseded", "Superseded"),
)
STATUS_NAMES = dict(STATUSES)

# A document is out of the door from here on: it has a number somebody else is
# holding, so its number is not ours to change any more.
ISSUED_STATES = frozenset({"issued", "code_a", "code_b", "code_c", "superseded"})

DEFAULT_FORMAT = "{project}-{trade}-{kind}-{seq:4}"


def _num(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


# --- the numbering convention ------------------------------------------------

# Every token a convention may use, and one line saying what fills it in. The
# list is shown on Setup beside the box, because a format language nobody can
# see the vocabulary of is a format language nobody will change.
TOKENS: tuple[tuple[str, str], ...] = (
    ("project", "The project code, as it is on Setup"),
    ("client", "The client's name, letters and digits only"),
    ("section", "The section's code — the scope heading a deliverable sits under"),
    ("wbs", "The deliverable's WBS number, with the dots taken out"),
    ("trade", "The issuing trade's key. Blank on a document several trades share"),
    ("kind", "The kind's code — RPT, DWG, SPC and so on"),
    ("year", "The year the document is planned or issued, as four digits"),
    ("yy", "The same year, as two digits"),
    ("rev", "The revision, as a number"),
    ("seq", "A running number. Write {seq:4} for 0001, {seq:2} for 01"),
)
TOKEN_NAMES = frozenset(name for name, _ in TOKENS)

_TOKEN = re.compile(r"\{(\w+)(?::(\d+))?\}")


def check_format(text: str) -> str:
    """Empty if the convention can be used, or what is wrong with it.

    A convention without ``{seq}`` would give every document the same number,
    which is worse than having no convention at all.
    """
    text = str(text or "").strip()
    if not text:
        return "Give a numbering convention, or the register cannot produce a number"
    unknown = [name for name, _width in _TOKEN.findall(text) if name not in TOKEN_NAMES]
    if unknown:
        known = ", ".join(sorted(TOKEN_NAMES))
        return f"{', '.join('{' + u + '}' for u in unknown)} is not a token. Use: {known}"
    if "{seq" not in text:
        return "Leave {seq} in, or every document would be given the same number"
    return ""


def _clean(value: Any, keep_dots: bool = False) -> str:
    """A token's value, with anything that has no business in a filename gone."""
    allowed = r"[^A-Za-z0-9.\-]" if keep_dots else r"[^A-Za-z0-9\-]"
    return re.sub(allowed, "", str(value or "")).upper()


def parts_for(project: Mapping[str, Any], task: Mapping[str, Any] | None = None,
              kind: Mapping[str, Any] | None = None,
              trade: Mapping[str, Any] | None = None,
              section: Mapping[str, Any] | None = None,
              year: Any = "", revision: Any = 0) -> dict[str, str]:
    """Everything a convention can ask for, as strings ready to drop in."""
    year = str(year or "")[:4]
    return {
        "project": _clean((project or {}).get("code")),
        "client": _clean((project or {}).get("client")),
        "section": _clean((section or {}).get("code")),
        "wbs": _clean((task or {}).get("wbs")).replace(".", ""),
        "trade": _clean((trade or {}).get("key")),
        "kind": _clean((kind or {}).get("code")),
        "year": year,
        "yy": year[-2:],
        "rev": str(int(_num(revision))),
    }


def fill(text: str, parts: Mapping[str, str], sequence: int | None = None) -> str:
    """The convention with its tokens filled in.

    `sequence` of None leaves ``{seq}`` where it is, which is how the prefix a
    number belongs to is worked out: two documents share a prefix when
    everything except the running number is the same.
    """
    def swap(found: re.Match) -> str:
        name, width = found.group(1), found.group(2)
        if name == "seq":
            if sequence is None:
                return "{seq}"
            return str(int(sequence)).zfill(int(width or 1))
        return parts.get(name, "")

    made = _TOKEN.sub(swap, str(text or ""))
    # A token that filled in blank — a document no single trade owns, a
    # deliverable with no section — leaves a double separator behind. Tidy it,
    # rather than handing somebody L26100--RPT-0001.
    made = re.sub(r"([-_/.])\1+", r"\1", made)
    return made.strip("-_/. ")


def number_for(project: Mapping[str, Any], taken: Iterable[str], **parts_of: Any) -> tuple[str, str]:
    """The next number under this convention, and the prefix it counts within.

    `taken` is every number already in the register. The next one is the lowest
    that nothing else is using under the same prefix, so a deleted document's
    number is reused rather than leaving a hole, and a number typed in by hand
    is never trodden on.
    """
    text = str((project or {}).get("document_format") or DEFAULT_FORMAT)
    parts = parts_for(project, **parts_of)
    prefix = fill(text, parts, None)

    # Read the numbers already issued under this prefix straight off the strings:
    # the register is the counter, so a convention can change without a migration.
    before, _, after = prefix.partition("{seq}")
    used: set[int] = set()
    for number in taken:
        number = str(number or "")
        if not number.startswith(before) or not number.endswith(after):
            continue
        middle = number[len(before):len(number) - len(after) or None]
        if middle.isdigit():
            used.add(int(middle))

    nextup = 1
    while nextup in used:
        nextup += 1
    return fill(text, parts, nextup), prefix


# --- what a deliverable submits, and in what proportion ----------------------

def mix_for(task_id: int, per_task: Mapping[int, Sequence[Mapping[str, Any]]],
            default: Sequence[Mapping[str, Any]],
            standard: Mapping[int, float] | None = None) -> list[dict[str, Any]]:
    """The kinds one deliverable submits, normalised to total 100%.

    Its own mix if it has been given one, the project's otherwise — so a project
    where every package is the same is set up once, and the one deliverable that
    is only a bill of quantities says so on its own row.

    Where a count has been given, the weight is worked out from it rather than
    typed: six drawings at 35 hours against one report at 120 is 64% and 36%,
    and that is a better answer than two numbers somebody guessed at. A kind
    with a count but no standard cost cannot be weighed that way, so it falls
    back to whatever percentage it was given.

    Counting is all-or-nothing for a package. Once anything in it has been
    counted the package is what was counted, and a kind left at nothing is not
    part of it — there is no honest way to weigh six drawings against "35% of
    something", and the form shows the uncounted weights falling to zero as it
    is typed rather than springing it on anybody at save time.
    """
    standard = {int(k): _num(v) for k, v in (standard or {}).items()}
    rows = list(per_task.get(int(task_id)) or ()) or list(default or ())

    counted = [row for row in rows
               if _num(row.get("quantity")) > 0 and standard.get(int(row["kind_id"]), 0) > 0]
    if counted:
        # Counting wins: it is the thing somebody actually knows about a package.
        weighed = {int(row["kind_id"]): _num(row["quantity"]) * standard[int(row["kind_id"])]
                   for row in counted}
        whole = sum(weighed.values()) or 1.0
        from_count = {int(row["kind_id"]) for row in counted}
        return [{"kind_id": kind_id, "percent": hours / whole * 100,
                 "quantity": next(_num(r["quantity"]) for r in counted
                                  if int(r["kind_id"]) == kind_id),
                 "from_count": kind_id in from_count}
                for kind_id, hours in weighed.items()]

    whole = sum(_num(row.get("percent")) for row in rows)
    if whole <= 0:
        return []
    return [{"kind_id": int(row["kind_id"]), "percent": _num(row["percent"]) / whole * 100,
             "quantity": _num(row.get("quantity")), "from_count": False}
            for row in rows if _num(row.get("percent")) > 0]


def costing(tasks: Sequence[Mapping[str, Any]], submittals: Sequence[Mapping[str, Any]],
            mixes: Mapping[int, Sequence[Mapping[str, Any]]],
            default_mix: Sequence[Mapping[str, Any]],
            planned_by_task: Mapping[int, Mapping[int, float]],
            booked: Mapping[int, Mapping[int, float]] | None = None,
            standard: Mapping[int, float] | None = None,
            ) -> dict[str, Any]:
    """Hours down to each document, and back up to each deliverable.

    `planned_by_task` is what the resource plan allows a deliverable, trade by
    trade — the register spends that, it does not invent more. `booked` is what
    was actually charged to each document, so planned and actual sit beside each
    other at every level.

    `standard` is what one of each kind costs — a drawing is 35 hours — which
    turns a share of a deliverable into a number of drawings to expect, and
    gives the hours actually booked to the ones issued something to be measured
    against.

    A deliverable with no documents in the register yet is still returned, with
    its hours unspent: "nothing has been raised for this" is the most useful
    thing the register can tell somebody.
    """
    booked = booked or {}
    standard = {int(k): _num(v) for k, v in (standard or {}).items()}
    by_task: dict[int, list[dict[str, Any]]] = {}
    for row in submittals:
        by_task.setdefault(int(row["task_id"]), []).append(dict(row))

    documents: list[dict[str, Any]] = []
    lines: list[dict[str, Any]] = []
    for task in tasks:
        task_id = int(task["id"])
        allowed = dict(planned_by_task.get(task_id) or {})
        total = sum(allowed.values())
        shape = mix_for(task_id, mixes, default_mix, standard)
        mix = {row["kind_id"]: row["percent"] for row in shape}
        counts = {row["kind_id"]: row["quantity"] for row in shape}
        mine = by_task.get(task_id) or []

        # Each kind's share of the line, then each document's share of its kind.
        weights: dict[int, float] = {}
        for row in mine:
            weights[int(row["kind_id"])] = weights.get(int(row["kind_id"]), 0.0) + max(
                _num(row.get("weight"), 1.0), 0.0)

        raised: list[dict[str, Any]] = []
        for row in mine:
            kind_id = int(row["kind_id"])
            share = mix.get(kind_id, 0.0) / 100
            whole = weights.get(kind_id) or 0.0
            weight = max(_num(row.get("weight"), 1.0), 0.0)
            hours = total * share * (weight / whole if whole > 0 else 0.0)

            # Who is doing it. The document's own split where it has one, the
            # deliverable's where it has not — a report every discipline writes
            # is the deliverable's split by definition.
            shares = {int(t["trade_id"]): _num(t.get("share"))
                      for t in (row.get("trades") or ()) if _num(t.get("share")) > 0}
            if not shares:
                shares = {trade_id: (value / total * 100 if total > 0 else 0.0)
                          for trade_id, value in allowed.items() if value > 0}
            spread = sum(shares.values()) or 1.0

            spent = dict(booked.get(int(row["id"])) or {})
            made = dict(row)
            made.update(
                hours=hours,
                kind_share=mix.get(kind_id, 0.0),
                weight_share=(weight / whole * 100) if whole > 0 else 0.0,
                by_trade={trade_id: hours * value / spread for trade_id, value in shares.items()},
                shares={trade_id: value / spread * 100 for trade_id, value in shares.items()},
                spent_hours=sum(spent.values()),
                spent_by_trade=spent,
            )
            raised.append(made)
            documents.append(made)

        # A kind the mix asks for with nothing raised against it is the gap
        # worth seeing: 60% of the line is drawings and there are no drawings.
        missing = [kind_id for kind_id, percent in mix.items()
                   if percent > 0 and kind_id not in weights]
        spent_here = sum(row["spent_hours"] for row in raised)
        lines.append({
            "task_id": task_id, "wbs": task.get("wbs") or "", "name": task.get("name") or "",
            "planned_hours": total,
            "documents": len(raised),
            "raised_hours": sum(row["hours"] for row in raised),
            "spent_hours": spent_here,
            "left_hours": total - spent_here,
            "used_pct": (spent_here / total) if total > 0 else 0.0,
            "mix": [dict(row) for row in shape],
            "missing_kinds": missing,
            "by_kind": _by_kind(raised, mix, total, counts, standard),
        })

    return {
        "documents": documents,
        "lines": lines,
        "planned_hours": sum(line["planned_hours"] for line in lines),
        "raised_hours": sum(line["raised_hours"] for line in lines),
        "spent_hours": sum(line["spent_hours"] for line in lines),
        "unraised": [line for line in lines if line["missing_kinds"] or not line["documents"]],
        "expected": _expected(lines, standard),
    }


def _by_kind(raised: Sequence[Mapping[str, Any]], mix: Mapping[int, float], total: float,
             counts: Mapping[int, float] | None = None,
             standard: Mapping[int, float] | None = None) -> list[dict[str, Any]]:
    """One deliverable's documents gathered under the kind they belong to.

    Alongside what each kind is worth, how many of it to expect and how many
    are really there. Where a count was given that is the number expected;
    where it was not, the hours divided by what one costs says the same thing
    in the other direction. Ten drawings expected, seven issued, 290 hours
    charged to them: 41 hours a drawing against a standard of 35.
    """
    counts = {int(k): _num(v) for k, v in (counts or {}).items()}
    standard = {int(k): _num(v) for k, v in (standard or {}).items()}

    def blank(kind_id: int, percent: float) -> dict[str, Any]:
        hours = total * percent / 100
        each = standard.get(kind_id, 0.0)
        expected = counts.get(kind_id) or (hours / each if each > 0 else 0.0)
        return {"kind_id": kind_id, "percent": percent, "hours": hours,
                "documents": 0, "spent_hours": 0.0, "issued": 0,
                "standard_hours": each, "expected": expected,
                "hours_each_expected": each or (hours / expected if expected > 0 else 0.0),
                "hours_each_actual": 0.0, "over_each": 0.0}

    out: dict[int, dict[str, Any]] = {kind_id: blank(kind_id, percent)
                                      for kind_id, percent in mix.items()}
    for row in raised:
        kind_id = int(row["kind_id"])
        cell = out.setdefault(kind_id, blank(kind_id, 0.0))
        cell["documents"] += 1
        cell["spent_hours"] += row["spent_hours"]
        if str(row.get("status") or "") in ISSUED_STATES:
            cell["issued"] += 1

    for cell in out.values():
        # Measured on what has gone out, because a drawing still being drawn
        # has not finished costing what it is going to cost.
        done = cell["issued"] or cell["documents"]
        cell["hours_each_actual"] = cell["spent_hours"] / done if done > 0 else 0.0
        cell["over_each"] = cell["hours_each_actual"] - cell["hours_each_expected"]
    return sorted(out.values(), key=lambda row: -row["percent"])


def _expected(lines: Sequence[Mapping[str, Any]],
              standard: Mapping[int, float]) -> list[dict[str, Any]]:
    """The same comparison for the whole project, one row a kind.

    What the setup sheet says to expect against what the register holds — the
    answer to "we budgeted for forty drawings, where are we?".
    """
    out: dict[int, dict[str, Any]] = {}
    for line in lines:
        for cell in line.get("by_kind") or ():
            kind_id = int(cell["kind_id"])
            row = out.setdefault(kind_id, {
                "kind_id": kind_id, "standard_hours": _num(standard.get(kind_id)),
                "expected": 0.0, "documents": 0, "issued": 0,
                "hours": 0.0, "spent_hours": 0.0,
            })
            row["expected"] += cell["expected"]
            row["documents"] += cell["documents"]
            row["issued"] += cell["issued"]
            row["hours"] += cell["hours"]
            row["spent_hours"] += cell["spent_hours"]

    for row in out.values():
        done = row["issued"] or row["documents"]
        row["hours_each_actual"] = row["spent_hours"] / done if done > 0 else 0.0
        row["hours_each_expected"] = (
            row["standard_hours"]
            or (row["hours"] / row["expected"] if row["expected"] > 0 else 0.0))
        row["over_each"] = row["hours_each_actual"] - row["hours_each_expected"]
        # What is still to exist at all, not what is still to go out: a drawing
        # raised but not issued is already in the register.
        row["left"] = max(0.0, row["expected"] - row["documents"])
    return sorted(out.values(), key=lambda row: -row["expected"])


def to_a_hundred(supplied: Mapping[Any, float]) -> dict[Any, float]:
    """Shares scaled so they total 100, keeping their proportions.

    Scaled rather than nudged. Somebody who types 70, 60 and 5 has said the
    report is worth a little more than the drawings and the specification is
    worth almost nothing — putting the whole 35-point drift on the largest of
    them would throw away exactly what they said. Scaling keeps it, and a split
    held in thirds that reads as 99 comes back as 100 either way.

    The rounding is then swept into the largest share, because that is where a
    hundredth of a percent is least visible.
    """
    given = {key: _num(value) for key, value in supplied.items() if _num(value) > 0}
    whole = sum(given.values())
    if whole <= 0:
        return {}
    scaled = {key: round(value / whole * 100, 2) for key, value in given.items()}
    drift = round(100 - sum(scaled.values()), 2)
    if drift:
        biggest = max(scaled, key=lambda key: scaled[key])
        scaled[biggest] = round(scaled[biggest] + drift, 2)
    return scaled


# --- reading the register in whatever order somebody wants --------------------

COLUMNS: dict[str, tuple[str, bool]] = {
    "number": ("Number", False),
    "title": ("Title", False),
    "wbs": ("WBS", False),
    "kind": ("Kind", False),
    "status": ("Status", False),
    "planned": ("Planned", False),
    "issued": ("Issued", False),
    "hours": ("Hours", True),
    "spent": ("Booked", True),
}


def sortable_columns(trades: Sequence[Mapping[str, Any]]) -> dict[str, tuple[str, bool]]:
    """Every column the register sorts on, a project's own trades included."""
    out = dict(COLUMNS)
    for trade in trades:
        out[f"trade:{int(trade['id'])}"] = (str(trade.get("name") or ""), True)
    return out


def order_for(column: str | None, direction: str | None,
              columns: Mapping[str, tuple[str, bool]], fallback: str) -> tuple[str, str]:
    column = column if column in columns else fallback
    if direction not in ("asc", "desc"):
        direction = "desc" if columns[column][1] else "asc"
    return column, direction


def sort_documents(rows: Sequence[Mapping[str, Any]], column: str,
                   direction: str = "asc") -> list[dict[str, Any]]:
    """The register in one column's order, the number breaking every tie."""
    from .sorting import _wbs_key

    if str(column).startswith("trade:"):
        try:
            trade_id = int(str(column).split(":", 1)[1])
        except (TypeError, ValueError):
            trade_id = 0
        key = lambda row: _num((row.get("by_trade") or {}).get(trade_id))   # noqa: E731
    else:
        order = {key: n for n, (key, _name) in enumerate(STATUSES)}
        keys = {
            "number": lambda row: _wbs_key(row.get("number")),
            "title": lambda row: str(row.get("title") or "").lower(),
            "wbs": lambda row: _wbs_key(row.get("task_wbs")),
            "kind": lambda row: str(row.get("kind_name") or "").lower(),
            "status": lambda row: order.get(str(row.get("status")), 99),
            "planned": lambda row: str(row.get("planned_date") or ""),
            "issued": lambda row: str(row.get("issued_date") or ""),
            "hours": lambda row: _num(row.get("hours")),
            "spent": lambda row: _num(row.get("spent_hours")),
        }
        key = keys.get(column, keys["number"])

    ordered = sorted(rows, key=lambda row: (key(row), _wbs_key(row.get("number"))))
    return list(reversed(ordered)) if direction == "desc" else list(ordered)

