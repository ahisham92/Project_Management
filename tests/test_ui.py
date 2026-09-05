"""Sorting, the Setup sheet's Save all, and the print / PDF output."""

from __future__ import annotations

import re

from app.db import connect

from .test_web import text, unlock


def wbs_order(html: str) -> list[str]:
    """The WBS codes in the order the progress table lists them."""
    return re.findall(r'<td class="tabular small muted nowrap">([\d.]+)</td>', html)


# --- sorting ----------------------------------------------------------------

def test_progress_lists_by_wbs_in_natural_order_by_default(signed_in):
    order = wbs_order(text(signed_in.get("/projects/1/tasks")))
    assert order[:4] == ["1.1", "1.2", "1.3", "1.4"]
    # 1.10 must follow 1.9, not 1.1.
    assert order.index("1.9") < order.index("1.10")


def test_progress_can_be_sorted_by_variance_worst_first(signed_in):
    body = text(signed_in.get("/projects/1/tasks?sort=variance&dir=asc&data_date=01/09/2026"))
    # Sorting by anything but WBS folds the sections into one ranked list.
    assert "All deliverables" in body
    assert wbs_order(body)[0] == "1.6", "the late kick-off is furthest behind plan"


def test_progress_sort_direction_flips(signed_in):
    ascending = wbs_order(text(signed_in.get("/projects/1/tasks?sort=weight&dir=asc")))
    descending = wbs_order(text(signed_in.get("/projects/1/tasks?sort=weight&dir=desc")))
    assert ascending[0] != descending[0]
    assert ascending == descending[::-1] or ascending[0] == descending[-1]


def test_progress_keeps_the_sections_when_sorted_by_wbs(signed_in):
    body = text(signed_in.get("/projects/1/tasks?sort=wbs&dir=asc"))
    assert "Sec. 3.1 Marine Design" in body
    assert "All deliverables" not in body


def test_sorting_survives_a_filter_and_a_search(signed_in):
    body = text(signed_in.get("/projects/1/tasks?filter=behind&sort=weight&dir=desc&data_date=01/09/2026"))
    assert "All deliverables" in body
    assert "sort=weight" in body, "the filter chips carry the sort"


def test_an_unknown_sort_column_falls_back_to_wbs(signed_in):
    body = text(signed_in.get("/projects/1/tasks?sort=nonsense&dir=sideways"))
    assert wbs_order(body)[:2] == ["1.1", "1.2"]


def test_the_schedule_can_be_sorted(signed_in):
    body = text(signed_in.get("/projects/1/schedule?sort=submission&dir=desc&data_date=01/09/2026"))
    dates = re.findall(r'id="submission-\d+"[^>]*>\s*(\d{2}/\d{2}/\d{4})', body)
    assert len(dates) > 5, "the plan lists a finish date per line"
    keys = [(d[6:], d[3:5], d[:2]) for d in dates]
    assert keys == sorted(keys, reverse=True), "latest finish first"


def test_schedule_headings_link_to_a_sort(signed_in):
    body = text(signed_in.get("/projects/1/schedule"))
    assert "sort=submission" in body
    assert "sort=start" in body


# --- Save all ---------------------------------------------------------------

def _save_all_payload(database) -> dict[str, str]:
    """The fields the Setup page submits, as they stand before any edit."""
    conn = connect(database)
    try:
        project = conn.execute("SELECT * FROM projects WHERE id = 1").fetchone()
        payload = {
            "code": project["code"], "name": project["name"], "client": project["client"],
            "description": project["description"], "ntp_date": "31/08/2026",
            "duration_months": str(project["duration_months"]),
            "days_per_month": str(project["days_per_month"]),
            "hours_per_month": str(project["hours_per_month"]),
            "elapsed_day_offset": str(int(project["elapsed_day_offset"])),
            "max_revisions": str(project["max_revisions"]),
            "rework_days": str(project["rework_days"]),
            "revision_reset_step": project["revision_reset_step"],
            "status": project["status"],
        }
        for step in conn.execute("SELECT * FROM workflow_steps WHERE project_id = 1"):
            payload[f"step_{step['id']}_name"] = step["name"]
            payload[f"step_{step['id']}_percent"] = str(round(step["percent"] * 100))
            payload[f"step_{step['id']}_anchor"] = step["anchor"]
            payload[f"step_{step['id']}_offset"] = str(round(step["offset_days"]))
        for trade in conn.execute("SELECT * FROM trades WHERE project_id = 1"):
            payload[f"trade_{trade['id']}_name"] = trade["name"]
            payload[f"trade_{trade['id']}_budget"] = str(trade["budget_hours"])
            payload[f"trade_{trade['id']}_color"] = trade["color"]
        for section in conn.execute("SELECT * FROM sections WHERE project_id = 1"):
            payload[f"section_{section['id']}_code"] = section["code"]
            payload[f"section_{section['id']}_name"] = section["name"]
        for task in conn.execute("SELECT * FROM tasks WHERE project_id = 1"):
            tid = task["id"]
            payload[f"task_{tid}_wbs"] = task["wbs"]
            payload[f"task_{tid}_name"] = task["name"]
            payload[f"task_{tid}_section"] = str(task["section_id"] or "")
            payload[f"task_{tid}_points"] = str(task["weight_points"])
            payload[f"task_{tid}_start_date"] = "01/09/2026"
            payload[f"task_{tid}_submission_date"] = "01/12/2026"
            payload[f"task_{tid}_tracking"] = task["tracking"]
            payload[f"task_{tid}_remarks"] = task["remarks"]
            for allocation in conn.execute(
                "SELECT trade_id, pct FROM task_allocations WHERE task_id = ?", (tid,)
            ):
                payload[f"task_{tid}_alloc_{allocation['trade_id']}"] = str(round(allocation["pct"] * 100))
        return payload
    finally:
        conn.close()


