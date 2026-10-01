"""Review, approval and issue control: the team, sign-off, the issue register,
changes since an issue, comments on paragraphs, the history of every change,
and two engineers working on the same project at once."""

from __future__ import annotations

import io
import json
import re
import zipfile

from app import specs
from .test_specs import text
from .test_specs_questions import _project

EDITED = """# PRODUCTS
## CONCRETE MIXTURES
- Class A {{conc_designation@foundations|<insert designation>}}: Normal-weight concrete used for foundations{{conc_class_a_piling|[, piling]}}, grade beams, and tie beams.
-- Minimum Compressive Strength: {{conc_strength@foundations|[45MPa] [40MPa] [35MPa] <Insert strength>}}.
-- Maximum w/cm: {{conc_max_wcm@foundations|[0.35] [0.40] <Insert number>}}.
- Class B {{conc_designation@basement_walls|<insert designation>}}: Normal-weight concrete used for basement walls and cores.
-- Minimum Compressive Strength: {{conc_strength@basement_walls|[45MPa] [40MPa] [35MPa] <Insert strength>}}.
## MEETINGS
- Conduct conference at {{proj_site|[Project site] <Insert location>}}.
- Admixtures: {{conc_admixtures|[water-reducing] [retarding] [air-entraining]}}.
"""


def _person(app, admin, name, password="longenough1"):
    admin.post("/admin/users", data={"username": name.lower(), "password": password, "name": name,
                                     "programs": ["specs"]})
    client = app.test_client()
    client.post("/login", data={"email": name.lower(), "password": password})
    return client


def _user_id(app, name):
    from app.db import query_one

    with app.app_context():
        return query_one("SELECT id FROM users WHERE name = ?", (name,))["id"]


def _row_id(app, set_id):
    from app import specs_store

    with app.app_context():
        return specs_store.set_sections(set_id)[0]["id"]


def _edit(client, set_id, row_id, body=EDITED, **extra):
    return client.post(f"/specs/sets/{set_id}/sections/{row_id}/edit",
                       data={"mode": "text", "text": body, "title": "CAST-IN-PLACE CONCRETE", **extra})


def test_a_team_decides_who_changes_signs_and_issues(app, signed_in):
    set_id = _project(app, signed_in)
    row_id = _row_id(app, set_id)
    sara = _person(app, signed_in, "Sara")
    omar = _person(app, signed_in, "Omar")
    # No team yet: anyone with THEMIS changes it, as before.
    assert "No team listed" in text(signed_in.get(f"/specs/sets/{set_id}"))
    omar.post(f"/specs/sets/{set_id}/details?group=project-information", data={"q_proj_site": "Jeddah"})
    signed_in.post(f"/specs/sets/{set_id}/team", data={
        f"role_{_user_id(app, 'Sara')}": "checker", f"role_{_user_id(app, 'Omar')}": ""})
    page = text(signed_in.get(f"/specs/sets/{set_id}/review"))
    assert "Only the people listed change this project" in page
    # Omar is not on the team: he reads and comments, but his changes are refused.
    answer = omar.post(f"/specs/sets/{set_id}/sections/{row_id}/edit", data={"mode": "text", "text": "# X"})
    assert answer.status_code == 302 and "Only this project" in text(omar.get(f"/specs/sets/{set_id}"))
    assert omar.post(f"/specs/sets/{set_id}/comments", data={"row_id": row_id, "body": "Why 40?"}).status_code == 302
    assert "You can read and comment" in text(omar.get(f"/specs/sets/{set_id}"))
    # Only the lead changes the team, and a checker does not issue.
    sara.post(f"/specs/sets/{set_id}/team", data={f"role_{_user_id(app, 'Omar')}": "lead"})
    from app import specs_review

    with app.app_context():
        assert [m["name"] for m in specs_review.team(set_id)] == ["Sara"]
    sara.post(f"/specs/sets/{set_id}/issues", data={"revision": "A"})
    with app.app_context():
        assert specs_review.issues(set_id) == []
    # My projects lists the ones I am on the team of.
    assert "Tower" in text(sara.get("/specs/")).split("Other people")[0]


