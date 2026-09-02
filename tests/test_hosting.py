"""What the app needs in order to be hosted for a team: a health check,
survivable concurrent use, and a session key that outlives a restart."""

from __future__ import annotations

import os
import threading

from app.db import connect


def test_health_check_reports_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json()["status"] == "ok"


def test_health_check_needs_no_sign_in(client):
    """Hosting platforms poll this without credentials."""
    assert client.get("/healthz").status_code == 200


def test_the_connection_waits_rather_than_failing_on_a_busy_database(database):
    """SQLite allows one writer at a time. Without a wait, a second simultaneous
    write fails instantly with "database is locked" — which is exactly what
    several people using the app at once would hit."""
    conn = connect(database)
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_several_people_can_write_at_the_same_time(app, database):
    """Six people booking hours simultaneously; every write must land."""
    failures: list[object] = []

    def book(worker: int) -> None:
        try:
            client = app.test_client()
            client.post("/login", data={"email": "admin@example.com", "password": "changeme123"})
            for entry in range(8):
                response = client.post(
                    "/projects/1/time",
                    data={"trade_id": "1", "entry_date": "01/09/2026", "hours": "1",
                          "description": f"worker {worker} entry {entry}"},
                    follow_redirects=True,
                )
                if response.status_code != 200:
                    failures.append((worker, entry, response.status_code))
        except Exception as exc:  # noqa: BLE001 - the failure is the result
            failures.append((worker, repr(exc)))

    threads = [threading.Thread(target=book, args=(n,)) for n in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not failures, f"concurrent writes failed: {failures[:3]}"

    conn = connect(database)
    try:
        assert conn.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 48
    finally:
        conn.close()


def test_one_persons_progress_is_visible_to_everyone(app, database):
    """The point of hosting it: two people, one shared set of figures."""
    conn = connect(database)
    try:
        task_id = conn.execute("SELECT id FROM tasks WHERE wbs = '2.3'").fetchone()["id"]
    finally:
        conn.close()

    manager = app.test_client()
    manager.post("/login", data={"email": "admin@example.com", "password": "changeme123"})
    manager.post("/register", data={"email": "colleague@example.com", "name": "Colleague",
                                    "password": "longenough1"})

    colleague = app.test_client()
    colleague.post("/register", data={"email": "colleague@example.com", "name": "Colleague",
                                      "password": "longenough1"})
    manager.post("/projects/1/setup/unlock", data={"password": "2026"})
    manager.post("/projects/1/members", data={"email": "colleague@example.com", "role": "member"})

    colleague.post("/login", data={"email": "colleague@example.com", "password": "longenough1"})
    colleague.post(f"/projects/1/tasks/{task_id}/progress",
                   data={"status_key": "submitted", "data_date": "01/09/2026"}, follow_redirects=True)

    seen_by_manager = manager.get("/projects/1/tasks?data_date=01/09/2026").get_data(as_text=True)
    assert "Submitted to client" in seen_by_manager


def test_the_session_key_comes_from_the_environment_when_it_is_set():
    """On a host with an ephemeral disk the generated key would change on every
    restart and sign everybody out, so SECRET_KEY must win."""
    from app.auth import secret_key

    previous = os.environ.get("SECRET_KEY")
    os.environ["SECRET_KEY"] = "a-fixed-key-for-the-whole-team"
    try:
        assert secret_key() == "a-fixed-key-for-the-whole-team"
    finally:
        if previous is None:
            del os.environ["SECRET_KEY"]
        else:
            os.environ["SECRET_KEY"] = previous


# --- the files that make hosting and publishing work ------------------------

import re  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def test_render_blueprint_keeps_the_database_on_a_disk():
    service = yaml.safe_load((ROOT / "render.yaml").read_text())["services"][0]
    assert service["startCommand"] == "python run.py"
    assert service["healthCheckPath"] == "/healthz"
    # Without the disk, every deploy would start from an empty database.
    assert service["disk"]["mountPath"] == "/var/data"
    env = {e["key"]: e for e in service["envVars"]}
    assert env["DATA_DIR"]["value"] == service["disk"]["mountPath"]
    assert env["HTTPS_ONLY"]["value"] == "true"
    assert env["SECRET_KEY"]["generateValue"] is True


def _fly() -> dict:
    return tomllib.loads((ROOT / "fly.toml").read_text())


def _mounts(fly: dict) -> list[dict]:
    """Fly's own tooling writes [[mounts]] while a hand-written file often uses
    [mounts]. Both are valid TOML for the same thing, so accept either."""
    mounts = fly["mounts"]
    return mounts if isinstance(mounts, list) else [mounts]


def test_fly_configuration_mounts_a_volume_and_stays_single_machine():
    fly = _fly()
    mounts = _mounts(fly)
    assert len(mounts) == 1
    assert mounts[0]["destination"] == fly["env"]["DATA_DIR"]
    assert fly["env"]["HTTPS_ONLY"] == "true"
    assert fly["http_service"]["force_https"] is True
    assert fly["http_service"]["checks"][0]["path"] == "/healthz"
    # The database is a file on one volume, so a second machine would drift.
    assert fly["http_service"]["min_machines_running"] == 1


def test_every_config_agrees_on_the_port_the_app_listens_on():
    """Fly regenerated internal_port as 8080 while PORT still said 8000, which
    would have routed traffic to a port nothing was listening on. Each file has
    to agree with itself, or the app is simply unreachable."""
    fly = _fly()
    assert fly["http_service"]["internal_port"] == int(fly["env"]["PORT"]), (
        "fly.toml routes traffic to internal_port, so it must match the PORT the app is given"
    )

    dockerfile = (ROOT / "Dockerfile").read_text()
    docker_port = re.search(r"^ENV PORT=(\d+)", dockerfile, re.M).group(1)
    assert re.search(rf"^EXPOSE {docker_port}$", dockerfile, re.M), "EXPOSE must match ENV PORT"
    assert f"'PORT','{docker_port}'" in dockerfile, "the health check falls back to the same port"

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]["app"]
    assert str(compose["environment"]["PORT"]) == docker_port
    assert f"{docker_port}:{docker_port}" in compose["ports"]


