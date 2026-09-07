"""This week: the compilation, and the page built on it.

The Internal tab opens on what the week wants rather than on a list, and what
the week wants comes from three places at once — the programme, the client's
minutes, and our own list. The rules that decide what belongs there are pure
functions, so they are tested without a database; the page is tested for the
one thing that makes it worth having, which is that changing something on it
changes the record it came from rather than a copy.
"""

from __future__ import annotations

import re

from app import week as weeks


def text(response) -> str:
    return response.get_data(as_text=True)


def task(**extra):
    return dict({
        "id": 1, "wbs": "1.1", "name": "A deliverable", "remarks": "",
        "start_date": "2026-09-07", "submission_date": "2026-09-18",
        "approval_due_date": "2026-09-25", "actual_pct": 0.2, "planned_pct": 0.3,
        "weight_pct": 0.1, "is_complete": False, "is_late": False, "days_late": 0,
        "is_submitted": False, "is_approved": False,
    }, **extra)


def open_item(**extra):
    return dict({
        "id": 1, "ref": "1.1", "subject": "Chase the client", "is_open": True,
        "is_overdue": False, "days_overdue": 0, "due_date": "2026-09-10",
        "raised_date": "2026-09-01", "owner_label": "PM", "agreement": "",
    }, **extra)


# --- which seven days -------------------------------------------------------

def test_the_week_runs_monday_to_sunday_by_default():
    assert weeks.week_window("2026-09-09") == ("2026-09-07", "2026-09-13")
    assert weeks.week_window("2026-09-07") == ("2026-09-07", "2026-09-13")
    assert weeks.week_window("2026-09-13") == ("2026-09-07", "2026-09-13")


def test_a_sunday_to_thursday_team_gets_a_week_that_opens_on_sunday():
    """Showing them a Monday week would cut it in half and call the first day
    of it last week."""
    assert weeks.first_working_day("1111001") == 6
    assert weeks.week_window("2026-09-09", 6) == ("2026-09-06", "2026-09-12")


def test_a_monday_to_friday_week_opens_on_monday():
    assert weeks.first_working_day("1111100") == 0
    assert weeks.first_working_day("1111110") == 0


def test_a_pattern_that_says_nothing_falls_back_to_monday():
    assert weeks.first_working_day("") == 0
    assert weeks.first_working_day("0000000") == 0
    assert weeks.first_working_day(None) == 0


def test_stepping_a_week_either_way():
    assert weeks.shift("2026-09-07", 1) == "2026-09-14"
    assert weeks.shift("2026-09-07", -1) == "2026-08-31"


# --- what the programme asks for -------------------------------------------

def test_a_submission_this_week_is_a_submission():
    rows = weeks.from_schedule([task(submission_date="2026-09-10")], "2026-09-07", "2026-09-13")
    assert [r["need"] for r in rows] == ["submit"]
    assert rows[0]["due"] == "2026-09-10"


def test_a_line_running_through_the_week_asks_only_for_progress():
    """The half a programme never shows: nothing is due and the days still
    have to go in."""
    running = task(start_date="2026-08-24", submission_date="2026-09-30")
    rows = weeks.from_schedule([running], "2026-09-07", "2026-09-13")
    assert [r["need"] for r in rows] == ["progress"]


def test_a_line_starting_this_week_says_so():
    rows = weeks.from_schedule([task(start_date="2026-09-09")], "2026-09-07", "2026-09-13")
    assert [r["need"] for r in rows] == ["start"]
    assert rows[0]["due"] == "2026-09-09"


def test_an_approval_due_back_this_week_is_its_own_kind_of_wanting():
    rows = weeks.from_schedule(
        [task(submission_date="2026-08-20", approval_due_date="2026-09-09",
              is_submitted=True, start_date="2026-08-01")],
        "2026-09-07", "2026-09-13")
    assert [r["need"] for r in rows] == ["approve"]


def test_one_deliverable_makes_one_row_however_many_dates_fall_in_the_week():
    """Starting on Monday and submitting on Friday is one line of work, and
    five rows for it is a table rather than a week."""
    rows = weeks.from_schedule(
        [task(start_date="2026-09-07", submission_date="2026-09-11")],
        "2026-09-07", "2026-09-13")
    assert len(rows) == 1
    assert rows[0]["need"] == "submit"           # the more pressing of the two


def test_a_finished_line_asks_for_nothing():
    rows = weeks.from_schedule([task(is_complete=True, actual_pct=1.0)],
                               "2026-09-07", "2026-09-13")
    assert rows == []


def test_a_line_nowhere_near_this_week_is_not_in_it():
    rows = weeks.from_schedule(
        [task(start_date="2026-11-01", submission_date="2026-11-20")],
        "2026-09-07", "2026-09-13")
    assert rows == []


def test_something_already_late_comes_whatever_week_it_is():
    rows = weeks.from_schedule(
        [task(start_date="2026-06-01", submission_date="2026-06-10",
              is_late=True, days_late=90)],
        "2026-09-07", "2026-09-13")
    assert rows[0]["state"] == "late"
    assert rows[0]["days_late"] == 90


