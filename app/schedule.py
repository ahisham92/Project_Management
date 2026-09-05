"""The plan: durations, dependencies, float and the critical path.

Pure functions over plain dictionaries — no database, no request — so the
arithmetic that decides what is critical and what may slip is testable on its
own. Everything works in calendar days, as the rest of the app does: a
deliverable that starts on Monday with a duration of 5 days finishes on Friday.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

from .dates import to_display

# How the dates on a line are entered. By duration, the finish follows the
# start; by dates, the duration follows the two.
MODES: tuple[tuple[str, str], ...] = (
    ("duration", "Start + duration"),
    ("dates", "Start and finish dates"),
)
MODE_KEYS = tuple(key for key, _ in MODES)
DEFAULT_MODE = "duration"

# How one deliverable waits for another. In each case the first named end is
# the predecessor's and the second is the successor's.
#
#   FS  finish to start   it cannot start until the other has finished
#   SS  start to start    it can start once the other has started
#   FF  finish to finish  it cannot finish until the other has finished
#   SF  start to finish   it cannot finish until the other has started
#
# Every one takes a lag in days, and the lag may be negative: "start a week
# before the survey ends" is FS with a lag of -7, which is how overlap between
# two pieces of work is written down.
KINDS: tuple[tuple[str, str], ...] = (
    ("FS", "finish → start"),
    ("SS", "start → start"),
    ("FF", "finish → finish"),
    ("SF", "start → finish"),
)
KIND_NOTES: dict[str, str] = {
    "FS": "cannot start until the other finishes",
    "SS": "cannot start until the other starts",
    "FF": "cannot finish until the other finishes",
    "SF": "cannot finish until the other starts",
}
KIND_KEYS = tuple(key for key, _ in KINDS)
DEFAULT_KIND = "FS"


def normalise_kind(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if text in KIND_KEYS else DEFAULT_KIND


def kind_label(value: Any) -> str:
    return dict(KINDS).get(normalise_kind(value), "finish → start")


def kind_note(value: Any) -> str:
    """The link in words, for a tooltip or a document."""
    return KIND_NOTES.get(normalise_kind(value), KIND_NOTES[DEFAULT_KIND])


def _lag_words(lag: int) -> str:
    if lag == 0:
        return "with no lag"
    return f"with a lag of {lag} day{'' if abs(lag) == 1 else 's'}"


def start_reason(driver: Mapping[str, Any], predecessor: Mapping[str, Any],
                 duration_days: int, earliest: Any) -> str:
    """Why a line cannot start where it is drawn, in words.

    The forward pass records which link held a line back; this turns that into
    a sentence. Finish → finish and start → finish are the two that surprise
    people: they fix the *finish*, and a line of a fixed length can only meet a
    later finish by starting later, so the start moves even though nothing was
    said about it.
    """
    kind = normalise_kind(driver.get("kind"))
    try:
        lag = int(round(float(driver.get("lag_days") or 0)))
    except (TypeError, ValueError):
        lag = 0

    who = str(predecessor.get("wbs") or "").strip() or "the line before it"
    from_its_start = kind in ("SS", "SF")
    anchor = predecessor.get("early_start") if from_its_start else predecessor.get("early_finish")
    when = to_display(anchor)
    verb = "starts" if from_its_start else "finishes"
    length = max(1, int(duration_days or 1))
    start = to_display(earliest)
    opening = f"{who} {verb} on {when}. " if when else ""
    rule = f"{kind_label(kind).capitalize()} {_lag_words(lag)}"

    if kind in ("FF", "SF"):
        return (f"{opening}{rule} puts this line's finish at "
                f"{to_display(finish_from(earliest, length))}, and at {length} "
                f"day{'' if length == 1 else 's'} long that means starting on {start}.")
    return f"{opening}{rule} means this line cannot start before {start}."


def _earliest_start(kind: str, lag: float, length: int,
                    began: date | None, done: date | None) -> date | None:
    """The soonest a successor may start, given where its predecessor sits.

    FS and SS drive the successor's start directly; FF and SF drive its finish,
    so its own length is taken off to give the start.
    """
    days = int(round(lag))
    if kind == "SS":
        return began + timedelta(days=days) if began else None
    if kind == "FF":
        return done + timedelta(days=days - (length - 1)) if done else None
    if kind == "SF":
        return began + timedelta(days=days - (length - 1)) if began else None
    return done + timedelta(days=1 + days) if done else None       # FS


def _latest_finish(kind: str, lag: float, length: int,
                   starts_by: date | None, ends_by: date | None) -> date | None:
    """The latest a predecessor may finish, given where its successor sits.

    The mirror of :func:`_earliest_start`: SS and SF are limits on the
    predecessor's start, so its own length is added back on.
    """
    days = int(round(lag))
    if kind == "SS":
        return starts_by - timedelta(days=days) + timedelta(days=length - 1) if starts_by else None
    if kind == "FF":
        return ends_by - timedelta(days=days) if ends_by else None
    if kind == "SF":
        return ends_by - timedelta(days=days) + timedelta(days=length - 1) if ends_by else None
    return starts_by - timedelta(days=1 + days) if starts_by else None   # FS


def normalise_mode(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in MODE_KEYS else DEFAULT_MODE


def parse(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def iso(value: date | None) -> str:
    return value.isoformat() if value else ""


def duration_between(start: Any, finish: Any) -> int:
    """Calendar days from start to finish inclusive: one day is a duration of 1."""
    first, last = parse(start), parse(finish)
    if not first or not last:
        return 0
    return max(1, (last - first).days + 1)


def finish_from(start: Any, days: Any) -> str:
    """The finish a start and a duration imply."""
    first = parse(start)
    if not first:
        return ""
    try:
        length = max(1, int(round(float(days))))
    except (TypeError, ValueError):
        length = 1
    return iso(first + timedelta(days=length - 1))


def with_duration(task: Mapping[str, Any]) -> dict[str, Any]:
    """One line with its duration worked out from its dates."""
    row = dict(task)
    row["duration_days"] = duration_between(row.get("start_date"), row.get("submission_date"))
    return row


# --- dependencies ----------------------------------------------------------

def edges_of(links: Iterable[Mapping[str, Any]]) -> list[tuple[int, int, float, str]]:
    """(predecessor, successor, lag, kind) for every link, as plain values."""
    out = []
    for link in links:
        try:
            out.append((int(link["predecessor_id"]), int(link["successor_id"]),
                        float(link.get("lag_days") or 0), normalise_kind(link.get("kind"))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def would_cycle(links: Iterable[Mapping[str, Any]], predecessor: int, successor: int) -> bool:
    """Whether adding this link would make a deliverable depend on itself.

    A programme that loops has no start, so the link is refused rather than
    quietly producing dates nobody can explain.
    """
    if predecessor == successor:
        return True
    following: dict[int, list[int]] = {}
    for first, second, _lag, _kind in edges_of(links):
        following.setdefault(first, []).append(second)

    seen = {successor}
    stack = [successor]
    while stack:
        node = stack.pop()
        if node == predecessor:
            return True
        for nxt in following.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return False


def order(task_ids: Sequence[int], links: Iterable[Mapping[str, Any]]) -> list[int]:
    """The deliverables in an order where every predecessor comes first.

    Anything caught in a loop is left at the end rather than dropped, so a
    programme with a bad link still draws.
    """
    edges = edges_of(links)
    ids = list(task_ids)
    known = set(ids)
    following: dict[int, list[int]] = {}
    incoming = {task_id: 0 for task_id in ids}
    for first, second, _lag, _kind in edges:
        if first in known and second in known:
            following.setdefault(first, []).append(second)
            incoming[second] += 1

    ready = [task_id for task_id in ids if incoming[task_id] == 0]
    ordered: list[int] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for nxt in following.get(node, ()):
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                ready.append(nxt)

    ordered.extend(task_id for task_id in ids if task_id not in set(ordered))
    return ordered


def paths(task_ids: Iterable[int], links: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The distinct routes through the network: where they begin and end, and
    how many there are.

    A route runs from a line nothing precedes to a line nothing follows. The
    count is worked out along the topological order — the number of routes into
    a line is the sum of the routes into everything before it — so a network of
    any size is counted in one pass rather than by walking every route.
    """
    wanted = {int(task_id) for task_id in task_ids}
    edges = [(a, b) for a, b, _lag, _kind in edges_of(links) if a in wanted and b in wanted]
    if not edges:
        return {"starts": [], "ends": [], "count": 0}

    predecessors: dict[int, set[int]] = {}
    successors: dict[int, set[int]] = {}
    for first, second in edges:
        successors.setdefault(first, set()).add(second)
        predecessors.setdefault(second, set()).add(first)

    joined = {a for a, _ in edges} | {b for _, b in edges}
    starts = sorted(t for t in joined if not predecessors.get(t))
    ends = sorted(t for t in joined if not successors.get(t))

    routes: dict[int, int] = {}
    for task_id in order(sorted(joined), links):
        if task_id not in joined:
            continue
        before = [p for p in predecessors.get(task_id, ()) if p in joined]
        routes[task_id] = sum(routes.get(p, 0) for p in before) if before else 1

    return {"starts": starts, "ends": ends, "count": sum(routes.get(e, 0) for e in ends)}


