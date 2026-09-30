"""Reading a specification whole: references that keep themselves right, one
basis of standards, and the checker that reads across every section."""

from __future__ import annotations

import io
import json
import zipfile

from app import specs, specs_check
from app.specs_seed import EQUIVALENTS, WITHDRAWN
from .test_specs import docx_of, part, text, upload

TABLE = specs_check.Standards(
    [{"topic": t, "bs": b, "us": u} for t, b, u in EQUIVALENTS],
    [{"old": o, "new": n, "note": w} for o, n, w in WITHDRAWN])

CONCRETE = """\
# GENERAL
## SUMMARY
- Reinforcement is specified in {ref:032000}.
- Cure as {ref:CURING} requires; tolerances to {ref:#tol}.
# PRODUCTS
## MATERIALS
- {if exposure=Marine} Marine mixes: minimum cover 75 mm.
- Cement: ASTM C150/C150M-20, Type I.
- Concrete class C40/50; cover 50 mm to buried faces.
- Water: BS 3148.
# EXECUTION
## PLACING
- Comply with ACI 301, "Specification for Concrete Construction".
- Concrete class C40/50 throughout; cover 50 mm.
- Concrete class C40/50 for slabs, with cover 50 mm.
## CURING
- Keep surfaces wet for seven days.
"""

REBAR = """\
# PRODUCTS
## REINFORCEMENT
- Bars: BS 4449 grade B500B, cover 50 mm.
- Concrete strength is specified in Section 033000 "Concrete Works".
- Tie wire to Section 016000.
"""


def whole(chosen=None):
    concrete = specs.align([], specs.from_text(CONCRETE))
    # One paragraph gets a fixed id, so a reference can point at it.
    target = next(n for n in concrete if n["text"].startswith("Comply with ACI 301"))
    target["id"] = "tol"
    return [{"id": 1, "number": "033000", "title": "CAST-IN-PLACE CONCRETE", "nodes": concrete},
            {"id": 2, "number": "032000", "title": "CONCRETE REINFORCING",
             "nodes": specs.align([], specs.from_text(REBAR))}]


# --- references ---------------------------------------------------------------------

def test_references_are_written_out_from_the_numbers_as_they_stand():
    sections = whole()
    reader = specs_check.Reader(sections, {"exposure": "General"})
    issued = reader.issued("033000")
    assert issued("Reinforcement is specified in {ref:032000}.") == \
        'Reinforcement is specified in Section 032000 "Concrete Reinforcing".'
    assert issued("Cure as {ref:CURING} requires; tolerances to {ref:#tol}.") == \
        "Cure as Article 3.2 requires; tolerances to Paragraph 3.1.A."
    # From another section, the section is named too.
    assert specs_check.Reader(sections, {}).issued("032000")("See {ref:033000/CURING}.") == \
        'See Article 3.2 of Section 033000 "Cast-in-Place Concrete".'

    # A paragraph put in ahead of it moves the reference with it.
    concrete = sections[0]["nodes"]
    at = next(i for i, n in enumerate(concrete) if n["id"] == "tol")
    concrete.insert(at, specs.node("PR1", "A new first paragraph."))
    assert "Paragraph 3.1.B" in specs_check.Reader(sections, {}).issued("033000")("{ref:#tol}")


def test_a_reference_to_something_gone_is_caught_not_issued():
    sections = whole()
    sections[0]["nodes"] = [n for n in sections[0]["nodes"] if n["id"] != "tol"]
    reader = specs_check.Reader(sections[:1], {})
    shown, problem = reader.ref("#tol", "033000")
    assert shown == "[reference not found]" and problem
    shown, problem = reader.ref("032000", "033000")
    assert problem == "Section 032000 is not in this specification"
    report = specs_check.check(sections[:1], {}, {}, [], TABLE)
    assert len(report["references"]) == 2


def test_typed_references_are_made_live_and_their_titles_dropped():
    sections = whole()
    where = specs_check.index(sections, {})
    linked, count = specs_check.link_typed(
        'Strength is in Section 33000 - CAST-IN-PLACE CONCRETE, and see article 3.2.',
        "032000", where)
    assert (linked, count) == ("Strength is in {ref:33000}, and see article 3.2.", 1)
    linked, count = specs_check.link_typed("Cure as section 3.2 says.", "033000", where)
    assert linked == "Cure as {ref:CURING} says." and count == 1
    # One that is not here is left as typed.
    assert specs_check.link_typed("See Section 016000.", "033000", where) == ("See Section 016000.", 0)


# --- standards ------------------------------------------------------------------------

