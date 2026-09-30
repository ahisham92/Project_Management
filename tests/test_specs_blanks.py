"""Blanks to fill: the master's [choices] and <Insert ...> places, answered
once and written into the project's own text."""

from __future__ import annotations

from app import specs, specs_blanks
from .test_specs import text
from .test_specs_kinds import load, set_id_of


def test_a_run_of_brackets_is_one_blank_with_its_answers():
    runs = [m.group(0) for m in specs_blanks._runs(
        "Conduct conference at [Project site] <Insert location> to comply {ref:033000}.")]
    assert runs == ["[Project site] <Insert location>"]
    assert specs_blanks.pieces(runs[0]) == [{"text": "Project site", "free": False},
                                            {"text": "Insert location", "free": True}]
    assert specs_blanks.pieces("[B500B] [B500C]") == [{"text": "B500B", "free": False},
                                                      {"text": "B500C", "free": False}]
    # A choice written as a field is the project's answers' to make, not a blank.
    assert specs_blanks._runs("Finish {finish=smooth: [Class A]}.") == []


def test_filling_a_blank_and_leaving_it_out():
    words = "Conduct conference at [Project site] <Insert location>."
    run = "[Project site] <Insert location>"
    assert specs_blanks.fill(words, run, 0, "the Engineer's  office") == \
        "Conduct conference at the Engineer's office."
    assert specs_blanks.fill(words, run, 0, "") == "Conduct conference at."
    twice = "[A] or [B], then [A] or [B]."
    assert specs_blanks.fill(twice, "[A] or [B]", 1, "B") == "[A] or [B], then B."


def _project(app, signed_in):
    from app import specs_store

    load(signed_in, "STD15A_SPC_033713_ST_Shotcrete.docx",
         "# GENERAL\n## MEETINGS\n- Conduct conference at [Project site] <Insert location>.\n"
         "- Submit [three] [four] copies to [Project site] <Insert location>.\n",
         "033713", "SHOTCRETE")
    with app.app_context():
        section_id = specs_store.section_by_number("033713", "15A")["id"]
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Tunnel", "family": "15A"}))
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    return set_id


def test_the_page_lists_the_blanks_and_writes_the_answers_in(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    assert "Fill the blanks (3)" in text(signed_in.get(f"/specs/sets/{set_id}"))
    page = text(signed_in.get(f"/specs/sets/{set_id}/blanks"))
    assert "Blanks to fill" in page and "<mark>[Project site] &lt;Insert location&gt;</mark>" in page
    assert "<sup>2</sup>[Project site] &lt;Insert location&gt;" in page  # two in one paragraph
    assert "Same answer wherever this blank appears (2 places)" in page
    with app.app_context():
        found = specs_store.blanks(set_id)
    site, copies, site2 = found
    answer = signed_in.post(f"/specs/sets/{set_id}/blanks", data={
        "key": [site["key"], copies["key"], site2["key"]],
        f"pick_{site['key']}": "__free__", f"free_{site['key']}": "the site office",
        f"all_{site['key']}": "1",
        f"pick_{copies['key']}": "three"}, follow_redirects=True)
    assert "Filled 3 blanks." in text(answer)
    with app.app_context():
        body = specs.loads(specs_store.set_sections(set_id)[0]["body"])
        assert specs_store.blanks(set_id) == []
    words = [n["text"] for n in body]
    assert "Conduct conference at the site office." in words
    assert "Submit three copies to the site office." in words
    assert "No blanks left" in text(signed_in.get(f"/specs/sets/{set_id}/blanks"))


def test_a_blank_answered_on_its_own_beats_the_same_everywhere_one(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    with app.app_context():
        site, _copies, site2 = specs_store.blanks(set_id)
    signed_in.post(f"/specs/sets/{set_id}/blanks", data={
        "key": [site["key"], site2["key"]],
        f"pick_{site['key']}": "Project site", f"all_{site['key']}": "1",
        f"free_{site2['key']}": "the Engineer"})
    with app.app_context():
        words = [n["text"] for n in specs.loads(specs_store.set_sections(set_id)[0]["body"])]
    assert "Conduct conference at Project site." in words
    assert "Submit [three] [four] copies to the Engineer." in words


def test_nothing_answered_fills_nothing(app, signed_in):
    set_id = _project(app, signed_in)
    answer = signed_in.post(f"/specs/sets/{set_id}/blanks", data={"key": ["x"]},
                            follow_redirects=True)
    assert "Nothing was filled" in text(answer)


def test_one_section_at_a_time_then_the_next(app, signed_in):
    from app import specs_store

    set_id = _project(app, signed_in)
    load(signed_in, "STD15A_SPC_033714_ST_Grout.docx",
         "# GENERAL\n## SUBMITTALS\n- Submit to <Insert name>.\n", "033714", "GROUT")
    with app.app_context():
        grout = specs_store.section_by_number("033714", "15A")["id"]
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(grout)]})
    with app.app_context():
        rows = {s["number"]: s["id"] for s in specs_store.set_sections(set_id)}
        found = specs_store.blanks(set_id)
    page = text(signed_in.get(f"/specs/sets/{set_id}/blanks"))
    assert "033713 — SHOTCRETE" in page and "Submit to" not in page and "Next: 033714" in page
    last = next(b for b in found if b["number"] == "033714")
    answer = signed_in.post(f"/specs/sets/{set_id}/blanks", data={
        "section": rows["033713"], "key": [b["key"] for b in found if b["number"] == "033713"],
        **{f"pick_{b['key']}": "__none__" for b in found if b["number"] == "033713"}},
        follow_redirects=True)
    page = text(answer)
    assert "033714 — GROUT" in page and f'name="free_{last["key"]}"' in page
