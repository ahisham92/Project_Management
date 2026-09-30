"""The page editor: paragraphs sent back as they are, with their ids."""

from __future__ import annotations

import json

from app import specs
from .test_specs import text
from .test_specs_kinds import load, set_id_of


def _library_section(app, signed_in):
    from app import specs_store

    load(signed_in, "STD15A_SPC_033713_ST_Shotcrete.docx",
         "# GENERAL\n## SUMMARY\n- Section includes shotcrete.\n-- Mixes.\n", "033713", "SHOTCRETE")
    with app.app_context():
        s = specs_store.section_by_number("033713", "15A")
        return s["id"], specs.loads(s["body"])


def test_the_page_editor_keeps_ids_and_levels(app, signed_in):
    from app import specs_store

    section_id, nodes = _library_section(app, signed_in)
    page = text(signed_in.get(f"/specs/library/{section_id}/edit"))
    assert 'id="se-data"' in page and "spec-editor.js" in page and "Save and close" in page
    sent = [dict(n) for n in nodes]
    sent[2]["text"] = "Section includes sprayed concrete."            # amended
    sent.insert(3, {"id": "", "level": "PR2", "text": "A new one.", "when": "leed=v4"})
    sent.append({"id": "", "level": "TBL", "text": "| a | b |\n| 1 | 2 |", "when": ""})
    sent.append({"id": "", "level": "PR1", "text": "   ", "when": ""})      # empty: dropped
    answer = signed_in.post(f"/specs/library/{section_id}/edit", data={
        "number": "033713", "title": "SHOTCRETE", "mode": "page", "text": "",
        "nodes": json.dumps({"count": len(sent), "nodes": sent})})
    assert answer.status_code == 302
    with app.app_context():
        saved = specs.loads(specs_store.section(section_id)["body"])
    assert [n["id"] for n in saved[:3]] == [n["id"] for n in nodes[:3]]
    assert saved[2]["text"] == "Section includes sprayed concrete."
    assert (saved[3]["level"], saved[3]["text"], saved[3]["when"]) == ("PR2", "A new one.", "leed=v4")
    assert saved[-1]["level"] == "TBL" and len(saved) == len(nodes) + 2


def test_a_page_cut_short_is_not_saved(app, signed_in):
    from app import specs_store

    section_id, nodes = _library_section(app, signed_in)
    answer = signed_in.post(f"/specs/library/{section_id}/edit", data={
        "number": "033713", "title": "SHOTCRETE", "mode": "page",
        "nodes": json.dumps({"count": len(nodes), "nodes": nodes[:1]})}, follow_redirects=True)
    assert "did not arrive whole" in text(answer)
    with app.app_context():
        assert len(specs.loads(specs_store.section(section_id)["body"])) == len(nodes)


def test_the_plain_text_still_saves(app, signed_in):
    from app import specs_store

    section_id, nodes = _library_section(app, signed_in)
    signed_in.post(f"/specs/library/{section_id}/edit", data={
        "number": "033713", "title": "SHOTCRETE", "mode": "text", "nodes": "",
        "text": "# GENERAL\n## SUMMARY\n- Section includes shotcrete.\n-- Mixes and curing.\n"})
    with app.app_context():
        saved = specs.loads(specs_store.section(section_id)["body"])
    assert saved[3]["text"] == "Mixes and curing." and saved[2]["id"] == nodes[2]["id"]


def test_a_project_section_edits_on_the_page_too(app, signed_in):
    from app import specs_store

    section_id, nodes = _library_section(app, signed_in)
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Tunnel", "family": "15A"}))
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    with app.app_context():
        row = specs_store.set_sections(set_id)[0]
    sent = specs.loads(row["body"])
    sent[3]["text"] = "Mixes, by the project."
    answer = signed_in.post(f"/specs/sets/{set_id}/sections/{row['id']}/edit", data={
        "title": "SHOTCRETE", "mode": "page", "nodes": json.dumps({"count": len(sent), "nodes": sent}),
        "stay": "1"})
    assert answer.headers["Location"].endswith("/edit")
    with app.app_context():
        assert specs.loads(specs_store.set_section(set_id, row["id"])["body"])[3]["text"] == "Mixes, by the project."
