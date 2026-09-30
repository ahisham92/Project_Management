"""The structural elements a project says it has: the question, its tiles on
step 2, the engineer's own elements, conditions on them, and what a Revit
export ticks."""

from __future__ import annotations

import io
import json
import re
import sqlite3

from app import specs, specs_model, specs_seed
from app.db import init_db
from .test_specs import text
from .test_specs_kinds import applies, load, set_id_of

LABELS = ["Piles", "Pile caps", "Foundations", "Slab on grade", "Columns", "Beams",
          "Suspended slabs and floors", "Walls", "Basement walls", "Retaining walls", "Precast",
          "Deck", "Quay walls", "Blinding", "Topping", "Water-retaining structures"]
SLUGS = ["piles", "pile_caps", "foundations", "slab_on_grade", "columns", "beams", "slabs", "walls",
         "basement_walls", "retaining_walls", "precast", "deck", "quay_walls", "blinding", "topping",
         "water_retaining"]


def chosen_of(app, set_id):
    from app import specs_store

    with app.app_context():
        return specs_store.chosen_for(specs_store.spec_set(set_id))


def new_set(client, name="Tower", family="15A"):
    return set_id_of(client.post("/specs/sets", data={"name": name, "family": family}))


def tile(page, value):
    """The tile of one element: its tick box and everything to its label's end."""
    at = page.index(f'name="opt_elements" value="{value}"')
    return page[page.rindex("<label", 0, at):page.index("</label>", at)]


# --- the question and its slugs -----------------------------------------------------------

def test_the_question_and_the_slugs():
    row = next(o for o in specs_seed.OPTIONS if o[0] == "elements")
    assert row == ("elements", "Structural elements", "|".join(LABELS), "", "Elements", "many")
    assert [k[0] for k in specs_seed.ELEMENT_KINDS] == SLUGS
    assert [k[1] for k in specs_seed.ELEMENT_KINDS] == LABELS
    kinds = {"Buildings", "Marine structures", "Bridges"}
    for _slug, _label, usual in specs_seed.ELEMENT_KINDS:
        assert usual and set(usual.split("|")) <= kinds
    for slug, label in zip(SLUGS, LABELS):
        assert specs_seed.element_slug(label) == slug
        assert specs_seed.element_slug(label.upper()) == slug
        assert specs_seed.element_slug(slug) == slug
    # The engineer's own: lower case, anything but letters and digits made "_".
    assert specs_seed.element_slug("Transfer slab") == "transfer_slab"
    assert specs_seed.element_slug("  Piers & crossheads ") == "piers_crossheads"
    assert specs_seed.element_slug("Culvert (box)") == "culvert_box"


def test_a_new_library_has_the_question(tmp_path):
    path = tmp_path / "fresh.sqlite"
    init_db(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT label, choices, default_value, grp, kind FROM spec_options "
                        "WHERE key = 'elements'").fetchone() == (
        "Structural elements", "|".join(LABELS), "", "Elements", "many")
    assert conn.execute("SELECT COUNT(*) FROM spec_options WHERE key = 'elements'").fetchone() == (1,)
    conn.close()


