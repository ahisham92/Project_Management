"""The assistant: its tools, its loop, and the deck it builds.

Nothing here calls Anthropic. What is worth testing is everything either side:
that a tool reads what the screens read, that a phrase turns into the right
deliverable or an honest question, that a change is staged rather than done,
that applying it goes through the ordinary service layer, and that the loop
copes with a model that asks for something that does not exist. The model
itself is stood in for, so the tests are fast and say the same thing every
time.
"""

from __future__ import annotations

import io
import json
import zipfile
from xml.dom.minidom import parseString

import pytest

from app.assistant import tools
from app.assistant.runner import ApplyError, ask
from app.assistant.tools import ToolError


def text(response) -> str:
    return response.get_data(as_text=True)


def _join(project_id: int, first: str, second: str) -> None:
    """A dependency between two deliverables, for the tests that need one."""
    from app.db import query_one
    from app.service import add_link

    ids = [query_one("SELECT id FROM tasks WHERE wbs = ? AND project_id = ?",
                     (wbs, project_id))["id"] for wbs in (first, second)]
    add_link(project_id, ids[0], ids[1])


def _member(app, email: str, role: str) -> None:
    """An ordinary account with a named place on the seeded project."""
    from app.auth import hash_password
    from app.db import execute, insert

    with app.app_context():
        user_id = insert(
            "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, 'user')",
            (email, email.split("@")[0], hash_password("password123")))
        execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, ?, ?)",
                (user_id, role))


@pytest.fixture()
def project(app):
    from app.db import query_one

    with app.app_context():
        return dict(query_one("SELECT * FROM projects WHERE id = 1"))


# --- the catalogue ----------------------------------------------------------

def test_every_tool_the_model_is_offered_can_actually_be_run():
    """A tool in the catalogue with no runner is one the model will call and
    get an error from, which is worse than not offering it."""
    offered = {tool["name"] for tool in tools.CATALOGUE}
    assert offered == set(tools.RUNNERS)


def test_every_tool_says_what_it_is_for():
    for tool in tools.CATALOGUE:
        assert tool["description"], f"{tool['name']} has no description"
        assert tool["input_schema"]["type"] == "object"
        for name in tool["input_schema"].get("required", []):
            assert name in tool["input_schema"]["properties"], \
                f"{tool['name']} requires {name}, which it does not define"


def test_reading_and_changing_are_told_apart():
    assert "overview" in tools.READ_ONLY
    assert "set_progress" in tools.WRITES
    assert not (tools.READ_ONLY & tools.WRITES)
    assert tools.READ_ONLY | tools.WRITES == set(tools.RUNNERS)


def test_a_link_is_not_a_change():
    """Handing somebody a URL changes nothing, so it does not need approving."""
    assert "open_view" in tools.READ_ONLY
    assert "presentation" in tools.READ_ONLY


# --- reading ----------------------------------------------------------------

def test_the_overview_reads_what_the_dashboard_reads(app, project):
    from app.service import project_overview, project_snapshot, today

    with app.app_context():
        seen = tools.run("overview", 1, {})
        straight = project_overview(project, project_snapshot(project, today()))

    assert seen["float_working_days"] == straight["float_days"]
    assert seen["earned_percent"] == round(straight["earned"] * 100, 2)
    assert seen["project"].startswith(project["code"])


def test_deliverables_can_be_narrowed_to_what_is_late(app):
    with app.app_context():
        everything = tools.run("find_deliverables", 1, {"state": "all"})
        late = tools.run("find_deliverables", 1, {"state": "late"})

    assert late["matched"] <= everything["matched"]
    assert all(row["late"] for row in late["deliverables"])


def test_a_search_reads_the_name_as_well_as_the_number(app):
    with app.app_context():
        found = tools.run("find_deliverables", 1, {"query": "design basis"})
    assert found["matched"] >= 1
    assert any("design basis" in row["name"].lower() for row in found["deliverables"])


