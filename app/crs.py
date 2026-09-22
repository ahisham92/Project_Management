"""Where the comment response sheet application is plugged in.

The CRS is a separate application with its own data, not a tab of this one. It
is mounted in front of ``/crs`` as a WSGI application of its own, so it keeps
its own routes, templates and database and this app never has to know how it
works. Everything either of them shares — the host, the domain, the one web app
on PythonAnywhere — they share by sitting side by side under one address.

**To install one**, put a package called ``crs`` beside ``app`` with a
``create_app()`` that returns a WSGI application (a Flask app is one)::

    crs/__init__.py     def create_app(): ... -> Flask

That is the whole contract. ``run.py`` and ``wsgi.py`` look for it on the way
up; find it and they mount it, do not and ``/crs`` says so instead of breaking.
Nothing else in this application changes either way, which is the point: the
front door can be built, reviewed and deployed before the thing behind it
exists.

Point ``CRS_APP`` at something else — ``mypackage.factory:build`` — to mount an
application that does not live in a package called ``crs``. Point ``CRS_URL``
at a full address to send the door somewhere else entirely, for a CRS that is
deployed on its own and only wants linking to.

**A broken CRS never takes the site down.** If the package is there but will not
import, project control still serves and ``/crs`` says what went wrong. One
application failing to start is not a reason for the other to stop answering,
and a host that serves nothing at all is the hardest kind of thing to diagnose.
"""

from __future__ import annotations

import importlib
import os
from typing import Any, Callable

# Where the door goes, and what it is called on the way there.
MOUNT = "/crs"
NAME = "Comment Response Sheet"

DEFAULT_FACTORY = "crs:create_app"

# What the door can be: nothing installed, something broken, something mounted
# here, or something deployed elsewhere that only wants linking to.
MISSING, BROKEN, MOUNTED, AWAY = "missing", "broken", "mounted", "away"


def wanted() -> str:
    """The factory to import, as ``module:attribute``."""
    return (os.environ.get("CRS_APP") or DEFAULT_FACTORY).strip()


def elsewhere() -> str:
    """A CRS deployed on its own, which the door should link to rather than mount."""
    return (os.environ.get("CRS_URL") or "").strip()


def _factory(target: str) -> tuple[Callable[[], Any] | None, str]:
    """The factory and an empty string, or None and what went wrong."""
    module_name, _, attribute = target.partition(":")
    attribute = attribute or "create_app"
    if not module_name:
        return None, f"“{target}” is not a module:attribute"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        # The package simply is not there, which is the ordinary case before
        # one has been installed rather than a fault to report.
        if (exc.name or "").split(".")[0] == module_name.split(".")[0]:
            return None, ""
        return None, f"{module_name} imports {exc.name}, which is not installed"
    except Exception as exc:                          # noqa: BLE001 - reported, not swallowed
        return None, f"{module_name} would not import: {exc}"

    made = getattr(module, attribute, None)
    if made is None:
        return None, f"{module_name} has no {attribute}()"
    if not callable(made):
        return None, f"{module_name}.{attribute} is not something that can be called"
    return made, ""


def state() -> dict[str, Any]:
    """What is behind the door, and what to say about it.

    Never raises. The front page calls this, and a comment response sheet that
    will not import is not a reason for project control to stop answering.
    """
    away = elsewhere()
    if away:
        return {"name": NAME, "state": AWAY, "href": away, "ready": True,
                "external": True, "how": away, "trouble": ""}

    target = wanted()
    made, trouble = _factory(target)
    if made is not None:
        return {"name": NAME, "state": MOUNTED, "href": MOUNT, "ready": True,
                "external": False, "how": target, "trouble": ""}
    return {"name": NAME, "state": BROKEN if trouble else MISSING, "href": MOUNT,
            "ready": False, "external": False, "how": target, "trouble": trouble}


def load() -> Any | None:
    """The CRS application, or None when there is not one to mount.

    Never raises, for the same reason: a host serving nothing at all is the
    hardest kind of thing to diagnose, and the page behind ``/crs`` can say far
    more about a broken import than a stack trace in a log nobody opens.
    """
    if elsewhere():
        return None
    made, trouble = _factory(wanted())
    if made is None:
        return None
    try:
        return made()
    except Exception:                                 # noqa: BLE001 - see above
        return None


def describe() -> dict[str, Any]:
    """What the front door needs to know: where it goes, and whether it is there."""
    return state()
