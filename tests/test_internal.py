"""The internal weekly register, and reading either register as at a date.

The client's minutes and the internal weekly list are the same kind of record
kept for two audiences, so they share every rule and differ only in which
register an item belongs to. What is new here is the date: "where did this
stand on the fifteenth?" is a different question from "where does it stand?",
and it is the one a client asks.
"""

from __future__ import annotations

from app.minutes import KIND_TITLES, as_at, normalise_kind, progress_note, rewind


def text(response) -> str:
    return response.get_data(as_text=True)


def item(**extra):
    return dict({"id": 1, "ref": "1", "subject": "Something", "status": "open",
                 "raised_date": "2026-01-05", "closed_date": ""}, **extra)


# --- which register a record belongs to -------------------------------------

def test_the_two_registers():
    assert normalise_kind("internal") == "internal"
    assert normalise_kind("client") == "client"
    assert KIND_TITLES["client"] == "Minutes of meeting"
    assert KIND_TITLES["internal"] == "Internal weekly"


def test_anything_unreadable_is_the_client_register():
    """The one that existed before, so an old link still lands where it did."""
    assert normalise_kind("") == "client"
    assert normalise_kind(None) == "client"
    assert normalise_kind("nonsense") == "client"


# --- the register as it stood on a date -------------------------------------

def test_an_item_closed_since_was_still_open_then():
    was = as_at(item(status="closed", closed_date="2026-02-10"), "2026-01-20")
    assert was["status"] == "open"
    assert was["closed_date"] == ""
    assert was["was_reopened"] is True          # it is closed now, just not then
    assert was["closed_after"] == "2026-02-10"


def test_an_item_closed_before_the_date_was_closed_then():
    was = as_at(item(status="closed", closed_date="2026-01-10"), "2026-01-20")
    assert was["status"] == "closed"
    assert was["closed_date"] == "2026-01-10"


def test_an_item_closed_on_the_day_itself_counts_as_closed():
    was = as_at(item(status="closed", closed_date="2026-01-20"), "2026-01-20")
    assert was["status"] == "closed"


def test_an_item_raised_after_the_date_did_not_exist_yet():
    assert as_at(item(raised_date="2026-03-01"), "2026-01-20") is None


def test_an_item_raised_on_the_day_itself_is_there():
    assert as_at(item(raised_date="2026-01-20"), "2026-01-20") is not None


def test_an_item_with_no_raised_date_is_always_there():
    """Rather than vanishing from every historical view because a date is blank."""
    assert as_at(item(raised_date=""), "2020-01-01") is not None


def test_a_closed_item_with_no_closing_date_is_taken_as_closed():
    """It was closed before anyone started recording the day, so the only
    honest reading is that it was already closed."""
    was = as_at(item(status="closed", closed_date=""), "2026-01-20")
    assert was["status"] == "closed"


def test_the_whole_register_rewinds_together():
    items = [
        item(id=1, ref="1", status="closed", closed_date="2026-02-10"),
        item(id=2, ref="2"),
        item(id=3, ref="3", raised_date="2026-03-01"),
    ]
    assert [(r["ref"], r["status"]) for r in rewind(items, "2026-01-20")] == \
        [("1", "open"), ("2", "open")]
    assert [(r["ref"], r["status"]) for r in rewind(items, "2026-02-15")] == \
        [("1", "closed"), ("2", "open")]
    assert len(rewind(items, "2026-03-05")) == 3


def test_no_date_is_the_register_as_it_is():
    items = [item(status="closed", closed_date="2026-02-10")]
    assert rewind(items, "")[0]["status"] == "closed"


def test_the_note_at_the_top_says_what_was_where():
    rows = rewind([item(id=1, status="closed", closed_date="2026-01-10"),
                   item(id=2), item(id=3, raised_date="2026-06-01")], "2026-01-20")
    assert progress_note(rows, "2026-01-20") == \
        "As at 20/01/2026: 2 items raised, 1 closed, 1 still open"


# --- the tab, and the two registers apart -----------------------------------

def add_internal(client, subject="Issue the mooring note", **extra):
    return client.post("/projects/1/minutes/items",
                       data=dict({"kind": "internal", "subject": subject}, **extra),
                       follow_redirects=True)


def add_client(client, subject="Approve the layout", **extra):
    return client.post("/projects/1/minutes/items",
                       data=dict({"kind": "client", "subject": subject}, **extra),
                       follow_redirects=True)


def test_the_internal_register_has_a_tab_and_a_path_of_its_own(signed_in):
    body = text(signed_in.get("/projects/1/internal/register"))
    assert "Internal weekly" in body
    assert "kept for us, not for the client" in body
    assert '/projects/1/internal"' in body and '/projects/1/minutes"' in body


def active_tab(body: str) -> str:
    import re

    found = re.search(r'<a href="([^"]+)"\s*\n?\s*class="active">', body)
    return found.group(1) if found else ""