def test_save_all_writes_every_part_of_the_sheet(signed_in, database):
    unlock(signed_in)
    payload = _save_all_payload(database)

    conn = connect(database)
    try:
        first_task = conn.execute("SELECT id FROM tasks WHERE wbs = '1.1'").fetchone()["id"]
        first_trade = conn.execute("SELECT id FROM trades WHERE key = 'marine'").fetchone()["id"]
        idc = conn.execute("SELECT id FROM workflow_steps WHERE key = 'idc'").fetchone()["id"]
        section = conn.execute("SELECT id FROM sections WHERE code = '1.0'").fetchone()["id"]
    finally:
        conn.close()

    payload.update({
        "name": "Sibline Port – Phase 2",
        "max_revisions": "6",
        f"step_{idc}_percent": "45",
        f"step_{idc}_offset": "-8",
        f"trade_{first_trade}_budget": "1200",
        f"section_{section}_name": "Sec. 3.0 Overall Scope",
        f"task_{first_task}_points": "7.5",
        f"task_{first_task}_submission_date": "20/10/2026",
    })

    response = signed_in.post("/projects/1/setup/save-all", data=payload, follow_redirects=True)
    assert "Saved — project settings" in text(response)

    conn = connect(database)
    try:
        project = conn.execute("SELECT * FROM projects WHERE id = 1").fetchone()
        assert project["name"] == "Sibline Port – Phase 2"
        assert project["max_revisions"] == 6
        step = conn.execute("SELECT * FROM workflow_steps WHERE id = ?", (idc,)).fetchone()
        assert step["percent"] == 0.45 and step["offset_days"] == -8
        assert conn.execute("SELECT budget_hours FROM trades WHERE id = ?", (first_trade,)).fetchone()[0] == 1200
        assert conn.execute("SELECT name FROM sections WHERE id = ?", (section,)).fetchone()[0] == "Sec. 3.0 Overall Scope"
        task = conn.execute("SELECT * FROM tasks WHERE id = ?", (first_task,)).fetchone()
        assert task["weight_points"] == 7.5
        assert task["submission_date"] == "2026-10-20"
    finally:
        conn.close()


def test_save_all_re_derives_progress_when_a_step_percentage_moves(signed_in, database):
    unlock(signed_in)
    conn = connect(database)
    try:
        task_id = conn.execute("SELECT id FROM tasks WHERE wbs = '2.3'").fetchone()["id"]
        idc = conn.execute("SELECT id FROM workflow_steps WHERE key = 'idc'").fetchone()["id"]
    finally:
        conn.close()

    signed_in.post(
        f"/projects/1/tasks/{task_id}/progress",
        data={"status_key": "idc", "data_date": "01/09/2026"}, follow_redirects=True,
    )
    payload = _save_all_payload(database)
    payload[f"step_{idc}_percent"] = "45"
    signed_in.post("/projects/1/setup/save-all", data=payload, follow_redirects=True)

    conn = connect(database)
    try:
        assert conn.execute("SELECT actual_pct FROM tasks WHERE id = ?", (task_id,)).fetchone()[0] == 0.45
    finally:
        conn.close()


