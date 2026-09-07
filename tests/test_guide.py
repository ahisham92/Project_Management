"""How to use this: the definitions, and the helper at the top of every tab.

Both are rendered from one dictionary, so the thing worth testing is that the
dictionary and the app agree — every tab a guide claims to describe exists,
every word a tab points at is defined, and the strip really appears on the page
it belongs to rather than only in the source of truth.
"""

from __future__ import annotations

from app import guide


def text(response) -> str:
    return response.get_data(as_text=True)


# --- the source of truth ----------------------------------------------------

def test_every_tab_names_a_page_that_exists(app):
    """A guide pointing at an endpoint nobody registered is a link that 404s."""
    known = {rule.endpoint for rule in app.url_map.iter_rules()}
    for tab in guide.TABS:
        for endpoint in tab["endpoints"]:
            assert endpoint in known, f"{tab['key']} points at {endpoint}, which does not exist"


def test_every_word_a_tab_points_at_is_defined():
    for tab in guide.TABS:
        for word in tab["terms"]:
            assert word.lower() in guide.TERM_LOOKUP, f"{tab['key']} names {word!r}, undefined"


def test_no_two_tabs_claim_the_same_page():
    """Otherwise which helper you get would depend on the order they are listed."""
    seen: set[str] = set()
    for tab in guide.TABS:
        for endpoint in tab["endpoints"]:
            assert endpoint not in seen, f"{endpoint} is claimed twice"
            seen.add(endpoint)


def test_no_term_is_defined_twice():
    names = [term.lower() for term, _group, _says, _how in guide.TERMS]
    assert len(names) == len(set(names))


def test_every_term_sits_in_a_group_the_page_renders():
    groups = {key for key, _name in guide.GROUPS}
    for term, group, _says, _how in guide.TERMS:
        assert group in groups, f"{term} is in {group!r}, which has no heading"


def test_every_tab_says_what_it_is_and_what_to_do():
    for tab in guide.TABS:
        assert tab["what"] and tab["start_here"]
        assert tab["steps"], f"{tab['key']} has no steps"
        assert tab["watch"], f"{tab['key']} has nothing worth knowing"


def test_a_page_finds_its_own_guide():
    assert guide.for_endpoint("projects.schedule")["key"] == "schedule"
    assert guide.for_endpoint("meetings.week")["key"] == "internal"
    assert guide.for_endpoint("nothing.at.all") is None
    assert guide.for_endpoint(None) is None


# --- searching --------------------------------------------------------------

def test_searching_narrows_to_what_was_asked_for():
    found = guide.grouped("float")
    words = [w["term"] for group in found for w in group["terms"]]
    assert "Float" in words
    assert "Code A" not in words


def test_searching_reads_the_definition_not_only_the_word():
    """Somebody looking up "slack" does not know the app calls it float."""
    words = [w["term"] for group in guide.grouped("slack") for w in group["terms"]]
    assert "Float" in words


def test_an_empty_group_is_dropped_rather_than_shown_empty():
    found = guide.grouped("Code B")
    assert all(group["terms"] for group in found)


def test_nothing_matching_gives_nothing_rather_than_everything():
    assert guide.grouped("qwertyuiop") == []


def test_the_words_for_one_tab_come_back_in_the_order_they_were_named():
    words = guide.terms_for(guide.TAB_BY_KEY["budget"])
    assert [w["term"] for w in words][:3] == ["Budget hours", "Booked hours", "Earned hours"]


# --- the page ---------------------------------------------------------------

def test_the_how_to_use_tab_is_there_and_holds_everything(signed_in):
    body = text(signed_in.get("/projects/1/help"))
    assert "How to use this" in body
    for tab in guide.TABS:
        assert tab["name"] in body
    for term, _group, _says, _how in guide.TERMS:
        assert term in body


def test_it_works_from_outside_a_project_too(signed_in):
    """Somebody who has not opened one yet still needs to know what this is."""
    body = text(signed_in.get("/help"))
    assert "How to use this" in body
    assert "Earned progress" in body


def test_searching_the_page_narrows_it(signed_in):
    body = text(signed_in.get("/projects/1/help?q=revision"))
    assert "Revision" in body
    assert "Man-month" not in body


def test_a_search_that_finds_nothing_says_so(signed_in):
    assert "Nothing matches that" in text(signed_in.get("/projects/1/help?q=qwertyuiop"))


