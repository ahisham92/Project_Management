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


def test_the_dashboard_shows_the_expected_figures(signed_in):
    body = text(signed_in.get("/projects/1/?data_date=01/09/2026"))
    assert "0.50%" in body, "earned progress"
    assert "2.03%" in body, "planned progress from the workflow step dates"
    assert "-1.53%" in body, "variance"
    assert "2,640 h" in body, "hour budget"
    for trade in ("Marine", "Geotechnical", "Marine Structures", "Utilities"):
        assert trade in body


def test_dates_read_as_day_month_year(signed_in):
    body = text(signed_in.get("/projects/1/?data_date=01/09/2026"))
    assert "01/09/2026" in body, "the data date reads dd/mm/yyyy"
    assert "2026-09-01" not in body, "no ISO dates leak into the page"
    schedule = text(signed_in.get("/projects/1/schedule?data_date=01/09/2026"))
    assert "31/08/2026" in schedule, "the kick-off submission date"
    assert 'type="date"' not in schedule, "native pickers would follow the machine locale"


def test_a_date_can_also_be_typed_with_dashes_or_a_short_year(signed_in):
    for typed in ("01-09-2026", "1/9/26", "2026-09-01"):
        body = text(signed_in.get(f"/projects/1/?data_date={typed}"))
        assert "0.50%" in body, f"{typed} should be understood"


def test_the_dashboard_draws_both_curve_series(signed_in):
    body = text(signed_in.get("/projects/1/?data_date=2026-09-01"))
    assert body.count("<polyline") >= 2, "planned and earned series"
    assert "Data date" in body


def test_the_schedule_lists_the_late_milestone(signed_in):
    body = text(signed_in.get("/projects/1/schedule?data_date=01/09/2026"))
    assert "Project kick-off meeting" in body
    assert "1 day late" in body


def test_the_schedule_look_ahead_can_be_a_window_or_everything(signed_in):
    window = text(signed_in.get("/projects/1/schedule?data_date=01/09/2026&horizon=30"))
    assert "Due in 30 days" in window

    everything = text(signed_in.get("/projects/1/schedule?data_date=01/09/2026&horizon=all"))
    assert "Due in everything ahead" in everything
    # The all-dates view reaches submissions the 30-day window cannot.
    assert "Structural tender drawings" in everything
    assert "Structural tender drawings" not in window

    custom = text(signed_in.get("/projects/1/schedule?data_date=01/09/2026&horizon=45"))
    assert "Due in 45 days" in custom


def test_the_schedule_shows_each_workflow_date(signed_in):
    body = text(signed_in.get("/projects/1/schedule?data_date=01/09/2026&horizon=all"))
    for heading in (">IDC<", ">Comments<", ">Code A<"):
        assert heading in body, f"missing column {heading}"
    # Submission is a sortable heading, so its text sits inside the sort link.
    assert re.search(r'sort=submission[^>]*>\s*Submission', body), "missing the Submission column"


def test_the_progress_filter_narrows_the_list(signed_in):
    body = text(signed_in.get("/projects/1/tasks?filter=late&data_date=01/09/2026"))
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


def test_setting_a_status_sets_the_percentage_and_keeps_history(signed_in, database):
    task_id = _task_id(database, "2.3")  # Coastal numerical modelling, 4.6 points
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/progress",
        data={"status_key": "comments_addressed", "note": "IDC comments closed", "data_date": "01/09/2026"},
        follow_redirects=True,
    )
    assert "updated to 60%" in text(response)

    conn = connect(database)
    try:
        row = conn.execute("SELECT actual_pct, status_key FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row["actual_pct"] == 0.6
        assert row["status_key"] == "comments_addressed"
        history = conn.execute(
            "SELECT * FROM progress_updates WHERE task_id = ? ORDER BY id DESC", (task_id,)
        ).fetchone()
        assert history["previous_pct"] == 0
        assert history["note"] == "IDC comments closed"
    finally:
        conn.close()

    # 4.6 of 100 weight points at 60% adds 2.76 points of earned progress.
    body = text(signed_in.get("/projects/1/?data_date=01/09/2026"))
    assert "3.26%" in body, "earned progress should rise from 0.50% to 3.26%"


def test_an_unknown_status_is_rejected(signed_in, database):
    task_id = _task_id(database, "2.3")
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/progress", data={"status_key": "made_up"}, follow_redirects=True
    )
    assert "does not exist on this project" in text(response)


def test_a_simple_line_still_takes_a_typed_percentage(signed_in, database):
    task_id = _task_id(database, "1.6")  # the kick-off meeting
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/progress",
        data={"actual_pct": "100", "data_date": "01/09/2026"},
        follow_redirects=True,
    )
    assert "updated to 100%" in text(response)


