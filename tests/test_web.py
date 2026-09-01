"""Checks the web layer: sign-in, the pages, updating progress, booking hours
and the per-project permission rules."""

from __future__ import annotations

import re

from app.db import connect


def text(response) -> str:
    return response.get_data(as_text=True)


# --- authentication --------------------------------------------------------

def test_signed_out_visitors_are_sent_to_the_login_page(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_login_rejects_a_wrong_password(client):
    response = client.post("/login", data={"email": "admin@example.com", "password": "nope"}, follow_redirects=True)
    assert "Incorrect email or password" in text(response)


def test_login_accepts_the_seeded_account(client):
    response = client.post(
        "/login", data={"email": "admin@example.com", "password": "changeme123"}, follow_redirects=True
    )
    assert response.status_code == 200
    assert "SIBLINE-PORT" in text(response)


def test_registration_rejects_a_short_password(client):
    response = client.post(
        "/register", data={"email": "new@example.com", "name": "New", "password": "short"}, follow_redirects=True
    )
    assert "at least 8 characters" in text(response)


def test_registration_rejects_a_duplicate_email(client):
    response = client.post(
        "/register",
        data={"email": "admin@example.com", "name": "Copy", "password": "longenough1"},
        follow_redirects=True,
    )
    assert "already exists" in text(response)


def test_logout_ends_the_session(signed_in):
    signed_in.post("/logout")
    assert signed_in.get("/").status_code == 302


# --- pages -----------------------------------------------------------------

def test_every_project_page_renders(signed_in):
    for path in ("", "tasks", "schedule", "budget", "period", "time", "setup"):
        response = signed_in.get(f"/projects/1/{path}")
        assert response.status_code == 200, f"/projects/1/{path} returned {response.status_code}"


def test_the_dashboard_shows_the_workbook_figures(signed_in):
    body = text(signed_in.get("/projects/1/?data_date=2026-09-01"))
    assert "0.50%" in body, "earned progress"
    assert "1.76%" in body, "planned progress"
    assert "-1.26%" in body, "variance"
    assert "2,640 h" in body, "hour budget"
    for trade in ("Marine", "Geotechnical", "Marine Structures", "Utilities"):
        assert trade in body


def test_the_dashboard_draws_both_curve_series(signed_in):
    body = text(signed_in.get("/projects/1/?data_date=2026-09-01"))
    assert body.count("<polyline") >= 2, "planned and earned series"
    assert "Data date" in body


def test_the_schedule_lists_the_late_milestone(signed_in):
    body = text(signed_in.get("/projects/1/schedule?data_date=2026-09-01"))
    assert "Project kick-off meeting" in body
    assert "1 day late" in body


def test_the_progress_filter_narrows_the_list(signed_in):
    body = text(signed_in.get("/projects/1/tasks?filter=late&data_date=2026-09-01"))
    assert "Project kick-off meeting" in body
    assert "Coastal numerical modelling" not in body, "a non-late line should be filtered out"


def test_search_narrows_the_progress_list(signed_in):
    body = text(signed_in.get("/projects/1/tasks?q=dredging"))
    assert "Zone Y" in body
    assert "Project kick-off meeting" not in body


# --- reporting progress ----------------------------------------------------

def _task_id(database: str, wbs: str) -> int:
    conn = connect(database)
    try:
        return conn.execute("SELECT id FROM tasks WHERE wbs = ?", (wbs,)).fetchone()["id"]
    finally:
        conn.close()


def test_recording_progress_updates_the_figures_and_keeps_history(signed_in, database):
    task_id = _task_id(database, "2.3")  # Coastal numerical modelling, 4.6 points
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/progress",
        data={"actual_pct": "50", "note": "Model calibrated", "data_date": "2026-09-01"},
        follow_redirects=True,
    )
    assert "updated to 50%" in text(response)

    conn = connect(database)
    try:
        assert conn.execute("SELECT actual_pct FROM tasks WHERE id = ?", (task_id,)).fetchone()["actual_pct"] == 0.5
        history = conn.execute(
            "SELECT * FROM progress_updates WHERE task_id = ? ORDER BY id DESC", (task_id,)
        ).fetchone()
        assert history["previous_pct"] == 0
        assert history["note"] == "Model calibrated"
    finally:
        conn.close()

    # 4.6 of 100 weight points at 50% adds 2.30 points of earned progress.
    body = text(signed_in.get("/projects/1/?data_date=2026-09-01"))
    assert "2.80%" in body, "earned progress should rise from 0.50% to 2.80%"


def test_progress_outside_0_to_100_is_rejected(signed_in, database):
    task_id = _task_id(database, "2.3")
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/progress", data={"actual_pct": "140"}, follow_redirects=True
    )
    assert "between 0% and 100%" in text(response)


# --- hours -----------------------------------------------------------------

def test_booked_hours_reach_budget_control(signed_in):
    response = signed_in.post(
        "/projects/1/time",
        data={"trade_id": "1", "entry_date": "2026-09-01", "hours": "120", "description": "Data review"},
        follow_redirects=True,
    )
    assert "Booked 120 hours" in text(response)

    body = text(signed_in.get("/projects/1/budget?data_date=2026-09-01"))
    assert "120 h" in body
    assert "Over-burning" in body, "spending ahead of earned progress"


