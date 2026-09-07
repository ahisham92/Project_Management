"""Carmen: minuting a meeting, going places, her face, and the chat log.

What is worth testing here is the half either side of the model. Turning a
paragraph somebody typed into numbered items is the model's job; putting those
items in the register with numbers that cannot collide, owners that are real
party codes and dates that parse is this code's, and that is what is checked.
"""

from __future__ import annotations

import pytest

from app.assistant import tools
from app.assistant.runner import ApplyError, apply
from app.assistant.tools import ToolError


def text(response) -> str:
    return response.get_data(as_text=True)


MEETING = {
    "register": "client", "ref": "MOM-04", "title": "Design coordination",
    "date": "10/09/2026", "time": "11:00", "location": "Teams",
    "attendees": [
        {"name": "Jihad Zuhairy", "organisation": "Sibline", "role": "Port Manager"},
        {"name": "Ahmed Mitwally", "organisation": "Dar", "role": "Lead", "present": False},
    ],
    "items": [
        {"subject": "Bathymetry survey", "discussion": "The client asked when it starts.",
         "agreement": "Dar to issue the brief.", "owner": "PM", "impact": "time",
         "due": "20/09/2026"},
        {"subject": "Vessel category", "agreement": "Confirmed on the call.",
         "owner": "Client", "closed": True},
    ],
}


def _minute(app, **extra):
    with app.app_context():
        staged = tools.run("minute_meeting", 1, dict(MEETING, **extra))
        apply(1, [staged], user_id=1)
        return staged


# --- minuting a meeting -----------------------------------------------------

def test_a_typed_up_meeting_becomes_a_numbered_register(app):
    from app.service import load_meetings, meeting_sheet, today

    _minute(app)
    with app.app_context():
        meeting = [m for m in load_meetings(1) if m["ref"] == "MOM-04"][0]
        sheet = meeting_sheet(1, meeting["id"], today())

    assert meeting["item_count"] == 2
    # Numbers are positions, set here rather than taken from anything the model
    # said, so they cannot collide and cannot be typed wrong.
    assert [i["ref"] for i in sheet["items"]] == ["4.1", "4.2"]
    assert sheet["items"][0]["owner_label"] == "PM"
    assert sheet["items"][0]["impact"] == "time"
    assert sheet["items"][0]["due_date"] == "2026-09-20"


def test_an_item_agreed_on_the_call_is_closed_on_the_day_of_the_meeting(app):
    from app.service import load_items

    _minute(app)
    with app.app_context():
        done = [i for i in load_items(1) if i["subject"] == "Vessel category"][0]

    assert done["is_open"] is False
    assert done["closed_date"] == "2026-09-10"


def test_who_was_there_is_recorded_and_who_was_not_is_too(app):
    from app.service import load_attendance, load_meetings

    _minute(app)
    with app.app_context():
        meeting = [m for m in load_meetings(1) if m["ref"] == "MOM-04"][0]
        ticks = load_attendance(meeting["id"])

    assert meeting["present_count"] == 1              # one of the two sent apologies
    assert len(ticks) == 2                            # both were invited


def test_somebody_named_in_the_minutes_joins_the_attendance_list(app):
    """The alternative is a set of minutes with an attendance table of nobody."""
    from app.service import load_attendees

    _minute(app)
    with app.app_context():
        names = {a["name"] for a in load_attendees(1)}
    assert {"Jihad Zuhairy", "Ahmed Mitwally"} <= names


def test_minuting_twice_does_not_duplicate_the_attendance_list(app):
    from app.service import load_attendees

    _minute(app)
    _minute(app, ref="MOM-05")
    with app.app_context():
        names = [a["name"] for a in load_attendees(1)]
    assert names.count("Jihad Zuhairy") == 1


def test_the_meeting_carries_the_register_it_was_minuted_in(app):
    from app.service import load_items, load_meetings

    _minute(app, register="internal", ref="WK-99")
    with app.app_context():
        internal = [m for m in load_meetings(1, "internal") if m["ref"] == "WK-99"]
        items = [i for i in load_items(1, kind="internal") if i["subject"] == "Bathymetry survey"]
    assert len(internal) == 1
    assert len(items) == 1


