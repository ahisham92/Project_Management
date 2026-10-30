"""Iris, the line between AI tools and the people they work for, mounted in front of ``/iris``.

A tool working on its own (the Sketch ProMax autopilot first) sends its
progress and its questions to Iris, and the person answers from their phone.
Each account connects its own tools by scanning a QR code the tool shows, and
sees only its own.

The code is the ``iris_app`` package beside ``app``, and it lives here: its
README says how any tool connects, and ``iris_app/clients`` holds the tool side
in Python and C#.

**One sign-in.** The phone pages answer only somebody signed in here, and Iris
is told who is asking rather than asking again: the account's id, so correcting
an email in the admin panel loses nobody their connected tools.

**What is let in without the sign-in** is decided by Iris (``is_public``): the
tool API, where every call carries the tool's own token and an unknown one is
refused; the page a pairing QR code opens, which only keeps the code's key on
the phone and then goes on to the signed-in pages; and the files the
home-screen app needs to load.

**Its files** — one database and the key its phone notifications are signed
with — go under ``iris`` in the data directory unless ``IRIS_DATA_DIR`` says
otherwise, so a ``git pull`` never touches them. Message bodies in it are
encrypted on the PC and the phone; nothing in it can be read here.

**A broken Iris never takes the site down.** If the package is missing or will
not import, everything else keeps serving and the door says so.
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

MOUNT = "/iris"
NAME = "Iris"
KEY = "iris"

_state: dict[str, Any] = {}


def data_folder() -> Path:
    """Where Iris keeps its database and its push key."""
    return Path(os.environ.get("IRIS_DATA_DIR") or data_dir() / "iris")


def _import() -> tuple[Any | None, str]:
    """Iris's WSGI module and an empty string, or None and what went wrong."""
    try:
        return importlib.import_module("iris_app.wsgi"), ""
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "iris_app":
            return None, ""
        return None, f"Iris needs {exc.name}, which is not installed — pip install -r requirements.txt"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"Iris would not import: {exc}"


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
    """Iris behind project control's sign-in, or None when it is not installed. Never raises."""
    os.environ.setdefault("IRIS_DATA_DIR", str(data_folder()))

    module, trouble = _import()
    _state.update(ready=module is not None, trouble=trouble)
    if module is None:
        return None
    try:
        module.get_app()
    except Exception as exc:                          # noqa: BLE001 - a folder it cannot write, say
        _state.update(ready=False, trouble=f"Iris could not start: {exc}")
        return None
    iris = module.application

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
            return iris(environ, start_response)
        user = account_in(control, environ)
        if user is None:
            if path.startswith("/api/"):
                return _refuse(start_response, "401 Unauthorized", "Sign in to use Iris.")
            start_response("302 Found", [("Location", "/login?next=" + quote(mount + path, safe="/"))])
            return [b""]
        if not may_open(user, KEY):
            if path.startswith("/api/"):
                return _refuse(start_response, "403 Forbidden", "Your account has not been given Iris.")
            start_response("302 Found", [("Location", "/?not=iris")])
            return [b""]
        environ[module.SITE_KEY] = {
            "id": str(user["id"]),
            "login": _login(user),
            "name": user["name"] or _login(user),
        }
        return iris(environ, start_response)

    return guarded


def mounts(control: Flask) -> dict[str, Callable]:
    """``{"/iris": app}`` when Iris is installed, otherwise nothing."""
    iris = load(control)
    return {MOUNT: iris} if iris is not None else {}
