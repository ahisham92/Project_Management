"""Pontoon, the floating pontoon and pile designer, mounted in front of ``/pontoon``.

Pontoon designs floating pontoons (concrete, framed, modular and wave
attenuators) and their guide piles to AS 3962, AS/NZS 1170, AS 4100, AS 3600 and
AS 2159, with 3D views, mode shapes and an IFC export for Revit. Its calculations
run in the browser; the server only keeps each person's projects.

The code is the ``pontoon_app`` package beside ``app``, copied in from its own
repository (``ahisham92/pontoon``) the way Talus is.

**One sign-in.** Pontoon answers only somebody signed in here and given
Pontoon, and is told who is asking rather than asking again.

**What is let in without the sign-in** is decided by Pontoon (``is_public``).

**Its projects** go under ``pontoon`` in the data directory unless
``PONTOON_DATA_DIR`` says otherwise,
so a ``git pull`` never touches them.

**A broken Pontoon never takes the site down.** If the package is missing or
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

MOUNT = "/pontoon"
NAME = "Pontoon"
KEY = "pontoon"

_state: dict[str, Any] = {}


def data_folder() -> Path:
    """Where Pontoon keeps its projects."""
    return Path(os.environ.get("PONTOON_DATA_DIR") or data_dir() / "pontoon")


def _import() -> tuple[Any | None, str]:
    """Pontoon's WSGI module and an empty string, or None and what went wrong."""
    try:
        return importlib.import_module("pontoon_app.wsgi"), ""
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "pontoon_app":
            return None, ""
        return None, f"Pontoon needs {exc.name}, which is not installed — pip install -r requirements.txt"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"Pontoon would not import: {exc}"


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
    """Pontoon behind project control's sign-in, or None when it is not installed. Never raises."""
    os.environ.setdefault("PONTOON_DATA_DIR", str(data_folder()))

    module, trouble = _import()
    _state.update(ready=module is not None, trouble=trouble)
    if module is None:
        return None
    try:
        module.get_app()
    except Exception as exc:                          # noqa: BLE001 - a folder it cannot write, say
        _state.update(ready=False, trouble=f"Pontoon could not start: {exc}")
        return None
    pontoon = module.application

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
            return pontoon(environ, start_response)
        user = account_in(control, environ)
        if user is None:
            if path.startswith("/api/"):
                return _refuse(start_response, "401 Unauthorized", "Sign in to use Pontoon.")
            start_response("302 Found", [("Location", "/login?next=" + quote(mount + path, safe="/"))])
            return [b""]
        if not may_open(user, KEY):
            if path.startswith("/api/"):
                return _refuse(start_response, "403 Forbidden", "Your account has not been given Pontoon.")
            start_response("302 Found", [("Location", "/?not=pontoon")])
            return [b""]
        environ[module.SITE_KEY] = {
            "id": str(user["id"]),
            "login": _login(user),
            "name": user["name"] or _login(user),
        }
        return pontoon(environ, start_response)

    return guarded


def mounts(control: Flask) -> dict[str, Callable]:
    """``{"/pontoon": app}`` when Pontoon is installed, otherwise nothing."""
    pontoon = load(control)
    return {MOUNT: pontoon} if pontoon is not None else {}
