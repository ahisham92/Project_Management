"""The specification writer.

What matters is the promise the program makes: one master text, a project copy
whose every amendment is known, a newer master brought in without losing them,
and every section issued in the same Word format whatever it was drafted in.
"""

from __future__ import annotations

import html
import io
import re
import zipfile

from app import specs

MASTER_TEXT = """\
# GENERAL
## RELATED DOCUMENTS
- Drawings and general provisions of the Contract apply to this Section.
## SUMMARY
- Section Includes:
-- Steel reinforcement bars.
-- Welded-wire reinforcement.
## ACTION SUBMITTALS
- Product Data: For each type of steel reinforcement.
- {if leed=v4|v4.1} Sustainable Design Submittals:
-- {if leed=v4} Product data for LEED v4.
-- {if leed=v4.1} Product data for LEED v4.1.
// Keep the LEED paragraphs in step with the credit being targeted.

# PRODUCTS
## STEEL REINFORCEMENT
- Reinforcing Bars: BS 4449 grade B500B, approved by the {{engineer}}.
| Bar | Grade |
| B500B | 500 MPa |

# EXECUTION
## INSTALLATION
- Hold the reinforcement in place.
"""


def text(response) -> str:
    return response.get_data(as_text=True)


def master_nodes():
    return specs.align([], specs.from_text(MASTER_TEXT))


def docx_of(nodes, number="032000", title="CONCRETE REINFORCING", project=None, chosen=None,
            values=None) -> bytes:
    return specs.write_docx({"number": number, "title": title}, nodes,
                            project or {"header_left": "Port Works\nPhase 2",
                                        "header_right": "Final Design\nHarbour",
                                        "doc_code": "N1-SPC-01", "revision": "0"},
                            chosen or {"leed": "v4.1"}, values or {"engineer": "Engineer"})


def part(data: bytes, name: str) -> str:
    return zipfile.ZipFile(io.BytesIO(data)).read(name).decode("utf-8")


def drifted_docx() -> bytes:
    """A section typed in Normal with the numbers typed by hand — the kind that
    drifts from the house format — as a bare Word package."""
    lines = ["SECTION 032000 - CONCRETE REINFORCING", "PART 1 - GENERAL",
             "1.1\tRELATED DOCUMENTS", "A.\tDrawings and general provisions of the Contract apply to this Section.",
             "1.2\tSUMMARY:", "A.\tSection Includes:", "1.\tSteel reinforcement bars.",
             "2.\tWelded-wire reinforcement.", "3.\tPlain dowels.",
             "PART 2 - PRODUCTS", "2.1\tSTEEL REINFORCEMENT",
             "A.\tReinforcing Bars: BS 4449 grade B500B.", "END OF SECTION 032000"]

    def para(line: str) -> str:
        runs = "<w:r><w:tab/></w:r>".join(
            f'<w:r><w:t xml:space="preserve">{bit}</w:t></w:r>' for bit in line.split("\t"))
        return f"<w:p>{runs}</w:p>"

    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body>" + "".join(para(line) for line in lines) + "</w:body></w:document>")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", document)
    return out.getvalue()


def upload(client, url, files):
    return client.post(url, data={"files": [(io.BytesIO(data), name) for name, data in files]},
                       content_type="multipart/form-data")


# --- the text and its numbers ---------------------------------------------------

def test_the_text_round_trips_and_numbers_itself():
    nodes = master_nodes()
    assert specs.from_text(specs.to_text(nodes)) == [
        {k: n[k] for k in ("level", "text", "when")} for n in nodes]

    shown = specs.number(nodes, {"leed": "v4.1"})
    labels = [(n["label"], n["text"][:20]) for n in shown if n["label"]]
    assert labels[:6] == [("PART 1 -", "GENERAL"), ("1.1", "RELATED DOCUMENTS"),
                          ("A.", "Drawings and general"), ("1.2", "SUMMARY"),
                          ("A.", "Section Includes:"), ("1.", "Steel reinforcement ")]
    # The paragraph for another LEED version is out, and takes no number.
    leed = [n for n in shown if "LEED" in n["text"] and n["level"] == "PR2"]
    assert [(n["included"], n["label"]) for n in leed] == [(False, ""), (True, "1.")]
    assert ("2.1", "STEEL REINFORCEMENT") in labels


def test_a_heading_switched_off_takes_what_is_under_it():
    shown = specs.number(master_nodes(), {"leed": "None"})
    out = [n["text"] for n in shown if not n["included"] and n["level"] != "CMT"]
    assert out == ["Sustainable Design Submittals:", "Product data for LEED v4.",
                   "Product data for LEED v4.1."]


def test_conditions():
    assert specs.applies("", {})
    assert specs.applies("leed=v4|v4.1", {"leed": "V4.1"})
    assert not specs.applies("leed=v4", {"leed": "v4.1"})
    assert specs.applies("leed!=none", {"leed": "v4"})
    assert not specs.applies("leed=v4 & exposure=marine", {"leed": "v4", "exposure": "general"})
    assert not specs.applies("leed=v4", {})


