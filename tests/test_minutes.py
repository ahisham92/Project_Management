"""The minutes of meeting: filtering, sorting, the Word writer and the screens."""

from __future__ import annotations

import zipfile
import xml.etree.ElementTree as ET
from io import BytesIO

import pytest

from app.minutes import (
    DEFAULT_FILTER, IMPACTS, decorate, filter_items, item_ref, matches_search, meeting_label,
    meeting_stem, moved, next_ref, normalise_impact, normalise_sort, normalise_status,
    renumber, sort_items, summarise,
)
from app.minutes_doc import minutes_document, register_document
from app.word import Document

TODAY = "2026-09-03"


def item(**fields):
    """One register row, with the fields the screens rely on filled in."""
    base = {
        "id": fields.pop("id", 1), "ref": "1.1", "subject": "Quay wall levels",
        "discussion": "", "agreement": "Marine to reissue the layout",
        "owner_id": None, "owner_name": "", "owner_person": None, "trade_id": None,
        "trade_name": "", "impact": "none", "status": "open",
        "raised_date": "2026-09-01", "due_date": "", "closed_date": "",
        "meeting_id": None, "meeting_ref": "", "meeting_title": "", "meeting_date": "",
    }
    base.update(fields)
    return decorate(base, TODAY)


# --- the reading of one item ----------------------------------------------

def test_an_item_past_its_due_date_reads_as_overdue():
    row = item(due_date="2026-08-25")
    assert row["is_open"] and row["is_overdue"]
    assert row["days_overdue"] == 9


def test_a_closed_item_is_never_overdue_however_late_its_due_date():
    row = item(due_date="2026-01-01", status="closed", closed_date="2026-02-01")
    assert not row["is_open"]
    assert not row["is_overdue"]


def test_an_item_due_within_a_week_is_flagged_but_not_overdue():
    row = item(due_date="2026-09-08")
    assert row["is_due_soon"] and not row["is_overdue"]
    assert row["days_to_due"] == 5


def test_an_item_with_no_due_date_is_neither_overdue_nor_due_soon():
    row = item()
    assert row["days_to_due"] is None
    assert not row["is_overdue"] and not row["is_due_soon"]


@pytest.mark.parametrize(
    "impact,time,cost",
    [("none", False, False), ("time", True, False), ("cost", False, True), ("both", True, True)],
)
def test_whether_an_item_bears_on_time_or_cost(impact, time, cost):
    row = item(impact=impact)
    assert row["affects_time"] is time
    assert row["affects_cost"] is cost


def test_an_unknown_impact_or_status_falls_back_rather_than_breaking_the_page():
    assert normalise_impact("schedule") == "none"
    assert normalise_impact(None) == "none"
    assert normalise_status("pending") == "open"
    assert item(impact="schedule", status="pending")["is_open"]


# --- filtering -------------------------------------------------------------

def register():
    return [
        item(id=1, ref="1.1", impact="time", due_date="2026-08-01", raised_date="2026-08-01",
             owner_id=7, owner_person="Ahmed", trade_id=3, trade_name="Marine", meeting_id=1,
             meeting_date="2026-08-01", meeting_ref="MOM-01"),
        item(id=2, ref="1.2", subject="Additional survey", impact="cost",
             due_date="2026-09-20", owner_id=8, owner_person="Client Rep", meeting_id=1,
             meeting_date="2026-08-01", meeting_ref="MOM-01", raised_date="2026-08-01"),
        item(id=3, ref="2.1", subject="Drawing register", status="closed",
             closed_date="2026-09-01", trade_id=4, trade_name="Civil", meeting_id=2,
             meeting_date="2026-09-01", meeting_ref="MOM-02", raised_date="2026-09-01"),
    ]


def refs(rows):
    return [r["ref"] for r in rows]


def test_the_default_filter_shows_what_is_still_open():
    assert DEFAULT_FILTER == "open"
    assert refs(filter_items(register(), chip="open")) == ["1.1", "1.2"]


def test_filtering_on_closed_overdue_time_and_cost():
    rows = register()
    assert refs(filter_items(rows, chip="closed")) == ["2.1"]
    assert refs(filter_items(rows, chip="overdue")) == ["1.1"]
    assert refs(filter_items(rows, chip="time")) == ["1.1"]
    assert refs(filter_items(rows, chip="cost")) == ["1.2"]
    assert refs(filter_items(rows, chip="all")) == ["1.1", "1.2", "2.1"]


def test_an_unknown_filter_falls_back_to_open_rather_than_showing_nothing():
    assert refs(filter_items(register(), chip="nonsense")) == ["1.1", "1.2"]


