"""Squeezing a stretch of the programme into fewer days.

The arithmetic is the part worth pinning down, because it is the part somebody
will check by hand against a printout. Three rules: durations come down in
proportion to what they already are, days are whole with the leftover going to
the shorter lines, and waiting between lines is not work so it does not
compress.
"""

from __future__ import annotations

import pytest

from app.schedule import duration_between
from app.squeeze import SqueezeError, between, plan, share_out


def text(response) -> str:
    return response.get_data(as_text=True)


# --- sharing the days out ---------------------------------------------------

def test_the_worked_example():
    """Twenty-five days and five, squeezed into fifteen. Half of each is 12.5
    and 2.5, which nobody can work to; it comes out 12 and 3."""
    assert share_out({1: 25, 2: 5}, 15) == {1: 12, 2: 3}


def test_the_leftover_day_goes_to_the_shorter_line():
    """A day off a three-day job costs a third of it; a day off a twelve-day
    job costs a twelfth. So the short line gets the benefit of the rounding."""
    shared = share_out({1: 25, 2: 5}, 15)
    assert shared[2] == 3, "the five-day line rounds up"
    assert shared[1] == 12, "the twenty-five-day line gives the day back"
    assert sum(shared.values()) == 15


def test_the_days_always_total_exactly_what_was_asked_for():
    for lengths, target in (
        ({1: 25, 2: 5}, 15),
        ({1: 10, 2: 10, 3: 10}, 10),
        ({1: 7, 2: 3, 3: 3, 4: 1}, 9),
        ({1: 100}, 1),
        ({1: 3, 2: 3, 3: 3}, 3),
        ({1: 40, 2: 20, 3: 13, 4: 7}, 33),
    ):
        shared = share_out(lengths, target)
        assert sum(shared.values()) == target, (lengths, target, shared)
        assert all(days >= 1 for days in shared.values()), shared


def test_proportions_are_kept_rather_than_days_taken_off_each():
    """Halving a stretch halves both lines. Taking the same number of days off
    each would finish the short one before it started."""
    shared = share_out({1: 40, 2: 20}, 30)
    assert shared == {1: 20, 2: 10}


def test_no_line_is_ever_squeezed_below_a_day():
    shared = share_out({1: 90, 2: 1}, 10)
    assert shared[2] == 1
    assert sum(shared.values()) == 10


def test_a_stretch_shorter_than_the_number_of_lines_is_refused_with_the_reason():
    with pytest.raises(SqueezeError) as refused:
        share_out({1: 5, 2: 5, 3: 5}, 2)
    assert "at least one" in str(refused.value)
    assert "3 is the shortest" in str(refused.value)


def test_a_stretch_that_is_already_the_length_asked_for_changes_nothing():
    assert share_out({1: 25, 2: 5}, 30) == {1: 25, 2: 5}


# --- what counts as the stretch ---------------------------------------------

def _link(a, b, lag=0, kind="FS"):
    return {"predecessor_id": a, "successor_id": b, "lag_days": lag, "kind": kind}


def test_the_stretch_is_everything_on_a_route_between_the_two_ends():
    links = [_link(1, 2), _link(2, 3), _link(3, 4), _link(4, 5)]
    assert between(2, 4, links) == [2, 3, 4]


def test_a_branch_that_runs_between_them_is_in_it_too():
    """A branch left at its old length finishes after the line it feeds."""
    links = [_link(1, 2), _link(1, 3), _link(2, 4), _link(3, 4)]
    assert between(1, 4, links) == [1, 2, 3, 4]


def test_a_branch_that_leaves_the_stretch_is_not_in_it():
    links = [_link(1, 2), _link(2, 3), _link(2, 9)]
    assert between(1, 3, links) == [1, 2, 3]


def test_two_lines_with_nothing_between_them_are_not_a_stretch():
    assert between(1, 4, [_link(1, 2), _link(3, 4)]) == []


# --- the whole proposal -----------------------------------------------------

def _rows(*spans):
    return [{"id": n, "wbs": f"1.{n}", "name": f"Line {n}", "start_date": start,
             "submission_date": finish, "calendar_id": None}
            for n, (start, finish) in enumerate(spans, start=1)]


