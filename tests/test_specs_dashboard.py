"""THEMIS's start page as a dashboard with a map, a new project's own page with
its city and country, .themis files between colleagues, a working copy that is
not issued, plain words for why a section is in, and a way to settle an answer
the library has nothing written for."""

from __future__ import annotations

import io
import json
import zipfile

from .test_specs import text
from .test_specs_kinds import applies, load, set_id_of


def _concrete(app, signed_in) -> int:
    load(signed_in, "STD15A_SPC_033000_ST_Concrete.docx", "# GENERAL\n## SUMMARY\n- Concrete.\n",
         "033000", "CAST-IN-PLACE CONCRETE")
    applies(app, "033000", "15A", "cast_in_place=Yes")
    return set_id_of(signed_in.post("/specs/sets", data={
        "name": "Jeddah Tower", "code": "P100", "client": "ACME", "family": "15A",
        "city": "Jeddah", "country": "Saudi Arabia"}))


def test_a_new_project_has_its_own_page_with_city_and_country(app, signed_in):
    page = text(signed_in.get("/specs/new"))
    assert 'name="city"' in page and 'name="country"' in page and "Start the project" in page
    set_id = _concrete(app, signed_in)
    from app import specs_questions, specs_store

    with app.app_context():
        row = specs_store.spec_set(set_id)
        assert (row["city"], row["country"]) == ("Jeddah", "Saudi Arabia")
        assert round(row["lat"]) == 21 and round(row["lng"]) == 39
        # The sections' location is written from them.
        assert specs_questions.answers_of(row)["proj_location"] == "Jeddah, Saudi Arabia"
    # The old way into a copy lands on the new page, filled in.
    answer = signed_in.get(f"/specs/?start_from={set_id}&package=1")
    assert answer.status_code == 302 and "/specs/new?start_from=" in answer.headers["Location"]


def test_the_start_page_is_a_dashboard_with_the_projects_on_a_map(app, signed_in):
    _concrete(app, signed_in)
    page = text(signed_in.get("/specs/"))
    assert "Where the projects are" in page and "leaflet" in page and "themis-dashboard.js" in page
    points = json.loads(page.split('data-points="', 1)[1].split('"', 1)[0].replace("&#34;", '"')
                        .replace("&quot;", '"'))
    assert points[0]["name"] == "Jeddah Tower" and points[0]["city"] == "Jeddah"
    assert "Recently issued" in page and "Not issued yet" in page and "Jeddah, Saudi Arabia" in page
    # A city the site's list does not have: the browser's point is kept, once.
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Far", "city": "Nowhereville",
                                                          "country": "Atlantis"}))
    page = text(signed_in.get("/specs/"))
    assert "Nowhereville" in page.split('data-unplaced="', 1)[1].split('"', 1)[0]
    assert signed_in.post("/specs/points", json={"points": [{"id": set_id, "lat": 10, "lng": 20}]}).json == {"saved": 1}
    assert signed_in.post("/specs/points", json={"points": [{"id": set_id, "lat": 11, "lng": 21}]}).json == {"saved": 0}


def test_every_page_has_the_same_menu_and_a_way_back(app, signed_in):
    set_id = _concrete(app, signed_in)
    project = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert 'class="themis-nav"' in project and "Back to all projects" in project
    for path in ("issues", "review", "comments", "history", "amendments", "packages"):
        page = text(signed_in.get(f"/specs/sets/{set_id}/{path}"))
        assert 'class="themis-nav"' in page, path
        assert f'href="/specs/sets/{set_id}"><span aria-hidden="true">←</span> Back to the project' in page, path
    issued = text(signed_in.get(f"/specs/sets/{set_id}/issues"))
    assert "Issued revisions" in issued and ">Issues<" not in issued
    library = text(signed_in.get("/specs/library"))
    assert 'aria-current="page">Master library' in library


def test_the_project_page_says_what_each_tool_does_and_why_a_section_is_in(app, signed_in):
    set_id = _concrete(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Jeddah Tower", "opt_cast_in_place": "Yes"})
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    for words in ("Check the text", "Changes from the master", "Copy into a new package or project",
                  "Download as it is now", "Send to a colleague (.themis)", "Issued revisions"):
        assert words in page, words
    assert "You said the project has cast-in-place concrete" in page
    assert "cast_in_place=Yes</td>" not in page


def test_a_working_copy_downloads_without_the_hold_and_says_it_is_not_issued(app, signed_in):
    set_id = _concrete(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Jeddah Tower", "opt_cast_in_place": "Yes",
                                                  "hold_shown": "1", "hold_issue": "1"})
    answer = signed_in.get(f"/specs/sets/{set_id}/export?draft=1")
    assert answer.status_code == 200
    assert "working copy (not issued)" in answer.headers["Content-Disposition"]
    files = zipfile.ZipFile(io.BytesIO(answer.data))
    inner = zipfile.ZipFile(io.BytesIO(files.read(files.namelist()[0])))
    xml = "".join(inner.read(n).decode("utf-8", "ignore") for n in inner.namelist() if n.endswith(".xml"))
    assert "WORKING COPY, NOT ISSUED" in xml
    from app import specs_review

    with app.app_context():
        assert specs_review.last_issue(set_id) is None


