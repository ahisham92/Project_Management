"""The pieces every tool needs: the errors, and turning a phrase into a record.

Split out from ``tools`` so the tools that change the setup sheet can live in
their own module without the two importing each other in a circle.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..dates import from_input, to_display


class ToolError(Exception):
    """Something the model asked for that cannot be done, said in words it can
    read and act on — a wrong reference is a thing to correct, not to crash."""


def _project(project_id: int) -> dict[str, Any]:
    from ..db import query_one
    from ..service import as_dict

    row = query_one("SELECT * FROM projects WHERE id = ?", (project_id,))
    if row is None:
        raise ToolError("That project does not exist")
    return as_dict(row)


def _deliverable(project_id: int, reference: Any) -> dict[str, Any]:
    """The deliverable the reader meant, by WBS number or by name.

    People say "1.2" and they say "the design basis report"; both have to work,
    and an ambiguous phrase has to come back as a question rather than as a
    guess about which of four lines to change.
    """
    from ..service import load_tasks

    wanted = " ".join(str(reference or "").strip().lower().split())
    if not wanted:
        raise ToolError("Say which deliverable — its WBS number, like 1.2, or its name")

    rows = load_tasks(project_id)
    exact = [t for t in rows if str(t.get("wbs") or "").strip().lower() == wanted]
    if len(exact) == 1:
        return exact[0]

    named = [t for t in rows if wanted in str(t.get("name") or "").lower()]
    if len(named) == 1:
        return named[0]
    if len(named) > 1:
        listed = "; ".join(f"{t['wbs']} {t['name'][:60]}" for t in named[:6])
        raise ToolError(f"That matches {len(named)} deliverables — say which: {listed}")
    raise ToolError(f"No deliverable matches {reference!r}. Use find_deliverables to look one up.")


def _date(value: Any, what: str) -> str:
    iso = from_input(value)
    if not iso:
        raise ToolError(f"{what} must be a date as dd/mm/yyyy — got {value!r}")
    return iso



class ApplyError(Exception):
    """A staged change that cannot be applied, said in words."""
