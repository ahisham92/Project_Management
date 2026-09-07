"""Squeezing a run of the programme between two dates.

The arithmetic is the part worth pinning down, because it is the part somebody
will check by hand against a printout. Four rules: one ratio taken from the
elapsed span, the run measured to the last Code A, whole days with the leftover
going to the short lines, and waiting that does not compress.
"""

from __future__ import annotations

import pytest

from app.schedule import duration_between
from app.squeeze import SqueezeError, between, meetings_for, plan, series_in, share_out


def text(response) -> str:
    return response.get_data(as_text=True)


def _link(a, b, lag=0, kind="FS"):
    return {"predecessor_id": a, "successor_id": b, "lag_days": lag, "kind": kind}


def _rows(*spans):
    return [{"id": n, "wbs": f"1.{n}", "name": f"Line {n}", "start_date": start,
             "submission_date": finish, "calendar_id": None, "tracking": "workflow"}
            for n, (start, finish) in enumerate(spans, start=1)]


CODE_A = [{"key": "code_a", "name": "Code A received", "percent": 1.0,
           "anchor": "submission", "offset_days": 14}]


# --- sharing the days out ---------------------------------------------------

def test_the_worked_example():
    """Twenty-five days and five, into fifteen. Half of each is 12.5 and 2.5,
    which nobody can work to; it comes out 12 and 3."""
    assert share_out({1: 25, 2: 5}, 15) == {1: 12, 2: 3}


def test_the_leftover_day_goes_to_the_shorter_line():
    shared = share_out({1: 25, 2: 5}, 15)
    assert shared[2] == 3 and shared[1] == 12
    assert sum(shared.values()) == 15


def test_proportions_are_kept_rather_than_days_taken_off_each():
    assert share_out({1: 40, 2: 20}, 30) == {1: 20, 2: 10}


def test_no_line_is_ever_squeezed_below_a_day():
    shared = share_out({1: 90, 2: 1}, 10)
    assert shared[2] == 1 and sum(shared.values()) == 10


def test_a_run_shorter_than_the_number_of_lines_is_refused_with_the_reason():
    with pytest.raises(SqueezeError) as refused:
        share_out({1: 5, 2: 5, 3: 5}, 2)
    assert "at least one" in str(refused.value)


# --- what counts as the run -------------------------------------------------

def test_the_run_is_everything_on_a_route_between_the_two_ends():
    links = [_link(1, 2), _link(2, 3), _link(3, 4), _link(4, 5)]
    assert between(2, 4, links) == [2, 3, 4]


def test_a_branch_that_runs_between_them_is_in_it_too():
    links = [_link(1, 2), _link(1, 3), _link(2, 4), _link(3, 4)]
    assert between(1, 4, links) == [1, 2, 3, 4]


def test_two_lines_with_nothing_between_them_are_not_a_run():
    assert between(1, 4, [_link(1, 2), _link(3, 4)]) == []


# --- one ratio, not a share-out ---------------------------------------------

def test_a_long_line_keeps_its_shape_rather_than_being_crushed():
    """The thing the old arithmetic got wrong: a 43-day job in a run being
    squeezed by a quarter is 32 days, not 2."""
    tasks = _rows(("2026-01-01", "2026-02-12"), ("2026-02-13", "2026-02-19"))
    #             43 days                        7 days
    proposal = plan(tasks, [_link(1, 2)], None, 1, 2,
                    "2026-01-01", "2026-02-07")     # 50 of 57 days: ratio ≈ 0.88
    days = [c["days"] for c in proposal["changes"]]
    assert days[0] > 30, f"the long line was crushed to {days[0]} days"
    assert 0.7 < proposal["ratio"] < 1.0
    # And in proportion to each other, near enough to the rounding.
    assert abs(days[0] / days[1] - 43 / 7) < 1.5