def test_the_tab_marks_which_register_is_open(signed_in):
    """Both registers share an endpoint, so marking the active one on the
    endpoint alone would light up whichever was listed last."""
    assert active_tab(text(signed_in.get("/projects/1/internal/register"))) == "/projects/1/internal"
    assert active_tab(text(signed_in.get("/projects/1/minutes"))) == "/projects/1/minutes"


def test_an_item_belongs_to_the_register_it_was_raised_in(signed_in):
    add_internal(signed_in)
    add_client(signed_in)

    from app.service import load_items

    with signed_in.application.app_context():
        internal = load_items(1, kind="internal")
        client = load_items(1, kind="client")
    assert [i["subject"] for i in internal] == ["Issue the mooring note"]
    assert [i["subject"] for i in client] == ["Approve the layout"]


def test_neither_register_shows_the_other_s_items(signed_in):
    add_internal(signed_in, "Internal only")
    add_client(signed_in, "Client only")

    assert "Internal only" in text(signed_in.get("/projects/1/internal/register?filter=all"))
    assert "Client only" not in text(signed_in.get("/projects/1/internal/register?filter=all"))
    assert "Client only" in text(signed_in.get("/projects/1/minutes?filter=all"))
    assert "Internal only" not in text(signed_in.get("/projects/1/minutes?filter=all"))


def test_a_meeting_belongs_to_a_register_too(signed_in):
    from app.service import load_meetings

    signed_in.post("/projects/1/minutes/meetings",
                   data={"kind": "internal", "title": "Weekly", "meeting_date": "05/01/2026"})
    signed_in.post("/projects/1/minutes/meetings",
                   data={"kind": "client", "title": "Progress no. 1", "meeting_date": "06/01/2026"})

    with signed_in.application.app_context():
        assert [m["title"] for m in load_meetings(1, "internal")] == ["Weekly"]
        assert [m["title"] for m in load_meetings(1, "client")] == ["Progress no. 1"]
        assert len(load_meetings(1)) == 2          # both, when nothing is asked


def test_an_item_added_inside_a_meeting_takes_that_meeting_s_register(signed_in):
    """Even if the form says otherwise, so the two can never disagree."""
    from app.db import query_one
    from app.service import load_meetings

    signed_in.post("/projects/1/minutes/meetings",
                   data={"kind": "internal", "title": "Weekly", "meeting_date": "05/01/2026"})
    with signed_in.application.app_context():
        meeting = load_meetings(1, "internal")[0]["id"]

    signed_in.post("/projects/1/minutes/items",
                   data={"kind": "client", "meeting_id": str(meeting), "subject": "In the weekly"})
    with signed_in.application.app_context():
        row = query_one("SELECT kind FROM meeting_items WHERE subject = 'In the weekly'")
    assert row["kind"] == "internal"


def test_a_change_made_on_the_internal_list_comes_back_to_it(signed_in):
    answer = add_internal(signed_in)
    assert "/projects/1/internal" in answer.request.path or "Internal weekly" in text(answer)


# --- reading it as at a date, through the app -------------------------------

def closed_on(client, item_id: int, when: str):
    """Close an item on the day it was actually closed."""
    return client.post(f"/projects/1/minutes/items/{item_id}",
                       data={"kind": "internal", "status": "closed", "closed_date": when},
                       follow_redirects=True)


def only_item(client, kind="internal"):
    from app.service import load_items

    with client.application.app_context():
        return load_items(1, kind=kind)[0]["id"]


def test_the_day_an_item_was_closed_is_editable(signed_in):
    """Stamped with today when nothing is said, but a register kept up after
    the fact needs the day it really happened."""
    from app.db import query_one

    add_internal(signed_in)
    closed_on(signed_in, only_item(signed_in), "10/01/2026")
    with signed_in.application.app_context():
        row = query_one("SELECT status, closed_date FROM meeting_items WHERE id = ?",
                        (only_item(signed_in),))
    assert row["status"] == "closed"
    assert row["closed_date"] == "2026-01-10"


def test_the_register_reads_as_it_stood_on_a_date(signed_in):
    add_internal(signed_in, "Closed in January", raised_date="05/01/2026")
    add_internal(signed_in, "Still open", raised_date="05/01/2026")
    add_internal(signed_in, "Raised in March", raised_date="01/03/2026")

    from app.service import load_items

    with signed_in.application.app_context():
        first = [i for i in load_items(1, kind="internal")
                 if i["subject"] == "Closed in January"][0]["id"]
    closed_on(signed_in, first, "10/01/2026")

    on_the_eighth = text(signed_in.get("/projects/1/internal/register?filter=all&as_at=08/01/2026"))
    assert "Closed in January" in on_the_eighth
    assert "Raised in March" not in on_the_eighth
    assert "2 items raised, 0 closed, 2 still open" in on_the_eighth

    on_the_twentieth = text(signed_in.get("/projects/1/internal/register?filter=all&as_at=20/01/2026"))
    assert "2 items raised, 1 closed, 1 still open" in on_the_twentieth

    in_april = text(signed_in.get("/projects/1/internal/register?filter=all&as_at=01/04/2026"))
    assert "3 items raised, 1 closed, 2 still open" in in_april


