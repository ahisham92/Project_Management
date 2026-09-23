"""The front door, and the place the older sheet is plugged in.

Two jobs live behind one address. What is worth pinning down is the joinery:
the door offers both, project control is where it always was, and the comment
response sheets are part of this application now — while the one that kept its
work in each person's browser is still mounted at ``/crs/classic``, so nothing
left in anybody's browser is stranded.
"""

from __future__ import annotations

from app import crs as mount


def text(response) -> str:
    return response.get_data(as_text=True)


# --- the door -----------------------------------------------------------------

def test_the_site_opens_on_a_choice(signed_in):
    page = text(signed_in.get("/"))

    assert "Project Management" in page
    assert "Comment Response Sheet" in page
    assert 'href="/projects"' in page
    assert 'href="/crs/"' in page


def test_the_door_is_not_open_to_a_stranger(client):
    """Both applications are for the same team, so one sign-in covers the pair
    and the choice is not something to show a passer-by."""
    answer = client.get("/")
    assert answer.status_code in (301, 302)
    assert "/login" in answer.headers["Location"]


def test_signing_in_lands_on_the_choice(client, app):
    answer = client.post("/login", data={"email": "admin@example.com",
                                         "password": "changeme123"})
    assert answer.status_code in (301, 302)
    assert answer.headers["Location"].rstrip("/").endswith("") is True
    assert "/projects" not in answer.headers["Location"]


def test_project_management_is_where_it_always_was(signed_in):
    """Moved off the root, but the same page — every link to it still resolves,
    because they all go through url_for rather than a typed address."""
    page = text(signed_in.get("/projects"))
    assert "How to use the Portfolio tab" in page


# --- what is plugged in -------------------------------------------------------

def test_the_older_sheet_is_still_mounted(signed_in, monkeypatch):
    """It is a package beside this one, found by its factory rather than wired
    in by hand — and it is out of the way at /crs/classic, because /crs is the
    real one now."""
    monkeypatch.delenv("CRS_URL", raising=False)
    monkeypatch.delenv("CRS_APP", raising=False)

    said = mount.state()
    assert said["state"] == mount.MOUNTED
    assert said["ready"] is True
    assert said["href"] == "/crs/classic"
    # And the door on the front page is open rather than marked shut.
    assert "door-shut" not in text(signed_in.get("/"))


def test_the_comment_response_sheets_are_part_of_this_application(signed_in):
    """Not mounted, not a second database: a blueprint on the same app, so a
    sheet is against a document the register numbered."""
    page = signed_in.get("/crs/")
    assert page.status_code == 200
    assert "Comment response sheets" in text(page)


def test_the_sheet_is_served_to_somebody_signed_in(signed_in):
    from crs import create_app

    page = create_app(secret="test").test_client()
    with page.session_transaction() as kept:
        kept["user_id"] = 1

    answer = page.get("/")
    assert answer.status_code == 200
    body = answer.get_data(as_text=True)
    assert "CRS Review" in body
    assert "crs-review-v3" in body            # its own storage, untouched
    assert answer.headers["Cache-Control"] == "no-store"


def test_the_sheet_is_not_served_to_a_stranger():
    """One sign-in for the pair is what the front door promises, and a second
    application on the same address should not be the way around it."""
    from crs import create_app

    answer = create_app(secret="test").test_client().get("/")
    assert answer.status_code in (301, 302)
    assert "/login" in answer.headers["Location"]


def test_the_door_still_opens_with_the_older_sheet_gone(signed_in, monkeypatch):
    """Nothing about the front door depends on it any more. The sheets are
    here; that one is a link for whoever still has work in their browser."""
    monkeypatch.setenv("CRS_APP", "nothing_of_that_name:create_app")
    monkeypatch.delenv("CRS_URL", raising=False)

    page = text(signed_in.get("/"))
    assert "Comment Response Sheet" in page
    assert "/crs/classic" not in page
    assert signed_in.get("/crs/").status_code == 200


def test_a_crs_somewhere_else_is_linked_rather_than_mounted(monkeypatch):
    """One that is deployed on its own only wants pointing at."""
    monkeypatch.setenv("CRS_URL", "https://crs.example.com/")

    said = mount.describe()
    assert said["href"] == "https://crs.example.com/"
    assert said["ready"] is True
    assert said["external"] is True
    # And nothing is mounted in front of /crs, because there is nothing to mount.
    assert mount.load() is None


def test_an_installed_crs_is_found_by_its_factory(monkeypatch):
    made = {}

    class Pretend:
        def __call__(self, *_args, **_kwargs):
            return []

    def factory():
        made["called"] = True
        return Pretend()

    module = type("module", (), {"create_app": factory})
    monkeypatch.setattr(mount.importlib, "import_module", lambda _name: module)
    monkeypatch.delenv("CRS_URL", raising=False)

    assert mount.describe()["ready"] is True
    assert isinstance(mount.load(), Pretend)
    assert made["called"] is True


def test_a_factory_somewhere_other_than_crs_is_honoured(monkeypatch):
    monkeypatch.setenv("CRS_APP", "mypackage.factory:build")
    monkeypatch.delenv("CRS_URL", raising=False)

    assert mount.wanted() == "mypackage.factory:build"
    # Nothing of that name exists, so it reads as not installed rather than
    # blowing up on the way to the front page.
    assert mount.state()["ready"] is False
    assert mount.state()["state"] == mount.MISSING


def test_a_crs_that_is_present_but_broken_says_so_and_does_not_take_the_site_down(monkeypatch):
    """One application failing to start is not a reason for the other to stop
    answering, and a host serving nothing at all is the hardest kind of thing
    to diagnose."""
    def explode(_name):
        raise ValueError("the CRS has a bug in it")

    monkeypatch.setattr(mount.importlib, "import_module", explode)
    monkeypatch.delenv("CRS_URL", raising=False)

    said = mount.state()
    assert said["state"] == mount.BROKEN
    assert said["ready"] is False
    assert "the CRS has a bug in it" in said["trouble"]
    assert mount.load() is None        # nothing mounted, nothing raised


def test_a_missing_package_is_not_reported_as_broken(monkeypatch):
    """Before one is installed is the ordinary case, not a fault."""
    monkeypatch.delenv("CRS_URL", raising=False)
    monkeypatch.setenv("CRS_APP", "nothing_of_that_name:create_app")

    said = mount.state()
    assert said["state"] == mount.MISSING
    assert said["trouble"] == ""


def test_a_factory_that_will_not_build_leaves_the_door_shut(monkeypatch):
    def factory():
        raise RuntimeError("no database")

    module = type("module", (), {"create_app": factory})
    monkeypatch.setattr(mount.importlib, "import_module", lambda _name: module)
    monkeypatch.delenv("CRS_URL", raising=False)

    assert mount.load() is None


def test_the_wsgi_entry_point_serves_both(monkeypatch):
    """What the host imports: project control at the root, the CRS in front of
    /crs when there is one."""
    import importlib

    import wsgi

    monkeypatch.delenv("CRS_URL", raising=False)
    monkeypatch.delenv("CRS_APP", raising=False)
    again = importlib.reload(wsgi)

    assert again.application is again.app
    # The sheet is installed, so the two are joined above Flask: project
    # control at the root, the sheet in front of /crs.
    assert again.application.__class__.__name__ == "DispatcherMiddleware"
    assert mount.MOUNT in again.application.mounts
    assert mount.MOUNT == "/crs/classic", "the real sheets answer at /crs"
