"""Reading a model: the answers an IFC export or a Revit schedule gives, and the
check of every concrete grade in it."""

from __future__ import annotations

import io
import zipfile

import pytest

from app import specs, specs_doc, specs_model

IFC4 = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [ReferenceView_V1.2]'),'2;1');
FILE_NAME('Harbour.ifc','2024-05-01T10:00:00',(''),(''),'ODA SDAI 24.1',
'Autodesk Revit 24.2.0.63 (ENU) - IFC 24.2.0.49','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCORGANIZATION($,'Autodesk Revit 2024 (ENU)',$,$,$);
#2=IFCAPPLICATION(#1,'2024','Autodesk Revit 2024 (ENU)','Revit');
#5=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#6=IFCSIUNIT(*,.PRESSUREUNIT.,$,.PASCAL.);
#7=IFCUNITASSIGNMENT((#5,#6));
#10=IFCPROJECT('0YvctVUKr0kugbFTf53O9L',$,'Harbour Offices',$,$,$,$,$,#7);
#11=IFCBUILDING('1YvctVUKr0kugbFTf53O9L',$,'Building',$,$,$,$,$,.ELEMENT.,$,$,$);
#20=IFCSLAB('2O2Fr$t4X7Zf8NOew3FLOH',$,'Floor:Architect''s Slab 250mm:1001',$,
  'Floor:Slab 250mm',$,$,'1001',.FLOOR.);
#21=IFCSLAB('2O2Fr$t4X7Zf8NOew3FLOI',$,'Floor:Slab 250mm:1002',$,'Floor:Slab 250mm',$,$,'1002',.FLOOR.);
#22=IFCCOLUMN('2O2Fr$t4X7Zf8NOew3FLOJ',$,'Concrete-Rectangular-Column:600 x 600mm:2001',$,
  'Concrete-Rectangular-Column:600 x 600mm',$,$,'2001',.COLUMN.);
#23=IFCCOLUMN('2O2Fr$t4X7Zf8NOew3FLOK',$,'Concrete-Rectangular-Column:600 x 600mm:2002',$,
  'Concrete-Rectangular-Column:600 x 600mm',$,$,'2002',.COLUMN.);
#24=IFCBEAM('2O2Fr$t4X7Zf8NOew3FLOL',$,'UB-Universal Beam:533x210x92UB:3001',$,
  'UB-Universal Beam:533x210x92UB',$,$,'3001',.BEAM.);
#30=IFCMATERIAL('Concrete C32/40',$,'Concrete');
#31=IFCMATERIAL('Steel S355',$,'Steel');
#32=IFCRELASSOCIATESMATERIAL('3O2Fr$t4X7Zf8NOew3FLOA',$,$,$,(#20,#21,#22,#23),#30);
#33=IFCRELASSOCIATESMATERIAL('3O2Fr$t4X7Zf8NOew3FLOB',$,'Link; (a semicolon inside)',$,(#24),#31);
#40=IFCSLABTYPE('4O2Fr$t4X7Zf8NOew3FLOA',$,'Precast Hollowcore Plank 200',$,$,$,$,$,$,.FLOOR.);
#41=IFCMATERIAL('Precast Concrete C40/50',$,'Concrete');
#42=IFCRELASSOCIATESMATERIAL('4O2Fr$t4X7Zf8NOew3FLOB',$,$,$,(#40),#41);
#43=IFCSLAB('4O2Fr$t4X7Zf8NOew3FLOC',$,'Plank:4001',$,$,$,$,'4001',.FLOOR.);
#44=IFCRELDEFINESBYTYPE('4O2Fr$t4X7Zf8NOew3FLOD',$,$,$,(#43),#40);
#50=IFCTENDON('5O2Fr$t4X7Zf8NOew3FLOA',$,'Tendon:T1:5001',$,$,$,$,'5001',$,.STRAND.,12.7,98.7,$,$,$,$,$);
#60=IFCBUILDINGELEMENTPROXY('6O2Fr$t4X7Zf8NOew3FLOA',$,'Cone Fender SCN1200:6001',$,
  'Cone Fender SCN1200',$,$,'6001',.ELEMENT.);
