"""Kinds of specification (03A, 15A, 16A), the elements a project ticks, and
the sections its answers put in by themselves."""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile

from app import specs
from app.db import init_db
from .test_specs import docx_of, text, upload

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def set_id_of(answer) -> int:
    return int(answer.headers["Location"].split("#")[0].rstrip("/").rsplit("/", 1)[1])


def load(client, filename, body, number, title, family=""):
    nodes = specs.align([], specs.from_text(body))
    return client.post("/specs/library/upload", data={
        "family": family, "files": [(io.BytesIO(docx_of(nodes, number=number, title=title,
                                                        chosen={})), filename)]},
        content_type="multipart/form-data")


def applies(app, number, family, condition):
    from app import specs_store

    with app.app_context():
        specs_store.set_applies(specs_store.section_by_number(number, family)["id"], condition)


# --- NBS sections (the British kind) --------------------------------------------------

def nbs_docx(template=False) -> bytes:
    """An NBS section as the office writes one: Word's headings for the title,
    the groups and the clauses, one bulleted list under them."""
    styles = ("<w:styles %s>" % W + "".join(
        f'<w:style w:type="paragraph" w:styleId="{sid}"><w:name w:val="{name}"/></w:style>'
        for sid, name in (("Heading1", "heading 1"), ("Heading2", "heading 2"),
                          ("Heading3", "heading 3"), ("ListParagraph", "List Paragraph")))
              + "</w:styles>")

    def p(style, words, ilvl=None):
        num = (f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="7"/></w:numPr>'
               if ilvl is not None else "")
        return (f'<w:p><w:pPr><w:pStyle w:val="{style}"/>{num}</w:pPr>'
                f'<w:r><w:t xml:space="preserve">{words}</w:t></w:r></w:p>')

    body = [p("Heading1", "E30 - REINFORCEMENT FOR IN SITU CONCRETE"),
            p("Heading2", "REINFORCEMENT"),
            p("Heading3", "110 QUALITY ASSURANCE OF REINFORCEMENT"),
            p("ListParagraph", "Standards:", 0),
            p("ListParagraph", "Reinforcement: To BS 4449.", 1),
            p("Heading3", "150 RIBBED BAR REINFORCEMENT"),
            p("ListParagraph", "Strength grade: [B500B] [B500C].", 0)]
    if template:
        body = [p("Heading1", "x"), p("Heading2", "x"), p("Heading3", "x"), p("ListParagraph", "x", 0)]
    document = (f'<w:document {W}><w:body>' + "".join(body)
                + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
    return out.getvalue()


def test_an_nbs_section_reads_as_groups_clauses_and_lists():
    read = specs.read_docx(nbs_docx())
    assert (read["number"], read["title"]) == ("E30", "REINFORCEMENT FOR IN SITU CONCRETE")
    assert [(n["level"], n["text"]) for n in read["nodes"]] == [
        ("PRT", "REINFORCEMENT"), ("ART", "110 QUALITY ASSURANCE OF REINFORCEMENT"),
        ("PR1", "Standards:"), ("PR2", "Reinforcement: To BS 4449."),
        ("ART", "150 RIBBED BAR REINFORCEMENT"), ("PR1", "Strength grade: [B500B] [B500C].")]
    numbered = specs.number(read["nodes"])
    # The clause keeps its own number; nothing is numbered 1.1 over it.
    assert [(n["label"], n["path"]) for n in numbered[:3]] == [("", ""), ("", "110"), ("•", "110.1")]


def test_an_nbs_section_goes_out_in_an_nbs_template():
    read = specs.read_docx(nbs_docx())
    template = nbs_docx(template=True)
    assert specs.template_info(template)["layout"] == "nbs"
    out = specs.write_docx({"number": "E30", "title": read["title"]}, read["nodes"],
                           {"revision": "0"}, {}, {}, template)
    document = zipfile.ZipFile(io.BytesIO(out)).read("word/document.xml").decode("utf-8")
    assert "E30 - REINFORCEMENT" in "".join(document.split("</w:t></w:r><w:r><w:t xml:space=\"preserve\">"))
    assert "SECTION " not in document and "END OF SECTION" not in document
    # Headings carry no list number; the lines under them are the template's list.
    assert '<w:pStyle w:val="Heading3"/></w:pPr>' in document
    assert '<w:pStyle w:val="ListParagraph"/><w:numPr><w:ilvl w:val="1"/><w:numId w:val="7"/>' in document
    # And it reads back the same.
    assert [n["text"] for n in specs.read_docx(out)["nodes"]] == [n["text"] for n in read["nodes"]]


def test_section_numbers_and_kinds_come_from_the_office_file_names():
    assert specs.number_from_filename("STD15A_SPC_071352.13_ST_App-Modified_REVA3.docx") == "071352.13"
    assert specs.number_from_filename("STD03A_SPC_J30A_ST_LIQUID APPLIED_REVA1.docx") == "J30A"
    assert specs.number_from_filename("STD16A_SPC_033000_ST_Cast-In-Place Concrete_REVA.docx") == "033000"
    assert specs.number_from_filename("SPC-FD-032000-ST.docx") == "032000"
    assert specs.family_from_filename("STD16A_SPC_033000_ST_x.docx") == "16A"
    assert specs.family_from_filename("N25185-0100D-FD-APA-00-SPC-15A-ST-01") == "15A"
    assert specs.family_from_filename("SPC-033000.docx") == ""


# --- the library keeps each kind apart ---------------------------------------------------

def test_each_kind_numbers_its_own_sections(app, signed_in):
    load(signed_in, "STD15A_SPC_033000_ST_Concrete.docx", "# GENERAL\n## SUMMARY\n- American.\n",
         "033000", "CAST-IN-PLACE CONCRETE")
    load(signed_in, "STD16A_SPC_033000_ST_Concrete.docx", "# GENERAL\n## SUMMARY\n- Saudi.\n",
         "033000", "CAST-IN-PLACE CONCRETE")
    load(signed_in, "SPC-E30.docx", "# REINFORCEMENT\n## 110 QUALITY\n- British.\n", "E30",
         "REINFORCEMENT", family="03A")
    from app import specs_store

    with app.app_context():
        rows = {(s["family"], s["number"]) for s in specs_store.library()}
        assert rows == {("15A", "033000"), ("16A", "033000"), ("03A", "E30")}
        counts = {f["code"]: f["sections"] for f in specs_store.families()}
        assert counts == {"03A": 1, "15A": 1, "16A": 1}
    page = text(signed_in.get("/specs/library?family=16A"))
    assert "16A sections (1)" in page
    # The library file carries the kind, and reading it back keeps them apart.
    data = signed_in.get("/specs/library/file").data
    sections = json.loads(zipfile.ZipFile(io.BytesIO(data)).read("library.json"))["sections"]
    assert sorted((s["family"], s["number"]) for s in sections) == sorted(rows)
    with app.app_context():
        counted = specs_store.unpack(data)
        assert counted["sections"] == 3 and len(specs_store.library()) == 3


def test_a_kind_can_have_its_own_template_and_it_travels(app, signed_in):
    signed_in.post("/specs/template", data={"family": "03A", "template": (
        io.BytesIO(nbs_docx(template=True)), "nbs.docx")}, content_type="multipart/form-data")
    from app import specs_store

    with app.app_context():
        assert specs.template_info(specs_store.template_bytes("03A"))["layout"] == "nbs"
        assert specs_store.template_bytes("15A") is None          # the built-in one
    names = zipfile.ZipFile(io.BytesIO(signed_in.get("/specs/library/file").data)).namelist()
    assert "templates/03A.docx" in names


def test_a_library_from_before_the_kinds_becomes_15a(tmp_path):
    """The live layout: one number across the library, versions and project
    copies hanging off each section by id."""
    path = tmp_path / "old.sqlite"
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript("""
        DROP TABLE spec_sections;
        CREATE TABLE spec_sections (
            id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL DEFAULT '', body TEXT NOT NULL DEFAULT '[]',
            version INTEGER NOT NULL DEFAULT 1, note TEXT NOT NULL DEFAULT '',
            updated_by TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            applies TEXT NOT NULL DEFAULT '');
        INSERT INTO spec_sections (id, number, title, version) VALUES (7, '033000', 'CONCRETE', 2);
        INSERT INTO spec_section_versions (section_id, version, title) VALUES (7, 1, 'CONCRETE');
        INSERT INTO spec_section_versions (section_id, version, title) VALUES (7, 2, 'CONCRETE');
        INSERT INTO spec_sets (id, name) VALUES (3, 'Old project');
        INSERT INTO spec_set_sections (set_id, section_id, number, title) VALUES (3, 7, '033000', 'CONCRETE');
    """)
    conn.commit()
    conn.close()
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    assert conn.execute("SELECT id, family, number FROM spec_sections").fetchall() == [(7, "15A", "033000")]
    assert conn.execute("SELECT COUNT(*) FROM spec_section_versions WHERE section_id = 7").fetchone() == (2,)
    assert conn.execute("SELECT section_id FROM spec_set_sections").fetchall() == [(7,)]
    assert conn.execute("SELECT family FROM spec_sets WHERE id = 3").fetchone() == ("15A",)
    conn.execute("INSERT INTO spec_sections (family, number) VALUES ('16A', '033000')")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # Deleting a section still takes its versions with it.
    conn.execute("DELETE FROM spec_sections WHERE id = 7")
    assert conn.execute("SELECT COUNT(*) FROM spec_section_versions").fetchone() == (0,)
    conn.close()


# --- elements, and the sections that follow them ------------------------------------------

def test_ticking_an_element_adds_its_section_and_says_so(app, signed_in):
    load(signed_in, "STD15A_SPC_033713_ST_Shotcrete.docx", "# GENERAL\n## SUMMARY\n- Shotcrete.\n",
         "033713", "SHOTCRETE")
    load(signed_in, "STD16A_SPC_033713_ST_Shotcrete.docx", "# GENERAL\n## SUMMARY\n- Shotcrete.\n",
         "033713", "SHOTCRETE")
    applies(app, "033713", "15A", "shotcrete=Yes")
    applies(app, "033713", "16A", "shotcrete=Yes")
    answer = signed_in.post("/specs/sets", data={"name": "Tunnel", "family": "16A"})
    set_id = set_id_of(answer)
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert 'class="spec-tile' in page and 'name="tile_shotcrete"' in page
    assert "spec-icon" in page                                     # the drawings
    # A new 16A project starts on the American basis with SASO.
    from app import specs_store

    with app.app_context():
        chosen = specs_store.chosen_for(specs_store.spec_set(set_id))
        assert (chosen["standards"], chosen["conformity"]) == ("ACI/ASTM", "SASO SABER")
    answer = signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Tunnel", "tile_shown": ["shotcrete", "precast"], "tile_shotcrete": "1"},
        follow_redirects=True)
    body = text(answer)
    assert "Added 1 section the answers call for" in body and "033713</strong> Shotcrete" in body
    with app.app_context():
        rows = specs_store.set_sections(set_id)
        assert [(r["number"], r["section_id"]) for r in rows] == [
            ("033713", specs_store.section_by_number("033713", "16A")["id"])]
        chosen = specs_store.chosen_for(specs_store.spec_set(set_id))
        assert chosen["shotcrete"] == "Yes" and chosen["precast"] == "None"
    # Unticked, the section stays (it may carry amendments) but is named.
    answer = signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Tunnel", "tile_shown": ["shotcrete"]}, follow_redirects=True)
    assert "No longer called for by the answers" in text(answer)


