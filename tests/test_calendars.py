"""Working weeks and holidays: which days a team is actually in, and what that
does to a duration, a dependency and the planned curve."""

from __future__ import annotations

import pytest

from app.calendars import (
    EVERY_DAY, ROUND_THE_CLOCK, WEEK_PATTERNS, Calendar, normalise_week,
    parse_days, week_days, week_label, working_days,
)

CAIRO = "1111001"        # Sunday to Thursday
BEIRUT = "1111100"       # Monday to Friday


def text(response) -> str:
    return response.get_data(as_text=True)


def unlocked(client):
    """The Setup sheet takes nothing until it is unlocked."""
    client.post("/projects/1/setup/unlock", data={"password": "2026"})
    return client


# --- reading a working week -------------------------------------------------

def test_the_two_weeks_this_was_built_for():
    assert week_label(BEIRUT) == "Monday to Friday"
    assert week_label(CAIRO) == "Sunday to Thursday"


def test_sunday_to_thursday_really_is_sunday_to_thursday():
    """Monday is day 0, so the week that reads oddly on paper is the one to pin."""
    team = Calendar("Cairo", CAIRO)
    assert team.works_on("2026-01-04") is True        # Sunday
    assert team.works_on("2026-01-08") is True        # Thursday
    assert team.works_on("2026-01-09") is False       # Friday
    assert team.works_on("2026-01-10") is False       # Saturday


def test_monday_to_friday_is_off_at_the_weekend():
    team = Calendar("Beirut", BEIRUT)
    assert team.works_on("2026-01-09") is True        # Friday
    assert team.works_on("2026-01-10") is False       # Saturday
    assert team.works_on("2026-01-11") is False       # Sunday


def test_a_week_nobody_could_read_falls_back_to_every_day():
    """A bad value must never quietly shorten a programme."""
    assert normalise_week("nonsense") == EVERY_DAY
    assert normalise_week("0000000") == EVERY_DAY
    assert normalise_week(None) == EVERY_DAY
    assert normalise_week("") == EVERY_DAY


def test_an_unnamed_week_is_said_day_by_day():
    assert week_label("1010100") == "Mon, Wed, Fri"


def test_a_week_can_be_built_from_the_days_that_were_ticked():
    assert parse_days(["0", "1", "2", "3", "4"]) == BEIRUT
    assert parse_days([6, 0, 1, 2, 3]) == CAIRO
    assert parse_days([]) == EVERY_DAY               # nothing ticked changes nothing


def test_the_named_weeks_on_offer():
    assert [key for key, _ in WEEK_PATTERNS] == [BEIRUT, CAIRO, "1111110", EVERY_DAY]


def test_the_days_come_back_ready_to_draw_a_chooser():
    days = week_days(CAIRO)
    assert [d["short"] for d in days] == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    assert [d["worked"] for d in days] == [True, True, True, True, False, False, True]
    assert working_days(BEIRUT) == (0, 1, 2, 3, 4)


# --- holidays ---------------------------------------------------------------

def test_a_holiday_is_a_day_off_even_in_the_working_week():
    team = Calendar("Cairo", CAIRO, ["2026-01-06"])
    assert team.works_on("2026-01-05") is True
    assert team.works_on("2026-01-06") is False
    assert team.why_off("2026-01-06") == "holiday"
    assert team.why_off("2026-01-09") == "weekend"
    assert team.why_off("2026-01-05") == ""


def test_the_same_holiday_twice_costs_nothing():
    team = Calendar("Cairo", CAIRO, ["2026-01-06", "2026-01-06"])
    assert team.holidays == {"2026-01-06"}


def test_only_the_holidays_are_news_a_weekend_is_expected():
    team = Calendar("Beirut", BEIRUT, ["2026-01-07"])
    off = team.days_off("2026-01-05", "2026-01-11")
    assert len(off) == 3                              # Wed holiday, Sat, Sun
    assert [d.isoformat() for d in team.holidays_between("2026-01-05", "2026-01-11")] \
        == ["2026-01-07"]