def test_a_wbs_number_finds_exactly_one_deliverable(app):
    with app.app_context():
        one = tools.run("deliverable", 1, {"reference": "1.1"})
    assert one["wbs"] == "1.1"
    assert "waits_on" in one and "drives" in one


def test_a_phrase_matching_several_comes_back_as_a_question(app):
    """Not a guess. Changing the wrong line is the failure this exists to
    prevent."""
    with app.app_context():
        with pytest.raises(ToolError) as raised:
            tools.run("deliverable", 1, {"reference": "design"})
    assert "say which" in str(raised.value).lower()


def test_a_phrase_matching_nothing_says_so_and_says_what_to_do(app):
    with app.app_context():
        with pytest.raises(ToolError) as raised:
            tools.run("deliverable", 1, {"reference": "the biscuit tin"})
    assert "find_deliverables" in str(raised.value)


def test_the_period_report_says_what_moved(app):
    with app.app_context():
        seen = tools.run("period_report", 1, {"start": "01/08/2026", "end": "06/09/2026"})
    assert seen["from"] == "01/08/2026"
    assert "movements" in seen and "gained_percent" in seen


def test_dates_the_wrong_way_round_are_simply_swapped(app):
    with app.app_context():
        seen = tools.run("period_report", 1, {"start": "06/09/2026", "end": "01/08/2026"})
    assert seen["from"] == "01/08/2026" and seen["to"] == "06/09/2026"


def test_an_unreadable_date_is_refused_in_words(app):
    with app.app_context():
        with pytest.raises(ToolError) as raised:
            tools.run("period_report", 1, {"start": "last Tuesday", "end": "06/09/2026"})
    assert "dd/mm/yyyy" in str(raised.value)


def test_the_schedule_summary_carries_the_critical_path(app):
    with app.app_context():
        _join(1, "1.1", "1.2")
        seen = tools.run("schedule_summary", 1, {})
    assert seen["unique_paths"] >= 1
    assert [row["wbs"] for row in seen["critical_path"]]
    assert seen["dependencies"] >= 1


def test_the_week_can_be_read_from_a_tool(app):
    with app.app_context():
        seen = tools.run("week_ahead", 1, {})
    assert "requirements" in seen and "totals" in seen


def test_a_register_can_be_read_as_at_a_past_date(app):
    with app.app_context():
        seen = tools.run("register", 1, {"kind": "client", "as_at": "01/01/2020"})
    assert seen["as_at"] == "01/01/2020"
    assert seen["count"] == 0            # nothing had been raised in 2020


# --- changing is staged, not done -------------------------------------------

def test_setting_progress_stages_it_rather_than_doing_it(app):
    from app.db import query_one

    with app.app_context():
        before = query_one("SELECT actual_pct FROM tasks WHERE wbs = '1.1' AND project_id = 1")
        staged = tools.run("set_progress", 1, {"reference": "1.1", "percent": 40})
        after = query_one("SELECT actual_pct FROM tasks WHERE wbs = '1.1' AND project_id = 1")

    assert staged["kind"] == "set_progress"
    assert "40%" in staged["says"]
    assert after["actual_pct"] == before["actual_pct"]      # nothing happened yet


def test_a_percentage_outside_the_possible_is_refused(app):
    with app.app_context():
        for value in (-5, 140):
            with pytest.raises(ToolError):
                tools.run("set_progress", 1, {"reference": "1.1", "percent": value})


def test_a_workflow_step_can_be_named_instead_of_a_number(app):
    with app.app_context():
        staged = tools.run("set_progress", 1, {"reference": "1.1", "status": "Submitted"})
    assert staged["status_key"]
    assert "%" in staged["says"]


def test_a_step_that_does_not_exist_lists_the_ones_that_do(app):
    with app.app_context():
        with pytest.raises(ToolError) as raised:
            tools.run("set_progress", 1, {"reference": "1.1", "status": "Nearly done"})
    assert "the steps are" in str(raised.value).lower()


