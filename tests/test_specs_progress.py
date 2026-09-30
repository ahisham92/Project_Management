"""Progress as things load: the library file read in a few sections at a
time, forms and downloads answered for spec-progress.js, and the check shown
one group at a time."""

from __future__ import annotations

import io
import os
import re
import time

from .test_specs import text
from .test_specs_check_actions import project
from .test_specs_kinds import load

PROGRESS = {"X-Specs-Progress": "1"}

BODY = """\
# GENERAL
## SUMMARY
- Section includes the work of this section.
# PRODUCTS
## MATERIALS
- Bars: BS 4449 grade B500B.
"""

SECTIONS = [("SPC-031000.docx", "031000", "CONCRETE FORMING"),
            ("SPC-032000.docx", "032000", "CONCRETE REINFORCING"),
            ("SPC-033000.docx", "033000", "CAST-IN-PLACE CONCRETE"),
            ("SPC-034500.docx", "034500", "PRECAST ARCHITECTURAL CONCRETE")]


def library_of(signed_in, sections=SECTIONS) -> bytes:
    for filename, number, title in sections:
        load(signed_in, filename, BODY.replace("work of this section", f"work of {title.lower()}"),
             number, title)
    return signed_in.get("/specs/library/file").data


def state(app) -> list[tuple]:
    from app import specs_store

    with app.app_context():
        return sorted((s["family"], s["number"], s["title"], s["body"], s.get("applies") or "")
                      for s in (specs_store.section(r["id"]) for r in specs_store.library()))


def clear(app) -> None:
    from app import specs_store

    with app.app_context():
        specs_store.delete_sections(s["id"] for s in specs_store.library())


def pending(app) -> set[str]:
    from app import specs_store

    with app.app_context():
        return {p.name for p in specs_store._loads_dir().iterdir()}


def stepped(signed_in, data: bytes, mode="update", sure=None, filename="lib.zip"):
    """The library file loaded as the page's script does it: its answers, in order."""
    form = {"library": (io.BytesIO(data), filename), "mode": mode, "family": ""}
    if sure:
        form["sure"] = sure
    begun = signed_in.post("/specs/library/file/begin", data=form, content_type="multipart/form-data",
                           headers=PROGRESS)
    answers = [begun.get_json()]
    while "go" not in answers[-1]:
        answers.append(signed_in.post(answers[0]["step"], headers=PROGRESS).get_json())
        assert len(answers) < 50
    return answers


# --- the library file, a few sections at a time --------------------------------------

def test_a_stepped_load_ends_as_the_one_call_load(app, signed_in):
    data = library_of(signed_in)
    before = state(app)
    assert len(before) == 4

    clear(app)
    answers = stepped(signed_in, data)
    assert answers[0]["total"] == 4 and answers[0]["done"] == 0
    assert answers[-1]["done"] == answers[-1]["total"] == 4 and answers[-1]["finished"]
    page = text(signed_in.get(answers[-1]["go"]))
    assert "Read lib.zip: 4 new sections" in page
    stepped_state = state(app)
    assert stepped_state == before
    assert not [n for n in pending(app) if not n.endswith(".tmp")]

    # The same file in one call (as without JavaScript) leaves the same library.
    clear(app)
    from app import specs_store

    with app.app_context():
        counted = specs_store.unpack(data)
    assert state(app) == stepped_state
    assert counted["added"] == 4


def test_each_step_says_how_far_it_has_got(app, signed_in):
    data = library_of(signed_in)
    clear(app)
    from app import specs_store

    with app.app_context():
        begun = specs_store.begin_load(data, "update", "lib.zip")
        assert begun["total"] == 4
        steps = [specs_store.step_load(begun["id"], most=1) for _ in range(4)]
    assert [s["done"] for s in steps] == [1, 2, 3, 4]
    assert all(s["total"] == 4 for s in steps)
    assert [s["finished"] for s in steps] == [False, False, False, True]
    assert "Read 1 of 4 sections: 031000 CONCRETE FORMING." == steps[0]["message"]
    # The counts carry from step to step.
    assert steps[-1]["counted"]["added"] == 4 and steps[-1]["counted"]["sections"] == 4
    # Once finished, the load is gone.
    with app.app_context():
        try:
            specs_store.step_load(begun["id"])
        except Exception as exc:  # noqa: BLE001
            assert "not waiting any more" in str(exc)
        else:
            raise AssertionError("a finished load stepped again")