# --- moving a date onto a working day ---------------------------------------

def test_a_start_on_a_day_off_moves_to_the_next_day_the_team_is_in():
    team = Calendar("Beirut", BEIRUT)
    assert team.next_working("2026-01-10").isoformat() == "2026-01-12"   # Sat -> Mon
    assert team.next_working("2026-01-12").isoformat() == "2026-01-12"   # already fine


def test_a_start_on_a_holiday_moves_past_it():
    team = Calendar("Cairo", CAIRO, ["2026-01-05", "2026-01-06"])
    assert team.next_working("2026-01-05").isoformat() == "2026-01-07"


def test_walking_backwards_finds_the_last_day_worked():
    team = Calendar("Beirut", BEIRUT)
    assert team.last_working("2026-01-11").isoformat() == "2026-01-09"   # Sun -> Fri


def test_a_calendar_with_no_working_days_cannot_hang_the_app():
    """normalise_week refuses one, which is the guard that matters."""
    team = Calendar("Nobody", "0000000")
    assert team.week == EVERY_DAY
    assert team.next_working("2026-01-10") is not None


# --- counting ---------------------------------------------------------------

def test_a_duration_counts_working_days_only():
    team = Calendar("Beirut", BEIRUT)
    assert team.duration("2026-01-05", "2026-01-09") == 5      # Mon to Fri
    assert team.duration("2026-01-05", "2026-01-11") == 5      # the weekend adds nothing


def test_a_duration_of_one_day_starts_and_finishes_the_same_day():
    team = Calendar("Beirut", BEIRUT)
    assert team.finish_after("2026-01-05", 1).isoformat() == "2026-01-05"


def test_a_week_of_work_crosses_the_weekend():
    team = Calendar("Beirut", BEIRUT)
    assert team.finish_after("2026-01-08", 5).isoformat() == "2026-01-14"


def test_a_holiday_in_the_middle_pushes_the_finish_out():
    plain = Calendar("Beirut", BEIRUT)
    with_eid = Calendar("Beirut", BEIRUT, ["2026-01-07"])
    assert plain.finish_after("2026-01-05", 5).isoformat() == "2026-01-09"
    assert with_eid.finish_after("2026-01-05", 5).isoformat() == "2026-01-12"


def test_the_two_teams_finish_the_same_work_on_different_days():
    """The whole point of having two: five days from the same Monday."""
    cairo = Calendar("Cairo", CAIRO)
    beirut = Calendar("Beirut", BEIRUT)
    assert cairo.finish_after("2026-01-05", 5).isoformat() == "2026-01-11"   # skips Fri, Sat
    assert beirut.finish_after("2026-01-05", 5).isoformat() == "2026-01-09"


def test_counting_backwards_for_a_step_planned_before_a_submission():
    team = Calendar("Beirut", BEIRUT)
    assert team.add("2026-01-12", -5).isoformat() == "2026-01-05"


def test_the_round_the_clock_calendar_changes_nothing():
    assert ROUND_THE_CLOCK.duration("2026-01-05", "2026-01-11") == 7
    assert ROUND_THE_CLOCK.finish_after("2026-01-05", 7).isoformat() == "2026-01-11"
    assert ROUND_THE_CLOCK.works_on("2026-01-10") is True


# --- what it does to the plan -----------------------------------------------

def test_a_duration_on_the_schedule_is_in_working_days():
    from app.schedule import duration_between, finish_from

    team = Calendar("Beirut", BEIRUT)
    assert finish_from("2026-01-05", 5) == "2026-01-09"              # no calendar: as before
    assert finish_from("2026-01-05", 5, team) == "2026-01-09"
    assert finish_from("2026-01-08", 5, team) == "2026-01-14"
    assert duration_between("2026-01-05", "2026-01-11", team) == 5


