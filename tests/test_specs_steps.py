"""A project's page, one step at a time, and sections added by mistake taken
back out of it."""

from __future__ import annotations

import re

from .test_specs import text
from .test_specs_kinds import applies, load, set_id_of


def _two_sections(app, signed_in) -> int:
    load(signed_in, "STD15A_SPC_033000_ST_Concrete.docx", "# GENERAL\n## SUMMARY\n- Concrete.\n",
         "033000", "CAST-IN-PLACE CONCRETE")
    load(signed_in, "STD15A_SPC_034100_ST_Precast.docx", "# GENERAL\n## SUMMARY\n- Precast.\n",
         "034100", "PRECAST STRUCTURAL CONCRETE")
    applies(app, "034100", "15A", "shotcrete=Yes")
    return set_id_of(signed_in.post("/specs/sets", data={"name": "Quay", "family": "15A"}))


def test_the_page_is_a_set_of_steps_that_work_without_the_script(app, signed_in):
    set_id = _two_sections(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    # The wrapper the script marks; a new project (no sections yet) opens on its first step.
    assert 'data-spec-flow data-first="project"' in page
    assert "spec-steps.js" in page and "spec-steps.css" in page
    # Nothing is hidden by the page itself: every step is in it, each one named.
    for step in ("project", "elements", "questions", "sections"):
        assert f'data-step="{step}"' in page
        assert f'data-step-link="{step}"' in page
        assert f'id="step-{step}"' in page
    assert "spec-flow-js" not in page.split("<script", 1)[0]
    # Back from each step after the first.
    assert 'href="#step-project">← Back' in page and 'href="#step-questions">← Back' in page
    # With no sections yet, nothing to take out.
    assert 'id="sections-remove"' not in page


def test_ticked_sections_come_out_together(app, signed_in):
    from app import specs_store

    set_id = _two_sections(app, signed_in)
    with app.app_context():
        ids = [specs_store.section_by_number(n, "15A")["id"] for n in ("033000", "034100")]
    signed_in.post(f"/specs/sets/{set_id}/sections", data={"section_id": [str(i) for i in ids]})
    with app.app_context():
        rows = [r["id"] for r in specs_store.set_sections(set_id)]
    assert len(rows) == 2

    page = text(signed_in.get(f"/specs/sets/{set_id}"))
    # Its own form, outside the one that saves the answers, with a tick a row
    # that joins it by its id, and a tick-all in the header.
    assert f'action="/specs/sets/{set_id}/sections/remove" id="sections-remove"' in page
    choices = page.index('id="step-choices"')
    assert page.index('id="sections-remove"') > page.index("</form>", choices)
    ticks = re.findall(r'<input type="checkbox" name="row_id" value="(\d+)" form="sections-remove"', page)
    assert sorted(int(t) for t in ticks) == sorted(rows)
    assert "data-tick-all" in page and "Take the ticked out" in page
    assert page.count('data-take-one="') == 2
    # With sections in and elements ticked, it opens on Sections.
    assert 'data-first="sections"' in page

    answer = text(signed_in.post(f"/specs/sets/{set_id}/sections/remove",
                                 data={"row_id": [str(r) for r in rows]}, follow_redirects=True))
    assert "Took 2 sections out: 033000, 034100" in answer
    with app.app_context():
        assert specs_store.set_sections(set_id) == []


def test_other_pages_link_to_the_sections_step(app, signed_in):
    set_id = _two_sections(app, signed_in)
    answer = signed_in.post(f"/specs/sets/{set_id}/sections/remove", data={})
    assert answer.headers["Location"].endswith(f"/specs/sets/{set_id}#step-sections")