def test_sections_are_prepared_checked_and_approved_for_their_words(app, signed_in):
    from app import specs_review, specs_store

    set_id = _project(app, signed_in)
    row_id = _row_id(app, set_id)
    sara = _person(app, signed_in, "Sara")
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "hold_shown": "1",
                                                   "signoff_shown": "1", "need_signoff": "1"})
    signed_in.post(f"/specs/sets/{set_id}/signoff", data={"stage": "prepared", "row_id": row_id})
    # Whoever prepared it does not check it too.
    signed_in.post(f"/specs/sets/{set_id}/signoff", data={"stage": "checked", "row_id": row_id})
    assert "someone else signs it as checked" in text(signed_in.get(f"/specs/sets/{set_id}/review"))
    sara.post(f"/specs/sets/{set_id}/signoff", data={"stage": "approved", "row_id": row_id})
    sara.post(f"/specs/sets/{set_id}/signoff", data={"stage": "checked", "row_id": row_id})
    with app.app_context():
        row = specs_store.spec_set(set_id)
        ready = specs_review.readiness(row)
        assert ready["rows"][0]["standing"] == "checked"
        assert ready["reasons"] == ["1 section not yet approved"]
    # Changing the words asks for the sign-off again.
    _edit(signed_in, set_id, row_id)
    page = text(signed_in.get(f"/specs/sets/{set_id}/sections/{row_id}"))
    assert "changed since" in page and "Sign as prepared" in page
    with app.app_context():
        assert specs_review.readiness(specs_store.spec_set(set_id))["rows"][0]["standing"] == ""
    # So does an answer that changes them.
    signed_in.post(f"/specs/sets/{set_id}/signoff", data={"stage": "prepared", "row_id": row_id})
    sara.post(f"/specs/sets/{set_id}/signoff", data={"stage": "checked", "row_id": row_id})
    sara.post(f"/specs/sets/{set_id}/signoff", data={"stage": "approved", "row_id": row_id})
    with app.app_context():
        assert specs_review.readiness(specs_store.spec_set(set_id))["reasons"] == []
    signed_in.post(f"/specs/sets/{set_id}/details?group=project-information",
                   data={"q_proj_site": "__free__", "t_proj_site": "Riyadh"})
    with app.app_context():
        assert specs_review.readiness(specs_store.spec_set(set_id))["rows"][0]["standing"] == ""
    # A sign-off taken back takes the ones after it.
    signed_in.post(f"/specs/sets/{set_id}/signoff/withdraw", data={"stage": "prepared", "row_id": row_id})
    with app.app_context():
        assert specs_review.signoffs(set_id, {}) == {}


