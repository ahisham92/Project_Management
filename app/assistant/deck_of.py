"""The deck: what was done between two dates, as slides somebody can present.

Built from the same period report the Period tab draws, so the presentation and
the screen can never say different things. What goes on it is what a project
manager would put on it themselves — where the project stands, what actually
moved, what is late, and what the coming weeks want — in that order, because
that is the order a client asks.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..dates import to_display
from ..deck import ACCENT, BAD, GOOD, INK, Deck


def _pct(value: Any, places: int = 2) -> str:
    try:
        return f"{float(value):.{places}f}%"
    except (TypeError, ValueError):
        return "—"


def build(project: Mapping[str, Any], start: str, end: str, title: str = "") -> bytes:
    """The whole deck, as a .pptx."""
    from .. import week as weeks
    from ..service import (as_dict, load_items, project_overview, project_period,
                           project_plan, project_snapshot, today)

    project = as_dict(project)
    code = str(project.get("code") or "")
    name = str(project.get("name") or "Project")
    stamp = today()

    snapshot = project_snapshot(project, stamp)
    overview = project_overview(project, snapshot)
    report = project_period(project, start, end)
    plan = project_plan(project, stamp)

    deck = Deck(footer=f"{code} · {name}")

    # 1. What this is.
    deck.cover(
        title or f"Progress report — {to_display(start)} to {to_display(end)}",
        f"{code} · {name}",
        f"{project.get('client') or 'Client'} · prepared {to_display(stamp)} · "
        f"{report['days_in_period']} days in the period",
    )

    # 2. Where the project stands, before anything about the period.
    behind = overview["variance"] < 0
    deck.figures("Where the project stands", [
        {"label": "Earned", "value": _pct(overview["earned"] * 100),
         "hint": f"against {_pct(overview['planned'] * 100)} planned"},
        {"label": "Variance", "value": _pct(overview["variance"] * 100),
         "hint": "behind plan" if behind else "ahead of plan",
         "colour": BAD if behind else GOOD},
        {"label": "Float", "value": f"{overview['float_days']}d",
         "hint": "against the contract date" if overview["on_time"] else "past the contract date",
         "colour": GOOD if overview["on_time"] else BAD},
        {"label": "Late", "value": str(snapshot["totals"]["late_count"]),
         "hint": "deliverables past their date",
         "colour": BAD if snapshot["totals"]["late_count"] else GOOD},
    ], note=(f"The programme runs {to_display(overview['start'])} to "
             f"{to_display(overview['finish'])}, against a contract date of "
             f"{to_display(overview['contract_end'])}."))

    # 3. What the period itself did — the whole point of the deck.
    gained = report["earned_in_period"] * 100
    deck.figures(f"The period · {to_display(start)} to {to_display(end)}", [
        {"label": "Progress gained", "value": _pct(gained), "hint": "of the whole project",
         "colour": ACCENT},
        {"label": "At the start", "value": _pct(report["earned_at_start"] * 100),
         "hint": "earned progress"},
        {"label": "At the end", "value": _pct(report["earned_at_end"] * 100),
         "hint": "earned progress"},
        {"label": "Lines moved", "value": str(sum(
            1 for row in report["tasks"] if abs(row["delta_actual"]) > 1e-9)),
         "hint": "deliverables that advanced"},
    ])

    # 4. Which lines moved, biggest contribution first — the answer to "what
    #    did you actually do".
    moved = sorted((row for row in report["tasks"] if row["delta_actual"] > 1e-9),
                   key=lambda row: -row["earned_in_period"])
    deck.table(
        "What moved",
        ["WBS", "Deliverable", "From", "To", "Project %"],
        [[row["wbs"], str(row["name"])[:70],
          f"{round(row['actual_start'] * 100)}%", f"{round(row['actual_end'] * 100)}%",
          f"{row['earned_in_period'] * 100:.2f}%"] for row in moved[:12]],
        widths=[1, 7, 1.1, 1.1, 1.5], right_from=2,
        note=(f"{len(moved)} deliverables advanced in the period"
              + (f"; the twelve largest are shown." if len(moved) > 12 else ".")),
    )

    # 5. Where the hours went.
    trades = [row for row in report["trade_earned_in_period"] if row["earned_in_period"] > 1e-9]
    if trades:
        deck.table(
            "By trade",
            ["Trade", "Gained in the period", "Earned to date"],
            [[row["name"], f"{row['earned_in_period'] * 100:.2f}%",
              _pct(next((t["earned_pct_of_trade"] * 100 for t in snapshot["trades"]
                         if t["id"] == row["id"]), 0))]
             for row in sorted(trades, key=lambda r: -r["earned_in_period"])],
            widths=[4, 2, 2], right_from=1)

    # 6. What is not going well. A deck that only carries good news is one
    #    nobody believes twice.
    late = sorted((row for row in plan["tasks"] if row.get("is_late")),
                  key=lambda row: -int(row.get("days_late") or 0))
    deck.table(
        "Behind, and by how much",
        ["WBS", "Deliverable", "Was due", "Days late", "Done"],
        [[row["wbs"], str(row["name"])[:70],
          to_display(row.get("due_date")), f"{row.get('days_late')}d",
          f"{round(float(row.get('actual_pct') or 0) * 100)}%"] for row in late[:12]],
        widths=[1, 7, 1.6, 1.2, 1], right_from=2,
        note="Nothing is overdue." if not late else
             "Each of these is past the date it was due and not yet complete.")

    # 7. The run of work that decides the finish.
    chain = plan["chain"][:10]
    if chain:
        deck.table(
            "The critical path",
            ["WBS", "Deliverable", "Start", "Submission"],
            [[row["wbs"], str(row["name"])[:70], to_display(row.get("start_date")),
              to_display(row.get("submission_date"))] for row in chain],
            widths=[1, 7, 1.6, 1.6], right_from=2,
            note=("A day lost anywhere on this run is a day lost off the end of the "
                  "project." + (f" {len(plan['chain'])} lines in all."
                                if len(plan["chain"]) > 10 else "")))

    # 8. What happens next, so the meeting has somewhere to go.
    first_day = weeks.first_working_day(plan["calendars"][None].week)
    week_start, week_end = weeks.week_window(stamp, first_day)
    targets = {row["id"]: row["planned_pct"]
               for row in project_snapshot(project, week_end)["tasks"]}
    ahead = weeks.compile_week(plan["tasks"],
                              load_items(project["id"], stamp, kind="client"),
                              load_items(project["id"], stamp, kind="internal"),
                              week_start, week_end, targets)
    deck.bullets(
        "Next",
        [f"{row['ref']} — {str(row['title'])[:80]}"
         + (f" (wanted {to_display(row['due'])})" if row["due"] else "")
         for row in ahead[:8]] or ["Nothing falls due in the coming week"],
        note=f"The week of {to_display(week_start)} to {to_display(week_end)}")

    # 9. What is open with the client.
    open_items = [item for item in load_items(project["id"], stamp, kind="client")
                  if item["is_open"]]
    deck.table(
        "Open with the client",
        ["Item", "Subject", "Owner", "Due"],
        [[item["ref"], str(item["subject"])[:70], item["owner_label"] or "—",
          to_display(item["due_date"]) or "—"]
         for item in sorted(open_items, key=lambda i: str(i.get("due_date") or "9999"))[:12]],
        widths=[1, 6, 1.4, 1.6], right_from=2,
        note="Nothing is open in the client register." if not open_items else
             f"{len(open_items)} items still open.")

    return deck.save(title or f"{code} progress {to_display(start)} to {to_display(end)}")