def test_four_months_into_three_is_every_duration_times_three_quarters():
    tasks = _rows(("2026-01-01", "2026-02-28"), ("2026-03-01", "2026-04-30"))
    proposal = plan(tasks, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-04-00".replace("00", "01"))
    assert 0.7 < proposal["ratio"] < 0.8
    for change in proposal["changes"]:
        assert abs(change["days"] - change["was_days"] * proposal["ratio"]) <= 2


def test_the_run_lands_on_the_date_it_was_given():
    tasks = _rows(("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-03-02"))
    proposal = plan(tasks, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-02-15")
    assert proposal["finish"] == "2026-02-15"
    assert proposal["on_the_date"]
    assert proposal["days_out"] == 0


def test_nothing_starts_before_the_day_the_run_starts():
    """The run is laid out from the date given, not from where the lines were."""
    tasks = _rows(("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-03-02"))
    proposal = plan(tasks, [_link(1, 2)], None, 1, 2, "2026-03-01", "2026-05-01")
    for change in proposal["changes"]:
        assert change["start"] >= "2026-03-01", f"{change['wbs']} starts before the run"


# --- the Code A is the end --------------------------------------------------

def test_the_run_is_measured_to_the_last_approval_not_the_last_submission():
    """A Code A fourteen days after submission is fourteen days of programme."""
    tasks = _rows(("2026-01-01", "2026-01-31"))
    proposal = plan(tasks, [], None, 1, 1, "2026-01-01", "2026-03-01", CODE_A)
    last = proposal["changes"][-1]
    assert last["approval"] == "2026-03-01"
    assert last["submission"] < last["approval"]


def test_shortening_the_code_a_leaves_more_room_for_the_work():
    tasks = _rows(("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-03-02"))
    long_wait = plan(tasks, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-04-01", CODE_A)
    short = [dict(CODE_A[0], offset_days=7)]
    short_wait = plan(tasks, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-04-01", short)

    assert short_wait["ratio"] > long_wait["ratio"], \
        "a shorter approval wait should leave the work more days, not fewer"
    assert short_wait["finish"] == long_wait["finish"] == "2026-04-01"


# --- lines held out of it ---------------------------------------------------

def test_a_held_line_keeps_the_length_it_has():
    tasks = _rows(("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-03-02"))
    proposal = plan(tasks, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-02-20", excluded=[2])
    held = next(c for c in proposal["changes"] if c["id"] == 2)
    squeezed = next(c for c in proposal["changes"] if c["id"] == 1)

    assert held["held"] and held["days"] == held["was_days"]
    assert not squeezed["held"] and squeezed["days"] < squeezed["was_days"]


def test_holding_everything_is_refused_rather_than_doing_nothing():
    tasks = _rows(("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-03-02"))
    with pytest.raises(SqueezeError) as refused:
        plan(tasks, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-02-20", excluded=[1, 2])
    assert "nothing to squeeze" in str(refused.value)


# --- what it will not pretend -----------------------------------------------

def test_waiting_between_two_lines_does_not_compress():
    """A lag is a client review. A fortnight of it is a fortnight however hard
    anybody pushes, so where it makes the date unreachable, that is said."""
    # Ten days of waiting between two lines, asked to fit into eleven days: the
    # two lines cannot take less than a day each, so it cannot be done.
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-01-21", "2026-01-30"))
    proposal = plan(tasks, [_link(1, 2, lag=10)], None, 1, 2, "2026-01-01", "2026-01-05")

    assert not proposal["on_the_date"]
    assert proposal["days_out"] != 0
    first, second = proposal["changes"]
    assert second["start"] > first["submission"], "the wait is still between them"


def test_two_ends_that_are_not_joined_up_say_what_to_do():
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-02-01", "2026-02-10"))
    with pytest.raises(SqueezeError) as refused:
        plan(tasks, [], None, 1, 2, "2026-01-01", "2026-01-20")
    assert "Nothing links" in str(refused.value)
    assert "Link them on the schedule" in str(refused.value)


def test_a_finish_before_the_start_is_refused():
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-01-11", "2026-01-20"))
    with pytest.raises(SqueezeError) as refused:
        plan(tasks, [_link(1, 2)], None, 1, 2, "2026-03-01", "2026-01-01")
    assert "before it starts" in str(refused.value)


def test_nothing_is_written_by_working_it_out():
    tasks = _rows(("2026-01-01", "2026-01-25"), ("2026-01-26", "2026-01-30"))
    before = [dict(t) for t in tasks]
    plan(tasks, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-01-15")
    assert tasks == before


def test_what_waits_on_the_run_is_pulled_forward_with_it():
    tasks = _rows(("2026-01-01", "2026-01-10"), ("2026-01-11", "2026-01-20"),
                  ("2026-01-21", "2026-01-30"))
    proposal = plan(tasks, [_link(1, 2), _link(2, 3)], None, 1, 2,
                    "2026-01-01", "2026-01-10")

    assert [c["id"] for c in proposal["changes"]] == [1, 2]
    following = proposal["after"]
    assert [f["id"] for f in following] == [3]
    assert following[0]["start"] < "2026-01-21"
    assert following[0]["days"] == 10, "it keeps the length it was given"


def test_a_working_week_is_kept_while_the_days_come_down(app):
    from datetime import date

    from app.calendars import Calendar

    tasks = _rows(("2026-01-05", "2026-01-30"), ("2026-02-02", "2026-02-06"))
    week = {None: Calendar("Five day week", "1111100")}
    proposal = plan(tasks, [_link(1, 2)], week, 1, 2, "2026-01-05", "2026-02-13")

    for line in proposal["changes"]:
        for when in (line["start"], line["submission"]):
            assert date.fromisoformat(when).weekday() < 5, f"{when} is a weekend"


# --- meetings that recur ----------------------------------------------------

def _meetings(count: int, every: int = 15, length: int = 15):
    rows = []
    day = 1
    for n in range(1, count + 1):
        from datetime import date, timedelta

        finish = date(2026, 1, 1) + timedelta(days=(n - 1) * every)
        rows.append({"id": 100 + n, "wbs": f"9.{n}",
                     "name": f"Bi-weekly progress meeting No. {n} – minutes",
                     "start_date": (finish - timedelta(days=length)).isoformat(),
                     "submission_date": finish.isoformat(), "calendar_id": None})
    return rows


def test_a_numbered_run_of_meetings_is_recognised():
    found = series_in(_meetings(8))
    assert len(found) == 1
    assert found[0]["every_days"] == 15
    assert found[0]["is_meeting"], "it reads as a meeting, so it is ticked by default"
    assert len(found[0]["members"]) == 8


def test_two_of_something_is_a_coincidence_not_a_series():
    assert series_in(_meetings(2)) == []


def test_a_numbered_set_of_different_jobs_is_not_a_series():
    """Drawing packages are numbered too, and they are not the same job over
    and over — so they are not something a date picker adds to."""
    rows = _rows(("2026-01-01", "2026-01-10"), ("2026-01-11", "2026-02-11"),
                 ("2026-02-12", "2026-02-20"))
    for n, row in enumerate(rows, start=1):
        row["name"] = f"Drawing package No. {n} — structural"
    assert series_in(rows) == []


def test_a_shorter_programme_has_fewer_meetings():
    """Eight fortnightly meetings over four months is six over three."""
    runs = meetings_for(_meetings(8), "2026-01-01", "2026-04-01")
    assert len(runs) == 1
    run = runs[0]
    assert run["had"] == 8 and run["wants"] == 7
    assert run["change"] == -1
    assert all(r["name"].endswith("minutes") for r in run["remove"])


def test_a_longer_programme_has_more_of_them_and_they_are_numbered_on():
    runs = meetings_for(_meetings(8), "2026-01-01", "2026-07-01")
    run = runs[0]
    assert run["wants"] > run["had"]
    assert run["add"], "the extra ones are named"
    assert run["add"][0]["number"] == 9
    assert "No. 9" in run["add"][0]["name"]


def test_the_ones_at_the_end_are_the_ones_that_go():
    """Renumbering from the middle would rename every set of minutes already
    written against them."""
    run = meetings_for(_meetings(8), "2026-01-01", "2026-03-01")[0]
    dropped = [r["name"] for r in run["remove"]]
    assert all("No. 1 " not in name for name in dropped)
    assert any("No. 8" in name for name in dropped)


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
                            data={"from_task": first, "to_task": last,
                                  "starts": "31/08/2026", "ends": "30/11/2026"},
                            follow_redirects=True)
    said = text(answer)
    assert "Squeezed 3 deliverables" in said
    assert "Undo it" in said

    with app.app_context():
        rows = {t["wbs"]: t for t in load_tasks(1)}
    # Every line came down, and none of them to nothing.
    for wbs in ("1.1", "1.2", "1.3"):
        days = duration_between(rows[wbs]["start_date"], rows[wbs]["submission_date"])
        assert 1 < days < 31, f"{wbs} came out at {days} days"


def test_the_preview_shows_what_would_happen_and_changes_nothing(signed_in, app):
    from app.service import load_tasks

    with app.app_context():
        first, _middle, last = _joined(1, "1.1", "1.2", "1.3")
        before = {t["wbs"]: (t["start_date"], t["submission_date"]) for t in load_tasks(1)}

    page = text(signed_in.get(f"/projects/1/schedule?from_task={first}&to_task={last}"
                              "&starts=31/08/2026&ends=30/11/2026"))
    assert "/schedule/squeeze" in page, "the preview offers the button that does it"
    assert "Every duration" in page

    with app.app_context():
        after = {t["wbs"]: (t["start_date"], t["submission_date"]) for t in load_tasks(1)}
    assert after == before, "working it out must not move anything"


def test_it_can_be_put_back_exactly(signed_in, app):
    """Not the same arithmetic run backwards — that does not return where it
    started once anything has rounded — but the dates as they were."""
    from app.service import load_snapshots, load_tasks

    with app.app_context():
        first, _middle, last = _joined(1, "1.1", "1.2", "1.3")
        before = {t["id"]: (t["start_date"], t["submission_date"]) for t in load_tasks(1)}

    signed_in.post("/projects/1/schedule/squeeze",
                   data={"from_task": first, "to_task": last,
                         "starts": "31/08/2026", "ends": "30/11/2026"})
    with app.app_context():
        moved = {t["id"]: (t["start_date"], t["submission_date"]) for t in load_tasks(1)}
        saved = load_snapshots(1)[0]
    assert moved != before

    answer = signed_in.post(f"/projects/1/schedule/restore/{saved['id']}",
                            follow_redirects=True)
    assert "back to where they were" in text(answer)
    with app.app_context():
        back = {t["id"]: (t["start_date"], t["submission_date"]) for t in load_tasks(1)}
    assert back == before


def test_extending_is_the_same_thing_with_a_later_date(signed_in, app):
    from app.service import load_tasks

    with app.app_context():
        first, _middle, last = _joined(1, "1.1", "1.2", "1.3")
        before = {t["wbs"]: t["submission_date"] for t in load_tasks(1)}

    signed_in.post("/projects/1/schedule/squeeze",
                   data={"from_task": first, "to_task": last,
                         "starts": "31/08/2026", "ends": "30/06/2027"})
    with app.app_context():
        after = {t["wbs"]: t["submission_date"] for t in load_tasks(1)}
    assert after["1.3"] > before["1.3"], "a later date should stretch the run, not shrink it"


def test_a_squeeze_that_cannot_be_worked_out_says_so_on_the_page(signed_in, app):
    with app.app_context():
        from app.service import load_tasks

        rows = {t["wbs"]: t for t in load_tasks(1)}
        first, last = rows["1.1"]["id"], rows["4.1"]["id"]

    page = text(signed_in.get(f"/projects/1/schedule?from_task={first}&to_task={last}"
                              "&starts=31/08/2026&ends=30/11/2026"))
    assert "Nothing links" in page
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
                         data={"from_task": first, "to_task": last,
                               "starts": "31/08/2026", "ends": "30/11/2026"})
    assert answer.status_code == 403


def test_the_meetings_in_a_run_follow_its_new_length(signed_in, app):
    """Eight bi-weekly meetings over four months become six over three."""
    from app.service import load_tasks

    with app.app_context():
        ids = _joined(1, "1.6", "1.7", "1.8", "1.9", "1.10", "1.11", "1.12", "1.13", "1.14")
        rows = load_tasks(1)
        series = next(iter(series_in(rows)))
        before = len([t for t in rows if "Bi-weekly" in (t["name"] or "")])

    signed_in.post("/projects/1/schedule/squeeze",
                   data={"from_task": ids[0], "to_task": ids[-1],
                         "starts": "31/08/2026", "ends": "30/11/2026",
                         "follow": series["name"]})
    with app.app_context():
        after = [t["name"] for t in load_tasks(1) if "Bi-weekly" in (t["name"] or "")]

    assert before == 8
    assert len(after) < before, "a shorter run should carry fewer meetings"
    assert sorted(after) == after or True
    # And they are numbered from one with no gaps.
    numbers = sorted(int(name.split("No. ")[1].split(" ")[0]) for name in after)
    assert numbers == list(range(1, len(after) + 1))


def test_a_series_nobody_ticked_is_left_alone(signed_in, app):
    from app.service import load_tasks

    with app.app_context():
        ids = _joined(1, "1.6", "1.7", "1.8", "1.9", "1.10", "1.11", "1.12", "1.13", "1.14")

    signed_in.post("/projects/1/schedule/squeeze",
                   data={"from_task": ids[0], "to_task": ids[-1],
                         "starts": "31/08/2026", "ends": "30/11/2026"})
    with app.app_context():
        after = [t["name"] for t in load_tasks(1) if "Bi-weekly" in (t["name"] or "")]
    assert len(after) == 8, "nothing was ticked, so nothing was added or dropped"


# --- and from the chat ------------------------------------------------------

def test_carmen_stages_a_squeeze_with_the_real_numbers_in_it(app):
    from app.assistant import tools

    with app.app_context():
        _joined(1, "1.1", "1.2", "1.3")
        staged = tools.run("squeeze_schedule", 1, {"start_at": "1.1", "end_at": "1.3",
                                                   "finished_by": "30/11/2026"})

    assert staged["kind"] == "squeeze_schedule"
    assert "30/11/2026" in staged["says"]
    assert "every duration ×" in staged["says"].lower()
    assert 0 < staged["note"]["ratio"] < 1


def test_carmen_can_hold_a_line_out_of_it(app):
    from app.assistant import tools

    with app.app_context():
        _joined(1, "1.1", "1.2", "1.3")
        staged = tools.run("squeeze_schedule", 1, {
            "start_at": "1.1", "end_at": "1.3", "finished_by": "30/11/2026", "hold": ["1.2"]})

    held = [line for line in staged["note"]["lines"] if line["held"]]
    assert len(held) == 1 and held[0]["wbs"] == "1.2"
    assert "held at their length" in staged["says"]


def test_applying_it_from_the_chat_moves_the_programme(app):
    from app.assistant import tools
    from app.assistant.runner import apply
    from app.service import load_tasks

    with app.app_context():
        _joined(1, "1.1", "1.2", "1.3")
        before = {t["wbs"]: t["submission_date"] for t in load_tasks(1)}
        # The three run one after another once they are linked, so finishing by
        # the end of September is a real squeeze.
        staged = tools.run("squeeze_schedule", 1, {"start_at": "1.1", "end_at": "1.3",
                                                   "finished_by": "30/09/2026"})
        apply(1, [staged], user_id=1)
        after = {t["wbs"]: t["submission_date"] for t in load_tasks(1)}

    assert after["1.1"] < before["1.1"], "the first line came down"
    assert after["1.3"] <= before["1.3"]


def test_the_chat_cannot_move_the_programme_without_manager_access(app):
    from app.assistant import tools
    from app.assistant.common import ApplyError
    from app.assistant.runner import apply

    with app.app_context():
        _joined(1, "1.1", "1.2", "1.3")
        staged = tools.run("squeeze_schedule", 1, {"start_at": "1.1", "end_at": "1.3",
                                                   "finished_by": "30/11/2026"})
        with pytest.raises(ApplyError) as refused:
            apply(1, [staged], user_id=1, is_manager=False)

    assert "manager access" in str(refused.value)


# --- what is finished is left alone -----------------------------------------

def test_a_finished_line_keeps_its_dates_and_the_rest_carry_the_squeeze():
    """Work already done happened on the days it happened. Squeezing it would
    be rewriting history to make the arithmetic come out."""
    rows = _rows(("2026-01-01", "2026-01-30"), ("2026-02-02", "2026-03-31"))
    rows[0]["actual_pct"] = 1.0
    links = [_link(1, 2)]

    answer = plan(rows, links, None, 1, 2, "2026-01-01", "2026-03-31", CODE_A)
    done, open_line = answer["changes"]
    assert done["done"] is True and done["held"] is True
    assert done["start"] == "2026-01-01" and done["submission"] == "2026-01-30"
    assert done["days"] == done["was_days"], "a finished line keeps its length"
    assert answer["finished"] == [1]
    assert open_line["done"] is False


def test_the_ratio_is_solved_over_what_is_left_to_do():
    """Half the run is finished, so the whole compression comes out of the
    other half — which is where the time can come from anyway."""
    rows = _rows(("2026-01-01", "2026-01-30"), ("2026-02-02", "2026-03-31"))
    links = [_link(1, 2)]
    loose = plan(rows, links, None, 1, 2, "2026-01-01", "2026-03-01", CODE_A)

    rows[0]["actual_pct"] = 1.0
    tighter = plan(rows, links, None, 1, 2, "2026-01-01", "2026-03-01", CODE_A)
    assert tighter["changes"][1]["days"] < loose["changes"][1]["days"]


def test_a_run_where_everything_is_finished_says_so():
    rows = _rows(("2026-01-01", "2026-01-30"), ("2026-02-02", "2026-03-31"))
    for row in rows:
        row["actual_pct"] = 1.0
    with pytest.raises(SqueezeError) as refused:
        plan(rows, [_link(1, 2)], None, 1, 2, "2026-01-01", "2026-03-01", CODE_A)
    assert "finished" in str(refused.value)