def test_moving_dates_is_staged_with_the_cascade_spelled_out(app):
    with app.app_context():
        staged = tools.run("set_dates", 1, {"reference": "1.1", "start": "01/10/2026",
                                            "submission": "20/10/2026"})
    assert staged["start"] == "2026-10-01"
    assert "waits on it moves with it" in staged["says"]


def test_a_deliverable_cannot_be_made_to_wait_on_itself(app):
    with app.app_context():
        with pytest.raises(ToolError):
            tools.run("link_deliverables", 1, {"predecessor": "1.1", "successor": "1.1"})


def test_unlinking_something_that_is_not_linked_says_so(app):
    with app.app_context():
        with pytest.raises(ToolError) as raised:
            tools.run("unlink_deliverables", 1, {"predecessor": "4.1", "successor": "1.1"})
    assert "does not wait on" in str(raised.value)


def test_an_action_needs_a_subject(app):
    with app.app_context():
        with pytest.raises(ToolError):
            tools.run("raise_item", 1, {"register": "internal", "subject": "   "})


def test_a_holiday_for_a_team_that_does_not_exist_lists_the_teams(app):
    with app.app_context():
        with pytest.raises(ToolError) as raised:
            tools.run("add_project_holiday", 1, {"date": "01/01/2027", "team": "Atlantis"})
    assert "the teams are" in str(raised.value).lower()


# --- links and documents ----------------------------------------------------

def test_a_view_comes_back_as_a_link(app):
    with app.test_request_context():
        seen = tools.run("open_view", 1, {"view": "schedule"})
    assert seen["url"].endswith("/projects/1/schedule")


def test_a_printable_view_carries_the_flag_the_page_reads(app):
    with app.test_request_context():
        seen = tools.run("open_view", 1, {"view": "schedule", "printable": True})
    assert "print=1" in seen["url"]


def test_a_view_nobody_has_is_refused_with_the_list(app):
    with app.test_request_context():
        with pytest.raises(ToolError) as raised:
            tools.run("open_view", 1, {"view": "gantt"})
    assert "schedule" in str(raised.value)


# --- the loop ---------------------------------------------------------------