def test_the_page_says_plainly_that_it_is_not_today(signed_in):
    add_internal(signed_in)
    body = text(signed_in.get("/projects/1/internal/register?as_at=20/01/2026"))
    assert "Showing the register as it stood on 20/01/2026" in body
    assert "Back to today" in body


def test_without_a_date_it_is_the_live_register(signed_in):
    add_internal(signed_in)
    body = text(signed_in.get("/projects/1/internal"))
    assert "as it stood on" not in body


def test_the_client_register_reads_as_at_a_date_too(signed_in):
    """The question comes from the client, so it is asked of their register as
    much as of ours."""
    add_client(signed_in, "Old business", raised_date="05/01/2026")
    add_client(signed_in, "New business", raised_date="01/06/2026")
    body = text(signed_in.get("/projects/1/minutes?filter=all&as_at=01/02/2026"))
    assert "Old business" in body and "New business" not in body


def test_an_unreadable_date_is_simply_ignored(signed_in):
    add_internal(signed_in)
    body = text(signed_in.get("/projects/1/internal/register?as_at=the+fifth+of+never"))
    assert "as it stood on" not in body


# --- taking it to the client ------------------------------------------------

def test_the_word_register_is_the_internal_one_when_asked_for_it(signed_in):
    add_internal(signed_in, "Internal only")
    add_client(signed_in, "Client only")

    answer = signed_in.get("/projects/1/internal/register.docx?filter=all")
    assert answer.status_code == 200
    assert "internal" in answer.headers["Content-Disposition"]

    import zipfile, io

    with zipfile.ZipFile(io.BytesIO(answer.data)) as book:
        body = book.read("word/document.xml").decode()
    assert "Internal only" in body
    assert "Client only" not in body
    assert "Internal weekly" in body


def test_the_document_says_which_date_it_was_read_at(signed_in):
    import io
    import zipfile

    add_internal(signed_in, "Old business", raised_date="05/01/2026")
    answer = signed_in.get("/projects/1/internal/register.docx?filter=all&as_at=20/01/2026")
    with zipfile.ZipFile(io.BytesIO(answer.data)) as book:
        body = book.read("word/document.xml").decode()
    assert "As at 20/01/2026" in body


def test_each_register_has_its_own_agenda(signed_in):
    add_internal(signed_in, "Internal only")
    add_client(signed_in, "Client only")

    internal = text(signed_in.get("/projects/1/internal/agenda"))
    assert "Internal weekly — agenda" in internal
    assert "Internal only" in internal and "Client only" not in internal

    client = text(signed_in.get("/projects/1/minutes/agenda"))
    assert "Minutes of meeting — agenda" in client
    assert "Client only" in client and "Internal only" not in client


def test_the_internal_agenda_downloads_under_its_own_name(signed_in):
    answer = signed_in.get("/projects/1/internal/agenda.docx")
    assert answer.status_code == 200
    assert "internal-agenda" in answer.headers["Content-Disposition"]


def test_a_member_can_keep_the_internal_list(client, app):
    """Minutes are a working record, and so is the weekly list."""
    client.post("/register", data={"name": "Member", "email": "m6@example.com",
                                   "password": "longenough1"})
    with app.app_context():
        from app.db import connect

        conn = connect(app.config["DATABASE"])
        with conn:
            user = conn.execute("SELECT id FROM users WHERE email = 'm6@example.com'").fetchone()
            conn.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (1, ?, 'member')",
                         (user["id"],))
        conn.close()

    assert client.get("/projects/1/internal/register").status_code == 200
    assert add_internal(client).status_code == 200


def test_the_tiles_count_the_same_day_the_table_shows(signed_in):
    """Today's open count above a table of how things stood in January would
    put two different days on one page."""
    add_internal(signed_in, "Closed in January", raised_date="05/01/2026")
    add_internal(signed_in, "Raised in June", raised_date="01/06/2026")

    from app.service import load_items

    with signed_in.application.app_context():
        first = [i for i in load_items(1, kind="internal")
                 if i["subject"] == "Closed in January"][0]["id"]
    closed_on(signed_in, first, "10/01/2026")

    live = text(signed_in.get("/projects/1/internal/register"))
    assert "1 open of 2 items" in live

    past = text(signed_in.get("/projects/1/internal/register?as_at=20/01/2026"))
    assert "0 open of 1 item" in past
