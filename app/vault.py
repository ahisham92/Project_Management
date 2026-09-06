"""Where the Google Drive credentials live: a small file, never the database.

A refresh token is a key to somebody's Drive. Two places it must not be:

* **The database.** The nightly backup copies the database to Drive, so a token
  kept there would be uploaded — a key to the safe, inside the safe, on the
  internet.
* **Git.** It sits in the same directory as the database, which is ignored, so
  it cannot be committed by accident.

The environment is still read first, so a host configured with `GOOGLE_*`
variables keeps working exactly as it did and nothing has to be moved. This
file is for connecting from the browser, where there is no shell to set an
environment variable in.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

FILE_NAME = "drive.json"

# What may be kept here. Anything else in the file is ignored rather than
# handed on, so a stray key cannot become a request parameter.
FIELDS = ("client_id", "client_secret", "refresh_token", "folder_id", "file_name",
          "account", "connected_at", "auto", "hour", "zone")


def path() -> Path:
    """Beside the database, wherever that is."""
    from .db import live_database

    return Path(live_database()).parent / FILE_NAME


def read() -> dict[str, Any]:
    """What has been saved, or nothing at all."""
    where = path()
    if not where.exists():
        return {}
    try:
        held = json.loads(where.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: held[key] for key in FIELDS if key in held} if isinstance(held, dict) else {}


def write(values: Mapping[str, Any]) -> None:
    """Saves, readable only by the account the app runs as."""
    where = path()
    where.parent.mkdir(parents=True, exist_ok=True)
    kept = {key: values[key] for key in FIELDS if key in values}

    # Written beside and renamed, so an interrupted write cannot leave half a
    # file where the credentials were.
    spare = where.with_name(where.name + ".new")
    spare.write_text(json.dumps(kept, indent=2), "utf-8")
    try:
        os.chmod(spare, 0o600)
    except OSError:
        pass                                       # Windows, and it is still fine
    spare.replace(where)


def update(**values: Any) -> dict[str, Any]:
    """Changes some of it and leaves the rest alone."""
    held = read()
    held.update({key: value for key, value in values.items() if key in FIELDS})
    write(held)
    return held


def forget() -> None:
    """Disconnects: the token is gone, not merely unused."""
    where = path()
    if where.exists():
        where.unlink()


def settings(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The Drive settings in force: the environment first, then this file.

    The environment wins so that a server set up the old way is never
    overridden by something clicked in a browser.
    """
    from .drive import settings_from_env

    held = read()
    from_env = settings_from_env(env if env is not None else os.environ)
    merged: dict[str, Any] = dict(held)
    for key, value in from_env.items():
        if value:
            merged[key] = value

    merged.setdefault("auto", bool(held.get("auto", True)))
    merged.setdefault("hour", int(held.get("hour", 0) or 0))
    merged.setdefault("zone", str(held.get("zone") or "Africa/Cairo"))
    merged["from_env"] = bool(from_env.get("refresh_token"))
    return merged


def schedule() -> dict[str, Any]:
    """When the nightly backup is meant to run, and whether it is switched on."""
    held = settings()
    return {
        "auto": bool(held.get("auto", True)),
        "hour": int(held.get("hour", 0) or 0),
        "zone": str(held.get("zone") or "Africa/Cairo"),
    }