class Block:
    """One content block, the shape the SDK hands back."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


class Reply:
    """One Messages API answer, as the runner reads it."""

    def __init__(self, text="", calls=(), stop_reason="", refusal=""):
        self.content = ([Block(type="text", text=text)] if text else []) + [
            Block(type="tool_use", id=call["id"], name=call["name"], input=call["input"])
            for call in calls
        ]
        self.stop_reason = stop_reason or ("tool_use" if calls else "end_turn")
        self.stop_details = Block(explanation=refusal, category="test") if refusal else None


class StandInClaude:
    """A model that says exactly what a test needs it to say, in order."""

    def __init__(self, *turns):
        self.turns = list(turns)
        self.asked: list[list[dict]] = []
        self.systems: list[str] = []
        self.efforts: list[str] = []

    def __call__(self, key, system, messages, tools=None, model="", effort="", **kwargs):
        self.asked.append([dict(m) for m in messages])
        self.systems.append(system)
        self.efforts.append(effort)
        return self.turns.pop(0) if self.turns else Reply(text="Nothing more to say.")


def _call(name, arguments, call_id="toolu_1"):
    return {"id": call_id, "name": name, "input": arguments}


def _tool_result(turn) -> str:
    """What went back to the model for the tools it asked for."""
    blocks = turn.get("content") or []
    if isinstance(blocks, str):
        return blocks
    return " ".join(str(b.get("content") or "") for b in blocks
                    if isinstance(b, dict) and b.get("type") == "tool_result")


def test_a_plain_question_comes_back_as_words(app, project, monkeypatch):
    from app import claude

    monkeypatch.setattr(claude, "chat", StandInClaude(Reply(text="It is going fine.")))
    with app.app_context():
        answer = ask(project, "How is it going?", "key")

    assert answer.text == "It is going fine."
    assert answer.staged == []
    assert answer.rounds == 1


def test_a_tool_the_model_asks_for_is_run_and_fed_back(app, project, monkeypatch):
    from app import claude

    model = StandInClaude(
        Reply(calls=[_call("overview", {})]),
        Reply(text="It is 0.5% earned against 2.4% planned."),
    )
    monkeypatch.setattr(claude, "chat", model)
    with app.app_context():
        answer = ask(project, "How is it going?", "key")

    assert answer.used == ["overview"]
    assert answer.rounds == 2
    # The tool's answer really went back to the model.
    last = model.asked[-1]
    assert last[-1]["role"] == "user"
    assert "earned_percent" in _tool_result(last[-1])


def test_a_change_is_staged_and_the_model_is_told_it_is_waiting(app, project, monkeypatch):
    from app import claude
    from app.db import query_one

    model = StandInClaude(
        Reply(calls=[_call("set_progress", {"reference": "1.1", "percent": 40})]),
        Reply(text="I have staged 1.1 at 40%."),
    )
    monkeypatch.setattr(claude, "chat", model)
    with app.app_context():
        before = query_one("SELECT actual_pct FROM tasks WHERE wbs = '1.1' AND project_id = 1")
        answer = ask(project, "Set 1.1 to 40", "key")
        after = query_one("SELECT actual_pct FROM tasks WHERE wbs = '1.1' AND project_id = 1")

    assert len(answer.staged) == 1
    assert answer.staged[0]["kind"] == "set_progress"
    assert after["actual_pct"] == before["actual_pct"]
    assert "Apply" in _tool_result(model.asked[-1][-1])  # the model knows it is not done


def test_a_tool_that_fails_is_reported_to_the_model_rather_than_ending_the_answer(
        app, project, monkeypatch):
    """A wrong reference is something it can correct on the next round."""
    from app import claude

    model = StandInClaude(
        Reply(calls=[_call("deliverable", {"reference": "the biscuit tin"})]),
        Reply(text="I could not find that — which one did you mean?"),
    )
    monkeypatch.setattr(claude, "chat", model)
    with app.app_context():
        answer = ask(project, "How is the biscuit tin?", "key")

    assert answer.trouble == ""
    assert "error" in _tool_result(model.asked[-1][-1])
    assert answer.text.startswith("I could not find that")


def test_arguments_that_are_not_an_object_do_not_break_the_answer(app, project, monkeypatch):
    from app import claude

    model = StandInClaude(
        Reply(calls=[{"id": "toolu_1", "name": "overview", "input": "not an object"}]),
        Reply(text="Sorry — let me try again."),
    )
    monkeypatch.setattr(claude, "chat", model)
    with app.app_context():
        answer = ask(project, "How is it going?", "key")
    assert answer.trouble == ""
    assert "not an object" in _tool_result(model.asked[-1][-1])


def test_the_loop_cannot_run_for_ever(app, project, monkeypatch):
    from app import claude
    from app.assistant import runner

    always = StandInClaude(*[Reply(calls=[_call("overview", {})]) for _ in range(50)])
    monkeypatch.setattr(claude, "chat", always)
    with app.app_context():
        answer = ask(project, "Go round for ever", "key")

    assert answer.rounds == runner.MAX_ROUNDS
    assert answer.text                                   # it says something rather than nothing


def test_one_answer_cannot_stage_the_whole_programme(app, project, monkeypatch):
    from app import claude
    from app.assistant import runner

    many = [_call("set_progress", {"reference": "1.1", "percent": 10}, f"toolu_{n}")
            for n in range(runner.MAX_STAGED + 4)]
    model = StandInClaude(Reply(calls=many), Reply(text="Staged what I could."))
    monkeypatch.setattr(claude, "chat", model)
    with app.app_context():
        answer = ask(project, "Change everything", "key")

    assert len(answer.staged) == runner.MAX_STAGED


def test_the_api_failing_is_reported_rather_than_swallowed(app, project, monkeypatch):
    from app import claude

    def refuse(*_args, **_kwargs):
        raise claude.ClaudeError("Anthropic did not accept that API key (401).")

    monkeypatch.setattr(claude, "chat", refuse)
    with app.app_context():
        answer = ask(project, "Anything", "key")

    assert "401" in answer.trouble
    assert answer.as_json()["ok"] is False


def test_a_refusal_is_reported_rather_than_read_as_an_empty_answer(app, project, monkeypatch):
    """A declined request comes back 200 with nothing to say; treating that as
    an answer would show the reader an empty box."""
    from app import claude

    monkeypatch.setattr(claude, "chat", StandInClaude(
        Reply(stop_reason="refusal", refusal="that is not something I can help with")))
    with app.app_context():
        answer = ask(project, "Anything", "key")

    assert "declined" in answer.trouble


def test_an_empty_question_is_not_sent_anywhere(app, project, monkeypatch):
    from app import claude

    model = StandInClaude(Reply(text="should never be reached"))
    monkeypatch.setattr(claude, "chat", model)
    with app.app_context():
        answer = ask(project, "   ", "key")
    assert answer.trouble
    assert model.asked == []


def test_the_project_comes_from_the_caller_not_from_the_model(app, project, monkeypatch):
    """No phrasing can reach another project's data."""
    from app import claude

    model = StandInClaude(
        Reply(calls=[_call("overview", {"project_id": 999})]),
        Reply(text="Here it is."),
    )
    monkeypatch.setattr(claude, "chat", model)
    with app.app_context():
        answer = ask(project, "Show me project 999", "key")

    assert answer.trouble == ""
    assert project["code"] in _tool_result(model.asked[-1][-1])


