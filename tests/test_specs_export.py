"""Issuing a specification three ways: clean Word, Word with tracked changes, PDF.

The tracked copy has to be something Word itself accepts and rejects — real
revisions, the changed words and nothing else — and the PDF the same words on
the page. Whatever the format, a held project is not issued.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree as ET

from app import specs, specs_export
from .test_specs import MASTER_TEXT, master_nodes, text
from .test_specs_kinds import load, set_id_of

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def document_xml(data: bytes) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read("word/document.xml").decode("utf-8")


def revised(xml: str, tag: str) -> str:
    """The words inside every <w:ins> or <w:del>, run together."""
    root = ET.fromstring(xml)
    return "".join(t.text or "" for mark in root.iter(W + tag)
                   for t in mark.iter() if t.tag in (W + "t", W + "delText"))


def project(client, amend=None, hold=False) -> int:
    load(client, "SPC-032000.docx", MASTER_TEXT, "032000", "CONCRETE REINFORCING")
    set_id = set_id_of(client.post("/specs/sets", data={"name": "Harbour Works", "code": "HW-001"}))
    form = {"name": "Harbour Works", "code": "HW-001", "header_left": "Port Works\nPhase 2",
            "header_right": "Final Design", "doc_code": "N1-SPC", "revision": "2",
            "file_pattern": "SPC-{number}", "opt_leed": "v4.1", "hold_shown": "1"}
    if hold:
        form["hold_issue"] = "1"
    client.post(f"/specs/sets/{set_id}", data=form)
    client.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["1"]})
    if amend:
        body = amend(specs.to_text(master_nodes()))
        client.post(f"/specs/sets/{set_id}/sections/1/edit",
                    data={"text": body, "mode": "text", "title": "CONCRETE REINFORCING"})
    return set_id


def amended(body: str) -> str:
    return (body.replace("- Section Includes:", "- Section Includes the following items:")
            .replace("-- Welded-wire reinforcement.\n", "")
            .replace("- Hold the reinforcement in place.",
                     "- Hold the reinforcement in place.\n- Tie every crossing with annealed wire."))


# --- Word with tracked changes -------------------------------------------------------

def test_an_amended_section_comes_out_with_its_changes_tracked(signed_in):
    set_id = project(signed_in, amended)
    answer = signed_in.get(f"/specs/sets/{set_id}/sections/1/docx?fmt=tracked")
    assert answer.status_code == 200 and answer.mimetype.endswith("wordprocessingml.document")
    assert "(tracked).docx" in answer.headers["Content-Disposition"]
    xml = document_xml(answer.data)
    ET.fromstring(xml)                                            # well formed
    assert "<w:ins " in xml and "<w:del " in xml
    inserted, deleted = revised(xml, "ins"), revised(xml, "del")
    # The reworded paragraph: only the new words are inserted, nothing deleted from it.
    assert "the following items" in inserted and "Section Includes" not in inserted
    # The dropped paragraph and its paragraph mark are deleted; the added one inserted.
    assert "Welded-wire reinforcement." in deleted
    assert "Tie every crossing with annealed wire." in inserted
    assert 'w:author="' in xml and 'w:date="' in xml
    # An inserted paragraph keeps the house style and list, so Word numbers it.
    added = next(p for p in ET.fromstring(xml).iter(W + "p")
                 if "annealed wire" in "".join(t.text or "" for t in p.iter(W + "t")))
    ppr = added.find(W + "pPr")
    assert ppr.find(W + "pStyle").get(W + "val") == "PR1"
    assert ppr.find(W + "numPr") is not None
    assert ppr.find(W + "rPr").find(W + "ins") is not None
    # The words that did not change are plain runs, as in the clean copy.
    assert "Drawings and general provisions" not in inserted + deleted

    import docx                                                   # python-docx opens it
    opened = docx.Document(io.BytesIO(answer.data))
    assert any("Section Includes" in p.text for p in opened.paragraphs)

    # The clean copy is still the default, with no revisions in it.
    clean = document_xml(signed_in.get(f"/specs/sets/{set_id}/sections/1/docx").data)
    assert "<w:ins " not in clean and "<w:del " not in clean
    assert "Section Includes the following items:" in clean


def test_a_section_as_the_master_has_no_revisions(signed_in):
    set_id = project(signed_in)
    xml = document_xml(signed_in.get(f"/specs/sets/{set_id}/sections/1/docx?fmt=tracked").data)
    assert "<w:ins " not in xml and "<w:del " not in xml and "pPrChange" not in xml


def test_what_the_choices_switch_off_is_not_a_deletion():
    base = master_nodes()
    data, changed = specs_export.write_tracked_docx(
        {"number": "032000", "title": "CONCRETE REINFORCING"}, base, base, {}, {"leed": "v4"},
        {"engineer": "Engineer"})
    assert changed == 0 and "<w:del " not in document_xml(data)
    assert "LEED v4.1" not in document_xml(data)


def test_a_changed_table_and_the_projects_own_section():
    base = master_nodes()
    ours = [dict(n) for n in base]
    table = next(n for n in ours if n["level"] == specs.TABLE)
    table["text"] = "| Bar | Grade |\n| B500C | 500 MPa |"
    xml = document_xml(specs_export.write_tracked_docx(
        {"number": "032000", "title": "X"}, ours, base, {}, {"leed": "v4.1"}, {})[0])
    assert "B500B" in revised(xml, "del") and "B500C" in revised(xml, "ins")
    assert "MPa" not in revised(xml, "ins")                       # the cell that stayed
    # With no master, every paragraph is the project's: all of it inserted.
    data, changed = specs_export.write_tracked_docx(
        {"number": "032000", "title": "X"}, ours, None, {}, {"leed": "v4.1"}, {})
    assert changed > 5 and "<w:del " not in document_xml(data)
    assert "Hold the reinforcement in place." in revised(document_xml(data), "ins")


def test_the_whole_project_issues_tracked_as_a_zip(signed_in):
    set_id = project(signed_in, amended)
    answer = signed_in.get(f"/specs/sets/{set_id}/export?fmt=tracked")
    assert answer.mimetype == "application/zip"
    assert "tracked changes" in answer.headers["Content-Disposition"]
    bundle = zipfile.ZipFile(io.BytesIO(answer.data))
    assert bundle.namelist() == ["SPC-032000 (tracked).docx"]
    assert "<w:del " in document_xml(bundle.read("SPC-032000 (tracked).docx"))


# --- PDF ------------------------------------------------------------------------------

def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(page.extract_text() for page in PdfReader(io.BytesIO(data)).pages)


def test_a_section_as_a_pdf(signed_in):
    set_id = project(signed_in, amended)
    answer = signed_in.get(f"/specs/sets/{set_id}/sections/1/docx?fmt=pdf")
    assert answer.mimetype == "application/pdf" and answer.data.startswith(b"%PDF")
    assert answer.headers["Content-Disposition"].endswith('SPC-032000.pdf"')
    words = " ".join(pdf_text(answer.data).split())
    assert "SECTION 032000 - CONCRETE REINFORCING" in words
    assert "Section Includes the following items:" in words
    assert "Welded-wire" not in words and "Keep the LEED paragraphs" not in words   # dropped, note
    assert "PART 1 - GENERAL" in words and "END OF SECTION 032000" in words
    assert "Page 1 of 1" in words and "N1-SPC REV 2" in words and "Port Works" in words


def test_the_whole_project_as_one_pdf(signed_in):
    set_id = project(signed_in)
    load(signed_in, "SPC-033000.docx", "# GENERAL\n## SUMMARY\n- Cast-in-place concrete.\n",
         "033000", "CAST-IN-PLACE CONCRETE")
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["2"]})
    answer = signed_in.get(f"/specs/sets/{set_id}/export?fmt=pdf")
    assert answer.mimetype == "application/pdf", text(answer)[:300]
    assert "HW-001 - specification REV 2.pdf" in answer.headers["Content-Disposition"]
    from pypdf import PdfReader

    pages = PdfReader(io.BytesIO(answer.data)).pages
    assert len(pages) == 2                                        # a new page for each
    first, second = (" ".join(p.extract_text().split()) for p in pages)
    assert "SECTION 032000" in first and "Page 1 of 1" in first
    assert "SECTION 033000" in second and "Cast-in-place concrete." in second


def test_a_library_section_as_a_pdf(signed_in):
    load(signed_in, "SPC-032000.docx", MASTER_TEXT, "032000", "CONCRETE REINFORCING")
    answer = signed_in.get("/specs/library/1/docx?fmt=pdf")
    assert answer.mimetype == "application/pdf" and answer.data.startswith(b"%PDF")
    assert "Reinforcing Bars" in pdf_text(answer.data)
    page = text(signed_in.get("/specs/library/1"))
    assert "fmt=pdf" in page


def test_characters_beyond_latin_are_drawn_or_stood_in_for():
    nodes = specs.align([], specs.from_text("# GENERAL\n## LIMITS\n- Slump ≤ 100 mm, "
                                            "strength ≥ 40 MPa, 25 µm.\n"))
    data = specs_export.write_pdf([({"number": "033000", "title": "CONCRETE"}, nodes, None)],
                                  {}, {}, {})
    words = pdf_text(data)
    assert ("≤ 100" in words or "<= 100" in words) and "40 MPa" in words


def test_the_project_page_offers_the_formats(signed_in):
    set_id = project(signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/sections/1"))
    assert "fmt=tracked" in page and "fmt=pdf" in page and "Word with tracked changes" in page


# --- the hold -------------------------------------------------------------------------

def test_the_hold_stops_every_format(signed_in):
    load(signed_in, "SPC-032000.docx",
         "# PRODUCTS\n## REINFORCEMENT\n- Tie wire to Section 016000.\n",
         "032000", "CONCRETE REINFORCING")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Held"}))
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["1"]})
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Held", "hold_shown": "1",
                                                  "hold_issue": "1"})
    for fmt in ("", "docx", "tracked", "pdf"):
        held = signed_in.get(f"/specs/sets/{set_id}/export" + (f"?fmt={fmt}" if fmt else ""))
        assert held.status_code == 302 and "/check" in held.headers["Location"], fmt
        if fmt in ("tracked", "pdf"):
            assert f"fmt={fmt}" in held.headers["Location"]
