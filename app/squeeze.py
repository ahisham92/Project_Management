"""Squeezing a stretch of the programme between two dates.

The ask is the one every project manager makes: *this has to be finished in
three months, not four*. What that means in practice is a run of deliverables —
from one line to another along the dependencies — whose durations all come down
in the same proportion, laid out again between the two dates you name, with
everything after the run pulled along with it.

Five rules decide the arithmetic. They are here rather than in a screen because
the Schedule tab, Carmen and the tests all have to apply the same ones.

**One ratio, taken from the elapsed span.** Four months into three is every
duration times 0.75. Not "share these days out between the lines" — that is how
a 43-day job ends up at 2 days, which is not a programme anybody can work to.

**The run ends when the last line is approved, not submitted.** A Code A
fourteen days after submission is fourteen days of the programme; changing it to
seven moves the end date. So the span is measured to the last approval, and the
ratio is solved for until the last approval lands on the date you asked for.

**Days are whole, and the rounding goes to the short lines.** 25 and 5 into 15
is 12.5 and 2.5, which nobody can work to. It comes out 12 and 3: a day off a
3-day job costs a third of it and a day off a 12-day job costs a twelfth. No
line ever falls below one day.

**Waiting is not work, so it does not compress.** A lag between two lines is a
client review or a curing time — a fortnight of it is a fortnight however hard
anybody pushes. Lags are left alone, and where they mean the run cannot reach
the date, that is reported rather than quietly missed.

**Some lines do not squeeze at all.** A survey takes as long as it takes, and a
meeting is a day. Those are excluded by hand and keep the length they have.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from .schedule import (_diaries, _earliest_start, duration_between, edges_of,
                       iso, order, parse, working)

# How many times the ratio is adjusted before the answer is taken as it stands.
# It converges in two or three; the rest is for a run whose end date is pinned
# by a lag it cannot compress.
TRIES = 8


class SqueezeError(ValueError):
    """A squeeze that cannot be worked out, said in words."""


# --- what is in the run -----------------------------------------------------

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
            f"{len(ids)} is the shortest this run can be")

    total = sum(max(1, lengths[i]) for i in ids)
    ratio = target / total if total else 1.0
    exact = {i: max(1, lengths[i]) * ratio for i in ids}
    whole = {i: max(1, int(exact[i])) for i in ids}

    spare = target - sum(whole.values())
    if spare > 0:
        owed = sorted(ids, key=lambda i: (-(exact[i] - whole[i]), lengths[i], i))
        for n in range(spare):
            whole[owed[n % len(owed)]] += 1
    while spare < 0:
        takeable = sorted((i for i in ids if whole[i] > 1), key=lambda i: (-whole[i], i))
        if not takeable:
            break
        whole[takeable[0]] -= 1
        spare += 1
    return whole


# --- when a line is finished ------------------------------------------------

def approval_offset(task: Mapping[str, Any], steps: Sequence[Mapping[str, Any]]) -> int:
    """Days between a line's submission and its approval, on this project.

    A line that is not on the design workflow — a meeting, a milestone — is
    finished when it is submitted, so its offset is nothing.
    """
    from .calc import uses_workflow
    from .workflow import CODE_A

    if not uses_workflow(task) or not steps:
        return 0
    step = next((s for s in steps if s.get("key") == CODE_A), None)
    if step is None or str(step.get("anchor") or "submission") != "submission":
        return 0
    return int(round(float(step.get("offset_days") or 0)))


def _finished(task: Mapping[str, Any], finish: Any, offset: int, diary: Any) -> Any:
    """When a line is done: its submission, plus the wait for a Code A."""
    if not offset:
        return finish
    return diary.add(finish, offset) or finish


# --- the proposal -----------------------------------------------------------

def plan(tasks: Sequence[Mapping[str, Any]], links: Sequence[Mapping[str, Any]],
         calendars: Mapping[Any, Any] | None,
         first_id: int, last_id: int, starts: Any, ends: Any,
         steps: Sequence[Mapping[str, Any]] = (), excluded: Iterable[int] = (),
         ) -> dict[str, Any]:
    """What squeezing this run between two dates would do.

    Nothing is written. The answer is the whole proposal — every line that
    changes, its old and new duration and dates, what the run finishes on and
    how far that is from what was asked — so a screen can show it and somebody
    can look at it before it happens.
    """
    rows = {int(t["id"]): dict(t) for t in tasks if t.get("id") is not None}
    if first_id not in rows or last_id not in rows:
        raise SqueezeError("Those deliverables are not both on this project")

    want_start, want_end = parse(starts), parse(ends)
    if want_start is None or want_end is None:
        raise SqueezeError("Give the day the run starts and the day it has to be finished, "
                           "both as dd/mm/yyyy")
    if want_end < want_start:
        raise SqueezeError("The run cannot finish before it starts")

    scope = between(first_id, last_id, links)
    if not scope:
        raise SqueezeError(
            f"Nothing links {rows[first_id].get('wbs') or rows[first_id].get('name')} to "
            f"{rows[last_id].get('wbs') or rows[last_id].get('name')}, so there is no run "
            "between them to squeeze. Link them on the schedule, or pick the two ends of a "
            "run that is already joined up.")

    diary = _diaries(rows, calendars)
    shared = working((calendars or {}).get(None))
    held = {int(i) for i in excluded if int(i) in set(scope)}
    movable = [i for i in scope if i not in held]
    if not movable:
        raise SqueezeError("Every line in that run is excluded, so there is nothing to squeeze")

    lengths = {i: max(1, duration_between(rows[i].get("start_date"),
                                          rows[i].get("submission_date"), diary[i]) or 1)
               for i in scope}
    offsets = {i: approval_offset(rows[i], steps) for i in scope}

    began = parse(rows[first_id].get("start_date"))
    if began is None:
        raise SqueezeError("The line the run starts on has no start date")
    was_finish = _latest(rows, scope, offsets, diary)
    if was_finish is None:
        raise SqueezeError("The lines in that run need submission dates first")

    was_span = max(1, shared.duration(began, was_finish))
    want_span = max(1, shared.duration(want_start, want_end))

    # Solve for the ratio. One pass gets it close; the rest is for a run whose
    # end is pinned by a lag or an excluded line, where the honest answer is
    # "this is as near as it goes" rather than a number that looks exact.
    movable_total = sum(lengths[i] for i in movable)
    ratio = want_span / was_span
    best: dict[str, Any] | None = None
    for _try in range(TRIES):
        wanted = dict(lengths)
        target_total = max(len(movable), int(round(movable_total * ratio)))
        wanted.update(share_out({i: lengths[i] for i in movable}, target_total))
        laid = _lay_out(rows, links, scope, diary, wanted, want_start, first_id)
        reached = _latest_of(laid, scope, offsets, diary)
        miss = shared.duration(reached, want_end) - 1 if reached <= want_end else -(
            shared.duration(want_end, reached) - 1)
        if best is None or abs(miss) < abs(best["miss"]):
            best = {"miss": miss, "wanted": wanted, "laid": laid, "reached": reached,
                    "ratio": ratio}
        if miss == 0 or not movable_total:
            break
        # Nudge the ratio by the proportion still missing.
        span_now = max(1, shared.duration(want_start, reached))
        ratio = max(0.01, ratio * (want_span / span_now))

    assert best is not None
    wanted, laid, reached = best["wanted"], best["laid"], best["reached"]

    changes: list[dict[str, Any]] = []
    for task_id in order(scope, links):
        row = rows[task_id]
        start, finish = laid[task_id]
        change = {
            "id": task_id, "wbs": row.get("wbs") or "", "name": row.get("name") or "",
            "was_days": lengths[task_id], "days": wanted[task_id],
            "was_start": row.get("start_date") or "", "start": iso(start),
            "was_submission": row.get("submission_date") or "", "submission": iso(finish),
            "held": task_id in held,
            "approval": iso(_finished(row, finish, offsets[task_id], diary[task_id])),
        }
        change["moved"] = (change["start"] != change["was_start"]
                           or change["submission"] != change["was_submission"])
        changes.append(change)

    after = _pull_in(rows, links, diary, laid, set(scope))

    return {
        "first_id": first_id, "last_id": last_id,
        "scope": scope, "excluded": sorted(held),
        "start": iso(want_start), "end": iso(want_end),
        "was_start": iso(began), "was_finish": iso(was_finish),
        "finish": iso(reached),
        "was_days": was_span, "days": max(1, shared.duration(want_start, reached)),
        "target_days": want_span,
        "ratio": round(best["ratio"], 4),
        "days_out": best["miss"],
        "on_the_date": best["miss"] == 0,
        "saved_days": (shared.duration(reached, was_finish) - 1) if reached <= was_finish
                      else -(shared.duration(was_finish, reached) - 1),
        "changes": changes,
        "after": after,
    }


def _latest(rows: Mapping[int, Mapping[str, Any]], scope: Sequence[int],
            offsets: Mapping[int, int], diary: Mapping[int, Any]) -> Any:
    """The day the run is finished as it stands: the last approval on it."""
    days = []
    for task_id in scope:
        finish = parse(rows[task_id].get("submission_date"))
        if finish is None:
            continue
        days.append(_finished(rows[task_id], finish, offsets[task_id], diary[task_id]))
    return max(days) if days else None


def _latest_of(laid: Mapping[int, tuple], scope: Sequence[int],
               offsets: Mapping[int, int], diary: Mapping[int, Any]) -> Any:
    days = [_finished({}, laid[i][1], offsets[i], diary[i]) for i in scope if i in laid]
    return max(days) if days else None


def _lay_out(rows: Mapping[int, Mapping[str, Any]], links: Sequence[Mapping[str, Any]],
             scope: Sequence[int], diary: Mapping[int, Any], lengths: Mapping[int, int],
             began: Any, first_id: int) -> dict[int, tuple]:
    """The run laid out from a start date, each line after its predecessors."""
    inside = set(scope)
    coming: dict[int, list[tuple[int, float, str]]] = {}
    for a, b, lag, kind in edges_of(links):
        if a in inside and b in inside:
            coming.setdefault(b, []).append((a, lag, kind))

    starts: dict[int, Any] = {}
    finishes: dict[int, Any] = {}
    for task_id in order(list(scope), links):
        length = lengths[task_id]
        earliest = None
        for before, lag, kind in coming.get(task_id, ()):
            if before not in starts:
                continue
            from_here = _earliest_start(kind, lag, length, starts[before], finishes[before],
                                        diary[task_id])
            if from_here and (earliest is None or from_here > earliest):
                earliest = from_here
        if earliest is None:
            earliest = began
        # Nothing in the run starts before the day the run starts.
        if earliest < began:
            earliest = began
        start = diary[task_id].next_working(earliest) or earliest
        starts[task_id] = start
        finishes[task_id] = diary[task_id].finish_after(start, length) or start
    return {task_id: (starts[task_id], finishes[task_id]) for task_id in scope}


def _pull_in(rows: Mapping[int, Mapping[str, Any]], links: Sequence[Mapping[str, Any]],
             diary: Mapping[int, Any], laid: Mapping[int, tuple],
             inside: set[int]) -> list[dict[str, Any]]:
    """Everything after the run, moved with it.

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

    placed = dict(laid)
    for task_id, row in rows.items():
        if task_id not in inside:
            placed[task_id] = (parse(row.get("start_date")), parse(row.get("submission_date")))

    lengths = {task_id: max(1, duration_between(row.get("start_date"),
                                                row.get("submission_date"),
                                                diary[task_id]) or 1)
               for task_id, row in rows.items()}

    moved: dict[int, dict[str, Any]] = {}
    queue = list(inside)
    guard, limit = 0, len(rows) * len(rows) + len(rows)
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
            was_start, _was = placed[second]
            if was_start and start == was_start:
                continue
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


