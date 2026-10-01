"""THEMIS suggests and checks; the engineer decides and answers for the issue."""

from __future__ import annotations

from .test_specs import text
from .test_specs_questions import _project

NOTE = "The engineer issuing the specification is responsible for it."


def test_every_working_page_says_the_engineer_is_responsible(app, signed_in):
    set_id = _project(app, signed_in)
    for url in ("/specs/", f"/specs/sets/{set_id}", f"/specs/sets/{set_id}/details",
                f"/specs/sets/{set_id}/check", f"/specs/sets/{set_id}/issues"):
        assert NOTE in text(signed_in.get(url)), url


def test_suggested_answers_are_written_in_only_once_the_engineer_accepts_them(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in)
    url = f"/specs/sets/{set_id}/details?group=project-information"
    page = text(signed_in.get(url))
    assert 'name="accept_suggested"' in page and "written in only when you accept them" in page

    def answers():
        with app.app_context():
            return specs_questions.answers_of(specs_store.spec_set(set_id))

    # Left as suggested and not accepted: nothing is written in, and it says why.
    answer = signed_in.post(url, data={"suggest_shown": "1", "q_proj_site": "Project site"},
                            follow_redirects=True)
    assert "proj_site" not in answers()
    assert "1 suggested answer was not written in" in text(answer)
    # Changed by the engineer: that is their own answer.
    signed_in.post(url, data={"suggest_shown": "1", "q_proj_site": "__free__", "t_proj_site": "Jeddah port"})
    assert answers()["proj_site"] == "Jeddah port"


def test_an_accepted_suggestion_is_written_in(app, signed_in):
    from app import specs_questions, specs_store

    set_id = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}/details?group=project-information",
                   data={"suggest_shown": "1", "accept_suggested": "1", "q_proj_site": "Project site"})
    with app.app_context():
        assert specs_questions.answers_of(specs_store.spec_set(set_id))["proj_site"] == "Project site"


def test_an_issue_needs_the_engineer_to_confirm_the_review(app, signed_in):
    from app import specs_review

    set_id = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "hold_shown": "1"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/issues"))
    assert 'name="responsible"' in page and "I am the engineer responsible" in page
    answer = signed_in.post(f"/specs/sets/{set_id}/issues", data={"revision": "A"}, follow_redirects=True)
    assert "the issue is yours" in text(answer)
    with app.app_context():
        assert specs_review.issues(set_id) == []
    signed_in.post(f"/specs/sets/{set_id}/issues", data={"revision": "A", "responsible": "1"})
    with app.app_context():
        assert [i["revision"] for i in specs_review.issues(set_id)] == ["A"]