def test_filtering_by_owner_trade_and_meeting():
    rows = register()
    assert refs(filter_items(rows, chip="all", owner_id=8)) == ["1.2"]
    assert refs(filter_items(rows, chip="all", trade_id=3)) == ["1.1"]
    assert refs(filter_items(rows, chip="all", meeting_id=2)) == ["2.1"]


def test_filters_combine_rather_than_replacing_one_another():
    rows = filter_items(register(), chip="open", trade_id=3, owner_id=7)
    assert refs(rows) == ["1.1"]
    assert refs(filter_items(register(), chip="open", trade_id=4)) == []


def test_the_date_range_reads_on_when_an_item_was_raised():
    rows = register()
    assert refs(filter_items(rows, chip="all", date_from="2026-09-01")) == ["2.1"]
    assert refs(filter_items(rows, chip="all", date_to="2026-08-31")) == ["1.1", "1.2"]
    assert refs(filter_items(rows, chip="all", date_from="2026-08-01", date_to="2026-08-31")) == ["1.1", "1.2"]


def test_search_looks_through_the_subject_agreement_and_owner():
    rows = register()
    assert refs(filter_items(rows, chip="all", search="quay")) == ["1.1"]
    assert refs(filter_items(rows, chip="all", search="reissue")) == ["1.1", "1.2", "2.1"]
    assert refs(filter_items(rows, chip="all", search="client rep")) == ["1.2"]
    assert refs(filter_items(rows, chip="all", search="MOM-02")) == ["2.1"]


def test_search_needs_every_word_to_appear_somewhere():
    assert matches_search({"subject": "Quay wall levels"}, "quay levels")
    assert not matches_search({"subject": "Quay wall levels"}, "quay survey")
    assert matches_search({"subject": "anything"}, "")


# --- sorting ---------------------------------------------------------------

def test_sorting_by_due_date_puts_undated_items_last_in_both_directions():
    rows = [item(id=1, ref="a", due_date="2026-09-10"), item(id=2, ref="b"),
            item(id=3, ref="c", due_date="2026-08-01")]
    assert refs(sort_items(rows, "due", "asc")) == ["c", "a", "b"]
    assert refs(sort_items(rows, "due", "desc"))[-1] == "b"


def test_item_references_sort_as_numbers_so_1_9_comes_before_1_10():
    rows = [item(id=1, ref="1.10"), item(id=2, ref="1.9"), item(id=3, ref="1.2")]
    assert refs(sort_items(rows, "ref", "asc")) == ["1.2", "1.9", "1.10"]


def test_sorting_is_stable_for_rows_that_tie():
    rows = [item(id=1, ref="2.1", impact="time"), item(id=2, ref="1.1", impact="time")]
    assert refs(sort_items(rows, "impact", "asc")) == ["1.1", "2.1"]


def test_an_unknown_sort_column_or_direction_is_replaced_with_a_safe_one():
    assert normalise_sort("; drop table", None) == ("due", "asc")
    assert normalise_sort("owner", "sideways") == ("owner", "asc")
    assert normalise_sort("meeting", None) == ("meeting", "desc")


# --- the headline counts ---------------------------------------------------

def test_the_summary_counts_only_open_items_as_affecting_time_or_cost():
    rows = register() + [item(id=4, ref="2.2", impact="both", status="closed")]
    totals = summarise(rows)
    assert totals == {"total": 4, "open": 2, "closed": 2, "overdue": 1,
                      "due_soon": 0, "time": 1, "cost": 1}


def test_the_next_item_number_follows_the_meeting_number():
    assert next_ref([], "MOM-04") == "4.1"
    assert next_ref([{"ref": "4.1"}, {"ref": "4.2"}], "MOM-04") == "4.3"
    assert next_ref([{"ref": "1"}], "") == "2"


# --- numbering by position -------------------------------------------------

def test_a_meeting_reference_gives_its_items_their_stem():
    assert meeting_stem("MOM-04") == "4"
    assert meeting_stem("MOM-01") == "1"          # not "01"
    assert meeting_stem("Kick-off") == ""         # nothing to hang a stem on
    assert meeting_stem(None) == ""


def test_an_item_with_no_stem_is_numbered_plainly():
    assert item_ref("4", 2) == "4.2"
    assert item_ref("", 2) == "2"


def test_numbering_follows_position_so_two_items_cannot_share_a_number():
    rows = [{"id": 7}, {"id": 3}, {"id": 9}]
    assert renumber(rows, "MOM-02") == [
        {"id": 7, "sort_order": 1, "ref": "2.1"},
        {"id": 3, "sort_order": 2, "ref": "2.2"},
        {"id": 9, "sort_order": 3, "ref": "2.3"},
    ]
    numbers = [row["ref"] for row in renumber([{"id": i} for i in range(20)], "MOM-01")]
    assert len(set(numbers)) == len(numbers)


