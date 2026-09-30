"""Keep, amend or remove: what the engineer does with each item on the check,
and the rewriting that proposes an amendment for a section not issued."""

from __future__ import annotations

from app import specs, specs_check
from .test_specs import text
from .test_specs_kinds import load, set_id_of

# --- rewriting a reference to a section not in the specification -------------------

def test_a_missing_section_is_put_as_the_codes_and_standards():
    rewrite = specs_check.without_section
    assert rewrite('Section 034500 "Precast Architectural Concrete" for reinforcing used in '
                   'precast architectural concrete.', "034500") == \
        "The applicable codes and standards for reinforcing used in precast architectural concrete."
    assert rewrite('Engineer as defined in Section 014000 "Quality Requirements," to design the '
                   'formwork.', "014000") == \
        "Engineer as defined in the applicable codes and standards, to design the formwork."
    assert rewrite('Preinstallation Conference: Conduct conference at [Project site] <Insert '
                   'location> to comply with requirements in Section 013100 "Project Management '
                   'and Coordination".', "013100") == \
        ("Preinstallation Conference: Conduct conference at [Project site] <Insert location> to "
         "comply with the requirements of the applicable codes and standards.")


def test_live_untitled_and_listed_references_are_rewritten_too():
    rewrite = specs_check.without_section
    assert rewrite("Tie wire to {ref:016000}.", "016000") == \
        "Tie wire to the applicable codes and standards."
    assert rewrite("Comply with Section 034500 for lifting.", "34500") == \
        "Comply with the applicable codes and standards for lifting."
    assert rewrite("Curing: see {ref:034500/CURING}.", "034500") == \
        "Curing: see the applicable codes and standards."
    assert rewrite("Grout as specified in Sections 033000 and 034500.", "034500") == \
        "Grout as specified in Section 033000."
    # Another section is left as it is.
    assert rewrite('Bars to Section 033000 "Cast-in-Place Concrete".', "034500") == \
        'Bars to Section 033000 "Cast-in-Place Concrete".'


def test_sentences_split_at_full_stops_and_semicolons_only():
    split = specs_check.sentences
    assert split('Use bars No. 4 at 200 mm, e.g. in slabs. Lap as shown; stagger laps.') == \
        ["Use bars No. 4 at 200 mm, e.g. in slabs.", "Lap as shown;", "stagger laps."]
    assert split('Mark "Grade A. Do not substitute." on each bundle. Store dry.') == \
        ['Mark "Grade A. Do not substitute." on each bundle.', "Store dry."]
    assert split("Approx. 5 kg, i.e. one bag. Sect. 2 of the code applies.") == \
        ["Approx. 5 kg, i.e. one bag.", "Sect. 2 of the code applies."]
    assert specs_check.without_sentence("Keep dry; cover with sheets.", 12) == \
        ("Keep dry.", "cover with sheets.")
    assert specs_check.without_sentence("Keep dry; cover with sheets.", 0) == \
        ("Cover with sheets.", "Keep dry;")
    assert specs_check.without_sentence("Only this.", 3) == ("", "Only this.")


# --- through the pages ----------------------------------------------------------------

REBAR = """\
# GENERAL
## SUMMARY
- Related Requirements:
-- Section 034500 "Precast Architectural Concrete" for reinforcing used in precast architectural concrete.
-- Tie wire to {ref:016000}.
## QUALITY ASSURANCE
- Engineer as defined in Section 014000 "Quality Requirements," to design the formwork.
- Mockups: Build one bay. Test it to Section 014000 "Quality Requirements".
# EXECUTION
## PLACING
- Preinstallation Conference: Conduct conference at the site to comply with requirements in Section 014000 "Quality Requirements".
- Bars: BS 4449 grade B500B.
"""


def project(app, signed_in) -> int:
    load(signed_in, "SPC-032000.docx", REBAR, "032000", "CONCRETE REINFORCING")
    set_id = set_id_of(signed_in.post("/specs/sets", data={"name": "Harbour Works"}))
    with app.app_context():
        from app import specs_store
        section_id = specs_store.section_by_number("032000")["id"]
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(section_id)]})
    return set_id


