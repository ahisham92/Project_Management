"""Laying the dependency diagram out so the lines cross as little as possible.

Pure functions over ids and links — no database, no drawing — so the ordering
can be tested by counting crossings rather than by looking at a picture.

The method is the standard layered one:

  1. Put every deliverable in a column: one further right than the last of the
     things it waits for. That is the order the work runs in, and it is fixed —
     moving a box between columns would make the picture say something untrue.
  2. Give a link that skips columns a stand-in box in each column it passes, so
     a long line is treated as the run of short ones it is drawn as. Without
     this a line sailing over four columns is counted as crossing nothing.
  3. Sweep up and down the columns, putting each box at the median of the boxes
     it joins in the column before (or after). Repeat, and keep the best
     arrangement seen — the median heuristic improves quickly and then wanders,
     so the best is worth holding on to rather than the last.

Only the order within a column changes, so the picture still reads left to
right in the order the work happens; it just stops tangling.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

# The geometry the diagram is drawn at, shared with app.charts so a saved
# position lands exactly where the automatic layout would have put it.
BOX_W, BOX_H = 54, 26
GAP_X, GAP_Y = 44, 18
PAD = 16

# A stand-in for a link passing through a column: (the link, the column).
Node = Any


def columns_of(task_ids: Iterable[int],
               links: Iterable[Mapping[str, Any]]) -> dict[int, int]:
    """Which column each deliverable sits in: one past the last it waits for."""
    from .schedule import edges_of, order

    wanted = {int(task_id) for task_id in task_ids}
    edges = [(a, b) for a, b, _lag, _kind in edges_of(links) if a in wanted and b in wanted]
    predecessors: dict[int, list[int]] = {}
    for first, second in edges:
        predecessors.setdefault(second, []).append(first)

    joined = {a for a, _ in edges} | {b for _, b in edges}
    column: dict[int, int] = {}
    for task_id in order(sorted(joined), links):
        if task_id not in joined:
            continue
        earlier = [column.get(p, 0) for p in predecessors.get(task_id, ()) if p in joined]
        column[task_id] = (max(earlier) + 1) if earlier else 0
    return column


def _segments(edges: Sequence[tuple[int, int]],
              column: Mapping[int, int]) -> list[list[tuple[Node, Node]]]:
    """Every link cut into one segment per column gap it spans.

    A link from column 1 to column 4 becomes three segments joined by two
    stand-in boxes, so the gaps it passes through count its crossings too.
    """
    gaps = max(column.values(), default=0)
    per_gap: list[list[tuple[Node, Node]]] = [[] for _ in range(gaps)]
    for index, (first, second) in enumerate(edges):
        start, end = column[first], column[second]
        if end <= start:                     # a link that does not go forwards
            continue
        upper: Node = first
        for gap in range(start, end):
            lower: Node = second if gap == end - 1 else ("via", index, gap + 1)
            per_gap[gap].append((upper, lower))
            upper = lower
    return per_gap


def _rows(layout: Mapping[int, Sequence[Node]]) -> dict[Node, int]:
    return {node: row for ids in layout.values() for row, node in enumerate(ids)}


def crossings(layout: Mapping[int, Sequence[Node]],
              per_gap: Sequence[Sequence[tuple[Node, Node]]]) -> int:
    """How many pairs of lines cross, over the whole diagram.

    Two segments in the same gap cross when one starts above the other and
    finishes below it.
    """
    row = _rows(layout)
    total = 0
    for pairs in per_gap:
        drawn = [(row[a], row[b]) for a, b in pairs if a in row and b in row]
        for i in range(len(drawn)):
            for j in range(i + 1, len(drawn)):
                (a1, b1), (a2, b2) = drawn[i], drawn[j]
                if (a1 - a2) * (b1 - b2) < 0:
                    total += 1
    return total


def _median(positions: Sequence[int], fallback: float) -> float:
    if not positions:
        return fallback
    ordered = sorted(positions)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2


def _sweep(layout: dict[int, list[Node]], neighbours: Mapping[Node, list[Node]],
           depths: Sequence[int]) -> None:
    """Order each named column by where its neighbours sit in the last one.

    The positions are read afresh for every column: a sweep works its way along,
    and a column ordered against where the one before it *used* to be undoes the
    work just done to it.
    """
    for depth in depths:
        row = _rows(layout)
        here = layout[depth]
        keys = {node: _median([row[n] for n in neighbours.get(node, ()) if n in row],
                              float(index))
                for index, node in enumerate(here)}
        # A box with nothing to follow keeps its place, so the sort is stable
        # against the order it came in with.
        here.sort(key=lambda node: (keys[node], row[node]))


def arrange(task_ids: Sequence[int], links: Iterable[Mapping[str, Any]],
            sweeps: int = 12) -> dict[str, Any]:
    """Where each box goes, and how much tangle the arrangement removed.

    `task_ids` is the starting order — pass them sorted by WBS and an already
    tidy programme comes back unchanged. Returns the column and row of every
    deliverable in the network, plus the crossings before and after.
    """
    from .schedule import edges_of

    wanted = {int(task_id) for task_id in task_ids}
    edges = [(a, b) for a, b, _lag, _kind in edges_of(links) if a in wanted and b in wanted]
    column = columns_of(task_ids, links)
    if not column:
        return {"places": {}, "before": 0, "after": 0}

    per_gap = _segments(edges, column)

    # The starting arrangement: the order the caller gave, plus a stand-in put
    # at the end of each column it passes through.
    layout: dict[int, list[Node]] = {depth: [] for depth in range(max(column.values()) + 1)}
    for task_id in task_ids:
        if int(task_id) in column:
            layout[column[int(task_id)]].append(int(task_id))
    for gap, pairs in enumerate(per_gap):
        for _upper, lower in pairs:
            if isinstance(lower, tuple) and lower not in layout[gap + 1]:
                layout[gap + 1].append(lower)

    down: dict[Node, list[Node]] = {}      # a node -> what it joins on its left
    up: dict[Node, list[Node]] = {}        # a node -> what it joins on its right
    for pairs in per_gap:
        for upper, lower in pairs:
            down.setdefault(lower, []).append(upper)
            up.setdefault(upper, []).append(lower)

    before = crossings(layout, per_gap)
    best = {depth: list(ids) for depth, ids in layout.items()}
    fewest = before

    depths = sorted(layout)
    for pass_number in range(sweeps):
        _sweep(layout, down if pass_number % 2 == 0 else up,
               depths[1:] if pass_number % 2 == 0 else list(reversed(depths[:-1])))
        count = crossings(layout, per_gap)
        if count < fewest:
            fewest, best = count, {depth: list(ids) for depth, ids in layout.items()}
        if fewest == 0:
            break

    places = {node: (depth, row)
              for depth, ids in best.items()
              for row, node in enumerate(ids)
              if not isinstance(node, tuple)}
    return {"places": places, "before": before, "after": fewest}


def point(depth: int, row: int) -> tuple[float, float]:
    """The column and row of a box, in the coordinates the diagram is drawn in."""
    return (PAD + depth * (BOX_W + GAP_X), PAD + row * (BOX_H + GAP_Y))