def test_what_the_week_wants_of_a_line_is_a_number():
    """"Carry on with it" is not something anybody can be held to. A target
    read at the Sunday rather than at today is."""
    rows = weeks.from_schedule([task(actual_pct=0.2)], "2026-09-07", "2026-09-13",
                               targets={1: 0.5})
    assert rows[0]["target_pct"] == 0.5
    assert abs(rows[0]["to_do_pct"] - 0.3) < 1e-9


def test_a_line_already_past_its_target_is_owed_nothing():
    rows = weeks.from_schedule([task(actual_pct=0.8)], "2026-09-07", "2026-09-13",
                               targets={1: 0.5})
    assert rows[0]["to_do_pct"] == 0


# --- what the registers ask for --------------------------------------------

def test_an_action_falling_due_this_week_is_wanted():
    rows = weeks.from_register([open_item()], "2026-09-07", "2026-09-13", "client")
    assert [r["need"] for r in rows] == ["close"]
    assert rows[0]["state"] == "due"
    assert rows[0]["source"] == "client"


def test_an_overdue_action_comes_too():
    rows = weeks.from_register([open_item(due_date="2026-08-01", is_overdue=True, days_overdue=37)],
                               "2026-09-07", "2026-09-13", "internal")
    assert rows[0]["state"] == "late"
    assert rows[0]["days_late"] == 37


def test_an_action_raised_this_week_comes_even_with_no_date_on_it():
    rows = weeks.from_register([open_item(due_date="", raised_date="2026-09-08")],
                               "2026-09-07", "2026-09-13", "internal")
    assert rows[0]["state"] == "open"


def test_a_closed_action_is_not_asked_for_again():
    assert weeks.from_register([open_item(is_open=False)], "2026-09-07", "2026-09-13", "client") == []


def test_an_action_due_long_after_this_week_waits_its_turn():
    assert weeks.from_register([open_item(due_date="2026-12-01")],
                               "2026-09-07", "2026-09-13", "client") == []


# --- putting the three together --------------------------------------------

def test_late_things_come_first_then_by_the_day_they_are_wanted():
    rows = weeks.compile_week(
        [task(id=1, submission_date="2026-09-11"),
         task(id=2, submission_date="2026-06-01", start_date="2026-05-01", is_late=True)],
        [open_item(id=3, due_date="2026-09-08")], [], "2026-09-07", "2026-09-13")
    assert [r["state"] for r in rows] == ["late", "due", "due"]
    assert [r["id"] for r in rows] == [2, 3, 1]


def test_the_groups_read_as_a_week_and_empty_ones_are_dropped():
    rows = weeks.compile_week([task(submission_date="2026-09-11")],
                              [open_item()], [], "2026-09-07", "2026-09-13")
    groups = weeks.group(rows)
    assert [g["need"] for g in groups] == ["submit", "close"]


def test_what_the_week_is_worth_is_weighted_by_the_lines_it_touches():
    """Summing bare percentages would make a 0.1% line count the same as a 9%
    one, which is how a week looks busy and moves nothing."""
    rows = weeks.compile_week(
        [task(id=1, weight_pct=0.10, actual_pct=0.0), task(id=2, weight_pct=0.01, actual_pct=0.0)],
        [], [], "2026-09-07", "2026-09-13", targets={1: 0.5, 2: 1.0})
    totals = weeks.summarise(rows)
    assert abs(totals["worth"] - (0.5 * 0.10 + 1.0 * 0.01)) < 1e-9
    assert totals["behind"] == 2


def test_the_weekly_meetings_reference_is_the_week_itself():
    assert weeks.meeting_ref("2026-09-07") == "WK-2026-37"


# --- the page ---------------------------------------------------------------

def test_the_internal_tab_opens_on_the_week(signed_in):
    body = text(signed_in.get("/projects/1/internal"))
    assert "This week" in body
    assert "Wanted this week" in body
    # And the register is still there, one click away.
    assert "/projects/1/internal/register" in body


def test_the_week_says_where_each_line_came_from(signed_in):
    """The point of the page is that these are gathered from three places."""
    body = text(signed_in.get("/projects/1/internal"))
    assert ">Schedule<" in body


def test_the_week_can_be_stepped_back_and_forward(signed_in):
    body = text(signed_in.get("/projects/1/internal"))
    found = re.search(r'href="/projects/1/internal\?week=([\d/]+)"', body)
    assert found

    other = text(signed_in.get(f"/projects/1/internal?week={found.group(1)}"))
    assert "Back to this week" in other


def test_something_late_follows_you_into_every_week_until_it_is_done(signed_in):
    """A week far past the end of the programme is not an empty week if
    anything is still overdue — that is exactly when it stops being noticed."""
    body = text(signed_in.get("/projects/1/internal?week=01/01/2030"))
    assert "Already late" in body
    assert "not the current week" in body