def test_a_library_from_before_gets_it_and_keeps_its_own(tmp_path):
    path = tmp_path / "live.sqlite"
    init_db(path)
    conn = sqlite3.connect(path)
    # As the live site has it: its own questions edited, no elements question yet.
    conn.execute("DELETE FROM spec_options WHERE key = 'elements'")
    conn.execute("DELETE FROM spec_meta WHERE key = 'elements_option'")
    conn.execute("UPDATE spec_options SET label = 'Fenders', choices = 'None|Cone' WHERE key = 'fenders'")
    conn.execute("DELETE FROM spec_options WHERE key = 'tilt_up'")
    conn.execute("INSERT INTO spec_sets (id, name, options) VALUES (4, 'Live', ?)",
                 (json.dumps({"fenders": "Cone"}),))
    conn.commit()
    before = conn.execute("SELECT * FROM spec_options ORDER BY id").fetchall()
    last = conn.execute("SELECT MAX(position) FROM spec_options").fetchone()[0]
    conn.close()

    init_db(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT * FROM spec_options WHERE key != 'elements' ORDER BY id").fetchall() == before
    assert conn.execute("SELECT choices, default_value, kind, position FROM spec_options "
                        "WHERE key = 'elements'").fetchone() == ("|".join(LABELS), "", "many", last + 1)
    assert conn.execute("SELECT options FROM spec_sets WHERE id = 4").fetchone() == ('{"fenders": "Cone"}',)
    # Taken out again by the administrator, it stays out.
    conn.execute("DELETE FROM spec_options WHERE key = 'elements'")
    conn.commit()
    conn.close()
    init_db(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT 1 FROM spec_options WHERE key = 'elements'").fetchone() is None
    conn.close()


# --- step 2 ----------------------------------------------------------------------------------

def test_a_new_project_has_the_tiles_and_nothing_ticked(app, signed_in):
    set_id = new_set(signed_in)
    assert chosen_of(app, set_id)["elements"] == ""
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert "Structural elements" in page and "Add an element" in page
    for label in LABELS:
        assert "checked" not in tile(page, label)
    assert page.index("Structural elements") < page.index("What the project builds")
    # A building's usual elements first; a quay's under the fold.
    fold = page.index("More elements")
    assert tile(page, "Slab on grade") and page.index('value="Slab on grade"') < fold
    assert page.index('value="Deck"') > fold and page.index('value="Quay walls"') > fold
    for label in ("Piles", "Beams", "Deck"):
        assert re.search(r"<svg class=\"spec-icon\"[^>]*>\s*<path", tile(page, label))
    # Not asked a second time under Questions.
    assert page.count('name="opt_elements"') == len(LABELS)


def test_a_marine_project_puts_its_own_first(app, signed_in):
    set_id = new_set(signed_in, "Quay")
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Quay", "opt_structures": "Marine structures"})
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    fold = page.index("More elements")
    for label in ("Piles", "Deck", "Beams", "Slab on grade", "Quay walls"):
        assert page.index(f'name="opt_elements" value="{label}"') < fold
    for label in ("Columns", "Basement walls", "Topping"):
        assert page.index(f'name="opt_elements" value="{label}"') > fold


def test_ticking_and_an_element_of_the_projects_own(app, signed_in):
    set_id = new_set(signed_in)
    answer = signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Tower", "opt_elements": ["Piles", "Beams"], "element_new": "Transfer | slab ",
        "next": "elements"})
    assert answer.headers["Location"].endswith("#step-elements")
    assert chosen_of(app, set_id)["elements"] == "Piles|Beams|Transfer slab"
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    own = tile(page, "Transfer slab")
    assert "checked" in own and "Added" in own and "spec-icon" in own
    assert "checked" in tile(page, "Piles") and "checked" not in tile(page, "Columns")
    assert page.index('value="Transfer slab"') < page.index("More elements")

    # A listed one typed by hand is the listed one; one already there is not doubled.
    signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Tower", "opt_elements": ["Piles", "Beams", "Transfer slab"],
        "element_new": "slab ON grade"})
    assert chosen_of(app, set_id)["elements"] == "Piles|Beams|Transfer slab|Slab on grade"
    signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Tower", "opt_elements": ["Piles", "Transfer slab"], "element_new": "transfer slab"})
    assert chosen_of(app, set_id)["elements"] == "Piles|Transfer slab"

    # A ticked one from under the fold comes up with the rest.
    signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Tower", "opt_elements": ["Piles", "Transfer slab", "Deck"]})
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert page.index('value="Deck"') < page.index("More elements")

    # Unticked and saved, the project's own goes.
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "opt_elements": ["Piles"]})
    assert chosen_of(app, set_id)["elements"] == "Piles"
    assert 'value="Transfer slab"' not in text(signed_in.get(f"/specs/sets/{set_id}"))
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "tile_shown": "elements"})
    assert chosen_of(app, set_id)["elements"] == ""