def test_progress_outside_0_to_100_is_rejected(signed_in, database):
    task_id = _task_id(database, "1.6")
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/progress", data={"actual_pct": "140"}, follow_redirects=True
    )
    assert "between 0% and 100%" in text(response)


# --- revisions -------------------------------------------------------------

def _submit(client, task_id: int, date: str = "01/09/2026"):
    return client.post(
        f"/projects/1/tasks/{task_id}/progress",
        data={"status_key": "submitted", "data_date": date}, follow_redirects=True,
    )


def test_comments_raise_a_revision_and_reschedule(signed_in, database):
    task_id = _task_id(database, "2.3")
    _submit(signed_in, task_id)

    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/comments",
        data={"comments_date": "05/09/2026", "note": "Code B"}, follow_redirects=True,
    )
    body = text(response)
    assert "moved to revision 1" in body
    assert "12/09/2026" in body, "resubmission planned 7 rework days after the comments"

    conn = connect(database)
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        assert row["revision"] == 1
        assert row["status_key"] == "comments_addressed", "back to the step the project nominates"
        assert row["actual_pct"] == 0.6, "progress drops to reflect the rework"
        assert row["submission_date"] == "2026-09-12"

        cycles = conn.execute(
            "SELECT * FROM task_revisions WHERE task_id = ? ORDER BY revision", (task_id,)
        ).fetchall()
        assert [(c["revision"], c["outcome"]) for c in cycles] == [(0, "comments"), (1, "open")]
    finally:
        conn.close()


def test_a_resubmission_date_can_be_given_directly(signed_in, database):
    task_id = _task_id(database, "2.3")
    _submit(signed_in, task_id)
    signed_in.post(
        f"/projects/1/tasks/{task_id}/comments",
        data={"comments_date": "05/09/2026", "new_submission_date": "30/09/2026"}, follow_redirects=True,
    )
    conn = connect(database)
    try:
        assert conn.execute(
            "SELECT submission_date FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()["submission_date"] == "2026-09-30"
    finally:
        conn.close()


def test_comments_need_a_submitted_deliverable(signed_in, database):
    task_id = _task_id(database, "2.3")
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/comments", data={"comments_date": "05/09/2026"}, follow_redirects=True
    )
    assert "has been submitted can receive comments" in text(response)


def test_the_revision_limit_is_enforced(signed_in, database):
    task_id = _task_id(database, "2.3")
    conn = connect(database)
    try:
        with conn:
            conn.execute("UPDATE projects SET max_revisions = 2 WHERE id = 1")
            conn.execute("UPDATE tasks SET revision = 2 WHERE id = ?", (task_id,))
    finally:
        conn.close()

    _submit(signed_in, task_id)
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/comments", data={"comments_date": "05/09/2026"}, follow_redirects=True
    )
    assert "limit of 2 revisions" in text(response)


def test_reaching_code_a_closes_the_cycle(signed_in, database):
    task_id = _task_id(database, "2.3")
    _submit(signed_in, task_id)
    signed_in.post(
        f"/projects/1/tasks/{task_id}/progress",
        data={"status_key": "code_a", "data_date": "20/09/2026"}, follow_redirects=True,
    )
    conn = connect(database)
    try:
        assert conn.execute("SELECT actual_pct FROM tasks WHERE id = ?", (task_id,)).fetchone()["actual_pct"] == 1.0
        cycle = conn.execute("SELECT * FROM task_revisions WHERE task_id = ?", (task_id,)).fetchone()
        assert cycle["outcome"] == "code_a"
        assert cycle["outcome_date"] == "2026-09-20"
    finally:
        conn.close()


def test_the_history_page_shows_the_workflow_and_the_trail(signed_in, database):
    task_id = _task_id(database, "2.3")
    _submit(signed_in, task_id)
    signed_in.post(
        f"/projects/1/tasks/{task_id}/comments",
        data={"comments_date": "05/09/2026", "note": "Code B returned"}, follow_redirects=True,
    )
    body = text(signed_in.get(f"/projects/1/tasks/{task_id}/history"))
    assert "Comments returned" in body
    assert "Code B returned" in body
    assert "IDC provided" in body, "the workflow for the current revision"
    assert "Rev 1" in body


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


# --- the setup lock ---------------------------------------------------------

def unlock(client, password: str = "2026"):
    """The Setup sheet is locked by default; every change needs it opened."""
    return client.post("/projects/1/setup/unlock", data={"password": password}, follow_redirects=True)


def test_the_setup_sheet_starts_locked(signed_in):
    body = text(signed_in.get("/projects/1/setup"))
    assert "Locked" in body
    assert "Unlock" in body