def test_an_issue_is_registered_with_its_files_and_the_next_shows_what_changed(app, signed_in):
    from app import specs_review, specs_store

    set_id = _project(app, signed_in)
    row_id = _row_id(app, set_id)
    # Held for the check: its items still to settle.
    assert "on the check still to keep" in text(signed_in.get(f"/specs/sets/{set_id}/issues"))
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "hold_shown": "1"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/issues"))
    assert 'name="revision" value="0"' in page and "Nothing issued yet" in page
    answer = signed_in.post(f"/specs/sets/{set_id}/issues", data={"responsible": "1",
        "revision": "A", "issue_date": "2026-10-01", "purpose": "For tender", "fmt": "docx"})
    assert answer.status_code == 302
    with app.app_context():
        listed = specs_review.issues(set_id)
        assert [(i["revision"], i["purpose"], i["issue_date"]) for i in listed] == [("A", "For tender", "2026-10-01")]
        row = specs_store.spec_set(set_id)
        assert (row["revision"], row["issue_date"]) == ("A", "2026-10-01")
    got = signed_in.get(f"/specs/sets/{set_id}/issues/{listed[0]['id']}/file")
    assert got.mimetype == "application/zip" and "REV A" in got.headers["Content-Disposition"]
    assert zipfile.ZipFile(io.BytesIO(got.data)).namelist()
    # The same revision twice is refused; the next is suggested.
    signed_in.post(f"/specs/sets/{set_id}/issues", data={"responsible": "1", "revision": "a"})
    with app.app_context():
        assert len(specs_review.issues(set_id)) == 1
    assert 'name="revision" value="B"' in text(signed_in.get(f"/specs/sets/{set_id}/issues"))
    # Changes since Rev A: the reworded paragraph, word by word, and answers.
    _edit(signed_in, set_id, row_id)
    signed_in.post(f"/specs/sets/{set_id}/details?group=project-information",
                   data={"q_proj_site": "__free__", "t_proj_site": "Riyadh"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/changes"))
    assert "Changes since Rev A" in page and "<ins> and cores</ins>" in page
    assert "Where the project site is" in page and "Riyadh" in page
    marked = signed_in.get(f"/specs/sets/{set_id}/changes/docx")
    doc = zipfile.ZipFile(io.BytesIO(marked.data))
    body = zipfile.ZipFile(io.BytesIO(doc.read(doc.namelist()[0]))).read("word/document.xml").decode()
    assert "<w:ins " in body and "Changes since Rev A" in body and "and cores" in body
    # Rev B issued with the changes marked; the register keeps both.
    signed_in.post(f"/specs/sets/{set_id}/issues", data={"responsible": "1", "revision": "B", "fmt": "since",
                                                        "purpose": "__other__", "purpose_other": "For client review"})
    with app.app_context():
        assert [(i["revision"], i["fmt"], i["purpose"]) for i in specs_review.issues(set_id)] == [
            ("B", "since", "For client review"), ("A", "docx", "For tender")]
    assert "No changes" in text(signed_in.get(f"/specs/sets/{set_id}/changes"))


def test_an_issue_waits_for_sign_off_and_closed_comments_when_held(app, signed_in):
    from app import specs_review

    set_id = _project(app, signed_in)
    row_id = _row_id(app, set_id)
    sara = _person(app, signed_in, "Sara")
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "hold_shown": "1", "signoff_shown": "1",
                                                   "need_signoff": "1"})
    signed_in.post(f"/specs/sets/{set_id}/issues", data={"responsible": "1", "revision": "0"})
    with app.app_context():
        assert specs_review.issues(set_id) == []
    assert "not yet approved" in text(signed_in.get(f"/specs/sets/{set_id}/issues"))
    signed_in.post(f"/specs/sets/{set_id}/signoff", data={"stage": "prepared", "row_id": row_id})
    sara.post(f"/specs/sets/{set_id}/signoff", data={"stage": "checked", "row_id": row_id})
    sara.post(f"/specs/sets/{set_id}/signoff", data={"stage": "approved", "row_id": row_id})
    sara.post(f"/specs/sets/{set_id}/comments", data={"row_id": row_id, "body": "Cover to be 50 mm"})
    signed_in.post(f"/specs/sets/{set_id}/issues", data={"responsible": "1", "revision": "0"})
    with app.app_context():
        assert specs_review.issues(set_id) == []
        cid = specs_review.comments(set_id)[0]["id"]
    sara.post(f"/specs/sets/{set_id}/comments/{cid}/close")
    signed_in.post(f"/specs/sets/{set_id}/issues", data={"responsible": "1", "revision": "0"})
    with app.app_context():
        issued = specs_review.issues(set_id)
        assert [i["revision"] for i in issued] == ["0"]
        assert issued[0]["signed"]["checked"] == ["Sara"] == issued[0]["signed"]["approved"]
        assert len(issued[0]["signed"]["prepared"]) == 1