def report(app, set_id):
    from flask import g
    from app import specs_store
    with app.test_request_context():
        g.user = {"id": 1, "name": "t", "email": "t", "role": "admin"}
        found = specs_store.check_set(set_id)
        specs_store.check_actions(set_id, found)
        return found


def item(app, set_id, words):
    for i in report(app, set_id)["references"]:
        if words in i["message"]:
            return i
    return None


def body(app, set_id) -> list[dict]:
    from app import specs_store
    with app.app_context():
        return specs_store.set_whole(set_id)[0]["nodes"]


def texts(app, set_id) -> list[str]:
    return [n["text"] for n in body(app, set_id)]


def test_keep_settles_and_the_page_offers_keep_amend_remove(app, signed_in):
    set_id = project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert ">Keep<" in page and ">Amend<" in page and ">Remove<" in page
    assert ">Accept<" not in page and ">Reject<" not in page
    assert "to keep, amend or remove" in page
    one = item(app, set_id, "Section 034500")
    answer = signed_in.post(f"/specs/sets/{set_id}/settle", data={"key": one["key"], "state": "kept"})
    assert "Kept." in text(signed_in.get(answer.headers["Location"]))
    assert item(app, set_id, "Section 034500")["settled"]["how"] == "kept"
    # The text is as it was.
    assert any("Section 034500" in t for t in texts(app, set_id))


def test_amend_with_the_proposed_text_and_the_item_is_gone(app, signed_in):
    set_id = project(app, signed_in)
    one = item(app, set_id, "Section 034500")
    place = one["act"]["places"][0]
    assert place["proposed"] == ("The applicable codes and standards for reinforcing used in precast "
                                 "architectural concrete.")
    # Without JavaScript, Amend opens the box by going back to the server.
    page = text(signed_in.get(f"/specs/sets/{set_id}/check?amend={one['key']}"))
    assert f'id="amend-{one["key"]}"' in page and "Proposed amendment" in page
    answer = signed_in.post(f"/specs/sets/{set_id}/check/amend", data={
        "key": one["key"], "row_id": place["row_id"], "node_id": place["node_id"],
        "text": place["proposed"]})
    shown = text(signed_in.get(answer.headers["Location"]))
    assert "Amended: 1.1.A.1 of 032000." in shown
    assert "Amended to" in shown and "The applicable codes and standards for reinforcing" in shown
    assert place["proposed"] in texts(app, set_id)
    assert item(app, set_id, "Section 034500") is None
    # It can be amended again from the settled list.
    done = report(app, set_id)["done"]["references"]
    assert done and done[0]["act"]["places"][0]["current"] == place["proposed"]
    signed_in.post(f"/specs/sets/{set_id}/check/amend", data={
        "key": done[0]["key"], "row_id": place["row_id"], "node_id": place["node_id"],
        "text": "Codes and standards for precast work."})
    assert "Codes and standards for precast work." in texts(app, set_id)
    again = report(app, set_id)["done"]["references"][0]["settled"]["detail"]["places"][0]
    assert again["before"].startswith("Section 034500") and again["after"].startswith("Codes")


def test_a_live_reference_is_amended_too(app, signed_in):
    set_id = project(app, signed_in)
    one = item(app, set_id, "Section 016000")
    place = one["act"]["places"][0]
    assert place["proposed"] == "Tie wire to the applicable codes and standards."
    signed_in.post(f"/specs/sets/{set_id}/check/amend", data={
        "key": one["key"], "row_id": place["row_id"], "node_id": place["node_id"],
        "text": place["proposed"]})
    assert item(app, set_id, "Section 016000") is None


def test_an_amendment_that_keeps_the_reference_still_settles(app, signed_in):
    set_id = project(app, signed_in)
    one = item(app, set_id, "Section 034500")
    place = one["act"]["places"][0]
    signed_in.post(f"/specs/sets/{set_id}/check/amend", data={
        "key": one["key"], "row_id": place["row_id"], "node_id": place["node_id"],
        "text": 'Section 034500 "Precast Architectural Concrete", by others.'})
    still = item(app, set_id, "Section 034500")
    assert still and still["settled"]["how"] == "amended"