# --- applying what was approved ---------------------------------------------

def test_applying_progress_writes_it_the_ordinary_way(app):
    from app.assistant.runner import apply
    from app.db import query_one

    with app.app_context():
        staged = tools.run("set_progress", 1, {"reference": "1.1", "percent": 40,
                                               "note": "drawings out"})
        apply(1, [staged], user_id=1)
        row = query_one("SELECT actual_pct FROM tasks WHERE wbs = '1.1' AND project_id = 1")
        history = query_one("SELECT COUNT(*) AS n FROM progress_updates WHERE task_id = ?",
                            (staged["task_id"],))

    assert abs(row["actual_pct"] - 0.40) < 1e-9
    assert history["n"] >= 1                             # it is in the history, like any update


def test_applying_dates_moves_what_waits_on_it(app):
    from app.assistant.runner import apply
    from app.db import query_one

    with app.app_context():
        _join(1, "1.1", "1.2")
        successor = query_one("SELECT id, start_date FROM tasks WHERE wbs = '1.2' AND project_id = 1")
        before = successor["start_date"]

        staged = tools.run("set_dates", 1, {"reference": "1.1", "start": "01/11/2026",
                                            "submission": "20/11/2026"})
        apply(1, [staged], user_id=1)
        after = query_one("SELECT start_date FROM tasks WHERE id = ?",
                          (successor["id"],))["start_date"]

    assert after > before


def test_applying_a_raised_action_puts_it_in_the_register(app):
    from app.assistant.runner import apply
    from app.service import load_items

    with app.app_context():
        staged = tools.run("raise_item", 1, {"register": "internal", "subject": "Book the vessel",
                                             "owner": "PM", "due": "01/12/2026"})
        apply(1, [staged], user_id=1)
        raised = [i for i in load_items(1, kind="internal") if i["subject"] == "Book the vessel"]

    assert len(raised) == 1
    assert raised[0]["owner_label"] == "PM"
    assert raised[0]["due_date"] == "2026-12-01"