# --- one copy of everything -------------------------------------------------

def _first_open_task(app):
    from app.service import load_tasks

    with app.app_context():
        return load_tasks(1)[0]["id"]


def test_progress_recorded_on_the_week_shows_on_the_progress_tab(signed_in, app):
    """Not a copy of the deliverable — the deliverable."""
    task_id = _first_open_task(app)
    signed_in.post(f"/projects/1/tasks/{task_id}/progress",
                   data={"actual_pct": "45", "note": "from the week"},
                   headers={"Accept": "application/json"})

    from app.db import query_one

    with app.app_context():
        assert abs(query_one("SELECT actual_pct FROM tasks WHERE id = ?",
                             (task_id,))["actual_pct"] - 0.45) < 1e-9
    assert "45%" in text(signed_in.get("/projects/1/tasks"))


def test_closing_an_action_on_the_week_closes_it_in_the_register(signed_in, app):
    signed_in.post("/projects/1/minutes/items",
                   data={"kind": "internal", "subject": "Send the survey brief",
                         "due_date": "01/01/2020"}, follow_redirects=True)

    from app.service import load_items

    with app.app_context():
        item_id = [i for i in load_items(1, kind="internal")
                   if i["subject"] == "Send the survey brief"][0]["id"]

    # It is overdue, so the week is asking for it.
    assert "Send the survey brief" in text(signed_in.get("/projects/1/internal"))

    answer = signed_in.post(f"/projects/1/minutes/items/{item_id}/status",
                            data={"status": "closed", "return": "week"})
    assert answer.status_code == 302
    assert "/internal" in answer.headers["Location"]

    with app.app_context():
        closed = [i for i in load_items(1, kind="internal") if i["id"] == item_id][0]
    assert closed["is_open"] is False
    assert "Send the survey brief" not in text(signed_in.get("/projects/1/internal"))


def test_something_raised_on_the_week_lands_in_the_internal_register(signed_in, app):
    signed_in.post("/projects/1/minutes/items",
                   data={"kind": "internal", "subject": "Book the survey vessel",
                         "return": "week", "due_date": "01/01/2020"},
                   follow_redirects=True)

    from app.service import load_items

    with app.app_context():
        raised = [i for i in load_items(1, kind="internal")
                  if i["subject"] == "Book the survey vessel"]
    assert len(raised) == 1
    assert "Book the survey vessel" in text(signed_in.get("/projects/1/internal/register?filter=all"))


def test_a_deliverable_and_an_item_can_share_a_number_without_colliding(signed_in, app):
    """A page showing both has a task 5 and an item 5. Without a prefix, saving
    one would rewrite the other's badge."""
    body = text(signed_in.get("/projects/1/internal"))
    assert 'data-rows="t"' in body or "tstatus-" in body


# --- the weekly meeting -----------------------------------------------------

def test_one_button_opens_the_weekly_meeting(signed_in, app):
    answer = signed_in.post("/projects/1/internal/weekly", follow_redirects=True)
    assert answer.status_code == 200

    from app.service import load_meetings

    with app.app_context():
        held = load_meetings(1, "internal")
    assert len(held) == 1
    assert held[0]["ref"].startswith("WK-")


def test_pressing_it_again_opens_the_same_meeting_rather_than_a_second_one(signed_in, app):
    signed_in.post("/projects/1/internal/weekly", follow_redirects=True)
    signed_in.post("/projects/1/internal/weekly", follow_redirects=True)

    from app.service import load_meetings

    with app.app_context():
        assert len(load_meetings(1, "internal")) == 1


def test_the_week_shows_the_meeting_once_it_is_open(signed_in):
    signed_in.post("/projects/1/internal/weekly", follow_redirects=True)
    body = text(signed_in.get("/projects/1/internal"))
    assert "Open the weekly meeting" in body


def test_each_week_gets_its_own_meeting(signed_in, app):
    signed_in.post("/projects/1/internal/weekly", follow_redirects=True)
    signed_in.post("/projects/1/internal/weekly", data={"week": "01/01/2030"},
                   follow_redirects=True)

    from app.service import load_meetings

    with app.app_context():
        assert len(load_meetings(1, "internal")) == 2


def test_a_line_with_the_client_is_never_asked_for_work():
    """It is issued. There is nothing to carry on with, so it appears once
    under what is coming back and never under carrying on."""
    from app.week import _task_need

    issued = {"is_complete": False, "with_client": True,
              "start_date": "2026-08-01", "submission_date": "2026-08-20",
              "approval_due_date": "2026-09-03", "is_submitted": True,
              "is_approved": False}

    # The Code A falls in this week: it is coming back.
    assert _task_need(issued, "2026-08-31", "2026-09-06") == "approve"
    # Already past it and still not returned: it stays there until it arrives.
    assert _task_need(issued, "2026-09-07", "2026-09-13") == "approve"
    # Before it is expected back, the week asks nothing of anybody.
    assert _task_need(issued, "2026-08-24", "2026-08-30") == ""