def test_counts_match_the_one_call_load_on_a_second_load(app, signed_in):
    data = library_of(signed_in)
    from app import specs_store

    with app.app_context():
        begun = specs_store.begin_load(data, "update")
        last = None
        while not (last or {}).get("finished"):
            last = specs_store.step_load(begun["id"], most=3)
        one_call = specs_store.unpack(data, "update")
    assert last["counted"] == one_call
    assert last["counted"]["same"] == 4


def test_replace_takes_out_what_the_file_lacks_at_the_end(app, signed_in):
    data = library_of(signed_in, SECTIONS[:2])
    library_of(signed_in, SECTIONS[2:])
    assert len(state(app)) == 4
    # Replace without the tick is refused, and nothing waits.
    refused = signed_in.post("/specs/library/file/begin", data={
        "library": (io.BytesIO(data), "two.zip"), "mode": "replace"},
        content_type="multipart/form-data", headers=PROGRESS).get_json()
    assert set(refused) == {"go"}
    assert "Tick that you mean to take out" in text(signed_in.get(refused["go"]))
    assert len(state(app)) == 4

    answers = stepped(signed_in, data, mode="replace", sure="yes", filename="two.zip")
    assert answers[-1]["finished"]
    assert [s[1] for s in state(app)] == ["031000", "032000"]
    page = text(signed_in.get(answers[-1]["go"]))
    assert "2 taken out" in page and "033000" in page


def test_a_stale_load_is_cleared_by_the_next_and_a_bad_one_is_refused(app, signed_in):
    data = library_of(signed_in, SECTIONS[:1])
    from app import specs_store

    with app.app_context():
        old = specs_store.begin_load(data)["id"]
        folder = specs_store._loads_dir()
        long_ago = time.time() - specs_store.LOAD_STALE - 60
        for name in (f"{old}.zip", f"{old}.json"):
            os.utime(folder / name, (long_ago, long_ago))
        fresh = specs_store.begin_load(data)["id"]
        names = {p.name for p in folder.iterdir()}
        assert f"{old}.zip" not in names and f"{old}.json" not in names
        assert f"{fresh}.zip" in names
        specs_store.drop_load(fresh)

    # Stepping a load that is not there says so, and the page is sent back.
    gone = signed_in.post(f"/specs/library/file/step/{old}", headers=PROGRESS).get_json()
    assert gone["failed"] and "not waiting any more" in text(signed_in.get(gone["go"]))
    odd = signed_in.post("/specs/library/file/step/..%2F..%2Fpm", headers=PROGRESS)
    assert odd.status_code in (200, 404)

    before = pending(app)
    bad = signed_in.post("/specs/library/file/begin", data={"library": (io.BytesIO(b"nope"), "x.zip")},
                         content_type="multipart/form-data", headers=PROGRESS).get_json()
    assert set(bad) == {"go"}
    assert "not a THEMIS library file" in text(signed_in.get(bad["go"]))
    assert pending(app) == before


def test_the_library_page_offers_the_stepped_load(signed_in):
    page = text(signed_in.get("/specs/library"))
    assert 'data-progress-begin="/specs/library/file/begin"' in page
    assert "spec-progress.js" in page and "spec-progress.css" in page


# --- forms and downloads answered for the script ---------------------------------------

def test_a_redirect_is_told_as_json_and_keeps_its_message(signed_in):
    answer = load(signed_in, "SPC-033000.docx", BODY, "033000", "CAST-IN-PLACE CONCRETE")
    assert answer.status_code == 302                         # as ever, without the script
    from .test_specs import docx_of
    from app import specs

    nodes = specs.align([], specs.from_text(BODY))
    told = signed_in.post("/specs/library/upload", data={"family": "", "files": [
        (io.BytesIO(docx_of(nodes, number="034500", title="PRECAST")), "SPC-034500.docx")]},
        content_type="multipart/form-data", headers=PROGRESS)
    assert told.status_code == 200 and told.is_json
    assert told.get_json()["go"].startswith("/specs/library")
    assert "Read SPC-034500.docx" in text(signed_in.get(told.get_json()["go"]))


