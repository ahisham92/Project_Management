"""The issued minutes: the Word, the PDF, and what is attached to them.

The point of these is that the two formats are one document. A client gets the
PDF and the office keeps the Word, and if the two disagree about what page the
attendance is on, or what the form code says, somebody has to work out which is
right. So what is checked here is mostly sameness.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.minutes_doc import FORM_CODE, minutes_document, minutes_pdf
from app.pdf import Document as PdfDocument, is_pdf, join, page_count


def text(response) -> str:
    return response.get_data(as_text=True)


def a_pdf(words: str = "Attachment") -> bytes:
    doc = PdfDocument(title=words)
    doc.add_paragraph(words)
    return doc.render()


def read(data: bytes) -> list[str]:
    from pypdf import PdfReader

    return [(page.extract_text() or "") for page in PdfReader(io.BytesIO(data)).pages]


@pytest.fixture()
def minuted(app, signed_in):
    """A meeting with four people, three items and the issue details filled in."""
    people = (
        ("Jihad Zuhairy", "Sibline Cement", "Port Manager"),
        ("Ola Bou Ghannam", "Dar", "Design Engineer"),
        ("Ahmed Mitwally", "Dar", "Project Manager"),
        ("R. Khoury", "Dar", "Director of Ports"),
    )
    for name, org, title in people:
        signed_in.post("/projects/1/minutes/attendees",
                       data={"name": name, "organisation": org, "job_title": title})
    answer = signed_in.post("/projects/1/minutes/meetings",
                            data={"meeting_date": "03/09/2026", "ref": "MOM-01",
                                  "title": "Kickoff meeting"})
    meeting_id = int(answer.headers["Location"].rstrip("/").split("/")[-1])
    for subject in ("Bathymetry survey", "Geotechnical scope", "Programme"):
        signed_in.post("/projects/1/minutes/items",
                       data={"meeting_id": meeting_id, "subject": subject,
                             "agreement": f"Agreed: {subject}", "owner_code": "PM",
                             "return": "meeting"})
    signed_in.post(f"/projects/1/minutes/meetings/{meeting_id}", data={
        "ref": "MOM-01", "title": "Kickoff meeting", "meeting_date": "03/09/2026",
        "purpose": "Kick-Off Meeting", "prepared_by": "Ola Bou Ghannam",
        "reviewed_by": "Jihad Zuhairy", "issue_date": "07/09/2026",
        "invited": ["1", "2", "3", "4"], "present": ["1", "2", "3"]})
    return meeting_id


# --- the PDF ----------------------------------------------------------------

def test_the_pdf_is_built_rather_than_printed(signed_in, minuted):
    answer = signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf")
    assert answer.status_code == 200
    assert answer.mimetype == "application/pdf"
    assert is_pdf(answer.data)


def test_the_attendance_is_the_first_page_and_the_items_start_on_the_next(signed_in, minuted):
    """How the practice issues them: the cover is who was there, and the
    minutes themselves begin overleaf."""
    pages = read(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    assert len(pages) >= 2
    assert "Jihad Zuhairy" in pages[0]
    assert "Items and Agreement" not in pages[0]
    assert "Items and Agreement" in pages[1]
    assert "Bathymetry survey" in pages[1]


def test_every_page_carries_the_form_code_and_its_own_number(signed_in, minuted):
    pages = read(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    for number, page in enumerate(pages, start=1):
        assert FORM_CODE in page, f"page {number} has no form code"
        assert str(number) in page


def test_the_signature_blocks_carry_the_names_and_the_issue_date(signed_in, minuted):
    pages = read(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    last = pages[1]
    assert "Prepared by:" in last and "Ola Bou Ghannam" in last
    assert "Reviewed &" in last and "Jihad Zuhairy" in last
    assert "07/09/2026" in last
    # The signature is always a rule to sign on, never a name typed for somebody.
    assert "Signature:" in last


# --- what is attached -------------------------------------------------------

def test_an_attached_pdf_is_kept_and_named_in_the_minutes(signed_in, app, minuted):
    signed_in.post(f"/projects/1/minutes/meetings/{minuted}/attachments",
                   data={"name": "Kick-off presentation",
                         "file": (io.BytesIO(a_pdf("Slide deck")), "deck.pdf")},
                   content_type="multipart/form-data")

    with app.app_context():
        from app.service import load_attachments

        kept = load_attachments(1, minuted)
    assert len(kept) == 1
    assert kept[0]["name"] == "Kick-off presentation"
    assert kept[0]["pages"] == 1

    pages = read(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    assert "Attachment: Kick-off presentation" in pages[1]


def test_the_attachment_is_compiled_onto_the_end_of_the_exported_pdf(signed_in, minuted):
    before = page_count(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    signed_in.post(f"/projects/1/minutes/meetings/{minuted}/attachments",
                   data={"name": "Presentation",
                         "file": (io.BytesIO(a_pdf("Slide deck")), "deck.pdf")},
                   content_type="multipart/form-data")

    data = signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data
    assert page_count(data) == before + 1
    assert "Slide deck" in read(data)[-1]


def test_something_that_is_not_a_pdf_is_refused(signed_in, app, minuted):
    answer = signed_in.post(f"/projects/1/minutes/meetings/{minuted}/attachments",
                            data={"name": "Notes",
                                  "file": (io.BytesIO(b"just some text"), "notes.pdf")},
                            content_type="multipart/form-data", follow_redirects=True)
    assert "have to be PDFs" in text(answer)
    with app.app_context():
        from app.service import load_attachments

        assert load_attachments(1, minuted) == []


def test_an_attachment_is_kept_in_the_database_so_the_backup_carries_it(app, signed_in, minuted):
    """A file beside the database is a file that does not come back when
    somebody restores from the nightly backup."""
    signed_in.post(f"/projects/1/minutes/meetings/{minuted}/attachments",
                   data={"name": "Presentation",
                         "file": (io.BytesIO(a_pdf()), "deck.pdf")},
                   content_type="multipart/form-data")
    with app.app_context():
        from app.db import query_one

        row = query_one("SELECT content FROM meeting_attachments WHERE meeting_id = ?",
                        (minuted,))
    assert is_pdf(bytes(row["content"]))


def test_an_attachment_is_removed_and_stops_being_compiled(signed_in, app, minuted):
    signed_in.post(f"/projects/1/minutes/meetings/{minuted}/attachments",
                   data={"name": "Presentation",
                         "file": (io.BytesIO(a_pdf()), "deck.pdf")},
                   content_type="multipart/form-data")
    with app.app_context():
        from app.service import load_attachments

        kept = load_attachments(1, minuted)[0]

    with_it = page_count(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    signed_in.post(f"/projects/1/minutes/attachments/{kept['id']}/delete")
    without = page_count(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    assert without == with_it - 1


def test_the_word_names_the_attachment_but_does_not_carry_it(signed_in, minuted):
    """A PDF does not go inside a .docx in any way a client can open, so the
    Word says what is attached and the PDF is the one that carries it."""
    signed_in.post(f"/projects/1/minutes/meetings/{minuted}/attachments",
                   data={"name": "Kick-off presentation",
                         "file": (io.BytesIO(a_pdf()), "deck.pdf")},
                   content_type="multipart/form-data")

    data = signed_in.get(f"/projects/1/minutes/meetings/{minuted}.docx").data
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        document = book.read("word/document.xml").decode("utf-8")
        assert "Kick-off presentation" in document
        assert not [n for n in book.namelist() if n.lower().endswith(".pdf")]


# --- the Word, and the two of them agreeing ---------------------------------

def test_the_word_carries_the_form_code_and_nine_point_text(signed_in, minuted):
    data = signed_in.get(f"/projects/1/minutes/meetings/{minuted}.docx").data
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        assert FORM_CODE in book.read("word/footer1.xml").decode("utf-8")
        styles = book.read("word/styles.xml").decode("utf-8")
        # 18 half-points is 9pt, the size asked for on the issued minutes.
        assert '<w:sz w:val="18"/>' in styles


def test_the_word_breaks_the_page_after_the_attendance(signed_in, minuted):
    data = signed_in.get(f"/projects/1/minutes/meetings/{minuted}.docx").data
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        document = book.read("word/document.xml").decode("utf-8")
    assert document.count('w:br w:type="page"') == 1
    assert document.index("Present at this meeting") < document.index('w:br w:type="page"')
    assert document.index('w:br w:type="page"') < document.index("Items and Agreement")


def test_both_formats_say_the_same_things(signed_in, minuted):
    """They are one document in two files. Anything in one and not the other is
    a difference somebody has to reconcile by hand."""
    pdf = " ".join(read(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data))
    data = signed_in.get(f"/projects/1/minutes/meetings/{minuted}.docx").data
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        word = book.read("word/document.xml").decode("utf-8")

    for said in ("MOM-01", "Kick-Off Meeting", "Bathymetry survey", "Ola Bou Ghannam",
                 "Jihad Zuhairy", "07/09/2026", "Items and Agreement"):
        assert said in pdf, f"the PDF is missing {said!r}"
        assert said in word, f"the Word is missing {said!r}"


# --- the order they are listed in -------------------------------------------

def test_the_attendance_is_listed_as_the_roster_has_it_by_default(signed_in, minuted):
    pages = read(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)
    cover = pages[0]
    assert cover.index("Jihad Zuhairy") < cover.index("Ola Bou Ghannam")
    assert cover.index("Ahmed Mitwally") < cover.index("R. Khoury")


def test_ordering_by_seniority_puts_the_client_first_then_down_the_ranks(signed_in, app,
                                                                        minuted):
    from app.db import execute

    with app.app_context():
        execute("UPDATE projects SET client = 'Sibline Cement' WHERE id = 1")
    signed_in.post("/projects/1/minutes/attendee-order", data={"attendee_order": "seniority"})

    cover = read(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.pdf").data)[0]
    # Client, then the director, then the project manager, then everybody else.
    assert (cover.index("Jihad Zuhairy") < cover.index("R. Khoury")
            < cover.index("Ahmed Mitwally") < cover.index("Ola Bou Ghannam"))


def test_the_order_is_one_setting_for_the_project(signed_in):
    answer = signed_in.post("/projects/1/minutes/attendee-order",
                            data={"attendee_order": "seniority"}, follow_redirects=True)
    assert "every set of minutes on this project" in text(answer)
    assert "client first" in text(signed_in.get("/projects/1/minutes")).lower()


# --- joining PDFs -----------------------------------------------------------

def test_joining_keeps_the_order_and_every_page():
    first, second = a_pdf("One"), a_pdf("Two")
    joined = join(first, second)
    pages = read(joined)
    assert len(pages) == 2
    assert "One" in pages[0] and "Two" in pages[1]


def test_something_that_will_not_open_costs_that_file_and_not_the_minutes():
    """An attachment somebody uploaded wrongly should not fail the export."""
    good = a_pdf("The minutes")
    joined = join(good, b"%PDF-1.4 not really")
    assert "The minutes" in read(joined)[0]
