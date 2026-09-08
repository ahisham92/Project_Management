"""Every document the app hands out, kept as it went out.

A deck built on Tuesday is not the deck the same dates build today, because the
project has moved. So "let me see the presentation Ola sent the client" cannot
be answered by rebuilding one from the same query string — only by keeping
Ola's copy.
"""

from __future__ import annotations

import io
import zipfile


def text(response) -> str:
    return response.get_data(as_text=True)


def _kinds(app) -> list[str]:
    from app.service import load_documents

    with app.app_context():
        return [row["kind"] for row in load_documents(1)]


def test_a_deck_is_kept_as_the_bytes_that_went_out(signed_in, app):
    got = signed_in.get("/projects/1/assistant/deck.pptx?start=01/08/2026&end=06/09/2026")
    assert got.status_code == 200

    from app.service import load_documents

    with app.app_context():
        kept = load_documents(1)
    assert len(kept) == 1
    assert kept[0]["kind"] == "deck"
    assert kept[0]["bytes"] == len(got.data)
    assert "01/08/2026 to 06/09/2026" in kept[0]["note"]
    assert kept[0]["user_name"]


def test_the_copy_is_the_file_and_not_a_fresh_one(signed_in, app):
    """The point of keeping it is to be able to see what somebody actually
    sent, so it comes back byte for byte even after the project has moved."""
    first = signed_in.get(
        "/projects/1/assistant/deck.pptx?start=01/08/2026&end=06/09/2026").data
    signed_in.post("/projects/1/tasks/1/progress",
                   data={"status_key": "submitted", "data_date": "01/09/2026"})

    again = signed_in.get(
        "/projects/1/assistant/deck.pptx?start=01/08/2026&end=06/09/2026").data
    assert again != first, "the same dates build a different deck once things move"

    from app.service import load_documents

    with app.app_context():
        oldest = min(load_documents(1), key=lambda row: row["id"])
    kept = signed_in.get(f"/projects/1/assistant/documents/{oldest['id']}")
    assert kept.data == first


def test_the_exports_from_every_tab_are_kept(signed_in, app):
    signed_in.post("/projects/1/minutes/attendees", data={"name": "Ola"})
    answer = signed_in.post("/projects/1/minutes/meetings",
                            data={"meeting_date": "03/09/2026", "ref": "MOM-01",
                                  "title": "Kickoff"})
    meeting_id = int(answer.headers["Location"].rstrip("/").split("/")[-1])

    signed_in.get("/projects/1/setup/export")
    signed_in.get("/projects/1/schedule.xlsx")
    signed_in.get("/projects/1/schedule/links.xlsx")
    signed_in.get(f"/projects/1/minutes/meetings/{meeting_id}.docx")
    signed_in.get("/projects/1/minutes/register.docx")
    signed_in.get("/projects/1/minutes/agenda.docx")
    signed_in.get("/projects/1/assistant/deck.pptx?start=01/08/2026&end=06/09/2026")

    kept = set(_kinds(app))
    for wanted in ("setup", "schedule", "dependencies", "minutes", "register",
                   "agenda", "deck"):
        assert wanted in kept, wanted


def test_they_are_listed_with_who_made_them_and_when(signed_in):
    signed_in.get("/projects/1/setup/export")
    body = text(signed_in.get("/projects/1/assistant/documents"))
    assert "The setup sheet" in body
    assert "Project Manager" in body, "who made it"
    assert "Setup sheet" in body, "what kind it is"

    # And the most recent few sit on Carmen's tab, where somebody would look.
    assert "The setup sheet" in text(signed_in.get("/projects/1/assistant"))


def test_only_the_most_recent_are_kept(signed_in, app):
    """A database is not an archive, and the nightly backup carries all of it."""
    from app.service import KEEP_DOCUMENTS, keep_document, load_documents

    with app.app_context():
        for number in range(KEEP_DOCUMENTS + 5):
            keep_document(1, "deck", f"Deck {number}", "d.pptx", "application/x",
                          f"deck {number}".encode())
        kept = load_documents(1, 200)

    assert len(kept) == KEEP_DOCUMENTS
    assert kept[0]["name"] == f"Deck {KEEP_DOCUMENTS + 4}", "the newest is still there"


def test_a_document_from_another_project_is_not_reachable(signed_in, app):
    from app.service import keep_document

    with app.app_context():
        made = keep_document(1, "deck", "Ours", "d.pptx", "application/x", b"ours")
    assert signed_in.get(f"/projects/1/assistant/documents/{made}").status_code == 200
    assert signed_in.get(f"/projects/2/assistant/documents/{made}").status_code in (403, 404)


def test_failing_to_keep_a_copy_never_costs_the_download(signed_in, monkeypatch):
    """The person asked for a document; they get their document."""
    import app.service as service

    def _no(*args, **kwargs):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(service, "keep_document", _no)
    got = signed_in.get("/projects/1/setup/export")
    assert got.status_code == 200
    assert got.data[:2] == b"PK"


def test_the_kept_deck_still_opens_as_a_powerpoint(signed_in, app):
    signed_in.get("/projects/1/assistant/deck.pptx?start=01/08/2026&end=06/09/2026")
    from app.service import load_documents

    with app.app_context():
        kept = load_documents(1)[0]
    got = signed_in.get(f"/projects/1/assistant/documents/{kept['id']}")
    with zipfile.ZipFile(io.BytesIO(got.data)) as book:
        assert "ppt/presentation.xml" in book.namelist()
