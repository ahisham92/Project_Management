"""Trades: each account has one, a project is given the trades it needs and
each trade writes its own specification of it, from its own library and
brief, shown side by side as tabs."""

from __future__ import annotations

import io
import json
import zipfile

from app import specs

from .test_specs import text
from .test_specs_kinds import set_id_of
from .test_specs_review import _person, _user_id

GEO = """# PART 1 GENERAL
## SUMMARY
A. Bored piles to [Project site] <Insert location>.
"""
STRUCT = """# PART 1 GENERAL
## SUMMARY
A. Cast-in-place concrete.
"""


def _library(app, geo_applies="ge_piles=Bored piles and barrettes"):
    """A structural section for every project, and a geotechnical one for
    bored piles, as library files bring them, with the geotechnical brief."""
    from app import specs_store

    data = {"format": "specs-writer-library/1", "sections": [
        {"family": "15A", "number": "033000", "title": "CAST-IN-PLACE CONCRETE", "applies": "*",
         "body": specs.align([], specs.from_text(STRUCT))},
        {"family": "15A", "number": "316323", "title": "DRILLED CONCRETE PILES", "trade": "geotechnical",
         "applies": geo_applies, "body": specs.align([], specs.from_text(GEO))}],
        "options": [{"key": "ge_piles", "label": "Piles", "grp": "Geotechnical scope", "kind": "many",
                     "trade": "geotechnical", "choices": "Bored piles and barrettes|Steel piles|None",
                     "default_value": "None"}]}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("library.json", json.dumps(data))
    with app.app_context():
        return specs_store.unpack(out.getvalue())


def test_an_account_is_given_its_trade_by_an_administrator(app, signed_in):
    _person(app, signed_in, "Layla")
    layla = _user_id(app, "Layla")
    signed_in.post(f"/admin/users/{layla}", data={"username": "layla", "name": "Layla", "programs": ["specs"],
                                                  "themis_trade": "geotechnical"})
    page = text(signed_in.get("/admin/"))
    assert "Geotechnical" in page
    from app.db import query_one
    with app.app_context():
        assert query_one("SELECT themis_trade FROM users WHERE id = ?", (layla,))["themis_trade"] == "geotechnical"


def test_library_sections_and_brief_questions_belong_to_a_trade(app, signed_in):
    from app import specs_store

    _library(app)
    with app.app_context():
        assert [s["number"] for s in specs_store.library(trade="geotechnical")] == ["316323"]
        assert [s["number"] for s in specs_store.library(trade="structures")] == ["033000"]
        geo = {o["key"] for o in specs_store.options("geotechnical")}
        struct = {o["key"] for o in specs_store.options("structures")}
    # Each trade asks its own questions and the shared ones (the standards, what it builds).
    assert "ge_piles" in geo and "ge_piles" not in struct
    assert "standards" in geo and "standards" in struct and "structures" in geo
    assert "steel_framing" in struct and "steel_framing" not in geo


def test_a_project_given_two_trades_has_a_specification_for_each_as_tabs(app, signed_in):
    from app import specs_store, specs_trades

    _library(app)
    _person(app, signed_in, "Layla")
    layla = _user_id(app, "Layla")
    answer = signed_in.post("/specs/sets", data={"name": "Jeddah Quay", "code": "P100", "family": "15A",
                                                "trade": ["structures", "geotechnical"],
                                                f"lead_geotechnical": str(layla)})
    first = set_id_of(answer)
    with app.app_context():
        row = specs_store.spec_set(first)
        both = specs_trades.siblings(row)
        assert [s["trade"] for s in both] == ["structures", "geotechnical"]
        geo = both[1]
        # Layla leads the geotechnical specification.
        from app.specs_review import role_of
        from app.db import query_one
        assert role_of(geo, query_one("SELECT * FROM users WHERE id = ?", (layla,))) == "lead"
    page = text(signed_in.get(f"/specs/sets/{first}"))
    assert "Structures" in page and "Geotechnical" in page and f"/specs/sets/{geo['id']}" in page
    # The other trade is a tab, not another package of the same trade.
    assert "2 packages" not in page
    # The geotechnical brief puts in its own trade's sections only.
    signed_in.post(f"/specs/sets/{geo['id']}/inputs/decide",
                   data={"shown_opt": ["ge_piles"], "opt_ge_piles": ["Bored piles and barrettes"]})
    with app.app_context():
        assert [s["number"] for s in specs_store.set_sections(geo["id"])] == ["316323"]
        assert "316323" not in [s["number"] for s in specs_store.set_sections(first)]


