"""IDC: the structural specification sent to geotechnical, whose engineer
puts their input in as tracked changes that the structural engineer accepts
or rejects; and, while it is open, the two documents checked against each
other."""

from __future__ import annotations

import json

from .test_specs import text
from .test_specs_kinds import set_id_of
from .test_specs_review import _person, _user_id
from .test_specs_trades import _library


def _project(app, signed_in):
    """A project with both trades: the structural one started by the signed-in
    engineer, the geotechnical one led by Layla, a geotechnical engineer."""
    from app import specs_store, specs_trades

    _library(app)
    _person(app, signed_in, "Layla")
    layla = _user_id(app, "Layla")
    signed_in.post(f"/admin/users/{layla}", data={"username": "layla", "name": "Layla", "programs": ["specs"],
                                                  "themis_trade": "geotechnical"})
    one = set_id_of(signed_in.post("/specs/sets", data={
        "name": "Jeddah Quay", "code": "P100", "family": "15A", "trade": ["structures", "geotechnical"],
        "lead_geotechnical": str(layla)}))
    signed_in.post(f"/specs/sets/{one}/sections", data={"section_id": _section_id(app, "033000")})
    with app.app_context():
        geo = specs_trades.sibling(specs_store.spec_set(one), "geotechnical")
        rows = specs_store.set_sections(one)
    assert rows, "the structural section is in"
    return one, geo["id"], rows[0]["id"], layla


def _section_id(app, number):
    from app.db import query_one
    with app.app_context():
        return query_one("SELECT id FROM spec_sections WHERE number = ?", (number,))["id"]


def _as(app, client, user_id):
    with client.session_transaction() as s:
        s["user_id"] = user_id


def _paragraph(app, set_id, row_id, words):
    from app import specs, specs_store
    with app.app_context():
        nodes = specs.loads(specs_store.set_section(set_id, row_id)["body"])
    return next(n for n in nodes if words in n["text"])


def test_structures_sends_an_idc_and_geotechnical_puts_in_changes_to_accept_or_reject(app, signed_in):
    from app import specs, specs_store

    one, geo, row_id, layla = _project(app, signed_in)
    answer = signed_in.post(f"/specs/sets/{one}/idc", data={"trade": ["geotechnical"],
                                                           "note": "Please check the foundations."})
    assert answer.headers["Location"].endswith(f"/specs/sets/{one}/idc")
    page = text(signed_in.get(f"/specs/sets/{one}"))
    assert "IDC" in page and "Geotechnical" in page
    # Layla sees it on her start page and on her own specification of the project.
    with signed_in.session_transaction() as s:
        admin_id = s["user_id"]
    _as(app, signed_in, layla)
    assert "Jeddah Quay" in text(signed_in.get("/specs/")) and "IDC" in text(signed_in.get("/specs/"))
    assert "input" in text(signed_in.get(f"/specs/sets/{geo}")).lower()
    p = _paragraph(app, one, row_id, "Cast-in-place concrete")
    signed_in.post(f"/specs/sets/{one}/idc/{row_id}/propose", data={
        "node": p["id"], "kind": "reword", "text": "Cast-in-place concrete for sulfate-resisting ground.",
        "why": "Sabkha on site"})
    signed_in.post(f"/specs/sets/{one}/idc/{row_id}/propose", data={
        "node": p["id"], "kind": "add", "text": "Piles are specified in Section 316323.", "level": "PR1"})
    section_page = text(signed_in.get(f"/specs/sets/{one}/idc/{row_id}"))
    assert "<ins>" in section_page and "Sabkha on site" in section_page and "Layla" in section_page
    # Nothing changed in the specification yet; and Layla cannot accept her own input.
    with app.app_context():
        assert "sulfate" not in specs_store.set_section(one, row_id)["body"]
    from app import specs_idc
    with app.app_context():
        it = specs_idc.open_idc(one)
        reword, add = specs_idc.changes(it["id"], row_id)
    signed_in.post(f"/specs/sets/{one}/idc/changes/{reword['id']}", data={"how": "accept"})
    with app.app_context():
        assert specs_idc.change(reword["id"])["state"] == "open"
    # The structural engineer accepts one and rejects the other with an answer.
    _as(app, signed_in, admin_id)
    signed_in.post(f"/specs/sets/{one}/idc/changes/{reword['id']}", data={"how": "accept"})
    signed_in.post(f"/specs/sets/{one}/idc/changes/{add['id']}", data={"how": "reject", "answer": ""})
    with app.app_context():
        assert specs_idc.change(add["id"])["state"] == "open"        # a rejection says why
    signed_in.post(f"/specs/sets/{one}/idc/changes/{add['id']}", data={"how": "reject",
                                                                       "answer": "Covered on the drawings."})
    with app.app_context():
        body = specs.loads(specs_store.set_section(one, row_id)["body"])
        assert any("sulfate-resisting" in n["text"] for n in body)
        assert not any("316323" in n["text"] for n in body)
        assert specs_idc.change(add["id"])["answer"] == "Covered on the drawings."
        from app.db import query
        assert any("IDC change by Layla accepted" in r["what"]
                   for r in query("SELECT what FROM spec_history WHERE set_id = ?", (one,)))
    # Closing it ends the input.
    signed_in.post(f"/specs/sets/{one}/idc/close")
    with app.app_context():
        assert specs_idc.open_idc(one) is None


def test_while_an_idc_is_open_the_trades_documents_are_checked_against_each_other(app, signed_in):
    from app import specs_idc, specs_store
    from app.db import execute

    one, geo, _row, _layla = _project(app, signed_in)
    with app.app_context():
        execute("UPDATE spec_sets SET options = ?, answers = ? WHERE id = ?",
                (json.dumps({"design_life": "100 years", "exposure": "Marine"}),
                 json.dumps({"conc_cover": "75 mm"}), one))
        execute("UPDATE spec_sets SET options = ?, answers = ?, client = 'Port Authority' WHERE id = ?",
                (json.dumps({"design_life": "50 years", "exposure": "Marine"}),
                 json.dumps({"conc_cover": "50 mm"}), geo))
        execute("UPDATE spec_sets SET client = 'Ports Co' WHERE id = ?", (one,))
        found = {b["key"]: b for b in specs_idc.between(specs_store.spec_set(one))}
    assert found["design_life"]["here"] == "100 years" and found["design_life"]["there"] == "50 years"
    assert found["conc_cover"]["there"] == "50 mm" and found["client"]["there"] == "Port Authority"
    assert "exposure" not in found
    # Shown on the IDC and on the check of both specifications while it is open.
    signed_in.post(f"/specs/sets/{one}/idc", data={"trade": ["geotechnical"]})
    assert "Between the documents" in text(signed_in.get(f"/specs/sets/{one}/idc"))
    for set_id in (one, geo):
        page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
        assert "Between the trades" in page and "50 years" in page


def test_an_idc_goes_only_to_another_trade_and_one_at_a_time(app, signed_in):
    one, _geo, _row, _layla = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{one}/idc", data={"trade": ["structures"]})
    from app import specs_idc
    with app.app_context():
        assert specs_idc.open_idc(one) is None
    signed_in.post(f"/specs/sets/{one}/idc", data={"trade": ["geotechnical"]})
    signed_in.post(f"/specs/sets/{one}/idc", data={"trade": ["geotechnical"]})
    with app.app_context():
        assert len(specs_idc.idcs(one)) == 1
