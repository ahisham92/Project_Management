"""Comment response sheets: what a comment is, and when it is owed.

A client reads a submission and writes back a register of comments. Each one is
an observation against a clause or a drawing, it carries a returned code, and
somebody here owes it an answer by a date. The sheet is closed when every
comment on it is.

The whole of this module is arithmetic on dictionaries — no database, no Flask.
What it knows is:

**When a comment is late.** Not answered and past its date. A comment that has
been signed off is never late however long it took, because the argument about
lateness is only ever about work still owed.

**What a returned code means.** A is accepted, B is accepted with comments, C is
revise and resubmit, D is rejected. A and B are the codes that let a submission
stand; C and D are the ones that send it round again, and those are the ones the
programme feels — which is why they are the codes the deliverable's rework is
read from.

**Who owes it.** The client writes a discipline in their own words. Matching
that to one of the project's trades is what turns a sheet into something the
resource plan can see, so the matching is done here and kept beside what they
actually wrote.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

from .calc import parse_date, to_iso


def today() -> str:
    """Kept here rather than imported, so this module leans on the calculation
    engine and nothing else."""
    return date.today().isoformat()


def _day(value: Any) -> date | None:
    """A date, or None for anything that is not one.

    A comment register is typed by hand and arrives with blanks, "TBC" and
    whatever else in its date column. The engine reads dates from it constantly,
    so the tolerant version is the one worth having at the top of the file.
    """
    try:
        return parse_date(value)
    except (ValueError, TypeError):
        return None


def _iso(value: Any) -> str:
    made = _day(value)
    return made.isoformat() if made else ""

# What the client's code says about the submission.
CODES: dict[str, str] = {
    "A": "Accepted",
    "B": "Accepted with comments",
    "C": "Revise and resubmit",
    "D": "Rejected",
}

# The codes that send a submission round again, and so cost the programme.
SENDS_IT_BACK = frozenset({"C", "D"})

OPEN, CLOSED = "open", "closed"
SIGNOFFS: dict[str, str] = {OPEN: "Open", CLOSED: "Closed"}

# Who a person is on a sheet. A reviewer raises comments; a designer answers
# them. The PM of either side can do anything their side can.
ROLES = ("Reviewer PM", "Reviewer", "Designer PM", "Designer")
REVIEWERS = frozenset({"Reviewer PM", "Reviewer"})

DEFAULT_DUE_DAYS = 14


def normalise_code(value: Any) -> str:
    """A returned code as one of A, B, C or D, or empty for one not yet given."""
    code = str(value or "").strip().upper()[:1]
    return code if code in CODES else ""


def is_closed(comment: Mapping[str, Any]) -> bool:
    return str(comment.get("signoff") or OPEN).strip().lower() == CLOSED


def is_late(comment: Mapping[str, Any], as_at: str | None = None) -> bool:
    """Owed an answer, and the day for it has gone.

    A comment that is signed off is never late, whatever it took to close it:
    the argument about lateness is only ever about work still owed.
    """
    if is_closed(comment):
        return False
    due = _iso(comment.get("due_date"))
    return bool(due) and due < (_iso(as_at) or today())


def due_on(received: Any, days: int = DEFAULT_DUE_DAYS) -> str:
    """When a comment received on a day is owed an answer.

    Plain days rather than working ones. A client's clock does not keep our
    calendar, and a date that is later than the one on their transmittal is not
    a date anybody can defend in a meeting.
    """
    start = _day(received)
    if start is None:
        return ""
    return (start + timedelta(days=max(0, int(days or 0)))).isoformat()


def match_trade(discipline: Any, trades: Sequence[Mapping[str, Any]]) -> int | None:
    """The project's trade for a discipline the client named, if one fits.

    Matched on the name and on how a name is usually shortened — "Structural"
    against "Marine Structures" — because the client writes their own words and
    a sheet nobody can attribute is a sheet nobody acts on. An unmatched
    discipline is left unmatched rather than guessed at: wrongly owing a trade a
    comment is worse than plainly owing nobody.
    """
    wanted = " ".join(str(discipline or "").strip().lower().split())
    if not wanted:
        return None

    for trade in trades:
        if " ".join(str(trade["name"]).strip().lower().split()) == wanted:
            return int(trade["id"])

    # A word in common, where that word is not one every trade shares.
    words = {word for word in wanted.replace("/", " ").split() if len(word) > 3}
    if not words:
        return None
    hits = [t for t in trades
            if words & {w for w in str(t["name"]).lower().replace("/", " ").split() if len(w) > 3}]
    return int(hits[0]["id"]) if len(hits) == 1 else None


def tally(comments: Iterable[Mapping[str, Any]], as_at: str | None = None) -> dict[str, Any]:
    """How a sheet stands: how many, how many answered, how many overdue."""
    rows = list(comments)
    closed = [row for row in rows if is_closed(row)]
    late = [row for row in rows if is_late(row, as_at)]
    answered = [row for row in rows if str(row.get("response") or "").strip()]

    by_code: dict[str, int] = {}
    for row in rows:
        code = normalise_code(row.get("returned_code"))
        if code:
            by_code[code] = by_code.get(code, 0) + 1

    return {
        "comments": len(rows),
        "closed": len(closed),
        "open": len(rows) - len(closed),
        "late": len(late),
        "answered": len(answered),
        "unanswered": len(rows) - len(answered),
        "by_code": by_code,
        "sends_it_back": sum(n for code, n in by_code.items() if code in SENDS_IT_BACK),
        "done_pct": (len(closed) / len(rows) * 100) if rows else 0.0,
        "all_closed": bool(rows) and len(closed) == len(rows),
    }


def by_trade(comments: Iterable[Mapping[str, Any]],
             trades: Sequence[Mapping[str, Any]],
             as_at: str | None = None) -> list[dict[str, Any]]:
    """The same count per trade, so a lead can see what their own people owe."""
    names = {int(t["id"]): t["name"] for t in trades}
    held: dict[Any, list[Mapping[str, Any]]] = {}
    for row in comments:
        held.setdefault(row.get("trade_id"), []).append(row)

    out = []
    for trade_id, rows in held.items():
        counted = tally(rows, as_at)
        counted["trade_id"] = trade_id
        counted["name"] = names.get(int(trade_id), "Nobody yet") if trade_id else "Nobody yet"
        out.append(counted)
    # Most owed first, and whoever owes nothing last. The row that needs doing
    # something about is the one at the top.
    return sorted(out, key=lambda row: (-row["late"], -row["open"], row["name"]))


def worst_code(comments: Iterable[Mapping[str, Any]]) -> str:
    """The code a submission comes back on, read from its comments.

    The worst one there is: a package with a single "revise and resubmit" in it
    is being revised and resubmitted, whatever the other forty rows say.
    """
    order = ["A", "B", "C", "D"]
    found = [normalise_code(row.get("returned_code")) for row in comments]
    found = [code for code in found if code]
    return max(found, key=order.index) if found else ""


def renumber(comments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Sort order in the order given, so a sheet keeps the client's own order."""
    return [{"id": int(row["id"]), "sort_order": n}
            for n, row in enumerate(comments, start=1)]


