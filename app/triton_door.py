"""Triton, the quay element designer, mounted in front of ``/triton``.

Triton reads the geotechnical team's Plaxis workbook and designs the quay's
piles, walls, slab and beams from it. It is its own application — FastAPI
rather than Flask, its own pages, its own files on disk — so it is joined to
this one at the WSGI layer, the same way the older comment sheet is: one web app
on the host, one address, and neither application knows how the other works.

The code is the ``triton`` package beside ``app``. It is a copy of
https://github.com/ahisham92/triton (``src/triton``), and ``triton/SOURCE.txt``
says which commit; a newer Triton arrives the way everything else here does,
with a ``git pull``.

**One sign-in for all of it.** Nothing reaches Triton without project control's
session: a page asked for by a stranger goes to the sign-in and comes back, and
an API call gets a 401. The session is read by project control itself, so the
cookie, the key and the users table are the ones everything else uses.

**Its files** — projects, uploaded workbooks, designs — go under ``triton`` in
the data directory, beside the database, so a ``git pull`` never touches them.
``TRITON_DATA_DIR`` puts them somewhere else.

**A broken Triton never takes the site down.** If the package is missing or will
not import (a requirement not installed, most likely), everything else keeps
serving and the door on the front page says what went wrong.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote

from flask import Flask, session

from .db import data_dir, query_one

MOUNT = "/triton"
NAME = "Triton"

_state: dict[str, Any] = {}


def data_folder() -> Path:
    """Where Triton keeps its projects and workbooks."""
    return Path(os.environ.get("TRITON_DATA_DIR") or data_dir() / "triton")


def _import() -> tuple[Any | None, str]:
    """Triton's WSGI module and an empty string, or None and what went wrong."""
    try:
        return importlib.import_module("triton.wsgi"), ""
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] == "triton":
            return None, ""
        return None, f"Triton needs {exc.name}, which is not installed — pip install -r requirements.txt"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"Triton would not import: {exc}"


def describe() -> dict[str, Any]:
    """What the front door needs to know: where it goes, and whether it is there."""
    if not _state:
        module, trouble = _import()
        _state.update(ready=module is not None, trouble=trouble)
    return {"name": NAME, "href": MOUNT + "/", **_state}


def signed_in(control: Flask, environ: dict[str, Any]) -> bool:
    """Whether the request carries project control's session for a real user."""
    with control.request_context(environ):
        user_id = session.get("user_id")
        if not user_id:
            return False
        return query_one("SELECT id FROM users WHERE id = ?", (user_id,)) is not None


def load(control: Flask) -> Callable | None:
    """Triton behind project control's sign-in, or None when it is not installed.

    Never raises, for the same reason the comment sheet's mount does not: a host
    serving nothing at all is the hardest kind of thing to diagnose.
    """
    os.environ.setdefault("TRITON_DATA_DIR", str(data_folder()))
    # The link back in Triton's header.
    os.environ.setdefault("TRITON_HOME_URL", "/")
    os.environ.setdefault("TRITON_HOME_LABEL", "Project Control")

    module, trouble = _import()
    _state.update(ready=module is not None, trouble=trouble)
    if module is None:
        return None
    triton = module.application

    def guarded(environ: dict[str, Any], start_response: Callable) -> Iterable[bytes]:
        mount = environ.get("SCRIPT_NAME", "")
        path = environ.get("PATH_INFO", "")
        if path == "":
            # /triton without the slash: Triton's pages ask for their files relative to it.
            start_response("301 Moved Permanently", [("Location", mount + "/")])
            return [b""]
        if signed_in(control, environ):
            return triton(environ, start_response)
        if path.startswith("/api/"):
            body = json.dumps({"detail": "Sign in to use Triton."}).encode()
            start_response("401 Unauthorized", [("Content-Type", "application/json")])
            return [body]
        start_response("302 Found", [("Location", "/login?next=" + quote(mount + path, safe="/"))])
        return [b""]

    return guarded


def mounts(control: Flask) -> dict[str, Callable]:
    """``{"/triton": app}`` when Triton is installed, otherwise nothing."""
    triton = load(control)
    return {MOUNT: triton} if triton is not None else {}