def test_a_section_taken_out_by_hand_stays_out(app, signed_in):
    load(signed_in, "STD15A_SPC_033713_ST_Shotcrete.docx", "# GENERAL\n## SUMMARY\n- Shotcrete.\n",
         "033713", "SHOTCRETE")
    applies(app, "033713", "15A", "shotcrete=Yes")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Tunnel", "family": "15A"}))
    form = {"name": "Tunnel", "tile_shown": ["shotcrete"], "tile_shotcrete": "1"}
    signed_in.post(f"/specs/sets/{set_id}", data=form)
    from app import specs_store

    with app.app_context():
        row_id = specs_store.set_sections(set_id)[0]["id"]
    signed_in.post(f"/specs/sets/{set_id}/sections/{row_id}/remove")
    signed_in.post(f"/specs/sets/{set_id}", data=form)
    with app.app_context():
        assert specs_store.set_sections(set_id) == []
    assert "taken out of this specification: accept if that was meant" in text(
        signed_in.get(f"/specs/sets/{set_id}/check"))
    # Added back by hand, it is the project's again.
    with app.app_context():
        section_id = specs_store.section_by_number("033713", "15A")["id"]
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    with app.app_context():
        assert specs_store.declined(specs_store.spec_set(set_id)) == set()


def test_a_section_for_every_project_of_a_kind(app, signed_in):
    load(signed_in, "STD03A_SPC_B50_ST_GENERAL.docx", "# GENERAL\n## 110 SCOPE\n- All works.\n",
         "B50", "GENERAL STRUCTURAL REQUIREMENTS")
    applies(app, "B50", "03A", "*")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "School", "family": "03A"}))
    answer = signed_in.post(f"/specs/sets/{set_id}", data={"name": "School"}, follow_redirects=True)
    assert "every project of this kind" in text(answer)
    assert "every 03A project" in text(signed_in.get("/specs/library?family=03A"))