def when(value: Any) -> str:
    """A date as the database keeps it, or empty."""
    return _iso(value)


def stamp(as_at: str | None = None) -> str:
    return _iso(as_at) or today()


def overdue_days(comment: Mapping[str, Any], as_at: str | None = None) -> int:
    """How many days past its date a comment is; 0 when it is not."""
    if not is_late(comment, as_at):
        return 0
    due = _day(comment.get("due_date"))
    now = _day(as_at) or _day(today())
    if due is None or now is None:
        return 0
    return max(0, (now - due).days)


def a_sheet_is_done(sheet: Mapping[str, Any], comments: Iterable[Mapping[str, Any]]) -> bool:
    """Whether a sheet has anything left owed on it."""
    counted = tally(comments)
    return counted["all_closed"] or bool(str(sheet.get("closed_on") or "").strip())


def default_due(sheet: Mapping[str, Any], received: Any = None) -> str:
    """The date a comment on this sheet is owed, from the sheet's own allowance."""
    days = int(sheet.get("due_days") or DEFAULT_DUE_DAYS)
    return due_on(received or sheet.get("received_on") or today(), days)


def blank_sheet(project_id: int) -> dict[str, Any]:
    """A sheet with nothing on it yet, for a client's comments still to arrive."""
    return {
        "project_id": int(project_id), "submittal_id": None, "task_id": None,
        "title": "", "revision": "", "report_no": "", "report_date": "",
        "contract_no": "", "drf_ref": "", "drf_rev": "", "drf_date": "",
        "stage": "", "engineer": "", "contractor": "",
        "due_days": DEFAULT_DUE_DAYS, "received_on": today(),
        "closed_on": "", "note": "",
    }
