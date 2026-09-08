"""The deck: what was done between two dates, as slides somebody can present.

Built from the same figures the tabs draw, so the presentation and the screen
can never say different things. What goes on it is what a project manager would
put on it themselves — where the project stands, what actually moved, what is
not going well, and what the coming weeks want — in that order, because that is
the order a client asks.

It is laid out in three acts with a dark divider in front of each, because a
run of twelve slides that all look alike is one nobody can navigate. Every
slide carries something drawn: the dial, the curve, the bars, the strip of
dates. The tables are for the detail underneath them, not for the argument.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..dates import to_display
from ..deck import BAD, DEEP, GOOD, MIST, MUTED, TEAL, WARN, Deck


def _pct(value: Any, places: int = 1) -> str:
    try:
        return f"{float(value):.{places}f}%"
    except (TypeError, ValueError):
        return "—"


def _short(text: Any, limit: int) -> str:
    """A name cut to fit, on a word boundary.

    Cutting mid-word is the difference between a deck that was laid out and one
    that was generated: "communication prot" is what nobody would ever type.
    """
    words = " ".join(str(text or "").split())
    if len(words) <= limit:
        return words
    cut = words[:limit].rsplit(" ", 1)[0].rstrip(" ,;-–&")
    return f"{cut or words[:limit]}…"


def _many(count: int, one: str, more: str = "") -> str:
    """A count with its noun agreeing with it."""
    return f"{count} {one if count == 1 else (more or one + 's')}"


def _whole(value: Any) -> str:
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _curve_points(points: Sequence[Mapping[str, Any]], field: str
                  ) -> list[tuple[float, float]]:
    """One series of the S-curve as fractions of the chart's own box.

    Anything with no value yet — earned progress after the data date — simply
    ends the line there, which is what makes the gap between the two curves
    readable rather than a drop to zero.
    """
    kept = [(index, row.get(field)) for index, row in enumerate(points)]
    kept = [(index, float(value)) for index, value in kept if value is not None]
    if not kept:
        return []
    last = max(1, len(points) - 1)
    return [(index / last, min(1.0, max(0.0, value))) for index, value in kept]


def build(project: Mapping[str, Any], start: str, end: str, title: str = "") -> bytes:
    """The whole deck, as a .pptx."""
    from .. import week as weeks
    from ..service import (as_dict, load_items, project_overview, project_period,
                           project_plan, project_s_curve, project_snapshot, today)

    project = as_dict(project)
    code = str(project.get("code") or "")
    name = str(project.get("name") or "Project")
    client = str(project.get("client") or "")
    stamp = today()

    snapshot = project_snapshot(project, stamp)
    overview = project_overview(project, snapshot)
    report = project_period(project, start, end)
    plan = project_plan(project, stamp)
    totals = snapshot["totals"]

    deck = Deck(footer=f"{code} · {name}")

    # --- the cover ----------------------------------------------------------
    deck.cover(
        title or f"Progress to {to_display(end)}",
        f"{code} · {name}",
        f"{client or 'Client'}   ·   the period {to_display(start)} to {to_display(end)}"
        f"   ·   prepared {to_display(stamp)}",
    )

    # --- 01 · where the project stands --------------------------------------
    behind = overview["variance"] < 0
    deck.divider(1, "Where the project stands",
                 f"As at {to_display(stamp)}, before anything about the period")

    deck.gauge(
        "Earned against plan", overview["earned"], "earned to date",
        [{"label": "Planned by today", "value": _whole(overview["planned"]),
          "hint": "from the schedule"},
         {"label": "Variance", "value": _pct(overview["variance"] * 100, 2),
          "hint": "behind plan" if behind else "ahead of plan",
          "colour": BAD if behind else GOOD},
         {"label": "Float", "value": f"{overview['float_days']}d",
          "hint": ("to the contract date" if overview["on_time"]
                   else "past the contract date"),
          "colour": GOOD if overview["on_time"] else BAD}],
        note=(f"The programme runs {to_display(overview['start'])} to "
              f"{to_display(overview['finish'])}, against a contract date of "
              f"{to_display(overview['contract_end'])}."))

    curve = project_s_curve(project, stamp)
    planned = _curve_points(curve, "planned")
    earned = _curve_points(curve, "earned")
    if planned:
        deck.curve(
            "Planned against earned",
            [{"name": "Planned", "colour": MIST, "hint": "from the schedule",
              "points": planned, "width": 22225},
             {"name": "Earned", "colour": DEEP, "fill": "E4EDF3",
              "hint": "from what was reported", "points": earned, "width": 34925}],
            marks=[{"at": (len(earned) - 1) / max(1, len(curve) - 1),
                    "label": "today", "colour": MUTED}] if earned else (),
            caption=f"{to_display(curve[0]['date'])} – {to_display(curve[-1]['date'])}",
            note=("Earned is behind planned by "
                  f"{_pct(abs(overview['variance']) * 100, 2)} of the project."
                  if behind else
                  "Earned is ahead of planned by "
                  f"{_pct(overview['variance'] * 100, 2)} of the project."))

    # --- 02 · the period ----------------------------------------------------
    gained = report["earned_in_period"] * 100
    moved = sorted((row for row in report["tasks"] if row["delta_actual"] > 1e-9),
                   key=lambda row: -row["earned_in_period"])
    deck.divider(2, "The period",
                 f"{to_display(start)} to {to_display(end)} · "
                 f"{report['days_in_period']} days")

    deck.figures("What the period did", [
        {"label": "Progress gained", "value": _pct(gained, 2),
         "hint": "of the whole project", "colour": DEEP},
        {"label": "At the start", "value": _whole(report["earned_at_start"]),
         "hint": to_display(start)},
        {"label": "At the end", "value": _whole(report["earned_at_end"]),
         "hint": to_display(end)},
        {"label": "Lines that moved", "value": str(len(moved)),
         "hint": "deliverables advanced", "colour": TEAL},
    ], note=("Nothing was reported in this period." if not moved else
             f"{moved[0]['wbs']} {_short(moved[0]['name'], 52)} contributed the most, "
             f"at {_pct(moved[0]['earned_in_period'] * 100, 2)} of the project."))

    if moved:
        deck.bars(
            "The biggest movers",
            [{"label": f"{row['wbs']}  {_short(row['name'], 34)}",
              "value": row["earned_in_period"] * 100,
              "shown": _pct(row["earned_in_period"] * 100, 2), "colour": DEEP}
             for row in moved[:7]],
            caption="share of the whole project gained",
            note=(f"{_many(len(moved), 'deliverable')} advanced in the period"
                  + ("; the seven largest are drawn." if len(moved) > 7 else ".")))

    # The table only earns a slide when there is more than the bars already
    # show; four lines drawn and then the same four listed is a slide nobody
    # needed.
    if len(moved) > 4:
        deck.table(
            "What moved, in full",
            ["WBS", "Deliverable", "From", "To", "Project %"],
            [[row["wbs"], _short(row["name"], 64),
              _whole(row["actual_start"]), _whole(row["actual_end"]),
              _pct(row["earned_in_period"] * 100, 2)] for row in moved[:11]],
            widths=[1, 7, 1.1, 1.1, 1.5], right_from=2)

    trades = [row for row in report["trade_earned_in_period"]
              if row["earned_in_period"] > 1e-9]
    if trades:
        deck.bars(
            "Where the progress came from",
            [{"label": row["name"], "value": row["earned_in_period"] * 100,
              "shown": _pct(row["earned_in_period"] * 100, 2), "colour": TEAL}
             for row in sorted(trades, key=lambda r: -r["earned_in_period"])],
            caption="by trade",
            note="Each trade's share of the progress gained in the period.")

    closed = report.get("items_closed") or []
    raised = report.get("items_raised") or []
    if closed or raised:
        deck.figures("What moved in the minutes", [
            {"label": "Actions closed", "value": str(len(closed)),
             "hint": "settled in the period", "colour": GOOD},
            {"label": "Actions raised", "value": str(len(raised)),
             "hint": "picked up in the period", "colour": TEAL},
            {"label": "Still open", "value": str(len(report.get("items_open_at_end") or [])),
             "hint": f"at {to_display(end)}"},
            {"label": "Overdue", "value": str(len(report.get("items_overdue_at_end") or [])),
             "hint": "open and past their date",
             "colour": BAD if report.get("items_overdue_at_end") else GOOD},
        ], note=("; ".join(f"{i['ref']} {str(i['subject'])[:40]}" for i in closed[:3])
                 + (" — closed in this period." if closed else "")) if closed else "")

    # --- 03 · what needs attention ------------------------------------------
    late = sorted((row for row in plan["tasks"] if row.get("is_late")),
                  key=lambda row: -int(row.get("days_late") or 0))
    issued = [row for row in plan["tasks"] if row.get("with_client")]
    deck.divider(3, "What needs attention",
                 "A deck that only carries good news is one nobody believes twice")

    deck.figures("The exceptions", [
        {"label": "Late", "value": str(len(late)), "hint": "past their date",
         "colour": BAD if late else GOOD},
        {"label": "Behind plan", "value": str(totals["behind_count"]),
         "hint": "under the plan",
         "colour": WARN if totals["behind_count"] else GOOD},
        {"label": "With the client", "value": str(totals.get("with_client_count") or 0),
         "hint": "awaiting Code A", "colour": TEAL},
        {"label": "In rework", "value": str(totals["rework_count"]),
         "hint": "returned Code B or C",
         "colour": WARN if totals["rework_count"] else GOOD},
    ], note=("Nothing is overdue and nothing is in rework." if not late
             and not totals["rework_count"] else
             f"{_pct(totals['weight_at_risk'] * 100, 1)} of the project's weight is "
             f"on a line that is past its date."))

    if late:
        deck.bars(
            "Late, and by how much",
            [{"label": f"{row['wbs']}  {_short(row['name'], 34)}",
              "value": int(row.get("days_late") or 0),
              "shown": f"{row.get('days_late')}d", "colour": BAD} for row in late[:7]],
            caption="days past the date",
            note=(f"{_many(len(late), 'deliverable')} "
                  f"{'is' if len(late) == 1 else 'are'} past its date"
                  + ("; the seven furthest behind are drawn." if len(late) > 7 else ".")))

    if issued:
        deck.table(
            "With the client",
            ["WBS", "Deliverable", "Issued", "Days with them", "Code A due"],
            [[row["wbs"], _short(row["name"], 58),
              to_display(row.get("submission_date")),
              f"{row.get('waiting_days') or 0}d",
              to_display(row.get("approval_due_date"))] for row in issued[:11]],
            widths=[1, 6.4, 1.5, 1.5, 1.5], right_from=2,
            note="The work is issued; these are waiting on the client's review.")

    chain = plan["chain"][:9]
    if chain:
        deck.timeline(
            "The critical path",
            [{"label": f"{row['wbs']}  {_short(row['name'], 38)}",
              "from": row.get("start_date"), "to": row.get("submission_date"),
              "colour": BAD if row.get("is_late") else DEEP} for row in chain],
            first=min(str(row.get("start_date") or "") for row in chain),
            last=max(str(row.get("submission_date") or "") for row in chain),
            shown=(to_display(min(str(row.get("start_date") or "") for row in chain)),
                   to_display(max(str(row.get("submission_date") or "") for row in chain))),
            marks=[{"on": stamp, "label": "today", "colour": WARN}],
            caption=f"{len(plan['chain'])} lines in the run",
            note=("A day lost anywhere on this run is a day lost off the end of the "
                  "project."))

    # --- what happens next --------------------------------------------------
    first_day = weeks.first_working_day(plan["calendars"][None].week)
    week_start, week_end = weeks.week_window(stamp, first_day)
    targets = {row["id"]: row["planned_pct"]
               for row in project_snapshot(project, week_end)["tasks"]}
    ahead = weeks.compile_week(plan["tasks"],
                              load_items(project["id"], stamp, kind="client"),
                              load_items(project["id"], stamp, kind="internal"),
                              week_start, week_end, targets)
    deck.divider(4, "What happens next",
                 f"The week of {to_display(week_start)} to {to_display(week_end)}")

    deck.bullets(
        "The coming week",
        [f"{row['ref']} — {_short(row['title'], 68)}"
         + (f"  ·  wanted {to_display(row['due'])}" if row["due"] else "")
         for row in ahead[:7]],
        caption=f"{len(ahead)} things wanted")

    open_items = [item for item in load_items(project["id"], stamp, kind="client")
                  if item["is_open"]]
    if open_items:
        deck.table(
            "Open with the client",
            ["Item", "Subject", "Owner", "Due"],
            [[item["ref"], _short(item["subject"], 62), item["owner_label"] or "—",
              to_display(item["due_date"]) or "—"]
             for item in sorted(open_items,
                                key=lambda i: str(i.get("due_date") or "9999"))[:11]],
            widths=[1, 6, 1.4, 1.6], right_from=2,
            note=f"{_many(len(open_items), 'item')} still open in the client register.")

    # --- the closing --------------------------------------------------------
    deck.closing(
        ("Ahead of plan." if not behind else
         f"{_pct(abs(overview['variance']) * 100, 2)} behind plan.")
        + (f"\n{_many(len(late), 'deliverable')} past "
           f"{'its' if len(late) == 1 else 'their'} date."
           if late else "\nNothing is overdue."),
        [f"Earned  {_whole(overview['earned'])}",
         f"Planned  {_whole(overview['planned'])}",
         f"Float  {overview['float_days']} days",
         f"Finishes  {to_display(overview['finish'])}"],
        note=f"{code} · {name} · prepared {to_display(stamp)}")

    return deck.save(title or f"{code} progress {to_display(start)} to {to_display(end)}")
