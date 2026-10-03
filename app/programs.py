"""Which programs on this site an account may open.

The site holds five programs — Project Management, the Comment Response Sheet,
Triton, the Specs Writer and MarineTwin. The administrator ticks which of them each account sees. A program
an account is not given is left off its front page and refused by address too,
so knowing the URL does not get anybody in.

Accounts made before the choice existed have no list stored and keep every
program until the administrator changes them. Administrators always see all.
"""

from __future__ import annotations

from typing import Any, Iterable

# key, name as the front page shows it
PROGRAMS: list[tuple[str, str]] = [
    ("pm", "Project Management"),
    ("crs", "Comment Response Sheet"),
    ("triton", "Triton"),
    ("specs", "THEMIS (structural specifications)"),
    ("marinetwin", "MarineTwin"),
]
KEYS = [key for key, _ in PROGRAMS]
NAMES = dict(PROGRAMS)

# The Flask blueprints that belong to each program.
BLUEPRINTS = {
    "portfolio": "pm",
    "projects": "pm",
    "meetings": "pm",
    "assistant": "pm",
    "crs": "crs",
    "specs": "specs",
    "marine": "marinetwin",
}


def allowed(user: Any) -> list[str]:
    """The program keys the account may open, in front-page order."""
    if user is None:
        return []
    if user["role"] == "admin":
        return list(KEYS)
    stored = user["programs"] if "programs" in user.keys() else None
    if stored is None:
        return list(KEYS)
    chosen = {part.strip() for part in stored.split(",")}
    return [key for key in KEYS if key in chosen]


def may_open(user: Any, program: str) -> bool:
    return program in allowed(user)


def pack(chosen: Iterable[str]) -> str:
    """The stored form of a set of ticked programs; unknown keys are dropped."""
    picked = set(chosen)
    return ",".join(key for key in KEYS if key in picked)


def account_in(control: Any, environ: dict[str, Any]) -> Any | None:
    """The signed-in account behind a request that reaches a mounted program."""
    from flask import session

    from .db import query_one

    with control.request_context(environ):
        user_id = session.get("user_id")
        if not user_id:
            return None
        return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def guard(control: Any, inner: Any, program: str) -> Any:
    """A mounted WSGI program that only answers accounts given ``program``."""
    import json
    from urllib.parse import quote

    def guarded(environ: dict[str, Any], start_response: Any) -> Any:
        user = account_in(control, environ)
        if user is not None and may_open(user, program):
            return inner(environ, start_response)
        path = environ.get("SCRIPT_NAME", "") + environ.get("PATH_INFO", "")
        if user is not None:
            body = f"Your account has not been given {NAMES[program]}. Ask the administrator.".encode()
            start_response("403 Forbidden", [("Content-Type", "text/plain; charset=utf-8")])
            return [body]
        if "/api/" in path:
            body = json.dumps({"detail": "Sign in first."}).encode()
            start_response("401 Unauthorized", [("Content-Type", "application/json")])
            return [body]
        start_response("302 Found", [("Location", "/login?next=" + quote(path, safe="/"))])
        return [b""]

    return guarded
