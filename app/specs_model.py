"""Reading a model: what a Revit export says the project has, and whether its
concrete grades are believable.

A project's elements are the answers that decide which sections are issued:
post-tensioning, precast, steel joists, fenders, waterproofing and the rest.
Most of them are already in the model, so the model can tick them. A Revit
``.rvt`` cannot be read here: Revit keeps its models in its own closed
format. What Revit writes for everyone else can, and it writes two things:

**IFC** (File → Export → IFC). A text file of numbered entities. One pass
splits it into entities and counts them by class; only the few classes that
say something about the structure are read fully: the building elements,
their types, their materials (through every kind of layer, profile and
constituent set) and the strength properties Revit attaches to them.

**Schedules** (View → Schedules, then File → Export → Reports → Schedule).
A table of families, types, categories and materials, as tab-separated or
comma-separated text in whatever encoding Revit chose, or saved to Excel.

Either way the answers come from words: names, types, materials and layers,
matched against what an engineer would call the thing. Every answer says
why it was given, and nothing is ticked without something in the file behind
it. The concrete grades found are read and checked for the slips that reach
contracts: a cube and cylinder strength written the wrong way round, a psi
value with a zero missing, a class EN 206 does not have.

Everything is the standard library, and the file never leaves the server.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from collections import Counter, defaultdict
from typing import Any, Iterable, NamedTuple
from xml.etree import ElementTree

from . import specs, specs_seed

# The answers a model can give, as the library asks them.
CHOICES: dict[str, list[str]] = {key: choices.split("|")
                                 for key, _q, choices, _d, _g, _k in specs_seed.OPTIONS}
ONE_ANSWER = {key for key, _q, _c, _d, _g, kind in specs_seed.OPTIONS if kind == "one"}

ACCEPTS = ("an IFC export (.ifc or .ifczip; in Revit, File → Export → IFC), or a Revit schedule "
           "or material takeoff exported as text (.txt or .csv; View → Schedules, then File → "
           "Export → Reports → Schedule) or saved to Excel (.xlsx)")
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
REVIT_EXTENSIONS = (".rvt", ".rfa", ".rte", ".rft")


# --- concrete grades ---------------------------------------------------------------

EN206 = [(8, 10), (12, 15), (16, 20), (20, 25), (25, 30), (28, 35), (30, 37), (32, 40),
         (35, 45), (40, 50), (45, 55), (50, 60), (55, 67), (60, 75), (70, 85), (80, 95),
         (90, 105), (100, 115)]
MPA_PER_PSI = 0.00689476

EN_PAIR = re.compile(r"(?<![A-Za-z])C\s?(\d{1,3}(?:\.\d)?)\s?[/-]\s?(\d{1,3}(?:\.\d)?)(?!\d)")
LONE_C = re.compile(r"(?<![A-Za-z])C\s?(\d{2,3})(?![\d/.]|\s?[/-]\s?\d)")
PSI = re.compile(r"(\d{1,2},\d{3}|\d+(?:\.\d+)?)\s*psi\b", re.I)
KSI = re.compile(r"(\d+(?:\.\d+)?)\s*ksi\b", re.I)
MPA = re.compile(r"(\d+(?:\.\d+)?)\s*(?:mpa|n/mm2|n/mm²|n/mm\^2|n per mm2)", re.I)
FC = re.compile(r"(?<![A-Za-z])f\s*'?\s*c(?![A-Za-z])\s*'?\s*[=:]?\s*(\d[\d,]*(?:\.\d+)?)", re.I)
BARE = re.compile(r"(?<![\w.,/-])(\d+(?:\.\d+)?)(?![\w.,/]|\s*(?:mm|cm|m|%|x)\b)", re.I)
LIGHT = re.compile(r"blinding|\blean\b|mass fill|screed|\bfill\b", re.I)
PRESTRESS = re.compile(r"tendon|prestress|pre-stress|post[- ]?tension|\bPT\b")
MARINE_EXPOSURE = re.compile(r"marine|quay|wharf|jetty|\bsea\b|seawater|splash|tidal", re.I)


def _num(value: float) -> str:
    """35 as 35, 27.58 as 27.6."""
    return f"{value:.0f}" if abs(value - round(value)) < 0.05 else f"{value:.1f}"


def _nearest_class(cyl: float, cube: float | None = None) -> tuple[int, int]:
    """The EN 206 class closest to a strength, the cylinder weighing most."""
    if cube is None:
        return min(EN206, key=lambda c: abs(c[0] - cyl))
    return min(EN206, key=lambda c: abs(c[0] - cyl) + 0.5 * abs(c[1] - cube))


def _read_grade(text: str) -> dict | None:
    """The strength a material name or grade gives, in whichever way it is written."""
    text = (text or "").replace("’", "'").replace("′", "'").replace("‘", "'")
    if not text.strip():
        return None
    m = EN_PAIR.search(text)
    if m:
        cyl, cube = float(m.group(1)), float(m.group(2))
        return {"how": "en", "grade": f"C{_num(cyl)}/{_num(cube)}", "mpa": cyl, "cube": cube}
    m = LONE_C.search(text)
    if m:
        cube = float(m.group(1))
        match = [c for c in EN206 if c[1] == cube]
        cyl = float(match[0][0]) if match else round(0.8 * cube, 1)
        return {"how": "cube", "grade": f"C{_num(cube)}", "mpa": cyl, "cube": cube}
    m = PSI.search(text)
    if m:
        psi = float(m.group(1).replace(",", ""))
        return {"how": "psi", "grade": f"{_num(psi)} psi", "psi": psi, "mpa": psi * MPA_PER_PSI}
    m = KSI.search(text)
    if m:
        psi = float(m.group(1)) * 1000
        return {"how": "psi", "grade": f"{m.group(1)} ksi", "psi": psi, "mpa": psi * MPA_PER_PSI}
    m = MPA.search(text)
    if m:
        value = float(m.group(1))
        if re.search(r"\bcube\b", text, re.I):
            match = [c for c in EN206 if c[1] == value]
            cyl = float(match[0][0]) if match else round(0.8 * value, 1)
            return {"how": "cube_mpa", "grade": f"{_num(value)} MPa cube", "mpa": cyl,
                    "cube": value}
        return {"how": "mpa", "grade": f"{_num(value)} MPa", "mpa": value}
    m = FC.search(text)
    if m:
        value = float(m.group(1).replace(",", ""))
        if value >= 1000:
            return {"how": "psi", "grade": f"{_num(value)} psi", "psi": value,
                    "mpa": value * MPA_PER_PSI}
        return {"how": "mpa", "grade": f"{_num(value)} MPa", "mpa": value}
    if re.search(r"concrete|grade|strength", text, re.I) or re.fullmatch(r"\s*[\d.]+\s*", text):
        for m in BARE.finditer(text):
            value = float(m.group(1))
            if 10 <= value <= 120:
                return {"how": "mpa", "grade": f"{_num(value)} MPa", "mpa": value}
            if 2000 <= value <= 15000:
                return {"how": "psi", "grade": f"{_num(value)} psi", "psi": value,
                        "mpa": value * MPA_PER_PSI}
    return None


def _meant_psi(psi: float) -> float | None:
    for factor in (10, 100, 0.1, 0.01):
        if 2500 <= psi * factor <= 12000:
            return psi * factor
    return None


def grade_check(text: str, used_in: list[str] | None = None, exposure: str = "") -> dict:
    """Whether one concrete grade looks right for what it is used in.

    ``state`` is ``ok``, ``check`` (believable, but worth a second look),
    ``unrealistic`` (almost certainly a slip) or ``missing`` (no strength
    written at all), and ``note`` says why in a sentence or two.
    """
    used = " ".join(used_in or [])
    context = f"{text or ''} {used}"
    read = _read_grade(text or "")
    if not read:
        return {"grade": "", "mpa": None, "cube": None, "state": "missing",
                "note": "No strength in the name or properties: the specification will use "
                        "the project's default class."}
    grade, cyl, cube, how = read["grade"], read["mpa"], read.get("cube"), read["how"]
    out = {"grade": grade, "mpa": round(cyl, 1), "cube": cube}

    def result(state: str, *notes: str) -> dict:
        return {**out, "state": state, "note": " ".join(n for n in notes if n)}

    # Slips: values no structural concrete has.
    if how == "psi" and (read["psi"] < 1000 or read["psi"] > 20000):
        meant = _meant_psi(read["psi"])
        what = ("is not a structural concrete" if read["psi"] < 1000
                else "is beyond any structural concrete")
        guess = f"; {_num(meant)} psi was probably meant" if meant else "; check the value"
        return result("unrealistic", f"{grade} {what}{guess}.")
    if how == "en":
        if cube < cyl:
            return result("unrealistic",
                          f"{grade} puts the cube strength below the cylinder strength, which "
                          f"cannot be: C{_num(cube)}/{_num(cyl)} was probably meant.")
        ratio = cube / cyl if cyl else 0
        if not 1.1 <= ratio <= 1.35:
            near = _nearest_class(cyl)
            return result("unrealistic",
                          f"{grade} is not a possible class: the cube strength is usually 1.15 "
                          f"to 1.3 times the cylinder strength, and here it is {ratio:.2f} "
                          f"times. The nearest class is C{near[0]}/{near[1]}.")
    said = grade if how == "mpa" else f"{grade} ({_num(cyl)} MPa)"
    if cyl < 8:
        return result("unrealistic",
                      f"{said} is below any structural concrete; the lowest EN 206 class is "
                      "C8/10. Check the value.")
    if cyl > 120:
        guess = (f" Perhaps {_num(cyl / 10)} MPa was meant." if 20 <= cyl / 10 <= 60 else "")
        return result("unrealistic",
                      f"{said} is beyond ordinary structural concrete; EN 206 stops at "
                      f"C100/115. Check the value.{guess}")

    checks: list[str] = []
    light = bool(LIGHT.search(context))
    if how == "en" and (int(cyl), int(cube)) not in EN206:
        near = _nearest_class(cyl, cube)
        checks.append(f"{grade} is not an EN 206 class; the nearest is C{near[0]}/{near[1]}.")
    if how in ("cube", "cube_mpa"):
        suggest = [c for c in EN206 if c[1] == cube] or [_nearest_class(0.8 * cube)]
        also = [c for c in EN206 if c[0] == cube]
        name = f"C{suggest[0][0]}/{suggest[0][1]}"
        if how == "cube":
            line = f"{grade} reads as a BS 8500 cube strength; write it as {name}."
            if also:
                line += (f" If {_num(cube)} MPa was meant as the cylinder strength, "
                         f"it is C{also[0][0]}/{also[0][1]}.")
        else:
            line = f"{grade} is about {name}; write it as the EN class."
        checks.append(line)
    minimum = 2500 * MPA_PER_PSI if how == "psi" else 20
    if cyl < minimum - 0.05 and not light:
        checks.append(f"{_num(cyl)} MPa is below the usual minimum for structural members "
                      "(EN 1992 and BS 8500: C20/25; ACI 318: 17 MPa, 2500 psi, and 28 MPa "
                      "for most exposed work).")
    if cyl >= 60:
        checks.append(f"{_num(cyl)} MPa is high-strength concrete: confirm that it can be "
                      "supplied locally and that the testing is specified for it.")
    if PRESTRESS.search(context) or re.search(r"prestress|post[- ]?tension", context, re.I):
        if cyl < 28:
            checks.append(f"{_num(cyl)} MPa is low for prestressed or post-tensioned work, "
                          "which usually needs at least 28 MPa (4000 psi, about C28/35).")
    marine = exposure.strip().lower() == "marine" or bool(MARINE_EXPOSURE.search(context))
    if marine and cyl < 35 and not light:
        checks.append(f"{_num(cyl)} MPa is low for marine exposure: ACI 318 exposure class C2 "
                      "asks for 35 MPa (5000 psi), and BS 8500's XS classes about C35/45 "
                      "and up.")
    if checks:
        return result("check", *checks)
    if light and cyl < 20:
        return result("ok", f"{said} is enough for blinding and lean fill.")
    if how == "en":
        return result("ok", f"{grade}: cylinder {_num(cyl)} MPa, cube {_num(cube)} MPa.")
    if how == "psi":
        return result("ok", f"{grade} = {_num(cyl)} MPa.")
    return result("ok", f"{grade} cylinder strength.")


# --- steel grades ------------------------------------------------------------------

S_GRADE = re.compile(r"(?<![A-Za-z])S\s?-?(\d{3})(?:\s?(JR|J0|J2|K2|MC|ML|M|NL|N|QL|Q|W|H))?"
                     r"(?![\d])")
A_GRADE = re.compile(r"(?<![A-Za-z])A\s?-?(36|53|572|992|500|913|588|1085)(?!\d)"
                     r"(?:[^,;]*?\bGr(?:ade)?\.?\s?([A-D]|\d{2})\b)?", re.I)
EN_STEEL_OK = {"235", "275", "355", "420", "460", "690"}


def steel_check(text: str) -> dict:
    """The grade a structural steel material names, and whether it is a usual one."""
    text = text or ""
    m = S_GRADE.search(text)
    if m:
        grade = "S" + m.group(1) + (m.group(2) or "")
        if m.group(1) in EN_STEEL_OK:
            return {"grade": grade, "state": "ok", "note": f"{grade} to BS EN 10025."}
        return {"grade": grade, "state": "check",
                "note": f"S{m.group(1)} is not a usual BS EN 10025 grade (S235, S275, S355, "
                        "S420, S460, S690); check it."}
    m = A_GRADE.search(text)
    if m:
        number, sub = m.group(1), (m.group(2) or "").upper()
        grade = f"A{number}" + (f" Gr {sub}" if sub else "")
        if number in ("36", "53", "992"):
            return {"grade": grade, "state": "ok", "note": f"ASTM {grade}."}
        if number == "572":
            if sub in ("50", "65"):
                return {"grade": grade, "state": "ok", "note": f"ASTM {grade}."}
            return {"grade": grade, "state": "check",
                    "note": "ASTM A572 comes in several grades; name it (usually Gr 50)."}
        if number == "500":
            if sub in ("B", "C"):
                return {"grade": grade, "state": "ok", "note": f"ASTM {grade}."}
            return {"grade": grade, "state": "check",
                    "note": "ASTM A500 comes in several grades; name it (usually Gr B or C)."}
        return {"grade": grade, "state": "check",
                "note": f"ASTM {grade} is not one of the usual structural grades here; confirm it."}
    if re.search(r"\b43\s?-?\s?275\b|\bgrade\s?43\b", text, re.I):
        return {"grade": "Grade 43", "state": "check",
                "note": "Grade 43 is the old BS 4360 name; write it as S275."}
    if re.search(r"\bgrade\s?50\b|\bgr\.?\s?50\b", text, re.I):
        return {"grade": "Grade 50", "state": "check",
                "note": "Grade 50 alone does not say which standard: ASTM A992, A572 Gr 50, or "
                        "BS 4360 grade 50 (now S355)."}
    yield_ = re.search(r"(\d{3})\s*(?:mpa|n/mm)", text, re.I)
    if yield_:
        value = int(yield_.group(1))
        near = {235: "S235", 250: "ASTM A36", 275: "S275", 345: "S355 or ASTM A992",
                350: "S355 or ASTM A992", 355: "S355", 420: "S420", 460: "S460"}
        match = near.get(value) or near[min(near, key=lambda v: abs(v - value))]
        return {"grade": f"{value} MPa", "state": "check",
                "note": f"{value} MPa is a yield strength, not a named grade; the nearest is "
                        f"{match}. Name the grade."}
    number = re.search(r"\d{2,4}", text)
    if number:
        return {"grade": number.group(0), "state": "check",
                "note": f"'{text}' is not a grade this recognises; name it (e.g. S355 or ASTM "
                        "A992)."}
    return {"grade": "", "state": "missing",
            "note": "No grade in the name: the specification will use the project's steel grade."}


# --- what a material is ------------------------------------------------------------

NOT_CONCRETE = re.compile(r"masonry|\bcmu\b|\bblock|brick|concrete block", re.I)
CONCRETE_WORDS = re.compile(r"concrete|\bbeton|grout|shotcrete|gunite|blinding|\blean mix|"
                            r"cast[- ]in[- ]place|cast[- ]in[- ]situ|in[- ]situ|precast|pre-cast|"
                            r"\bC\s?\d{1,3}\s?[/-]\s?\d{2,3}\b", re.I)
CONCRETE_LOOSE = re.compile(r"\bf'?c'?\b|\bpsi\b|\bksi\b|\bmpa\b|n/mm|\bC\s?\d{2,3}\b", re.I)
REBAR_MATERIAL = re.compile(r"\bB\s?(?:420|450|500|550)[A-C]?\b|A615|A706|A1035|rebar|"
                            r"reinforcing (?:bar|steel)|reinforcement (?:bar|steel)|"
                            r"\bgrade\s?60\b|\bgr\.?\s?60\b|\bfe\s?\d{3}\b|\bgfrp\b", re.I)
STEEL_MATERIAL = re.compile(r"steel|\bmetal\b|(?<![A-Za-z])S\s?(?:235|275|355|420|460|690)\b|"
                            r"(?<![A-Za-z])A\s?(?:36|53|572|992|500)\b|\bQ\d{3}\b|\bSS\d{3}\b|"
                            r"\bgrade\s?50\b", re.I)
NON_FERROUS = re.compile(r"alumin|copper|zinc|bronze|brass|lead\b|titanium", re.I)
# Studs and light-gauge framing are not the structural steel whose grade is checked.
LIGHT_STEEL = re.compile(r"\bstuds?\b|stud layer|light[- ]gauge|cold[- ]formed|furring", re.I)


def material_kind(name: str) -> str:
    """``concrete``, ``steel`` or ``""`` (anything else, rebar included)."""
    if not name:
        return ""
    if NOT_CONCRETE.search(name):
        return ""
    if CONCRETE_WORDS.search(name):
        return "concrete"
    if REBAR_MATERIAL.search(name):
        return ""
    if STEEL_MATERIAL.search(name) and not NON_FERROUS.search(name):
        return "" if LIGHT_STEEL.search(name) else "steel"
    if CONCRETE_LOOSE.search(name):
        return "concrete"
    return ""


# --- what a model holds, however it came ---------------------------------------------

class Group(NamedTuple):
    """Elements alike in everything the rules look at, counted together."""
    role: str           # BEAM, COLUMN, SLAB, ... what the rules treat it as
    kind: str           # "Beams" or "Structural Framing": what it is used in
    unit: str           # "IfcBeam" or "rows": how a reason counts it
    name: str           # what it is called, for the reasons
    words: str          # every name the element and its type go by
    mats: tuple         # its materials, by name
    layers: str         # layer and set names, for waterproofing
    strength: str       # a strength or grade from its properties
    thickness: float | None  # metres, when it could be read
    phase: str          # the phase it is demolished in, if any


class Model:
    def __init__(self, source: str, detail: str):
        self.source = source
        self.detail = detail
        self.groups: Counter = Counter()
        self.categories: list[dict] = []
        self.notes: list[str] = []
        self.material_names: set[str] = set()
        self.material_extra: dict[str, str] = {}      # name -> its category, for the kind
        self.material_strength: dict[str, str] = {}   # name -> strength from its properties
        self.no_material_column = False
        self.total = 0


# --- IFC ---------------------------------------------------------------------------

ENTITY = re.compile(r"#(\d+)\s*=\s*([A-Za-z0-9_]+)\s*\(([^;']*(?:'[^']*'[^;']*)*)\)\s*;")
DATA_START = re.compile(r"ENDSEC\s*;\s*DATA\s*(?:\([^)]*\))?\s*;")

# class: (what it is, how it is written, what the rules treat it as)
IFC_CLASSES: dict[str, tuple[str, str, str]] = {}
for _cls, _plural, _role in [
        ("IfcBeam", "Beams", "BEAM"), ("IfcBeamStandardCase", "Beams", "BEAM"),
        ("IfcColumn", "Columns", "COLUMN"), ("IfcColumnStandardCase", "Columns", "COLUMN"),
        ("IfcSlab", "Slabs", "SLAB"), ("IfcSlabStandardCase", "Slabs", "SLAB"),
        ("IfcSlabElementedCase", "Slabs", "SLAB"),
        ("IfcWall", "Walls", "WALL"), ("IfcWallStandardCase", "Walls", "WALL"),
        ("IfcWallElementedCase", "Walls", "WALL"),
        ("IfcFooting", "Footings", "FOOTING"), ("IfcPile", "Piles", "PILE"),
        ("IfcStair", "Stairs", "STAIR"), ("IfcStairFlight", "Stair flights", "STAIR"),
        ("IfcRamp", "Ramps", "RAMP"), ("IfcRampFlight", "Ramp flights", "RAMP"),
        ("IfcRoof", "Roofs", "ROOF"),
        ("IfcMember", "Members", "MEMBER"), ("IfcMemberStandardCase", "Members", "MEMBER"),
        ("IfcPlate", "Plates", "PLATE"), ("IfcPlateStandardCase", "Plates", "PLATE"),
        ("IfcRailing", "Railings", "RAILING"), ("IfcCovering", "Coverings", "COVERING"),
        ("IfcReinforcingBar", "Reinforcing bars", "REBAR"),
        ("IfcReinforcingMesh", "Reinforcing mesh", "REBAR"),
        ("IfcTendon", "Tendons", "TENDON"), ("IfcTendonAnchor", "Tendon anchors", "TENDON"),
        ("IfcTendonConduit", "Tendon ducts", "TENDON"),
        ("IfcMechanicalFastener", "Mechanical fasteners", "FASTENER"),
        ("IfcFastener", "Fasteners", "FASTENER"),
        ("IfcDiscreteAccessory", "Accessories", "OTHER"),
        ("IfcBearing", "Bearings", "BEARING"),
        ("IfcBuildingElementProxy", "Other elements", "OTHER"),
        ("IfcBuildingElementPart", "Parts", "OTHER"),
        ("IfcElementAssembly", "Assemblies", "OTHER"),
        ("IfcCivilElement", "Civil elements", "OTHER"),
        ("IfcFurnishingElement", "Furnishings", "OTHER"), ("IfcFurniture", "Furniture", "OTHER"),
        ("IfcTransportElement", "Transport elements", "OTHER"),
        ("IfcBridge", "Bridges", "BRIDGE"), ("IfcBridgePart", "Bridge parts", "BRIDGE"),
        ("IfcMarineFacility", "Marine facilities", "MARINE"),
        ("IfcMarinePart", "Marine parts", "MARINE")]:
    IFC_CLASSES[_cls.upper()] = (_plural, _cls, _role)
IFC_TYPES = {cls + "TYPE": cls for cls in IFC_CLASSES}
IFC_TYPES.update({"IFCSLABTYPE": "IFCSLAB", "IFCWALLTYPE": "IFCWALL", "IFCBEAMTYPE": "IFCBEAM",
                  "IFCCOLUMNTYPE": "IFCCOLUMN", "IFCMEMBERTYPE": "IFCMEMBER",
                  "IFCPLATETYPE": "IFCPLATE", "IFCFURNITURETYPE": "IFCFURNITURE",
                  "IFCFURNISHINGELEMENTTYPE": "IFCFURNISHINGELEMENT"})
IFC_MATERIALS = {"IFCMATERIAL", "IFCMATERIALLIST", "IFCMATERIALLAYERSETUSAGE",
                 "IFCMATERIALLAYERSET", "IFCMATERIALLAYER", "IFCMATERIALLAYERWITHOFFSETS",
                 "IFCMATERIALPROFILESETUSAGE", "IFCMATERIALPROFILESETUSAGETAPERING",
                 "IFCMATERIALPROFILESET", "IFCMATERIALPROFILE", "IFCMATERIALPROFILEWITHOFFSETS",
                 "IFCMATERIALCONSTITUENTSET", "IFCMATERIALCONSTITUENT"}
IFC_WANTED = (set(IFC_CLASSES) | set(IFC_TYPES) | IFC_MATERIALS | {
    "IFCRELASSOCIATESMATERIAL", "IFCRELDEFINESBYTYPE", "IFCRELDEFINESBYPROPERTIES",
    "IFCPROPERTYSET", "IFCPROPERTYSINGLEVALUE", "IFCMATERIALPROPERTIES",
    "IFCEXTENDEDMATERIALPROPERTIES", "IFCMECHANICALCONCRETEMATERIALPROPERTIES",
    "IFCAPPLICATION", "IFCSIUNIT", "IFCCONVERSIONBASEDUNIT", "IFCUNITASSIGNMENT"})

# Properties worth reading, by their names squeezed to letters.
STRENGTH_PROPS = {"compressivestrength", "concretecompressivestrength", "strength", "grade",
                  "concretegrade", "fc", "f'c", "fc'", "fck", "concretestrength", "concreteclass",
                  "strengthclass", "concretestrengthclass", "characteristicstrength"}
THICKNESS_PROPS = {"thickness", "foundationthickness", "defaultthickness", "depth"}
PHASE_PROPS = {"phasedemolished"}
MATERIAL_PROPS = {"structuralmaterial"}
KEEP_PROPS = STRENGTH_PROPS | THICKNESS_PROPS | PHASE_PROPS | MATERIAL_PROPS
PROP_NAME = re.compile(r"\s*'([^']*)'")


def _squeeze(name: str) -> str:
    return re.sub(r"[\s_\-:.]", "", (name or "").lower())


class _Ref(int):
    """A reference to another entity, told apart from a number."""


class _Enum(str):
    """An enumeration value such as ``.BASESLAB.``, told apart from text."""


TOKEN = re.compile(r"""\s*(?:
    '(?P<s>[^']*(?:''[^']*)*)'
  | \#(?P<r>\d+)
  | (?P<e>\.[A-Za-z0-9_]+\.)
  | (?P<t>[A-Za-z][A-Za-z0-9_]*)\s*\(
  | (?P<o>\()
  | (?P<c>\))
  | (?P<n>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)
  | (?P<u>[$*])
  | "(?P<x>[0-9A-Fa-f]*)"
  | (?P<k>,)
)""", re.X)
ESCAPE = re.compile(r"\\X2\\((?:[0-9A-Fa-f]{4})*)\\X0\\|\\X4\\((?:[0-9A-Fa-f]{8})*)\\X0\\|"
                    r"\\X\\([0-9A-Fa-f]{2})|\\S\\(.)|\\P[A-I]?\\|\\\\", re.S)


def _unescape(m: re.Match) -> str:
    if m.group(1) is not None:
        h = m.group(1)
        return "".join(chr(int(h[i:i + 4], 16)) for i in range(0, len(h), 4))
    if m.group(2) is not None:
        h = m.group(2)
        return "".join(chr(int(h[i:i + 8], 16)) for i in range(0, len(h), 8))
    if m.group(3) is not None:
        return chr(int(m.group(3), 16))
    if m.group(4) is not None:
        return chr(ord(m.group(4)) + 128)
    return "\\" if m.group(0) == "\\\\" else ""


def step_text(raw: str) -> str:
    """A STEP string as it reads: '' as a quote, \\X2\\ and \\X\\ escapes decoded."""
    text = raw.replace("''", "'")
    return ESCAPE.sub(_unescape, text) if "\\" in text else text


def step_args(body: str) -> list:
    """The attributes of one entity: text, numbers, references, lists and typed values."""
    stack: list[list] = [[]]
    typed: list[str | None] = []
    pos, end = 0, len(body)
    while pos < end:
        m = TOKEN.match(body, pos)
        if not m:
            break
        pos = m.end()
        kind = m.lastgroup
        top = stack[-1]
        if kind == "s":
            top.append(step_text(m.group("s")))
        elif kind == "r":
            top.append(_Ref(m.group("r")))
        elif kind == "n":
            top.append(float(m.group("n")))
        elif kind == "e":
            top.append(_Enum(m.group("e")[1:-1]))
        elif kind == "u":
            top.append(None)
        elif kind in ("o", "t"):
            stack.append([])
            typed.append(m.group("t"))
        elif kind == "c":
            if len(stack) == 1:
                break
            done = stack.pop()
            name = typed.pop()
            stack[-1].append((name.upper(), done[0] if done else None) if name else done)
        elif kind == "x":
            top.append(m.group("x"))
    return stack[0]


def _arg(args: list, i: int) -> Any:
    return args[i] if i < len(args) else None


def _refs(value: Any) -> list[int]:
    if isinstance(value, _Ref):
        return [int(value)]
    if isinstance(value, list):
        return [int(v) for v in value if isinstance(v, _Ref)]
    return []


def _label(value: Any) -> str:
    """Text, whether given plain or as a typed value such as IFCLABEL('x')."""
    if isinstance(value, tuple):
        value = value[1]
    return value.strip() if isinstance(value, str) and not isinstance(value, _Enum) else ""


REVIT_ID = re.compile(r":\d+$")
QUOTES = re.compile(r"'[^']*'")
LIST = re.compile(r"\(([^()]*)\)")
REF = re.compile(r"#(\d+)")


def _relation(body: str) -> tuple[list[int], int | None]:
    """The related objects and the relating one of an IfcRel..., read quickly."""
    bare = QUOTES.sub("''", body)
    lists = LIST.findall(bare)
    related = [int(r) for r in REF.findall(lists[-1])] if lists else []
    tail = bare[bare.rfind(")") + 1:] if lists else bare
    relating = REF.findall(tail)
    return related, (int(relating[-1]) if relating else None)


def _decode_ifc(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def _read_ifc(data: bytes) -> Model:
    text = _decode_ifc(data)
    start = DATA_START.search(text)
    if not start:
        raise specs.SpecError("That IFC file has no data section, so it cannot be read. "
                              "Export it again from Revit.")
    header = text[:start.start()]
    schema = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", header)
    schema_name = (schema.group(1) if schema else "IFC").upper()
    schema_name = re.sub(r"_ADD\d.*|_TC\d.*", "", schema_name)

    counts: dict[str, int] = {}
    bodies: dict[str, list[tuple[int, str]]] = defaultdict(list)
    wanted = IFC_WANTED
    for m in ENTITY.finditer(text, start.end()):
        cls = m.group(2).upper()
        counts[cls] = counts.get(cls, 0) + 1
        if cls in wanted:
            if cls == "IFCPROPERTYSINGLEVALUE":
                name = PROP_NAME.match(text, m.start(3))
                if not name or _squeeze(name.group(1)) not in KEEP_PROPS:
                    continue
            bodies[cls].append((int(m.group(1)), m.group(3)))
    del text

    # Where the file came from.
    source = ""
    for _id, body in bodies.get("IFCAPPLICATION", [])[:1]:
        args = step_args(body)
        source = _label(_arg(args, 2)) or _label(_arg(args, 3))
    if not source:
        name = re.search(r"FILE_NAME\s*\((.*?)\)\s*;", header, re.S)
        if name:
            args = step_args(name.group(1))
            source = _label(_arg(args, 5)) or _label(_arg(args, 4))
    detail = f"{schema_name} export from {source}" if source else f"{schema_name} file"
    model = Model("IFC", detail)

    # Units: lengths to metres, pressures to pascals.
    length_scale, pressure_scale = 1.0, 1.0
    units: dict[int, tuple[str, float]] = {}
    prefixes = {"MILLI": 1e-3, "CENTI": 1e-2, "DECI": 1e-1, "KILO": 1e3, "MEGA": 1e6, "GIGA": 1e9}
    for uid, body in bodies.get("IFCSIUNIT", []):
        args = step_args(body)
        kind, prefix = str(_arg(args, 1) or ""), _arg(args, 2)
        units[uid] = (kind, prefixes.get(str(prefix), 1.0) if prefix else 1.0)
    for uid, body in bodies.get("IFCCONVERSIONBASEDUNIT", []):
        args = step_args(body)
        name = _label(_arg(args, 2)).upper()
        factor = {"FOOT": 0.3048, "INCH": 0.0254, "PSI": 6894.757,
                  "POUND PER SQUARE INCH": 6894.757}.get(name)
        if factor:
            units[uid] = (str(_arg(args, 1) or ""), factor)
    for _id, body in bodies.get("IFCUNITASSIGNMENT", [])[:1]:
        for ref in _refs(_arg(step_args(body), 0)):
            kind, scale = units.get(ref, ("", 1.0))
            if kind == "LENGTHUNIT":
                length_scale = scale
            elif kind == "PRESSUREUNIT":
                pressure_scale = scale

    # Properties worth keeping, and the sets that hold them.
    props: dict[int, tuple[str, Any]] = {}
    for pid, body in bodies.pop("IFCPROPERTYSINGLEVALUE", []):
        args = step_args(body)
        props[pid] = (_squeeze(_label(_arg(args, 0))), _arg(args, 2))
    psets: dict[int, list[int]] = {}
    for sid, body in bodies.pop("IFCPROPERTYSET", []):
        held = [int(r) for r in REF.findall(QUOTES.sub("''", body)) if int(r) in props]
        if held:
            psets[sid] = held

    def strength_text(value: Any) -> str:
        if isinstance(value, tuple):
            kind, raw = value
            if isinstance(raw, str):
                return raw.strip()
            if isinstance(raw, float):
                if kind == "IFCPRESSUREMEASURE" or raw > 1e5:
                    pa = raw * (pressure_scale if kind == "IFCPRESSUREMEASURE" else 1.0)
                    mpa, psi = pa / 1e6, pa / 6894.757
                    if abs(mpa - round(mpa)) < 0.01:
                        return f"{round(mpa)} MPa"
                    if abs(psi - round(psi / 250) * 250) < 1.5:
                        return f"{round(psi / 250) * 250} psi"
                    return f"{mpa:.1f} MPa"
                if 8 <= raw <= 150:
                    return f"{_num(raw)} MPa"
                if 1000 <= raw <= 20000:
                    return f"{_num(raw)} psi"
        return value.strip() if isinstance(value, str) else ""

    def read_props(set_ids: Iterable[int]) -> dict[str, str]:
        out: dict[str, str] = {}
        for sid in set_ids:
            for pid in psets.get(sid, []):
                name, value = props[pid]
                if name in STRENGTH_PROPS:
                    found = strength_text(value)
                    if found and "strength" not in out:
                        out["strength"] = found
                elif name in THICKNESS_PROPS:
                    raw = value[1] if isinstance(value, tuple) else value
                    if isinstance(raw, float) and raw > 0:
                        out.setdefault("thickness", str(raw * length_scale))
                elif name in PHASE_PROPS:
                    phase = _label(value)
                    if phase and phase.lower() not in ("none", "<none>"):
                        out["phase"] = phase
                elif name in MATERIAL_PROPS:
                    material = _label(value)
                    if material and not material.startswith("<"):
                        out["material"] = material
        return out

    # Materials, through every set and usage.
    mat_ents: dict[int, tuple[str, list]] = {}
    for cls in IFC_MATERIALS:
        for mid, body in bodies.pop(cls, []):
            mat_ents[mid] = (cls, step_args(body))
    for mid, (cls, args) in mat_ents.items():
        if cls == "IFCMATERIAL":
            name = _label(_arg(args, 0))
            if name:
                model.material_names.add(name)
                category = _label(_arg(args, 2))
                if category:
                    model.material_extra[name] = category
    cache: dict[int, tuple[tuple[str, ...], tuple[str, ...], float | None]] = {}

    def resolve(ref: int, depth: int = 0) -> tuple[tuple[str, ...], tuple[str, ...], float | None]:
        if ref in cache:
            return cache[ref]
        if ref not in mat_ents or depth > 6:
            return (), (), None
        cls, args = mat_ents[ref]
        names: list[str] = []
        words: list[str] = []
        thick: float | None = None

        def take(refs: Iterable[int]) -> None:
            for r in refs:
                n, w, _t = resolve(r, depth + 1)
                names.extend(n)
                words.extend(w)
        if cls == "IFCMATERIAL":
            name = _label(_arg(args, 0))
            names = [name] if name else []
        elif cls == "IFCMATERIALLIST":
            take(_refs(_arg(args, 0)))
        elif cls in ("IFCMATERIALLAYERSETUSAGE", "IFCMATERIALPROFILESETUSAGE",
                     "IFCMATERIALPROFILESETUSAGETAPERING"):
            n, w, thick = resolve(_refs(_arg(args, 0))[0], depth + 1) if _refs(_arg(args, 0)) \
                else ((), (), None)
            names, words = list(n), list(w)
        elif cls == "IFCMATERIALLAYERSET":
            layers = _refs(_arg(args, 0))
            take(layers)
            words.append(_label(_arg(args, 1)))
            total = 0.0
            for r in layers:
                layer = mat_ents.get(r)
                if layer and isinstance(_arg(layer[1], 1), float):
                    total += _arg(layer[1], 1)
            thick = total * length_scale if total else None
        elif cls in ("IFCMATERIALLAYER", "IFCMATERIALLAYERWITHOFFSETS"):
            take(_refs(_arg(args, 0)))
            words += [_label(_arg(args, 3)), _label(_arg(args, 5))]
        elif cls == "IFCMATERIALPROFILESET":
            take(_refs(_arg(args, 2)))
            words.append(_label(_arg(args, 0)))
        elif cls in ("IFCMATERIALPROFILE", "IFCMATERIALPROFILEWITHOFFSETS"):
            take(_refs(_arg(args, 2)))
            words.append(_label(_arg(args, 0)))
        elif cls == "IFCMATERIALCONSTITUENTSET":
            take(_refs(_arg(args, 2)))
            words.append(_label(_arg(args, 0)))
        elif cls == "IFCMATERIALCONSTITUENT":
            take(_refs(_arg(args, 2)))
            words.append(_label(_arg(args, 0)))
        out = (tuple(dict.fromkeys(n for n in names if n)),
               tuple(dict.fromkeys(w for w in words if w)), thick)
        cache[ref] = out
        return out

    # Strengths attached to the materials themselves.
    def material_name(ref: Any) -> str:
        entry = mat_ents.get(int(ref)) if isinstance(ref, _Ref) else None
        return _label(_arg(entry[1], 0)) if entry and entry[0] == "IFCMATERIAL" else ""

    for _id, body in bodies.pop("IFCMATERIALPROPERTIES", []):
        args = step_args(body)
        name = material_name(_arg(args, 3))
        found = read_props_from(_refs(_arg(args, 2)), props, strength_text) if name else ""
        if found:
            model.material_strength.setdefault(name, found)
    for _id, body in bodies.pop("IFCEXTENDEDMATERIALPROPERTIES", []):
        args = step_args(body)
        name = material_name(_arg(args, 0))
        found = read_props_from(_refs(_arg(args, 1)), props, strength_text) if name else ""
        if found:
            model.material_strength.setdefault(name, found)
    for _id, body in bodies.pop("IFCMECHANICALCONCRETEMATERIALPROPERTIES", []):
        args = step_args(body)
        name = material_name(_arg(args, 0))
        value = _arg(args, 6)
        if name and isinstance(value, float) and value > 0:
            found = strength_text(("IFCPRESSUREMEASURE", value))
            model.material_strength.setdefault(name, found)

    # Relations: materials, types and property sets, to elements and types.
    material_of: dict[int, int] = {}
    for _id, body in bodies.pop("IFCRELASSOCIATESMATERIAL", []):
        related, relating = _relation(body)
        if relating is not None:
            for r in related:
                material_of.setdefault(r, relating)
    type_of: dict[int, int] = {}
    for _id, body in bodies.pop("IFCRELDEFINESBYTYPE", []):
        related, relating = _relation(body)
        if relating is not None:
            for r in related:
                type_of[r] = relating
    psets_of: dict[int, list[int]] = defaultdict(list)
    for _id, body in bodies.pop("IFCRELDEFINESBYPROPERTIES", []):
        related, relating = _relation(body)
        if relating in psets:
            for r in related:
                psets_of[r].append(relating)

    # Types.
    types: dict[int, dict] = {}
    for cls in IFC_TYPES:
        for tid, body in bodies.pop(cls, []):
            args = step_args(body)
            words = [_label(_arg(args, 2)), _label(_arg(args, 3)), _label(_arg(args, 8))]
            words += [_enum_words(a) for a in args[9:]]
            types[tid] = {"name": _label(_arg(args, 2)), "words": words,
                          "props": read_props(_refs(_arg(args, 5)) + psets_of.get(tid, [])),
                          "material": material_of.get(tid)}

    # The elements.
    for cls, (plural, written, role) in IFC_CLASSES.items():
        for eid, body in bodies.pop(cls, []):
            args = step_args(body)
            name = REVIT_ID.sub("", _label(_arg(args, 2)))
            objtype = REVIT_ID.sub("", _label(_arg(args, 4)))
            words = [name, _label(_arg(args, 3)), objtype]
            for extra in args[8:]:
                words.append(_enum_words(extra) or _label(extra))
            kind = types.get(type_of.get(eid, -1))
            own = read_props(psets_of.get(eid, []))
            both = {**(kind["props"] if kind else {}), **own}
            if kind:
                words += kind["words"]
            mref = material_of.get(eid)
            if mref is None and kind:
                mref = kind["material"]
            mats, layers, thick = resolve(mref) if mref is not None else ((), (), None)
            if not mats and both.get("material"):
                mats = (both["material"],)
                model.material_names.add(both["material"])
            if both.get("thickness"):
                thick = float(both["thickness"])
            label = name or objtype or (kind["name"] if kind else "") or written
            model.groups[Group(
                role=role, kind=plural, unit=written, name=label[:80],
                words=" | ".join(dict.fromkeys(w for w in words if w)), mats=mats,
                layers=" | ".join(layers), strength=both.get("strength", ""),
                thickness=round(thick, 3) if thick else None,
                phase=both.get("phase", ""))] += 1

    shown = Counter()
    for cls, (plural, written, role) in IFC_CLASSES.items():
        if counts.get(cls):
            shown[f"{plural} ({written})"] += counts[cls]
    model.categories = [{"name": n, "count": c} for n, c in shown.most_common()]
    model.total = sum(counts.get(cls, 0) for cls, (_p, _w, role) in IFC_CLASSES.items()
                      if role not in ("BRIDGE", "MARINE"))
    if not model.total:
        model.notes.append("This IFC file holds no building elements (beams, columns, slabs, "
                           "walls and the like), so nothing could be read from it.")
    return model


def read_props_from(refs: Iterable[int], props: dict, strength_text) -> str:
    """The first strength among a list of properties."""
    for pid in refs:
        if pid in props and props[pid][0] in STRENGTH_PROPS:
            found = strength_text(props[pid][1])
            if found:
                return found
    return ""


def _enum_words(value: Any) -> str:
    if isinstance(value, _Enum) and value not in ("NOTDEFINED", "USERDEFINED", "T", "F", "U"):
        return value.replace("_", " ").lower()
    return ""


# --- schedules ---------------------------------------------------------------------

# A schedule's category, as Revit names it: what the rules treat it as.
CATEGORY_ROLES = [
    (r"structural rebar|area reinforcement|fabric reinforcement|path reinforcement|rebar",
     "REBAR"),
    (r"structural framing|beam", "BEAM"), (r"column", "COLUMN"),
    (r"structural foundation|foundation|footing", "FOOTING"), (r"pile", "PILE"),
    (r"floor|slab", "SLAB"), (r"wall", "WALL"),
    (r"stair|runs?\b|landing", "STAIR"), (r"ramp", "RAMP"), (r"roof", "ROOF"),
    (r"truss|brac", "MEMBER"), (r"railing", "RAILING"), (r"connection", "FASTENER"),
    (r"tendon", "TENDON"), (r"bearing", "BEARING"),
]
TITLE_CATEGORIES = [
    (r"structural framing", "Structural Framing"), (r"structural column", "Structural Columns"),
    (r"structural foundation", "Structural Foundations"), (r"structural rebar|rebar",
                                                            "Structural Rebar"),
    (r"structural connection", "Structural Connections"), (r"structural truss",
                                                            "Structural Trusses"),
    (r"\bcolumn", "Columns"), (r"floor", "Floors"), (r"wall", "Walls"), (r"stair", "Stairs"),
    (r"ramp", "Ramps"), (r"roof", "Roofs"), (r"railing", "Railings"),
    (r"generic model", "Generic Models"), (r"specialty equipment", "Specialty Equipment"),
]


def _role_of(category: str) -> str:
    for pattern, role in CATEGORY_ROLES:
        if re.search(pattern, category or "", re.I):
            return role
    return "OTHER"


def _category_from_title(title: str) -> str:
    if re.search(r"multi[- ]?category", title or "", re.I):
        return ""
    for pattern, name in TITLE_CATEGORIES:
        if re.search(pattern, title or "", re.I):
            return name
    return ""


def _decode_text(data: bytes) -> str:
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    if data[:3] == b"\xef\xbb\xbf":
        return data[3:].decode("utf-8", "replace")
    head = data[:400]
    if head and head.count(b"\x00") > len(head) // 4:
        return data.decode("utf-16-be" if head[:1] == b"\x00" else "utf-16-le", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", "replace")


def _looks_like_text(text: str) -> bool:
    sample = text[:4000]
    if not sample.strip():
        return False
    control = sum(1 for ch in sample if ch < " " and ch not in "\t\r\n")
    return control <= len(sample) // 100


def _text_rows(text: str) -> list[list[str]]:
    lines = [line for line in text.splitlines()[:30] if line.strip()]
    if any("\t" in line for line in lines):
        delimiter = "\t"
    else:
        sample = "\n".join(lines)
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    return [[cell.strip() for cell in row] for row in csv.reader(io.StringIO(text),
                                                                 delimiter=delimiter)]


SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _xlsx_rows(archive: zipfile.ZipFile) -> list[list[str]]:
    """The first sheet of a workbook, as rows of text."""
    names = set(archive.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        for si in root.iter(SHEET + "si"):
            shared.append("".join(t.text or "" for t in si.iter(SHEET + "t")))
    path = ""
    try:
        book = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        first = next(book.iter(SHEET + "sheet"))
        rid = first.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        rels = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        for rel in rels:
            if rel.get("Id") == rid:
                target = rel.get("Target", "").lstrip("/")
                path = target if target.startswith("xl/") else "xl/" + target
    except (KeyError, StopIteration, ElementTree.ParseError):
        pass
    if path not in names:
        sheets = sorted(n for n in names if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        if not sheets:
            raise specs.SpecError("That workbook has no sheet to read.")
        path = sheets[0]
    rows: list[list[str]] = []
    for row in ElementTree.fromstring(archive.read(path)).iter(SHEET + "row"):
        cells: dict[int, str] = {}
        for c in row.iter(SHEET + "c"):
            ref = re.match(r"([A-Z]+)", c.get("r", "")) if c.get("r") else None
            col = 0
            if ref:
                for ch in ref.group(1):
                    col = col * 26 + ord(ch) - 64
                col -= 1
            else:
                col = len(cells)
            kind = c.get("t", "")
            if kind == "inlineStr":
                value = "".join(t.text or "" for t in c.iter(SHEET + "t"))
            else:
                v = c.find(SHEET + "v")
                value = v.text if v is not None and v.text else ""
                if kind == "s" and value.isdigit() and int(value) < len(shared):
                    value = shared[int(value)]
                elif kind == "b":
                    value = "Yes" if value == "1" else "No"
                elif value and not kind:
                    try:
                        number = float(value)
                        value = _num(number) if abs(number) < 1e15 else value
                    except ValueError:
                        pass
            cells[col] = value.strip()
        if cells:
            width = max(cells) + 1
            rows.append([cells.get(i, "") for i in range(width)])
        else:
            rows.append([])
    return rows


def _length_m(value: str) -> float | None:
    """A length as Revit writes it in a schedule, in metres."""
    value = (value or "").strip()
    feet = re.match(r"(\d+)'\s*-?\s*(\d+(?:\.\d+)?)?(?:\s+(\d+)/(\d+))?\s*\"?", value)
    if feet and "'" in value:
        inches = float(feet.group(2) or 0)
        if feet.group(3):
            inches += int(feet.group(3)) / int(feet.group(4))
        return int(feet.group(1)) * 0.3048 + inches * 0.0254
    m = re.match(r"(\d+(?:[.,]\d+)?)\s*(mm|cm|m)?\b", value)
    if not m:
        return None
    number = float(m.group(1).replace(",", "."))
    unit = m.group(2) or ("mm" if number > 20 else "m")
    return number * {"mm": 1e-3, "cm": 1e-2, "m": 1.0}[unit]


def _read_schedule(rows: list[list[str]], fallback_title: str) -> Model:
    filled = [(i, row) for i, row in enumerate(rows) if any(cell for cell in row)]
    if not filled:
        raise specs.SpecError("That file is empty. " + "Upload " + ACCEPTS + ".")
    title = ""
    at = 0
    first = [c for c in filled[0][1] if c]
    if len(first) == 1 and len(filled) > 1 and len([c for c in filled[1][1] if c]) >= 2:
        title, at = first[0], 1
    if at >= len(filled) or len([c for c in filled[at][1] if c]) < 2:
        raise specs.SpecError("That file does not read as a schedule: it needs a row of column "
                              "headings. Upload " + ACCEPTS + ".")
    header = [h.strip().lower() for h in filled[at][1]]
    body = [row for _i, row in filled[at + 1:]
            if len([c for c in row if c]) >= 2 or len(header) < 2]
    body = [row for row in body if not any(re.match(r"grand total", c, re.I) for c in row[:1])]
    title = title or fallback_title

    def col(*names: str) -> int | None:
        for name in names:
            if name in header:
                return header.index(name)
        return None

    c_category = col("category")
    c_family_type = col("family and type", "family & type")
    c_family, c_type = col("family"), col("type", "type name")
    c_count = col("count")
    c_demolished = col("phase demolished")
    c_thickness = col("thickness", "default thickness", "foundation thickness", "depth")
    c_words = [i for i, h in enumerate(header)
               if h in ("comments", "type comments", "description", "assembly description",
                        "name", "family name", "model", "type mark description")]
    c_materials = [i for i, h in enumerate(header)
                   if h in ("structural material", "material", "material name", "materials")
                   or re.fullmatch(r"(?:structural )?material\s*:\s*name", h)]
    c_strength = [i for i, h in enumerate(header)
                  if re.search(r"grade|strength|\bf'?c'?\b|concrete class", h)
                  and "material" not in h]
    from_title = _category_from_title(title)
    counted = c_count is not None
    unit = "elements" if counted else "rows"
    model = Model("Schedule", f"Schedule: {title}, {len(body)} rows")
    model.no_material_column = not c_materials

    def cell(row: list[str], i: int | None) -> str:
        return row[i].strip() if i is not None and i < len(row) else ""

    categories: Counter = Counter()
    families: Counter = Counter()
    for row in body:
        category = cell(row, c_category) or from_title
        family_type = cell(row, c_family_type)
        family, typ = cell(row, c_family), cell(row, c_type)
        if not family_type:
            family_type = ": ".join(x for x in (family, typ) if x)
        words = [family_type, family, typ] + [cell(row, i) for i in c_words]
        mats = tuple(dict.fromkeys(m for m in (cell(row, i) for i in c_materials)
                                   if m and not m.startswith("<")))
        model.material_names.update(mats)
        try:
            count = max(int(float(cell(row, c_count).replace(",", ""))), 0) if counted else 1
        except ValueError:
            count = 1
        strength = next((cell(row, i) for i in c_strength if cell(row, i)), "")
        phase = cell(row, c_demolished)
        if phase.lower() in ("none", "<none>", "-"):
            phase = ""
        thick = _length_m(cell(row, c_thickness)) if c_thickness is not None else None
        model.groups[Group(
            role=_role_of(category), kind=category or title, unit=unit,
            name=(family_type or family or typ or category or "unnamed")[:80],
            words=" | ".join(dict.fromkeys(w for w in words if w)), mats=mats, layers="",
            strength=strength, thickness=round(thick, 3) if thick else None,
            phase=phase)] += count
        if category:
            categories[category] += count
        elif family or family_type:
            families[(family or family_type).split(":")[0].strip()] += count
    model.categories = [{"name": n, "count": c}
                        for n, c in (categories or families).most_common(20)]
    model.total = sum(model.groups.values())
    if not body:
        model.notes.append("The schedule has headings but no rows.")
    return model


# --- the answers -------------------------------------------------------------------

def _rx(pattern: str, flags: int = re.I) -> re.Pattern:
    return re.compile(pattern, flags)


BRIDGE_WORDS = _rx(r"\bbridges?\b|viaduct|flyover|overpass|abutment")
MARINE_WORDS = _rx(r"\bquay|wharf|jetty|jetties|\bberth|breakwater|fender|mooring|dolphin|"
                   r"revetment|sea ?wall|pontoon")
BOLLARD = _rx(r"bollard")
LAND_BOLLARD = _rx(r"traffic|security|anti[- ]?ram|removable|parking|pedestrian|landscape|"
                   r"light|retractable|street")
PIER = _rx(r"\bpiers?\b")
PRECAST = _rx(r"precast|pre-cast|hollow ?core|double[- ]tee|\bdouble t\b")
PRECAST_PC = _rx(r"\bPC[\s_-]*(?:beam|slab|column|panel|plank|wall|girder|stair|double|hollow|"
                 r"unit|element)", 0)
PRESTRESSED = _rx(r"prestress|pre-stress|pretension|pre-tension|hollow ?core|double[- ]tee|"
                  r"\bdouble t\b")
PT = _rx(r"post[- ]?tension")
PT_CASE = _rx(r"\bPT\b", 0)
BONDED = _rx(r"(?<!un)(?<!un-)bonded|grout|\bducts?\b|grouting duct")
UNBONDED = _rx(r"unbonded|un-bonded|monostrand|mono-strand|greased|sheathed")
MASS = _rx(r"mass concrete")
FOUNDATION_MASS = _rx(r"\braft\b|\bmat (?:foundation|slab)|pile ?cap|foundation slab|baseslab|"
                      r"base slab")
TILT = _rx(r"tilt[- ]?up")
SHOTCRETE = _rx(r"shotcrete|sprayed concrete|gunite")
COUPLER = _rx(r"coupler")
ANCHOR = _rx(r"post[- ]?installed|chemical anchor|expansion anchor|adhesive anchor|"
             r"epoxy anchor|wedge anchor|undercut anchor|screw anchor|\bhilti\b|\bHIT-|"
             r"\bHST\d?\b|\bHSL\d?\b|\bHUS\d?\b|\bHDA\b|kwik ?bolt|\bfischer\b")
AESS = _rx(r"\baess\b|architecturally exposed")
CRANE = _rx(r"crane ?rail|crane ?beam|crane ?girder|runway beam|crane runway")
LADDER = _rx(r"ladder")
MOORING_RING = _rx(r"mooring ring")
FLOATING = _rx(r"pontoon|floating (?:pier|jetty|dock|walkway|berth|platform|breakwater)")
SHORING = _rx(r"shoring|sheet ?pil|secant pil|soldier pil|contiguous pil|fa[cç]ade retention|"
              r"king ?post wall")
MONITORING = _rx(r"monitoring|settlement (?:point|marker|monitor|stud)|inclinometer|"
                 r"strain gauge|piezometer|extensometer|crack ?meter")
DEMOLISH = _rx(r"demoli|to be removed|remove existing|existing to be removed")
STEEL_SECTION = _rx(r"\b(?:W|HP|WT|MC)\d+X\d+|\bHSS\s?\d|\b(?:UB|UC|PFC|UKB|UKC|IPE|HEA|HEB|HEM|"
                    r"SHS|RHS|CHS|UPN|UPE)\s?\d|wide flange|universal (?:beam|column)")
STEEL_WORDS = _rx(r"steel|\bmetal\b")
CONCRETE_NAME = _rx(r"concrete|\bRC\b|reinforced|cast[- ]in[- ]place|in[- ]situ|\bCIP\b|"
                    r"\bC\d{2}/\d{2}\b")
JOIST = _rx(r"joist girder|steel joist|open[- ]web|bar joist|\b\d{1,2}K\d{1,2}\b|"
            r"\b\d{2}D?LH\d{2}\b|\bK-series|\bLH-series|\bjoists?\b")
TIMBER = _rx(r"timber|wood|lumber|glulam|\bLVL\b|\bTJI\b|concrete|precast")
DECK = _rx(r"metal deck|steel deck|composite deck|\bdeck-|comflor|profiled (?:steel |metal )?"
           r"sheet|metal form deck|form deck")
COLD_FORMED = _rx(r"cold[- ]formed|\bCFS\b|light[- ]gauge|\bC[- ]?stud|\b[CZ][- ]?purlin|"
                  r"c channel - cold|\bLGS\b")
SPACE_FRAME = _rx(r"space ?frame|\bmero\b")
LINTEL = _rx(r"lintel")
GRATING = _rx(r"grating|\bgrate")
FLOOR_PLATE = _rx(r"chequer|checker|floor ?plate|tread ?plate")
LOAD_BEARING = _rx(r"load[- ]?bearing|bearing wall|non[- ]?bearing|bearing plate|bearing pile")
BEARING = _rx(r"\bbearings?\b|elastomeric pad|pot bearing")
EXPANSION_JOINT = _rx(r"expansion joint|movement joint|deck joint|modular joint|finger joint")
EJ = _rx(r"\bEJ\d*\b", 0)
PARAPET = _rx(r"parapet|barrier|railing|guardrail|guard rail")
BRIDGE_DRAIN = _rx(r"scupper|deck drain|drainage|gully")
DECK_WP = _rx(r"deck waterproof")
GIRDER = _rx(r"(?:precast|prestressed|pre-stressed|pretensioned).{0,30}girder|"
             r"girder.{0,30}(?:precast|prestressed)|aashto|\bI[- ]girder|box girder|"
             r"bulb[- ]?tee|\bU[- ]girder")
REBAR_WORDS = _rx(r"rebar|reinforcing bar|reinforcement bar")
GFRP = _rx(r"gfrp|glass fib(?:re|er)|\bfrp\b|basalt")
STAINLESS = _rx(r"stainless|\b1\.4\d{3}\b")
EPOXY = _rx(r"epoxy|\bECR\b|fusion[- ]bonded")
GALV = _rx(r"galvani[sz]ed|\bgalv\b|hot[- ]dip|zinc")
FENDER = _rx(r"fender")
FENDER_TYPES = [("Cone", _rx(r"cone|\bSCN\b|\bSCN\d")), ("Cell", _rx(r"\bcell\b|\bSCK\b|\bSCK\d")),
                ("Arch", _rx(r"\barch\b|\bSA\d|\bV[- ]?(?:type|fender)")),
                ("Pneumatic", _rx(r"pneumatic|yokohama"))]
TONNES = _rx(r"(\d{2,3}(?:\.\d)?)\s*-?\s*(?:t|te|tons?|tonnes?)\b")
KILONEWTONS = _rx(r"(\d{3,4})\s*-?\s*kn\b")
WP_CONTEXT = _rx(r"waterproof|membrane|damp[- ]?proof|tanking|\bDPM\b|\bWP\b|sheet|bitum|"
                 r"asphalt|coating")
WATERPROOFING = [
    # (answer, pattern, needs the name to be about waterproofing)
    ("Bentonite", _rx(r"bentonite|voltex|volclay"), False),
    ("Crystalline admixture", _rx(r"kryton|krystol|penetron admix|crystalline admix|"
                                  r"xypex admix"), False),
    ("Crystalline", _rx(r"xypex|crystalline|penetron"), False),
    ("Self-adhering sheet", _rx(r"self[- ]adhe(?:red|sive|ring)|peel[- ](?:and|&)[- ]stick|"
                                r"bituthene|preprufe"), False),
    ("APP modified sheet", _rx(r"\bAPP\b|atactic", 0), True),
    ("SBS modified sheet", _rx(r"\bSBS\b|styrene[- ]butadiene"), True),
    ("Elastomeric sheet", _rx(r"\bEPDM\b|\bbutyl\b|elastomeric"), True),
    ("Thermoplastic sheet", _rx(r"\bPVC\b|\bTPO\b|thermoplastic|\bHDPE\b"), True),
    ("Liquid membrane", _rx(r"liquid[- ]applied|liquid membrane|polyurethane membrane|"
                            r"\bPU membrane|polyurea"), True),
    ("Acrylic-modified cement", _rx(r"acrylic[- ]modified|polymer[- ]modified cement|"
                                    r"cementitious (?:waterproof|coating|slurry)"), True),
    ("Bituminous sheet", _rx(r"(?:bitum|asphalt)\w*\s+(?:sheet|membrane|felt|roll)|"
                             r"torch[- ]on"), True),
    ("Bituminous dampproofing", _rx(r"bitum|asphalt"), True),
]
WP_ANY = _rx(r"waterproof|tanking|\bDPM\b|damp[- ]?proof")
ROOFING = _rx(r"\broof")

CIP_ROLES = {"BEAM", "COLUMN", "SLAB", "WALL", "FOOTING", "PILE", "STAIR", "RAMP", "ROOF",
             "OTHER"}
FRAME_ROLES = {"BEAM", "COLUMN", "MEMBER", "PLATE"}
BOLLARD_SIZES = [50, 100, 150, 200]


class Evidence:
    """What was found for each answer, and where."""

    def __init__(self) -> None:
        self.found: dict[tuple[str, str], Counter] = defaultdict(Counter)

    def add(self, key: str, value: str, count: int, reason: str) -> None:
        if value in CHOICES.get(key, []):
            self.found[(key, value)][reason] += count

    def has(self, key: str, value: str | None = None) -> bool:
        return any(k == key and (value is None or v == value) for k, v in self.found)


def _where(g: Group, pattern: re.Pattern, text: str | None = None) -> str | None:
    """How a group shows a word: by its name, a material, or a layer; None if not."""
    if pattern.search(g.words if text is None else text):
        if pattern.search(g.name):
            return f"{g.unit} named '{g.name}'"
        part = next((p for p in g.words.split(" | ") if pattern.search(p)), g.name)
        return f"{g.unit} named '{g.name}' ('{part}')" if part != g.name else \
            f"{g.unit} named '{g.name}'"
    for m in g.mats:
        if pattern.search(m):
            return f"{g.unit} of '{m}'"
    if g.layers and pattern.search(g.layers):
        layer = next((part for part in g.layers.split(" | ") if pattern.search(part)), g.layers)
        return f"{g.unit} with layer '{layer}'"
    return None


def _as_class(g: Group) -> str:
    return g.unit if g.unit.startswith("Ifc") else f"'{g.kind}' {g.unit}"


def _bollard_size(text: str) -> tuple[str, bool]:
    m = TONNES.search(text)
    tonnes = float(m.group(1)) if m else None
    if tonnes is None:
        m = KILONEWTONS.search(text)
        tonnes = float(m.group(1)) / 10 if m else None
    if tonnes is None:
        return "150 t", False
    size = next((s for s in BOLLARD_SIZES if s >= tonnes - 0.01), BOLLARD_SIZES[-1])
    return f"{size} t", True


def _judge(model: Model) -> tuple[Evidence, list[str]]:
    """The answers the model's groups give, each with its reasons."""
    ev = Evidence()
    notes: list[str] = []
    groups = list(model.groups.items())

    # What the project builds, first: the other answers read in its light.
    piers: list[tuple[Group, int]] = []
    for g, n in groups:
        if g.role == "BRIDGE":
            ev.add("structures", "Bridges", n, _as_class(g))
        elif g.role == "MARINE":
            ev.add("structures", "Marine structures", n, _as_class(g))
        why = _where(g, BRIDGE_WORDS, g.words)
        if why and g.role != "BRIDGE":
            ev.add("structures", "Bridges", n, why)
        why = _where(g, MARINE_WORDS, g.words)
        if not why and BOLLARD.search(g.words) and not LAND_BOLLARD.search(g.words):
            why = f"{g.unit} named '{g.name}'"
        if why and g.role != "MARINE":
            ev.add("structures", "Marine structures", n, why)
        if PIER.search(g.words):
            piers.append((g, n))
    if piers and not ev.has("structures", "Bridges"):
        for g, n in piers:
            ev.add("structures", "Marine structures", n, f"{g.unit} named '{g.name}'")
    bridge = ev.has("structures", "Bridges") or any(g.role == "BEARING" for g, _n in groups)
    marine = ev.has("structures", "Marine structures")
    if not bridge and not marine and model.total:
        things = "elements" if model.source == "IFC" else "rows"
        ev.add("structures", "Buildings", model.total,
               f"no bridge or marine works among {model.total} {things}")

    pt_undecided: list[tuple[Group, int, str]] = []
    fenders_untyped = 0
    wp_untyped: Counter = Counter()
    for g, n in groups:
        text = f"{g.words} | {' | '.join(g.mats)} | {g.layers}"
        kinds = {material_kind(m + " " + model.material_extra.get(m, "")) for m in g.mats}
        concrete = "concrete" in kinds or (not g.mats and bool(CONCRETE_NAME.search(g.words))
                                           and not NOT_CONCRETE.search(g.words))
        steel = ("steel" in kinds and "concrete" not in kinds) or (
            not g.mats and not concrete and bool(STEEL_SECTION.search(g.words)
                                                 or STEEL_WORDS.search(g.words)))
        mat_why = next((f"{g.unit} of '{m}'" for m in g.mats
                        if material_kind(m + " " + model.material_extra.get(m, ""))
                        == ("concrete" if concrete else "steel")), None)
        named = f"{g.unit} named '{g.name}'"

        # Concrete.
        precast = PRECAST.search(text) or PRECAST_PC.search(text)
        is_pt = g.role == "TENDON" or PT.search(text) or PT_CASE.search(g.words)
        if precast or (PRESTRESSED.search(text) and not is_pt and concrete):
            value = "Precast prestressed" if PRESTRESSED.search(text) else "Plant precast"
            ev.add("precast", value, n, _where(g, PRESTRESSED if value == "Precast prestressed"
                                                else PRECAST) or _where(g, PRECAST_PC) or named)
        if is_pt:
            why = _as_class(g) if g.role == "TENDON" else (_where(g, PT) or named)
            if UNBONDED.search(text):
                ev.add("post_tensioning", "Unbonded", n, why)
            elif BONDED.search(text):
                ev.add("post_tensioning", "Bonded", n, why)
            else:
                pt_undecided.append((g, n, why))
        tilt = TILT.search(text)
        spray = SHOTCRETE.search(text)
        if tilt:
            ev.add("tilt_up", "Yes", n, _where(g, TILT) or named)
        if spray:
            ev.add("shotcrete", "Yes", n, _where(g, SHOTCRETE) or named)
        if concrete and g.role in CIP_ROLES and not precast and not tilt and not spray \
                and not (g.role == "OTHER" and not g.mats):
            ev.add("cast_in_place", "Yes", n, mat_why or named)
        if MASS.search(text):
            ev.add("mass_concrete", "Yes", n, _where(g, MASS) or named)
        elif g.role in ("FOOTING", "SLAB", "PILE", "OTHER") and (
                g.role == "FOOTING" or FOUNDATION_MASS.search(g.words)):
            thick = g.thickness or _thickness_from_name(g.words, g.role)
            if thick and thick >= 1.0 and (concrete or not g.mats):
                ev.add("mass_concrete", "Yes", n, f"{named}, {_num(thick)} m thick")

        # Reinforcement and fixings.
        if g.role == "REBAR" or REBAR_WORDS.search(g.words):
            why = _as_class(g) if g.role == "REBAR" else named
            for value, pattern in (("GFRP bars", GFRP), ("Stainless steel", STAINLESS),
                                   ("Epoxy-coated", EPOXY), ("Galvanized", GALV)):
                if pattern.search(text):
                    ev.add("rebar", value, n, _where(g, pattern) or why)
                    break
            else:
                ev.add("rebar", "Uncoated", n, why)
        if COUPLER.search(text) and g.role != "TENDON":
            ev.add("couplers", "Yes", n, _where(g, COUPLER) or named)
        anchor = _where(g, ANCHOR)
        if not anchor and g.role == "FASTENER" and re.search(r"anchor", g.words, re.I) \
                and not re.search(r"anchor ?bolt|cast[- ]in", g.words, re.I):
            anchor = named
        if anchor:
            ev.add("anchors", "Yes", n, anchor)

        # Steel.
        if g.role in FRAME_ROLES and steel:
            ev.add("steel_framing", "Yes", n, mat_why or named)
        if JOIST.search(g.words) and not TIMBER.search(text):
            ev.add("steel_systems", "Steel joists", n, _where(g, JOIST) or named)
        if DECK.search(text):
            ev.add("steel_systems", "Steel deck", n, _where(g, DECK) or named)
        if COLD_FORMED.search(text):
            ev.add("steel_systems", "Cold-formed framing", n, _where(g, COLD_FORMED) or named)
        if SPACE_FRAME.search(text):
            ev.add("steel_systems", "Space frames", n, _where(g, SPACE_FRAME) or named)
        if LINTEL.search(g.words) and (steel or STEEL_SECTION.search(g.words)) and not concrete:
            ev.add("steel_systems", "Isolated members", n, named)
        if g.role == "STAIR" and (steel or GRATING.search(text) or FLOOR_PLATE.search(text)):
            if GRATING.search(text):
                ev.add("stairs", "Grating", n, _where(g, GRATING) or named)
            elif FLOOR_PLATE.search(text):
                ev.add("stairs", "Floor plate", n, _where(g, FLOOR_PLATE) or named)
            else:
                ev.add("stairs", "Metal pan", n, mat_why or named)
        if AESS.search(text):
            ev.add("aess", "Yes", n, _where(g, AESS) or named)
        if CRANE.search(text):
            ev.add("cranes", "Yes", n, _where(g, CRANE) or named)

        # Bridges.
        if g.role == "BEARING":
            ev.add("bridge_items", "Bearings", n, _as_class(g))
        if bridge:
            if g.role != "BEARING" and BEARING.search(g.words) and not LOAD_BEARING.search(g.words):
                ev.add("bridge_items", "Bearings", n, named)
            if EXPANSION_JOINT.search(g.words) or EJ.search(g.words):
                ev.add("bridge_items", "Expansion joints", n, named)
            if g.role == "RAILING" or PARAPET.search(g.words):
                ev.add("bridge_items", "Parapets and railings", n,
                       _as_class(g) if g.role == "RAILING" else named)
            if BRIDGE_DRAIN.search(g.words):
                ev.add("bridge_items", "Drainage", n, named)
            if DECK_WP.search(text):
                ev.add("bridge_items", "Deck waterproofing", n, _where(g, DECK_WP) or named)
        if GIRDER.search(text) and (bridge or re.search(r"aashto|bulb", text, re.I)):
            ev.add("bridge_items", "Prestressed girders", n, _where(g, GIRDER) or named)

        # Marine.
        if FENDER.search(g.words):
            for value, pattern in FENDER_TYPES:
                if pattern.search(g.words):
                    ev.add("fenders", value, n, named)
                    break
            else:
                fenders_untyped += n
        if BOLLARD.search(g.words) and not LAND_BOLLARD.search(g.words):
            size, read = _bollard_size(g.words)
            ev.add("bollards", size, n, named if read else f"{named}, capacity not given")
        if MOORING_RING.search(g.words) or (marine and LADDER.search(g.words)):
            ev.add("ladders", "Yes", n, named)
        if FLOATING.search(g.words):
            ev.add("floating_piers", "Yes", n, named)

        # Waterproofing: each name and material on its own, the first answer that fits.
        parts = [("named", p) for p in g.words.split(" | ")] + \
                [("of", m) for m in g.mats] + [("layer", p) for p in g.layers.split(" | ") if p]
        membrane = g.role == "COVERING" and "membrane" in g.words.lower()
        systems: set[str] = set()
        # A roof's membrane is roofing, not the waterproofing of the structure.
        parts = [] if g.role == "ROOF" else [(h, p) for h, p in parts if not ROOFING.search(p)]
        for how, part in parts:
            for value, pattern, needs in WATERPROOFING:
                if pattern.search(part) and (not needs or WP_CONTEXT.search(part) or membrane):
                    if value not in systems:
                        label = {"named": f"{g.unit} named '{part}'",
                                 "of": f"{g.unit} of '{part}'",
                                 "layer": f"{g.unit} with layer '{part}'"}[how]
                        ev.add("waterproofing", value, n, label)
                        systems.add(value)
                    break
        if not systems and g.role != "ROOF" and (WP_ANY.search(text) or membrane) \
                and not ROOFING.search(text):
            wp_untyped[g.name] += n

        # Other works.
        if g.phase:
            ev.add("demolition", "Yes", n, f"{g.unit} demolished in phase '{g.phase}'")
        elif DEMOLISH.search(text):
            ev.add("demolition", "Yes", n, _where(g, DEMOLISH) or named)
        if SHORING.search(text):
            ev.add("shoring", "Yes", n, _where(g, SHORING) or named)
        if MONITORING.search(text):
            ev.add("monitoring", "Yes", n, _where(g, MONITORING) or named)

    if pt_undecided:
        bonded = ev.has("post_tensioning", "Bonded")
        unbonded = ev.has("post_tensioning", "Unbonded")
        if not bonded or unbonded:
            target = "Unbonded" if unbonded or not bonded else "Bonded"
            for g, n, why in pt_undecided:
                ev.add("post_tensioning", target, n, why)
            if not bonded and not unbonded:
                notes.append("Post-tensioning was found, but nothing says whether it is bonded "
                             "or unbonded; it is taken as unbonded. Change it if the tendons "
                             "are grouted in ducts.")
        elif bonded:
            for g, n, why in pt_undecided:
                ev.add("post_tensioning", "Bonded", n, why)
    if fenders_untyped:
        notes.append(f"{fenders_untyped} fender{'s' if fenders_untyped != 1 else ''} "
                     f"{'were' if fenders_untyped != 1 else 'was'} found, but the names do not "
                     "say whether cone, cell, arch or pneumatic.")
    if wp_untyped:
        names = ", ".join(f"'{n}'" for n, _c in wp_untyped.most_common(3))
        notes.append(f"Waterproofing was found ({names}), but the names do not say which system; "
                     "choose it by hand.")
    return ev, notes


def _thickness_from_name(words: str, role: str) -> float | None:
    """A foundation's depth from a Revit type name: 'Raft 1500mm', '3000 x 2000 x 1200mm'."""
    m = re.search(r"\d+\s*x\s*\d+\s*x\s*(\d+)\s*mm", words, re.I)
    if m and role == "FOOTING":
        return int(m.group(1)) / 1000
    if re.search(r"\d+\s*x\s*\d+", words):
        return None
    m = re.search(r"(\d{3,4})\s*mm\b", words, re.I)
    if m:
        return int(m.group(1)) / 1000
    m = re.search(r"(\d(?:\.\d+)?)\s*m\b", words, re.I)
    return float(m.group(1)) if m else None


def _counted(count: int, label: str) -> str:
    """'3 rows named ...', '1 row named ...'; a reason that is a sentence stays as it is."""
    if label.startswith("no "):
        return label
    if count == 1:
        label = re.sub(r"^(rows|elements)\b", lambda m: m.group(1)[:-1], label)
    return f"{count} {label}"


def _elements(ev: Evidence, notes: list[str]) -> list[dict]:
    out = []
    order = {key: i for i, (key, *_rest) in enumerate(specs_seed.OPTIONS)}
    by_key: dict[str, list[tuple[str, Counter]]] = defaultdict(list)
    for (key, value), reasons in ev.found.items():
        by_key[key].append((value, reasons))
    for key in sorted(by_key, key=lambda k: order.get(k, 99)):
        answers = sorted(by_key[key], key=lambda a: CHOICES[key].index(a[0]))
        if key in ONE_ANSWER and len(answers) > 1:
            answers.sort(key=lambda a: -sum(a[1].values()))
            question = next(q for k, q, *_r in specs_seed.OPTIONS if k == key)
            listed = ", ".join(f"{v} ({sum(r.values())})" for v, r in answers)
            notes.append(f"{question}: the model has more than one ({listed}); "
                         f"{answers[0][0]} is the one given.")
            answers = answers[:1]
        for value, reasons in answers:
            top = reasons.most_common()
            why = "; ".join(_counted(c, label) for label, c in top[:3])
            if len(top) > 3:
                why += f"; and {len(top) - 3} more"
            out.append({"key": key, "value": value, "count": sum(reasons.values()), "why": why})
    return out


def _grades(model: Model, marine: bool, notes: list[str]) -> tuple[list[dict], list[dict], str]:
    concrete: dict[str, dict] = {}
    steel: dict[str, dict] = {}
    for g, n in model.groups.items():
        if g.role == "REBAR":
            continue
        kinds = [(m, material_kind(m + " " + model.material_extra.get(m, ""))) for m in g.mats]
        concrete_here = [m for m, k in kinds if k == "concrete"]
        for m, k in kinds:
            if k not in ("concrete", "steel"):
                continue
            table = concrete if k == "concrete" else steel
            row = table.setdefault(m, {"count": 0, "used_in": Counter(), "strength": Counter()})
            row["count"] += n
            row["used_in"][g.kind] += n
            if k == "concrete" and g.strength and len(concrete_here) == 1:
                row["strength"][g.strength] += n

    exposure = "Marine" if marine else ""
    concrete_rows: list[dict] = []
    for name, row in sorted(concrete.items(), key=lambda kv: -kv[1]["count"]):
        used_in = [k for k, _c in row["used_in"].most_common()]
        check = grade_check(name, used_in, exposure)
        given = model.material_strength.get(name) or \
            (row["strength"].most_common(1)[0][0] if row["strength"] else "")
        if given:
            from_props = grade_check(given if _read_grade(given) else "", used_in, exposure)
            if check["state"] == "missing" and from_props["state"] != "missing":
                check = dict(from_props)
                check["note"] = f"{from_props['note']} (From the material's properties.)"
            elif check["mpa"] and from_props["mpa"] and \
                    abs(check["mpa"] - from_props["mpa"]) > max(2.0, 0.1 * check["mpa"]):
                check = dict(check)
                if check["state"] == "ok":
                    check["state"] = "check"
                check["note"] += (f" The material's properties give {from_props['grade']} "
                                  "instead; make them agree.")
        concrete_rows.append({"material": name, "count": row["count"], "used_in": used_in,
                              "grade": check["grade"], "mpa": check["mpa"],
                              "state": check["state"], "note": check["note"]})
    steel_rows = []
    for name, row in sorted(steel.items(), key=lambda kv: -kv[1]["count"]):
        check = steel_check(name)
        steel_rows.append({"material": name, "count": row["count"],
                           "used_in": [k for k, _c in row["used_in"].most_common()],
                           "grade": check["grade"], "state": check["state"],
                           "note": check["note"]})

    ok = [r for r in concrete_rows if r["state"] == "ok"]
    concrete_class = max(ok, key=lambda r: r["count"])["grade"] if ok else ""

    # Remarks across the materials.
    by_kind: dict[str, set[str]] = defaultdict(set)
    for r in concrete_rows:
        for kind in r["used_in"]:
            if r["grade"]:
                by_kind[kind].add(r["grade"])
    for kind, grades in sorted(by_kind.items()):
        if len(grades) > 1:
            listed = sorted(grades)
            notes.append(f"{kind}: {len(listed)} concrete grades are used ("
                         f"{', '.join(listed[:-1])} and {listed[-1]}). Check that this is meant.")
    bare = [r["material"] for r in concrete_rows if r["state"] == "missing"]
    if bare:
        listed = ", ".join(f"'{m}'" for m in bare[:4]) + (f" and {len(bare) - 4} more"
                                                          if len(bare) > 4 else "")
        notes.append(f"{len(bare)} concrete material{'s have' if len(bare) != 1 else ' has'} no "
                     f"strength ({listed}): the specification will use the project's default "
                     "class for them.")
    bad = [r for r in concrete_rows if r["state"] == "unrealistic"]
    if bad:
        notes.append(f"{len(bad)} concrete grade{'s do' if len(bad) != 1 else ' does'} not look "
                     f"realistic: {', '.join(repr(r['material']) for r in bad[:4])}. "
                     f"See {'the note against each' if len(bad) != 1 else 'the note against it'}.")
    if model.no_material_column:
        notes.append("The schedule has no material column, so no grades could be read. Add "
                     "'Structural Material' or 'Material: Name' to the schedule to have them "
                     "checked.")
    elif not model.material_names:
        notes.append("No materials are assigned in this file, so no grades could be read.")
    elif not concrete_rows and not steel_rows:
        notes.append(f"None of the {len(model.material_names)} materials in this file reads as "
                     "concrete or structural steel, so no grades were checked.")
    return concrete_rows, steel_rows, concrete_class


# --- the upload --------------------------------------------------------------------

def _revit_error(filename: str, data: bytes) -> specs.SpecError:
    version = ""
    try:
        from . import specs_doc
        info = specs_doc.streams(data).get("BasicFileInfo", b"")
        text = info.decode("utf-16-le", "ignore") + " " + info.decode("latin-1", "ignore")
        m = re.search(r"Autodesk Revit (\d{4})|Format:\s*(\d{4})|Revit (\d{4})", text)
        if m:
            version = next(g for g in m.groups() if g)
    except Exception:  # the version is a nicety; the message stands without it
        version = ""
    what = "a Revit family" if filename.lower().endswith(".rfa") else "the Revit model itself"
    saved = f" (saved by Revit {version})" if version else ""
    return specs.SpecError(
        f"This is {what}{saved}. Revit keeps its models in its own closed format, which "
        "only Autodesk software can read. Upload an IFC export instead (in Revit: File → "
        "Export → IFC), or a schedule or material takeoff exported as text (View → Schedules, "
        "then File → Export → Reports → Schedule).")


def _is_ifc(data: bytes) -> bool:
    head = data[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(b"ISO-10303-21")


def read_model(filename: str, data: bytes) -> dict:
    """What an IFC export or a Revit schedule says about the project.

    The answers found (each with its reasons), what the file holds, the
    concrete and steel grades with a check of each, and general remarks.
    Raises ``specs.SpecError`` with a plain message for anything it cannot
    read, a Revit model above all.
    """
    filename = filename or ""
    lower = filename.lower()
    data = data or b""
    if not data:
        raise specs.SpecError("That file is empty. Upload " + ACCEPTS + ".")
    stem = re.sub(r"\.[^.]+$", "", filename.replace("\\", "/").split("/")[-1])

    if data[:8] == OLE:
        if lower.endswith(".xls"):
            raise specs.SpecError("That is an old Excel 97–2003 workbook (.xls). Save it as "
                                  ".xlsx, or export the schedule from Revit as text.")
        is_revit = lower.endswith(REVIT_EXTENSIONS)
        if not is_revit:
            try:
                from . import specs_doc
                is_revit = "BasicFileInfo" in specs_doc.streams(data)
            except Exception:
                is_revit = False
        if is_revit:
            raise _revit_error(filename, data)
        raise specs.SpecError("That file is not one the model reader takes. Upload "
                              + ACCEPTS + ".")
    if lower.endswith(REVIT_EXTENSIONS):
        raise _revit_error(filename, data)

    if data[:4] == b"PK\x03\x04":
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
            names = archive.namelist()
        except zipfile.BadZipFile as exc:
            raise specs.SpecError("That zip file is damaged and cannot be opened.") from exc
        ifcs = [n for n in names if n.lower().endswith(".ifc")]
        if ifcs:
            biggest = max(ifcs, key=lambda n: archive.getinfo(n).file_size)
            model = _read_ifc(archive.read(biggest))
        elif "xl/workbook.xml" in names:
            model = _read_schedule(_xlsx_rows(archive), stem)
        elif any(n.lower().endswith(".ifcxml") for n in names):
            raise specs.SpecError("That zip holds an ifcXML file, which this does not read. "
                                  "Export the IFC as .ifc or .ifczip instead.")
        else:
            raise specs.SpecError("That zip file holds no IFC model. Upload " + ACCEPTS + ".")
    elif _is_ifc(data):
        model = _read_ifc(data)
    elif lower.endswith(".ifc"):
        raise specs.SpecError("That .ifc file does not start the way an IFC file does "
                              "(ISO-10303-21). Export it again from Revit.")
    elif data[:5] == b"%PDF-":
        raise specs.SpecError("That is a PDF, which has no model data in it. Upload "
                              + ACCEPTS + ".")
    elif data[:4] in (b"AC10", b"AC1.") or lower.endswith((".dwg", ".dxf")):
        raise specs.SpecError("That is a CAD drawing, not a model export. Upload " + ACCEPTS + ".")
    else:
        text = _decode_text(data)
        start = text.lstrip()[:400].lower()
        if start.startswith("<?xml") or "<ifcxml" in start or "iso_10303_28" in start:
            raise specs.SpecError("That is an XML file (ifcXML or similar), which this does not "
                                  "read. Upload " + ACCEPTS + ".")
        if not _looks_like_text(text):
            raise specs.SpecError("That file is not one the model reader takes. Upload "
                                  + ACCEPTS + ".")
        model = _read_schedule(_text_rows(text), stem)

    ev, notes = _judge(model)
    elements = _elements(ev, notes)
    marine = ev.has("structures", "Marine structures")
    concrete, steel, concrete_class = _grades(model, marine, notes)
    return {
        "filename": filename,
        "source": model.source,
        "detail": model.detail,
        "elements": elements,
        "categories": model.categories,
        "concrete": concrete,
        "steel": steel,
        "concrete_class": concrete_class,
        "notes": model.notes + notes,
    }