def test_minutes_with_no_title_at_all_are_refused(app):
    with app.app_context():
        with pytest.raises(ToolError):
            tools.run("minute_meeting", 1, {"title": "", "purpose": ""})


def test_an_item_with_neither_subject_nor_agreement_is_dropped_rather_than_saved_blank(app):
    with app.app_context():
        staged = tools.run("minute_meeting", 1, {
            "title": "A meeting",
            "items": [{"subject": "Real"}, {"discussion": "only chatter"}]})
    assert len(staged["items"]) == 1


def test_a_date_that_does_not_parse_stops_the_whole_thing(app):
    """Better than minuting nine items correctly and the tenth with no date."""
    with app.app_context():
        with pytest.raises(ToolError):
            tools.run("minute_meeting", 1, {
                "title": "A meeting", "items": [{"subject": "x", "due": "next Tuesday"}]})


def test_an_owner_that_is_not_a_party_code_comes_out_blank_rather_than_wrong(app):
    with app.app_context():
        staged = tools.run("minute_meeting", 1, {
            "title": "A meeting", "items": [{"subject": "x", "owner": "Bob from marine"}]})
    assert staged["items"][0]["owner"] == ""


# --- adding to and correcting what is minuted -------------------------------

def test_more_items_can_be_added_to_a_meeting_that_exists(app):
    from app.service import meeting_sheet, load_meetings, today

    _minute(app)
    with app.app_context():
        staged = tools.run("add_minute_items", 1, {
            "meeting": "MOM-04",
            "items": [{"subject": "Hoppers", "agreement": "Client to confirm.", "owner": "Client"}]})
        apply(1, [staged], user_id=1)
        meeting = [m for m in load_meetings(1) if m["ref"] == "MOM-04"][0]
        sheet = meeting_sheet(1, meeting["id"], today())

    assert [i["ref"] for i in sheet["items"]] == ["4.1", "4.2", "4.3"]


def test_a_meeting_nobody_has_is_refused_with_help(app):
    with app.app_context():
        with pytest.raises(ToolError) as raised:
            tools.run("add_minute_items", 1, {"meeting": "MOM-99", "items": [{"subject": "x"}]})
    assert "list_meetings" in str(raised.value)


def test_correcting_one_field_leaves_the_others_alone(app):
    """Fixing an owner must not blank an agreement somebody spent ten minutes
    wording."""
    from app.service import load_items

    _minute(app)
    with app.app_context():
        staged = tools.run("update_minute_item", 1, {"reference": "4.1", "owner": "MR"})
        apply(1, [staged], user_id=1)
        item = [i for i in load_items(1) if i["ref"] == "4.1"][0]

    assert item["owner_label"] == "MR"
    assert item["agreement"] == "Dar to issue the brief."
    assert item["discussion"] == "The client asked when it starts."


def test_an_item_can_be_found_by_its_words_as_well_as_its_number(app):
    _minute(app)
    with app.app_context():
        staged = tools.run("update_minute_item", 1,
                           {"reference": "bathymetry", "due": "25/09/2026"})
    assert staged["item_id"]
    assert staged["fields"]["due_date"] == "2026-09-25"


def test_a_correction_with_nothing_to_correct_is_refused(app):
    _minute(app)
    with app.app_context():
        with pytest.raises(ToolError):
            tools.run("update_minute_item", 1, {"reference": "4.1"})


def test_only_the_fields_it_knows_about_can_be_written(app):
    """The staged list comes back from the page, so it is checked again on the
    way in."""
    _minute(app)
    from app.db import query_one

    with app.app_context():
        item = query_one("SELECT id FROM meeting_items WHERE ref = '4.1' AND project_id = 1")
        with pytest.raises(ApplyError):
            apply(1, [{"kind": "update_minute_item", "item_id": item["id"],
                       "fields": {"project_id": 2}}], user_id=1)