def test_renumbering_ignores_whatever_number_an_item_used_to_carry():
    rows = [{"id": 1, "ref": "9.9"}, {"id": 2, "ref": "9.9"}]      # a duplicate
    assert [r["ref"] for r in renumber(rows, "MOM-01")] == ["1.1", "1.2"]


def test_moving_an_item_swaps_it_with_its_neighbour():
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert [r["id"] for r in moved(rows, 2, "up")] == [2, 1, 3]
    assert [r["id"] for r in moved(rows, 2, "down")] == [1, 3, 2]


def test_moving_past_either_end_leaves_the_order_alone():
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    assert [r["id"] for r in moved(rows, 1, "up")] == [1, 2, 3]
    assert [r["id"] for r in moved(rows, 3, "down")] == [1, 2, 3]
    assert [r["id"] for r in moved(rows, 99, "up")] == [1, 2, 3]


def test_moving_does_not_disturb_the_rest_of_the_list():
    rows = [{"id": i} for i in range(1, 6)]
    assert [r["id"] for r in moved(rows, 3, "down")] == [1, 2, 4, 3, 5]


def test_a_meeting_reads_as_its_reference_subject_and_date():
    assert meeting_label({"ref": "MOM-01", "title": "Design", "meeting_date": "2026-09-03"}) \
        == "MOM-01 · Design (03/09/2026)"
    assert meeting_label({"ref": "", "title": "", "meeting_date": "2026-09-03"}) == "03/09/2026"


# --- the Word writer -------------------------------------------------------

def parts(data: bytes) -> dict[str, str]:
    with zipfile.ZipFile(BytesIO(data)) as archive:
        return {name: archive.read(name).decode("utf-8") for name in archive.namelist()}


def test_a_word_document_is_a_zip_whose_every_part_is_valid_xml():
    data = Document("Test").add_title("Hello").render()
    contents = parts(data)
    assert "[Content_Types].xml" in contents and "word/document.xml" in contents
    for name, text in contents.items():
        ET.fromstring(text)                      # raises if any part is malformed


def test_text_is_escaped_so_an_ampersand_cannot_corrupt_the_file():
    data = Document().add_paragraph('Cost & time <b>"x"</b>').render()
    document = parts(data)["word/document.xml"]
    assert "Cost &amp; time &lt;b&gt;" in document
    ET.fromstring(document)


def test_a_line_break_inside_a_cell_stays_a_line_break():
    data = Document().add_table((), [["first\nsecond"]]).render()
    assert "<w:br/>" in parts(data)["word/document.xml"]


def test_a_table_carries_one_cell_per_column_even_for_a_short_row():
    data = Document().add_table(("A", "B", "C"), [["only one"]]).render()
    document = parts(data)["word/document.xml"]
    assert document.count("<w:tc>") == 6         # three headings, three cells
    assert "<w:tblHeader/>" in document          # the headings repeat on each page


def test_a_paragraph_follows_every_table_so_two_tables_do_not_merge():
    data = Document().add_table((), [["a"]]).add_table((), [["b"]]).render()
    document = parts(data)["word/document.xml"]
    assert document.count("<w:tbl>") == 2
    assert "</w:tbl><w:p/>" in document


def test_landscape_is_what_the_page_size_says():
    assert 'w:orient="landscape"' in parts(Document(orientation="landscape").render())["word/document.xml"]
    assert "orient" not in parts(Document().render())["word/document.xml"]


# --- the documents themselves ----------------------------------------------

PROJECT = {"code": "SIBLINE-PORT", "name": "Sibline Port", "client": "Port Authority"}


def sheet():
    return {
        "meeting": {"id": 1, "ref": "MOM-01", "title": "Design coordination",
                    "meeting_date": "2026-09-03", "meeting_time": "10:00",
                    "location": "Teams", "chaired_by": "Ahmed", "minuted_by": "Ahmed",
                    "next_date": "2026-09-10", "notes": "On site next week."},
        "attendance": [
            {"name": "Ahmed", "organisation": "Dar", "job_title": "PM",
             "trade_name": "Marine", "invited": True, "present": True},
            {"name": "Client Rep", "organisation": "Port", "job_title": "",
             "trade_name": "", "invited": True, "present": False},
        ],
        "present": [], "absent": [],
        "items": [item(id=1, impact="time", due_date="2026-08-01")],
    }


def test_the_minutes_carry_the_project_number_and_name():
    document = parts(minutes_document(PROJECT, sheet()))["word/document.xml"]
    assert "SIBLINE-PORT" in document and "Sibline Port" in document
    assert "Minutes of meeting" in document