def test_another_trade_is_added_to_a_project_later_with_the_shared_answers(app, signed_in):
    from app import specs_store, specs_trades

    _library(app)
    one = set_id_of(signed_in.post("/specs/sets", data={"name": "Lagos Port", "family": "15A"}))
    with app.app_context():
        from app.db import execute
        execute("UPDATE spec_sets SET options = ? WHERE id = ?",
                (json.dumps({"structures": "Marine structures", "design_life": "100 years"}), one))
    answer = signed_in.post(f"/specs/sets/{one}/trades", data={"trade": "geotechnical"})
    assert "/story" in answer.headers["Location"]
    with app.app_context():
        geo = specs_trades.sibling(specs_store.spec_set(one), "geotechnical")
        assert geo and json.loads(geo["options"])["structures"] == "Marine structures"
        assert geo["name"] == "Lagos Port" and geo["trade_group"] == one
    # A trade is added once.
    signed_in.post(f"/specs/sets/{one}/trades", data={"trade": "geotechnical"})
    with app.app_context():
        assert len(specs_trades.siblings(specs_store.spec_set(one))) == 2


def test_replacing_one_trades_library_leaves_the_other_trades_sections(app, signed_in):
    from app import specs_store

    _library(app)
    data = {"format": "specs-writer-library/1", "trade": "geotechnical", "sections": [
        {"family": "15A", "number": "316216", "title": "STEEL PILES", "applies": "ge_piles=Steel piles",
         "body": specs.align([], specs.from_text(GEO))}]}
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("library.json", json.dumps(data))
    with app.app_context():
        done = specs_store.unpack(out.getvalue(), "replace")
        assert done["removed"] == ["15A 316323"]
        assert [s["number"] for s in specs_store.library("15A")] == ["033000", "316216"]


def test_the_trade_comes_from_the_mtd_file_name():
    from app import specs_trades

    assert specs_trades.from_filename("STD15A_SPC_316323_GE_DRILLED PILES_REVA.docx") == "geotechnical"
    assert specs_trades.from_filename("STD15A_SPC_353123_MR_BREAKWATERS_REVA.docx") == "geotechnical"
    assert specs_trades.from_filename("STD15A_SPC_033000_ST_CONCRETE_REVA.docx") == "structures"
    assert specs_trades.from_filename("SPC-FD-032000-ST.docx") == ""


def test_a_geotechnical_specification_ticks_its_ground_works_and_tells_the_ground_story(app, signed_in):
    from app import specs_store, specs_trades

    _library(app)
    with app.app_context():
        from app.db import execute
        execute("INSERT INTO spec_options (key, label, grp, kind, choices, default_value, trade) "
                "VALUES ('ge_ground', 'Ground the works are founded in', 'Ground conditions', 'many', "
                "'Soft clay|Sabkha', '', 'geotechnical')")
    one = set_id_of(signed_in.post("/specs/sets", data={"name": "Yanbu Berth", "family": "15A",
                                                       "trade": ["structures", "geotechnical"]}))
    with app.app_context():
        geo = specs_trades.sibling(specs_store.spec_set(one), "geotechnical")
    signed_in.post(f"/specs/sets/{geo['id']}/inputs/decide",
                   data={"shown_opt": ["ge_piles", "ge_ground"], "opt_ge_piles": ["Bored piles and barrettes"],
                         "opt_ge_ground": ["Sabkha"]})
    page = text(signed_in.get(f"/specs/sets/{geo['id']}"))
    # Its step 2 is the ground works, not the structural elements or the Revit model.
    assert "Ground works" in page and "Bored piles and barrettes" in page
    assert "Read the elements from the Revit model" not in page
    # The ground it stands on calls for no section of its own.
    assert "no section written for them" not in page
    story = text(signed_in.get(f"/specs/sets/{geo['id']}/story"))
    assert "the instruments that watch the ground works" in story