def test_a_project_and_a_template_travel_as_themis_files(app, signed_in):
    set_id = _concrete(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Jeddah Tower", "opt_cast_in_place": "Yes"})
    from app import specs_store

    with app.app_context():
        row_id = specs_store.set_sections(set_id)[0]["id"]
    signed_in.post(f"/specs/sets/{set_id}/sections/{row_id}/edit",
                   data={"mode": "text", "text": "# GENERAL\n## SUMMARY\n- Concrete for the tower.\n",
                         "title": "CAST-IN-PLACE CONCRETE"})
    whole = signed_in.get(f"/specs/sets/{set_id}/themis")
    assert whole.headers["Content-Disposition"].endswith('.themis"')
    doc = json.loads(zipfile.ZipFile(io.BytesIO(whole.data)).read("themis.json"))
    assert doc["kind"] == "project" and doc["project"]["code"] == "P100"
    assert doc["sections"][0]["master"]["number"] == "033000"

    back = signed_in.post("/specs/import", data={"file": (io.BytesIO(whole.data), "x.themis")},
                          content_type="multipart/form-data")
    copy = set_id_of(back)
    with app.app_context():
        row = specs_store.spec_set(copy)
        assert copy != set_id and row["name"] == "Jeddah Tower" and row["code"] == "P100"
        assert row["city"] == "Jeddah" and row["created_by"] is not None
        one = specs_store.set_sections(copy)[0]
        # Lined up with the same master, with its amendment still counted.
        assert one["section_id"] is not None and one["changed"] + one["added"] >= 1
        assert "Concrete for the tower." in one["body"]

    template = signed_in.get(f"/specs/sets/{set_id}/themis?template=1")
    doc = json.loads(zipfile.ZipFile(io.BytesIO(template.data)).read("themis.json"))
    assert doc["kind"] == "template" and "code" not in doc["project"] and "city" not in doc["project"]
    refused = signed_in.post("/specs/import", data={"file": (io.BytesIO(template.data), "t.themis")},
                             content_type="multipart/form-data", follow_redirects=True)
    assert "Give the project a name" in text(refused)
    made = set_id_of(signed_in.post("/specs/import", data={
        "file": (io.BytesIO(template.data), "t.themis"), "name": "Riyadh Mall", "city": "Riyadh",
        "country": "Saudi Arabia"}, content_type="multipart/form-data"))
    with app.app_context():
        row = specs_store.spec_set(made)
        assert row["name"] == "Riyadh Mall" and row["code"] == "" and row["city"] == "Riyadh"
    junk = signed_in.post("/specs/import", data={"file": (io.BytesIO(b"not a zip"), "j.themis")},
                          content_type="multipart/form-data", follow_redirects=True)
    assert "not a .themis file" in text(junk)


def test_an_answer_with_no_section_can_be_settled(app, signed_in):
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
    assert "no section written for" in page and "Not needed" in page and "Write a section for it" in page
    signed_in.post(f"/specs/sets/{set_id}/cover", data={"key": "fenders", "value": "Cell", "how": "not_needed"})
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    assert 'id="uncovered"' not in page or "Cell</strong> <span" not in page.split('id="uncovered"')[1][:400]
    assert "settled" in page
    check = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "Fender type: Cell" not in check
    # Opened again, it is back.
    signed_in.post(f"/specs/sets/{set_id}/cover", data={"key": "fenders", "value": "Cell", "how": "open"})
    assert "Fender type: Cell" in text(signed_in.get(f"/specs/sets/{set_id}/check"))
    # Or a section of the project's own is written for it.
    answer = signed_in.post(f"/specs/sets/{set_id}/cover", data={
        "key": "fenders", "value": "Cell", "how": "own", "number": "355913", "title": "CELL FENDERS"})
    assert "/edit" in answer.headers["Location"]
    assert "Fender type: Cell" not in text(signed_in.get(f"/specs/sets/{set_id}/check"))


def test_conditions_read_as_plain_words(app):
    from app import specs_store

    labels = {"cast_in_place": {"label": "Cast-in-place concrete", "choice_list": ["No", "Yes"]},
              "waterproofing": {"label": "Waterproofing", "choice_list": ["None", "SBS modified sheet"]},
              "elements": {"label": "Structural elements", "choice_list": []}}
    with app.app_context():
        said = lambda w: specs_store.plain_condition(w, "15A", labels)  # noqa: E731
        assert said("cast_in_place=Yes") == "You said the project has cast-in-place concrete"
        assert said("cast_in_place=No") == "You said the project has no cast-in-place concrete"
        assert said("waterproofing=SBS modified sheet|Bituminous sheet") == \
            "You chose SBS modified sheet or Bituminous sheet for waterproofing"
        assert said("cast_in_place=Yes&elements=Piles") == \
            "You said the project has cast-in-place concrete and it has piles"
        assert said("*") == "Every 15A project has it"
