"""GeoProMax, the settlement program, mounted in front of ``/geopromax``.

GeoProMax works out how much the ground settles under foundations, tanks and
embankments, and how fast: stresses, immediate settlement, consolidation and
creep, over the plan and with time, live as the numbers are typed. Its
calculations run in the browser; the server only keeps each person's projects.

The code is the ``geopromax_app`` package beside ``app``, copied in from its own
repository (``ahisham92/geo-promax``) the way Talus is.

**One sign-in.** GeoProMax answers only somebody signed in here and given
GeoProMax, and is told who is asking rather than asking again.

**What is let in without the sign-in** is decided by GeoProMax (``is_public``).

**Its projects** go under ``geopromax`` in the data directory unless
``GEOPROMAX_DATA_DIR`` says otherwise,
so a ``git pull`` never touches them.

**A broken GeoProMax never takes the site down.** If the package is missing or
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

MOUNT = "/geopromax"
NAME = "GeoProMax"
KEY = "geopromax"

_state: dict[str, Any] = {}


def data_folder() -> Path:
    """Where GeoProMax keeps its projects."""
    return Path(os.environ.get("GEOPROMAX_DATA_DIR") or data_dir() / "geopromax")


def _import() -> tuple[Any | None, str]:
    """GeoProMax's WSGI module and an empty string, or None and what went wrong."""
    try:
        return importlib.import_module("geopromax_app.wsgi"), ""
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "geopromax_app":
            return None, ""
        return None, f"GeoProMax needs {exc.name}, which is not installed — pip install -r requirements.txt"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"GeoProMax would not import: {exc}"


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
    """GeoProMax behind project control's sign-in, or None when it is not installed. Never raises."""
    os.environ.setdefault("GEOPROMAX_DATA_DIR", str(data_folder()))

    module, trouble = _import()
    _state.update(ready=module is not None, trouble=trouble)
    if module is None:
        return None
    try:
        module.get_app()
    except Exception as exc:                          # noqa: BLE001 - a folder it cannot write, say
        _state.update(ready=False, trouble=f"GeoProMax could not start: {exc}")
        return None
    inner = module.application

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
            return inner(environ, start_response)
        user = account_in(control, environ)
        if user is None:
            if path.startswith("/api/"):
                return _refuse(start_response, "401 Unauthorized", "Sign in to use GeoProMax.")
            start_response("302 Found", [("Location", "/login?next=" + quote(mount + path, safe="/"))])
            return [b""]
        if not may_open(user, KEY):
            if path.startswith("/api/"):
                return _refuse(start_response, "403 Forbidden", "Your account has not been given GeoProMax.")
            start_response("302 Found", [("Location", "/?not=geopromax")])
            return [b""]
        environ[module.SITE_KEY] = {
            "id": str(user["id"]),
            "login": _login(user),
            "name": user["name"] or _login(user),
        }
        return inner(environ, start_response)

    return guarded


def mounts(control: Flask) -> dict[str, Callable]:
    """``{"/geopromax": app}`` when GeoProMax is installed, otherwise nothing."""
    inner = load(control)
    return {MOUNT: inner} if inner is not None else {}
