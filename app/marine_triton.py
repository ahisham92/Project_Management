"""What MarineTwin asks of Triton, and nothing more.

MarineTwin does not design anything. The quay was designed in Triton, so the two
numbers a monitored element is judged against come from there:

* **the design utilisation** of the element — the ratio Triton found for it under
  the Plaxis straining actions, read from the section's saved results; and
* **the corrosion allowance** the design assumed — the project's own durability
  settings when the asset is linked to a Triton project, or Triton's defaults for
  the chosen code and design life when it is not.

Triton is read in-process from its own files (the ``triton`` package beside
``app``, and the data folder ``triton_door`` points it at), read-only: nothing
here writes to a Triton project. And as with the door on the front page, a
missing or broken Triton never takes MarineTwin down — every function here
answers something sensible without it and says so.
"""

from __future__ import annotations

from typing import Any

from .triton_door import data_folder

# BS 6349-1-4:2021 mean rates (mm per side per year), only for when Triton itself
# will not import: the same figures Triton's durability module uses.
_FALLBACK_SPLASH = 4.5 / 50
_FALLBACK_IMMERSION = 2.5 / 50

# Which of Triton's allowances an element takes, by what it is.
ALLOWANCE_FOR_KIND = {
    "pile": "casing",
    "combi_wall": "combi_tube",
    "sheet_pile": "sheet_pile_per_face",
}
# And by where it sits, for anything else made of steel.
ALLOWANCE_FOR_ZONE = {
    "atmospheric": "casing",
    "splash": "casing",
    "tidal": "casing",
    "immersed": "sheet_pile_per_face",
    "buried": "sheet_pile_per_face",
}


def _store():
    """Triton's project store, or None when Triton is not installed here."""
    try:
        from triton.store import ProjectStore
    except Exception:                                 # noqa: BLE001 - reported by available()
        return None
    try:
        return ProjectStore(data_folder())
    except Exception:                                 # noqa: BLE001
        return None


def available() -> bool:
    return _store() is not None


def projects() -> list[dict[str, Any]]:
    """Every Triton project and its sections, for the picker on an asset."""
    store = _store()
    if store is None:
        return []
    out = []
    try:
        listed = store.list()
    except Exception:                                 # noqa: BLE001 - an unreadable project is not ours to fix
        return []
    for project in listed:
        out.append({
            "id": project.id,
            "name": project.info.name,
            "number": project.info.number,
            "sections": [{"id": s.id, "name": s.name, "elements": sorted(s.elements)}
                         for s in project.sections],
        })
    return out


def _project(project_id: str):
    store = _store()
    if store is None or not project_id:
        return None
    try:
        return store.get(project_id)
    except Exception:                                 # noqa: BLE001 - deleted, renamed or unreadable
        return None


def design_utilisation(project_id: str, section_id: str) -> dict[str, dict[str, Any]]:
    """``{element: {"ur", "passed", "kind"}}`` from a designed Triton section.

    Every list in Triton's results whose entries name an element and carry a
    utilisation is read, so piles, walls, beams and slabs all come through
    without MarineTwin knowing how each is designed. An element that appears
    more than once keeps its highest ratio.
    """
    store = _store()
    if store is None or not project_id or not section_id:
        return {}
    try:
        results = store.load_results(project_id, section_id)
    except Exception:                                 # noqa: BLE001
        return {}
    found: dict[str, dict[str, Any]] = {}
    for value in (results or {}).values():
        if not isinstance(value, list):
            continue
        for entry in value:
            if not isinstance(entry, dict) or "element" not in entry:
                continue
            ur = entry.get("utilisation")
            if not isinstance(ur, (int, float)):
                continue
            name = str(entry["element"])
            if name not in found or ur > found[name]["ur"]:
                found[name] = {"ur": float(ur), "passed": bool(entry.get("passed", ur <= 1)),
                               "kind": entry.get("kind", "")}
    return found


def durability(asset: Any) -> dict[str, Any]:
    """The corrosion allowances (mm per face over the design life) the asset is judged by.

    A linked Triton project's own settings win: they are what the design used.
    """
    project = _project(asset["triton_project"] or "")
    if project is not None:
        d = project.design.durability
        return {
            "allowances": {"casing": d.corrosion.casing, "combi_tube": d.corrosion.combi_tube,
                           "sheet_pile_per_face": d.corrosion.sheet_pile_per_face},
            "life": project.design.design_life_years,
            "source": f"Triton project “{project.info.name}”, {d.corrosion_code.upper()}",
        }
    life = int(asset["design_life"] or 50)
    code = asset["corrosion_code"] or "bs6349"
    try:
        from triton.durability import defaults

        allowances = defaults("bs6349", code, life)["corrosion"]
        source = f"Triton defaults, {'EN 1993-5' if code == 'en1993_5' else 'BS 6349-1-4'}, {life} years"
    except Exception:                                 # noqa: BLE001 - Triton not installed
        splash, immersed = round(_FALLBACK_SPLASH * life, 2), round(_FALLBACK_IMMERSION * life, 2)
        allowances = {"casing": splash, "combi_tube": splash, "sheet_pile_per_face": immersed}
        source = f"BS 6349-1-4 mean rates, {life} years (Triton is not installed here)"
    return {"allowances": allowances, "life": life, "source": source}


def allowance_for(element: Any, allowances: dict[str, float]) -> float | None:
    """The allowance one element was designed with, or None when it is not steel."""
    if element["material"] != "steel":
        return None
    key = ALLOWANCE_FOR_KIND.get(element["kind"]) or ALLOWANCE_FOR_ZONE.get(element["zone"], "casing")
    return float(allowances.get(key, 0.0)) or None