def test_a_link_waits_the_lag_in_working_days():
    from app.schedule import analyse

    tasks = [{"id": 1, "wbs": "1.1", "start_date": "2026-01-05", "submission_date": "2026-01-09"},
             {"id": 2, "wbs": "1.2", "start_date": "2026-01-05", "submission_date": "2026-01-06"}]
    links = [{"predecessor_id": 1, "successor_id": 2, "kind": "FS", "lag_days": 0}]
    team = Calendar("Beirut", BEIRUT)

    plain = analyse(tasks, links)
    worked = analyse(tasks, links, {None: team})
    assert plain[2]["early_start"] == "2026-01-10"        # the Saturday
    assert worked[2]["early_start"] == "2026-01-12"       # the Monday after


def test_a_line_can_keep_its_own_team_while_the_rest_follow_the_default():
    from app.schedule import analyse

    tasks = [{"id": 1, "wbs": "1.1", "start_date": "2026-01-05", "submission_date": "2026-01-08",
              "calendar_id": 7},
             {"id": 2, "wbs": "1.2", "start_date": "2026-01-05", "submission_date": "2026-01-05"}]
    links = [{"predecessor_id": 1, "successor_id": 2, "kind": "FS", "lag_days": 1}]
    diaries = {None: Calendar("Beirut", BEIRUT), 7: Calendar("Cairo", CAIRO)}
    rows = analyse(tasks, links, diaries)
    # 1.2 follows the default Monday-to-Friday team: Thursday finish, plus one
    # working day of lag, is the following Monday.
    assert rows[2]["early_start"] == "2026-01-12"


def test_planned_progress_does_not_tick_over_a_weekend_the_team_is_not_working():
    """The complaint this was built for: a line reading as behind on a Monday
    because the plan moved on over a Saturday nobody worked."""
    from app.calc import planned_pct_on

    line = {"start_date": "2026-01-05", "submission_date": "2026-01-16", "tracking": "simple"}
    team = Calendar("Beirut", BEIRUT)
    friday = planned_pct_on(line, "2026-01-09", calendar=team)
    monday = planned_pct_on(line, "2026-01-12", calendar=team)
    assert planned_pct_on(line, "2026-01-10", calendar=team) == friday   # Saturday
    assert planned_pct_on(line, "2026-01-11", calendar=team) == friday   # Sunday
    assert monday > friday                                               # and then it moves


def test_a_workflow_step_is_not_planned_for_a_day_off():
    from app.workflow import planned_date

    step = {"key": "idc", "anchor": "submission", "offset_days": -7}
    team = Calendar("Beirut", BEIRUT)
    plain = planned_date(step, "2026-01-01", "2026-01-16")
    worked = planned_date(step, "2026-01-01", "2026-01-16", team)
    assert plain == "2026-01-09"
    assert worked == "2026-01-07"                    # seven working days back
    assert Calendar("Beirut", BEIRUT).works_on(worked)


# --- through the app --------------------------------------------------------

def test_a_project_starts_with_one_round_the_clock_team(signed_in):
    from app.service import load_calendars

    with signed_in.application.app_context():
        teams = load_calendars(1)
    assert len(teams) == 1
    assert teams[0]["workdays"] == EVERY_DAY
    assert teams[0]["week_label"] == "Every day"


def test_nothing_moves_until_a_team_keeps_a_shorter_week(signed_in):
    """The safety this rests on: an existing programme is untouched by the
    arrival of calendars."""
    before = text(signed_in.get("/projects/1/schedule"))
    assert "31/08/2026" in before


def test_the_setup_sheet_offers_teams_and_holidays(signed_in):
    body = text(signed_in.get("/projects/1/setup"))
    assert "Teams and their working days" in body
    # The forms that change them appear once the sheet is unlocked.
    body = text(unlocked(signed_in).get("/projects/1/setup"))
    assert "Monday to Friday" in body and "Sunday to Thursday" in body
    assert "Add team" in body and "Add holiday" in body