#70=IFCWALL('7O2Fr$t4X7Zf8NOew3FLOA',$,'Basic Wall:Basement Wall 300:7001',$,$,$,$,'7001',.STANDARD.);
#71=IFCMATERIAL('Waterproofing - SBS',$,$);
#72=IFCMATERIALLAYER(#71,5.,.U.,'Waterproofing - SBS',$,$,$);
#73=IFCMATERIALLAYER(#30,300.,.U.,'Structure',$,$,$);
#74=IFCMATERIALLAYERSET((#72,#73),'Basic Wall:Basement Wall 300',$);
#75=IFCMATERIALLAYERSETUSAGE(#74,.AXIS2.,.POSITIVE.,-150.,$);
#76=IFCRELASSOCIATESMATERIAL('7O2Fr$t4X7Zf8NOew3FLOB',$,$,$,(#70),#75);
#80=IFCPROPERTYSINGLEVALUE('CompressiveStrength',$,IFCPRESSUREMEASURE(32000000.),$);
#81=IFCMATERIALPROPERTIES('Pset_MaterialConcrete',$,(#80),#30);
#90=IFCPROPERTYSINGLEVALUE('LoadBearing',$,IFCBOOLEAN(.T.),$);
#91=IFCPROPERTYSET('9O2Fr$t4X7Zf8NOew3FLOA',$,'Pset_ColumnCommon',$,(#90));
ENDSEC;
END-ISO-10303-21;
"""

IFC2X3 = """ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView_V2.0]'),'2;1');
FILE_NAME('Offices.ifc','2019-05-23T15:15:00',(''),(''),'The EXPRESS Data Manager Version 5.02',
'20190523_1515(x64) - Exporter 20.0.0.377','');
FILE_SCHEMA(('IFC2X3'));
ENDSEC;
DATA;
#1=IFCAPPLICATION($,'2020','Autodesk Revit 2020 (ENU)','Revit');
#10=IFCBUILDING('1YvctVUKr0kugbFTf53O9L',$,'Offices',$,$,$,$,$,.ELEMENT.,$,$,$);
#20=IFCSLAB('2O2Fr$t4X7Zf8NOew3FLOH',$,'Floor:Generic 8in:1',$,'Floor:Generic 8in',$,$,'1',.FLOOR.);
#21=IFCSLAB('2O2Fr$t4X7Zf8NOew3FLOI',$,'Floor:Generic 8in:2',$,'Floor:Generic 8in',$,$,'2',.FLOOR.);
#22=IFCFOOTING('2O2Fr$t4X7Zf8NOew3FLOJ',$,'Footing-Rectangular:72x48x18:3',$,$,$,$,'3',.PAD_FOOTING.);
#23=IFCWALLSTANDARDCASE('2O2Fr$t4X7Zf8NOew3FLOK',$,'Basic Wall:Foundation 12in:4',$,$,$,$,'4');
#24=IFCREINFORCINGBAR('2O2Fr$t4X7Zf8NOew3FLOL',$,'Rebar Bar:#5 Epoxy:5',$,$,$,$,'5','Grade 60',
  15.9,199.,1200.,.MAIN.,.TEXTURED.);