def test_downloads_say_how_big_they_are(app, signed_in):
    set_id = project(app, signed_in)
    # The hold off (its tick box shown, not ticked), so the issue goes out.
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Harbour Works", "hold_shown": "1"})
    for url in (f"/specs/sets/{set_id}/sections/1/docx",
                f"/specs/sets/{set_id}/sections/1/docx?fmt=tracked",
                f"/specs/sets/{set_id}/sections/1/docx?fmt=pdf",
                "/specs/library/1/docx", "/specs/library/1/docx?fmt=pdf",
                "/specs/library/file", "/specs/template",
                f"/specs/sets/{set_id}/export?anyway=1",
                f"/specs/sets/{set_id}/export?anyway=1&fmt=tracked",
                f"/specs/sets/{set_id}/export?anyway=1&fmt=pdf"):
        answer = signed_in.get(url, headers=PROGRESS)
        assert answer.status_code == 200 and not answer.is_json, url
        assert answer.headers["Content-Disposition"].startswith("attachment"), url
        assert int(answer.headers["Content-Length"]) == len(answer.data) > 0, url


def test_an_issue_held_back_is_sent_to_the_check(app, signed_in):
    set_id = project(app, signed_in)
    plain = signed_in.get(f"/specs/sets/{set_id}/export")
    assert plain.status_code == 302 and "/check" in plain.headers["Location"]
    told = signed_in.get(f"/specs/sets/{set_id}/export", headers=PROGRESS)
    assert told.is_json and re.search(rf"/specs/sets/{set_id}/check\?issuing=1", told.get_json()["go"])
    assert "Not issued yet" in text(signed_in.get(told.get_json()["go"]))


# --- the check, one group at a time -----------------------------------------------------

def test_the_check_is_laid_out_one_group_at_a_time(app, signed_in):
    set_id = project(app, signed_in)
    page = text(signed_in.get(f"/specs/sets/{set_id}/check"))
    flow = re.search(r'<div class="spec-check-flow" data-check-flow data-groups="([^"]+)"\s+'
                     r'data-first="([^"]*)">', page)
    assert flow, "the groups' wrapper"
    groups = flow.group(1).split()
    assert groups[0] == "references" and groups[-1] == "language"
    assert "model" not in groups                              # no model read
    assert flow.group(2) == "references"                      # the first with anything open
    # The script comes straight after the wrapper opens, then the bar of groups.
    after = page[flow.end():]
    assert after.lstrip().startswith('<script src="/static/spec-check.js">')
    for key in groups:
        assert f'data-group-link="{key}"' in page and f'href="#group-{key}"' in page
        assert f'data-group="{key}"' in page
        assert f'.spec-check-js[data-current="{key}"] [data-group]:not([data-group="{key}"])' in page
    assert 'id="group-references"' in page and 'id="language"' in page and 'id="group-language"' in page
    # Open counts on the bar; the references are what hold the issue.
    tab = re.search(r'data-group-link="references">(.*?)</a>', page, re.S).group(1)
    assert re.search(r'spec-group-n spec-group-n-hold" title="(\d+) open">\1<', tab)
    # Next and Back at each group's foot; the last one's Next is the issue.
    assert "Next: Outdated standards →" in page
    assert "← Back: Cross-references" in page
    assert page.count("spec-group-foot") >= len(groups)
    last = page[page.index('data-group="language"'):]
    assert "Next: review and sign-off" in last
    # Every form is still there: Keep, Amend and Remove, and the summary bar on top.
    assert ">Keep<" in page and ">Amend<" in page and ">Remove<" in page
    assert page.index("to settle") < page.index("data-check-flow")


def test_the_library_check_has_its_groups_too(signed_in):
    load(signed_in, "SPC-033000.docx", BODY, "033000", "CAST-IN-PLACE CONCRETE")
    page = text(signed_in.get("/specs/library/check"))
    assert "data-check-flow" in page and 'data-group-link="references"' in page
    assert "Done: back to the library" in page