def test_the_minutes_show_who_attended_and_who_sent_apologies():
    document = parts(minutes_document(PROJECT, sheet()))["word/document.xml"]
    assert "Present" in document and "Absent" in document
    assert "Client Rep" in document


def test_the_minutes_carry_each_item_with_its_owner_impact_and_status():
    document = parts(minutes_document(PROJECT, sheet()))["word/document.xml"]
    for expected in ("Quay wall levels", "Marine to reissue the layout", "Time",
                     "01/08/2026", "days overdue"):
        assert expected in document, expected


def test_a_meeting_with_nothing_minuted_still_produces_a_readable_document():
    empty = dict(sheet(), items=[], attendance=[], present=[], absent=[])
    document = parts(minutes_document(PROJECT, empty))["word/document.xml"]
    assert "No items were minuted" in document
    assert "No attendees recorded" in document
    ET.fromstring(document)


def test_the_register_document_says_which_filter_produced_it():
    data = register_document(PROJECT, register(), "Action register", "Filtered: Open")
    document = parts(data)["word/document.xml"]
    assert "Filtered: Open" in document
    assert "MOM-01" in document and "MOM-02" in document


def test_an_empty_register_says_so_rather_than_producing_a_bare_page():
    document = parts(register_document(PROJECT, []))["word/document.xml"]
    assert "Nothing matches this filter" in document


def test_a_project_row_from_the_database_can_be_passed_straight_in(database):
    """The document builders take a row as it comes off the database, which does
    not answer .get() — the bug that made every page 500 when it was missed."""
    from app.db import connect

    conn = connect(database)
    try:
        project = conn.execute("SELECT * FROM projects LIMIT 1").fetchone()
        assert b"PK" == minutes_document(project, sheet())[:2]
        assert b"PK" == register_document(project, [])[:2]
    finally:
        conn.close()


def test_every_impact_has_a_name_for_the_documents_and_the_dropdown():
    assert [key for key, _ in IMPACTS] == ["none", "time", "cost", "both"]
    assert dict(IMPACTS)["both"] == "Time & cost"


# --- the screens -----------------------------------------------------------

def page(client, url):
    response = client.get(url)
    assert response.status_code == 200, (url, response.status_code)
    return response.get_data(as_text=True)


def post(client, url, **data):
    response = client.post(url, data=data, follow_redirects=True)
    assert response.status_code == 200, (url, response.status_code)
    return response.get_data(as_text=True)


@pytest.fixture()
def minuted(signed_in):
    """A project with two attendees, one meeting and three items on it."""
    post(signed_in, "/projects/1/minutes/attendees", name="Ahmed Mitwally",
         organisation="Dar", job_title="Project manager", trade_id="1")
    post(signed_in, "/projects/1/minutes/attendees", name="Client Rep", organisation="Port")
    post(signed_in, "/projects/1/minutes/meetings", ref="MOM-01",
         title="Weekly design coordination", meeting_date="03/09/2026",
         meeting_time="10:00", location="Teams", chaired_by="Ahmed Mitwally")
    post(signed_in, "/projects/1/minutes/items", meeting_id="1", ref="1.1",
         subject="Quay wall levels", agreement="Marine to reissue the layout",
         owner_id="1", trade_id="1", impact="time", status="open", due_date="10/09/2026")
    post(signed_in, "/projects/1/minutes/items", meeting_id="1", ref="1.2",
         subject="Additional survey", agreement="Client to confirm the budget",
         owner_id="2", impact="cost", status="open", due_date="01/08/2026")
    post(signed_in, "/projects/1/minutes/items", meeting_id="1", ref="1.3",
         subject="Drawing register format", agreement="Agreed as issued",
         impact="none", status="closed")
    return signed_in


def test_the_minutes_tab_is_on_every_project_screen(signed_in):
    assert "/projects/1/minutes" in page(signed_in, "/projects/1/")


def test_the_register_opens_on_a_project_with_no_meetings_yet(signed_in):
    body = page(signed_in, "/projects/1/minutes")
    assert "Minutes of meeting" in body
    assert "No meetings yet" in body


def test_the_register_carries_the_project_number_and_name(minuted):
    body = page(minuted, "/projects/1/minutes")
    assert "SIBLINE-PORT" in body and "Sibline Port" in body


def test_the_register_opens_on_the_open_items(minuted):
    body = page(minuted, "/projects/1/minutes")
    assert "Quay wall levels" in body
    assert "Drawing register format" not in body      # closed