def test_an_answer_no_section_of_the_kind_covers_is_said(app, signed_in):
    load(signed_in, "STD16A_SPC_033000_ST_Concrete.docx", "# GENERAL\n## SUMMARY\n- Concrete.\n",
         "033000", "CAST-IN-PLACE CONCRETE")
    load(signed_in, "STD15A_SPC_355913_ST_Fenders.docx", "# PRODUCTS\n## FENDERS\n- Cone.\n",
         "355913", "MARINE FENDERS")
    applies(app, "355913", "15A", "structures=Marine structures&fenders=Cone|Cell")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Jeddah quay", "family": "16A"}))
    signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Jeddah quay", "opt_structures": ["Marine structures"], "opt_fenders": "Cell",
        "tile_shown": ["structures"]})
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    # 16A has no fender section: the answer is flagged, and 15A's is on offer to borrow.
    assert "Fender type: Cell" in page
    assert "Sections of the other kinds" in page and "355913" in page


# --- people's own projects ------------------------------------------------------------------

def test_each_person_sees_their_own_projects_first(app, signed_in):
    signed_in.post("/admin/users", data={"username": "sara", "password": "longenough1",
                                         "name": "Sara", "programs": ["specs"]})
    signed_in.post("/specs/sets", data={"name": "Admin harbour", "family": "15A"})
    sara = app.test_client()
    sara.post("/login", data={"email": "sara", "password": "longenough1"})
    sara.post("/specs/sets", data={"name": "Sara school", "family": "03A"})
    page = text(sara.get("/specs/"))
    mine, others = page.split("<h2>My projects</h2>", 1)[1].split("<h2>Other people", 1)
    assert "Sara school" in mine and "Admin harbour" not in mine
    assert "Admin harbour" in others


