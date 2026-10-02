"""Each engineer sees their own trade's specifications; an administrator sees
every one. Another trade's specification opens only for the IDC sent to them,
or for a question asked of their team."""

from __future__ import annotations

from .test_specs import text
from .test_specs_idc import _as, _project
from .test_specs_review import _person, _user_id


def _engineer(app, client, name, trade, team=""):
    _person(app, client, name)
    user = _user_id(app, name)
    client.post(f"/admin/users/{user}", data={"username": name.lower(), "name": name, "programs": ["specs"],
                                              "themis_trade": trade, "themis_team": team})
    return user


def test_an_engineer_sees_only_their_own_trades_specifications(app, signed_in):
    one, geo, _row, layla = _project(app, signed_in)
    sami = _engineer(app, signed_in, "Sami", "structures")
    nobody = _engineer(app, signed_in, "Nour", "")
    with signed_in.session_transaction() as s:
        admin = s["user_id"]
    # The administrator sees both.
    page = text(signed_in.get("/specs/"))
    assert f"/specs/sets/{one}\"" in page and f"/specs/sets/{geo}\"" in page
    assert signed_in.get(f"/specs/sets/{geo}").status_code == 200
    # Layla, geotechnical: her own, not the structural one, nor its files.
    _as(app, signed_in, layla)
    page = text(signed_in.get("/specs/"))
    assert f"/specs/sets/{geo}\"" in page and f"href=\"/specs/sets/{one}\"" not in page
    assert signed_in.get(f"/specs/sets/{geo}").status_code == 200
    for path in (f"/specs/sets/{one}", f"/specs/sets/{one}/story", f"/specs/sets/{one}/export",
                 f"/specs/sets/{one}/themis", f"/specs/sets/{one}/check"):
        answer = signed_in.get(path)
        assert answer.status_code == 302 and answer.headers["Location"].endswith("/specs/"), path
    # The structural tab shows on her project, as another trade's, not a link.
    page = text(signed_in.get(f"/specs/sets/{geo}"))
    assert "is-closed" in page and f"href=\"/specs/sets/{one}\"" not in page
    # Sami, structures: the other way round.
    _as(app, signed_in, sami)
    assert signed_in.get(f"/specs/sets/{one}").status_code == 200
    assert signed_in.get(f"/specs/sets/{geo}").status_code == 302
    # An account with no trade yet sees every one, as before trades.
    _as(app, signed_in, nobody)
    assert signed_in.get(f"/specs/sets/{geo}").status_code == 200
    assert signed_in.get(f"/specs/sets/{one}").status_code == 200
    # Put on the structural team by its lead, Layla sees it.
    _as(app, signed_in, admin)
    signed_in.post(f"/specs/sets/{one}/team", data={f"role_{layla}": "checker"})
    _as(app, signed_in, layla)
    assert signed_in.get(f"/specs/sets/{one}").status_code == 200


def test_another_trades_specification_opens_for_its_idc_and_for_a_team_ask(app, signed_in):
    from app import specs_asks, specs_store
    from app.views.specs_views import _asked

    one, _geo, row_id, layla = _project(app, signed_in)
    omar = _engineer(app, signed_in, "Omar", "geotechnical", "materials")
    _as(app, signed_in, layla)
    assert signed_in.get(f"/specs/sets/{one}/idc").status_code == 302
    # Sent to geotechnical, the IDC opens for her; the specification's own pages do not.
    with signed_in.session_transaction():
        pass
    from app.db import query_one
    with app.app_context():
        admin = query_one("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")["id"]
    _as(app, signed_in, admin)
    signed_in.post(f"/specs/sets/{one}/idc", data={"trade": ["geotechnical"]})
    _as(app, signed_in, layla)
    assert signed_in.get(f"/specs/sets/{one}/idc").status_code == 200
    assert signed_in.get(f"/specs/sets/{one}/idc/{row_id}").status_code == 200
    assert signed_in.get(f"/specs/sets/{one}").status_code == 302
    # A question asked of the materials team opens for Omar, and he answers it.
    with app.test_request_context():
        q = next((x for x in _asked(one, specs_store.spec_set(one)) if not x.get("switch")), None)
    if q is None:
        return
    _as(app, signed_in, admin)
    signed_in.post(f"/specs/sets/{one}/ask/{q['key']}", data={"team": "materials"})
    _as(app, signed_in, omar)
    assert signed_in.get(f"/specs/sets/{one}/ask/{q['key']}").status_code == 200
    assert signed_in.get(f"/specs/sets/{one}").status_code == 302
    with app.app_context():
        assert specs_asks.of_set(one, live=True)


def test_only_a_trades_own_engineers_write_sign_and_issue_its_specification(app, signed_in):
    from app import specs_review, specs_store
    from app.db import query_one

    one, geo, _row, layla = _project(app, signed_in)
    sami = _engineer(app, signed_in, "Sami", "structures")
    with app.app_context():
        structural, geotechnical = specs_store.spec_set(one), specs_store.spec_set(geo)
        user = lambda i: query_one("SELECT * FROM users WHERE id = ?", (i,))  # noqa: E731
        admin = query_one("SELECT * FROM users WHERE role = 'admin' ORDER BY id LIMIT 1")
        # Even on the structural team, Layla reads it but does not sign or issue it.
        from app.db import execute
        execute("INSERT INTO spec_set_members (set_id, user_id, role) VALUES (?, ?, 'lead')", (one, layla))
        execute("INSERT INTO spec_set_members (set_id, user_id, role) VALUES (?, ?, 'lead')", (geo, sami))
        for what in ("edit", "prepared", "checked", "approved", "issue"):
            assert not specs_review.may(structural, user(layla), what)
            assert not specs_review.may(geotechnical, user(sami), what)
            assert specs_review.may(geotechnical, user(layla), what)
            assert specs_review.may(structural, admin, what) and specs_review.may(geotechnical, admin, what)
    _as(app, signed_in, sami)
    signed_in.post(f"/specs/sets/{geo}", data={"name": "Renamed by structures"})
    with app.app_context():
        assert specs_store.spec_set(geo)["name"] != "Renamed by structures"