def test_every_filter_narrows_the_register(minuted):
    assert "Drawing register format" in page(minuted, "/projects/1/minutes?filter=closed")
    assert "Additional survey" in page(minuted, "/projects/1/minutes?filter=overdue")
    assert "Quay wall levels" in page(minuted, "/projects/1/minutes?filter=time")
    assert "Additional survey" in page(minuted, "/projects/1/minutes?filter=cost")
    everything = page(minuted, "/projects/1/minutes?filter=all")
    assert everything.count("id=\"item-") == 3


def test_searching_by_keyword(minuted):
    body = page(minuted, "/projects/1/minutes?filter=all&q=quay")
    assert "Quay wall levels" in body and "Additional survey" not in body


def test_filtering_by_owner_trade_and_meeting_on_the_page(minuted):
    assert "Additional survey" in page(minuted, "/projects/1/minutes?filter=all&owner=2")
    assert "Additional survey" not in page(minuted, "/projects/1/minutes?filter=all&owner=1")
    assert "Quay wall levels" in page(minuted, "/projects/1/minutes?filter=all&trade=1")
    assert "Quay wall levels" in page(minuted, "/projects/1/minutes?filter=all&meeting=1")


def test_the_date_range_is_typed_as_dd_mm_yyyy(minuted):
    inside = page(minuted, "/projects/1/minutes?filter=all&from=01/09/2026&to=30/09/2026")
    assert "Quay wall levels" in inside
    outside = page(minuted, "/projects/1/minutes?filter=all&from=01/10/2026")
    assert "Quay wall levels" not in outside


def test_every_sortable_column_renders(minuted):
    for column in ("ref", "subject", "meeting", "owner", "trade", "impact", "raised", "due", "status"):
        page(minuted, f"/projects/1/minutes?filter=all&sort={column}&dir=desc")


def test_a_filter_survives_closing_an_item(minuted):
    body = post(minuted, "/projects/1/minutes/items/1/status?filter=closed&q=quay", status="closed")
    assert "Quay wall levels" in body                 # still filtered to what was on screen


def test_closing_and_reopening_an_item(minuted):
    post(minuted, "/projects/1/minutes/items/1/status", status="closed")
    assert "Quay wall levels" not in page(minuted, "/projects/1/minutes?filter=open")
    post(minuted, "/projects/1/minutes/items/1/status", status="open")
    assert "Quay wall levels" in page(minuted, "/projects/1/minutes?filter=open")


def test_closing_an_item_stamps_the_date_it_was_closed(minuted):
    post(minuted, "/projects/1/minutes/items/1/status", status="closed")
    from app.service import load_items

    with minuted.application.app_context():
        closed = [i for i in load_items(1) if i["id"] == 1][0]
    assert closed["closed_date"]


def test_the_meeting_page_shows_the_project_the_date_and_who_attended(minuted):
    post(minuted, "/projects/1/minutes/meetings/1", ref="MOM-01", title="Weekly design coordination",
         meeting_date="03/09/2026", invited=["1", "2"], present=["1"])
    body = page(minuted, "/projects/1/minutes/meetings/1")
    assert "SIBLINE-PORT" in body and "03/09/2026" in body
    assert "Present" in body and "Apologies" in body


def test_an_attendee_is_added_once_and_then_ticked_on_each_meeting(minuted):
    body = page(minuted, "/projects/1/minutes/meetings/1")
    assert body.count('name="present"') == 2         # a tick box each, not retyped


def test_a_new_meeting_invites_everyone_on_the_roster(minuted):
    post(minuted, "/projects/1/minutes/meetings", ref="MOM-02", meeting_date="10/09/2026")
    from app.service import load_attendance

    with minuted.application.app_context():
        assert set(load_attendance(2)) == {1, 2}


def test_every_item_has_a_row_the_edit_form_opens_into(minuted):
    """Clicking Edit fills the row below rather than reloading the page."""
    body = page(minuted, "/projects/1/minutes/meetings/1")
    assert body.count('id="edit-') == 3
    assert body.count("data-toggle-row") == 3        # one Edit control per item
    assert body.count('id="editor-template"') == 1


def test_the_form_is_rendered_once_rather_than_per_row(minuted):
    """A copy per row would repeat the owner, trade and meeting lists and turn
    a long register into a megabyte of HTML."""
    body = page(minuted, "/projects/1/minutes?filter=all")
    assert body.count('<textarea name="agreement"') == 2      # add form, and the template
    assert body.count('data-item=') == 3                      # the values to fill in