def test_the_lock_refuses_a_wrong_password(signed_in):
    assert "Incorrect setup password" in text(unlock(signed_in, "0000"))
    assert "Locked" in text(signed_in.get("/projects/1/setup"))


def test_the_lock_opens_with_2026(signed_in):
    assert "Setup sheet unlocked" in text(unlock(signed_in))
    assert "Unlocked" in text(signed_in.get("/projects/1/setup"))


def test_changes_are_refused_while_locked(signed_in, database):
    response = signed_in.post(
        "/projects/1/settings",
        data={"name": "Renamed while locked", "code": "SIBLINE-PORT"},
        follow_redirects=True,
    )
    assert "setup sheet is locked" in text(response)

    conn = connect(database)
    try:
        assert conn.execute("SELECT name FROM projects WHERE id = 1").fetchone()["name"] != "Renamed while locked"
    finally:
        conn.close()


def test_the_sheet_can_be_locked_again(signed_in):
    unlock(signed_in)
    response = signed_in.post("/projects/1/setup/unlock", data={"action": "lock"}, follow_redirects=True)
    assert "Setup sheet locked" in text(response)
    assert "setup sheet is locked" in text(
        signed_in.post("/projects/1/settings", data={"name": "X", "code": "SIBLINE-PORT"}, follow_redirects=True)
    )


def test_the_setup_password_can_be_changed(signed_in):
    unlock(signed_in)
    response = signed_in.post(
        "/projects/1/setup/password", data={"current": "2026", "new": "port2027"}, follow_redirects=True
    )
    assert "Setup password changed" in text(response)

    signed_in.post("/projects/1/setup/unlock", data={"action": "lock"})
    assert "Incorrect setup password" in text(unlock(signed_in, "2026"))
    assert "Setup sheet unlocked" in text(unlock(signed_in, "port2027"))


# --- setup -----------------------------------------------------------------

def test_a_trade_split_must_total_100_percent(signed_in, database):
    unlock(signed_in)
    task_id = _task_id(database, "1.1")
    response = signed_in.post(
        f"/projects/1/tasks/{task_id}/edit",
        data={"action": "split", "alloc_1": "50", "alloc_2": "20", "alloc_3": "0", "alloc_4": "0"},
        follow_redirects=True,
    )
    assert "must total 100%" in text(response)


def test_a_valid_trade_split_is_saved(signed_in, database):
    unlock(signed_in)
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
    unlock(signed_in)
    before = text(signed_in.get("/projects/1/setup"))
    assert "100.0 weight points" in before

    signed_in.post(
        "/projects/1/tasks",
        data={"wbs": "9.9", "name": "Extra deliverable", "weight_points": "25",
              "start_date": "01/09/2026", "submission_date": "01/12/2026", "section_id": ""},
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
    unlock(signed_in)
    signed_in.post("/projects/1/members", data={"email": "viewer@example.com", "role": "viewer"})

    assert viewer.get("/projects/1/").status_code == 200
    assert "view-only access" in text(viewer.get("/projects/1/tasks"))

    task_id = _task_id(database, "2.3")
    assert viewer.post(
        f"/projects/1/tasks/{task_id}/progress", data={"status_key": "idc"}
    ).status_code == 403
    assert viewer.post("/projects/1/settings", data={"name": "Hijacked", "code": "X"}).status_code == 403


def test_a_member_can_report_progress_but_not_change_setup(app, signed_in, database):
    member = app.test_client()
    _register(member, "member@example.com")
    unlock(signed_in)
    signed_in.post("/projects/1/members", data={"email": "member@example.com", "role": "member"})

    task_id = _task_id(database, "2.3")
    response = member.post(
        f"/projects/1/tasks/{task_id}/progress", data={"status_key": "idc"}, follow_redirects=True
    )
    assert "updated to 40%" in text(response)
    assert member.post("/projects/1/settings", data={"name": "Hijacked", "code": "X"}).status_code == 403
    assert member.post("/projects/1/delete", data={"confirm": "SIBLINE-PORT"}).status_code == 403


def test_adding_an_unknown_email_to_a_project_is_reported(signed_in):
    unlock(signed_in)
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
    assert 'value="Civil"' in body
    assert 'value="Mechanical"' in body
    budgets = re.findall(r'name="trade_\d+_budget"[^>]*value="([\d.]+)"', body)
    assert budgets[:2] == ["800.0", "400.0"]


def test_a_duplicate_project_code_is_rejected(signed_in):
    response = signed_in.post(
        "/projects/new",
        data={"code": "SIBLINE-PORT", "name": "Clone", "ntp_date": "2026-01-01", "duration_months": "6"},
        follow_redirects=True,
    )
    assert "already exists" in text(response)