def test_the_workflows_are_valid_and_do_what_they_say():
    tests = yaml.safe_load((ROOT / ".github/workflows/tests.yml").read_text())
    steps = " ".join(str(s) for s in tests["jobs"]["pytest"]["steps"])
    assert "pytest" in steps and "/healthz" in steps

    pages = yaml.safe_load((ROOT / ".github/workflows/pages.yml").read_text())
    upload = next(s for s in pages["jobs"]["deploy"]["steps"] if "upload-pages-artifact" in str(s.get("uses", "")))
    assert upload["with"]["path"] == "docs"

    deploy = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
    assert set(deploy["jobs"]) == {"render", "fly"}
    body = str(deploy["jobs"])
    # Both jobs must no-op when the secret is absent, so the file is safe to keep.
    assert "RENDER_DEPLOY_HOOK" in body and "FLY_API_TOKEN" in body
    assert body.count("nothing to do") == 2


def test_the_wsgi_entry_point_serves_the_app():
    """PythonAnywhere, gunicorn and uWSGI import this rather than running
    run.py, and look for a module-level `application`."""
    import os
    import tempfile

    from werkzeug.test import Client

    from app.seed import seed

    previous = {k: os.environ.get(k) for k in ("DATA_DIR", "DATABASE_FILE", "SECRET_KEY")}
    os.environ["DATA_DIR"] = tempfile.mkdtemp()
    os.environ["DATABASE_FILE"] = str(Path(tempfile.mkdtemp()) / "wsgi.sqlite")
    os.environ["SECRET_KEY"] = "wsgi-test"
    try:
        seed(os.environ["DATABASE_FILE"], quiet=True)
        import wsgi

        assert callable(wsgi.application)
        assert wsgi.app is wsgi.application, "gunicorn looks for 'app', PythonAnywhere for 'application'"
        client = Client(wsgi.application)
        assert client.get("/healthz").status_code == 200
        assert client.get("/login").status_code == 200
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_the_landing_page_has_one_line_to_edit_and_explains_itself():
    page = (ROOT / "docs/index.html").read_text()
    assert 'const APP_URL = "";' in page, "the address is set in exactly one place"
    assert "static files" in page, "it says why the app cannot live on Pages"
    assert 'id="live"' in page and 'id="setup"' in page, "both panels are present"
    assert "python run.py seed" in page
