"""The client's own review response form, read and written back.

Every test here goes through the blank form that ships with the application,
which is the client's workbook with their entries cleared. So what is being
checked is not a shape we invented: it is that the form the project actually
runs on can be read, answered and handed back looking exactly as it arrived.
"""

from __future__ import annotations

import io
import zipfile

import openpyxl
import pytest

from app import crs_excel
from app.crs_excel import SheetError


def parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as book:
        return {name: book.read(name) for name in book.namelist()}


def fill(comments, **kept):
    """The blank form with comments written into it, as a sheet raised here."""
    blank = crs_excel.blank_form()
    form = crs_excel.read(blank)
    return crs_excel.write(blank, comments, form["header_row"], form["columns"],
                           authored=True, info_at=form["info_at"],
                           overall_at=form["overall_at"], **kept)


ONE = [{"sn": "1", "reviewer": "Client PM", "source": "Clause 4.2",
        "observation": "The connection detail is not dimensioned.",
        "discipline": "Structural", "reference": "ST-0003",
        "returned_code": "C", "response": "Dimensioned on revision C2.",
        "signoff": "closed"}]


# --- reading ----------------------------------------------------------------

def test_the_blank_form_reads_as_the_clients_own_geometry():
    """Where the table and the header sit is the client's decision, not ours,
    so it is read off the form rather than written down anywhere."""
    form = crs_excel.read(crs_excel.blank_form())

    assert form["header_row"] == 21
    assert form["columns"]["sn"] == 2 and form["columns"]["signoff"] == 10
    assert set(crs_excel.MINE) <= set(form["columns"])
    assert form["comments"] == [], "the blank form is blank"
    assert form["overall_at"] == "J15"
    # Every field the header carries has somewhere to be written back to.
    assert set(form["info_at"]) == {field for field, _ in crs_excel.INFO}


def test_a_file_that_is_not_a_workbook_says_so():
    with pytest.raises(SheetError):
        crs_excel.read(b"this is not a spreadsheet")


def test_a_workbook_with_no_comment_table_says_so():
    book = openpyxl.Workbook()
    book.active["A1"] = "Monthly invoice"
    stream = io.BytesIO()
    book.save(stream)

    with pytest.raises(SheetError) as raised:
        crs_excel.read(stream.getvalue())
    assert "comment table" in str(raised.value).lower()


# --- writing back -----------------------------------------------------------

def test_everything_but_the_worksheet_comes_back_byte_for_byte():
    """The letterhead is the client's artwork. openpyxl drops it on a save, so
    the workbook is patched as a zip and every other part is copied across."""
    before, after = parts(crs_excel.blank_form()), parts(fill(ONE))

    assert set(after) == set(before), "no part lost"
    changed = [name for name in before if before[name] != after[name]]
    assert changed == ["xl/worksheets/sheet1.xml"]
    assert any(name.startswith("xl/media/") for name in after), "the logo is still there"


def test_the_answered_form_still_opens():
    openpyxl.load_workbook(io.BytesIO(fill(ONE)))


def test_a_sheet_raised_here_is_written_whole_and_read_back():
    read = crs_excel.read(fill(ONE))["comments"]

    assert len(read) == 1
    for field, value in ONE[0].items():
        expected = "Closed" if field == "signoff" else value
        assert read[0][field] == expected, field


def test_more_comments_than_the_form_has_rows():
    """A client sends 7 rows and forty comments. The table grows by cloning its
    own last row, so the added rows carry the form's borders and not ours."""
    many = [dict(ONE[0], sn=str(n), observation=f"Comment {n}", response=f"Answered {n}")
            for n in range(1, 41)]

    read = crs_excel.read(fill(many))["comments"]
    assert [row["sn"] for row in read] == [str(n) for n in range(1, 41)]
    assert read[-1]["observation"] == "Comment 40"
    assert read[-1]["response"] == "Answered 40"


def test_answering_a_clients_form_leaves_their_words_alone():
    """Editing a reviewer's observation is not answering it. A form that came
    in from the client gives up only the response, the code and the sign-off."""
    theirs = fill(ONE)
    form = crs_excel.read(theirs)

    meddled = [dict(form["comments"][0], observation="No comment at all, actually",
                    reviewer="Me", response="Dimensioned on revision C3.",
                    returned_code="B", signoff="open")]
    back = crs_excel.read(crs_excel.write(theirs, meddled, form["header_row"],
                                          form["columns"]))["comments"][0]

    assert back["observation"] == ONE[0]["observation"], "theirs, untouched"
    assert back["reviewer"] == "Client PM"
    assert back["response"] == "Dimensioned on revision C3.", "ours, answered"
    assert back["returned_code"] == "B"
    assert back["signoff"] == "Open"


def test_the_header_and_the_overall_code_are_written_where_the_form_keeps_them():
    said = {"project_name": "Marine works", "contractor": "Dar",
            "drf_ref": "DRF-0003", "drf_rev": "C2", "engineer": "A. Mitwally",
            "title": "Steel connection details"}
    form = crs_excel.read(fill(ONE, info=said, overall="B"))

    assert form["overall_code"] == "B"
    for field, value in said.items():
        assert form["info"][field] == value, field


def test_a_form_we_never_read_keeps_its_header():
    """Without knowing where a value goes, nothing is written anywhere: a
    guessed cell is a client's form with our text across their letterhead."""
    blank = crs_excel.blank_form()
    form = crs_excel.read(blank)
    written = crs_excel.write(blank, ONE, form["header_row"], form["columns"],
                              info={"project_name": "Marine works"}, overall="B")

    assert crs_excel.read(written)["info"] == {}
    assert crs_excel.read(written)["overall_code"] == ""
