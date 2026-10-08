"""Selecao+, the unit's workload and profit plan, mounted in front of ``/workload``.

Selecao+ is what the Workload application is called now; its package, its
address and its files keep the old name, so "Workload" below is the same thing.

Workload is the front end of the Workload & Profit Plan workbook: timesheets
in, projects and their deliverables, tasks, the team, and the reports built on
them. It is its own application — no framework at all, its own pages, a
workbook per unit on disk — so it is joined to this one at the WSGI layer, the
way Triton is: one web app on the host, one address, one sign-in.

The code is the ``workload_app`` package beside ``app``. It is a copy of
https://github.com/ahisham92/Workload (``workload_app``), and
``workload_app/SOURCE.txt`` says which commit.

**One sign-in.** Nothing reaches Workload without project control's session,
and Workload is told who is asking rather than asking again: the account's id
is handed over with the request and that *is* the Workload account. Its own
login page is never shown. The id rather than the email or username, because
those can be edited in the admin panel and somebody's units must not go missing
when a typo in their address is corrected.

**A unit is its owner's alone.** That rule is Workload's and it is unchanged:
somebody who opens the door for the first time has an account with nothing in
it, and sees nobody else's units. A manager gives one colleague sight of their
own figures from the Team tab, by picking them from the people who sign in
here — which is why Workload is told who those people are.

**Its files** — the accounts database and each account's workbooks — go under
``workload`` in the data directory, beside the database, so a ``git pull``
never touches them. ``WORKLOAD_DATA_DIR`` puts them somewhere else, which is
also how an installation that ran at an address of its own is brought in:
point it at the folder that one already uses.

**A broken Workload never takes the site down.** If the package is missing or
will not import, everything else keeps serving and the door says so.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from flask import Flask

from .db import connect, data_dir
from .programs import account_in, may_open

MOUNT = "/workload"
NAME = "Selecao+"
KEY = "workload"

_state: dict[str, Any] = {}


# The only Workload call let in without an AHM sign-in: it carries a key in its
# body that Workload checks, and it cannot read anything back.
KEYED = frozenset({
    ("POST", "/api/nightly/timesheets"),
})


def data_folder() -> Path:
    """Where Workload keeps its accounts and every unit's workbook."""
    return Path(os.environ.get("WORKLOAD_DATA_DIR") or data_dir() / "workload")


def _import() -> tuple[Any | None, str]:
    """Workload's WSGI module and an empty string, or None and what went wrong."""
    try:
        return importlib.import_module("workload_app.wsgi"), ""
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "workload_app":
            return None, ""
        return None, f"Workload needs {exc.name}, which is not installed — pip install -r requirements.txt"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"Workload would not import: {exc}"


def describe() -> dict[str, Any]:
    """What the front door needs to know: where it goes, and whether it is there."""
    if not _state:
        module, trouble = _import()
        _state.update(ready=module is not None, trouble=trouble)
    return {"name": NAME, "href": MOUNT + "/", **_state}


def people(control: Flask) -> list[dict[str, str]]:
    """Everybody who signs in here and has been given Workload.

    This is the list a manager picks from when giving a colleague access to
    their own figures. Names and what they sign in with only, and only of
    accounts that could open the door anyway.
    """
    conn = connect(control.config["DATABASE"])
    try:
        rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    finally:
        conn.close()
    return [{"id": row["id"], "login": _login(row), "name": row["name"] or _login(row)}
            for row in rows if may_open(row, KEY)]


def _login(user: Any) -> str:
    """What the account types to sign in: its username, or its email."""
    return user["username"] or user["email"] or ""


def load(control: Flask) -> Callable | None:
    """Workload behind project control's sign-in, or None when it is not installed.

    Never raises, for the same reason Triton's mount does not.
    """
    os.environ.setdefault("WORKLOAD_DATA_DIR", str(data_folder()))

    module, trouble = _import()
    _state.update(ready=module is not None, trouble=trouble)
    if module is None:
        return None
    try:
        module.get_app().site_people = lambda: people(control)
    except Exception as exc:                          # noqa: BLE001 - a folder it cannot write, say
        _state.update(ready=False, trouble=f"Workload could not start: {exc}")
        return None
    workload = module.application

    def guarded(environ: dict[str, Any], start_response: Callable) -> Iterable[bytes]:
        mount = environ.get("SCRIPT_NAME", "")
        path = environ.get("PATH_INFO", "")
        if path == "":
            # /workload without the slash: its pages ask for their files relative to it.
            start_response("301 Moved Permanently", [("Location", mount + "/")])
            return [b""]
        if (environ.get("REQUEST_METHOD", "GET"), path) in KEYED:
            # Sent by a machine, not a browser: a PC's nightly export, or an
            # Outlook flow's email. No AHM session comes with it; the key in its
            # body says whose unit it is, and Workload checks that key itself.
            environ.pop(module.SITE_KEY, None)
            return workload(environ, start_response)
        user = account_in(control, environ)
        if user is None:
            if path.startswith("/api/"):
                message = "Sign in to use Selecao+."
                body = json.dumps({"error": message, "errors": [message]}).encode()
                start_response("401 Unauthorized", [("Content-Type", "application/json")])
                return [body]
            start_response("302 Found", [("Location", "/login?next=" + quote(mount + path, safe="/"))])
            return [b""]
        if not may_open(user, KEY):
            if path.startswith("/api/"):
                message = "Your account has not been given Selecao+."
                body = json.dumps({"error": message, "errors": [message]}).encode()
                start_response("403 Forbidden", [("Content-Type", "application/json")])
                return [body]
            start_response("302 Found", [("Location", "/?not=workload")])
            return [b""]
        # Who is asking, said by the only party that can know. A browser cannot
        # put this key into the request: everything it sends arrives under
        # HTTP_*.
        environ[module.SITE_KEY] = {
            "id": user["id"],
            "login": _login(user),
            "name": user["name"] or _login(user),
            "home": "/",
            "label": "AHM",
            "logout": "/logout",
        }
        return workload(environ, start_response)

    return guarded


def mounts(control: Flask) -> dict[str, Callable]:
    """``{"/workload": app}`` when Workload is installed, otherwise nothing."""
    workload = load(control)
    return {MOUNT: workload} if workload is not None else {}