def test_a_long_register_stays_a_reasonable_size(signed_in):
    from app.service import load_items

    post(signed_in, "/projects/1/minutes/meetings", ref="MOM-01", meeting_date="03/09/2026")
    for number in range(60):
        post(signed_in, "/projects/1/minutes/items", meeting_id="1",
             subject=f"Item {number}", agreement="Something was agreed here")
    body = page(signed_in, "/projects/1/minutes?filter=all")
    with signed_in.application.app_context():
        assert len(load_items(1)) == 60
    assert len(body) < 300_000, f"{len(body) / 1024:.0f} KB for 60 items"


def open_rows(body):
    """The ids of the edit rows rendered open — the ones without `hidden`."""
    import re

    return {
        match.group(1)
        for match in re.finditer(r'<tr[^>]*id="edit-(\d+)"[^>]*>', body)
        if "hidden" not in match.group(0)
    }


def test_the_edit_link_still_works_with_javascript_switched_off(minuted):
    """?edit=<id> renders that one row open — where the link leads when the
    script that opens it in place is not running."""
    for url in ("/projects/1/minutes?filter=all&edit=1", "/projects/1/minutes/meetings/1?edit=1"):
        body = page(minuted, url)
        assert open_rows(body) == {"1"}
        assert "Save item" in body


def test_no_row_is_open_until_one_is_asked_for(minuted):
    assert open_rows(page(minuted, "/projects/1/minutes/meetings/1")) == set()


def test_the_agreement_and_discussion_are_text_areas_with_room_to_write(minuted):
    for url in ("/projects/1/minutes", "/projects/1/minutes/meetings/1"):
        body = page(minuted, url)
        assert '<textarea name="agreement"' in body
        assert '<textarea name="discussion"' in body
        assert 'name="agreement" value=' not in body      # no longer a one-line input


def test_saving_an_item_keeps_what_was_changed(minuted):
    post(minuted, "/projects/1/minutes/items/1", ref="1.1", subject="Quay wall levels revised",
         agreement="Marine to reissue", owner_id="2", impact="both", status="open",
         due_date="20/09/2026", meeting_id="1")
    body = page(minuted, "/projects/1/minutes?filter=all")
    assert "Quay wall levels revised" in body
    assert "Time &amp; cost" in body


def test_an_item_needs_a_subject_or_an_agreement(minuted):
    body = post(minuted, "/projects/1/minutes/items", meeting_id="1", impact="time")
    assert "needs a subject or an agreement" in body


def test_a_meeting_needs_a_date(minuted):
    assert "A meeting needs a date" in post(minuted, "/projects/1/minutes/meetings", ref="MOM-09")


def test_an_attendee_needs_a_name(minuted):
    assert "An attendee needs a name" in post(minuted, "/projects/1/minutes/attendees", name="  ")


def test_an_item_cannot_borrow_a_trade_or_attendee_from_another_project(minuted):
    """A stray id in the form is dropped rather than crossing project lines."""
    post(minuted, "/projects/1/minutes/items", subject="Stray", agreement="x",
         owner_id="9999", trade_id="9999")
    from app.service import load_items

    with minuted.application.app_context():
        stray = [i for i in load_items(1) if i["subject"] == "Stray"][0]
    assert stray["owner_id"] is None and stray["trade_id"] is None


def test_the_agenda_lists_every_open_item_grouped_by_owner(minuted):
    body = page(minuted, "/projects/1/minutes/agenda")
    assert "Ahmed Mitwally" in body and "Client Rep" in body
    assert "Drawing register format" not in body     # closed items are not on the agenda


def test_the_agenda_can_be_narrowed_to_one_trade_or_owner(minuted):
    assert "Additional survey" not in page(minuted, "/projects/1/minutes/agenda?trade=1")
    assert "Quay wall levels" not in page(minuted, "/projects/1/minutes/agenda?owner=2")


def test_deleting_a_meeting_keeps_its_items_in_the_register(minuted):
    post(minuted, "/projects/1/minutes/meetings/1/delete")
    body = page(minuted, "/projects/1/minutes?filter=all")
    assert "Quay wall levels" in body
    assert "No meetings yet" in body


def test_removing_an_attendee_keeps_their_name_on_the_items_they_owned(minuted):
    post(minuted, "/projects/1/minutes/attendees/1/delete")
    assert "Ahmed Mitwally" in page(minuted, "/projects/1/minutes?filter=all")


def test_deleting_an_item(minuted):
    post(minuted, "/projects/1/minutes/items/1/delete")
    assert "Quay wall levels" not in page(minuted, "/projects/1/minutes?filter=all")


def test_word_downloads_are_offered_for_the_minutes_the_register_and_the_agenda(minuted):
    for url in ("/projects/1/minutes/meetings/1.docx", "/projects/1/minutes/register.docx",
                "/projects/1/minutes/agenda.docx"):
        response = minuted.get(url)
        assert response.status_code == 200, url
        assert response.data[:2] == b"PK", url
        assert ".docx" in response.headers["Content-Disposition"]
        assert "wordprocessingml" in response.headers["Content-Type"]


