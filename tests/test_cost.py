"""What Carmen costs to run, and the four things that keep it down.

None of this shows on the screen except as a number nobody has to act on. That
is the point: an assistant that gets steadily more expensive the more it is used
is one that quietly stops being used.

The four:
  * the standing prompt and the tool catalogue are marked to be kept between
    turns, so they are charged at a tenth after the first question;
  * a long conversation sends its recent turns and a short note of the rest,
    rather than the whole afternoon;
  * a question asked again while nothing on the project has changed is answered
    from what she said last time, without asking at all;
  * and what all that saves is counted, so it can be looked at.
"""

from __future__ import annotations

import pytest

from app.assistant.runner import Answer, ask


class _Reply:
    """One answer from the API, in the shape the SDK hands back."""

    def __init__(self, text: str, usage=None):
        self.content = [type("Block", (), {"type": "text", "text": text})()]
        self.stop_reason = "end_turn"
        self.usage = usage


class _Usage:
    def __init__(self, fresh=1000, out=200, read=0, written=0):
        self.input_tokens = fresh
        self.output_tokens = out
        self.cache_read_input_tokens = read
        self.cache_creation_input_tokens = written


@pytest.fixture()
def project(app):
    from app.db import query_one

    with app.app_context():
        return dict(query_one("SELECT * FROM projects WHERE id = 1"))


# --- the prompt and the tools are kept between turns ------------------------

def test_the_standing_prompt_and_the_tool_catalogue_are_marked_to_be_kept(monkeypatch):
    """They are the same on every turn and together they are most of what goes
    up, so keeping them is the single biggest saving available."""
    import app.claude as claude

    sent = {}

    class _Messages:
        def create(self, **body):
            sent.update(body)
            return _Reply("fine")

    monkeypatch.setattr(claude, "client",
                        lambda key: type("C", (), {"messages": _Messages()})())
    claude.chat("k", "the standing instruction",
                [{"role": "user", "content": "hello"}],
                [{"name": "one", "input_schema": {}}, {"name": "two", "input_schema": {}}])

    assert sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" in sent["tools"][-1], "the mark covers the catalogue before it"
    assert "cache_control" not in sent["tools"][0]


def test_marking_the_catalogue_does_not_change_the_catalogue(monkeypatch):
    """It is built once and handed to every conversation, so it is copied
    rather than edited where it stands."""
    import app.claude as claude

    monkeypatch.setattr(claude, "client",
                        lambda key: type("C", (), {"messages": type(
                            "M", (), {"create": lambda self, **body: _Reply("fine")})()})())
    catalogue = [{"name": "one", "input_schema": {}}]
    claude.chat("k", "s", [{"role": "user", "content": "hi"}], catalogue)
    assert "cache_control" not in catalogue[0]


def test_what_a_turn_cost_is_read_off_the_answer():
    from app.claude import spent

    counted = spent(_Reply("x", _Usage(fresh=900, out=120, read=8000, written=200)))
    assert counted == {"input": 900, "output": 120,
                       "cache_read": 8000, "cache_written": 200}
    assert spent(_Reply("x")) == {}, "an answer with no usage on it costs nothing known"


# --- a question asked again ------------------------------------------------

def test_the_same_question_twice_is_only_asked_once(app, project, monkeypatch):
    """The figures come from the project, and the project has not moved."""
    import app.claude as claude

    calls = []

    def _chat(key, system, messages, tools=None, model="", effort=""):
        calls.append(messages)
        return _Reply("Three lines are late.", _Usage())

    monkeypatch.setattr(claude, "chat", _chat)

    with app.app_context():
        first = ask(project, "What is late?", "key")
        second = ask(project, "what is late", "key")       # the same, said differently

    assert len(calls) == 1, "the second question did not need asking"
    assert second.text == first.text
    assert second.from_cache is True and first.from_cache is False


def test_a_change_on_the_project_makes_it_ask_again(app, project, monkeypatch):
    import app.claude as claude

    calls = []

    def _chat(key, system, messages, tools=None, model="", effort=""):
        calls.append(messages)
        return _Reply(f"Answer {len(calls)}", _Usage())

    monkeypatch.setattr(claude, "chat", _chat)

    with app.app_context():
        ask(project, "What is late?", "key")

    # Anything at all: the counter the live refresh reads moves on every write.
    signed = app.test_client()
    signed.post("/login", data={"email": "admin@example.com", "password": "changeme123"})
    signed.post("/projects/1/tasks/1/progress",
                data={"status_key": "idc", "data_date": "07/09/2026"})

    with app.app_context():
        again = ask(project, "What is late?", "key")

    assert len(calls) == 2, "the project moved, so the answer had to be worked out again"
    assert again.from_cache is False


