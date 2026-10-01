"""Packages of one project: each specification is its owner's to change, the
others read and copy it, and a package is checked against what the project's
other packages issued, each difference accepted or kept."""

from __future__ import annotations

from .test_specs import text
from .test_specs_kinds import set_id_of
from .test_specs_review import _edit, _person, _row_id, _user_id
from .test_specs_questions import _project


def _issue(client, set_id, revision="A"):
    return client.post(f"/specs/sets/{set_id}/issues", data={
        "revision": revision, "responsible": "1", "issue_date": "2026-10-01", "purpose": "For tender"})


def _packages(app, signed_in):
    """Package 1, amended and issued by its owner; package 2 started by Sara
    from the library with the master's words and another answer."""
    from app import specs_store

    one = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{one}", data={"name": "Jeddah Tower", "code": "P100",
                                               "package": "Package 1", "hold_shown": "1"})
    _edit(signed_in, one, _row_id(app, one))
    signed_in.post(f"/specs/sets/{one}/details?group=project-information",
                   data={"q_proj_site": "__free__", "t_proj_site": "Jeddah port"})
    _issue(signed_in, one)
    sara = _person(app, signed_in, "Sara")
    two = set_id_of(sara.post("/specs/sets", data={"name": "Jeddah Tower", "code": "p 100",
                                                   "package": "Package 2", "family": "15A"}))
    with app.app_context():
        section_id = specs_store.section_by_number("033000", "15A")["id"]
    sara.post(f"/specs/sets/{two}/sections", data={"section_id": [str(section_id)]})
    sara.post(f"/specs/sets/{two}/details?group=project-information",
              data={"q_proj_site": "__free__", "t_proj_site": "Jeddah north port"})
    return one, two, sara


def test_a_specification_is_changed_only_by_its_owner_and_the_people_they_add(app, signed_in):
    from app import specs_store

    one, two, sara = _packages(app, signed_in)
    row_id = _row_id(app, one)
    # Sara reads package 1 and what it issued, but cannot change it.
    page = text(sara.get(f"/specs/sets/{one}"))
    assert "You can read this specification" in page and "start a package from it" in page
    with app.app_context():
        before = specs_store.set_section(one, row_id)["body"]
    sara.post(f"/specs/sets/{one}/sections/{row_id}/edit",
              data={"mode": "text", "text": "# X", "title": "CAST-IN-PLACE CONCRETE"})
    with app.app_context():
        assert specs_store.set_section(one, row_id)["body"] == before
        issue_id = __import__("app.specs_review", fromlist=["x"]).last_issue(one)["id"]
    assert sara.get(f"/specs/sets/{one}/issues/{issue_id}/file").status_code == 200
    # Starting a package from it: the form comes filled with the project.
    form = text(sara.get(f"/specs/?start_from={one}&package=1"))
    assert 'value="P100"' in form and 'value="Jeddah Tower"' in form
    # Sara's own package is hers: Omar, not on its team, is refused until she adds him.
    omar = _person(app, signed_in, "Omar")
    two_row = _row_id(app, two)
    omar.post(f"/specs/sets/{two}/sections/{two_row}/edit",
              data={"mode": "text", "text": "# X", "title": "CAST-IN-PLACE CONCRETE"})
    with app.app_context():
        assert "# X" not in specs_store.set_section(two, two_row)["body"]
    sara.post(f"/specs/sets/{two}/team", data={f"role_{_user_id(app, 'Omar')}": "editor"})
    omar.post(f"/specs/sets/{two}", data={"name": "Jeddah Tower", "package": "Package 2 (piling)"})
    with app.app_context():
        assert specs_store.spec_set(two)["package"] == "Package 2 (piling)"


def test_a_package_is_checked_against_what_the_others_issued(app, signed_in):
    from app import specs_packages, specs_questions, specs_store

    one, two, sara = _packages(app, signed_in)
    page = text(sara.get(f"/specs/sets/{two}"))
    assert "differences from the project&#39;s other issued packages" in page or \
        "differences from the project's other issued packages" in page
    assert "to decide" in text(sara.get("/specs/"))
    page = text(sara.get(f"/specs/sets/{two}/packages"))
    assert "Package 1" in page and "spec-pkg-red" in page and "and cores" in page
    assert "Jeddah north port" in page and "Jeddah port" in page
    with app.app_context():
        found = specs_packages.discrepancies(specs_store.spec_set(two))
    assert found["key"] == "P100" and found["open"] == 2
    peer = found["against"][0]
    paragraph = peer["sections"][0]["items"][0]
    assert paragraph["state"] == "changed" and "and cores" in paragraph["theirs"]
    # Accept package 1's wording: package 2 now says it too.
    sara.post(f"/specs/sets/{two}/packages/accept", data={
        "peer": one, "kind": "text", "number": "033000", "key": paragraph["key"]})
    with app.app_context():
        assert "and cores" in specs_store.set_section(two, _row_id(app, two))["body"]
    # Keep our own answer, with the reason; nothing is left to decide.
    sara.post(f"/specs/sets/{two}/packages/keep", data={
        "peer": one, "kind": "answer", "number": "", "key": "proj_site", "note": "North quay"})
    with app.app_context():
        row = specs_store.spec_set(two)
        assert specs_questions.answers_of(row)["proj_site"] == "Jeddah north port"
        assert specs_packages.open_count(row) == 0
    assert "differences from the project" not in text(sara.get(f"/specs/sets/{two}"))
    # Package 1 issues again with another answer: the decision was for the
    # old wording, so the difference is flagged again.
    signed_in.post(f"/specs/sets/{one}/details?group=project-information",
                   data={"q_proj_site": "__free__", "t_proj_site": "King Abdullah port"})
    _issue(signed_in, one, "B")
    with app.app_context():
        assert specs_packages.open_count(specs_store.spec_set(two)) == 1
    # Package 1 is checked against package 2 once package 2 issues.
    sara.post(f"/specs/sets/{two}", data={"name": "Jeddah Tower", "hold_shown": "1"})
    _issue(sara, two)
    with app.app_context():
        found = specs_packages.discrepancies(specs_store.spec_set(one))
    assert [i["key"] for i in found["against"][0]["answers"]] == ["proj_site"]


def test_only_the_package_team_decides_its_differences(app, signed_in):
    from app import specs_packages, specs_store

    one, two, sara = _packages(app, signed_in)
    omar = _person(app, signed_in, "Omar")
    omar.post(f"/specs/sets/{two}/packages/keep", data={
        "peer": one, "kind": "answer", "number": "", "key": "proj_site", "note": "mine"})
    with app.app_context():
        assert specs_packages.open_count(specs_store.spec_set(two)) == 2
    page = text(omar.get(f"/specs/sets/{two}/packages"))
    assert "Package 1" in page and "Accept Package 1" not in page