def analyse(tasks: Sequence[Mapping[str, Any]],
            links: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    """Early and late dates, float, and what is critical, for every line.

    A forward pass gives the earliest each deliverable could start once its
    predecessors are done; a backward pass gives the latest it could start
    without pushing the programme's finish. The difference is its float, and a
    line with none of it is on the critical path.
    """
    rows = {int(t["id"]): dict(t) for t in tasks if t.get("id") is not None}
    if not rows:
        return {}

    edges = [(a, b, lag, kind) for a, b, lag, kind in edges_of(links) if a in rows and b in rows]
    predecessors: dict[int, list[tuple[int, float, str]]] = {}
    successors: dict[int, list[tuple[int, float, str]]] = {}
    for first, second, lag, kind in edges:
        successors.setdefault(first, []).append((second, lag, kind))
        predecessors.setdefault(second, []).append((first, lag, kind))

    sequence = order(list(rows), links)
    length = {
        task_id: max(1, duration_between(row.get("start_date"), row.get("submission_date")) or 1)
        for task_id, row in rows.items()
    }
    planned_start = {task_id: parse(row.get("start_date")) for task_id, row in rows.items()}
    floor = min((day for day in planned_start.values() if day), default=date.today())

    # Forward: the earliest each line can start.
    early_start: dict[int, date] = {}
    early_finish: dict[int, date] = {}
    driver: dict[int, tuple[int, float, str]] = {}
    for task_id in sequence:
        own = planned_start[task_id] or floor
        earliest = own
        for first, lag, kind in predecessors.get(task_id, ()):
            soonest = _earliest_start(kind, lag, length[task_id],
                                      early_start.get(first), early_finish.get(first))
            # Which link holds the line back is worth keeping: it is the whole
            # answer to "why can this not start when I drew it?".
            if soonest and soonest > earliest:
                earliest, driver[task_id] = soonest, (first, lag, kind)
        early_start[task_id] = earliest
        early_finish[task_id] = earliest + timedelta(days=length[task_id] - 1)

    # Backward: the latest each line can start without moving the finish.
    horizon = max(early_finish.values())
    late_finish: dict[int, date] = {}
    late_start: dict[int, date] = {}
    for task_id in reversed(sequence):
        latest = horizon
        for second, lag, kind in successors.get(task_id, ()):
            limit = _latest_finish(kind, lag, length[task_id],
                                   late_start.get(second), late_finish.get(second))
            if limit:
                latest = min(latest, limit)
        late_finish[task_id] = latest
        late_start[task_id] = latest - timedelta(days=length[task_id] - 1)

    result: dict[int, dict[str, Any]] = {}
    for task_id in rows:
        slack = (late_finish[task_id] - early_finish[task_id]).days
        # A line with nothing before or after it is not on a path, whatever its
        # float works out to. Calling every unlinked deliverable that happens to
        # finish on the project's end date "critical" says nothing useful; once
        # it is sequenced, the float decides as it should.
        in_a_chain = bool(predecessors.get(task_id) or successors.get(task_id))
        result[task_id] = {
            "duration_days": length[task_id],
            "early_start": iso(early_start[task_id]),
            "early_finish": iso(early_finish[task_id]),
            "late_start": iso(late_start[task_id]),
            "late_finish": iso(late_finish[task_id]),
            "total_float": slack,
            "is_critical": slack <= 0 and in_a_chain,
            "in_a_chain": in_a_chain,
            # A line whose own start is earlier than its predecessors allow is
            # not achievable as drawn, which is worth saying out loud.
            "starts_late": bool(planned_start[task_id]
                                and early_start[task_id] > planned_start[task_id]),
            "driven_by": ({"task_id": driver[task_id][0],
                           "lag_days": driver[task_id][1],
                           "kind": normalise_kind(driver[task_id][2])}
                          if task_id in driver else None),
            "predecessor_ids": [first for first, _lag, _kind in predecessors.get(task_id, ())],
            "successor_ids": [second for second, _lag, _kind in successors.get(task_id, ())],
        }
    return result


def critical_path(analysis: Mapping[int, Mapping[str, Any]]) -> list[int]:
    """The critical lines, in the order they run."""
    critical = [task_id for task_id, row in analysis.items() if row["is_critical"]]
    return sorted(critical, key=lambda task_id: (analysis[task_id]["early_start"],
                                                 analysis[task_id]["early_finish"]))


def shift_successors(tasks: Sequence[Mapping[str, Any]],
                     links: Iterable[Mapping[str, Any]],
                     moved_id: int) -> dict[int, dict[str, str]]:
    """The new dates for whatever a move pushes.

    Only later: bringing a predecessor forward frees float rather than dragging
    the rest of the programme back with it, which is what a planner expects.
    Returns the lines that actually move, keyed by id.
    """
    rows = {int(t["id"]): dict(t) for t in tasks if t.get("id") is not None}
    edges = [(a, b, lag, kind) for a, b, lag, kind in edges_of(links) if a in rows and b in rows]
    successors: dict[int, list[tuple[int, float, str]]] = {}
    for first, second, lag, kind in edges:
        successors.setdefault(first, []).append((second, lag, kind))

    starts = {task_id: parse(row.get("start_date")) for task_id, row in rows.items()}
    finishes = {task_id: parse(row.get("submission_date")) for task_id, row in rows.items()}
    lengths = {task_id: max(1, duration_between(row.get("start_date"), row.get("submission_date")) or 1)
               for task_id, row in rows.items()}

    moves: dict[int, dict[str, str]] = {}
    queue = [int(moved_id)]
    guard = 0
    while queue and guard < len(rows) * len(rows) + len(rows):
        guard += 1
        node = queue.pop(0)
        done, began = finishes.get(node), starts.get(node)
        if not done or not began:
            continue
        for second, lag, kind in successors.get(node, ()):
            earliest = _earliest_start(kind, lag, lengths[second], began, done)
            if not earliest:
                continue
            current = starts.get(second)
            if current and current >= earliest:
                continue                       # it already sits late enough
            starts[second] = earliest
            finishes[second] = earliest + timedelta(days=lengths[second] - 1)
            moves[second] = {"start_date": iso(starts[second]),
                             "submission_date": iso(finishes[second])}
            queue.append(second)
    return moves


def summarise(analysis: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    """The headline numbers above the plan."""
    if not analysis:
        return {"count": 0, "critical": 0, "start": "", "finish": "", "days": 0, "linked": 0}

    starts = [row["early_start"] for row in analysis.values() if row["early_start"]]
    finishes = [row["early_finish"] for row in analysis.values() if row["early_finish"]]
    return {
        "count": len(analysis),
        "critical": sum(1 for row in analysis.values() if row["is_critical"]),
        "linked": sum(1 for row in analysis.values()
                      if row["predecessor_ids"] or row["successor_ids"]),
        "start": min(starts) if starts else "",
        "finish": max(finishes) if finishes else "",
        "days": duration_between(min(starts), max(finishes)) if starts and finishes else 0,
    }


def link_label(predecessor: Mapping[str, Any], successor: Mapping[str, Any],
               lag: float = 0, kind: str = DEFAULT_KIND) -> str:
    """How one link reads in a list: 1.2 → 1.5, finish → start, -3 days."""
    text = f"{predecessor.get('wbs') or '?'} → {successor.get('wbs') or '?'}, {kind_label(kind)}"
    if lag:
        text += f", {lag:+g} days"
    return text


def window(tasks: Sequence[Mapping[str, Any]], *extra_dates: Any) -> tuple[str, str]:
    """The span a chart has to cover: every date on the plan, plus today."""
    days = []
    for task in tasks:
        for field in ("start_date", "submission_date", "approval_due_date"):
            day = parse(task.get(field))
            if day:
                days.append(day)
        for step in task.get("step_plan") or ():
            day = parse(step.get("date"))
            if day:
                days.append(day)
        for revision in task.get("revisions") or ():
            for field in ("comments_date", "submission_date"):
                day = parse(revision.get(field))
                if day:
                    days.append(day)
    for value in extra_dates:
        day = parse(value)
        if day:
            days.append(day)
    if not days:
        today = date.today()
        return iso(today), iso(today + timedelta(days=30))
    return iso(min(days)), iso(max(days))


def readable(value: Any) -> str:
    return to_display(value) or "—"