def test_every_standard_goes_on_the_projects_basis():
    to_bs = specs_check.convert
    assert to_bs("Cement: ASTM C150/C150M-20, Type I.", "bs", TABLE) == "Cement: BS EN 197-1, Type I."
    # The quoted title named the old standard, so it goes with it.
    assert to_bs('Comply with ACI 301, "Specification for Concrete Construction".', "bs", TABLE) == \
        "Comply with BS EN 13670."
    # Said once when a conversion makes it twice.
    assert to_bs("Bars to ASTM A615 or BS 4449.", "bs", TABLE) == "Bars to BS 4449."
    assert to_bs("Bars to BS 4449 grade B500B.", "us", TABLE) == "Bars to ASTM A615 grade B500B."
    assert to_bs("Bars to BS 4449.", "both", TABLE) == "Bars to BS 4449 or ASTM A615."
    assert to_bs("Bars to BS 4449 or ASTM A615.", "both", TABLE) == "Bars to BS 4449 or ASTM A615."
    assert to_bs("Water to BS 3148.", "", TABLE) == "Water to BS 3148."


def test_the_basis_is_read_from_the_choice():
    assert specs_check.basis_of("BS EN") == "bs"
    assert specs_check.basis_of("ACI/ASTM") == "us"
    assert specs_check.basis_of("ASTM") == "us"
    assert specs_check.basis_of("Both") == "both"


def test_the_same_standard_however_it_is_typed():
    key = specs_check.std_key
    assert key("ASTM C 150/C150M-20") == key("ASTM C150") == key("ASTM C150M")
    assert key("BS EN ISO 1461:2009") == key("EN ISO 1461")
    assert key("ACI 318-19") == key("ACI 318") != key("ACI 318.2")


def test_outdated_standards_are_found_and_replaced():
    assert TABLE.outdated("BS 8110-1:1997", 1997)["new"] == "BS EN 1992-1-1"
    assert TABLE.outdated("BS EN 10210-1:1994", 1994)["new"] == "BS EN 10210-1"
    assert TABLE.outdated("BS EN 10210-1:2006", 2006) is None
    assert TABLE.outdated("BS 4449", None) is None
    assert specs_check.replace_standard("Design to BS 8110-1:1997 and BS 8110.", "BS 8110",
                                        "BS EN 1992-1-1") == \
        ("Design to BS EN 1992-1-1 and BS EN 1992-1-1.", 2)


# --- the checker ----------------------------------------------------------------------

def test_the_checker_reads_across_every_section():
    report = specs_check.check(whole(), {"exposure": "Marine", "standards": "BS EN"}, {},
                               [{"key": "exposure", "choice_list": ["General", "Marine"]},
                                {"key": "standards", "choice_list": ["BS EN", "ACI/ASTM"]}], TABLE)
    messages = {k: [i.get("message", "") for i in v] for k, v in report.items() if isinstance(v, list)}

    assert any("BS 3148 is out of date; use BS EN 1008" in m for m in messages["outdated"])
    assert any("Section 016000" in m for m in messages["references"])
    # The same property given two values, and the section cited by the wrong title.
    assert any(m.startswith("Concrete cover is given as 50 mm (4×), 75 mm (1×)")
               for m in messages["discrepancies"])
    assert any('as "Concrete Works"; it is "Cast-in-Place Concrete"' in m
               for m in messages["discrepancies"])
    # Written out often enough to be one variable.
    repeated = {i["value"]: i for i in report["repeated"] if "value" in i}
    assert repeated["C40/50"]["fix"]["suggest"] == "concrete_class"
    assert repeated["50 mm"]["fix"] == {"action": "variable", "value": "50 mm", "suggest": "cover",
                                        "property": "Concrete cover"}
    assert report["setup"] == []


def test_a_value_made_a_variable_only_where_it_is_that_property():
    text_in = "Cover 50 mm to faces; laps 50 mm; cover of 50 mm to ties."
    assert specs_check.make_variable(text_in, "50 mm", "cover", "Concrete cover") == \
        ("Cover {{cover}} to faces; laps 50 mm; cover of {{cover}} to ties.", 2)
    assert specs_check.make_variable("C40/50 and C40/50", "C40/50", "concrete_class") == \
        ("{{concrete_class}} and {{concrete_class}}", 2)


def test_a_condition_on_a_question_that_does_not_exist_is_reported():
    sections = [{"id": 1, "number": "033000", "title": "X", "nodes": specs.align([], specs.from_text(
        "# GENERAL\n## A\n- {if colour=red} Red.\n- {if exposure=Arctic} Cold."))}]
    report = specs_check.check(sections, {"exposure": "Marine"}, {},
                               [{"key": "exposure", "choice_list": ["General", "Marine"]}], TABLE)
    assert len(report["setup"]) == 2