def test_a_team_is_added_with_its_working_week(signed_in):
    from app.service import load_calendars

    unlocked(signed_in).post("/projects/1/setup/teams",
                             data={"name": "Cairo", "workdays": CAIRO}, follow_redirects=True)
    with signed_in.application.app_context():
        teams = load_calendars(1)
    assert [t["name"] for t in teams] == ["Every day", "Cairo"]
    assert teams[1]["week_label"] == "Sunday to Thursday"


def test_a_holiday_belongs_to_one_team_or_to_everybody(signed_in):
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Cairo", "workdays": CAIRO})
    with signed_in.application.app_context():
        cairo = load_calendars(1)[1]["id"]

    signed_in.post("/projects/1/setup/holidays",
                   data={"calendar_id": "", "holiday_date": "25/12/2026", "name": "Christmas"})
    signed_in.post("/projects/1/setup/holidays",
                   data={"calendar_id": str(cairo), "holiday_date": "20/03/2026", "name": "Eid"})

    with signed_in.application.app_context():
        teams = load_calendars(1)
    everyone = [h["holiday_date"] for h in teams[0]["holidays"]]
    theirs = [h["holiday_date"] for h in teams[1]["holidays"]]
    assert everyone == ["2026-12-25"]
    assert theirs == ["2026-03-20", "2026-12-25"]     # its own, and everybody's


def test_the_same_holiday_is_not_added_twice(signed_in):
    unlocked(signed_in)
    signed_in.post("/projects/1/setup/holidays", data={"holiday_date": "25/12/2026", "name": "X"})
    again = signed_in.post("/projects/1/setup/holidays",
                           data={"holiday_date": "25/12/2026", "name": "X"}, follow_redirects=True)
    assert "already a holiday" in text(again)


def test_a_date_that_is_not_a_date_is_refused(signed_in):
    answer = unlocked(signed_in).post("/projects/1/setup/holidays",
                                      data={"holiday_date": "the fifth of never"},
                                      follow_redirects=True)
    assert "not a date" in text(answer)


def test_the_last_team_is_never_removed(signed_in):
    from app.service import load_calendars

    unlocked(signed_in)
    with signed_in.application.app_context():
        only = load_calendars(1)[0]["id"]
    answer = signed_in.post("/projects/1/setup/remove",
                            data={"target": f"calendar:{only}"}, follow_redirects=True)
    assert "keeps at least one team" in text(answer)


def test_the_default_team_is_not_removed_out_from_under_the_project(signed_in):
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Cairo", "workdays": CAIRO})
    with signed_in.application.app_context():
        default = load_calendars(1)[0]["id"]
    answer = signed_in.post("/projects/1/setup/remove",
                            data={"target": f"calendar:{default}"}, follow_redirects=True)
    assert "default team" in text(answer)


def test_removing_a_team_hands_its_deliverables_back_to_the_default(signed_in):
    from app.db import execute, query_one
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Cairo", "workdays": CAIRO})
    with signed_in.application.app_context():
        cairo = load_calendars(1)[1]["id"]
        execute("UPDATE tasks SET calendar_id = ? WHERE id = 1", (cairo,))

    signed_in.post("/projects/1/setup/remove", data={"target": f"calendar:{cairo}"})
    with signed_in.application.app_context():
        assert query_one("SELECT calendar_id FROM tasks WHERE id = 1")["calendar_id"] is None


def test_the_default_team_can_be_changed(signed_in):
    from app.db import query_one
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Cairo", "workdays": CAIRO})
    with signed_in.application.app_context():
        cairo = load_calendars(1)[1]["id"]
    signed_in.post("/projects/1/setup/teams/default", data={"calendar_id": str(cairo)})
    with signed_in.application.app_context():
        assert query_one("SELECT calendar_id FROM projects WHERE id = 1")["calendar_id"] == cairo