def test_a_serial_run_is_re_laid_end_to_end_from_where_it_starts():
    # 25 days and 5 days, back to back, squeezed into 15.
    tasks = _rows(("2026-01-01", "2026-01-25"), ("2026-01-26", "2026-01-30"))
    proposal = plan(tasks, [_link(1, 2)], None, 1, 2, 15)

    assert [c["days"] for c in proposal["changes"]] == [12, 3]
    assert proposal["was_days"] == 30
    assert proposal["days"] == 15
    assert proposal["start"] == "2026-01-01"
    assert proposal["changes"][0]["submission"] == "2026-01-12"
    assert proposal["changes"][1]["start"] == "2026-01-13"
    assert proposal["finish"] == "2026-01-15"
    assert proposal["saved_days"] == 15
    assert proposal["reaches_target"] is True


def test_nothing_is_written_by_working_it_out():
    """The proposal is a description. It has to be safe to run it, read it, and
    change your mind."""
    tasks = _rows(("2026-01-01", "2026-01-25"), ("2026-01-26", "2026-01-30"))
    before = [dict(t) for t in tasks]
    plan(tasks, [_link(1, 2)], None, 1, 2, 15)
    assert tasks == before


def test_what_waits_on_the_run_is_pulled_forward_with_it():
    """A squeeze that leaves the rest of the programme where it was has not
    shortened anything."""
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-01-11", "2026-01-20"),
                  ("2026-01-21", "2026-01-30"))
    proposal = plan(tasks, [_link(1, 2), _link(2, 3)], None, 1, 2, 10)

    assert [c["id"] for c in proposal["changes"]] == [1, 2]
    following = proposal["after"]
    assert [f["id"] for f in following] == [3]
    assert following[0]["start"] == "2026-01-11"
    # It keeps the length it was given; only its place changes.
    assert following[0]["days"] == 10
    assert following[0]["submission"] == "2026-01-20"


def test_a_line_that_already_sits_early_enough_is_left_alone():
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-01-11", "2026-01-20"))
    # Nothing after the run: there is nothing to pull in.
    proposal = plan(tasks, [_link(1, 2)], None, 1, 2, 10)
    assert proposal["after"] == []


def test_waiting_between_two_lines_does_not_compress():
    """A lag is a client review or a curing time. A fortnight of it is a
    fortnight however hard anybody pushes, so it is reported rather than
    quietly counted as squeezed."""
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-01-21", "2026-01-30"))
    proposal = plan(tasks, [_link(1, 2, lag=10)], None, 1, 2, 10)

    assert proposal["days"] == 10, "the durations do total what was asked"
    assert proposal["reaches_target"] is False, "but the run itself cannot"
    # The lag still sits between them.
    first, second = proposal["changes"]
    assert second["start"] > first["submission"]


def test_squeezing_two_ends_that_are_not_joined_up_says_what_to_do():
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-02-01", "2026-02-10"))
    with pytest.raises(SqueezeError) as refused:
        plan(tasks, [], None, 1, 2, 10)
    assert "Nothing links" in str(refused.value)
    assert "Link them on the schedule" in str(refused.value)


def test_a_stretch_of_no_days_is_refused():
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-01-11", "2026-01-20"))
    with pytest.raises(SqueezeError):
        plan(tasks, [_link(1, 2)], None, 1, 2, 0)


def test_a_working_week_is_kept_while_the_days_come_down(app):
    """Squeezed days are working days, so a five-day week still gets weekends."""
    from app.calendars import Calendar

    tasks = _rows(("2026-01-05", "2026-01-30"), ("2026-02-02", "2026-02-06"))
    week = {None: Calendar("Five day week", "1111100")}
    proposal = plan(tasks, [_link(1, 2)], week, 1, 2, 15)

    assert sum(c["days"] for c in proposal["changes"]) == 15
    for line in proposal["changes"]:
        # Monday to Friday: nothing starts or is submitted at the weekend.
        from datetime import date
        for when in (line["start"], line["submission"]):
            assert date.fromisoformat(when).weekday() < 5, f"{when} is a weekend"


# --- on the project ---------------------------------------------------------

def _joined(project_id: int, *wbs: str) -> list[int]:
    from app.service import add_link, load_tasks

    rows = {t["wbs"]: t for t in load_tasks(project_id)}
    ids = [rows[w]["id"] for w in wbs]
    for first, second in zip(ids, ids[1:]):
        add_link(project_id, first, second)
    return ids