def test_the_issue_details_reach_the_word_document(app):
    from app.db import query_one
    from app.minutes_doc import minutes_document
    from app.service import load_meetings, meeting_sheet, today

    _minute(app)
    with app.app_context():
        staged = tools.run("issue_details", 1, {
            "meeting": "MOM-04", "prepared_by": "Ola Bou Ghannam",
            "reviewed_by": "Jihad Zuhairy", "issue_date": "11/09/2026",
            "attachment": "Coordination pack."})
        apply(1, [staged], user_id=1)

        meeting = [m for m in load_meetings(1) if m["ref"] == "MOM-04"][0]
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        document = minutes_document(project, meeting_sheet(1, meeting["id"], today()))

    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(document)) as book:
        body = book.read("word/document.xml").decode("utf-8")
    assert "Ola Bou Ghannam" in body
    assert "Jihad Zuhairy" in body
    assert "11/09/2026" in body
    assert "Coordination pack." in body


# --- taking somebody somewhere ----------------------------------------------

def test_asked_to_be_taken_somewhere_she_goes_rather_than_offering_a_link(app):
    with app.test_request_context():
        seen = tools.run("open_view", 1, {"view": "schedule"})
    assert seen["go"] is True
    assert seen["url"].endswith("/projects/1/schedule")


def test_printing_does_not_navigate_away(app):
    """The print dialog belongs where the reader already is."""
    with app.test_request_context():
        seen = tools.run("open_view", 1, {"view": "budget", "printable": True})
    assert "print=1" in seen["url"]


def test_a_link_can_be_offered_instead_of_taken(app):
    with app.test_request_context():
        seen = tools.run("open_view", 1, {"view": "minutes", "go": False})
    assert seen["go"] is False


# --- she is on every page ---------------------------------------------------

def test_carmen_sits_in_the_corner_of_every_project_page(signed_in):
    for url in ("/projects/1/", "/projects/1/schedule", "/projects/1/tasks",
                "/projects/1/minutes", "/projects/1/internal", "/projects/1/setup"):
        body = text(signed_in.get(url))
        assert 'id="carmen-popup"' in body, f"{url} has no Carmen"
        assert "Ask Carmen" in body


def test_she_starts_minimised_on_every_page(signed_in):
    """A chat box that reappears in the corner of every tab because it was
    opened once is not a feature."""
    body = text(signed_in.get("/projects/1/schedule"))
    popup = body.split('id="carmen-popup"', 1)[1].split(">", 1)[0]
    assert "hidden" in popup


def test_she_is_not_doubled_up_on_her_own_tab(signed_in):
    """The whole page is already the conversation there."""
    body = text(signed_in.get("/projects/1/assistant"))
    assert 'id="carmen-popup"' not in body
    assert 'id="chat"' in body


def test_she_is_not_offered_outside_a_project(signed_in):
    """Everything she can do is scoped to one, so a chat with no project is a
    chat that can only disappoint."""
    for url in ("/", "/backups", "/help"):
        assert 'id="carmen-popup"' not in text(signed_in.get(url))


def test_the_pop_up_and_the_tab_are_the_same_conversation(signed_in):
    """One initialiser drives both, so there is no second chat to keep in step."""
    body = text(signed_in.get("/projects/1/schedule"))
    assert "data-carmen" in body and "data-chat-form" in body


# --- her face ---------------------------------------------------------------

def test_she_has_a_face_before_anybody_uploads_one(signed_in):
    answer = signed_in.get("/projects/1/assistant/face")
    assert answer.status_code == 200
    assert answer.mimetype == "image/svg+xml"
    assert b"<svg" in answer.data