def test_a_deliverable_is_put_on_a_team_from_the_setup_sheet(signed_in):
    from app.db import query_one
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Cairo", "workdays": CAIRO})
    with signed_in.application.app_context():
        cairo = load_calendars(1)[1]["id"]
        task = query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY id LIMIT 1")

    signed_in.post("/projects/1/setup/save-all", data={
        "code": "SIBLINE-PORT", "name": "Sibline Port",
        f"task_{task['id']}_name": task["name"],
        f"task_{task['id']}_calendar": str(cairo),
    })
    with signed_in.application.app_context():
        assert query_one("SELECT calendar_id FROM tasks WHERE id = ?",
                         (task["id"],))["calendar_id"] == cairo


def test_a_team_s_working_days_are_saved_with_the_rest_of_the_sheet(signed_in):
    from app.service import load_calendars

    unlocked(signed_in)
    with signed_in.application.app_context():
        team = load_calendars(1)[0]["id"]

    signed_in.post("/projects/1/setup/save-all", data={
        "code": "SIBLINE-PORT", "name": "Sibline Port",
        f"calendar_{team}_name": "Beirut",
        f"calendar_{team}_days": ["0", "1", "2", "3", "4"],
    })
    with signed_in.application.app_context():
        saved = load_calendars(1)[0]
    assert saved["name"] == "Beirut"
    assert saved["workdays"] == BEIRUT


def test_a_deliverable_on_a_shorter_week_is_replanned_when_its_dates_are_saved(signed_in):
    """The proof that a team is not decoration: the same duration lands on a
    different day once the weekend stops counting."""
    from app.db import execute, query_one
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Beirut", "workdays": BEIRUT})
    with signed_in.application.app_context():
        beirut = load_calendars(1)[1]["id"]
        execute("UPDATE tasks SET calendar_id = ? WHERE id = 1", (beirut,))

    signed_in.post("/projects/1/schedule/1",
                   data={"start_date": "05/01/2026", "duration_days": "5", "mode": "duration"})
    with signed_in.application.app_context():
        row = query_one("SELECT start_date, submission_date FROM tasks WHERE id = 1")
    assert row["start_date"] == "2026-01-05"
    assert row["submission_date"] == "2026-01-09"     # Mon to Fri, not Mon to Fri+2


def test_a_start_landing_on_a_day_off_is_shifted(signed_in):
    from app.db import execute, query_one
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Beirut", "workdays": BEIRUT})
    with signed_in.application.app_context():
        beirut = load_calendars(1)[1]["id"]
        execute("UPDATE tasks SET calendar_id = ? WHERE id = 1", (beirut,))

    signed_in.post("/projects/1/schedule/1",
                   data={"start_date": "10/01/2026", "duration_days": "3", "mode": "duration"})
    with signed_in.application.app_context():
        row = query_one("SELECT start_date FROM tasks WHERE id = 1")
    assert row["start_date"] == "2026-01-12", "a Saturday start should move to the Monday"


@pytest.mark.parametrize("role_path", ["/projects/1/setup/teams",
                                       "/projects/1/setup/holidays",
                                       "/projects/1/setup/teams/default"])
def test_the_setup_lock_covers_the_calendars_too(signed_in, role_path):
    """Locked, the sheet takes nothing — teams and holidays included."""
    before = text(signed_in.get("/projects/1/setup"))
    signed_in.post(role_path, data={"name": "Sneaky", "workdays": CAIRO,
                                    "holiday_date": "01/01/2027", "calendar_id": "1"})
    assert "Sneaky" not in text(signed_in.get("/projects/1/setup"))
    assert before.count("calendar_") == text(signed_in.get("/projects/1/setup")).count("calendar_")


# --- holidays in the week before a submission -------------------------------

def flagged(client):
    from app.db import query_one
    from app.service import project_plan

    with client.application.app_context():
        plan = project_plan(dict(query_one("SELECT * FROM projects WHERE id = 1")))
    return [t for t in plan["tasks"] if t["run_up"]["count"]]