# --- the check -----------------------------------------------------------------------------

def test_many_bracketed_choices_are_one_item_for_the_section():
    from app import specs_check

    body = "# PRODUCTS\n## MIXES\n" + "".join(f"- Choice [{i}] here.\n" for i in range(8))
    nodes = specs.align([], specs.from_text(body))
    report = specs_check.check([{"id": 1, "number": "033000", "title": "CONCRETE", "nodes": nodes}],
                               {}, {}, [], specs_check.Standards([], []))
    brackets = [i for i in report["setup"] if "square brackets" in i["message"]]
    assert len(brackets) == 1 and brackets[0]["message"].startswith("8 choices")
    few = specs.align([], specs.from_text("# PRODUCTS\n## MIXES\n- One [a] and [b].\n"))
    report = specs_check.check([{"id": 1, "number": "033000", "title": "CONCRETE", "nodes": few}],
                               {}, {}, [], specs_check.Standards([], []))
    assert len([i for i in report["setup"] if "in brackets" in i["message"]]) == 2


# --- the model -----------------------------------------------------------------------

def test_a_project_started_from_the_model_ticks_adds_and_flags(app, signed_in):
    from tests.test_specs_model import IFC4
    from app import specs_store

    load(signed_in, "STD15A_SPC_355913_ST_Fenders.docx", "# GENERAL\n## SUMMARY\n- Fenders.\n",
         "355913", "FENDERS")
    applies(app, "355913", "15A", "fenders!=None")
    ifc = IFC4.replace("Concrete C32/40", "Concrete 3 MPa").replace("32000000.", "3000000.")
    answer = signed_in.post("/specs/sets", data={
        "name": "Quay", "family": "15A", "model": [(io.BytesIO(ifc.encode()), "Quay.ifc")]},
        content_type="multipart/form-data")
    set_id = set_id_of(answer)
    assert answer.headers["Location"].endswith("#step-elements")
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert "Read Quay.ifc" in page and "does not look realistic" in page
    assert "Added 1 section the answers call for" in page
    assert "From the model: Quay.ifc" in page and "In the model" in page
    with app.app_context():
        row = specs_store.spec_set(set_id)
        chosen = specs_store.chosen_for(row)
        assert chosen["fenders"] == "Cone" and chosen["post_tensioning"] == "Unbonded"
        assert [r["number"] for r in specs_store.set_sections(set_id)] == ["355913"]
    check = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "The model&#39;s grades" in check or "The model's grades" in check
    assert "below any structural concrete" in check
    # Forgotten, the model's grades leave the check; its ticks stay.
    signed_in.post(f"/specs/sets/{set_id}/model", data={"action": "forget"})
    assert "below any structural concrete" not in text(signed_in.get(f"/specs/sets/{set_id}/check"))
    with app.app_context():
        assert specs_store.chosen_for(specs_store.spec_set(set_id))["fenders"] == "Cone"


