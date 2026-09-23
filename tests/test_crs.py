"""The comment response sheets, in the database everything else is in.

What these pin down is the part that made the sheets worth moving out of a
browser: a sheet is against a document the register numbered, a comment is owed
by one of the project's own trades, and what goes back to the client is the
client's own workbook rather than a rendering of it.
"""

from __future__ import annotations

import io

import pytest

from app import crs_excel, crs_store as store
from app.crs_sheet import today


def text(response) -> str:
    return response.get_data(as_text=True)


def a_form(rows, **info) -> bytes:
    """A client's review response form with those comments typed onto it."""
    blank = crs_excel.blank_form()
    form = crs_excel.read(blank)
    return crs_excel.write(blank, rows, form["header_row"], form["columns"],
                           authored=True, info=info, info_at=form["info_at"],
                           overall_at=form["overall_at"])


FIVE = [{"sn": str(n), "reviewer": "Client PM", "source": "Clause 2.1",
         "observation": f"Comment {n} about the piling", "discipline": "Marine",
         "reference": "MR-01", "returned_code": "C" if n == 1 else "B",
         "response": "", "signoff": "open"}
        for n in range(1, 6)]


@pytest.fixture()
def uploaded(signed_in):
    """A sheet on the project, read in from a client's form."""
    data = a_form(FIVE, project_name="Demo", engineer="A. Mitwally", drf_ref="DRF-9")
    answer = signed_in.post(
        "/crs/1/sheets", data={"workbook": (io.BytesIO(data), "client.xlsx")},
        content_type="multipart/form-data")
    assert answer.status_code in (301, 302)
    return int(answer.headers["Location"].rstrip("/").split("/")[-1])


def a_comment(app, sheet_id: int, which: int = 0) -> dict:
    with app.app_context():
        return store.comments_for(sheet_id)[which]


# --- the door and the list ---------------------------------------------------

def test_the_sheets_are_part_of_this_application_now(signed_in):
    """Not a second application sharing a domain: one sign-in, one database,
    and a link from the front door that goes to a page in here."""
    door = text(signed_in.get("/"))
    assert "/crs" in door

    page = signed_in.get("/crs/")
    assert page.status_code == 200
    assert "Comment response sheets" in text(page)


def test_a_stranger_is_sent_to_sign_in(client):
    answer = client.get("/crs/")
    assert answer.status_code in (301, 302)
    assert "/login" in answer.headers["Location"]


# --- reading a client's form -------------------------------------------------

def test_a_form_comes_in_whole(signed_in, app, uploaded):
    with app.app_context():
        sheet = store.sheet(uploaded)
        comments = store.comments_for(uploaded)

    assert sheet["drf_ref"] == "DRF-9"
    assert sheet["engineer"] == "A. Mitwally"
    assert len(comments) == 5
    assert comments[0]["observation"] == "Comment 1 about the piling"
    assert comments[0]["returned_code"] == "C"


def test_a_comment_is_owed_by_one_of_the_projects_trades(signed_in, app, uploaded):
    """The client writes a discipline in their own words. Matching it to a real
    trade is what lets the resource plan see the work."""
    row = a_comment(app, uploaded)
    with app.app_context():
        trades = {t["id"]: t["name"] for t in store.trades_of(1)}

    assert row["discipline"] == "Marine"
    assert trades[row["trade_id"]] == "Marine"


def test_a_discipline_that_fits_nobody_is_left_owing_nobody(signed_in, app):
    """Wrongly owing a trade a comment is worse than plainly owing nobody."""
    data = a_form([dict(FIVE[0], discipline="Landscaping")])
    answer = signed_in.post("/crs/1/sheets",
                            data={"workbook": (io.BytesIO(data), "c.xlsx")},
                            content_type="multipart/form-data")
    sheet_id = int(answer.headers["Location"].rstrip("/").split("/")[-1])

    assert a_comment(app, sheet_id)["trade_id"] is None


def test_something_that_is_not_a_comment_register_is_refused(signed_in):
    answer = signed_in.post(
        "/crs/1/sheets", data={"workbook": (io.BytesIO(b"not a workbook"), "x.xlsx")},
        content_type="multipart/form-data", follow_redirects=True)
    assert "would not open" in text(answer)


def test_a_newer_copy_keeps_the_answers_already_written(signed_in, app, uploaded):
    """A second file is a revision of the register, not more rows to add to it —
    but the answers here are ours and are kept against the comment they answer."""
    row = a_comment(app, uploaded)
    signed_in.post(f"/crs/1/comments/{row['id']}", data={"response": "Repiled."})

    again = a_form([dict(one, observation=one["observation"] + " (clarified)") for one in FIVE])
    signed_in.post(f"/crs/1/sheets/{uploaded}/upload",
                   data={"workbook": (io.BytesIO(again), "c2.xlsx")},
                   content_type="multipart/form-data")

    with app.app_context():
        comments = store.comments_for(uploaded)
    assert len(comments) == 5, "replaced, not appended to"
    assert comments[0]["observation"].endswith("(clarified)"), "theirs, as they now hold it"
    assert comments[0]["response"] == "Repiled.", "ours, kept"