def test_save_all_refuses_a_split_that_is_not_100_and_writes_nothing(signed_in, database):
    unlock(signed_in)
    payload = _save_all_payload(database)
    conn = connect(database)
    try:
        task_id = conn.execute("SELECT id FROM tasks WHERE wbs = '1.1'").fetchone()["id"]
        trade_id = conn.execute("SELECT id FROM trades WHERE key = 'marine'").fetchone()["id"]
    finally:
        conn.close()

    payload["name"] = "Should not be saved"
    payload[f"task_{task_id}_alloc_{trade_id}"] = "5"      # was 35, so the split now totals 70

    response = signed_in.post("/projects/1/setup/save-all", data=payload, follow_redirects=True)
    assert "totals 70%, not 100%" in text(response)
    assert "Nothing was saved" in text(response)

    conn = connect(database)
    try:
        assert conn.execute("SELECT name FROM projects WHERE id = 1").fetchone()[0] != "Should not be saved"
    finally:
        conn.close()


def test_save_all_is_refused_while_the_sheet_is_locked(signed_in, database):
    payload = _save_all_payload(database)
    payload["name"] = "Renamed while locked"
    response = signed_in.post("/projects/1/setup/save-all", data=payload, follow_redirects=True)
    assert "setup sheet is locked" in text(response)


def test_a_row_can_be_removed_from_the_sheet(signed_in, database):
    unlock(signed_in)
    conn = connect(database)
    try:
        task_id = conn.execute("SELECT id FROM tasks WHERE wbs = '1.1'").fetchone()["id"]
    finally:
        conn.close()

    response = signed_in.post(
        "/projects/1/setup/remove", data={"target": f"task:{task_id}"}, follow_redirects=True
    )
    assert "Deliverable deleted" in text(response)

    conn = connect(database)
    try:
        assert conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is None
    finally:
        conn.close()


def test_removing_something_that_is_not_ours_does_nothing(signed_in):
    unlock(signed_in)
    assert "Nothing to remove" in text(
        signed_in.post("/projects/1/setup/remove", data={"target": "wombat:1"}, follow_redirects=True)
    )


def test_every_trade_is_editable_on_each_deliverable(signed_in, database):
    """The split used to sit in extra columns that scrolled off the right, so
    only the first trade was reachable. It now has its own row per deliverable."""
    unlock(signed_in)
    body = text(signed_in.get("/projects/1/setup"))

    conn = connect(database)
    try:
        trades = conn.execute("SELECT id, name FROM trades WHERE project_id = 1 ORDER BY sort_order").fetchall()
        task_id = conn.execute("SELECT id FROM tasks WHERE wbs = '1.1'").fetchone()["id"]
    finally:
        conn.close()
    assert len(trades) == 4

    for trade in trades:
        assert f'name="task_{task_id}_alloc_{trade["id"]}"' in body, f"{trade['name']} has no input"

    # Each box is labelled with its trade, so they cannot be confused. Take the
    # markup from this deliverable's first field to its last split input.
    start = body.index(f'name="task_{task_id}_wbs"')
    end = body.index(f'name="task_{task_id}_alloc_{trades[-1]["id"]}"')
    window = body[start:end]
    for trade in trades:
        assert trade["name"] in window, f"{trade['name']} is not labelled beside its input"


def test_a_new_trade_appears_on_every_deliverable(signed_in, database):
    unlock(signed_in)
    signed_in.post(
        "/projects/1/trades", data={"name": "Surveying", "budget_hours": "100"}, follow_redirects=True
    )
    body = text(signed_in.get("/projects/1/setup"))

    conn = connect(database)
    try:
        new_trade = conn.execute("SELECT id FROM trades WHERE key = 'surveying'").fetchone()["id"]
        task_ids = [r["id"] for r in conn.execute("SELECT id FROM tasks WHERE project_id = 1 LIMIT 5")]
    finally:
        conn.close()

    for task_id in task_ids:
        assert f'name="task_{task_id}_alloc_{new_trade}"' in body


# --- print / PDF ------------------------------------------------------------

def test_the_report_tabs_offer_a_print_button(signed_in):
    for path in ("tasks", "schedule", "budget", "period"):
        body = text(signed_in.get(f"/projects/1/{path}"))
        assert "data-print" in body, f"/{path} has no print button"
        assert "Print / PDF" in body


def test_a_printed_page_carries_a_report_header(signed_in):
    body = text(signed_in.get("/projects/1/schedule?data_date=01/09/2026"))
    assert 'class="print-only print-header"' in body
    assert "SIBLINE-PORT" in body
    assert "01/09/2026" in body


def test_the_stylesheet_hides_the_chrome_when_printing(app):
    css = app.test_client().get("/static/app.css").get_data(as_text=True)
    assert "@media print" in css
    assert ".topbar, .tabs, .no-print" in css, "navigation and controls are dropped on paper"
    assert "thead { display: table-header-group; }" in css, "long tables repeat their heading"
