"""What the office keeps from what it issues: each issue with its project's
data, issues compared across projects, amendments gathered for the MTD, and the
standards register."""

from __future__ import annotations

import io

from .test_specs import text
from .test_specs_kinds import set_id_of
from .test_specs_questions import _project
from .test_specs_review import _edit, _row_id


def _two_projects(app, signed_in):
    """Jeddah, with one paragraph amended, and Lagos as the master has it."""
    from app import specs_store

    jeddah = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{jeddah}", data={"name": "Jeddah Tower", "hold_shown": "1",
                                                  "proj_location": "Jeddah, Saudi Arabia"})
    _edit(signed_in, jeddah, _row_id(app, jeddah))
    signed_in.post(f"/specs/sets/{jeddah}/details?group=project-information",
                   data={"q_proj_site": "__free__", "t_proj_site": "Jeddah port"})
    lagos = set_id_of(signed_in.post("/specs/sets", data={"name": "Lagos Quay", "family": "15A"}))
    with app.app_context():
        section_id = specs_store.section_by_number("033000", "15A")["id"]
    signed_in.post(f"/specs/sets/{lagos}/sections", data={"section_id": [str(section_id)]})
    signed_in.post(f"/specs/sets/{lagos}", data={"name": "Lagos Quay", "hold_shown": "1",
                                                 "proj_location": "Lagos, Nigeria"})
    for set_id in (jeddah, lagos):
        signed_in.post(f"/specs/sets/{set_id}/issues", data={
            "revision": "A", "responsible": "1", "open_ok": "1", "issue_date": "2026-10-01", "purpose": "For tender"})
    return jeddah, lagos


def test_each_issue_is_kept_with_its_projects_data_even_once_the_project_goes(app, signed_in):
    from app import specs_issued

    jeddah, lagos = _two_projects(app, signed_in)
    page = text(signed_in.get("/specs/issued"))
    assert "Jeddah Tower" in page and "Jeddah, Saudi Arabia" in page and "Lagos, Nigeria" in page
    with app.app_context():
        kept = {r["name"]: specs_issued.record(r["id"]) for r in specs_issued.records()}
    data = kept["Jeddah Tower"]["snapshot"]["data"]
    assert data["location"] == "Jeddah, Saudi Arabia" and data["family"] == "15A"
    amended = kept["Jeddah Tower"]["snapshot"]["amendments"][0]["items"]
    assert [(i["state"], "and cores" in i["text"]) for i in amended] == [("changed", True)]
    assert kept["Lagos Quay"]["snapshot"]["amendments"] == []
    # The project deleted: its issue stays on record.
    signed_in.post(f"/specs/sets/{jeddah}/delete")
    page = text(signed_in.get("/specs/issued"))
    assert "Jeddah Tower" in page and "project deleted" in page


def test_two_issues_from_different_projects_are_compared(app, signed_in):
    from app import specs_issued

    _two_projects(app, signed_in)
    with app.app_context():
        ids = {r["name"]: r["id"] for r in specs_issued.records()}
    page = text(signed_in.get(f"/specs/issued/compare?a={ids['Lagos Quay']}&b={ids['Jeddah Tower']}"))
    assert "Lagos, Nigeria" in page and "Jeddah, Saudi Arabia" in page
    assert "<ins> and cores</ins>" in page
    answers = text(signed_in.get("/specs/issued/answers"))
    assert "Jeddah Tower" in answers and "Lagos Quay" in answers and "Jeddah port" in answers
    got = signed_in.get("/specs/issued/answers?format=csv")
    assert got.mimetype == "text/csv" and "Jeddah Tower" in got.get_data(as_text=True)


def test_an_admin_writes_a_projects_amendment_into_the_mtd(app, signed_in):
    from app import specs, specs_store

    _two_projects(app, signed_in)
    page = text(signed_in.get("/specs/library/amendments"))
    assert "Jeddah Tower" in page and "Write into the MTD" in page and "and cores" in page
    with app.app_context():
        master = specs_store.section_by_number("033000", "15A")
        node = next(n for n in specs.loads(master["body"]) if "basement walls" in n["text"])
    form = {"family": "15A", "number": "033000", "node_id": node["id"]}
    jeddah = next(r for r in _records(app) if r["name"] == "Jeddah Tower")
    answer = signed_in.post("/specs/library/amendments/adopt", data={
        **form, "set_id": jeddah["set_id"], "record_id": jeddah["id"]}, follow_redirects=True)
    assert "Written into the MTD" in text(answer)
    with app.app_context():
        now = specs_store.section_by_number("033000", "15A")
        assert now["version"] == master["version"] + 1
        assert any("basement walls and cores" in n["text"] for n in specs.loads(now["body"]))
    # Nothing left to decide; shown as in the MTD when asked.
    assert "Nothing to decide" in text(signed_in.get("/specs/library/amendments"))
    assert "the MTD says this now" in text(signed_in.get("/specs/library/amendments?decided=1"))