def test_zero_hours_are_rejected(signed_in):
    response = signed_in.post(
        "/projects/1/time", data={"trade_id": "1", "entry_date": "2026-09-01", "hours": "0"}, follow_redirects=True
    )
    assert "Enter the number of hours worked" in text(response)


# --- setup -----------------------------------------------------------------

def test_a_trade_split_must_total_100_percent(signed_in, database):
    task_id = _task_id(database, "1.1")
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/edit",
        data={"action": "split", "alloc_1": "50", "alloc_2": "20", "alloc_3": "0", "alloc_4": "0"},
        follow_redirects=True,
    )
    assert "must total 100%" in text(response)


def test_a_valid_trade_split_is_saved(signed_in, database):
    task_id = _task_id(database, "1.1")
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/edit",
        data={"action": "split", "alloc_1": "40", "alloc_2": "30", "alloc_3": "20", "alloc_4": "10"},
        follow_redirects=True,
    )
    assert "Trade split saved" in text(response)

    conn = connect(database)
    try:
        rows = conn.execute("SELECT pct FROM task_allocations WHERE task_id = ?", (task_id,)).fetchall()
        assert abs(sum(r["pct"] for r in rows) - 1) < 1e-9
    finally:
        conn.close()


def test_adding_a_deliverable_dilutes_the_other_weights(signed_in):
    before = text(signed_in.get("/projects/1/setup"))
    assert "100.0 weight points" in before

    signed_in.post(
        "/projects/1/tasks",
        data={"wbs": "9.9", "name": "Extra deliverable", "weight_points": "25",
              "start_month": "0", "finish_month": "2", "section_id": ""},
        follow_redirects=True,
    )
    after = text(signed_in.get("/projects/1/setup"))
    assert "125.0 weight points" in after
    assert "Extra deliverable" in after


def test_deleting_a_project_requires_the_code(signed_in):
    response = signed_in.post("/projects/1/delete", data={"confirm": "WRONG"}, follow_redirects=True)
    assert "Type the project code to confirm" in text(response)
    assert signed_in.get("/projects/1/").status_code == 200


# --- permissions -----------------------------------------------------------

def _register(client, email: str) -> None:
    client.post("/register", data={"email": email, "name": email.split("@")[0], "password": "longenough1"})


def test_another_user_cannot_see_the_project(app):
    other = app.test_client()
    _register(other, "outsider@example.com")
    assert "SIBLINE-PORT" not in text(other.get("/"))
    # Reported as missing rather than forbidden, so ids are not confirmed.
    assert other.get("/projects/1/").status_code == 404


def test_a_viewer_can_read_but_not_report_progress(app, signed_in, database):
    viewer = app.test_client()
    _register(viewer, "viewer@example.com")
    signed_in.post("/projects/1/members", data={"email": "viewer@example.com", "role": "viewer"})

    assert viewer.get("/projects/1/").status_code == 200
    assert "view-only access" in text(viewer.get("/projects/1/tasks"))

    task_id = _task_id(database, "2.3")
    assert viewer.post(f"/projects/1/tasks/{task_id}/progress", data={"actual_pct": "50"}).status_code == 403
    assert viewer.post("/projects/1/settings", data={"name": "Hijacked", "code": "X"}).status_code == 403


def test_a_member_can_report_progress_but_not_change_setup(app, signed_in, database):
    member = app.test_client()
    _register(member, "member@example.com")
    signed_in.post("/projects/1/members", data={"email": "member@example.com", "role": "member"})

    task_id = _task_id(database, "2.3")
    response = member.post(
        f"/projects/1/tasks/{task_id}/progress", data={"actual_pct": "25"}, follow_redirects=True
    )
    assert "updated to 25%" in text(response)
    assert member.post("/projects/1/settings", data={"name": "Hijacked", "code": "X"}).status_code == 403
    assert member.post("/projects/1/delete", data={"confirm": "SIBLINE-PORT"}).status_code == 403


def test_adding_an_unknown_email_to_a_project_is_reported(signed_in):
    response = signed_in.post(
        "/projects/1/members", data={"email": "nobody@example.com", "role": "member"}, follow_redirects=True
    )
    assert "No account with that email" in text(response)


# --- creating a project ----------------------------------------------------

def test_creating_a_project_with_trades(signed_in):
    response = signed_in.post(
        "/projects/new",
        data={
            "code": "NEW-1", "name": "New Build", "client": "A Client", "description": "",
            "ntp_date": "2026-01-01", "duration_months": "6", "days_per_month": "30.4375",
            "hours_per_month": "176", "elapsed_day_offset": "0",
            "trade_name": ["Civil", "Mechanical", ""], "trade_hours": ["800", "400", ""],
        },
        follow_redirects=True,
    )
    body = text(response)
    assert "Project created" in body
    # The setup page lands with both trades and their hour budgets ready to edit.
    assert 'name="name" value="Civil"' in body
    assert 'name="name" value="Mechanical"' in body
    assert re.findall(r'name="budget_hours"[^>]*value="([\d.]+)"', body)[:2] == ["800.0", "400.0"]


def test_a_duplicate_project_code_is_rejected(signed_in):
    response = signed_in.post(
        "/projects/new",
        data={"code": "SIBLINE-PORT", "name": "Clone", "ntp_date": "2026-01-01", "duration_months": "6"},
        follow_redirects=True,
    )
    assert "already exists" in text(response)