# --- amendments -----------------------------------------------------------------

def test_an_edit_keeps_ids_so_amendments_are_known():
    master = master_nodes()
    edited = specs.to_text(master).replace("- Section Includes:", "- Section Includes the following:") \
        .replace("-- Welded-wire reinforcement.\n", "") + "- Project specific requirement.\n"
    ours = specs.align(master, specs.from_text(edited))
    counted = specs.amendments(master, ours)
    assert (counted["added"], counted["changed"], counted["removed"]) == (1, 1, 1)
    changed = next(m for m in counted["marked"] if m["state"] == "changed")
    assert changed["was"]["text"] == "Section Includes:"
    removed = next(m for m in counted["marked"] if m["state"] == "removed")
    assert removed["text"] == "Welded-wire reinforcement."


def test_a_newer_master_comes_in_without_losing_the_projects_amendments():
    base = master_nodes()
    ours = specs.align(base, specs.from_text(
        specs.to_text(base).replace("- Section Includes:", "- Section Includes (project):")
        .replace("-- Welded-wire reinforcement.\n", "-- Welded-wire reinforcement.\n-- Project dowels.\n")))
    newer = specs.align(base, specs.from_text(
        specs.to_text(base).replace("in place.", "in place (v2).")
        .replace("## INSTALLATION\n", "## INSTALLATION\n- Clean reinforcement first.\n")
        .replace("-- Steel reinforcement bars.\n", "")))
    merged = specs.to_text(specs.merge(base, newer, ours))
    assert "Section Includes (project):" in merged           # the project's rewording kept
    assert "-- Project dowels." in merged                     # the project's addition kept
    assert "in place (v2)." in merged             # the master's rewording taken
    assert "- Clean reinforcement first." in merged           # the master's addition taken
    assert "Steel reinforcement bars." not in merged          # the master's deletion taken
    assert merged.index("Clean reinforcement first") < merged.index("(v2)")


# --- Word -----------------------------------------------------------------------

def test_a_section_is_written_in_the_house_styles_with_its_header_and_footer():
    data = docx_of(master_nodes())
    document = part(data, "word/document.xml")
    assert '<w:pStyle w:val="SCT"/>' in document and "END OF SECTION 032000" in document
    assert re.search(r'<w:pStyle w:val="ART"/><w:numPr><w:ilvl w:val="3"/>', document)
    assert re.search(r'<w:pStyle w:val="PR2"/><w:numPr><w:ilvl w:val="5"/>', document)
    assert "LEED v4.1" in document and "LEED v4." not in document.replace("LEED v4.1", "")
    assert "Keep the LEED paragraphs" not in document                # notes are never issued
    assert "approved by the Engineer" in document                   # variables filled in
    assert "<w:tbl>" in document and "500 MPa" in document
    header = part(data, "word/header1.xml")
    assert "Port Works" in header and "Final Design" in header and "Harbour" in header
    footer = part(data, "word/footer1.xml")
    assert "CONCRETE REINFORCING" in footer and "032000 - Page " in footer
    assert "NUMPAGES" in footer and "N1-SPC-01 REV 0" in footer


def test_a_drifted_section_is_read_back_into_the_house_levels():
    read = specs.read_docx(drifted_docx())
    assert (read["number"], read["title"]) == ("032000", "CONCRETE REINFORCING")
    assert [(n["level"], n["text"]) for n in read["nodes"]][:8] == [
        ("PRT", "GENERAL"), ("ART", "RELATED DOCUMENTS"),
        ("PR1", "Drawings and general provisions of the Contract apply to this Section."),
        ("ART", "SUMMARY"), ("PR1", "Section Includes:"),
        ("PR2", "Steel reinforcement bars."), ("PR2", "Welded-wire reinforcement."),
        ("PR2", "Plain dowels.")]


def test_what_is_written_reads_back_the_same():
    nodes = master_nodes()
    read = specs.read_docx(docx_of(nodes, chosen={"leed": "v4"}))
    issued = [n for n in specs.number(nodes, {"leed": "v4"}) if n["included"] and n["level"] != "CMT"]
    assert [n["level"] for n in read["nodes"]] == [n["level"] for n in issued]
    assert [n["text"] for n in read["nodes"] if n["level"] != "TBL"] == [
        specs.fill(n["text"], {"engineer": "Engineer"}) for n in issued if n["level"] != "TBL"]
    table = next(n for n in read["nodes"] if n["level"] == "TBL")
    assert specs.rows_of(table["text"]) == [["Bar", "Grade"], ["B500B", "500 MPa"]]


def test_a_house_template_without_the_styles_is_refused():
    try:
        specs.template_info(drifted_docx())
    except specs.SpecError as exc:
        assert "styles" in str(exc)
    else:
        raise AssertionError("a template with no styles was accepted")
    assert specs.template_info(specs.TEMPLATE.read_bytes())["num_id"]


