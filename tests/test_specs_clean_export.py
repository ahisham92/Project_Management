"""The issued files: what is still to be specified said plainly and
highlighted, never the master's raw brackets, the issue held until each is
answered or the engineer ticks to issue with them, and the Word files open
for editing."""

from __future__ import annotations

import io
import re
import zipfile

from app import specs
from .test_specs import docx_of, master_nodes, part, text
from .test_specs_questions import _project


def test_an_unanswered_question_says_plainly_what_to_specify():
    assert specs.open_prompt("x", "<insert designation>") == "[Insert designation]"
    assert specs.open_prompt("x", "[, piling]") == "[keep or delete: “, piling”]"
    assert specs.open_prompt("x", "[45MPa] [40MPa] <Insert strength>") == \
        "[choose: 45MPa / 40MPa, or insert strength]"
    assert specs.open_prompt("x", "[ACI 318 (ACI 318M)] [F0] [F1] [S2] <Specify>") == \
        "ACI 318 (ACI 318M) [choose: F0 / F1 / S2, or specify]"
    assert specs.open_prompt("x", "[, except with a rating of] <Insert rating>") == \
        "[keep or delete: “, except with a rating of [Insert rating]”]"
    assert specs.open_prompt("conc_x", "") == "[conc x: to be specified]"
    # Answered, the words go in as before; unmarked, the master's words stay.
    line = "Class A {{d|<insert designation>}}: foundations{{p|[, piling]}}."
    assert specs.fill(line, {"d": "C40", "p": "piling"}, marked=True) == "Class A C40: foundations, piling."
    assert specs.fill(line, {}) == "Class A <insert designation>: foundations[, piling]."
    assert specs.fill(line, {}, marked=True) == \
        "Class A [Insert designation]: foundations[keep or delete: “, piling”]."


def test_the_masters_own_prompts_and_wrappers_read_cleanly():
    wrapped = "Exposure Class: [ACI 318 (ACI 318M) {{e|[S1] [S2] [C2]}}] <Specify>."
    assert specs.fill(wrapped, {}, marked=True) == "Exposure Class: ACI 318 (ACI 318M) [choose: S1 / S2 / C2]."
    assert specs.fill(wrapped, {"e": "S2"}, marked=True) == "Exposure Class: ACI 318 (ACI 318M) S2."
    assert specs.fill("Every 110 cu.m. <Specify volume>.", {}, marked=True) == "Every 110 cu.m. [Specify volume]."
    # A choice taken with its comma leaves no ",." behind.
    assert specs.fill("Apply to {{l|[exposed faces,] [rubbed,]}}.",
                      {"l": "exposed faces"}) == "Apply to exposed faces."


def test_the_word_file_highlights_what_is_still_open():
    nodes = specs.align([], specs.from_text("# PRODUCTS\n## MIXES\n- Class A {{d|<insert designation>}}: footings.\n"))
    document = part(docx_of(nodes, values={}, marked=True), "word/document.xml")
    assert "&lt;insert designation&gt;" not in document
    assert re.search(r'<w:highlight w:val="yellow"/>.*?\[Insert designation\]', document)
    # The master downloaded from the library keeps its own words.
    master = part(docx_of(nodes, values={}), "word/document.xml")
    assert "&lt;insert designation&gt;" in master and "[Insert designation]" not in master


def test_the_word_file_opens_for_editing_whatever_the_house_template_says():
    source = zipfile.ZipFile(io.BytesIO(specs.TEMPLATE.read_bytes()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for name in source.namelist():
            data = source.read(name)
            if name == "word/settings.xml":
                data = data.replace(b"</w:settings>", b'<w:documentProtection w:edit="readOnly" w:enforcement="1"/>'
                                                     b'<w:writeProtection w:recommended="1"/></w:settings>')
            if name == "[Content_Types].xml":
                data = data.replace(b"wordprocessingml.document.main+xml", b"wordprocessingml.template.main+xml")
            z.writestr(name, data)
    data = specs.write_docx({"number": "032000", "title": "CONCRETE REINFORCING"}, master_nodes(),
                            {"revision": "0"}, {}, {}, template=out.getvalue())
    assert "documentProtection" not in part(data, "word/settings.xml")
    assert "writeProtection" not in part(data, "word/settings.xml")
    types = part(data, "[Content_Types].xml")
    assert "wordprocessingml.document.main+xml" in types and "template.main" not in types


def test_an_issue_is_held_while_places_are_open_unless_the_engineer_ticks(app, signed_in):
    from app import specs_review

    set_id = _project(app, signed_in)
    signed_in.post(f"/specs/sets/{set_id}", data={"name": "Tower", "hold_shown": "1"})
    page = text(signed_in.get(f"/specs/sets/{set_id}/issues"))
    assert "still to be specified" in page and 'name="open_ok"' in page
    assert "[Insert designation]" in page
    form = {"revision": "A", "responsible": "1", "issue_date": "2026-10-01"}
    answer = text(signed_in.post(f"/specs/sets/{set_id}/issues", data=form, follow_redirects=True))
    assert "Not issued yet" in answer and "still to be specified" in answer
    with app.app_context():
        assert specs_review.issues(set_id) == []
    signed_in.post(f"/specs/sets/{set_id}/issues", data=dict(form, open_ok="1"))
    with app.app_context():
        assert [i["revision"] for i in specs_review.issues(set_id)] == ["A"]
        issued = specs_review.issues(set_id)[0]
        data = specs_review.issue(set_id, issued["id"], content=True)["content"]
    bundle = zipfile.ZipFile(io.BytesIO(data))
    document = part(bundle.read(bundle.namelist()[0]), "word/document.xml")
    assert "[Insert designation]" in document and "&lt;insert designation&gt;" not in document


def test_answered_places_are_no_longer_open(app, signed_in):
    from app import specs_review, specs_store

    set_id = _project(app, signed_in)
    with app.app_context():
        before = specs_review.still_open(specs_store.spec_set(set_id))
    signed_in.post(f"/specs/sets/{set_id}/details?group=project-information",
                   data={"q_proj_site": "__free__", "t_proj_site": "Jeddah port"})
    with app.app_context():
        after = specs_review.still_open(specs_store.spec_set(set_id))
    assert len(after) == len(before) - 1
    assert all("Insert location" not in " ".join(p["open"]) for p in after)