def test_comments_sit_under_their_paragraph_and_are_answered_and_closed(app, signed_in):
    from app import specs, specs_review, specs_store

    set_id = _project(app, signed_in)
    row_id = _row_id(app, set_id)
    omar = _person(app, signed_in, "Omar")
    with app.app_context():
        node = next(n for n in specs.loads(specs_store.set_section(set_id, row_id)["body"])
                    if "basement walls" in n["text"])
    omar.post(f"/specs/sets/{set_id}/comments", data={"row_id": row_id, "node_id": node["id"],
                                                      "body": "Add the cores here?"})
    with app.app_context():
        t = specs_review.comments(set_id)[0]
        assert t["label"] == "1.1.B" and "basement walls" in t["quote"]
    signed_in.post(f"/specs/sets/{set_id}/comments", data={"parent_id": t["id"], "body": "Done in Rev B."})
    page = text(signed_in.get(f"/specs/sets/{set_id}/sections/{row_id}"))
    assert page.index(f'id="p-{node["id"]}"') < page.index("Add the cores here?") < page.index("Done in Rev B.")
    assert "Comments (1 open)" in page and 'data-comment="' in page
    signed_in.post(f"/specs/sets/{set_id}/comments/{t['id']}/close")
    assert "No open comments" in text(signed_in.get(f"/specs/sets/{set_id}/comments"))
    assert "closed by Project Manager" in text(signed_in.get(f"/specs/sets/{set_id}/comments?show=all"))
    # A paragraph that goes keeps its comment, listed under the section.
    assert omar.post(f"/specs/sets/{set_id}/comments", data={"row_id": row_id, "node_id": "nothere1",
                                                             "body": "x"}).status_code == 302
    with app.app_context():
        assert len(specs_review.comments(set_id)) == 1


def test_every_answer_and_paragraph_changed_is_in_the_history(app, signed_in):
    set_id = _project(app, signed_in)
    row_id = _row_id(app, set_id)
    signed_in.post(f"/specs/sets/{set_id}/details?group=project-information",
                   data={"q_proj_site": "__free__", "t_proj_site": "Riyadh"})
    _edit(signed_in, set_id, row_id)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower 2"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/history"))
    assert "Where the project site is" in page and "Riyadh" in page
    assert "1.1.B reworded" in page and "basement walls and cores" in page
    assert "Project name" in page and "Tower 2" in page and "Project Manager" in page
    assert "Added" in page and "033000" in page
    only = text(signed_in.get(f"/specs/sets/{set_id}/history?kind=answer"))
    assert "Riyadh" in only and "reworded" not in only


def test_two_engineers_do_not_save_over_each_other(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in)
    row_id = _row_id(app, set_id)
    sara = _person(app, signed_in, "Sara")
    # Both open the editor; Sara is told the other has it open.
    mine = text(signed_in.get(f"/specs/sets/{set_id}/sections/{row_id}/edit"))
    assert "opened this section in the editor" in text(sara.get(f"/specs/sets/{set_id}/sections/{row_id}/edit"))
    seen = re.search(r'name="seen" value="([0-9a-f]+)"', mine).group(1)
    _edit(sara, set_id, row_id, body=EDITED.replace("and cores", "and lift pits"), seen=seen)
    answer = _edit(signed_in, set_id, row_id, seen=seen)
    page = text(answer)
    assert answer.status_code == 200 and "Sara saved this section" in page and "and cores" in page
    with app.app_context():
        assert "lift pits" in specs_store.set_section(set_id, row_id)["body"]
    # Saving again, having seen hers, puts it in on purpose.
    again = re.search(r'name="seen" value="([0-9a-f]+)"', page).group(1)
    _edit(signed_in, set_id, row_id, seen=again)
    with app.app_context():
        assert "and cores" in specs_store.set_section(set_id, row_id)["body"]
    # The project page opened before a change is not saved over it.
    opened = re.search(r'name="seen" value="([0-9a-f]+)"', text(signed_in.get(f"/specs/sets/{set_id}"))).group(1)
    sara.post(f"/specs/sets/{set_id}", data={"name": "Tower", "client": "NEOM"})
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "client": "", "seen": opened})
    with app.app_context():
        assert specs_store.spec_set(set_id)["client"] == "NEOM"
    # An answer somebody gave after the Details page was opened is kept.
    page = text(signed_in.get(f"/specs/sets/{set_id}/details?group=project-information"))
    was = re.search(r'name="was" value="([^"]*)"', page).group(1).replace("&#34;", '"').replace("&quot;", '"')
    sara.post(f"/specs/sets/{set_id}/details?group=project-information",
              data={"q_proj_site": "__free__", "t_proj_site": "Jeddah"})
    signed_in.post(f"/specs/sets/{set_id}/details?group=project-information",
                   data={"q_proj_site": "Project site", "was": was})
    with app.app_context():
        assert specs_questions.answers_of(specs_store.spec_set(set_id))["proj_site"] == "Jeddah"
