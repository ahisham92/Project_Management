"""Carmen's conversations: kept, listed, and picked up again.

A question on its own is a search box. What makes an assistant worth having is
that a thread from last Tuesday is still there on Thursday and can be carried
on — so what is checked here is that the conversation lives on the server, that
resuming one gives the model what was already said, and that a manager can see
what the office has been asking.
"""

from __future__ import annotations

import pytest

from app.assistant.runner import Answer


def text(response) -> str:
    return response.get_data(as_text=True)


def _said(app, thread_id, question: str, answer: str, **extra):
    from app.service import record_chat

    with app.app_context():
        return record_chat(1, {"id": 1, "name": "Ahmed"}, question,
                           Answer(text=answer, **extra), thread_id)


@pytest.fixture()
def talked(app):
    """One conversation with two exchanges in it."""
    from app.service import open_thread

    with app.app_context():
        thread = open_thread(1, {"id": 1, "name": "Ahmed"}, "What is late, and by how much?")
    _said(app, thread, "What is late, and by how much?", "Three lines are late.",
          used=["overview"])
    _said(app, thread, "And the worst one?", "2.3, by nine days.")
    return thread


# --- the thread itself ------------------------------------------------------

def test_a_conversation_is_named_after_the_first_thing_asked(app):
    from app.service import load_threads, open_thread

    with app.app_context():
        open_thread(1, {"id": 1, "name": "Ahmed"},
                    "Give the project manager ten percent of every deliverable")
        listed = load_threads(1, 1)

    assert listed[0]["title"].startswith("Give the project manager")


def test_a_long_first_question_is_cut_at_a_word(app):
    from app.service import load_threads, open_thread

    with app.app_context():
        open_thread(1, {"id": 1}, "word " * 40)
        title = load_threads(1)[0]["title"]

    assert len(title) <= 71
    assert title.endswith("…")


def test_the_conversation_holds_what_was_said_on_both_sides(app, talked):
    from app.service import thread_messages

    with app.app_context():
        messages = thread_messages(talked)

    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "What is late, and by how much?"
    assert messages[1]["content"] == "Three lines are late."
    assert messages[1]["used"] == ["overview"]


def test_a_thread_says_how_many_exchanges_it_holds(app, talked):
    from app.service import load_threads

    with app.app_context():
        listed = load_threads(1, 1)
    assert listed[0]["exchanges"] == 2


def test_the_most_recently_used_conversation_is_at_the_top(app):
    from app.db import execute
    from app.service import load_threads, open_thread

    with app.app_context():
        first = open_thread(1, {"id": 1}, "The older one")
        open_thread(1, {"id": 1}, "The newer one")
        # Something said in the older thread brings it back to the top.
        execute("UPDATE chat_threads SET last_at = datetime('now', '+1 minute') WHERE id = ?",
                (first,))
        listed = load_threads(1, 1)

    assert listed[0]["title"] == "The older one"


# --- on the page ------------------------------------------------------------

def test_the_tab_lists_the_conversations_and_opens_one(signed_in, talked):
    page = text(signed_in.get("/projects/1/assistant"))
    assert "New conversation" in page
    assert "What is late, and by how much?" in page

    opened = text(signed_in.get(f"/projects/1/assistant?thread={talked}"))
    assert "Three lines are late." in opened
    assert "2.3, by nine days." in opened
    assert "Read: overview" in opened


def test_an_empty_list_says_so_rather_than_being_blank(signed_in):
    assert "Nothing yet" in text(signed_in.get("/projects/1/assistant"))


def test_a_conversation_can_be_renamed(signed_in, app, talked):
    from app.service import load_thread

    signed_in.post(f"/projects/1/assistant/threads/{talked}/rename",
                   data={"title": "Late deliverables"})
    with app.app_context():
        assert load_thread(1, talked)["title"] == "Late deliverables"


def test_deleting_a_conversation_keeps_what_was_said_in_the_log(signed_in, app, talked):
    """The transcript that goes to Drive is the record of how this is being
    used. Tidying a list is not the same as erasing that."""
    from app.db import query_one
    from app.service import load_thread

    signed_in.post(f"/projects/1/assistant/threads/{talked}/delete")
    with app.app_context():
        assert load_thread(1, talked) is None
        kept = query_one("SELECT COUNT(*) AS n FROM chat_log WHERE question = ?",
                         ("And the worst one?",))
    assert kept["n"] == 1


# --- who sees what ----------------------------------------------------------

def _member(app, email: str, role: str) -> int:
    from app.auth import hash_password
    from app.db import execute, insert

    with app.app_context():
        user_id = insert(
            "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, 'user')",
            (email, email.split("@")[0], hash_password("password123")))
        execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, ?, ?)",
                (user_id, role))
    return user_id


def test_you_see_your_own_conversations(client, app, talked):
    """Somebody else's half-finished thread is not what you want in your list."""
    user_id = _member(app, "member@example.com", "member")
    from app.service import open_thread

    with app.app_context():
        open_thread(1, {"id": user_id, "name": "member"}, "My own question")

    client.post("/login", data={"email": "member@example.com", "password": "password123"})
    page = text(client.get("/projects/1/assistant"))
    assert "My own question" in page
    assert "What is late, and by how much?" not in page


def test_a_manager_can_ask_for_everybody_s(client, app, talked):
    """How it is actually being used is a question the person running the
    project is meant to be able to answer."""
    _member(app, "boss@example.com", "manager")
    client.post("/login", data={"email": "boss@example.com", "password": "password123"})

    mine = text(client.get("/projects/1/assistant"))
    assert "What is late, and by how much?" not in mine
    assert "Everyone" in mine, "a manager is offered the whole list"

    everyone = text(client.get("/projects/1/assistant?who=all"))
    assert "What is late, and by how much?" in everyone
    assert "Ahmed" in everyone, "and whose conversation it is"


def test_somebody_who_is_not_a_manager_cannot_ask_for_everybody_s(client, app, talked):
    _member(app, "member2@example.com", "member")
    client.post("/login", data={"email": "member2@example.com", "password": "password123"})

    page = text(client.get("/projects/1/assistant?who=all"))
    assert "What is late, and by how much?" not in page


def test_a_member_cannot_delete_somebody_else_s_conversation(client, app, talked):
    from app.service import load_thread

    _member(app, "member3@example.com", "member")
    client.post("/login", data={"email": "member3@example.com", "password": "password123"})
    answer = client.post(f"/projects/1/assistant/threads/{talked}/delete",
                         follow_redirects=True)

    assert "somebody else" in text(answer)
    with app.app_context():
        assert load_thread(1, talked) is not None


# --- what it costs ----------------------------------------------------------

def test_a_long_conversation_does_not_send_itself_back_without_limit(app, talked):
    """Resuming costs input tokens, so the history that goes to the model is
    trimmed the same way it always was — a thread that runs all afternoon does
    not grow the bill without bound."""
    from app.assistant.runner import KEEP_TURNS, _trim

    with app.app_context():
        from app.service import thread_messages

        for n in range(20):
            _said(app, talked, f"Question {n}", f"Answer {n}")
        messages = thread_messages(talked)

    assert len(messages) > KEEP_TURNS
    assert len(_trim([{"role": m["role"], "content": m["content"]} for m in messages])) \
        == KEEP_TURNS