def test_a_squeeze_moves_the_dates_and_says_what_it_did(signed_in, app):
    from app.service import load_tasks

    with app.app_context():
        first, _middle, last = _joined(1, "1.1", "1.2", "1.3")

    answer = signed_in.post("/projects/1/schedule/squeeze",
                            data={"from_task": first, "to_task": last, "days": 20},
                            follow_redirects=True)
    said = text(answer)
    assert "Squeezed 3 deliverables into 20 working days" in said

    with app.app_context():
        rows = {t["wbs"]: t for t in load_tasks(1)}
        days = sum(duration_between(rows[w]["start_date"], rows[w]["submission_date"])
                   for w in ("1.1", "1.2", "1.3"))
    assert days == 20


def test_the_preview_shows_what_would_happen_and_changes_nothing(signed_in, app):
    from app.service import load_tasks

    with app.app_context():
        first, _middle, last = _joined(1, "1.1", "1.2", "1.3")
        before = {t["wbs"]: (t["start_date"], t["submission_date"]) for t in load_tasks(1)}

    page = text(signed_in.get(f"/projects/1/schedule?from_task={first}&to_task={last}&days=20"))
    assert "/schedule/squeeze" in page, "the preview offers the button that does it"
    assert "Squeezed into" in page

    with app.app_context():
        after = {t["wbs"]: (t["start_date"], t["submission_date"]) for t in load_tasks(1)}
    assert after == before, "working it out must not move anything"


def test_a_squeeze_that_cannot_be_worked_out_says_so_on_the_page(signed_in, app):
    with app.app_context():
        from app.service import load_tasks
        rows = {t["wbs"]: t for t in load_tasks(1)}
        first, last = rows["1.1"]["id"], rows["4.1"]["id"]

    page = text(signed_in.get(f"/projects/1/schedule?from_task={first}&to_task={last}&days=20"))
    assert "Nothing links" in page
    # No button to press: there is nothing to do until they are joined up. (The
    # words themselves appear in the tab's own helper strip, so this looks for
    # the button rather than the phrase.)
    assert "/schedule/squeeze" not in page


def test_squeezing_takes_manager_access(client, app):
    from app.auth import hash_password
    from app.db import execute, insert

    with app.app_context():
        first, _m, last = _joined(1, "1.1", "1.2", "1.3")
        user_id = insert("INSERT INTO users (email, name, password_hash, role) "
                         "VALUES (?, ?, ?, 'user')",
                         ("member@example.com", "Member", hash_password("password123")))
        execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, ?, 'member')",
                (user_id,))
    client.post("/login", data={"email": "member@example.com", "password": "password123"})

    answer = client.post("/projects/1/schedule/squeeze",
                         data={"from_task": first, "to_task": last, "days": 20})
    # Refused the same way every other change to the programme is refused.
    assert answer.status_code == 403


# --- and from the chat ------------------------------------------------------

def test_carmen_stages_a_squeeze_with_the_real_numbers_in_it(app):
    from app.assistant import tools

    with app.app_context():
        _joined(1, "1.1", "1.2", "1.3")
        staged = tools.run("squeeze_schedule", 1, {"start_at": "1.1", "end_at": "1.3",
                                                   "days": 20})

    assert staged["kind"] == "squeeze_schedule"
    assert "20 working days" in staged["says"]
    assert "3 deliverables" in staged["says"]
    assert sum(line["days"] for line in staged["note"]["lines"]) == 20


def test_applying_it_from_the_chat_moves_the_programme(app):
    from app.assistant import tools
    from app.assistant.runner import apply
    from app.service import load_tasks

    with app.app_context():
        _joined(1, "1.1", "1.2", "1.3")
        staged = tools.run("squeeze_schedule", 1, {"start_at": "1.1", "end_at": "1.3",
                                                   "days": 20})
        apply(1, [staged], user_id=1)
        rows = {t["wbs"]: t for t in load_tasks(1)}
        days = sum(duration_between(rows[w]["start_date"], rows[w]["submission_date"])
                   for w in ("1.1", "1.2", "1.3"))

    assert days == 20


def test_the_chat_cannot_move_the_programme_without_manager_access(app):
    from app.assistant import tools
    from app.assistant.common import ApplyError
    from app.assistant.runner import apply

    with app.app_context():
        _joined(1, "1.1", "1.2", "1.3")
        staged = tools.run("squeeze_schedule", 1, {"start_at": "1.1", "end_at": "1.3",
                                                   "days": 20})
        with pytest.raises(ApplyError) as refused:
            apply(1, [staged], user_id=1, is_manager=False)

    assert "manager access" in str(refused.value)