def test_remove_takes_the_sentence_or_the_whole_paragraph(app, signed_in):
    set_id = project(app, signed_in)
    before = len(body(app, set_id))
    one = item(app, set_id, "Section 034500")
    assert "whole paragraph goes" in one["act"]["confirm"]
    answer = signed_in.post(f"/specs/sets/{set_id}/check/remove", data={"key": one["key"]})
    shown = text(signed_in.get(answer.headers["Location"]))
    assert "Removed paragraph 1.1.A.1 of 032000" in shown
    assert len(body(app, set_id)) == before - 1
    assert not any("034500" in t for t in texts(app, set_id))
    assert item(app, set_id, "Section 034500") is None


def test_the_grouped_item_is_amended_and_removed_in_every_place(app, signed_in):
    set_id = project(app, signed_in)
    group = item(app, set_id, "Section 014000 is referred to in 3 places")
    assert group and len(group["act"]["places"]) == 3 and group["act"]["can_remove"]
    proposed = [p["proposed"] for p in group["act"]["places"]]
    assert "Engineer as defined in the applicable codes and standards, to design the formwork." in proposed
    assert ("Preinstallation Conference: Conduct conference at the site to comply with the "
            "requirements of the applicable codes and standards.") in proposed
    signed_in.post(f"/specs/sets/{set_id}/check/amend", data={
        "key": group["key"], "row_id": [p["row_id"] for p in group["act"]["places"]],
        "node_id": [p["node_id"] for p in group["act"]["places"]], "text": proposed})
    assert not any("014000" in t for t in texts(app, set_id))
    assert item(app, set_id, "Section 014000") is None


def test_the_grouped_item_removed_everywhere(app, signed_in):
    set_id = project(app, signed_in)
    group = item(app, set_id, "Section 014000 is referred to in 3 places")
    answer = signed_in.post(f"/specs/sets/{set_id}/check/remove", data={"key": group["key"]})
    shown = text(signed_in.get(answer.headers["Location"]))
    assert "Removed the sentence from" in shown
    now = texts(app, set_id)
    assert not any("014000" in t for t in now)
    # A paragraph with another sentence keeps it; one with none goes.
    assert "Mockups: Build one bay." in now
    assert not any(t.startswith("Engineer as defined") for t in now)
    assert not any(t.startswith("Preinstallation Conference") for t in now)
    assert "Bars: BS 4449 grade B500B." in now


def test_remove_all_to_missing_sections(app, signed_in):
    set_id = project(app, signed_in)
    missing = [i["key"] for i in report(app, set_id)["references"] if i["act"]["missing"]]
    assert len(missing) == 3
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "Remove all 3 to missing sections" in page and "Keep all" in page
    signed_in.post(f"/specs/sets/{set_id}/check/remove", data={"key": missing})
    assert not any(i["act"]["missing"] for i in report(app, set_id)["references"])
    assert "Related Requirements:" in texts(app, set_id)


def test_old_accepted_and_rejected_items_still_count_as_settled(app, signed_in):
    set_id = project(app, signed_in)
    keys = [i["key"] for i in report(app, set_id)["references"]]
    from app.db import get_db
    with app.app_context():
        conn = get_db()
        with conn:
            for n, key in enumerate(keys):
                # As a row was written before items were kept, amended or removed.
                conn.execute("INSERT INTO spec_check_settled (set_id, key, state, message, settled_by) "
                             "VALUES (?, ?, ?, '', 'old')", (set_id, key, "accepted" if n % 2 else "rejected"))
    found = report(app, set_id)
    assert found["open"]["references"] == 0
    assert all(i["settled"]["how"] == "kept" for i in found["references"])
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    assert "Kept" in page and "Accepted" not in page and "Rejected" not in page


def test_the_issue_hold_says_keep_amend_or_remove(app, signed_in):
    set_id = project(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Harbour Works", "hold_shown": "1",
                                                  "hold_issue": "1"})
    held = signed_in.get(f"/specs/sets/{set_id}/export")
    assert held.status_code == 302
    assert "keep, amend or remove" in text(signed_in.get(held.headers["Location"]))
