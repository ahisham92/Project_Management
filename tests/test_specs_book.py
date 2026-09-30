"""Reading a specification as a book: the text as it is issued, on pages.

The pages themselves are cut in the browser; what the server owes the book is
the issued text — only what the project keeps, no editor's notes, the words
filled in — in the order and the form the pages are cut from.
"""

from __future__ import annotations

from .test_specs import text
from .test_specs_kinds import load, set_id_of

BODY = """\
# GENERAL
## SUMMARY
- Section Includes:
-- Steel reinforcement bars.
- {if leed=v4} Only for a LEED v4 project: recycled content.
// Editor's note: keep the LEED paragraphs in step with the credit.
# PRODUCTS
## STEEL REINFORCEMENT
- Reinforcing Bars: approved by the {{engineer}}.
| Bar | Grade |
| B500B | 500 MPa |
"""


def _library_id(app, number, family):
    from app import specs_store

    with app.app_context():
        return specs_store.section_by_number(number, family)["id"]


def _master(app, signed_in):
    """The master section, conditions, notes and variables and all: a Word file
    carries only what applies, so the text is put in through the editor."""
    load(signed_in, "STD15A_SPC_032000_ST_Reinforcing.docx", "# GENERAL\n", "032000",
         "CONCRETE REINFORCING")
    section_id = _library_id(app, "032000", "15A")
    signed_in.post(f"/specs/library/{section_id}/edit", data={
        "number": "032000", "title": "CONCRETE REINFORCING", "note": "Book", "text": BODY})
    return section_id


def _project(app, signed_in):
    _master(app, signed_in)
    load(signed_in, "STD15A_SPC_033000_ST_Concrete.docx", "# GENERAL\n## SUMMARY\n- Concrete.\n",
         "033000", "CAST-IN-PLACE CONCRETE")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Harbour Works",
                                                          "family": "15A"}))
    signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Harbour Works", "header_left": "Port Works\nPhase 2", "header_right": "Final Design",
        "doc_code": "N1", "revision": "2", "opt_leed": "None", "var_engineer": "Harbour Authority"})
    signed_in.post(f"/specs/sets/{set_id}/sections", data={
        "section_id": [str(_library_id(app, "032000", "15A")),
                       str(_library_id(app, "033000", "15A"))]})
    return set_id


def test_a_project_reads_as_a_book_as_it_is_issued(app, signed_in):
    set_id = _project(app, signed_in)
    # The section page shows the editor's note and the {{engineer}} word; the book does not
    # show the note, and fills the word.
    shown = text(signed_in.get(f"/specs/sets/{set_id}/sections/1"))
    assert "keep the LEED paragraphs" in shown and "Only for a LEED v4 project" in shown
    answer = signed_in.get(f"/specs/sets/{set_id}/book")
    assert answer.status_code == 200
    page = text(answer)
    assert "spec-book.js" in page and "spec-book.css" in page
    # Every section, in order, each with its heading and its end.
    assert page.index("SECTION 032000 - CONCRETE REINFORCING") < page.index(
        "SECTION 033000 - CAST-IN-PLACE CONCRETE")
    assert "END OF SECTION 032000" in page and "END OF SECTION 033000" in page
    # The issued text: the paragraphs kept, the project's word filled in, the table.
    assert "Steel reinforcement bars." in page
    assert "Harbour Authority" in page
    assert "500 MPa" in page and 'class="bk-table"' in page
    # Not issued: a paragraph whose condition is off, and the editor's notes.
    assert "Only for a LEED v4 project" not in page
    assert "Editor&#39;s note" not in page and "keep the LEED paragraphs" not in page
    # The running header and the footer's code line, as the issued document has them.
    assert "Port Works" in page and "Final Design" in page and "N1 REV 2" in page
    # MasterSpec labels, ready to hang.
    assert '<span class="bk-n">PART 1 -</span>' in page and '<span class="bk-n">1.1</span>' in page
    assert '<span class="bk-n">A.</span>' in page


def test_a_condition_switched_on_puts_its_paragraph_in_the_book(app, signed_in):
    set_id = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Harbour Works", "opt_leed": "v4"})
    assert "Only for a LEED v4 project" in text(signed_in.get(f"/specs/sets/{set_id}/book"))


def test_the_book_opens_at_a_section_and_is_offered_where_it_is_read(app, signed_in):
    set_id = _project(app, signed_in)
    sections = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert f"/specs/sets/{set_id}/book" in sections and "Read as a book" in sections
    from app import specs_store

    with app.app_context():
        row = [s for s in specs_store.set_sections(set_id) if s["number"] == "033000"][0]["id"]
    one = text(signed_in.get(f"/specs/sets/{set_id}/sections/{row}"))
    assert f"/specs/sets/{set_id}/book?row={row}" in one
    page = text(signed_in.get(f"/specs/sets/{set_id}/book?row={row}"))
    assert f'data-start-row="{row}"' in page
    assert signed_in.get("/specs/sets/9999/book").status_code == 404


def test_a_master_section_reads_as_a_book(app, signed_in):
    section_id = _master(app, signed_in)
    assert f"/specs/library/{section_id}/book" in text(signed_in.get(f"/specs/library/{section_id}"))
    answer = signed_in.get(f"/specs/library/{section_id}/book")
    assert answer.status_code == 200
    page = text(answer)
    assert "SECTION 032000 - CONCRETE REINFORCING" in page and "END OF SECTION 032000" in page
    assert "Steel reinforcement bars." in page
    assert "approved by the" in page and 'title="{{engineer}}">Engineer<' in page  # its default
    assert "Only for a LEED v4 project" not in page               # as issued, on the defaults
    assert "keep the LEED paragraphs" not in page
    assert signed_in.get("/specs/library/9999/book").status_code == 404


def test_an_nbs_section_reads_as_headings_clauses_and_bullets(app, signed_in):
    load(signed_in, "SPC-E30.docx",
         "# REINFORCEMENT\n## 110 QUALITY ASSURANCE\n- Standards:\n-- To BS 4449.\n", "E30",
         "REINFORCEMENT", family="03A")
    page = text(signed_in.get(f"/specs/library/{_library_id(app, 'E30', '03A')}/book"))
    assert "E30 - REINFORCEMENT" in page and "SECTION E30" not in page
    assert "END OF SECTION" not in page
    assert "110 QUALITY ASSURANCE" in page and "•" in page and "bk-nbs" in page