# --- answering ---------------------------------------------------------------

def test_a_cell_saves_where_it_stands(signed_in, app, uploaded):
    """Forty comments and no Save button: what is typed is saved as it is typed,
    and the sheet's own counts come back with it because closing one moves them."""
    row = a_comment(app, uploaded)
    answer = signed_in.post(f"/crs/1/comments/{row['id']}",
                            data={"response": "Revised on rev C2."},
                            headers={"Accept": "application/json"})

    said = answer.get_json()
    assert said["ok"] is True
    assert said["comment"]["response"] == "Revised on rev C2."
    assert said["sheet"]["answered"] == 1
    assert said["sheet"]["open"] == 5


def test_signing_a_comment_off_dates_it_and_re_opening_clears_that(signed_in, app, uploaded):
    row = a_comment(app, uploaded)
    signed_in.post(f"/crs/1/comments/{row['id']}", data={"signoff": "closed"})
    assert a_comment(app, uploaded)["closed_on"] == today()

    signed_in.post(f"/crs/1/comments/{row['id']}", data={"signoff": "open"})
    assert a_comment(app, uploaded)["closed_on"] == ""


def test_a_comment_signed_off_is_never_late(signed_in, app, uploaded):
    row = a_comment(app, uploaded)
    signed_in.post(f"/crs/1/comments/{row['id']}",
                   data={"due_date": "01/01/2020", "signoff": "open"})
    with app.app_context():
        assert store.overview(1)["late"] == 1

    signed_in.post(f"/crs/1/comments/{row['id']}", data={"signoff": "closed"})
    with app.app_context():
        assert store.overview(1)["late"] == 0


def test_the_clients_words_are_not_ours_to_edit_from_the_sheet(signed_in, app, uploaded):
    """The response column is ours; the observation is theirs. Both are here, so
    a register typed in by hand can be corrected — but not by the live cells,
    which is why only ours are on the page."""
    page = text(signed_in.get(f"/crs/1/sheets/{uploaded}"))
    assert 'data-crs-cell="response"' in page
    assert 'data-crs-cell="returned_code"' in page
    assert 'data-crs-cell="observation"' not in page


def test_signing_off_everything_answered(signed_in, app, uploaded):
    with app.app_context():
        rows = store.comments_for(uploaded)
    for row in rows[:3]:
        signed_in.post(f"/crs/1/comments/{row['id']}", data={"response": "Done."})

    signed_in.post(f"/crs/1/sheets/{uploaded}/close-answered")
    with app.app_context():
        counted = store.overview(1)
    assert counted["closed"] == 3
    assert counted["open"] == 2


def test_a_viewer_cannot_answer_a_comment(client, app, database):
    """Reading a project does not mean answering its client."""
    from app.auth import hash_password
    from app.db import connect

    conn = connect(database)
    with conn:
        conn.execute("INSERT INTO users (email, name, password_hash, role) VALUES (?,?,?,?)",
                     ("reader@example.com", "Reader", hash_password("changeme123"), "user"))
        conn.execute("INSERT INTO project_members (project_id, user_id, role) "
                     "VALUES (1, (SELECT id FROM users WHERE email='reader@example.com'), 'viewer')")
    conn.close()

    with app.app_context():
        sheet_id = store.create_sheet(1, title="A sheet")
        comment_id = store.add_comment(sheet_id, observation="Something")

    client.post("/login", data={"email": "reader@example.com", "password": "changeme123"})
    answer = client.post(f"/crs/1/comments/{comment_id}", data={"response": "no"},
                         headers={"Accept": "application/json"})
    assert answer.status_code == 403
    with app.app_context():
        assert store.comments_for(sheet_id)[0]["response"] == ""


# --- handing it back ---------------------------------------------------------

def test_what_goes_back_is_the_clients_own_workbook(signed_in, app, uploaded):
    row = a_comment(app, uploaded)
    signed_in.post(f"/crs/1/comments/{row['id']}", data={"response": "Repiled.",
                                                         "returned_code": "B"})

    answer = signed_in.get(f"/crs/1/sheets/{uploaded}.xlsx")
    assert answer.status_code == 200
    assert answer.mimetype == crs_excel.MIMETYPE
    assert "DRF-9.xlsx" in answer.headers["Content-Disposition"]

    back = crs_excel.read(answer.data)
    assert len(back["comments"]) == 5
    assert back["comments"][0]["response"] == "Repiled."
    assert back["comments"][0]["observation"] == "Comment 1 about the piling"
    # The overall code is the worst one on the sheet: a package with one
    # "revise and resubmit" in it is being resubmitted.
    assert back["overall_code"] == "B"