def test_conditions_on_elements(app, signed_in):
    assert specs.applies("elements=Slab on grade", {"elements": "Piles|Slab on grade"})
    assert specs.applies("elements=slab on grade", {"elements": "Piles|Slab on grade"})
    assert not specs.applies("elements=Slab on grade", {"elements": "Piles"})
    # A project that has named no elements keeps every element's paragraphs.
    assert specs.applies("elements=Slab on grade", {"elements": ""})
    assert specs.applies("elements!=Slab on grade", {"elements": "Piles"})
    assert specs.applies("elements=Transfer slab", {"elements": "Piles|Transfer slab"})
    assert specs.applies("elements=Piles|Deck&structures=Marine structures",
                         {"elements": "Deck", "structures": "Marine structures"})

    load(signed_in, "STD15A_SPC_033100_ST_Slabs.docx", "# GENERAL\n## SUMMARY\n- Slab on grade.\n",
         "033100", "SLABS ON GRADE")
    applies(app, "033100", "15A", "elements=Slab on grade")
    set_id = new_set(signed_in)
    from app import specs_store

    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "opt_elements": ["Piles"]})
    with app.app_context():
        assert specs_store.set_sections(set_id) == []
    answer = signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Tower", "opt_elements": ["Piles"], "element_new": "Slab on grade"},
        follow_redirects=True)
    assert "Added 1 section the answers call for" in text(answer)
    with app.app_context():
        assert [r["number"] for r in specs_store.set_sections(set_id)] == ["033100"]


# --- from the model --------------------------------------------------------------------------