def test_the_tab_is_in_the_bar(signed_in):
    assert "/projects/1/help" in text(signed_in.get("/projects/1/"))


# --- the helper on every tab ------------------------------------------------

def test_each_tab_carries_its_own_helper(signed_in):
    for url, expected in (
        ("/projects/1/", "How to use the Dashboard tab"),
        ("/projects/1/tasks", "How to use the Progress tab"),
        ("/projects/1/schedule", "How to use the Schedule tab"),
        ("/projects/1/budget", "How to use the Budget tab"),
        ("/projects/1/minutes", "How to use the Minutes tab"),
        ("/projects/1/internal", "How to use the Internal tab"),
        ("/projects/1/setup", "How to use the Setup tab"),
        ("/backups", "How to use the Backups tab"),
        ("/", "How to use the Portfolio tab"),
    ):
        assert expected in text(signed_in.get(url)), f"{url} has no helper"


def test_the_helper_starts_folded_away(signed_in):
    """It is reference, not something to read again on every page: the summary
    says which tab it is for, and one click opens it. A <details> the browser
    remembers, so somebody who opens it keeps it open."""
    body = text(signed_in.get("/projects/1/schedule"))
    assert 'data-panel="guide-schedule"' in body
    assert "guide-strip" in body

    strip = body.split('data-panel="guide-schedule"', 1)[1].split(">", 1)[0]
    assert "open" not in strip


def test_the_helper_links_to_the_full_guide(signed_in):
    assert "Every definition, on the How to use tab" in text(signed_in.get("/projects/1/schedule"))


def test_a_page_with_no_guide_simply_has_none(signed_in):
    """The strip is included everywhere; a page nobody wrote an entry for must
    render without it rather than blank."""
    answer = signed_in.get("/account")
    assert answer.status_code == 200
    assert "guide-strip" not in text(answer)


# --- the overview -----------------------------------------------------------

def test_the_dashboard_says_when_the_project_runs(signed_in):
    body = text(signed_in.get("/projects/1/"))
    assert "Overview" in body
    for heading in ("Starts", "Finishes", "Contract date", "Float",
                    "Planned", "Earned", "Variance", "Earned hours"):
        assert ">" + heading + "<" in body


def test_the_project_float_is_the_room_left_against_the_contract_date(app):
    """Not a deliverable's float: every line can have slack while the whole
    thing still finishes late, and that is the number a client asks about."""
    from app.db import query_one
    from app.service import project_overview, project_snapshot

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        overview = project_overview(project, project_snapshot(project, "2026-09-06"))

    assert overview["start"] <= overview["finish"]
    assert overview["contract_end"]
    # The seeded programme runs past its own contract date, and says so.
    assert overview["float_days"] < 0
    assert overview["on_time"] is False


def test_a_programme_finishing_early_has_float_to_spare(app):
    from app.db import execute, query_one
    from app.service import project_overview, project_snapshot

    with app.app_context():
        # Give it years, so every submission lands well inside the contract.
        execute("UPDATE projects SET duration_months = 60 WHERE id = 1")
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        overview = project_overview(project, project_snapshot(project, "2026-09-06"))

    assert overview["float_days"] > 0
    assert overview["on_time"] is True


def test_the_overview_carries_progress_and_earned(app):
    from app.db import query_one
    from app.service import project_overview, project_snapshot

    with app.app_context():
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        snapshot = project_snapshot(project, "2026-09-06")
        overview = project_overview(project, snapshot)

    assert overview["earned"] == snapshot["totals"]["earned_progress"]
    assert overview["planned"] == snapshot["totals"]["planned_progress"]
    assert overview["variance"] == snapshot["totals"]["variance"]
    assert overview["earned_hours"] == snapshot["budget"]["earned_hours"]


def test_a_project_with_no_dated_work_still_reads(app):
    """A brand-new project has no submissions at all; the overview must not
    fall over on it."""
    from app.db import execute, query_one
    from app.service import project_overview, project_snapshot

    with app.app_context():
        execute("DELETE FROM tasks WHERE project_id = 1")
        project = dict(query_one("SELECT * FROM projects WHERE id = 1"))
        overview = project_overview(project, project_snapshot(project, "2026-09-06"))

    assert overview["finish"] == ""
    assert overview["float_days"] == 0
    assert overview["start"]