def test_applying_something_that_is_no_longer_there_says_so(app):
    from app.assistant.runner import apply
    from app.db import execute

    with app.app_context():
        staged = tools.run("set_progress", 1, {"reference": "1.1", "percent": 40})
        execute("DELETE FROM tasks WHERE id = ?", (staged["task_id"],))
        with pytest.raises(ApplyError):
            apply(1, [staged], user_id=1)


def test_a_change_naming_another_projects_deliverable_is_refused(app):
    """The staged list comes back from the page, so it is checked again here."""
    from app.assistant.runner import apply

    with app.app_context():
        with pytest.raises(ApplyError):
            apply(1, [{"kind": "set_progress", "task_id": 999999, "percent": 50}], user_id=1)


def test_an_invented_kind_of_change_is_refused(app):
    from app.assistant.runner import apply

    with app.app_context():
        with pytest.raises(ApplyError):
            apply(1, [{"kind": "drop_the_database", "says": "…"}], user_id=1)


# --- the deck ---------------------------------------------------------------

def test_the_deck_is_a_real_powerpoint_package(app, project):
    from app.assistant.deck_of import build

    with app.test_request_context():
        data = build(project, "2026-08-01", "2026-09-06")

    with zipfile.ZipFile(io.BytesIO(data)) as book:
        names = set(book.namelist())
        for part in ("[Content_Types].xml", "_rels/.rels", "ppt/presentation.xml",
                     "ppt/_rels/presentation.xml.rels", "ppt/theme/theme1.xml",
                     "ppt/slideMasters/slideMaster1.xml", "ppt/slideLayouts/slideLayout1.xml"):
            assert part in names, f"the deck has no {part}"
        assert sum(1 for n in names if n.startswith("ppt/slides/slide")) >= 6
        for name in names:
            if name.endswith((".xml", ".rels")):
                parseString(book.read(name))             # raises if it is malformed


def test_every_relationship_in_the_deck_points_at_something_that_is_there(app, project):
    """A dangling relationship is exactly how one of these fails to open."""
    from app.assistant.deck_of import build
    from posixpath import dirname, normpath, join

    with app.test_request_context():
        data = build(project, "2026-08-01", "2026-09-06")

    with zipfile.ZipFile(io.BytesIO(data)) as book:
        names = set(book.namelist())
        for part in [n for n in names if n.endswith(".rels")]:
            base = dirname(dirname(part)) or ""
            document = parseString(book.read(part))
            for rel in document.getElementsByTagName("Relationship"):
                target = rel.getAttribute("Target")
                if target.startswith("http"):
                    continue
                pointed = normpath(join(base, target)).lstrip("/")
                assert pointed in names, f"{part} points at {target}, which is not in the file"


def test_every_slide_the_presentation_lists_exists(app, project):
    from app.assistant.deck_of import build

    with app.test_request_context():
        data = build(project, "2026-08-01", "2026-09-06")

    with zipfile.ZipFile(io.BytesIO(data)) as book:
        rels = parseString(book.read("ppt/_rels/presentation.xml.rels"))
        by_id = {r.getAttribute("Id"): r.getAttribute("Target")
                 for r in rels.getElementsByTagName("Relationship")}
        listed = parseString(book.read("ppt/presentation.xml"))
        wanted = [node.getAttribute("r:id")
                  for node in listed.getElementsByTagName("p:sldId")]

    assert wanted
    for rid in wanted:
        assert rid in by_id and "slides/slide" in by_id[rid]


