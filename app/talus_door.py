"""Talus, the slope stability program, mounted in front of ``/talus``.

Talus checks cut slopes, embankments and revetments (rock and Accropode armour)
for every load case, earthquakes included, live as the numbers are typed, with a
3D view of how the slope would fail. Its calculations run in the browser; the
server only keeps each person's projects.

The code is the ``talus_app`` package beside ``app``, copied in from its own
repository (``ahisham92/talus``) the way Talus is.

**One sign-in.** Talus answers only somebody signed in here and given
Talus, and is told who is asking rather than asking again.

**What is let in without the sign-in** is decided by Talus (``is_public``).

**Its projects** go under ``talus`` in the data directory unless
``TALUS_DATA_DIR`` says otherwise,
so a ``git pull`` never touches them.

**A broken Talus never takes the site down.** If the package is missing or
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

from .db import data_dir
from .programs import account_in, may_open

MOUNT = "/talus"
NAME = "Talus"
KEY = "talus"

_state: dict[str, Any] = {}


def data_folder() -> Path:
    """Where Talus keeps its projects."""
    return Path(os.environ.get("TALUS_DATA_DIR") or data_dir() / "talus")


def _import() -> tuple[Any | None, str]:
    """Talus's WSGI module and an empty string, or None and what went wrong."""
    try:
        return importlib.import_module("talus_app.wsgi"), ""
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "talus_app":
            return None, ""
        return None, f"Talus needs {exc.name}, which is not installed — pip install -r requirements.txt"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"Talus would not import: {exc}"


def describe() -> dict[str, Any]:
    """What the front door needs to know: where it goes, and whether it is there."""
    if not _state:
        module, trouble = _import()
        _state.update(ready=module is not None, trouble=trouble)
    return {"name": NAME, "href": MOUNT + "/", **_state}


def _login(user: Any) -> str:
    return user["username"] or user["email"] or ""


def _refuse(start_response: Callable, status: str, message: str) -> list[bytes]:
    start_response(status, [("Content-Type", "application/json")])
    return [json.dumps({"error": message}).encode()]


def load(control: Flask) -> Callable | None:
    """Talus behind project control's sign-in, or None when it is not installed. Never raises."""
    os.environ.setdefault("TALUS_DATA_DIR", str(data_folder()))

    module, trouble = _import()
    _state.update(ready=module is not None, trouble=trouble)
    if module is None:
        return None
    try:
        module.get_app()
    except Exception as exc:                          # noqa: BLE001 - a folder it cannot write, say
        _state.update(ready=False, trouble=f"Talus could not start: {exc}")
        return None
    talus = module.application

    def guarded(environ: dict[str, Any], start_response: Callable) -> Iterable[bytes]:
        mount = environ.get("SCRIPT_NAME", "")
        path = environ.get("PATH_INFO", "")
        if path == "":
            start_response("301 Moved Permanently", [("Location", mount + "/")])
            return [b""]
        # Nobody but this door may say who is asking; a browser's headers all
        # arrive under HTTP_*, so this only clears anything set further in.
        environ.pop(module.SITE_KEY, None)
        if module.is_public(path):
            return talus(environ, start_response)
        user = account_in(control, environ)
        if user is None:
            if path.startswith("/api/"):
                return _refuse(start_response, "401 Unauthorized", "Sign in to use Talus.")
            start_response("302 Found", [("Location", "/login?next=" + quote(mount + path, safe="/"))])
            return [b""]
        if not may_open(user, KEY):
            if path.startswith("/api/"):
                return _refuse(start_response, "403 Forbidden", "Your account has not been given Talus.")
            start_response("302 Found", [("Location", "/?not=talus")])
            return [b""]
        environ[module.SITE_KEY] = {
            "id": str(user["id"]),
            "login": _login(user),
            "name": user["name"] or _login(user),
        }
        return talus(environ, start_response)

    return guarded


def mounts(control: Flask) -> dict[str, Callable]:
    """``{"/talus": app}`` when Talus is installed, otherwise nothing."""
    talus = load(control)
    return {MOUNT: talus} if talus is not None else {}
