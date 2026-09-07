"""Files to Carmen and documents back from her.

Claude reads a PDF and a picture as themselves; a Word or PowerPoint file it
does not read at all, so those are unzipped here and the words pulled out. What
is worth checking is that each kind arrives in the shape the API takes, that
what somebody attached is kept with the conversation, and that a file she hands
back is a link rather than a change to approve.
"""

from __future__ import annotations

import io

import pytest

from app.pdf import Document as PdfDocument
from app.reading import ReadError, as_content, looks_like, read
from app.word import Document as WordDocument


def text(response) -> str:
    return response.get_data(as_text=True)


@pytest.fixture()
def connected(signed_in, app):
    """A key on the installation, so a question is actually attempted.

    Without one the ask is refused before anything is read, which is right —
    a file should not be kept for a question that cannot be asked.
    """
    signed_in.post("/projects/1/assistant/settings",
                   data={"anthropic_key": "sk-ant-test", "back": "setup"})
    yield signed_in
    from app import vault

    with app.app_context():
        vault.forget()


def a_word_file(words: str = "The client has asked for the survey to start earlier.") -> bytes:
    doc = WordDocument(title="Letter")
    doc.add_heading("Sibline Port", 1)
    doc.add_paragraph(words)
    return doc.render()


def a_pdf(words: str = "Drawing register") -> bytes:
    doc = PdfDocument(title=words)
    doc.add_paragraph(words)
    return doc.render()


def a_deck(words: str = "Progress to date") -> bytes:
    from app.deck import Deck

    deck = Deck()
    deck.cover(words, "Sibline Port")
    return deck.save(words)


# --- reading what arrives ---------------------------------------------------

def test_a_pdf_goes_to_the_model_as_a_pdf():
    """Claude reads a PDF itself — pulling the words out here would throw away
    the drawings and the layout, which is most of what a PDF is."""
    got = read(a_pdf(), "register.pdf")
    assert got["kind"] == "pdf"
    assert got["block"]["type"] == "document"
    assert got["block"]["source"]["media_type"] == "application/pdf"
    assert got["block"]["source"]["type"] == "base64"


def test_a_picture_goes_as_a_picture():
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    got = read(png, "site.png")
    assert got["kind"] == "image"
    assert got["block"]["type"] == "image"
    assert got["block"]["source"]["media_type"] == "image/png"


def test_a_word_file_is_unzipped_and_its_words_read():
    """The API does not take a .docx, so it is read here — a .docx is a zip of
    XML and the standard library opens it."""
    got = read(a_word_file(), "letter.docx")
    assert got["kind"] == "docx"
    assert "block" not in got
    assert "survey to start earlier" in got["words"]
    assert "Sibline Port" in got["words"]


def test_a_powerpoint_is_read_slide_by_slide():
    got = read(a_deck(), "progress.pptx")
    assert got["kind"] == "pptx"
    assert "Slide 1" in got["words"]
    assert "Progress to date" in got["words"]


def test_plain_text_is_read_as_it_is():
    got = read(b"1.1 is late by nine days", "note.txt")
    assert got["kind"] == "text"
    assert got["words"] == "1.1 is late by nine days"


def test_something_unreadable_says_what_can_be_attached():
    with pytest.raises(ReadError) as refused:
        read(b"\x00\x01\x02\x03binary nonsense\xff\xfe", "mystery.bin")
    assert "PDF" in str(refused.value) and "PowerPoint" in str(refused.value)


def test_an_empty_file_is_refused():
    with pytest.raises(ReadError):
        read(b"", "nothing.pdf")


def test_a_file_too_big_to_be_meant_is_refused():
    with pytest.raises(ReadError) as refused:
        read(b"%PDF-" + b"0" * (11 * 1024 * 1024), "huge.pdf")
    assert "MB" in str(refused.value)


def test_what_it_is_is_read_from_the_file_not_its_name():
    """A .docx that is really a PDF is a PDF."""
    assert looks_like(a_pdf(), "letter.docx") == "pdf"
    assert looks_like(a_word_file(), "anything.pdf") == "docx"


# --- how it reaches the model -----------------------------------------------

def test_the_question_comes_after_what_was_attached():
    content = as_content("What does this ask us to do?",
                         [read(a_pdf(), "letter.pdf"), read(a_word_file(), "note.docx")])
    assert [block["type"] for block in content] == ["document", "text"]
    said = content[-1]["text"]
    assert said.index("note.docx") < said.index("What does this ask us to do?")
    assert "end of what was attached" in said


def test_words_from_a_file_are_marked_as_such():
    """So an answer does not treat a client's letter as an instruction the
    reader typed."""
    content = as_content("Summarise it", [read(a_word_file(), "client-letter.docx")])
    assert "--- client-letter.docx (docx) ---" in content[-1]["text"]


def test_a_question_with_nothing_attached_is_still_just_a_question():
    assert as_content("How is it going?", []) == "How is it going?"


# --- on the way through the app ---------------------------------------------