def _deck_words(data: bytes) -> str:
    """Everything the deck says, across all of its slides."""
    import re

    with zipfile.ZipFile(io.BytesIO(data)) as book:
        names = sorted((n for n in book.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
        return " ".join(book.read(name).decode("utf-8") for name in names)


def test_the_deck_says_what_the_period_says(app, project):
    """A deck that disagrees with the Summarized Progress tab is worse than no
    deck."""
    from app.assistant.deck_of import build

    with app.app_context():
        _join(1, "1.1", "1.2")
    with app.test_request_context():
        data = build(project, "2026-08-01", "2026-09-06", title="Monthly report")

    words = _deck_words(data)
    assert "Monthly report" in words
    assert project["code"] in words
    assert "critical path" in words.lower()
    assert "Where the project stands" in words
    assert "The period" in words
    assert "What needs attention" in words
    assert "What happens next" in words


def test_the_deck_is_drawn_rather_than_tabulated(app, project):
    """A deck of nothing but tables is a report somebody has printed sideways.
    The dial, the curve, the bars and the strip of dates are all shapes."""
    from app.assistant.deck_of import build

    with app.test_request_context():
        data = build(project, "2026-08-01", "2026-09-06")

    words = _deck_words(data)
    assert "blockArc" in words, "the gauge"
    assert "custGeom" in words, "the curve"
    assert words.count("Bar ") >= 2, "the bars"
    assert "Planned against earned" in words


def test_the_deck_opens_dark_and_divides_itself(app, project):
    """Dark, light, dark: the cover, the dividers and the closing are navy, and
    everything between them is white. That sandwich is what makes a deck read
    as a deck rather than as a run of pages."""
    from app.assistant.deck_of import build
    from app.deck import NAVY

    with app.test_request_context():
        data = build(project, "2026-08-01", "2026-09-06")

    import re

    with zipfile.ZipFile(io.BytesIO(data)) as book:
        names = sorted((n for n in book.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.findall(r"\d+", n)[-1]))
        dark = [n for n in names
                if f'<p:bgPr><a:solidFill><a:srgbClr val="{NAVY}"' in
                book.read(n).decode("utf-8")]
    assert len(dark) >= 5, "a cover, four dividers and a closing"
    assert names[0] in dark and names[-1] in dark


# --- the web layer ----------------------------------------------------------

def test_the_tab_is_there_and_says_it_has_no_key_yet(signed_in):
    body = text(signed_in.get("/projects/1/assistant"))
    assert "Carmen" in body
    assert "no key yet" in body
    assert "console.anthropic.com" in body


def test_asking_without_a_key_says_what_to_do_rather_than_failing(signed_in):
    answer = signed_in.post("/projects/1/assistant/ask", json={"question": "hello"})
    assert answer.status_code == 400
    assert "not connected" in answer.get_json()["error"]
    assert "Anthropic" in answer.get_json()["error"]


def test_an_administrator_can_connect_it_and_the_key_stays_out_of_the_database(signed_in, app):
    from app import vault

    signed_in.post("/projects/1/assistant/settings",
                   data={"anthropic_key": "sk-ant-secret", "anthropic_model": "claude-opus-5"},
                   follow_redirects=True)
    with app.app_context():
        assert vault.read()["anthropic_key"] == "sk-ant-secret"

        from app.backup import build
        data, _manifest = build(app.config["DATABASE"])
    assert b"sk-ant-secret" not in data


def test_only_an_administrator_can_connect_it(client, app):
    _member(app, "plain@example.com", "manager")
    client.post("/login", data={"email": "plain@example.com", "password": "password123"})
    answer = client.post("/projects/1/assistant/settings", data={"anthropic_key": "sk-ant-x"},
                         follow_redirects=True)
    assert "Only an administrator" in text(answer)

    with app.app_context():
        from app import vault

        assert not vault.read().get("anthropic_key")


def test_the_page_answers_a_question_end_to_end(signed_in, app, monkeypatch):
    from app import claude

    monkeypatch.setattr(claude, "chat", StandInClaude(
        Reply(calls=[_call("overview", {})]),
        Reply(text="Earned is behind planned."),
    ))
    signed_in.post("/projects/1/assistant/settings", data={"anthropic_key": "sk-ant-x"},
                   follow_redirects=True)

    answer = signed_in.post("/projects/1/assistant/ask", json={"question": "How is it going?"})
    said = answer.get_json()
    assert said["ok"] is True
    assert said["text"] == "Earned is behind planned."
    assert said["used"] == ["overview"]


def test_applying_from_the_page_changes_the_project(signed_in, app):
    with app.app_context():
        staged = tools.run("set_progress", 1, {"reference": "1.1", "percent": 55})

    answer = signed_in.post("/projects/1/assistant/apply", json={"actions": [staged]})
    assert answer.get_json()["ok"] is True

    from app.db import query_one

    with app.app_context():
        assert abs(query_one("SELECT actual_pct FROM tasks WHERE wbs = '1.1' AND project_id = 1"
                             )["actual_pct"] - 0.55) < 1e-9
    # And it shows on the Progress tab, because it is the same record.
    assert "55%" in text(signed_in.get("/projects/1/tasks"))


def test_applying_nothing_is_refused(signed_in):
    answer = signed_in.post("/projects/1/assistant/apply", json={"actions": []})
    assert answer.status_code == 400


def test_a_reader_who_cannot_edit_is_not_offered_changes(client, app, monkeypatch):
    """Somebody who may look but not write can still ask about the project —
    they are simply never handed a button that would change it."""
    from app import claude, vault

    with app.app_context():
        vault.write({"anthropic_key": "sk-ant-x"})
    _member(app, "look@example.com", "viewer")
    client.post("/login", data={"email": "look@example.com", "password": "password123"})

    monkeypatch.setattr(claude, "chat", StandInClaude(
        Reply(calls=[_call("set_progress", {"reference": "1.1", "percent": 40})]),
        Reply(text="I would set 1.1 to 40%."),
    ))
    answer = client.post("/projects/1/assistant/ask", json={"question": "set 1.1 to 40"})
    assert answer.status_code == 200
    assert answer.get_json()["staged"] == []

    refused = client.post("/projects/1/assistant/apply", json={"actions": [
        {"kind": "set_progress", "task_id": 1, "percent": 40}]})
    assert refused.status_code == 403


def test_the_deck_downloads_as_a_pptx(signed_in):
    answer = signed_in.get("/projects/1/assistant/deck.pptx?start=01/08/2026&end=06/09/2026")
    assert answer.status_code == 200
    assert "presentationml" in answer.headers["Content-Type"]
    assert ".pptx" in answer.headers["Content-Disposition"]
    assert answer.data[:2] == b"PK"


def test_a_deck_with_no_dates_says_so_rather_than_guessing(signed_in):
    answer = signed_in.get("/projects/1/assistant/deck.pptx", follow_redirects=True)
    assert "needs a start and an end date" in text(answer)


def test_nothing_on_a_slide_falls_off_it(app, project):
    """The one check a generated deck actually needs: every shape inside the
    slide, with a margin. A box half an inch off the right edge is text nobody
    ever sees, and it is invisible in the XML."""
    import re
    from xml.dom.minidom import parseString

    from app.assistant.deck_of import build
    from app.deck import EMU, HEIGHT, WIDTH

    with app.test_request_context():
        data = build(project, "2026-08-01", "2026-09-06")

    edge = int(0.35 * EMU)
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        for name in sorted(n for n in book.namelist()
                           if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)):
            page = parseString(book.read(name))
            for xfrm in page.getElementsByTagName("a:xfrm"):
                off = xfrm.getElementsByTagName("a:off")[0]
                ext = xfrm.getElementsByTagName("a:ext")[0]
                x, y = int(off.getAttribute("x")), int(off.getAttribute("y"))
                cx, cy = int(ext.getAttribute("cx")), int(ext.getAttribute("cy"))
                if not cx and not cy:
                    continue                     # the group's own empty frame
                assert x >= edge and y >= edge, f"{name}: a shape starts at {x},{y}"
                assert x + cx <= WIDTH - edge + 1, f"{name}: a shape runs past the right"
                assert y + cy <= HEIGHT - edge + 1, f"{name}: a shape runs past the foot"