#30=IFCMATERIAL('Concrete - 4000 psi');
#31=IFCMATERIAL('Concrete 400 psi');
#32=IFCMATERIAL('Concrete, Cast-in-Place gray');
#33=IFCMATERIAL('Rebar - Grade 60');
#34=IFCRELASSOCIATESMATERIAL('3O2Fr$t4X7Zf8NOew3FLOA',$,$,$,(#20,#21),#30);
#35=IFCRELASSOCIATESMATERIAL('3O2Fr$t4X7Zf8NOew3FLOB',$,$,$,(#22),#31);
#36=IFCMATERIALLIST((#32));
#37=IFCRELASSOCIATESMATERIAL('3O2Fr$t4X7Zf8NOew3FLOC',$,$,$,(#23),#36);
#38=IFCRELASSOCIATESMATERIAL('3O2Fr$t4X7Zf8NOew3FLOD',$,$,$,(#24),#33);
#40=IFCMECHANICALCONCRETEMATERIALPROPERTIES(#32,$,$,$,$,$,27579029.0,$,$,$,$,$);
ENDSEC;
END-ISO-10303-21;
"""

FRAMING = (
    '"Structural Framing Schedule"\n'
    '"Family and Type"\t"Structural Material"\t"Count"\t"Comments"\n'
    '\n'
    '"Concrete-Rectangular Beam: 300 x 600mm"\t"Concrete, C30/37"\t"12"\t""\n'
    '"PT Band Beam: 1200 x 400"\t"Concrete, C40/50"\t"4"\t"bonded, grouted ducts"\n'
    '"W-Wide Flange: W12X26"\t"Metal - Steel - ASTM A992"\t"20"\t""\n'
    '"K-Series Bar Joist-Rod Web: 18K4"\t"Metal - Steel"\t"8"\t""\n'
    '"Grand total: 44"\n')

WALLS = (
    "Wall Material Takeoff\n"
    "Family and Type,Material: Name,Phase Created,Phase Demolished,Count\n"
    "Basic Wall: Existing 200,Concrete Masonry Units,Existing,New Construction,1\n"
    "Basic Wall: Retaining 400,Concrete C35/45,New Construction,None,1\n"
    "Basic Wall: Basement 400,Bentonite Waterproofing,New Construction,None,1\n")


def answers(result):
    return {(e["key"], e["value"]) for e in result["elements"]}


def answer(result, key, value):
    return next(e for e in result["elements"] if e["key"] == key and e["value"] == value)


def row(rows, material):
    return next(r for r in rows if r["material"] == material)


# --- IFC ---------------------------------------------------------------------------

def test_ifc4_answers_materials_and_grades():
    result = specs_model.read_model("Harbour.ifc", IFC4.encode())
    assert result["source"] == "IFC"
    assert result["detail"] == "IFC4 export from Autodesk Revit 2024 (ENU)"
    found = answers(result)
    assert ("structures", "Marine structures") in found
    assert ("structures", "Buildings") not in found
    assert ("cast_in_place", "Yes") in found
    assert ("precast", "Precast prestressed") in found
    assert ("post_tensioning", "Unbonded") in found
    assert ("steel_framing", "Yes") in found
    assert ("fenders", "Cone") in found
    assert ("waterproofing", "SBS modified sheet") in found
    assert answer(result, "post_tensioning", "Unbonded")["why"] == "1 IfcTendon"
    assert "Cone Fender SCN1200" in answer(result, "fenders", "Cone")["why"]
    assert "Precast Hollowcore Plank 200" in answer(result, "precast", "Precast prestressed")["why"]
    # Every answer is one the library asks.
    for e in result["elements"]:
        assert e["value"] in specs_model.CHOICES[e["key"]]
        assert e["count"] >= 1 and e["why"]

    names = {c["name"]: c["count"] for c in result["categories"]}
    assert names["Slabs (IfcSlab)"] == 3
    assert names["Columns (IfcColumn)"] == 2
    assert names["Tendons (IfcTendon)"] == 1
    assert result["categories"][0]["name"] == "Slabs (IfcSlab)"

    c32 = row(result["concrete"], "Concrete C32/40")
    assert c32["count"] == 5                       # 2 slabs, 2 columns, the wall's core
    assert set(c32["used_in"]) == {"Slabs", "Columns", "Walls"}
    assert c32["grade"] == "C32/40" and c32["mpa"] == 32.0
    assert c32["state"] == "check"                 # low for a marine project
    assert "marine" in c32["note"]
    assert row(result["concrete"], "Precast Concrete C40/50")["state"] == "ok"
    assert result["concrete_class"] == "C40/50"
    steel = row(result["steel"], "Steel S355")
    assert steel["grade"] == "S355" and steel["state"] == "ok" and steel["used_in"] == ["Beams"]
    assert not any(r["material"] == "Waterproofing - SBS" for r in result["concrete"])
    assert any("bonded or unbonded" in n for n in result["notes"])


def test_ifc2x3_psi_grades_and_rebar():
    result = specs_model.read_model("Offices.ifc", IFC2X3.encode())
    assert result["detail"] == "IFC2X3 export from Autodesk Revit 2020 (ENU)"
    found = answers(result)
    assert ("structures", "Buildings") in found
    assert ("cast_in_place", "Yes") in found
    assert ("rebar", "Epoxy-coated") in found
    assert not any(k == "steel_framing" for k, _v in found)

    good = row(result["concrete"], "Concrete - 4000 psi")
    assert good["state"] == "ok" and good["mpa"] == pytest.approx(27.6, abs=0.05)
    bad = row(result["concrete"], "Concrete 400 psi")
    assert bad["state"] == "unrealistic" and "4000 psi was probably meant" in bad["note"]
    # A name with no strength takes the strength Revit wrote in pascals.
    gray = row(result["concrete"], "Concrete, Cast-in-Place gray")
    assert gray["grade"] == "4000 psi" and gray["state"] == "ok"
    assert "properties" in gray["note"]
    assert not any("Rebar" in r["material"] for r in result["concrete"] + result["steel"])
    assert result["concrete_class"] == "4000 psi"
    assert any("do not look realistic" in n or "does not look realistic" in n
               for n in result["notes"])


def test_ifczip_reads_the_ifc_inside():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("Harbour.ifc", IFC4)
    result = specs_model.read_model("Harbour.ifczip", buffer.getvalue())
    assert result["source"] == "IFC"
    assert ("fenders", "Cone") in answers(result)


def test_step_strings_are_decoded():
    assert specs_model.step_text("Dalle b\\X2\\00E9\\X0\\ton") == "Dalle béton"
    assert specs_model.step_text("Architect''s") == "Architect's"
    assert specs_model.step_text("\\X\\E9t\\X\\E9") == "été"
    args = specs_model.step_args("'a;b',#12,(#1,#2),.T.,$,IFCLABEL('C30/37'),3.5")
    assert args[0] == "a;b" and args[1] == 12 and args[2] == [1, 2]
    assert args[5] == ("IFCLABEL", "C30/37") and args[6] == 3.5


def test_bridge_and_bollards():
    fender = "'Cone Fender SCN1200:6001',$,\n  'Cone Fender SCN1200'"
    bollard = IFC4.replace(fender, "'Tee Bollard 1000kN:6001',$,\n  'Tee Bollard 1000kN'")
    result = specs_model.read_model("Quay.ifc", bollard.encode())
    assert ("bollards", "100 t") in answers(result)

    bridge = IFC4.replace("#11=IFCBUILDING(", "#12=IFCBRIDGE('9YvctVUKr0kugbFTf53O9L',$,"
                                              "'Bridge',$,$,$,$,$,$,$);\n#11=IFCBUILDING(")
    bridge = bridge.replace(fender, "'Pot Bearing PB-1:6001',$,\n  'Pot Bearing PB-1'")
    bridge = bridge.replace("FILE_SCHEMA(('IFC4'))", "FILE_SCHEMA(('IFC4X3_ADD2'))")
    result = specs_model.read_model("Bridge.ifc", bridge.encode())
    assert result["detail"].startswith("IFC4X3 export")
    found = answers(result)
    assert ("structures", "Bridges") in found
    assert ("bridge_items", "Bearings") in found
    assert ("structures", "Buildings") not in found


# --- schedules ---------------------------------------------------------------------

def test_utf16_tab_schedule():
    data = FRAMING.encode("utf-16")                 # with its byte-order mark
    result = specs_model.read_model("Framing.txt", data)
    assert result["source"] == "Schedule"
    assert result["detail"] == "Schedule: Structural Framing Schedule, 4 rows"
    assert result["categories"] == [{"name": "Structural Framing", "count": 44}]
    found = answers(result)
    assert ("cast_in_place", "Yes") in found
    assert ("post_tensioning", "Bonded") in found
    assert ("steel_framing", "Yes") in found
    assert ("steel_systems", "Steel joists") in found
    assert answer(result, "steel_systems", "Steel joists")["why"] == \
        "8 elements named 'K-Series Bar Joist-Rod Web: 18K4'"
    assert answer(result, "steel_framing", "Yes")["count"] == 28
    assert row(result["concrete"], "Concrete, C30/37")["state"] == "ok"
    assert row(result["concrete"], "Concrete, C30/37")["used_in"] == ["Structural Framing"]
    assert result["concrete_class"] == "C30/37"
    assert row(result["steel"], "Metal - Steel - ASTM A992")["state"] == "ok"
    assert row(result["steel"], "Metal - Steel")["state"] == "missing"
    assert any("Structural Framing: 2 concrete grades are used" in n for n in result["notes"])


def test_csv_with_phase_demolished_and_bentonite():
    result = specs_model.read_model("Walls.csv", WALLS.encode("cp1252"))
    found = answers(result)
    assert ("demolition", "Yes") in found
    assert answer(result, "demolition", "Yes")["why"] == \
        "1 element demolished in phase 'New Construction'"
    assert ("waterproofing", "Bentonite") in found
    assert ("cast_in_place", "Yes") in found
    assert result["categories"] == [{"name": "Walls", "count": 3}]
    # Masonry is not concrete.
    assert [r["material"] for r in result["concrete"]] == ["Concrete C35/45"]


def test_xlsx_schedule():
    shared = ["Structural Column Schedule", "Family and Type", "Structural Material", "Count",
              "Precast Column: 400x400", "Precast Concrete C50/60"]
    sst = "".join(f"<si><t>{s}</t></si>" for s in shared)
    sheet = ('<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
             '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="B2" t="s"><v>2</v></c>'
             '<c r="C2" t="s"><v>3</v></c></row>'
             '<row r="3"><c r="A3" t="s"><v>4</v></c><c r="B3" t="s"><v>5</v></c>'
             '<c r="C3"><v>6</v></c></row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", f'<workbook {ns}><sheets/></workbook>')
        archive.writestr("xl/sharedStrings.xml", f"<sst {ns}>{sst}</sst>")
        archive.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{sheet}"
                                                     "</sheetData></worksheet>")
    result = specs_model.read_model("Columns.xlsx", buffer.getvalue())
    assert result["detail"] == "Schedule: Structural Column Schedule, 1 rows"
    assert ("precast", "Plant precast") in answers(result)
    assert ("cast_in_place", "Yes") not in answers(result)
    assert row(result["concrete"], "Precast Concrete C50/60")["count"] == 6
    assert result["categories"] == [{"name": "Structural Columns", "count": 6}]


def test_schedule_without_materials_says_so():
    text = "Floor Schedule\nFamily and Type\tCount\nFloor: Composite Deck 150mm\t3\n"
    result = specs_model.read_model("Floors.txt", text.encode("utf-8-sig"))
    assert ("steel_systems", "Steel deck") in answers(result)
    assert any("no material column" in n for n in result["notes"])


# --- what it does not read ---------------------------------------------------------

def test_revit_model_is_refused_in_words():
    fake = specs_doc.SIGNATURE + b"\0" * 1024
    with pytest.raises(specs.SpecError) as err:
        specs_model.read_model("Tower.rvt", fake)
    message = str(err.value)
    assert "Revit model itself" in message and "closed format" in message
    assert "File → Export → IFC" in message and "schedule" in message


def test_revit_version_is_named(monkeypatch):
    info = "Worksharing: Not enabled Format: 2024 Build: 20230308_1635(x64) Autodesk Revit 2024"
    monkeypatch.setattr(specs_doc, "streams",
                        lambda data: {"BasicFileInfo": info.encode("utf-16-le")})
    with pytest.raises(specs.SpecError, match="saved by Revit 2024"):
        specs_model.read_model("Tower.rvt", specs_doc.SIGNATURE + b"\0" * 1024)


@pytest.mark.parametrize("name, data", [
    ("noise.bin", bytes(range(256)) * 8),
    ("drawing.pdf", b"%PDF-1.7\n" + bytes(range(256))),
    ("model.ifcxml", b'<?xml version="1.0"?><ifcXML xmlns="http://www.iai-tech.org/ifcXML"/>'),
    ("empty.ifc", b""),
    ("broken.ifc", b"not an ifc at all"),
])
def test_other_files_are_refused(name, data):
    with pytest.raises(specs.SpecError, match=r"\S"):
        specs_model.read_model(name, data)


def test_refusal_names_what_is_accepted():
    with pytest.raises(specs.SpecError, match=r"IFC export .*\.xlsx"):
        specs_model.read_model("noise.bin", bytes(range(256)) * 8)


# --- the grade check ---------------------------------------------------------------

@pytest.mark.parametrize("text, used_in, exposure, state, mpa", [
    ("C32/40", None, "", "ok", 32.0),
    ("C 32/40", None, "", "ok", 32.0),
    ("C32-40", None, "", "ok", 32.0),
    ("C30/35", None, "", "check", 30.0),
    ("C40", None, "", "check", 32.0),
    ("C40/32", None, "", "unrealistic", 40.0),
    ("C30/60", None, "", "unrealistic", 30.0),
    ("5 MPa", None, "", "unrealistic", 5.0),
    ("12 MPa", ["Structural Columns"], "", "check", 12.0),
    ("12 MPa", ["Blinding"], "", "ok", 12.0),
    ("Blinding 12 N/mm2", None, "", "ok", 12.0),
    ("Blinding 5 MPa", None, "", "unrealistic", 5.0),
    ("150 MPa", None, "", "unrealistic", 150.0),
    ("4000 psi", None, "", "ok", 27.6),
    ("4,000psi", None, "", "ok", 27.6),
    ("4 ksi", None, "", "ok", 27.6),
    ("Concrete 400 psi", None, "", "unrealistic", 2.8),
    ("25 MPa", None, "Marine", "check", 25.0),
    ("C28/35", ["Piles", "Quay deck"], "", "check", 28.0),
    ("90 MPa", None, "", "check", 90.0),
    ("35 N/mm²", None, "", "ok", 35.0),
    ("fc' = 35", None, "", "ok", 35.0),
    ("f'c 5000", None, "", "ok", 34.5),
    ("Concrete 30", None, "", "ok", 30.0),
    ("C25/30", ["Post-tensioned slabs"], "", "check", 25.0),
    ("Concrete, Cast-in-Place gray", None, "", "missing", None),
    ("", None, "", "missing", None),
])
def test_grade_check(text, used_in, exposure, state, mpa):
    result = specs_model.grade_check(text, used_in, exposure)
    assert result["state"] == state, result
    if mpa is None:
        assert result["mpa"] is None
    else:
        assert result["mpa"] == pytest.approx(mpa, abs=0.05)
    assert result["note"].endswith(".")


def test_grade_check_notes_say_what_to_do():
    assert "nearest is C30/37" in specs_model.grade_check("C30/35")["note"]
    assert "write it as C32/40" in specs_model.grade_check("C40")["note"]
    assert "C32/40 was probably meant" in specs_model.grade_check("C40/32")["note"]
    assert specs_model.grade_check("C32/40")["cube"] == 40.0
    assert "high-strength" in specs_model.grade_check("90 MPa")["note"]
    assert "C20/25" in specs_model.grade_check("12 MPa", ["Structural Columns"])["note"]
    assert specs_model.grade_check("C32/40")["note"] == "C32/40: cylinder 32 MPa, cube 40 MPa."
    assert specs_model.grade_check("4000 psi")["note"] == "4000 psi = 27.6 MPa."


def test_steel_grades():
    assert specs_model.steel_check("Steel S355")["state"] == "ok"
    assert specs_model.steel_check("Metal - Steel - ASTM A992")["state"] == "ok"
    assert specs_model.steel_check("A572 Grade 50")["state"] == "ok"
    assert specs_model.steel_check("A500 Gr C")["state"] == "ok"
    assert specs_model.steel_check("Metal - Steel 43-275")["state"] == "check"
    assert specs_model.steel_check("Steel Q345")["state"] == "check"
    assert specs_model.steel_check("Metal - Steel")["state"] == "missing"


def test_material_kinds():
    kind = specs_model.material_kind
    assert kind("Concrete C32/40") == "concrete"
    assert kind("Grout, non-shrink") == "concrete"
    assert kind("Steel S355") == "steel"
    assert kind("Metal - Steel") == "steel"
    assert kind("Rebar B500B") == ""
    assert kind("Concrete Masonry Units") == ""
    assert kind("Metal - Aluminum") == ""


def test_studs_and_roofing_are_left_out():
    assert specs_model.material_kind("Metal - Stud Layer") == ""
    assert "S355 or ASTM A992" in specs_model.steel_check("Metal - Steel - 345 MPa")["note"]
    text = ("Floor Material Takeoff\nFamily and Type\tMaterial: Name\tCategory\n"
            "Basic Roof: EPDM 200\tRoofing - EPDM Membrane\tRoofs\n"
            "Floor: Podium 300\tWaterproofing - EPDM\tFloors\n")
    result = specs_model.read_model("Roof.txt", text.encode())
    wp = answer(result, "waterproofing", "Elastomeric sheet")
    assert wp["count"] == 1 and "Waterproofing - EPDM" in wp["why"]


MIXED = (
    "Multi-Category Schedule\n"
    "Category\tFamily\tType\tStructural Material\tThickness\tCount\n"
    "Structural Foundations\tFoundation Slab\tRaft 1500mm\tConcrete C35/45\t1500 mm\t1\n"
    "Floors\tFloor\tPT Slab 250 - monostrand\tConcrete C40/50\t250 mm\t3\n"
    "Walls\tBasic Wall\tShotcrete Lining 150\tShotcrete C30/37\t150 mm\t2\n"
    "Walls\tBasic Wall\tTilt-Up Panel 200\tConcrete C32/40\t200 mm\t6\n"
    "Structural Connections\tHilti HIT-RE 500 Anchor\tM16\t\t\t40\n"
    "Structural Rebar\tRebar Coupler\tType A 32\t\t\t12\n"
    "Structural Rebar\tRebar Bar\tGFRP 16\t\t\t50\n"
    "Structural Framing\tAESS Round HSS\tHSS 6x6\tSteel S355\t\t4\n"
    "Structural Framing\tCrane Runway Beam\tUB 610\tSteel S355\t\t2\n"
    "Structural Framing\tSpace Frame Chord\tCHS 88.9\tSteel S355\t\t30\n"
    "Floors\tFloor\tComposite Deck 150\tConcrete C30/37\t150 mm\t2\n"
    "Structural Framing\tC Channel - Cold Formed\tC150\tSteel S355\t\t9\n"
    "Stairs\tSteel Stair\tGrating Treads\tSteel S275\t\t1\n"
    "Generic Models\tSheet Pile\tAZ 26\tSteel S355\t\t14\n"
    "Generic Models\tSettlement Point\tSP\t\t\t8\n")


def test_word_rules_across_a_multi_category_schedule():
    result = specs_model.read_model("Mixed.txt", MIXED.encode())
    found = answers(result)
    for expected in [("mass_concrete", "Yes"), ("post_tensioning", "Unbonded"),
                     ("shotcrete", "Yes"), ("tilt_up", "Yes"), ("anchors", "Yes"),
                     ("couplers", "Yes"), ("rebar", "GFRP bars"), ("aess", "Yes"),
                     ("cranes", "Yes"), ("steel_systems", "Space frames"),
                     ("steel_systems", "Steel deck"), ("steel_systems", "Cold-formed framing"),
                     ("stairs", "Grating"), ("shoring", "Yes"), ("monitoring", "Yes"),
                     ("steel_framing", "Yes"), ("cast_in_place", "Yes"),
                     ("structures", "Buildings")]:
        assert expected in found, expected
    assert "1.5 m thick" in answer(result, "mass_concrete", "Yes")["why"]
    assert ("post_tensioning", "Bonded") not in found
    assert ("rebar", "Uncoated") in found            # the couplers' bars say nothing
    # Shotcrete and tilt-up are not counted as cast in place.
    assert answer(result, "cast_in_place", "Yes")["count"] == 1 + 3 + 2
    assert result["categories"][0] == {"name": "Structural Rebar", "count": 62}


def test_steel_stair_with_concrete_fill_is_a_metal_pan():
    text = ("Stair Material Takeoff\nFamily and Type\tMaterial: Name\n"
            "Assembled Stair: Steel Pan\tMetal - Steel - ASTM A36\n"
            "Assembled Stair: Steel Pan\tConcrete - 3000 psi\n"
            "Cast-In-Place Stair: Monolithic\tConcrete, Cast-in-Place gray\n")
    result = specs_model.read_model("Stairs.txt", text.encode())
    assert ("stairs", "Metal pan") in answers(result)
    assert answer(result, "cast_in_place", "Yes")["count"] == 1
