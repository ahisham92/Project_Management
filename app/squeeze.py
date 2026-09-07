"""Squeezing a stretch of the programme into fewer days.

The ask is the one every project manager makes: *this has to be done in three
months, not four*. What that means in practice is a run of deliverables — from
one line to another along the dependencies — whose durations all come down in
proportion, with everything after it pulled forward by what was saved.

Three rules decide the arithmetic, and they are here rather than in a screen
because the Schedule tab, Carmen and the tests all have to apply the same ones.

**Durations come down in proportion to what they already are.** A line given 25
days and a line given 5 are not the same job; halving the stretch should halve
both, not take ten days off each. So every line keeps its share.

**Days are whole, and the rounding goes to the short lines.** 25 and 5 squeezed
into 15 is 12.5 and 2.5, which is not a programme anybody can work to. It comes
out 12 and 3: the leftover day goes to the shorter line, because a day taken off
a 3-day job costs a third of it and a day off a 12-day job costs a twelfth. No
line ever falls below one day.

**Waiting is not work, so it does not compress.** A lag between two lines is a
client review or a curing time — a fortnight of it is a fortnight however hard
anybody pushes. Lags are left alone, and where they mean the stretch cannot
reach the target, that is reported rather than quietly missed.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .schedule import (_diaries, _earliest_start, duration_between, edges_of,
                       finish_from, iso, order, parse, working)


class SqueezeError(ValueError):
    """A squeeze that cannot be worked out, said in words."""


def between(first_id: int, last_id: int,
            links: Iterable[Mapping[str, Any]]) -> list[int]:
    """Every deliverable on a dependency route from one line to another.

    Not the shortest route and not only the longest: everything that runs
    between them, because a branch left at its old length is a branch that
    finishes after the line it was supposed to feed.
    """
    edges = edges_of(links)
    forward: dict[int, set[int]] = {}
    backward: dict[int, set[int]] = {}
    for a, b, _lag, _kind in edges:
        forward.setdefault(a, set()).add(b)
        backward.setdefault(b, set()).add(a)

    def reach(start: int, graph: Mapping[int, set[int]]) -> set[int]:
        seen = {start}
        queue = [start]
        while queue:
            node = queue.pop()
            for nxt in graph.get(node, ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return seen

    if first_id == last_id:
        return [first_id]
    both = reach(first_id, forward) & reach(last_id, backward)
    return sorted(both) if len(both) > 1 else []


def share_out(lengths: Mapping[int, int], target: int) -> dict[int, int]:
    """The durations scaled to total ``target``, in whole days.

    Largest remainder, and a tie goes to the shorter line — which is what makes
    12.5 and 2.5 come out as 12 and 3 rather than 13 and 2.
    """
    ids = list(lengths)
    if not ids:
        return {}
    if target < len(ids):
        raise SqueezeError(
            f"{len(ids)} deliverables cannot share {target} day"
            f"{'s' if target != 1 else ''} — each one needs at least one, so "
            f"{len(ids)} is the shortest this stretch can be")

    total = sum(max(1, lengths[i]) for i in ids)
    ratio = target / total if total else 1.0

    exact = {i: max(1, lengths[i]) * ratio for i in ids}
    whole = {i: max(1, int(exact[i])) for i in ids}

    # Hand the days that are left to the lines with most of one owing, and when
    # two are owed the same, to the shorter of them.
    spare = target - sum(whole.values())
    if spare > 0:
        owed = sorted(ids, key=lambda i: (-(exact[i] - whole[i]), lengths[i], i))
        for n in range(spare):
            whole[owed[n % len(owed)]] += 1
    while spare < 0:
        # Rounding up to the floor of one day can overshoot on a hard squeeze.
        # Take the days back off the longest lines, never below one day.
        takeable = sorted((i for i in ids if whole[i] > 1), key=lambda i: (-whole[i], i))
        if not takeable:
            break
        whole[takeable[0]] -= 1
        spare += 1
    return whole


def plan(tasks: Sequence[Mapping[str, Any]], links: Sequence[Mapping[str, Any]],
         calendars: Mapping[Any, Any] | None,
         first_id: int, last_id: int, target: Any) -> dict[str, Any]:
    """What squeezing this stretch into ``target`` working days would do.

    Nothing is written. The answer is the whole proposal — every line that
    changes, its old and new duration and dates, what the stretch finishes on
    and how many days that saves — so a screen can show it and somebody can
    look at it before it happens.
    """
    rows = {int(t["id"]): dict(t) for t in tasks if t.get("id") is not None}
    if first_id not in rows or last_id not in rows:
        raise SqueezeError("Those deliverables are not both on this project")

    try:
        want = int(target)
    except (TypeError, ValueError):
        raise SqueezeError("The stretch has to be a whole number of working days") from None
    if want < 1:
        raise SqueezeError("A stretch of no days is not a programme")

    scope = between(first_id, last_id, links)
    if not scope:
        raise SqueezeError(
            f"Nothing links {rows[first_id].get('wbs') or rows[first_id].get('name')} to "
            f"{rows[last_id].get('wbs') or rows[last_id].get('name')}, so there is no stretch "
            "between them to squeeze. Link them on the schedule, or pick the two ends of a "
            "run that is already joined up.")

    diary = _diaries(rows, calendars)
    lengths = {i: max(1, duration_between(rows[i].get("start_date"),
                                          rows[i].get("submission_date"), diary[i]) or 1)
               for i in scope}
    was_total = sum(lengths.values())
    began = parse(rows[first_id].get("start_date"))
    was_finish = parse(rows[last_id].get("submission_date"))
    if not began or not was_finish:
        raise SqueezeError("Both ends of the stretch need a start and a submission date first")

    wanted = share_out(lengths, want)

    # Re-lay the stretch: the first line keeps its start, and everything else
    # follows its own predecessors, on its own team's working week.
    starts: dict[int, Any] = {}
    finishes: dict[int, Any] = {}
    inside = set(scope)
    coming: dict[int, list[tuple[int, float, str]]] = {}
    for a, b, lag, kind in edges_of(links):
        if a in inside and b in inside:
            coming.setdefault(b, []).append((a, lag, kind))

    for task_id in order(scope, links):
        length = wanted[task_id]
        earliest = None
        for before, lag, kind in coming.get(task_id, ()):
            if before not in starts:
                continue
            from_here = _earliest_start(kind, lag, length, starts[before], finishes[before],
                                        diary[task_id])
            if from_here and (earliest is None or from_here > earliest):
                earliest = from_here
        if earliest is None:
            earliest = parse(rows[task_id].get("start_date")) if task_id != first_id else began
            earliest = earliest or began
        start = diary[task_id].next_working(earliest) or earliest
        starts[task_id] = start
        finishes[task_id] = diary[task_id].finish_after(start, length) or start

    now_finish = finishes[last_id]
    saved = _days_between(working((calendars or {}).get(None)), now_finish, was_finish)

    changes: list[dict[str, Any]] = []
    for task_id in order(scope, links):
        row = rows[task_id]
        change = {
            "id": task_id, "wbs": row.get("wbs") or "", "name": row.get("name") or "",
            "was_days": lengths[task_id], "days": wanted[task_id],
            "was_start": row.get("start_date") or "", "start": iso(starts[task_id]),
            "was_submission": row.get("submission_date") or "",
            "submission": iso(finishes[task_id]),
        }
        change["moved"] = (change["start"] != change["was_start"]
                           or change["submission"] != change["was_submission"])
        changes.append(change)

    after = _pull_in(rows, links, diary, starts, finishes, inside)

    return {
        "first_id": first_id, "last_id": last_id,
        "scope": scope,
        "target_days": want,
        "was_days": was_total,
        "days": sum(wanted.values()),
        "was_finish": iso(was_finish),
        "finish": iso(now_finish),
        "start": iso(began),
        "saved_days": saved,
        "changes": changes,
        "after": after,
        # The durations always total the target; the stretch itself only lands
        # on it when nothing is waiting in the middle. Said either way.
        "reaches_target": _reaches(inside, links, want, sum(wanted.values())),
    }


def _reaches(inside: set[int], links: Sequence[Mapping[str, Any]], want: int,
             total: int) -> bool:
    if total != want:
        return False
    return not any(lag for a, b, lag, _kind in edges_of(links)
                   if a in inside and b in inside and lag)


def _days_between(calendar: Any, earlier: Any, later: Any) -> int:
    """Working days from one date to another; negative if it is the other way."""
    first, last = parse(earlier), parse(later)
    if not first or not last:
        return 0
    if last == first:
        return 0
    if last > first:
        return max(0, calendar.duration(first, last) - 1)
    return -max(0, calendar.duration(last, first) - 1)


def _pull_in(rows: Mapping[int, Mapping[str, Any]], links: Sequence[Mapping[str, Any]],
             diary: Mapping[int, Any], starts: Mapping[int, Any],
             finishes: Mapping[int, Any], inside: set[int]) -> list[dict[str, Any]]:
    """Everything after the stretch, brought forward with it.

    A squeeze that leaves the rest of the programme where it was has not
    shortened anything, so what follows moves too — as early as its own
    predecessors allow and no earlier, keeping the length it was given.
    """
    successors: dict[int, list[tuple[int, float, str]]] = {}
    predecessors: dict[int, list[tuple[int, float, str]]] = {}
    for a, b, lag, kind in edges_of(links):
        if a in rows and b in rows:
            successors.setdefault(a, []).append((b, lag, kind))
            predecessors.setdefault(b, []).append((a, lag, kind))

    placed = {task_id: (starts[task_id], finishes[task_id]) for task_id in inside}
    for task_id, row in rows.items():
        if task_id not in inside:
            placed[task_id] = (parse(row.get("start_date")), parse(row.get("submission_date")))

    lengths = {task_id: max(1, duration_between(row.get("start_date"),
                                                row.get("submission_date"),
                                                diary[task_id]) or 1)
               for task_id, row in rows.items()}

    moved: dict[int, dict[str, str]] = {}
    queue = [task_id for task_id in inside]
    guard = 0
    limit = len(rows) * len(rows) + len(rows)
    while queue and guard < limit:
        guard += 1
        node = queue.pop(0)
        for second, _lag, _kind in successors.get(node, ()):
            if second in inside:
                continue
            earliest = None
            for before, lag, kind in predecessors.get(second, ()):
                began, done = placed.get(before, (None, None))
                if not began or not done:
                    continue
                from_here = _earliest_start(kind, lag, lengths[second], began, done,
                                            diary[second])
                if from_here and (earliest is None or from_here > earliest):
                    earliest = from_here
            if earliest is None:
                continue
            start = diary[second].next_working(earliest) or earliest
            was_start, _was_finish = placed[second]
            if was_start and start >= was_start:
                continue                       # it was already sitting this early
            finish = diary[second].finish_after(start, lengths[second]) or start
            placed[second] = (start, finish)
            moved[second] = {
                "id": second, "wbs": rows[second].get("wbs") or "",
                "name": rows[second].get("name") or "",
                "was_start": rows[second].get("start_date") or "", "start": iso(start),
                "was_submission": rows[second].get("submission_date") or "",
                "submission": iso(finish), "days": lengths[second],
            }
            queue.append(second)

    return [moved[task_id] for task_id in order(list(moved), links) if task_id in moved]