def test_the_minutes_document_names_the_meeting_it_came_from(minuted):
    body = minuted.get("/projects/1/minutes/meetings/1.docx")
    assert "MOM-01" in body.headers["Content-Disposition"]
    assert "MOM-01" in parts(body.data)["word/document.xml"]


def test_the_register_download_honours_the_filter_on_screen(minuted):
    document = parts(minuted.get("/projects/1/minutes/register.docx?filter=all&q=quay").data)
    body = document["word/document.xml"]
    assert "Quay wall levels" in body and "Additional survey" not in body
    assert 'matching "quay"' in body


def test_every_screen_offers_print_for_pdf(minuted):
    for url in ("/projects/1/minutes", "/projects/1/minutes/meetings/1", "/projects/1/minutes/agenda"):
        assert "data-print" in page(minuted, url)


def test_a_missing_meeting_is_a_404_not_a_crash(signed_in):
    assert signed_in.get("/projects/1/minutes/meetings/99").status_code == 404
    assert signed_in.get("/projects/1/minutes/meetings/99.docx").status_code == 404


def test_minutes_on_a_project_you_cannot_see_are_not_found(client):
    client.post("/register", data={"name": "Outsider", "email": "out@example.com",
                                   "password": "longenough1"})
    for url in ("/projects/1/minutes", "/projects/1/minutes/agenda",
                "/projects/1/minutes/meetings/1"):
        assert client.get(url).status_code == 404, url


def test_a_column_heading_containing_an_ampersand_is_not_escaped_twice(minuted):
    """A heading passed to the macro is escaped once by Jinja; writing the
    entity by hand printed a literal "&amp;" on screen."""
    assert "&amp;amp;" not in page(minuted, "/projects/1/minutes")
    assert "&amp;amp;" not in page(minuted, "/projects/1/tasks")


# --- reordering on the page ------------------------------------------------

def numbers(client, meeting_id=1):
    """The items of one meeting, in the order they are minuted."""
    from app.service import meeting_items

    with client.application.app_context():
        return [(row["ref"], row["subject"]) for row in meeting_items(1, meeting_id)]


@pytest.fixture()
def ordered(minuted):
    """The three seeded items, which start numbered 1.1, 1.2, 1.3."""
    assert numbers(minuted) == [("1.1", "Quay wall levels"),
                                ("1.2", "Additional survey"),
                                ("1.3", "Drawing register format")]
    return minuted


def test_moving_an_item_down_swaps_it_and_renumbers_both(ordered):
    post(ordered, "/projects/1/minutes/items/1/move", direction="down")
    assert numbers(ordered) == [("1.1", "Additional survey"),
                                ("1.2", "Quay wall levels"),
                                ("1.3", "Drawing register format")]


def test_moving_an_item_up_is_the_mirror_of_moving_it_down(ordered):
    post(ordered, "/projects/1/minutes/items/3/move", direction="up")
    post(ordered, "/projects/1/minutes/items/3/move", direction="down")
    assert numbers(ordered) == [("1.1", "Quay wall levels"),
                                ("1.2", "Additional survey"),
                                ("1.3", "Drawing register format")]


def test_moving_the_first_item_up_says_so_rather_than_wrapping_around(ordered):
    body = post(ordered, "/projects/1/minutes/items/1/move", direction="up")
    assert "already first" in body
    assert numbers(ordered)[0] == ("1.1", "Quay wall levels")


def test_moving_the_last_item_down_says_so(ordered):
    body = post(ordered, "/projects/1/minutes/items/3/move", direction="down")
    assert "already last" in body
    assert numbers(ordered)[-1] == ("1.3", "Drawing register format")


def test_an_item_number_cannot_be_typed_in(ordered):
    """The number comes from the position, so a posted one is ignored rather
    than creating a second item numbered 1.1."""
    post(ordered, "/projects/1/minutes/items", meeting_id="1", ref="1.1",
         subject="Sneaked in", agreement="x")
    minuted_numbers = [ref for ref, _ in numbers(ordered)]
    assert minuted_numbers == ["1.1", "1.2", "1.3", "1.4"]
    assert len(set(minuted_numbers)) == 4


def test_deleting_an_item_closes_the_gap_in_the_numbering(ordered):
    post(ordered, "/projects/1/minutes/items/1/delete")
    assert numbers(ordered) == [("1.1", "Additional survey"),
                                ("1.2", "Drawing register format")]