def test_a_question_with_several_answers():
    assert specs.applies("rebar=Galvanized", {"rebar": "Uncoated|Galvanized"})
    assert not specs.applies("rebar=Epoxy-coated", {"rebar": "Uncoated|Galvanized"})
    assert specs.applies("rebar!=Epoxy-coated", {"rebar": "Uncoated|Galvanized"})
    assert not specs.applies("rebar=Galvanized", {"rebar": ""})


# --- the pages ---------------------------------------------------------------------

def load(signed_in, number, body, title):
    nodes = specs.align([], specs.from_text(body))
    return upload(signed_in, "/specs/library/upload",
                  [(f"SPC-{number}.docx", docx_of(nodes, number=number, title=title, chosen={}))])


def test_check_basis_and_references_through_the_pages(app, signed_in):
    load(signed_in, "033000", CONCRETE.replace("{ref:#tol}", "{ref:PLACING}"), "CAST-IN-PLACE CONCRETE")
    load(signed_in, "032000", REBAR, "CONCRETE REINFORCING")
    answer = signed_in.post("/specs/sets", data={"name": "Harbour Works"})
    set_id = int(answer.headers["Location"].rstrip("/").rsplit("/", 1)[1])
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["1", "2"]})
    signed_in.post(f"/specs/sets/{set_id}", data={
        "name": "Harbour Works", "opt_standards": "BS EN", "opt_rebar": ["Uncoated", "Galvanized"]})

    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert "Check (" in page and 'value="Galvanized" checked' in page

    shown = text(signed_in.get(f"/specs/sets/{set_id}/sections/1"))
    assert "Article 3.1" in shown and "BS EN 197-1" in shown and "ASTM C150" not in shown
    docx = part(signed_in.get(f"/specs/sets/{set_id}/sections/1/docx").data, "word/document.xml")
    assert "Section 032000 &quot;Concrete Reinforcing&quot;" in docx or \
        'Section 032000 "Concrete Reinforcing"' in docx
    assert "BS EN 13670" in docx and "ACI 301" not in docx

    report = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "BS 3148 is out of date" in report
    signed_in.post(f"/specs/sets/{set_id}/fix", data={"action": "replace", "old": "BS 3148",
                                                      "new": "BS EN 1008"})
    assert "BS 3148 is out of date" not in text(signed_in.get(f"/specs/sets/{set_id}/check"))
    signed_in.post(f"/specs/sets/{set_id}/fix", data={"action": "variable", "value": "C40/50",
                                                      "name": "concrete_class"})
    assert "{{concrete_class}}" in text(signed_in.get(f"/specs/sets/{set_id}/sections/1/edit"))
    # The master is untouched by a project's fixes.
    assert "BS 3148" in text(signed_in.get("/specs/library/1"))
    assert signed_in.get("/specs/library/check").status_code == 200


def test_the_library_travels_as_one_file(app, signed_in):
    load(signed_in, "033000", CONCRETE, "CAST-IN-PLACE CONCRETE")
    signed_in.post("/specs/standards", data={"eq_topic": ["Cement"], "eq_bs": ["BS EN 197-1"],
                                             "eq_us": ["ASTM C150"], "wd_old": ["BS 12"],
                                             "wd_new": ["BS EN 197-1"], "wd_note": [""]})
    packed = signed_in.get("/specs/library/file").data
    data = json.loads(zipfile.ZipFile(io.BytesIO(packed)).read("library.json"))
    assert [s["number"] for s in data["sections"]] == ["033000"]
    assert data["standards"] == [{"topic": "Cement", "bs": "BS EN 197-1", "us": "ASTM C150"}]

    signed_in.post("/specs/library/1/delete")
    assert 'href="/specs/library/1"' not in text(signed_in.get("/specs/library"))
    answer = signed_in.post("/specs/library/file", data={"library": (io.BytesIO(packed), "lib.zip")},
                            content_type="multipart/form-data")
    assert answer.status_code == 302
    assert "CAST-IN-PLACE CONCRETE" in text(signed_in.get("/specs/library"))
    bad = signed_in.post("/specs/library/file", data={"library": (io.BytesIO(b"nope"), "x.zip")},
                         content_type="multipart/form-data", follow_redirects=True)
    assert "not a Specs Writer library file" in text(bad)


