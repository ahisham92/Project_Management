"""The minutes built from a Word document somebody else wrote.

The layout used to live only in code, which was fine until the practice moved a
column — and then it was a change to the software, made by somebody who is not
in the room. So the form can be downloaded, changed in Word and uploaded back.
"""

from __future__ import annotations

import io
import zipfile

import pytest

from app.doctemplate import TemplateError, fill, is_docx, placeholders
from app.minutes_doc import minutes_from_template, starter_template


def text(response) -> str:
    return response.get_data(as_text=True)


def body_of(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        return book.read("word/document.xml").decode("utf-8")


def words_of(data: bytes) -> str:
    """What the document reads as: its text, with real breaks as newlines."""
    import re

    xml = re.sub(r"<w:br\s*/>", "\n", body_of(data))
    return re.sub(r"<[^>]+>", "", xml)


def edited(template: bytes, was: str, now: str) -> bytes:
    """The template with a word changed, the way somebody would in Word."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(template)) as src, \
            zipfile.ZipFile(out, "w") as made:
        for name in src.namelist():
            data = src.read(name)
            if name == "word/document.xml":
                data = data.decode("utf-8").replace(was, now).encode("utf-8")
            made.writestr(name, data)
    return out.getvalue()


SHEET = {
    "meeting": {"ref": "MOM-01", "title": "Kickoff", "meeting_date": "2026-09-03",
                "meeting_time": "10:00", "location": "Teams", "prepared_by": "Ola",
                "reviewed_by": "Jihad", "issue_date": "2026-09-07",
                "notes": "On site next week."},
    "attendance": [
        {"name": "Jihad", "organisation": "Sibline", "job_title": "Port Manager",
         "trade_name": "", "invited": True, "present": True},
        {"name": "Ola", "organisation": "Dar", "job_title": "Engineer",
         "trade_name": "Marine", "invited": True, "present": True},
        {"name": "Absent Anna", "organisation": "Dar", "job_title": "Drafter",
         "trade_name": "", "invited": True, "present": False},
    ],
    "items": [
        {"ref": "1.1", "subject": "Bathymetry", "discussion": "When does it start?",
         "agreement": "Dar to issue the brief", "owner_code": "PM", "impact": "time",
         "due_date": "2026-09-20", "is_open": True},
        {"ref": "1.2", "subject": "Quay levels", "discussion": "",
         "agreement": "Marine to reissue", "owner_code": "MR", "impact": "cost",
         "due_date": "", "is_open": True},
    ],
}
PROJECT = {"code": "L26100", "name": "Sibline Port", "client": "Sibline Cement"}


# --- the template itself ----------------------------------------------------

def test_the_starter_template_is_a_word_document_with_every_placeholder_in_it():
    made = starter_template()
    assert is_docx(made)
    found = placeholders(made)
    for wanted in ("project.code", "meeting.ref", "meeting.issue_date",
                   "attendee.name", "item.subject", "item.agreement"):
        assert wanted in found, wanted


def test_something_that_is_not_a_word_document_is_refused_in_words():
    for rubbish in (b"", b"not a zip", b"%PDF-1.4 hello"):
        assert not is_docx(rubbish)
    with pytest.raises(TemplateError) as refused:
        fill(b"not a zip", {})
    assert "Word" in str(refused.value)


# --- filling one in ---------------------------------------------------------

def test_every_placeholder_is_replaced_and_none_are_left_behind():
    made = minutes_from_template(starter_template(), PROJECT, SHEET)
    assert "{{" not in body_of(made)
    said = words_of(made)
    for expected in ("L26100", "Sibline Port", "MOM-01", "03/09/2026", "Teams",
                     "Bathymetry", "Dar to issue the brief", "07/09/2026"):
        assert expected in said, expected


def test_a_row_with_a_row_placeholder_is_written_once_per_entry():
    made = body_of(minutes_from_template(starter_template(), PROJECT, SHEET))
    assert made.count("Bathymetry") == 1 and made.count("Quay levels") == 1
    assert made.count("Sibline</w:t>") == 1
    assert made.count("Port Manager") == 1, "one row per person, not two"


def test_the_people_who_did_not_come_are_not_written_out():
    said = words_of(minutes_from_template(starter_template(), PROJECT, SHEET))
    assert "Jihad" in said and "Absent Anna" not in said


def test_a_line_break_in_a_discussion_becomes_a_real_break():
    sheet = {**SHEET, "items": [dict(SHEET["items"][0],
                                     agreement="One thing\nAnother thing")]}
    made = minutes_from_template(starter_template(), PROJECT, sheet)
    assert "<w:br/>" in body_of(made)
    assert "One thing\nAnother thing" in words_of(made)


def test_the_rest_of_the_template_is_left_exactly_as_it_was():
    """Fonts, colours, widths, the letterhead — none of it is this code's
    business. Only the placeholders change."""
    changed = edited(starter_template(), "Items and Agreement", "Points discussed")
    made = minutes_from_template(changed, PROJECT, SHEET)
    assert "Points discussed" in words_of(made)
    assert "Items and Agreement" not in words_of(made)


def test_a_placeholder_word_split_into_pieces_still_fills_in():
    """Word breaks a line into runs wherever it likes, so a placeholder typed
    by hand can arrive in three pieces."""
    template = starter_template()
    broken = edited(
        template,
        '<w:t xml:space="preserve">{{meeting.ref}}</w:t>',
        '<w:t xml:space="preserve">{{meet</w:t></w:r>'
        '<w:r><w:t xml:space="preserve">ing.</w:t></w:r>'
        '<w:r><w:t xml:space="preserve">ref}}</w:t>')
    said = words_of(minutes_from_template(broken, PROJECT, SHEET))
    assert "MOM-01" in said and "{{" not in said


def test_a_placeholder_nobody_passes_is_left_where_it_is():
    """Better a template that says {{whatever}} than one that quietly drops
    what somebody typed and leaves them wondering where it went."""
    template = edited(starter_template(), "{{meeting.location}}", "{{meeting.weather}}")
    assert "{{meeting.weather}}" in body_of(fill(template, {"meeting.ref": "MOM-02"}))


def test_a_meeting_with_no_items_keeps_the_table_rather_than_emptying_it():
    sheet = {**SHEET, "items": []}
    made = words_of(minutes_from_template(starter_template(), PROJECT, sheet))
    assert "Agreed action" in made, "the headings stay"


# --- through the app --------------------------------------------------------

@pytest.fixture
def minuted(signed_in):
    for name, org in (("Jihad", "Sibline"), ("Ola", "Dar")):
        signed_in.post("/projects/1/minutes/attendees",
                       data={"name": name, "organisation": org})
    answer = signed_in.post("/projects/1/minutes/meetings",
                            data={"meeting_date": "03/09/2026", "ref": "MOM-01",
                                  "title": "Kickoff"})
    meeting_id = int(answer.headers["Location"].rstrip("/").split("/")[-1])
    signed_in.post("/projects/1/minutes/items",
                   data={"meeting_id": meeting_id, "subject": "Bathymetry",
                         "agreement": "Dar to issue the brief", "owner_code": "PM",
                         "return": "meeting"})
    signed_in.post(f"/projects/1/minutes/meetings/{meeting_id}", data={
        "ref": "MOM-01", "title": "Kickoff", "meeting_date": "03/09/2026",
        "invited": ["1", "2"], "present": ["1", "2"]})
    return meeting_id


def unlocked(client):
    client.post("/projects/1/setup/unlock", data={"password": "2026"})
    return client


def test_the_template_downloads_from_setup_before_anything_is_uploaded(signed_in):
    answer = signed_in.get("/projects/1/setup/minutes-template.docx")
    assert answer.status_code == 200
    assert is_docx(answer.data)
    assert "project.code" in placeholders(answer.data)


def test_uploading_a_template_says_how_many_placeholders_it_found(signed_in):
    unlocked(signed_in)
    template = signed_in.get("/projects/1/setup/minutes-template.docx").data
    answer = signed_in.post("/projects/1/setup/minutes-template",
                            data={"file": (io.BytesIO(template), "form.docx")},
                            follow_redirects=True)
    assert "placeholders found" in text(answer)
    assert "form.docx" in text(signed_in.get("/projects/1/setup"))


def test_the_word_export_is_built_from_the_uploaded_template(signed_in, minuted):
    unlocked(signed_in)
    template = edited(signed_in.get("/projects/1/setup/minutes-template.docx").data,
                      "Items and Agreement", "Points discussed")
    signed_in.post("/projects/1/setup/minutes-template",
                   data={"file": (io.BytesIO(template), "form.docx")})

    said = words_of(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.docx").data)
    assert "Points discussed" in said
    assert "Bathymetry" in said and "MOM-01" in said


def test_going_back_to_the_built_in_layout(signed_in, minuted):
    unlocked(signed_in)
    template = edited(signed_in.get("/projects/1/setup/minutes-template.docx").data,
                      "Items and Agreement", "Points discussed")
    signed_in.post("/projects/1/setup/minutes-template",
                   data={"file": (io.BytesIO(template), "form.docx")})
    signed_in.post("/projects/1/setup/minutes-template/remove", follow_redirects=True)

    said = words_of(signed_in.get(f"/projects/1/minutes/meetings/{minuted}.docx").data)
    assert "Items and Agreement" in said and "Points discussed" not in said


def test_a_file_that_is_not_a_word_document_is_refused_at_the_door(signed_in):
    unlocked(signed_in)
    answer = signed_in.post("/projects/1/setup/minutes-template",
                            data={"file": (io.BytesIO(b"%PDF-1.4 nope"), "form.pdf")},
                            follow_redirects=True)
    assert "not a Word document" in text(answer)


def test_a_locked_setup_sheet_will_not_take_a_new_template(signed_in):
    template = signed_in.get("/projects/1/setup/minutes-template.docx").data
    answer = signed_in.post("/projects/1/setup/minutes-template",
                            data={"file": (io.BytesIO(template), "form.docx")},
                            follow_redirects=True)
    assert "form.docx" not in text(signed_in.get("/projects/1/setup"))
    assert answer.status_code == 200