# --- meetings that recur ----------------------------------------------------
#
# A programme carries a series: "Bi-weekly progress meeting No. 1", "No. 2",
# and so on to the end. They are not work that compresses — each is a day — but
# there are as many of them as the programme is long. Squeeze four months into
# three and two of the eight should go; extend it to six and four more are due.
# Nothing else in the plan behaves like this, so it is recognised rather than
# configured: a run of milestones whose names are the same but for a number.

NUMBERED = re.compile(r"^(?P<before>.*?)(?P<number>\d+)(?P<after>.*)$")

# Two members is a coincidence. Three is a series.
SERIES_AT_LEAST = 3


def _numbered(name: str) -> tuple[str, int, str] | None:
    found = NUMBERED.match(" ".join(str(name or "").split()))
    if not found:
        return None
    return found.group("before"), int(found.group("number")), found.group("after")


MEETING_WORDS = ("meeting", "review", "workshop", "presentation")


def series_in(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Runs of numbered lines that recur, in the order they happen.

    The signature of a series is the name — the same words but for a number —
    plus the same length each time and a regular gap between them. That is what
    a fortnightly meeting looks like in a programme, and what a numbered set of
    drawing packages does not.

    Whether a series *should* follow the length of the programme is not decided
    here. It is shown, with what it would become, and somebody says.
    """
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        start, finish = parse(row.get("start_date")), parse(row.get("submission_date"))
        if start is None or finish is None:
            continue
        parts = _numbered(row.get("name") or "")
        if not parts:
            continue
        before, number, after = parts
        if len(before.strip()) < 4:               # "1.2" is not a series name
            continue
        groups.setdefault((before, after), []).append(
            {"id": row["id"], "number": number, "date": finish, "start": start,
             "length": (finish - start).days, "row": row})

    out = []
    for (before, after), members in groups.items():
        if len(members) < SERIES_AT_LEAST:
            continue
        members.sort(key=lambda m: m["date"])
        # The same length each time. A numbered set of real deliverables is not
        # the same job over and over, and it varies.
        lengths = {m["length"] for m in members}
        if max(lengths) - min(lengths) > 1:
            continue
        gaps = [(b["date"] - a["date"]).days for a, b in zip(members, members[1:])]
        gaps = [g for g in gaps if g > 0]
        if not gaps or max(gaps) - min(gaps) > max(2, min(gaps) // 3):
            continue                              # not a regular cadence
        gaps.sort()
        words = f"{before} {after}".lower()
        out.append({
            "before": before, "after": after, "members": members,
            "every_days": gaps[len(gaps) // 2],
            "length": members[0]["length"],
            "name": f"{before}N{after}".strip(),
            # Ticked by default when it reads as a meeting; a series of anything
            # else is somebody's decision, not a date picker's.
            "is_meeting": any(word in words for word in MEETING_WORDS),
        })
    out.sort(key=lambda s: s["members"][0]["date"])
    return out


def meetings_for(rows: Sequence[Mapping[str, Any]], from_day: Any, to_day: Any,
                 diary: Mapping[int, Any] | None = None) -> list[dict[str, Any]]:
    """What each series becomes between two dates: how many, and which go.

    The cadence is kept — a fortnightly meeting stays fortnightly — and the
    number of them follows the length of the run. The ones at the end are the
    ones added or dropped, because renumbering from the middle would rename
    every set of minutes already written against them.
    """
    from datetime import timedelta

    start, finish = parse(from_day), parse(to_day)
    if start is None or finish is None:
        return []

    out = []
    for run in series_in(rows):
        every = run["every_days"]
        first = max(start, parse(run["members"][0]["date"]) or start)
        if first > finish:
            first = start
        when: list[Any] = []
        day = first
        while day <= finish:
            when.append(day)
            day = day + timedelta(days=every)

        wanted = max(1, len(when))
        have = len(run["members"])
        keeping = run["members"][:wanted]
        dropping = run["members"][wanted:]
        adding = wanted - have

        length = max(0, int(run.get("length") or 0))

        def placed(day: Any, like: int) -> tuple[str, str]:
            """One occurrence: the day it happens, and when its run-up starts."""
            if diary is not None and like in diary:
                day = diary[like].next_working(day) or day
            return iso(day - timedelta(days=length)), iso(day)

        moves = []
        for n, member in enumerate(keeping):
            day = when[n] if n < len(when) else member["date"]
            start, finish = placed(day, member["id"])
            moves.append({"id": member["id"], "date": finish, "start": start,
                          "was": iso(member["date"]), "number": n + 1,
                          "name": f"{run['before']}{n + 1}{run['after']}"})

        extra = []
        last = run["members"][-1]["id"]
        for n in range(have, wanted):
            start, finish = placed(when[n], last)
            extra.append({"date": finish, "start": start, "number": n + 1,
                          "name": f"{run['before']}{n + 1}{run['after']}",
                          "like": last})

        out.append({
            "name": run["name"], "every_days": every, "is_meeting": run["is_meeting"],
            "had": have, "wants": wanted, "change": adding,
            "moves": moves,
            "add": extra,
            "remove": [{"id": m["id"], "name": m["row"].get("name") or "",
                        "date": iso(m["date"])} for m in dropping],
        })
    return out