def _records(app):
    from app import specs_issued

    with app.app_context():
        return specs_issued.records()


def test_an_amendment_kept_out_of_the_mtd_can_be_decided_again(app, signed_in):
    from app import specs, specs_store

    _two_projects(app, signed_in)
    jeddah = next(r for r in _records(app) if r["name"] == "Jeddah Tower")
    with app.app_context():
        master = specs_store.section_by_number("033000", "15A")
        node = next(n for n in specs.loads(master["body"]) if "basement walls" in n["text"])
    form = {"family": "15A", "number": "033000", "node_id": node["id"], "set_id": jeddah["set_id"],
            "record_id": jeddah["id"]}
    signed_in.post("/specs/library/amendments/keep", data={**form, "note": "Client-specific"})
    assert "Nothing to decide" in text(signed_in.get("/specs/library/amendments"))
    assert "Client-specific" in text(signed_in.get("/specs/library/amendments?decided=1"))
    signed_in.post("/specs/library/amendments/reopen", data=form)
    assert "Write into the MTD" in text(signed_in.get("/specs/library/amendments"))
    with app.app_context():
        assert specs_store.section_by_number("033000", "15A")["version"] == master["version"]


def test_only_an_admin_sees_the_amendments_for_the_mtd(app, signed_in):
    from .test_specs_review import _person

    sara = _person(app, signed_in, "Sara")
    answer = sara.get("/specs/library/amendments", follow_redirects=True)
    assert "Only an administrator reviews amendments" in text(answer)
    assert sara.post("/specs/library/amendments/adopt", data={}).status_code == 302


def test_the_standards_register_takes_a_check_and_the_checker_flags_older_editions(app, signed_in):
    from app import specs, specs_store

    with app.app_context():
        specs_store.save_section("033100", "CONCRETE TESTING", specs.align([], specs.from_text(
            "# GENERAL\n## REFERENCES\n- Concrete to ACI 318-19 and cement to ASTM C150/C150M-20.\n"
            "- Old practice to BS 8110-1:1997.\n")), family="15A")
    page = text(signed_in.get("/specs/standards/register?show=all"))
    assert "ACI 318" in page and "Not checked" in page
    listed = signed_in.get("/specs/standards/register.csv").get_data(as_text=True)
    assert listed.startswith("standard,current,status") and "ACI 318" in listed
    check = ("standard,current,status,replaced_by,source,checked,note\n"
             "ACI 318,ACI 318-25,current,,https://www.concrete.org/,2026-10-01,\n"
             "ASTM C150/C150M,ASTM C150/C150M-20,current,,https://www.astm.org/,2026-10-01,\n"
             "BS 8110-1,,withdrawn,BS EN 1992-1-1,https://knowledge.bsigroup.com/,2026-10-01,\n"
             "ASTM C33,,unknown,,,2026-10-01,\n")
    preview = text(signed_in.post("/specs/standards/register/load", data={
        "file": (io.BytesIO(check.encode()), "check.csv")}, content_type="multipart/form-data"))
    assert "Citations of the 2019 edition will be flagged, with ACI 318-25 offered" in preview
    assert "flagged as withdrawn, with BS EN 1992-1-1 offered" in preview
    import json
    import re
    rows = re.search(r'name="rows" value="([^"]*)"', preview).group(1)
    rows = json.loads(rows.replace("&#34;", '"').replace("&quot;", '"').replace("&amp;", "&")
                      .replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">"))
    signed_in.post("/specs/standards/register/apply", data={
        "rows": json.dumps(rows), "take": ["ACI318", "BS8110-1", "ASTMC150", "ASTMC33"]})
    page = text(signed_in.get("/specs/standards/register?show=all"))
    assert "Older edition cited: 2019" in page and "Withdrawn" in page and "Up to date" in page
    with app.app_context():
        gone = [w for w in specs_store.withdrawn() if w["note"].startswith("From the standards register")]
        assert sorted((w["old"], w["new"]) for w in gone) == [
            ("ACI 318:2024", "ACI 318-25"), ("ASTM C150/C150M:2019", "ASTM C150/C150M-20"),
            ("BS 8110-1", "BS EN 1992-1-1")]
    # Checked again later: the register's own rows are replaced, not added to.
    signed_in.post("/specs/standards/register/one", data={"key": "ACI318", "standard": "ACI 318",
                                                          "current": "ACI 318-19", "status": "current"})
    with app.app_context():
        gone = [w for w in specs_store.withdrawn() if w["note"].startswith("From the standards register")
                and w["old"].startswith("ACI")]
        assert [(w["old"], w["new"]) for w in gone] == [("ACI 318:2018", "ACI 318-19")]
    assert "Up to date" in text(signed_in.get("/specs/standards/register?show=all"))