class _ToolReply:
    """An answer that asks for a tool to be run."""

    def __init__(self, name: str, arguments: dict):
        self.content = [type("Block", (), {"type": "tool_use", "id": "t1",
                                           "name": name, "input": arguments})()]
        self.stop_reason = "tool_use"
        self.usage = _Usage()


def test_an_answer_that_stages_a_change_is_never_kept(app, project, monkeypatch):
    """What those produce is not just words: the change has to be staged again
    for the reader to approve, so it cannot be handed back from memory."""
    import app.claude as claude

    def _chat(key, system, messages, tools=None, model="", effort=""):
        # Ask for the tool the first time round; say something once the result
        # has come back. Which round it is reads off what was sent.
        content = messages[-1].get("content")
        answered = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        return (_Reply("I have staged that.", _Usage()) if answered
                else _ToolReply("set_progress", {"reference": "1.1", "percent": 40}))

    monkeypatch.setattr(claude, "chat", _chat)
    with app.app_context():
        from app.service import remembered_answer

        answer = ask(project, "Set 1.1 to 40%", "key")
        assert answer.staged, "the change should have been staged"
        assert remembered_answer(1, "Set 1.1 to 40%") is None

        again = ask(project, "Set 1.1 to 40%", "key")
    assert again.from_cache is False
    assert again.staged, "asked again, it stages the change again"


def test_a_question_with_a_file_on_it_is_always_answered_properly(app, project, monkeypatch):
    import app.claude as claude

    calls = []

    def _chat(key, system, messages, tools=None, model="", effort=""):
        calls.append(messages)
        return _Reply("It says the survey starts in September.", _Usage())

    monkeypatch.setattr(claude, "chat", _chat)
    attached = [{"kind": "text", "name": "letter.txt", "bytes": 20,
                 "words": "The survey starts in September."}]
    with app.app_context():
        ask(project, "What does this say?", "key", attachments=attached)
        ask(project, "What does this say?", "key", attachments=attached)
    assert len(calls) == 2


def test_the_kept_answers_can_be_thrown_away(app, project, monkeypatch):
    import app.claude as claude

    monkeypatch.setattr(claude, "chat",
                        lambda *a, **k: _Reply("Three lines are late.", _Usage()))
    with app.app_context():
        from app.service import forget_answers, remembered_answer

        ask(project, "What is late?", "key")
        assert remembered_answer(1, "What is late?") is not None
        assert forget_answers(1) == 1
        assert remembered_answer(1, "What is late?") is None


# --- and it is counted ------------------------------------------------------

def test_what_it_has_cost_is_added_up_and_can_be_looked_at(app):
    from app.service import chat_spend, record_chat

    with app.app_context():
        record_chat(1, {"id": 1, "name": "Ahmed"}, "One?",
                    Answer(text="Yes", spent={"input": 900, "output": 120,
                                              "cache_read": 8000, "cache_written": 400}))
        record_chat(1, {"id": 1, "name": "Ahmed"}, "Two?",
                    Answer(text="Yes", spent={"input": 100, "output": 40,
                                              "cache_read": 9000}))
        record_chat(1, {"id": 1, "name": "Ahmed"}, "One?",
                    Answer(text="Yes", from_cache=True))

        spend = chat_spend(1)

    assert spend["asked"] == 3
    assert spend["fresh"] == 1000 and spend["written"] == 160
    assert spend["cached"] == 17000
    assert spend["answered_free"] == 1
    assert spend["cached_share"] > 0.9, "nearly all of what went in was read back"


def test_the_carmen_tab_says_what_she_has_cost(signed_in, app):
    from app.service import record_chat

    with app.app_context():
        record_chat(1, {"id": 1, "name": "Ahmed"}, "One?",
                    Answer(text="Yes", spent={"input": 900, "output": 120, "cache_read": 8000}))
    import re

    body = re.sub(r"\s+", " ", signed_in.get("/projects/1/assistant").get_data(as_text=True))
    assert "What she costs" in body
    assert "read back out of the cache" in body
    assert "8,900</strong> tokens in" in body