# --- the pages ------------------------------------------------------------------

def test_the_door_and_the_pages(signed_in):
    assert "Open the Specs Writer" in text(signed_in.get("/"))
    assert signed_in.get("/specs/").status_code == 200


def test_the_whole_round(app, signed_in):
    master = docx_of(master_nodes(), chosen={"leed": "v4.1"})
    answer = upload(signed_in, "/specs/library/upload", [("SPC-032000.docx", master)])
    assert answer.status_code == 302
    assert "CONCRETE REINFORCING" in text(signed_in.get("/specs/library"))

    answer = signed_in.post("/specs/sets", data={"name": "Harbour Works", "code": "HW-001"})
    set_id = int(answer.headers["Location"].split("#")[0].rstrip("/").rsplit("/", 1)[1])
    signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Harbour Works", "code": "HW-001", "header_left": "Port Works", "doc_code": "N1",
        "revision": "1", "file_pattern": "SPC-FD-{number}-ST", "opt_leed": "v4.1",
        "hold_shown": "1"})                                  # issued without settling the check
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["1"]})
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert "As the master" in page

    # Amend it.
    edit = text(signed_in.get(f"/specs/sets/{set_id}/sections/1/edit"))
    body = re.search(r'<textarea name="text"[^>]*>(.*?)</textarea>', edit, re.S).group(1)
    body = html.unescape(body).replace("- Section Includes:", "- Section Includes the following:")
    signed_in.post(f"/specs/sets/{set_id}/sections/1/edit", data={"text": body, "title": "CONCRETE REINFORCING"})
    assert "1 changed" in text(signed_in.get(f"/specs/sets/{set_id}"))
    assert "Section Includes:" in text(signed_in.get(f"/specs/sets/{set_id}/amendments"))

    # Issue it.
    bundle = signed_in.get(f"/specs/sets/{set_id}/export")
    names = zipfile.ZipFile(io.BytesIO(bundle.data)).namelist()
    assert names == ["SPC-FD-032000-ST.docx"]
    one = signed_in.get(f"/specs/sets/{set_id}/sections/1/docx")
    assert "Section Includes the following" in part(one.data, "word/document.xml")
    assert "N1 REV 1" in part(one.data, "word/footer1.xml")

    # The master moves on; the project brings it in and keeps its amendment.
    library = text(signed_in.get("/specs/library/1/edit"))
    master_text = html.unescape(re.search(r'<textarea name="text"[^>]*>(.*?)</textarea>', library, re.S).group(1))
    signed_in.post("/specs/library/1/edit", data={
        "number": "032000", "title": "CONCRETE REINFORCING", "note": "v2",
        "text": master_text.replace("in place.", "in place, v2.")})
    assert "Master is now v2" in text(signed_in.get(f"/specs/sets/{set_id}"))
    signed_in.post(f"/specs/sets/{set_id}/sections/1/update")
    docx = part(signed_in.get(f"/specs/sets/{set_id}/sections/1/docx").data, "word/document.xml")
    assert "in place, v2." in docx and "Section Includes the following" in docx


def test_an_old_project_file_shows_up_as_amendments(signed_in):
    upload(signed_in, "/specs/library/upload", [("SPC-032000.docx", docx_of(master_nodes()))])
    answer = signed_in.post("/specs/sets", data={"name": "Old job"})
    set_id = int(answer.headers["Location"].split("#")[0].rstrip("/").rsplit("/", 1)[1])
    upload(signed_in, f"/specs/sets/{set_id}/upload", [("old.docx", drifted_docx())])
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert "CONCRETE REINFORCING" in page and "added" in page and "dropped" in page


def test_only_an_administrator_changes_the_master(app, signed_in):
    upload(signed_in, "/specs/library/upload", [("SPC-032000.docx", docx_of(master_nodes()))])
    signed_in.post("/admin/users", data={"username": "sara", "password": "longenough1",
                                         "name": "Sara", "programs": ["specs"]})
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    assert sara.get("/specs/").status_code == 200
    assert sara.get("/projects").status_code == 403
    sara.post("/specs/library/1/edit", data={"text": "# NOTHING", "number": "032000"})
    assert "Drawings and general provisions" in text(sara.get("/specs/library/1"))
    answer = upload(sara, "/specs/library/upload", [("SPC-033000.docx", docx_of([], number="033000"))])
    assert "033000" not in text(sara.get("/specs/library"))
    assert answer.status_code == 302
    # But writes a project's specification like anybody else.
    assert sara.post("/specs/sets", data={"name": "Sara's"}).status_code == 302


def test_an_account_without_the_program_is_kept_out(app, signed_in):
    signed_in.post("/admin/users", data={"username": "omar", "password": "longenough1",
                                         "name": "Omar", "programs": ["pm"]})
    omar = app.test_client()
    omar.post("/login", data={"email": "omar", "password": "longenough1"})
    assert omar.get("/specs/").status_code == 403
    assert "Open the Specs Writer" not in text(omar.get("/"))
