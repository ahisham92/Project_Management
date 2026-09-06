"""Backing everything up, and putting it back.

The Setup sheet's Excel export is one project's setup. This is every project's
everything, and the tests here are about the two things that make a backup
worth having: that it holds what it claims to, and that it restores.

Google is not called. The upload is tested against a stand-in that answers the
way Drive does, which is what proves the one thing that matters about it — the
same file is replaced rather than a second one being made.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.backup import (
    DATABASE_IN_ZIP, MANIFEST_IN_ZIP, RestoreError, build, describe, read_manifest,
    readable, restore, snapshot,
)


def text(response) -> str:
    return response.get_data(as_text=True)


# --- what a backup holds ----------------------------------------------------

def test_a_backup_holds_the_whole_database(app):
    with app.app_context():
        from app.db import live_database

        data, manifest = build(live_database())

    with zipfile.ZipFile(io.BytesIO(data)) as book:
        assert sorted(book.namelist()) == sorted([DATABASE_IN_ZIP, MANIFEST_IN_ZIP])
        assert book.read(DATABASE_IN_ZIP).startswith(b"SQLite format 3\x00")
    assert manifest["counts"]["tasks"] == 55
    assert manifest["projects"][0]["code"] == "SIBLINE-PORT"


def test_it_holds_what_the_setup_export_does_not(app):
    """Progress history, hours, minutes, dependencies, teams — none of which
    are in a setup workbook, and all of which would be lost with the file."""
    with app.app_context():
        from app.db import live_database

        _data, manifest = build(live_database())

    for kept in ("progress_updates", "time_entries", "meeting_items", "task_links",
                 "calendars", "holidays", "task_revisions", "users"):
        assert kept in manifest["counts"], f"a backup without {kept} is not a backup"


def test_the_manifest_says_what_is_inside_without_opening_it(app):
    with app.app_context():
        from app.db import live_database

        data, _ = build(live_database(), note="nightly")

    said = read_manifest(data)
    assert said["note"] == "nightly"
    assert said["taken_at"].endswith("+00:00")
    assert "restore" in said                      # how to put it back, in the file itself


def test_the_snapshot_is_taken_while_the_app_is_writing(app):
    """Copying the file could catch a half-written page; SQLite's own backup
    cannot, so the copy always opens."""
    with app.app_context():
        from app.db import connect, live_database

        busy = connect(live_database())
        busy.execute("BEGIN")
        busy.execute("UPDATE projects SET name = 'mid-write' WHERE id = 1")
        try:
            body = snapshot(live_database())
        finally:
            busy.rollback()
            busy.close()

    assert body.startswith(b"SQLite format 3\x00")
    held = sqlite3.connect(":memory:")
    held.deserialize(body) if hasattr(held, "deserialize") else None
    # Whatever the Python version, the bytes are a database that opens.
    assert len(body) > 1000


def test_a_project_added_after_the_backup_is_not_in_it(app):
    with app.app_context():
        from app.db import execute, live_database

        _first, before = build(live_database())
        execute("INSERT INTO projects (code, name, client, ntp_date, owner_id) "
                "VALUES ('LATER', 'Added later', '', '2026-01-01', 1)")
        _second, after = build(live_database())

    assert len(before["projects"]) == 1
    assert len(after["projects"]) == 2


def test_a_byte_count_reads_as_something_a_person_would_say():
    assert readable(400) == "400 bytes"
    assert readable(2048) == "2.0 KB"
    assert readable(5 * 1024 * 1024) == "5.0 MB"


# --- putting one back -------------------------------------------------------

def test_a_backup_restores_over_a_different_database(app, tmp_path):
    with app.app_context():
        from app.db import execute, live_database

        data, _ = build(live_database())
        execute("UPDATE projects SET name = 'changed since' WHERE id = 1")

    where = tmp_path / "somewhere.sqlite3"
    where.write_bytes(b"not a database at all")
    manifest = restore(data, where)

    conn = sqlite3.connect(where)
    assert conn.execute("SELECT name FROM projects WHERE id = 1").fetchone()[0] != "changed since"
    assert manifest["projects"][0]["code"] == "SIBLINE-PORT"


def test_what_was_there_is_kept_beside_the_restored_one(app, tmp_path):
    with app.app_context():
        from app.db import live_database

        data, _ = build(live_database())

    where = tmp_path / "live.sqlite3"
    where.write_bytes(b"the old one")
    restore(data, where)

    kept = list(tmp_path.glob("live.sqlite3.replaced-*"))
    assert len(kept) == 1
    assert kept[0].read_bytes() == b"the old one"


def test_it_can_be_told_not_to_keep_the_old_one(app, tmp_path):
    with app.app_context():
        from app.db import live_database

        data, _ = build(live_database())

    where = tmp_path / "live.sqlite3"
    where.write_bytes(b"the old one")
    restore(data, where, keep_old=False)
    assert not list(tmp_path.glob("live.sqlite3.replaced-*"))


def test_a_stale_write_ahead_log_is_not_replayed_over_a_restore(app, tmp_path):
    """The -wal beside a database belongs to the one that was there a moment
    ago; left behind, SQLite would replay it over what was just restored."""
    with app.app_context():
        from app.db import live_database

        data, _ = build(live_database())

    where = tmp_path / "live.sqlite3"
    where.write_bytes(b"old")
    (tmp_path / "live.sqlite3-wal").write_bytes(b"stale")
    (tmp_path / "live.sqlite3-shm").write_bytes(b"stale")
    restore(data, where)

    assert not (tmp_path / "live.sqlite3-wal").exists()
    assert not (tmp_path / "live.sqlite3-shm").exists()


def test_something_that_is_not_a_backup_is_refused(tmp_path):
    with pytest.raises(RestoreError, match="not a zip"):
        restore(b"just some bytes", tmp_path / "x.sqlite3")


def test_a_zip_of_the_wrong_thing_is_refused(tmp_path):
    held = io.BytesIO()
    with zipfile.ZipFile(held, "w") as book:
        book.writestr("holiday-photos.txt", "nope")
    with pytest.raises(RestoreError, match="not a backup of this app"):
        restore(held.getvalue(), tmp_path / "x.sqlite3")


def test_a_zip_holding_something_that_is_not_a_database_is_refused(tmp_path):
    held = io.BytesIO()
    with zipfile.ZipFile(held, "w") as book:
        book.writestr(DATABASE_IN_ZIP, b"I am not SQLite")
        book.writestr(MANIFEST_IN_ZIP, json.dumps({}))
    with pytest.raises(RestoreError, match="not a SQLite database"):
        restore(held.getvalue(), tmp_path / "x.sqlite3")


def test_nothing_is_written_when_a_backup_is_refused(tmp_path):
    where = tmp_path / "live.sqlite3"
    where.write_bytes(b"precious")
    with pytest.raises(RestoreError):
        restore(b"rubbish", where)
    assert where.read_bytes() == b"precious"


# --- Google Drive, against a stand-in ---------------------------------------

class FakeDrive:
    """Answers the way Drive does, and remembers what it was asked to do."""

    def __init__(self, existing: str = ""):
        self.existing = existing
        self.calls: list[str] = []
        self.created = 0
        self.replaced = 0
        self.body = b""

    def token(self, *_args):
        self.calls.append("token")
        return "an-access-token"

    def find(self, _token, _name, _folder=""):
        self.calls.append("find")
        return self.existing

    def create(self, _token, name, data, _folder=""):
        self.calls.append("create")
        self.created += 1
        self.body = data
        return {"id": "new-file-id", "name": name, "size": str(len(data))}

    def replace(self, _token, file_id, data):
        self.calls.append("replace")
        self.replaced += 1
        self.body = data
        return {"id": file_id, "name": "project-control-backup.zip", "size": str(len(data))}

    def install(self, monkeypatch):
        from app import drive

        monkeypatch.setattr(drive, "access_token", self.token)
        monkeypatch.setattr(drive, "find", self.find)
        monkeypatch.setattr(drive, "create", self.create)
        monkeypatch.setattr(drive, "replace", self.replace)
        return self


SETTINGS = {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh",
            "folder_id": "", "file_name": ""}


def test_the_first_backup_creates_the_file(monkeypatch):
    from app.drive import upload

    fake = FakeDrive().install(monkeypatch)
    said = upload(SETTINGS, b"the backup")

    assert fake.created == 1 and fake.replaced == 0
    assert said["replaced"] is False
    assert said["link"].endswith("/new-file-id/view")


def test_every_backup_after_that_replaces_it(monkeypatch):
    """The whole point: one file that is written over, not a folder filling up
    with a copy a day."""
    from app.drive import upload

    fake = FakeDrive(existing="the-same-file").install(monkeypatch)
    said = upload(SETTINGS, b"tonight's backup")

    assert fake.replaced == 1 and fake.created == 0
    assert said["replaced"] is True
    assert said["id"] == "the-same-file"          # the id, and so the link, do not change
    assert fake.body == b"tonight's backup"


def test_the_file_can_be_given_a_name_and_a_folder(monkeypatch):
    from app import drive

    seen = {}

    def find(_token, name, folder=""):
        seen.update(name=name, folder=folder)
        return ""

    fake = FakeDrive().install(monkeypatch)
    monkeypatch.setattr(drive, "find", find)
    drive.upload(dict(SETTINGS, file_name="ours.zip", folder_id="a-folder"), b"x")
    assert seen == {"name": "ours.zip", "folder": "a-folder"}


def test_it_refuses_to_pretend_when_nothing_is_configured():
    from app.drive import DriveError, configured, upload

    assert not configured({"client_id": "a", "client_secret": "b"})
    with pytest.raises(DriveError, match="not set up"):
        upload({"client_id": "", "client_secret": "", "refresh_token": ""}, b"x")


def test_the_credentials_come_from_the_environment_not_the_database():
    """A refresh token in the database would be carried to Drive inside the
    very backup it is the key to."""
    from app.drive import settings_from_env

    got = settings_from_env({"GOOGLE_CLIENT_ID": " id ", "GOOGLE_CLIENT_SECRET": "secret",
                             "GOOGLE_REFRESH_TOKEN": "refresh", "GOOGLE_DRIVE_FOLDER_ID": "f"})
    assert got == {"client_id": "id", "client_secret": "secret", "refresh_token": "refresh",
                   "folder_id": "f", "file_name": ""}


def test_the_consent_url_asks_for_a_refresh_token():
    """Without both of these Google hands back an hour of access and nothing
    that works tomorrow."""
    from app.drive import consent_url

    url = consent_url("an-id", "http://localhost:8765/")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "drive.file" in url                    # only files this app made


# --- the nightly run, and what it writes down -------------------------------

def test_a_run_is_written_down_so_the_screen_can_say_it_worked(app, monkeypatch):
    from app.service import last_backup, run_backup

    FakeDrive().install(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "refresh")

    with app.app_context():
        result = run_backup()
        latest = last_backup()

    assert result["ok"] and result["uploaded"]
    assert latest["ok"] == 1
    assert latest["where_to"] == "drive"
    assert latest["bytes"] > 0


def test_a_failure_is_written_down_too_rather_than_disappearing(app, monkeypatch):
    """A nightly job that dies quietly is worse than none, because it is the
    one that was being counted on."""
    from app import drive
    from app.service import last_backup, run_backup

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "refresh")

    def refuse(*_args, **_kwargs):
        raise drive.DriveError("Google said 403: quota exceeded")

    monkeypatch.setattr(drive, "access_token", refuse)

    with app.app_context():
        result = run_backup()
        latest = last_backup()

    assert result["ok"] is False
    assert "quota exceeded" in result["detail"]
    assert latest["ok"] == 0
    assert "quota exceeded" in latest["detail"]


def test_not_being_set_up_is_reported_rather_than_crashing(app, monkeypatch):
    from app.service import run_backup

    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)

    with app.app_context():
        result = run_backup()
    assert result["ok"] is False
    assert "not connected" in result["detail"]


def test_a_backup_can_be_taken_without_uploading(app, monkeypatch):
    from app.service import last_backup, run_backup

    with app.app_context():
        result = run_backup(upload_to_drive=False)
        latest = last_backup()
    assert result["ok"] and not result["uploaded"]
    assert latest["where_to"] == "local"


def test_only_the_last_twenty_runs_are_kept(app):
    """A health light, not a log."""
    from app.service import load_backup_runs, record_backup

    with app.app_context():
        for n in range(25):
            record_backup(True, "drive", n, f"run {n}")
        kept = load_backup_runs(50)
    assert len(kept) == 20
    assert kept[0]["detail"] == "run 24"


# --- the page ---------------------------------------------------------------

def test_the_backups_page_says_where_things_stand(signed_in):
    body = text(signed_in.get("/backups"))
    assert "Backups" in body
    assert "Not connected" in body                # no Google credentials in a test run
    assert "Every night" in body
    assert "python run.py backup" in body
    assert "Putting one back" in body


def test_the_page_counts_what_would_be_in_the_backup(signed_in):
    body = text(signed_in.get("/backups"))
    assert "55 deliverables" in body


def test_a_backup_downloads_as_a_zip_that_opens(signed_in):
    answer = signed_in.get("/backups/download")
    assert answer.status_code == 200
    assert answer.headers["Content-Type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(answer.data)) as book:
        assert DATABASE_IN_ZIP in book.namelist()


def test_taking_one_from_the_page_says_what_happened(signed_in):
    answer = signed_in.post("/backups/run", follow_redirects=True)
    assert "not connected" in text(answer)           # honest, rather than a silent success


def test_only_an_administrator_may_see_or_take_a_backup(client, app):
    """It is every project's data in one file, so who may download it is who
    may already see all of it."""
    client.post("/register", data={"name": "Member", "email": "m7@example.com",
                                   "password": "longenough1"})
    assert client.get("/backups", follow_redirects=True).status_code == 200
    assert "Backups are for administrators" in text(client.get("/backups", follow_redirects=True))
    assert "SQLite" not in text(client.get("/backups/download", follow_redirects=True))


def test_the_link_is_only_offered_to_administrators(signed_in, client):
    assert "/backups" in text(signed_in.get("/"))
    client.post("/logout")                        # signing out is a POST, as it should be
    client.post("/register", data={"name": "Member", "email": "m8@example.com",
                                   "password": "longenough1"}, follow_redirects=True)
    assert "/backups" not in text(client.get("/"))


# --- the HTTP itself, against a stand-in Google -----------------------------
#
# The tests above replace the four Drive functions, which proves the logic but
# not a single request. These run the real urllib code against a small server
# that answers the way Google's does, so the multipart body, the PATCH, the
# bearer header and the error parsing are all exercised for real.

class StandInGoogle:
    def __init__(self):
        import http.server
        import threading

        self.seen: list[tuple[str, str]] = []
        self.files: dict[str, dict] = {}
        self.bodies: dict[str, bytes] = {}
        self.next_id = 1
        self.fail_with: tuple[int, bytes] | None = None
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def _read(self):
                length = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(length) if length else b""

            def _reply(self, code, payload):
                body = json.dumps(payload).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):                        # noqa: N802
                import urllib.parse

                data = self._read()
                outer.seen.append(("POST", self.path))
                if outer.fail_with:
                    code, raw = outer.fail_with
                    self.send_response(code)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return

                if self.path.startswith("/token"):
                    fields = urllib.parse.parse_qs(data.decode())
                    if fields.get("grant_type") != ["refresh_token"]:
                        return self._reply(400, {"error": "unsupported_grant_type"})
                    return self._reply(200, {"access_token": "fresh-token", "expires_in": 3599})

                # A create: multipart, metadata then the bytes.
                assert self.headers["Authorization"] == "Bearer fresh-token"
                assert "multipart/related" in self.headers["Content-Type"]
                head, _, tail = data.partition(b"\r\n\r\n")
                metadata = json.loads(tail.split(b"\r\n--")[0])
                new_id = f"file-{outer.next_id}"
                outer.next_id += 1
                outer.files[new_id] = {"id": new_id, "name": metadata["name"],
                                       "parents": metadata.get("parents", [])}
                outer.bodies[new_id] = data.split(b"application/zip\r\n\r\n", 1)[1].rsplit(b"\r\n--", 1)[0]
                return self._reply(200, outer.files[new_id])

            def do_PATCH(self):                       # noqa: N802
                data = self._read()
                outer.seen.append(("PATCH", self.path))
                assert self.headers["Authorization"] == "Bearer fresh-token"
                assert self.headers["Content-Type"] == "application/zip"
                file_id = self.path.split("/files/")[1].split("?")[0]
                outer.bodies[file_id] = data
                return self._reply(200, outer.files[file_id])

            def do_GET(self):                         # noqa: N802
                import urllib.parse

                outer.seen.append(("GET", self.path))
                asked = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                wanted = asked.get("q", [""])[0]
                found = [f for f in outer.files.values() if f"name = '{f['name']}'" in wanted]
                return self._reply(200, {"files": found})

            def log_message(self, *_args):
                return

        self.server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def point(self, monkeypatch):
        from app import drive

        root = f"http://127.0.0.1:{self.port}"
        monkeypatch.setattr(drive, "TOKEN_URL", f"{root}/token")
        monkeypatch.setattr(drive, "FILES_URL", f"{root}/drive/v3/files")
        monkeypatch.setattr(drive, "UPLOAD_URL", f"{root}/upload/drive/v3/files")
        return self

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def google(monkeypatch):
    stand_in = StandInGoogle().point(monkeypatch)
    yield stand_in
    stand_in.stop()


def test_a_real_upload_creates_then_replaces_the_same_file(google):
    """Two nights running: one file on Drive, written over the second time."""
    from app.drive import upload

    first = upload(SETTINGS, b"monday's backup")
    assert first["replaced"] is False
    assert google.bodies[first["id"]] == b"monday's backup"

    second = upload(SETTINGS, b"tuesday's backup")
    assert second["replaced"] is True
    assert second["id"] == first["id"], "a second file would defeat the whole point"
    assert len(google.files) == 1
    assert google.bodies[first["id"]] == b"tuesday's backup"
    assert ("PATCH", f"/upload/drive/v3/files/{first['id']}?uploadType=media&fields=id,name,modifiedTime,size") \
        in google.seen


def test_the_zip_arrives_whole(google, app):
    """A multipart body assembled by hand is exactly where a backup would
    quietly arrive truncated."""
    from app.drive import upload

    with app.app_context():
        from app.db import live_database

        data, _ = build(live_database())

    said = upload(SETTINGS, data)
    assert google.bodies[said["id"]] == data
    with zipfile.ZipFile(io.BytesIO(google.bodies[said["id"]])) as book:
        assert DATABASE_IN_ZIP in book.namelist()


def test_the_file_is_put_in_the_folder_it_was_told_to(google):
    from app.drive import upload

    said = upload(dict(SETTINGS, folder_id="the-folder"), b"x")
    assert google.files[said["id"]]["parents"] == ["the-folder"]


def test_what_google_refuses_is_said_in_words(google):
    from app.drive import DriveError, upload

    google.fail_with = (400, json.dumps(
        {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}
    ).encode())

    with pytest.raises(DriveError) as raised:
        upload(SETTINGS, b"x")
    said = str(raised.value)
    assert "Token has been expired" in said
    assert "drive-auth" in said, "it should say what to do about it"


def test_a_host_that_cannot_reach_google_says_which_names_to_allow(monkeypatch):
    """The failure a locked-down shared host gives, which is otherwise a bare
    URLError nobody can act on."""
    from app import drive

    monkeypatch.setattr(drive, "TOKEN_URL", "http://127.0.0.1:1/token")
    with pytest.raises(drive.DriveError) as raised:
        drive.access_token("id", "secret", "refresh")
    assert "oauth2.googleapis.com" in str(raised.value)


# --- what time it is where the project is -----------------------------------
#
# "Every day at midnight" means midnight in Cairo, and Egypt puts its clocks
# forward in April and back in October. A UTC hour is right for half the year.

from datetime import datetime, timezone      # noqa: E402 - beside the tests that use it

from app import clock                        # noqa: E402
from app import vault                        # noqa: E402


def utc(month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=timezone.utc)


def test_midnight_in_cairo_is_a_different_utc_hour_in_summer_and_winter():
    assert clock.utc_hour(0, "Africa/Cairo", utc(1, 15, 12)) == "22:00"      # UTC+2
    assert clock.utc_hour(0, "Africa/Cairo", utc(7, 15, 12)) == "21:00"      # UTC+3


def test_the_offset_is_said_in_words_so_it_can_be_checked_by_eye():
    assert clock.offset_words("Africa/Cairo", utc(1, 15, 12)) == "UTC+2"
    assert clock.offset_words("Africa/Cairo", utc(7, 15, 12)) == "UTC+3"


def test_a_backup_that_has_never_run_is_owed_one():
    assert clock.due("", 0, "Africa/Cairo", utc(7, 15, 12)) is True


def test_one_taken_after_tonights_hour_is_not_owed_again():
    # 21:00 UTC on the 15th is midnight in Cairo on the 16th.
    assert clock.due("2026-07-15 21:00:00", 0, "Africa/Cairo", utc(7, 16, 5)) is False


def test_one_taken_before_tonights_hour_is_owed_again():
    assert clock.due("2026-07-14 21:00:00", 0, "Africa/Cairo", utc(7, 16, 5)) is True


def test_a_missed_night_is_caught_rather_than_waited_out():
    """Nothing ran for three days. The moment anybody looks, one is owed."""
    assert clock.due("2026-07-12 21:00:00", 0, "Africa/Cairo", utc(7, 16, 5)) is True


def test_before_the_hour_has_come_round_yesterdays_run_still_counts():
    # 18:00 UTC on the 16th is 21:00 in Cairo — tonight's midnight has not
    # arrived, so this morning's run is still the current one.
    assert clock.due("2026-07-15 21:30:00", 0, "Africa/Cairo", utc(7, 16, 18)) is False


def test_the_next_run_is_always_ahead_of_now():
    assert clock.next_run(0, "Africa/Cairo", utc(7, 16, 18)) > clock.now("Africa/Cairo", utc(7, 16, 18))


def test_egypts_rule_is_written_out_for_a_machine_with_no_timezone_database():
    """`zoneinfo` reads the system's database; a bare Windows install has none,
    and an hour out twice a year is not something to discover in October."""
    egypt = clock._Egypt()
    assert utc(1, 15, 12).astimezone(egypt).hour == 14        # UTC+2
    assert utc(7, 15, 12).astimezone(egypt).hour == 15        # UTC+3


def test_an_unreadable_stamp_is_treated_as_never_run():
    assert clock.parse_utc("") is None
    assert clock.parse_utc("nonsense") is None
    assert clock.due("nonsense", 0, "Africa/Cairo", utc(7, 16, 5)) is True


# --- where the credentials live ---------------------------------------------

def test_the_token_is_kept_beside_the_database_not_in_it(app):
    """A key to the safe, inside the safe, uploaded nightly, is not a plan."""
    with app.app_context():
        vault.write({"client_id": "abc", "refresh_token": "secret"})
        assert vault.path().parent == Path(app.config["DATABASE"]).parent
        assert vault.read()["refresh_token"] == "secret"

        # And it is nowhere in the backup that gets uploaded.
        data, _manifest = build(app.config["DATABASE"])
        assert b"secret" not in data


def test_only_the_fields_it_knows_about_are_kept(app):
    with app.app_context():
        vault.write({"client_id": "abc", "nonsense": "dropped"})
        assert vault.read() == {"client_id": "abc"}


def test_updating_leaves_the_rest_alone(app):
    with app.app_context():
        vault.write({"client_id": "abc", "client_secret": "shh"})
        vault.update(refresh_token="token")
        held = vault.read()
        assert held["client_id"] == "abc" and held["refresh_token"] == "token"


def test_disconnecting_deletes_it_rather_than_switching_it_off(app):
    with app.app_context():
        vault.write({"refresh_token": "token"})
        vault.forget()
        assert vault.read() == {}
        assert not vault.path().exists()


def test_a_half_written_file_is_not_read_as_settings(app):
    with app.app_context():
        vault.path().parent.mkdir(parents=True, exist_ok=True)
        vault.path().write_text("{ not json", "utf-8")
        assert vault.read() == {}


def test_the_environment_still_wins_so_a_configured_host_is_never_overridden(app, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "from-env")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "env-token")
    with app.app_context():
        vault.write({"client_id": "from-file", "refresh_token": "file-token"})
        held = vault.settings()
    assert held["client_id"] == "from-env"
    assert held["from_env"] is True


def test_without_the_environment_the_file_is_what_counts(app, monkeypatch):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with app.app_context():
        vault.write({"client_id": "a", "client_secret": "b", "refresh_token": "c"})
        held = vault.settings()
    assert held["refresh_token"] == "c"
    assert held["from_env"] is False


# --- whether tonight's is owed ----------------------------------------------

def _connect(app, **extra):
    with app.app_context():
        vault.write(dict({"client_id": "a", "client_secret": "b", "refresh_token": "c"}, **extra))


def test_nothing_is_owed_while_drive_is_not_connected(app, monkeypatch):
    from app.service import backup_due

    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    with app.app_context():
        vault.forget()
        assert backup_due() is False


def test_nothing_is_owed_when_the_nightly_run_is_switched_off(app):
    from app.service import backup_due

    _connect(app, auto=False)
    with app.app_context():
        assert backup_due() is False


def test_once_connected_the_first_one_is_owed(app):
    from app.service import backup_due

    _connect(app, auto=True)
    with app.app_context():
        assert backup_due() is True


def test_a_run_that_failed_does_not_count_as_a_backup(app):
    """A failed run is not a backup, and treating it as one is how a month
    goes by with nothing on Drive."""
    from app.service import backup_due, record_backup

    _connect(app, auto=True)
    with app.app_context():
        record_backup(False, "drive", 0, "Google said 403")
        assert backup_due() is True


def test_one_that_landed_settles_it_until_the_next_hour(app):
    from app.service import backup_due, record_backup

    _connect(app, auto=True)
    with app.app_context():
        record_backup(True, "drive", 1000, "Replaced it")
        assert backup_due() is False


def test_only_the_run_that_reached_drive_settles_it(app):
    """A local copy is a copy on the same disk as the thing it protects."""
    from app.service import backup_due, record_backup

    _connect(app, auto=True)
    with app.app_context():
        record_backup(True, "local", 1000, "Taken, not uploaded")
        assert backup_due() is True


# --- connecting from the browser --------------------------------------------

def test_the_page_shows_what_to_register_with_google(signed_in):
    body = text(signed_in.get("/backups"))
    assert "/backups/connected" in body            # the redirect URI to paste
    assert "Connect Google Drive" in body


def test_connecting_sends_you_to_google_with_a_state_of_our_own(signed_in):
    answer = signed_in.post("/backups/connect",
                            data={"client_id": "id.apps.googleusercontent.com",
                                  "client_secret": "GOCSPX-x"})
    assert answer.status_code == 302
    where = answer.headers["Location"]
    assert where.startswith("https://accounts.google.com/")
    assert "access_type=offline" in where and "prompt=consent" in where
    assert "state=" in where


def test_a_code_that_did_not_come_from_our_own_request_is_refused(signed_in, app):
    """Otherwise anyone who can reach this page could plant their own token,
    and tonight the database goes to a Drive nobody here owns."""
    signed_in.post("/backups/connect", data={"client_id": "a", "client_secret": "b"})
    answer = signed_in.get("/backups/connected?code=theirs&state=wrong", follow_redirects=True)
    assert "did not come back from the request this page made" in text(answer)

    with app.app_context():
        assert not vault.read().get("refresh_token")


def test_a_code_with_no_state_at_all_is_refused(signed_in, app):
    answer = signed_in.get("/backups/connected?code=theirs", follow_redirects=True)
    assert "did not come back" in text(answer)
    with app.app_context():
        assert not vault.read().get("refresh_token")


def test_google_saying_no_is_reported_rather_than_swallowed(signed_in):
    answer = signed_in.get("/backups/connected?error=access_denied", follow_redirects=True)
    assert "access_denied" in text(answer)


def test_a_good_round_trip_saves_the_token_and_the_account(signed_in, app, monkeypatch):
    from app import drive

    monkeypatch.setattr(drive, "exchange",
                        lambda *a, **k: {"refresh_token": "1//long-lived"})
    monkeypatch.setattr(drive, "access_token", lambda *a, **k: "an-hour")
    monkeypatch.setattr(drive, "about", lambda *a, **k: {"emailAddress": "me@example.com"})

    answer = signed_in.post("/backups/connect",
                            data={"client_id": "a", "client_secret": "b"})
    state = answer.headers["Location"].split("state=")[1]

    page = signed_in.get(f"/backups/connected?code=good&state={state}", follow_redirects=True)
    assert "Google Drive connected" in text(page)

    with app.app_context():
        held = vault.read()
    assert held["refresh_token"] == "1//long-lived"
    assert held["account"] == "me@example.com"
    assert "me@example.com" in text(signed_in.get("/backups"))


def test_the_same_state_cannot_be_used_twice(signed_in, app, monkeypatch):
    from app import drive

    monkeypatch.setattr(drive, "exchange", lambda *a, **k: {"refresh_token": "first"})
    monkeypatch.setattr(drive, "access_token", lambda *a, **k: "t")
    monkeypatch.setattr(drive, "about", lambda *a, **k: {})

    answer = signed_in.post("/backups/connect", data={"client_id": "a", "client_secret": "b"})
    state = answer.headers["Location"].split("state=")[1]
    signed_in.get(f"/backups/connected?code=good&state={state}")

    again = signed_in.get(f"/backups/connected?code=again&state={state}", follow_redirects=True)
    assert "did not come back" in text(again)


def test_disconnecting_forgets_the_account(signed_in, app):
    _connect(app)
    signed_in.post("/backups/disconnect", follow_redirects=True)
    with app.app_context():
        assert vault.read() == {}


def test_the_schedule_is_kept_in_the_zone_it_was_meant_in(signed_in, app):
    answer = signed_in.post("/backups/schedule",
                            data={"hour": "0", "zone": "Africa/Cairo", "auto": "1"},
                            follow_redirects=True)
    assert "00:00 Africa/Cairo" in text(answer)
    with app.app_context():
        held = vault.schedule()
    assert held == {"auto": True, "hour": 0, "zone": "Africa/Cairo"}


def test_an_impossible_hour_is_brought_back_into_the_day(signed_in, app):
    signed_in.post("/backups/schedule", data={"hour": "99", "zone": "UTC"},
                   follow_redirects=True)
    with app.app_context():
        assert vault.schedule()["hour"] == 23


def test_unticking_it_stops_the_app_taking_one_by_itself(signed_in, app):
    signed_in.post("/backups/schedule", data={"hour": "0", "zone": "UTC"},
                   follow_redirects=True)
    with app.app_context():
        assert vault.schedule()["auto"] is False


def test_only_an_administrator_may_connect_a_drive(client, app):
    from app.auth import hash_password
    from app.db import execute

    with app.app_context():
        execute("INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, 'user')",
                ("plain@example.com", "Plain", hash_password("password123")))
    client.post("/login", data={"email": "plain@example.com", "password": "password123"})

    for where in ("/backups/connect", "/backups/disconnect", "/backups/schedule"):
        answer = client.post(where, data={"client_id": "a", "client_secret": "b"},
                             follow_redirects=True)
        assert "for administrators" in text(answer)
    with app.app_context():
        assert vault.read() == {}