IFC = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');
FILE_NAME('Elements.ifc','2025-01-01T10:00:00',(''),(''),'ODA SDAI 24.1','Autodesk Revit 2024 (ENU)','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCORGANIZATION($,'Autodesk Revit 2024 (ENU)',$,$,$);
#2=IFCAPPLICATION(#1,'2024','Autodesk Revit 2024 (ENU)','Revit');
#10=IFCPILE('p1',$,'Pile:Bored 600:101',$,'Pile:Bored 600',$,$,'101',.BORED.,.CAST_IN_PLACE.);
#11=IFCFOOTING('f1',$,'Pile Cap:2 Pile 2400:102',$,'Pile Cap',$,$,'102',.PILE_CAP.);
#12=IFCFOOTING('f2',$,'Footing-Rectangular:1800x1200x450mm:103',$,$,$,$,'103',.PAD_FOOTING.);
#13=IFCSLAB('s1',$,'Floor:Ground 200:104',$,'Floor:Ground 200',$,$,'104',.BASESLAB.);
#14=IFCSLAB('s2',$,'Floor:Slab 250mm:105',$,'Floor:Slab 250mm',$,$,'105',.FLOOR.);
#15=IFCSLAB('s3',$,'Floor:Roof slab 300:106',$,$,$,$,'106',.ROOF.);
#16=IFCSLAB('s4',$,'Floor:Blinding 75mm:107',$,$,$,$,'107',.BASESLAB.);
#17=IFCBEAM('b1',$,'Concrete-Rectangular Beam:400x700:108',$,$,$,$,'108',.BEAM.);
#18=IFCBEAM('b2',$,'Precast Inverted Tee:600:109',$,$,$,$,'109',.BEAM.);
#19=IFCCOLUMN('c1',$,'Concrete-Rectangular-Column:600x600:110',$,$,$,$,'110',.COLUMN.);
#20=IFCWALL('w1',$,'Basic Wall:Generic 200:111',$,'Basic Wall:Generic 200',$,$,'111',.STANDARD.);
#21=IFCWALL('w2',$,'Basic Wall:Wall 400:112',$,'Retaining',$,$,'112',.STANDARD.);
#22=IFCWALLSTANDARDCASE('w3',$,'Basic Wall:W-300:113',$,$,$,$,'113',.STANDARD.);
#23=IFCWALLTYPE('t1',$,'Basement Wall 300',$,$,$,$,'t1',$,.STANDARD.);
#24=IFCRELDEFINESBYTYPE('r1',$,$,$,(#22),#23);
#25=IFCWALL('w4',$,'Curtain Wall:Storefront:114',$,$,$,$,'114',.STANDARD.);
ENDSEC;
END-ISO-10303-21;
"""

SCHEDULE = (
    "Category,Family and Type,Count\n"
    "Structural Foundations,Pile Cap-3 Pile: 1800x1800,4\n"
    "Structural Foundations,Footing-Rectangular: 1800x1200x450mm,6\n"
    "Structural Framing,Concrete-Rectangular Beam: 300x600mm,20\n"
    "Structural Framing,HSS-Hollow Structural Section Brace: 100x100,4\n"
    "Structural Columns,Concrete-Rectangular-Column: 400x400,8\n"
    "Walls,Basic Wall: Retaining - 300mm Concrete,3\n"
    "Walls,Basic Wall: Basement - 250mm,2\n"
    "Walls,Basic Wall: Generic - 200mm,5\n"
    "Walls,Curtain Wall: Storefront,2\n"
    "Floors,Floor: SOG 150mm,1\n"
    "Floors,Floor: Slab 200mm,3\n"
    "Floors,Floor: Precast Hollowcore 200,2\n")


def elements_of(result):
    return {e["value"]: e for e in result["elements"] if e["key"] == "elements"}


def test_an_ifc_ticks_the_structural_elements():
    found = elements_of(specs_model.read_model("Elements.ifc", IFC.encode()))
    assert set(found) == {"Piles", "Pile caps", "Foundations", "Slab on grade",
                          "Suspended slabs and floors", "Blinding", "Beams", "Precast", "Columns",
                          "Walls", "Retaining walls", "Basement walls"}
    # The IfcPile, and the piles a Revit pile cap family says it carries.
    assert found["Piles"]["why"] == "1 IfcFooting named 'Pile Cap:2 Pile 2400'; 1 IfcPile"
    assert found["Pile caps"]["count"] == 1 and "pile cap" in found["Pile caps"]["why"].lower()
    assert found["Foundations"]["count"] == 1
    assert found["Slab on grade"]["count"] == 1              # not the blinding
    assert found["Suspended slabs and floors"]["count"] == 2  # floor and roof
    assert found["Beams"]["count"] == 2 and found["Columns"]["count"] == 1
    assert "Precast Inverted Tee" in found["Precast"]["why"]
    assert found["Walls"]["count"] == 1                      # not the curtain wall
    assert "Retaining" in found["Retaining walls"]["why"]    # from its ObjectType
    assert "Basement Wall 300" in found["Basement walls"]["why"]  # from its type
    for e in found.values():
        assert e["value"] in specs_model.CHOICES["elements"]


def test_a_schedule_ticks_the_structural_elements():
    found = elements_of(specs_model.read_model("Takeoff.csv", SCHEDULE.encode()))
    assert set(found) == {"Pile caps", "Piles", "Foundations", "Beams", "Columns",
                          "Retaining walls", "Basement walls", "Walls", "Slab on grade",
                          "Suspended slabs and floors", "Precast"}
    assert found["Beams"]["count"] == 20                     # not the braces
    assert found["Walls"]["count"] == 5                      # not the curtain wall
    assert found["Suspended slabs and floors"]["count"] == 5
    assert found["Foundations"]["count"] == 6
    assert "'Structural Columns' elements" in found["Columns"]["why"]


def test_a_quay_model_ticks_its_deck():
    marine = SCHEDULE + ("Floors,Floor: Jetty Deck 450,2\n"
                         "Walls,Basic Wall: Quay Wall 1200,1\n"
                         "Generic Models,Cone Fender SCN1200,6\n")
    found = elements_of(specs_model.read_model("Jetty.csv", marine.encode()))
    assert found["Deck"]["count"] == 2 and found["Quay walls"]["count"] == 1


def test_a_model_upload_ticks_the_tiles_and_keeps_the_projects_own(app, signed_in):
    set_id = new_set(signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "opt_elements": ["Topping"],
                                                   "element_new": "Transfer slab"})
    signed_in.post(f"/specs/sets/{set_id}/model", data={
        "model": [(io.BytesIO(IFC.encode()), "Elements.ifc")]}, content_type="multipart/form-data")
    have = chosen_of(app, set_id)["elements"].split("|")
    assert have[:2] == ["Topping", "Transfer slab"]
    assert {"Piles", "Pile caps", "Beams", "Retaining walls", "Precast"} <= set(have)
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert "Structural elements: Piles" in page
    assert "In the model" in tile(page, "Piles") and "checked" in tile(page, "Piles")
    assert "In the model" not in tile(page, "Topping")