def test_a_sheet_raised_here_goes_out_on_the_blank_form(signed_in, app):
    answer = signed_in.post("/crs/1/sheets", data={"title": "Piling method statement",
                                                   "received_on": "01/09/2026"})
    sheet_id = int(answer.headers["Location"].rstrip("/").split("/")[-1])
    signed_in.post(f"/crs/1/sheets/{sheet_id}/comments",
                   data={"observation": "The sequence is not shown.", "discipline": "Marine"})

    got = signed_in.get(f"/crs/1/sheets/{sheet_id}.xlsx")
    assert got.status_code == 200
    back = crs_excel.read(got.data)
    assert len(back["comments"]) == 1
    assert back["comments"][0]["observation"] == "The sequence is not shown."
    assert back["info"]["title"] == "Piling method statement"


def test_a_comment_added_here_is_owed_by_the_sheets_own_allowance(signed_in, app):
    answer = signed_in.post("/crs/1/sheets", data={"title": "A sheet",
                                                   "received_on": "01/09/2026"})
    sheet_id = int(answer.headers["Location"].rstrip("/").split("/")[-1])
    signed_in.post(f"/crs/1/sheets/{sheet_id}/comments", data={"observation": "Something"})

    assert a_comment(app, sheet_id)["due_date"] == "2026-09-15", "fourteen days on"


# --- threads and files -------------------------------------------------------

def test_a_thread_hangs_off_the_comment_it_is_about(signed_in, app, uploaded):
    row = a_comment(app, uploaded)
    signed_in.post(f"/crs/1/comments/{row['id']}/messages",
                   data={"body": "Ask the marine lead before answering this."})

    with app.app_context():
        said = store.messages_for(row["id"])
    assert len(said) == 1
    assert said[0]["author"] == "Administrator" or said[0]["author"]
    assert "marine lead" in said[0]["body"]

    page = text(signed_in.get(f"/crs/1/sheets/{uploaded}"))
    assert "marine lead" in page


def test_a_file_on_a_comment_comes_back_out(signed_in, app, uploaded):
    row = a_comment(app, uploaded)
    signed_in.post(f"/crs/1/comments/{row['id']}/files",
                   data={"file": (io.BytesIO(b"%PDF-1.4 marked up"), "markup.pdf")},
                   content_type="multipart/form-data")

    with app.app_context():
        held = [f for f in store.files_for(uploaded) if f["name"] == "markup.pdf"]
    assert len(held) == 1

    got = signed_in.get(f"/crs/1/files/{held[0]['id']}")
    assert got.status_code == 200
    assert got.data == b"%PDF-1.4 marked up"


def test_a_file_on_another_project_is_not_reachable_from_this_one(signed_in, app, uploaded):
    """Every file hangs off a sheet in the end, and a sheet belongs to a project."""
    with app.app_context():
        held = store.original(uploaded)
    answer = signed_in.get(f"/crs/2/files/{held['id']}")
    assert answer.status_code == 404


# --- what the programme should feel ------------------------------------------

def test_a_code_c_sheet_says_the_submission_goes_round_again(signed_in, app, uploaded):
    with app.app_context():
        said = store.sheet_is_rework(uploaded)
    assert said["code"] == "C"
    assert said["sends_it_back"] is True
    assert said["comments"] == 5


def test_a_code_c_sheet_moves_the_deliverable_it_is_about(signed_in, app, uploaded):
    """Reading the sheet and moving the programme are one action: the
    deliverable takes another revision and a new submission date."""
    from app.db import query_one

    with app.app_context():
        from app.db import execute, insert

        task = dict(query_one("SELECT * FROM tasks WHERE project_id = 1 ORDER BY id LIMIT 1"))
        # Put the deliverable where a client's comments can land on it: nothing
        # can come back that has not gone out.
        execute("UPDATE tasks SET status_key = 'submitted' WHERE id = ?", (task["id"],))
        # And hang a document off it for the sheet to be against.
        kind = insert("INSERT INTO document_kinds (project_id, key, name, code) "
                      "VALUES (1, 'dwg', 'Drawings', 'DWG')")
        doc = insert("INSERT INTO submittals (project_id, task_id, kind_id, number, title) "
                     "VALUES (1, ?, ?, 'D-001', 'A drawing')", (task["id"], kind))

    signed_in.post(f"/crs/1/sheets/{uploaded}", data={"submittal_id": doc})
    answer = signed_in.post(f"/crs/1/sheets/{uploaded}/rework",
                            data={"comments_date": "01/09/2026"}, follow_redirects=True)

    with app.app_context():
        after = dict(query_one("SELECT * FROM tasks WHERE id = ?", (task["id"],)))
    assert after["revision"] == int(task["revision"] or 0) + 1
    assert after["status_key"] != "submitted", "back to where the rework starts"
    assert "Code C" in text(answer)


def test_a_sheet_against_nothing_has_no_deliverable_to_move(signed_in, app, uploaded):
    """Better to say so than to guess at which line on the programme it meant."""
    answer = signed_in.post(f"/crs/1/sheets/{uploaded}/rework", follow_redirects=True)
    assert "not against a deliverable" in text(answer)