def test_moving_an_item_to_another_meeting_renumbers_both(ordered):
    post(ordered, "/projects/1/minutes/meetings", ref="MOM-02", meeting_date="10/09/2026")
    post(ordered, "/projects/1/minutes/items/2", meeting_id="2", subject="Additional survey",
         agreement="Client to confirm the budget", impact="cost", status="open")
    assert numbers(ordered, 1) == [("1.1", "Quay wall levels"),
                                   ("1.2", "Drawing register format")]
    assert numbers(ordered, 2) == [("2.1", "Additional survey")]


def test_renaming_a_meeting_renumbers_its_items(ordered):
    post(ordered, "/projects/1/minutes/meetings/1", ref="MOM-07",
         title="Weekly design coordination", meeting_date="03/09/2026")
    assert [ref for ref, _ in numbers(ordered)] == ["7.1", "7.2", "7.3"]


def test_items_raised_outside_a_meeting_are_numbered_as_their_own_run(ordered):
    post(ordered, "/projects/1/minutes/items", subject="Raised by email", agreement="x")
    post(ordered, "/projects/1/minutes/items", subject="Raised on site", agreement="x")
    assert numbers(ordered, None) == [("1", "Raised by email"), ("2", "Raised on site")]


def test_the_meeting_page_offers_the_move_buttons(ordered):
    body = page(ordered, "/projects/1/minutes/meetings/1")
    assert body.count("/move") == 6              # up and down on each of three items
    assert "▲" in body and "▼" in body


def test_the_arrows_are_disabled_at_each_end_of_the_list(ordered):
    body = page(ordered, "/projects/1/minutes/meetings/1")
    assert body.count("disabled") == 2           # the first cannot go up, the last down


def test_the_item_number_is_shown_but_not_typed(ordered):
    """The only "ref" field left on either page is the meeting's own
    reference; an item's number is no longer something anyone types."""
    for url in ("/projects/1/minutes/meetings/1?edit=1", "/projects/1/minutes?filter=all&edit=1"):
        assert page(ordered, url).count('name="ref"') == 1


def test_a_register_with_duplicate_numbers_is_put_right_on_start(database):
    """Numbers used to be typed, so an existing register can hold duplicates.
    Opening the database renumbers them by position, keeping the order."""
    from app.db import connect, init_db

    conn = connect(database)
    with conn:
        conn.execute(
            "INSERT INTO meetings (project_id, ref, meeting_date) VALUES (1, 'MOM-01', '2026-09-03')"
        )
        for subject in ("First", "Second", "Third"):
            conn.execute(
                "INSERT INTO meeting_items (project_id, meeting_id, ref, subject, sort_order) "
                "VALUES (1, 1, '1.1', ?, 0)",
                (subject,),
            )
    conn.close()

    init_db(database)

    conn = connect(database)
    try:
        rows = conn.execute(
            "SELECT ref, subject FROM meeting_items ORDER BY sort_order, id"
        ).fetchall()
    finally:
        conn.close()
    assert [(r["ref"], r["subject"]) for r in rows] == [
        ("1.1", "First"), ("1.2", "Second"), ("1.3", "Third")
    ]


def test_the_edit_payload_survives_a_subject_full_of_quotes(minuted):
    """The values the edit form is filled from ride in an HTML attribute; a
    quote in the text must not cut the attribute short and break editing."""
    import json
    import re

    post(minuted, "/projects/1/minutes/items", meeting_id="1",
         subject='The "quay" wall & <levels>', agreement="Re-issue 'as agreed'")
    body = page(minuted, "/projects/1/minutes/meetings/1")

    payloads = re.findall(r"data-item='([^']*)'", body)
    assert len(payloads) == 4
    import html as html_module

    decoded = [json.loads(html_module.unescape(p)) for p in payloads]
    assert any(d["subject"] == 'The "quay" wall & <levels>' for d in decoded)
    assert any(d["agreement"] == "Re-issue 'as agreed'" for d in decoded)


def test_moving_an_item_comes_back_to_the_minutes_it_was_moved_in(minuted):
    """The arrows sit on the meeting page, so that is where they return to —
    landing on the register instead loses the list you were reordering."""
    response = minuted.post("/projects/1/minutes/items/1/move",
                            data={"direction": "down", "return": "meeting"})
    assert response.headers["Location"].endswith("/minutes/meetings/1")


def test_the_move_buttons_say_to_come_back_to_the_meeting(minuted):
    body = page(minuted, "/projects/1/minutes/meetings/1")
    for direction in ("up", "down"):
        marker = f'<input type="hidden" name="direction" value="{direction}">'
        assert body.count(marker) == 3
    # Each move form carries the return, next to its direction.
    assert body.count('name="return" value="meeting"') >= 6