def test_a_holiday_in_the_week_before_a_submission_is_flagged(signed_in):
    """The week a package is pulled together is the one a holiday costs."""
    from app.db import query_one

    with signed_in.application.app_context():
        due = query_one("SELECT submission_date FROM tasks WHERE id = 1")["submission_date"]

    from datetime import date, timedelta
    two_days_before = (date.fromisoformat(due) - timedelta(days=2)).isoformat()
    unlocked(signed_in).post("/projects/1/setup/holidays",
                             data={"holiday_date": "/".join(reversed(two_days_before.split("-"))),
                                   "name": "Test day"})

    marked = flagged(signed_in)
    assert marked, "a holiday two days before a submission should be flagged"
    assert all(day["everyone"] for row in marked for day in row["run_up"]["days"])


def test_a_holiday_well_clear_of_a_submission_is_not_flagged(signed_in):
    from app.db import query_one

    with signed_in.application.app_context():
        due = query_one("SELECT submission_date FROM tasks WHERE id = 1")["submission_date"]

    from datetime import date, timedelta
    long_before = (date.fromisoformat(due) - timedelta(days=40)).isoformat()
    unlocked(signed_in).post("/projects/1/setup/holidays",
                             data={"holiday_date": "/".join(reversed(long_before.split("-"))),
                                   "name": "Too early to matter"})

    assert not any(t["id"] == 1 for t in flagged(signed_in))


def test_one_team_s_holiday_is_not_reported_as_everybody_s(signed_in):
    from app.db import execute, query_one
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Cairo", "workdays": CAIRO})
    signed_in.post("/projects/1/setup/teams", data={"name": "Beirut", "workdays": BEIRUT})
    with signed_in.application.app_context():
        cairo = load_calendars(1)[1]["id"]
        execute("UPDATE tasks SET calendar_id = ? WHERE id = 1", (cairo,))
        due = query_one("SELECT submission_date FROM tasks WHERE id = 1")["submission_date"]

    from datetime import date, timedelta
    day = (date.fromisoformat(due) - timedelta(days=2)).isoformat()
    signed_in.post("/projects/1/setup/holidays",
                   data={"calendar_id": str(cairo), "name": "Cairo only",
                         "holiday_date": "/".join(reversed(day.split("-")))})

    mine = [t for t in flagged(signed_in) if t["id"] == 1]
    assert mine, "Cairo's own holiday should still be flagged on its line"
    assert mine[0]["run_up"]["everyone"] == 0, "it is not everybody's day off"


def test_the_flag_reaches_the_schedule_and_says_whose_it_is(signed_in):
    from app.db import query_one

    with signed_in.application.app_context():
        due = query_one("SELECT submission_date FROM tasks WHERE id = 1")["submission_date"]
    from datetime import date, timedelta
    day = (date.fromisoformat(due) - timedelta(days=1)).isoformat()
    unlocked(signed_in).post("/projects/1/setup/holidays",
                             data={"holiday_date": "/".join(reversed(day.split("-"))), "name": "X"})

    body = text(signed_in.get("/projects/1/schedule"))
    assert "holiday-flag" in body
    assert "for everyone" in body
    assert "Holidays before a submission" in body      # and the tile counts them


# --- a deliverable, opened from the schedule --------------------------------

def test_a_deliverable_opens_on_its_own_page(signed_in):
    body = text(signed_in.get("/projects/1/schedule/1"))
    assert "Waits for" in body and "Waited on by" in body
    assert "working days" in body
    assert "back to the schedule" in body


def test_the_panel_comes_back_as_markup_when_it_is_asked_for(signed_in):
    answer = signed_in.get("/projects/1/schedule/1",
                           headers={"Accept": "application/json"}).get_json()
    assert answer["ok"]
    assert "panel-head" in answer["panel_html"]
    assert answer["title"].startswith("1.1")


