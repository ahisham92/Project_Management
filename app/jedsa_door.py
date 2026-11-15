"""JEDSA, the structural analysis and design program, mounted in front of ``/jedsa``.

JEDSA analyses 2D and 3D frames and shells, seismic to EN 1998 included, and
designs to Eurocodes, ACI and BS. It is one self-contained page: every analysis
runs in the browser and a model is saved as a file on the person's own machine,
so the server only hands out the page and keeps nothing.

The code is the ``jedsa_app`` package beside ``app``, copied in from its own
repository (``ahisham92/JEDSA``) the way Talus is.

**One sign-in.** JEDSA answers only somebody signed in here and given
JEDSA, and is told who is asking rather than asking again.

**What is let in without the sign-in** is decided by JEDSA (``is_public``).

**A broken JEDSA never takes the site down.** If the package is missing or
will not import, everything else keeps serving and the door says so.
"""

from __future__ import annotations

import importlib
import json
from typing import Any, Callable, Iterable
from urllib.parse import quote

from flask import Flask

from .programs import account_in, may_open

MOUNT = "/jedsa"
NAME = "JEDSA"
KEY = "jedsa"

_state: dict[str, Any] = {}


def _import() -> tuple[Any | None, str]:
    """JEDSA's WSGI module and an empty string, or None and what went wrong."""
    try:
        return importlib.import_module("jedsa_app.wsgi"), ""
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "jedsa_app":
            return None, ""
        return None, f"JEDSA needs {exc.name}, which is not installed — pip install -r requirements.txt"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"JEDSA would not import: {exc}"


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
    """JEDSA behind project control's sign-in, or None when it is not installed. Never raises."""
    module, trouble = _import()
    _state.update(ready=module is not None, trouble=trouble)
    if module is None:
        return None
    try:
        module.get_app()
    except Exception as exc:                          # noqa: BLE001 - reported on the door
        _state.update(ready=False, trouble=f"JEDSA could not start: {exc}")
        return None
    jedsa = module.application

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
            return jedsa(environ, start_response)
        user = account_in(control, environ)
        if user is None:
            if path.startswith("/api/"):
                return _refuse(start_response, "401 Unauthorized", "Sign in to use JEDSA.")
            start_response("302 Found", [("Location", "/login?next=" + quote(mount + path, safe="/"))])
            return [b""]
        if not may_open(user, KEY):
            if path.startswith("/api/"):
                return _refuse(start_response, "403 Forbidden", "Your account has not been given JEDSA.")
            start_response("302 Found", [("Location", "/?not=jedsa")])
            return [b""]
        environ[module.SITE_KEY] = {
            "id": str(user["id"]),
            "login": _login(user),
            "name": user["name"] or _login(user),
        }
        return jedsa(environ, start_response)

    return guarded


def mounts(control: Flask) -> dict[str, Callable]:
    """``{"/jedsa": app}`` when JEDSA is installed, otherwise nothing."""
    jedsa = load(control)
    return {MOUNT: jedsa} if jedsa is not None else {}