def test_a_revit_file_itself_is_turned_away_plainly(app, signed_in):
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Quay", "family": "15A"}))
    answer = signed_in.post(f"/specs/sets/{set_id}/model", data={
        "model": [(io.BytesIO(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600), "Quay.rvt")]},
        content_type="multipart/form-data", follow_redirects=True)
    body = text(answer)
    assert "Quay.rvt" in body and "File → Export → IFC" in body


# --- loading a library file over one, and taking sections out -------------------------

def _library_with(app, signed_in, *numbers):
    from app import specs_store

    for number in numbers:
        load(signed_in, f"STD15A_SPC_{number}_ST_S.docx", "# GENERAL\n## SUMMARY\n- Old words.\n",
             number, f"SECTION {number}")
    with app.app_context():
        return specs_store.pack()


def test_a_library_file_can_add_update_or_replace(app, signed_in):
    from app import specs_store

    packed = _library_with(app, signed_in, "033000", "033713")
    # Here: 033000 amended, 034100 extra; the file has 033000 and 033713 as they were.
    with app.app_context():
        s = specs_store.section_by_number("033000", "15A")
        specs_store.save_section("033000", s["title"], specs.align(specs.loads(s["body"]), specs.from_text(
            "# GENERAL\n## SUMMARY\n- New words.\n")), section_id=s["id"])
    load(signed_in, "STD15A_SPC_034100_ST_Precast.docx", "# GENERAL\n## SUMMARY\n- P.\n",
         "034100", "PRECAST")
    load(signed_in, "STD03A_SPC_E10_ST_Concrete.docx", "# GENERAL\n## 110 SCOPE\n- E.\n",
         "E10", "IN SITU CONCRETE")

    def post(mode, **more):
        return text(signed_in.post("/specs/library/file", data={
            "mode": mode, "library": [(io.BytesIO(packed), "lib.zip")], **more},
            content_type="multipart/form-data", follow_redirects=True))

    def words(number):
        with app.app_context():
            return specs_store.section_by_number(number, "15A")["body"]

    assert "left as they are" in post("add") and "New words" in words("033000")
    assert "updated to a new version" in post("update") and "Old words" in words("033000")
    # Replace asks to be meant first, then takes out 034100 but not the 03A section.
    assert "Tick that you mean" in post("replace")
    with app.app_context():
        assert specs_store.section_by_number("034100", "15A")
    assert "taken out (15A 034100)" in post("replace", sure="yes")
    with app.app_context():
        assert specs_store.section_by_number("034100", "15A") is None
        assert specs_store.section_by_number("E10", "03A")


def test_ticked_sections_are_taken_out_of_the_library(app, signed_in):
    from app import specs_store

    _library_with(app, signed_in, "033000", "033713", "034100")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Quay", "family": "15A"}))
    with app.app_context():
        ids = {n: specs_store.section_by_number(n, "15A")["id"] for n in ("033000", "033713", "034100")}
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(ids["033000"])]})
    page = text(signed_in.get("/specs/library?family=15A"))
    assert 'form="library-delete"' in page and "Take the ticked out" in page
    answer = text(signed_in.post("/specs/library/delete", data={
        "family": "15A", "section_id": [str(ids["033000"]), str(ids["033713"])]},
        follow_redirects=True))
    assert "Took 2 sections out of the library: 033000, 033713" in answer
    with app.app_context():
        assert [s["number"] for s in specs_store.library("15A")] == ["034100"]
        # The project keeps its copy.
        assert [r["number"] for r in specs_store.set_sections(set_id)] == ["033000"]