def test_the_suggested_questions_are_added_without_changing_what_is_there(signed_in):
    signed_in.post("/specs/options", data={
        "opt_key": ["standards"], "opt_label": ["Standards"], "opt_choices": ["BS EN|ASTM"],
        "opt_default": ["BS EN"], "opt_grp": [""], "opt_kind": ["one"]})
    signed_in.post("/specs/options/suggested")
    page = text(signed_in.get("/specs/options"))
    assert 'value="Standards"' in page and "BS EN|ASTM|ACI/ASTM|Both" not in page
    assert "BS EN|ACI/ASTM|Both" in page or "BS EN|ASTM|Both" in page
    assert 'value="rebar"' in page and 'value="Reinforcement"' in page


# --- old Word files -------------------------------------------------------------------

FIXTURES = __import__("pathlib").Path(__file__).parent / "fixtures"


def test_an_old_doc_reads_the_same_as_the_docx_it_was_saved_from():
    from app import specs_doc

    data = (FIXTURES / "section-032000.doc").read_bytes()
    assert specs_doc.is_doc(data)
    read = specs.read_docx(data)
    assert (read["number"], read["title"]) == ("032000", "CONCRETE REINFORCING")
    levels = [(n["level"], n["text"]) for n in read["nodes"]]
    assert ("PRT", "GENERAL") in levels and ("ART", "RELATED DOCUMENTS") in levels
    assert ("PR2", "Steel reinforcement bars.") in levels
    assert ("TBL", "| Test | Standard |\n| Slump | BS EN 12350-2 |") in levels


def test_a_doc_is_loaded_through_the_page(signed_in):
    data = (FIXTURES / "section-032000.doc").read_bytes()
    upload(signed_in, "/specs/library/upload", [("SPC-032000.doc", data)])
    assert "CONCRETE REINFORCING" in text(signed_in.get("/specs/library"))
    bad = upload(signed_in, "/specs/library/upload", [("broken.doc", data[:600])])
    assert bad.status_code == 302


# --- language -------------------------------------------------------------------------

LANGUAGE = """\
# GENERAL
## SUMMARY
- The colour of the the concrete shall conforms to a approved sample; an HDPE sleeve , a unit.
- Provide 2 meters of aluminum at the center line; use a cover meter. See "Color Guide".
- Reinforcment within the entire building, and building products.
- Submit data etc.
"""


def language(english, chosen=None, wording=()):
    from app import specs_language

    sections = [{"id": 7, "number": "033000", "title": "X",
                 "nodes": specs.align([], specs.from_text(LANGUAGE))}]
    return [(f["kind"], f["old"], f["new"]) for f in
            specs_language.findings(sections, chosen or {}, english, wording)]


def test_one_english_throughout():
    uk = language("UK")
    assert ("english", "aluminum", "aluminium") in uk and ("english", "center", "centre") in uk
    assert ("english", "meters", "metres") in uk
    # A cover meter is an instrument, and a title in quotes is the document's own.
    assert not any(old in ("meter", "Color") for _k, old, _n in uk)
    us = language("US")
    assert ("english", "colour", "color") in us and not any(k == "english" and o == "center"
                                                             for k, o, _n in us)


def test_grammar_and_spelling_are_suggested():
    found = language("UK")
    for expected in [("grammar", "the the", "the"), ("grammar", "conforms", "conform"),
                     ("grammar", "a", "an"), ("grammar", " ,", ","),
                     ("spelling", "Reinforcment", "Reinforcement")]:
        assert expected in found
    assert ("grammar", "an", "a") not in found            # "an HDPE sleeve" is right


def test_the_scope_rewords_only_where_it_applies():
    rules = [{"find": "building", "replace": "structure", "when": "structures!=Buildings",
              "unless_next": "products"}, {"find": "etc.", "replace": "", "note": "list them"}]
    marine = language("UK", {"structures": "Marine structures"}, rules)
    assert marine.count(("scope", "building", "structure")) == 1       # not "building products"
    assert ("wording", "etc.", "") in marine
    both = language("UK", {"structures": "Marine structures|Buildings"}, rules)
    assert not any(k == "scope" for k, _o, _n in both)