def test_a_picture_can_be_uploaded_and_is_kept_out_of_the_repository(signed_in, app):
    from io import BytesIO
    from pathlib import Path

    from app.views import carmen_avatar as avatar

    png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + b"IHDR" + b"\x00" * 40)
    signed_in.post("/projects/1/assistant/face",
                   data={"picture": (BytesIO(png), "carmen.png")},
                   content_type="multipart/form-data", follow_redirects=True)

    with app.app_context():
        where = avatar.saved()
        assert where is not None
        assert where.parent == Path(app.config["DATABASE"]).parent

    answer = signed_in.get("/projects/1/assistant/face")
    assert answer.mimetype == "image/png"


def test_something_that_is_not_a_picture_is_refused(signed_in, app):
    from io import BytesIO

    from app.views import carmen_avatar as avatar

    answer = signed_in.post("/projects/1/assistant/face",
                            data={"picture": (BytesIO(b"#!/bin/sh\nrm -rf /"), "nasty.png")},
                            content_type="multipart/form-data", follow_redirects=True)
    assert "not a JPEG, PNG or WebP" in text(answer)
    with app.app_context():
        assert avatar.saved() is None


def test_only_an_administrator_changes_her_picture(client, app):
    from io import BytesIO

    from app.auth import hash_password
    from app.db import execute, insert

    with app.app_context():
        user_id = insert("INSERT INTO users (email, name, password_hash, role) "
                         "VALUES (?, ?, ?, 'user')",
                         ("member@example.com", "Member", hash_password("password123")))
        execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, ?, 'manager')",
                (user_id,))
    client.post("/login", data={"email": "member@example.com", "password": "password123"})

    answer = client.post("/projects/1/assistant/face",
                         data={"picture": (BytesIO(b"\xff\xd8\xff" + b"0" * 20), "c.jpg")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "Only an administrator" in text(answer)


# --- the chat log -----------------------------------------------------------

def _say(app, question: str, answer_text: str = "", **extra):
    from app.assistant.runner import Answer
    from app.service import record_chat

    with app.app_context():
        return record_chat(1, {"id": 1, "name": "Ahmed"}, question,
                           Answer(text=answer_text, **extra))


def test_every_exchange_is_written_down(app):
    from app.service import load_chats

    _say(app, "How is it going?", "Behind plan.", used=["overview"])
    with app.app_context():
        rows = load_chats()

    assert rows[-1]["question"] == "How is it going?"
    assert rows[-1]["answer"] == "Behind plan."
    assert rows[-1]["tools_used"] == "overview"
    assert rows[-1]["user_name"] == "Ahmed"


def test_a_failure_is_written_down_too(app):
    """A week of failures is the thing worth noticing, and it is invisible if
    only the answers are kept."""
    from app.service import load_chats

    _say(app, "anything", trouble="Forbidden (403), and Anthropic said nothing")
    with app.app_context():
        rows = load_chats()
    assert "403" in rows[-1]["trouble"]


def test_applying_what_was_proposed_is_counted_against_the_question(app):
    from app.service import load_chats, note_applied

    chat_id = _say(app, "set 1.1 to 40", "Staged.", staged=[{"says": "x"}])
    with app.app_context():
        note_applied(chat_id, 1)
        row = [r for r in load_chats() if r["id"] == chat_id][0]
    assert row["staged"] == 1 and row["applied"] == 1


def test_the_days_transcript_reads_without_this_program(app):
    from app.service import chat_transcript, today

    _say(app, "How is it going?", "Behind plan.", used=["overview"])
    with app.app_context():
        said = chat_transcript(today())

    assert "Carmen" in said
    assert "asked: How is it going?" in said
    assert "said:  Behind plan." in said
    assert "read:  overview" in said


def test_a_day_nobody_asked_anything_still_produces_a_file(app):
    from app.service import chat_transcript

    with app.app_context():
        said = chat_transcript("2020-01-01")
    assert "Nobody asked her anything" in said


def test_a_multi_line_answer_stays_readable_in_the_transcript(app):
    from app.service import chat_transcript, today

    _say(app, "list them", "One line.\nAnother line.")
    with app.app_context():
        said = chat_transcript(today())
    assert "  said:  One line." in said
    assert "         Another line." in said


def test_the_transcript_is_not_uploaded_when_drive_is_not_connected(app, monkeypatch):
    from app import vault
    from app.service import upload_chat_log

    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with app.app_context():
        vault.forget()
        result = upload_chat_log()
    assert result["ok"] is False
    assert "not connected" in result["detail"]


def test_the_transcript_goes_up_under_the_day_it_covers(app, monkeypatch):
    from app import drive, vault
    from app.service import upload_chat_log

    sent = {}

    def fake_upload(settings, data, name=""):
        sent["name"] = name
        sent["data"] = data
        return {"id": "abc", "replaced": False, "link": "https://drive/x"}

    monkeypatch.setattr(drive, "upload", fake_upload)
    with app.app_context():
        vault.write({"client_id": "a", "client_secret": "b", "refresh_token": "c"})
        result = upload_chat_log("2026-09-06")

    assert result["ok"] is True
    assert sent["name"] == "project-control-chats-2026-09-06.txt"
    assert b"Carmen" in sent["data"]


def test_asking_writes_a_line_in_the_log_through_the_page(signed_in, app, monkeypatch):
    from app import claude, vault
    from tests.test_assistant import Reply, StandInClaude, _call

    with app.app_context():
        vault.write({"anthropic_key": "sk-ant-x"})
    monkeypatch.setattr(claude, "chat", StandInClaude(
        Reply(calls=[_call("overview", {})]),
        Reply(text="It is behind.")))

    answer = signed_in.post("/projects/1/assistant/ask", json={"question": "how is it?"})
    said = answer.get_json()
    assert said["chat_id"]

    from app.service import load_chats

    with app.app_context():
        rows = load_chats()
    assert rows[-1]["question"] == "how is it?"
    assert rows[-1]["answer"] == "It is behind."


# --- why nothing works ------------------------------------------------------

def test_the_diagnosis_tells_the_host_apart_from_the_key(app, monkeypatch):
    """A 403 from a host's outbound proxy and a 403 from Anthropic read
    identically in a log and need completely different fixes."""
    import socket

    from app import claude

    def refuse(*_args, **_kwargs):
        raise OSError("Connection refused")

    monkeypatch.setattr(socket, "create_connection", refuse)
    found = claude.diagnose("sk-ant-x")
    assert found["reachable"] is False
    assert "PythonAnywhere" in found["detail"]


def test_a_403_with_no_message_is_explained_as_the_host(app):
    import anthropic

    from app.claude import _why

    said = _why(anthropic.PermissionDeniedError.__new__(anthropic.PermissionDeniedError))
    assert "never reached them" in said
    assert "PythonAnywhere" in said


def test_a_403_that_anthropic_itself_sent_is_explained_as_the_key(app):
    import anthropic

    from app.claude import _why

    refusal = anthropic.PermissionDeniedError.__new__(anthropic.PermissionDeniedError)
    refusal.message = "Your organization has been disabled"
    said = _why(refusal)
    assert "not the network" in said
    assert "Your organization has been disabled" in said


def test_a_bad_key_is_named_as_a_bad_key(app):
    import anthropic

    from app.claude import _why

    said = _why(anthropic.AuthenticationError.__new__(anthropic.AuthenticationError))
    assert "did not accept that API key" in said


def test_being_unable_to_reach_anthropic_is_not_read_as_a_bad_key(app):
    import anthropic

    from app.claude import _why

    said = _why(anthropic.APIConnectionError.__new__(anthropic.APIConnectionError))
    assert "Could not reach api.anthropic.com" in said


def test_the_sdk_being_missing_is_its_own_answer(app, monkeypatch):
    """On a host where the web app runs in a virtualenv, `pip install` in a
    console installs somewhere else. That looks like every other failure from a
    browser and needs a completely different fix, so it is named."""
    import builtins

    from app import claude

    real = builtins.__import__

    def hide(name, *rest):
        if name == "anthropic":
            raise ImportError("No module named 'anthropic'")
        return real(name, *rest)

    monkeypatch.setattr(builtins, "__import__", hide)
    found = claude.diagnose("sk-ant-x")
    assert found["installed"] is False
    assert "not installed for the Python running this app" in found["detail"]


def test_an_unexpected_failure_is_named_rather_than_swallowed(app, monkeypatch):
    """"Could not be reached" for a TypeError sends somebody to check a key, a
    network and a host that were all fine."""
    from app import claude

    class Boom:
        def __init__(self, *a, **k):
            pass

        @property
        def messages(self):
            raise TypeError("unexpected keyword argument 'effort'")

    monkeypatch.setattr(claude, "client", lambda key: Boom())
    with app.app_context():
        try:
            claude.chat("k", "system", [{"role": "user", "content": "hi"}])
        except claude.ClaudeError as exc:
            assert "TypeError" in str(exc)
            assert "effort" in str(exc)
        else:
            raise AssertionError("that should not have succeeded")


def test_asking_never_answers_with_html_when_something_goes_wrong(signed_in, app, monkeypatch):
    """The page can only show what it is given."""
    from app import claude, vault

    with app.app_context():
        vault.write({"anthropic_key": "sk-ant-x"})

    def explode(*_args, **_kwargs):
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr("app.assistant.ask", explode)
    answer = signed_in.post("/projects/1/assistant/ask", json={"question": "hello"})
    assert answer.status_code == 500
    assert answer.is_json
    assert "something nobody predicted" in answer.get_json()["error"]


def test_the_badge_only_claims_a_key_is_set(signed_in, app):
    """It never knew anything more than that, and saying "connected" sent
    somebody looking for a fault that was not where they were told."""
    from app import vault

    with app.app_context():
        vault.write({"anthropic_key": "sk-ant-x"})
    body = text(signed_in.get("/projects/1/assistant"))
    assert "key set" in body
    assert "Ask her one question" in body


def test_one_real_question_is_what_proves_she_works(signed_in, app, monkeypatch):
    from app import claude, vault
    from tests.test_assistant import Reply, StandInClaude

    with app.app_context():
        vault.write({"anthropic_key": "sk-ant-x"})
    monkeypatch.setattr(claude, "chat", StandInClaude(Reply(text="ready.")))

    answer = signed_in.get("/projects/1/assistant/ping").get_json()
    assert answer["ok"] is True
    assert "ready." in answer["detail"]


def test_a_failing_ping_says_why(signed_in, app, monkeypatch):
    from app import claude, vault

    with app.app_context():
        vault.write({"anthropic_key": "sk-ant-x"})

    def refuse(*_args, **_kwargs):
        raise claude.ClaudeError("Anthropic did not accept that API key (401).")

    monkeypatch.setattr(claude, "chat", refuse)
    answer = signed_in.get("/projects/1/assistant/ping")
    assert answer.status_code == 502
    assert "401" in answer.get_json()["error"]


def test_only_an_administrator_can_run_the_test(client, app):
    from app.auth import hash_password
    from app.db import execute, insert

    with app.app_context():
        user_id = insert("INSERT INTO users (email, name, password_hash, role) "
                         "VALUES (?, ?, ?, 'user')",
                         ("look2@example.com", "Look", hash_password("password123")))
        execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, ?, 'viewer')",
                (user_id,))
    client.post("/login", data={"email": "look2@example.com", "password": "password123"})
    assert client.get("/projects/1/assistant/test").status_code == 403


# --- one key, everybody -----------------------------------------------------

def test_the_key_is_the_installations_not_one_persons(app):
    """Set once, everybody uses it — which is the answer to "does the other
    administrator need their own?"."""
    from app import vault

    with app.app_context():
        vault.write({"anthropic_key": "sk-ant-shared"})
        assert vault.carmen()["key"] == "sk-ant-shared"

    # Nothing about it is per user: it is one file beside the database.
    with app.app_context():
        assert "user" not in vault.read()
