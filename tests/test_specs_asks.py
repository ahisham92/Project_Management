"""Questions handed to a team before the IDC: the structural engineer asks the
materials team for one answer, the team answers it with the question's own
buttons, and nothing is written in until the structural engineer accepts it."""

from __future__ import annotations

from .test_specs import text
from .test_specs_idc import _as
from .test_specs_questions import _project as _questions_project
from .test_specs_review import _person, _user_id


def _project(app, signed_in):
    one = _questions_project(app, signed_in)
    _person(app, signed_in, "Layla")
    return one, None, None, _user_id(app, "Layla")


def _question(app, set_id):
    from app import specs_store
    from app.views.specs_views import _asked
    with app.test_request_context():
        row = specs_store.spec_set(set_id)
        return next(q for q in _asked(set_id, row) if not q.get("switch") and not q.get("place"))


def _materials(app, signed_in, name="Omar"):
    _person(app, signed_in, name)
    user = _user_id(app, name)
    signed_in.post(f"/admin/users/{user}", data={"username": name.lower(), "name": name, "programs": ["specs"],
                                                 "themis_trade": "geotechnical", "themis_team": "materials"})
    return user


def test_a_question_asked_of_the_materials_team_is_answered_and_accepted_by_the_owner(app, signed_in):
    from app import specs_asks, specs_questions, specs_store

    one, _geo, _row, _layla = _project(app, signed_in)
    omar = _materials(app, signed_in)
    with app.app_context():
        assert specs_asks.of_user(__import__("app.db", fromlist=["x"]).query_one("SELECT * FROM users WHERE id = ?", (omar,))) == "materials"
    q = _question(app, one)
    key = q["key"]
    assert "Ask a team" in text(signed_in.get(f"/specs/sets/{one}/details"))
    page = text(signed_in.get(f"/specs/sets/{one}/ask/{key}"))
    assert "Materials team" in page and "Marine unit" in page and "Omar" in page
    signed_in.post(f"/specs/sets/{one}/ask/{key}", data={"team": "materials", "note": "Sabkha: what cement?"})
    with app.app_context():
        a = specs_asks.of_set(one, live=True)[0]
    assert a["state"] == "asked" and a["qkey"] == key
    # Asked once at a time.
    signed_in.post(f"/specs/sets/{one}/ask/{key}", data={"team": "marine"})
    with app.app_context():
        assert len(specs_asks.of_set(one)) == 1
    assert "Waiting for the Materials team" in text(signed_in.get(f"/specs/sets/{one}/ask/{key}"))
    assert "waiting on Materials team" in text(signed_in.get(f"/specs/sets/{one}"))
    with signed_in.session_transaction() as s:
        admin_id = s["user_id"]
    # The owner cannot answer for the team.
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/answer", data={f"q_{key}": "__free__", f"t_{key}": "x"})
    with app.app_context():
        assert specs_asks.ask(a["id"])["state"] == "asked"
    # Omar sees it on his start page and answers it.
    _as(app, signed_in, omar)
    assert "Sabkha: what cement?" in text(signed_in.get("/specs/"))
    assert "Send the answer" in text(signed_in.get(f"/specs/sets/{one}/ask/{key}"))
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/answer", data={
        f"q_{key}": specs_questions.FREE, f"t_{key}": "Sulfate resisting, 60 years", "why": "BS 8500 DS-4"})
    with app.app_context():
        a = specs_asks.ask(a["id"])
        assert a["state"] == "answered" and a["given"][key] == "Sulfate resisting, 60 years"
        assert specs_questions.answers_of(specs_store.spec_set(one)).get(key) != "Sulfate resisting, 60 years"
    # He cannot accept his own answer.
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/decide", data={"how": "accept"})
    with app.app_context():
        assert specs_asks.ask(a["id"])["state"] == "answered"
    # The owner sends it back with a note, Omar answers again, the owner accepts.
    _as(app, signed_in, admin_id)
    assert "Team answers to accept" in text(signed_in.get("/specs/"))
    assert "team answer" in text(signed_in.get(f"/specs/sets/{one}"))
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/decide", data={"how": "back", "why": ""})
    with app.app_context():
        assert specs_asks.ask(a["id"])["state"] == "answered"       # sending back says why
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/decide", data={"how": "back", "why": "Give the class too"})
    _as(app, signed_in, omar)
    assert "Give the class too" in text(signed_in.get("/specs/"))
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/answer", data={
        f"q_{key}": specs_questions.FREE, f"t_{key}": "Sulfate resisting, DC-4", "why": "BS 8500"})
    _as(app, signed_in, admin_id)
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/decide", data={"how": "accept"})
    with app.app_context():
        assert specs_asks.ask(a["id"])["state"] == "accepted"
        assert specs_questions.answers_of(specs_store.spec_set(one))[key] == "Sulfate resisting, DC-4"
        from app.db import query
        said = [r["what"] for r in query("SELECT what FROM spec_history WHERE set_id = ?", (one,))]
    assert "Asked the Materials team" in said and "Materials team answered" in said
    assert "Accepted" in text(signed_in.get(f"/specs/sets/{one}/asks"))


def test_the_owner_takes_a_question_back_and_only_team_members_answer(app, signed_in):
    from app import specs_asks

    one, _geo, _row, layla = _project(app, signed_in)
    q = _question(app, one)
    signed_in.post(f"/specs/sets/{one}/ask/{q['key']}", data={"team": "marine"})
    with app.app_context():
        a = specs_asks.of_set(one, live=True)[0]
    # Layla is geotechnical but in no team: she cannot answer for the marine unit.
    _as(app, signed_in, layla)
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/answer", data={f"q_{q['key']}": "__free__",
                                                                     f"t_{q['key']}": "x"})
    with app.app_context():
        assert specs_asks.ask(a["id"])["state"] == "asked"
        from app.db import query_one
        admin = query_one("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")["id"]
    _as(app, signed_in, admin)
    signed_in.post(f"/specs/sets/{one}/asks/{a['id']}/decide", data={"how": "withdraw"})
    with app.app_context():
        assert specs_asks.ask(a["id"])["state"] == "withdrawn" and not specs_asks.of_set(one, live=True)
    assert "Ask a team" in text(signed_in.get(f"/specs/sets/{one}/ask/{q['key']}"))