def test_nothing_changes_until_it_is_accepted(signed_in):
    load(signed_in, "033000", LANGUAGE, "CAST-IN-PLACE CONCRETE")
    answer = signed_in.post("/specs/sets", data={"name": "Harbour Works"})
    set_id = int(answer.headers["Location"].rstrip("/").rsplit("/", 1)[1])
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["1"]})
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Harbour Works", "opt_english": "UK",
                                                  "opt_structures": ["Marine structures"]})
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "aluminium" in page and "structure" in page
    edit = lambda: text(signed_in.get(f"/specs/sets/{set_id}/sections/1/edit"))
    assert "aluminum" in edit() and "the the" in edit()

    from app import specs_store
    with signed_in.application.test_request_context():
        from flask import g
        g.user = {"id": 1, "name": "t", "role": "admin"}
        found = {f["old"]: f for f in specs_store.language_set(set_id)}
    one = found["aluminum"]
    signed_in.post(f"/specs/sets/{set_id}/language", data={
        "action": "accept", "row_id": one["row_id"], "node_id": one["node_id"], "old": "aluminum",
        "at": one["at"], "new": "aluminium"})
    # Or what the engineer typed instead.
    signed_in.post(f"/specs/sets/{set_id}/language", data={
        "action": "accept", "old": "the the", "new": "all the", "row_id": found["the the"]["row_id"],
        "node_id": found["the the"]["node_id"], "at": found["the the"]["at"]})
    assert "aluminium" in edit() and "all the concrete" in edit() and "center" in edit()
    signed_in.post(f"/specs/sets/{set_id}/language", data={"action": "leave", "old": "center"})
    assert "centre" not in text(signed_in.get(f"/specs/sets/{set_id}/check"))
    # The master is as it was.
    assert "aluminum" in text(signed_in.get("/specs/library/1"))


def test_an_issue_that_refers_to_a_section_not_in_it_is_held(signed_in):
    load(signed_in, "032000", REBAR, "CONCRETE REINFORCING")
    answer = signed_in.post("/specs/sets", data={"name": "Harbour Works"})
    set_id = int(answer.headers["Location"].rstrip("/").rsplit("/", 1)[1])
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["1"]})
    held = signed_in.get(f"/specs/sets/{set_id}/export")
    assert held.status_code == 302 and "/check" in held.headers["Location"]
    page = text(signed_in.get(held.headers["Location"]))
    assert "Section 016000" in page and "Issue anyway" in page
    issued = signed_in.get(f"/specs/sets/{set_id}/export?anyway=1")
    assert issued.mimetype == "application/zip"


# --- SI units -------------------------------------------------------------------------

def test_imperial_units_are_offered_in_si():
    from app.specs_language import unit_findings

    found = {old: (new, why) for _at, old, new, why in unit_findings(
        "Water at 20 deg. C (68 deg. F); below 25 deg.C (68 deg. F); 4000 psi concrete; "
        "2.0 to 3.0 mils DFT; aggregate 3/8\"; 1-1/2 inches (38 mm) cover; see Section 2.4 in. full.")}
    assert found["20 deg. C (68 deg. F)"][0] == "20 deg. C"
    # A pair that does not agree is said so, not silently resolved.
    assert "disagree" in found["25 deg.C (68 deg. F)"][1]
    assert found["4000 psi"][0] == "27.6 MPa"
    assert found["2.0 to 3.0 mils"][0] == "50 to 75 µm"
    assert found["3/8\""][0] == "10 mm"
    assert found["1-1/2 inches (38 mm)"][0] == "38 mm"
    assert not any("2.4 in." in old for old in found)


def test_all_the_unit_suggestions_accepted_at_once(signed_in):
    load(signed_in, "033000", "# GENERAL\n## SUMMARY\n- Cure at 20 deg. C (68 deg. F) with 4000 psi grout.\n"
                              "- Keep below 25 deg. C (68 deg. F).\n", "CAST-IN-PLACE CONCRETE")
    answer = signed_in.post("/specs/sets", data={"name": "Harbour Works"})
    set_id = int(answer.headers["Location"].rstrip("/").rsplit("/", 1)[1])
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": ["1"]})
    signed_in.post(f"/specs/sets/{set_id}/language", data={"action": "all", "kind": "units"})
    edit = text(signed_in.get(f"/specs/sets/{set_id}/sections/1/edit"))
    assert "Cure at 20 deg. C with 27.6 MPa grout." in edit
    assert "25 deg. C (68 deg. F)" in edit                # left for the engineer to decide


def test_an_old_dated_edition_is_worth_a_look():
    sections = [{"id": 1, "number": "051200", "title": "X", "nodes": specs.align([], specs.from_text(
        "# GENERAL\n## A\n- Loads to EN 1991-1-4:2005 and BS EN 1090-2."))}]
    report = specs_check.check(sections, {}, {}, [], TABLE)
    assert any("2005 edition" in i["message"] for i in report["outdated"])
    assert not any("1090-2" in i["message"] for i in report["outdated"])