def test_the_panel_lists_what_a_line_waits_for_and_what_waits_on_it(signed_in):
    signed_in.post("/projects/1/schedule/links",
                   data={"successor_id": "2", "predecessor_id": "1"})
    before = text(signed_in.get("/projects/1/schedule/2"))
    after = text(signed_in.get("/projects/1/schedule/1"))
    assert "Nothing — it can start" not in before        # 1.2 now waits for something
    assert "Nothing — it closes a path" not in after     # and 1.1 is waited on


def test_the_schedule_links_each_deliverable_to_its_own_panel(signed_in):
    body = text(signed_in.get("/projects/1/schedule"))
    assert 'class="open-task"' in body
    assert 'id="task-panel"' in body


def test_a_deliverable_from_another_project_is_not_opened(signed_in):
    assert signed_in.get("/projects/1/schedule/99999").status_code == 404


def test_a_link_made_from_the_panel_answers_with_the_plan_redrawn(signed_in):
    answer = signed_in.post("/projects/1/schedule/links",
                            data={"successor_id": "2", "predecessor_id": "1"},
                            headers={"Accept": "application/json"}).get_json()
    assert answer["ok"]
    assert "network_html" in answer
    assert answer["note"] == "Dependency added"


def test_a_link_the_programme_will_not_take_says_so_rather_than_reloading(signed_in):
    answer = signed_in.post("/projects/1/schedule/links",
                            data={"successor_id": "1", "predecessor_id": "1"},
                            headers={"Accept": "application/json"})
    assert answer.status_code == 400
    assert "itself" in answer.get_json()["error"]


def test_the_team_a_line_is_planned_on_is_changed_from_the_schedule(signed_in):
    from app.db import query_one
    from app.service import load_calendars

    unlocked(signed_in)
    signed_in.post("/projects/1/setup/teams", data={"name": "Beirut", "workdays": BEIRUT})
    with signed_in.application.app_context():
        beirut = load_calendars(1)[1]["id"]
        was = query_one("SELECT start_date, submission_date FROM tasks WHERE id = 1")

    answer = signed_in.post("/projects/1/schedule/1/team",
                            data={"calendar_id": str(beirut)},
                            headers={"Accept": "application/json"}).get_json()
    assert answer["ok"]
    assert answer["moved"][0]["team"] == "Beirut"

    with signed_in.application.app_context():
        now = query_one("SELECT start_date, submission_date, calendar_id FROM tasks WHERE id = 1")
    assert now["calendar_id"] == beirut
    # Its dates are kept; what changes is that the duration now reads in the
    # days the team is actually in.
    assert now["submission_date"] == was["submission_date"]
    assert answer["moved"][0]["duration"] < 30


def test_only_a_manager_moves_a_line_between_teams(client, app):
    client.post("/register", data={"name": "Member", "email": "m5@example.com",
                                   "password": "longenough1"})
    with app.app_context():
        from app.db import connect

        conn = connect(app.config["DATABASE"])
        with conn:
            user = conn.execute("SELECT id FROM users WHERE email = 'm5@example.com'").fetchone()
            conn.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, ?, 'member')",
                         (user["id"],))
        conn.close()

    assert client.get("/projects/1/schedule/1").status_code == 200
    assert client.post("/projects/1/schedule/1/team", data={"calendar_id": ""}).status_code == 403


def test_every_deliverable_opens(signed_in):
    """Every branch of the panel is exercised by opening all of them — the
    critical badge among them, which needed an import the panel did not have."""
    from app.db import query

    signed_in.post("/projects/1/schedule/links",
                   data={"successor_id": "2", "predecessor_id": "1"})
    with signed_in.application.app_context():
        ids = [r["id"] for r in query("SELECT id FROM tasks WHERE project_id = 1")]

    broken = [i for i in ids if signed_in.get(f"/projects/1/schedule/{i}").status_code != 200]
    assert not broken, f"these deliverables would not open: {broken}"