def test_an_attached_file_is_kept_with_the_conversation(connected, signed_in, app):
    from app.service import open_thread, thread_files

    with app.app_context():
        thread = open_thread(1, {"id": 1, "name": "Ahmed"}, "About the letter")

    signed_in.post("/projects/1/assistant/ask", data={
        "question": "What does this say?", "thread_id": str(thread),
        "files": (io.BytesIO(a_word_file()), "letter.docx"),
    }, content_type="multipart/form-data")

    with app.app_context():
        kept = thread_files(thread)
    assert len(kept) == 1
    assert kept[0]["name"] == "letter.docx" and kept[0]["kind"] == "docx"


def test_a_kept_file_can_be_read_back(connected, signed_in, app):
    from app.service import open_thread, thread_files

    with app.app_context():
        thread = open_thread(1, {"id": 1}, "About the register")
    signed_in.post("/projects/1/assistant/ask", data={
        "question": "What is in this?", "thread_id": str(thread),
        "files": (io.BytesIO(a_pdf()), "register.pdf"),
    }, content_type="multipart/form-data")

    with app.app_context():
        kept = thread_files(thread)[0]
    answer = signed_in.get(f"/projects/1/assistant/files/{kept['id']}")
    assert answer.status_code == 200
    assert answer.mimetype == "application/pdf"
    assert answer.data[:5] == b"%PDF-"


def test_a_file_that_cannot_be_read_says_so_before_anything_is_asked(connected, signed_in, app):
    from app.service import open_thread

    with app.app_context():
        thread = open_thread(1, {"id": 1}, "Something odd")
    answer = signed_in.post("/projects/1/assistant/ask", data={
        "question": "Read this", "thread_id": str(thread),
        "files": (io.BytesIO(b"\x00\x01\x02binary\xff"), "mystery.bin"),
    }, content_type="multipart/form-data")

    assert answer.status_code == 400
    assert "not something that can be read" in answer.get_json()["error"]


def test_a_resumed_conversation_shows_what_was_attached(connected, signed_in, app):
    from app.service import open_thread, thread_files

    with app.app_context():
        thread = open_thread(1, {"id": 1}, "About the letter")
    signed_in.post("/projects/1/assistant/ask", data={
        "question": "What does this say?", "thread_id": str(thread),
        "files": (io.BytesIO(a_word_file()), "letter.docx"),
    }, content_type="multipart/form-data")

    page = text(signed_in.get(f"/projects/1/assistant?thread={thread}"))
    assert "letter.docx" in page
    with app.app_context():
        kept = thread_files(thread)[0]
    assert f"/assistant/files/{kept['id']}" in page


def test_the_composer_offers_to_attach_something(signed_in):
    page = text(signed_in.get("/projects/1/assistant"))
    assert "data-attach" in page
    assert 'name="files"' in page
    assert ".docx" in page and ".pptx" in page


# --- documents back ---------------------------------------------------------

def test_a_document_is_a_link_rather_than_a_change_to_approve():
    from app.assistant import tools

    assert "document" in tools.READ_ONLY
    assert "document" not in tools.WRITES


def test_she_hands_back_each_kind_of_document(app):
    from app.assistant import tools

    with app.test_request_context("/projects/1/assistant"):
        for what, expected in (("register", ".docx"), ("agenda", ".docx"),
                               ("schedule", ".xlsx"), ("setup", "/setup/export")):
            got = tools.run("document", 1, {"what": what})
            assert got["kind"] == "document"
            assert expected in got["url"], f"{what} came back as {got['url']}"
            assert got["says"].startswith("Download")


def test_the_minutes_come_as_word_or_as_the_compiled_pdf(app, signed_in):
    from app.assistant import tools

    answer = signed_in.post("/projects/1/minutes/meetings",
                            data={"meeting_date": "03/09/2026", "ref": "MOM-09",
                                  "title": "Coordination"})
    meeting_id = int(answer.headers["Location"].rstrip("/").split("/")[-1])

    with app.test_request_context("/projects/1/assistant"):
        as_word = tools.run("document", 1, {"what": "minutes", "meeting": "MOM-09"})
        as_pdf = tools.run("document", 1, {"what": "minutes", "meeting": "MOM-09",
                                           "form": "pdf"})
    assert as_word["url"].endswith(f"/meetings/{meeting_id}.docx")
    assert as_pdf["url"].endswith(f"/meetings/{meeting_id}.pdf")


def test_a_document_that_does_not_exist_says_what_does(app):
    from app.assistant import tools
    from app.assistant.common import ToolError

    with app.test_request_context("/projects/1/assistant"):
        with pytest.raises(ToolError) as refused:
            tools.run("document", 1, {"what": "poster"})
    assert "minutes" in str(refused.value) and "register" in str(refused.value)


def test_asking_for_a_form_a_document_does_not_come_in_says_so(app):
    from app.assistant import tools
    from app.assistant.common import ToolError

    with app.test_request_context("/projects/1/assistant"):
        with pytest.raises(ToolError) as refused:
            tools.run("document", 1, {"what": "schedule", "form": "pdf"})
    assert "excel" in str(refused.value).lower()
