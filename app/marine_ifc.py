"""What MarineTwin reads from an uploaded IFC file, without any IFC library.

The 3D view draws the model in the browser. The server only needs a few facts
from it, and the IFC text (ISO 10303-21) is simple enough to read for those:

* **where it is** — the site's latitude, longitude and elevation (IfcSite
  RefLatitude / RefLongitude / RefElevation); failing that the MT_Project
  property set's MT_Latitude / MT_Longitude; failing that the map conversion
  (IfcMapConversion eastings and northings on a UTM grid named by its EPSG code);
* **which way it faces** — the rotation from the model's x axis to east, from
  the map conversion or the project's true north;
* **what the project says about itself** — the MT_Project property set
  (asset name and type, terminal type, vertical datum, commissioning date,
  design life, Triton project), as the MarineTwin Revit guide sets it up; and
* **the elements MarineTwin should track** — every product with a name,
  its GlobalId, its IFC class, its MT_Common properties (kind, material, zone,
  wall thickness, Triton name, design ratio, sensors) and MT_Furniture
  properties (ratings, also read from its type), and roughly where it is.

Anything the file does not carry is simply missing from the answer: nothing
here fails on an IFC it does not fully understand.

A Revit export runs to hundreds of megabytes, nearly all of it geometry the
server never needs. So the file is not parsed whole: one pass notes where each
entity starts, and only the entities the answer needs (the site, the property
sets named MT_..., the elements and their placements) are read.
"""

from __future__ import annotations

import math
import mmap
import re
from array import array
from typing import Any

# --- reading the STEP text -------------------------------------------------------------

_ENTITY = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*?)\)\s*;\s*(?=#\d+\s*=|ENDSEC)", re.S)


def _split(args: str) -> list[Any]:
    """One level of a STEP argument list: strings, numbers, refs, enums, $, * and nested lists."""
    out: list[Any] = []
    i, n = 0, len(args)
    while i < n:
        c = args[i]
        if c in " \r\n\t,":
            i += 1
            continue
        if c == "'":
            j, buf = i + 1, []
            while j < n:
                if args[j] == "'" and j + 1 < n and args[j + 1] == "'":
                    buf.append("'")
                    j += 2
                elif args[j] == "'":
                    break
                else:
                    buf.append(args[j])
                    j += 1
            out.append(_decode("".join(buf)))
            i = j + 1
        elif c == "(":
            depth, j = 1, i + 1
            in_str = False
            while j < n and depth:
                if args[j] == "'":
                    in_str = not in_str
                elif not in_str:
                    depth += args[j] == "("
                    depth -= args[j] == ")"
                j += 1
            out.append(_split(args[i + 1:j - 1]))
            i = j
        else:
            j = i
            depth = 0
            while j < n and (depth or args[j] != ","):
                depth += args[j] == "("
                depth -= args[j] == ")"
                j += 1
            token = args[i:j].strip()
            out.append(_token(token))
            i = j
    return out


def _token(token: str) -> Any:
    if token.startswith("#"):
        return ("ref", int(token[1:]))
    if token in ("$", "*"):
        return None
    if token.startswith(".") and token.endswith("."):
        return token.strip(".")
    m = re.match(r"([A-Z0-9_]+)\((.*)\)$", token, re.S)
    if m:                                             # a typed value, IFCLABEL('x') or IFCREAL(1.)
        inner = _split(m.group(2))
        return inner[0] if inner else None
    try:
        return float(token) if any(ch in token for ch in ".E") else int(token)
    except ValueError:
        return token


def _decode(text: str) -> str:
    """IFC's \\X2\\...\\X0\\ escapes for characters outside ASCII."""
    def x2(m):
        hexes = m.group(1)
        return "".join(chr(int(hexes[k:k + 4], 16)) for k in range(0, len(hexes), 4))
    text = re.sub(r"\\X2\\([0-9A-F]+)\\X0\\", x2, text)
    text = re.sub(r"\\X\\([0-9A-F]{2})", lambda m: chr(int(m.group(1), 16)), text)
    return text


_HEAD = re.compile(rb"^[ \t]*#(\d+)[ \t]*=[ \t]*([A-Z0-9_]+)", re.M)
_ONE = re.compile(rb"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*?)\)\s*;\s*(?=#\d+\s*=|ENDSEC|$)", re.S)
# The types the answer is built from; everything else is reached by reference when needed.
_WANTED = {b"IFCPROJECT", b"IFCSITE", b"IFCMAPCONVERSION", b"IFCSIUNIT", b"IFCCONVERSIONBASEDUNIT",
           b"IFCGEOMETRICREPRESENTATIONCONTEXT", b"IFCRELDEFINESBYPROPERTIES", b"IFCRELDEFINESBYTYPE",
           b"IFCRELCONTAINEDINSPATIALSTRUCTURE", b"IFCRELAGGREGATES", b"IFCPROPERTYSET"}


class Model:
    """An IFC file's entities, read on demand: get(id) gives (TYPE, [args])."""

    def __init__(self, data: bytes | mmap.mmap):
        self.data = data
        start = data.find(b"DATA;")
        self.offsets = array("q")
        self.by_type: dict[str, list[int]] = {}
        self._cache: dict[int, tuple[str, list[Any]] | None] = {}
        offsets, by_type, wanted = self.offsets, self.by_type, _WANTED
        for m in _HEAD.finditer(data, max(start, 0)):
            eid = int(m.group(1))
            if eid >= len(offsets):
                offsets.extend([-1] * (eid - len(offsets) + 65536))
            offsets[eid] = m.start(1) - 1
            kind = m.group(2)
            if kind in wanted:
                by_type.setdefault(kind.decode(), []).append(eid)

    def raw(self, eid: int) -> bytes | None:
        """The entity's text, undecoded: for a quick look before parsing it."""
        if eid < 0 or eid >= len(self.offsets) or self.offsets[eid] < 0:
            return None
        m = _ONE.match(self.data, self.offsets[eid])
        return m.group(0) if m else None

    def get(self, eid: int, default=None):
        if eid in self._cache:
            return self._cache[eid] or default
        found = None
        if 0 <= eid < len(self.offsets) and self.offsets[eid] >= 0:
            m = _ONE.match(self.data, self.offsets[eid])
            if m:
                found = (m.group(2).decode(), _split(m.group(3).decode("utf-8", "replace")))
        self._cache[eid] = found
        return found or default

    def of(self, kind: str) -> list[int]:
        return self.by_type.get(kind, [])


def parse(text: str | bytes) -> Model:
    return Model(text.encode("utf-8") if isinstance(text, str) else text)


# --- geometry helpers -------------------------------------------------------------------

def _deref(model, value):
    if isinstance(value, tuple) and value and value[0] == "ref":
        return model.get(value[1])
    return None


def _point(model, ref) -> tuple[float, float, float]:
    ent = _deref(model, ref)
    if not ent or ent[0] != "IFCCARTESIANPOINT":
        return (0.0, 0.0, 0.0)
    coords = [float(c) for c in ent[1][0]] + [0.0, 0.0, 0.0]
    return (coords[0], coords[1], coords[2])


def _direction(model, ref, default=(1.0, 0.0, 0.0)):
    ent = _deref(model, ref)
    if not ent or ent[0] != "IFCDIRECTION":
        return default
    r = [float(c) for c in ent[1][0]] + [0.0, 0.0, 0.0]
    return (r[0], r[1], r[2])


def _placement(model, ref, depth: int = 0) -> tuple[float, float, float]:
    """Where an object's local placement puts its origin, in model units.

    Each placement's offset is rotated by its parent's axes, so a model whose
    site or building is turned still comes out in one frame.
    """
    ent = _deref(model, ref)
    if not ent or ent[0] != "IFCLOCALPLACEMENT" or depth > 30:
        return (0.0, 0.0, 0.0)
    rel, axis = ent[1][0], ent[1][1]
    a = _deref(model, axis)
    local = _point(model, a[1][0]) if a else (0.0, 0.0, 0.0)
    if rel is None:
        return local
    parent_axes = _axes(model, _deref(model, rel))
    px, py, pz = _placement(model, rel, depth + 1)
    (xx, xy, xz), (yx, yy, yz), (zx, zy, zz) = parent_axes
    lx, ly, lz = local
    return (px + lx * xx + ly * yx + lz * zx, py + lx * xy + ly * yy + lz * zy, pz + lx * xz + ly * yz + lz * zz)


def _axes(model, placement_ent):
    """The x, y and z axes of a placement, in its parent's frame (rotations nest only one level here)."""
    if not placement_ent or placement_ent[0] != "IFCLOCALPLACEMENT":
        return ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    a = _deref(model, placement_ent[1][1])
    if not a or a[0] != "IFCAXIS2PLACEMENT3D":
        return ((1, 0, 0), (0, 1, 0), (0, 0, 1))
    z = _direction(model, a[1][1] if len(a[1]) > 1 else None, (0.0, 0.0, 1.0))
    x = _direction(model, a[1][2] if len(a[1]) > 2 else None, (1.0, 0.0, 0.0))
    y = (z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0])
    return (x, y, z)


def _angle(compound) -> float | None:
    """IfcCompoundPlaneAngleMeasure: degrees, minutes, seconds, millionths of a second."""
    if not isinstance(compound, list) or not compound:
        return None
    parts = [float(p) for p in compound] + [0, 0, 0, 0]
    sign = -1 if any(p < 0 for p in parts[:4]) else 1
    d, m, s, u = (abs(p) for p in parts[:4])
    return sign * (d + m / 60 + (s + u / 1e6) / 3600)


def _length_scale(model) -> float:
    """Metres per model length unit."""
    for eid in model.of("IFCSIUNIT"):
        kind, args = model.get(eid)
        if len(args) >= 4 and args[1] == "LENGTHUNIT":
            return {"MILLI": 0.001, "CENTI": 0.01, "DECI": 0.1, "KILO": 1000.0}.get(args[2], 1.0)
    for eid in model.of("IFCCONVERSIONBASEDUNIT"):
        kind, args = model.get(eid)
        if len(args) >= 3 and args[1] == "LENGTHUNIT":
            return 0.3048 if "FOOT" in str(args[2]).upper() else 0.0254 if "INCH" in str(args[2]).upper() else 1.0
    return 1.0


# --- UTM, for a model that is only on a map grid ----------------------------------------

def utm_to_latlon(easting: float, northing: float, zone: int, north: bool = True) -> tuple[float, float]:
    """WGS 84 UTM to latitude and longitude (Snyder's series; better than a metre)."""
    a, f, k0 = 6378137.0, 1 / 298.257223563, 0.9996
    e2 = f * (2 - f)
    ep2 = e2 / (1 - e2)
    x = easting - 500000.0
    y = northing if north else northing - 10000000.0
    m = y / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * math.sin(6 * mu) + (1097 * e1 ** 4 / 512) * math.sin(8 * mu))
    n1 = a / math.sqrt(1 - e2 * math.sin(phi1) ** 2)
    t1 = math.tan(phi1) ** 2
    c1 = ep2 * math.cos(phi1) ** 2
    r1 = a * (1 - e2) / (1 - e2 * math.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * k0)
    lat = phi1 - (n1 * math.tan(phi1) / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * ep2) * d ** 4 / 24
                                                + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * ep2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = (d - (1 + 2 * t1 + c1) * d ** 3 / 6 + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * ep2 + 24 * t1 ** 2) * d ** 5 / 120) / math.cos(phi1)
    return math.degrees(lat), (zone - 1) * 6 - 180 + 3 + math.degrees(lon)


def _epsg_utm(name: str) -> tuple[int, bool] | None:
    m = re.search(r"(?:EPSG:?)?\s*(32[67])(\d{2})", name or "")
    if not m:
        return None
    return int(m.group(2)), m.group(1) == "326"


# --- the answer ----------------------------------------------------------------------

# How an IFC class reads as a MarineTwin kind, when the element does not say.
CLASS_KIND = {
    "IFCPILE": "pile", "IFCSLAB": "slab", "IFCBEAM": "beam", "IFCRAIL": "crane_rail",
    "IFCWALL": "sheet_pile", "IFCWALLSTANDARDCASE": "sheet_pile", "IFCMEMBER": "tie_rod",
}
# And how a name does, by the guide's prefixes: longest first, so BOL wins over B.
NAME_KIND = [
    ("BOL", "bollard"), ("LAD", "ladder"), ("STP", "storm_pin"), ("CW", "combi_wall"), ("SP", "sheet_pile"),
    ("DK", "slab"), ("CB", "beam"), ("BM", "beam"), ("CR", "crane_rail"), ("CS", "crane_stopper"),
    ("TR", "tie_rod"), ("RR", "ramp"), ("P", "pile"), ("F", "fender"),
]
KIND_MATERIAL = {"fender": "rubber", "slab": "concrete", "beam": "concrete"}
KIND_ZONE = {"pile": "splash", "combi_wall": "tidal", "sheet_pile": "tidal", "slab": "atmospheric", "beam": "splash",
             "fender": "splash", "bollard": "atmospheric", "crane_rail": "atmospheric", "crane_stopper": "atmospheric",
             "storm_pin": "atmospheric", "ladder": "splash", "tie_rod": "buried", "ramp": "splash", "other": "splash"}
PRODUCT_SKIP = {"IFCPROJECT", "IFCSITE", "IFCBUILDING", "IFCBUILDINGSTOREY", "IFCSPACE", "IFCOPENINGELEMENT",
                "IFCANNOTATION", "IFCGRID", "IFCVIRTUALELEMENT"}
TERMINALS = {"container": "container", "general_cargo": "general_cargo", "general cargo": "general_cargo",
             "generalcargo": "general_cargo", "roro": "roro", "ro-ro": "roro", "bulk": "bulk", "dry bulk": "bulk",
             "multipurpose": "multipurpose", "multi-purpose": "multipurpose"}


# The legend tags of DAR's Revit quay models: MP1-DS03 is middle pile 1 of design section 3,
# RP a rear pile, FKS and FKC a front king pile (steel and its concrete fill), L1/L2 a lowered
# pile, SPW a sheet pile wall.
LEGEND_KIND = [
    (re.compile(r"(?:MP|RP|FP|P)\d*(?:-DS\d+)?(?:-?L\d)?"), "pile"),
    (re.compile(r"FK[SC]\d*(?:-DS\d+)?(?:-?L\d)?"), "pile"),
    (re.compile(r"SPW\d*(?:-DS\d+)?"), "sheet_pile"),
]


def _kind_from_name(name: str) -> str | None:
    up = name.upper()
    for pattern, kind in LEGEND_KIND:
        if pattern.fullmatch(up):
            return kind
    for prefix, kind in NAME_KIND:
        if re.fullmatch(prefix + r"[-_ ]?\d+[A-Z]?|" + prefix + r"-[A-Z]+", up):
            return kind
    return None


_MT_SET = re.compile(rb"IFCPROPERTYSET\s*\(\s*'[^']*'\s*,[^,]*,\s*'MT_")
_REFS = re.compile(rb"#(\d+)")


def read(text: str | bytes | mmap.mmap) -> dict[str, Any]:
    model = text if isinstance(text, Model) else parse(text)
    scale = _length_scale(model)

    # Property sets, by the objects they are attached to (directly or through their type).
    # Only MarineTwin's own sets (MT_...) are read: a Revit export has thousands of others.
    mt_sets = {eid for eid in model.of("IFCPROPERTYSET") if _MT_SET.match(model.raw(eid) or b"", (model.raw(eid) or b"").find(b"IFCPROPERTYSET"))}
    psets: dict[int, dict[str, dict[str, Any]]] = {}

    def props_of(pset_ref) -> tuple[str, dict[str, Any]] | None:
        if not (isinstance(pset_ref, tuple) and pset_ref[1] in mt_sets):
            return None
        ent = _deref(model, pset_ref)
        if not ent or ent[0] != "IFCPROPERTYSET":
            return None
        out = {}
        for p in ent[1][4] or []:
            pe = _deref(model, p)
            if pe and pe[0] == "IFCPROPERTYSINGLEVALUE":
                out[str(pe[1][0])] = pe[1][2]
        return str(ent[1][2]), out

    for rid in model.of("IFCRELDEFINESBYPROPERTIES"):
        raw = model.raw(rid) or b""
        last = _REFS.findall(raw[raw.rfind(b","):]) if raw else []
        if not last or int(last[-1]) not in mt_sets:
            continue                                  # not one of ours: no need to read it
        args = model.get(rid)[1]
        found = props_of(args[5])
        if found:
            for obj in args[4] or []:
                psets.setdefault(obj[1], {}).setdefault(found[0], {}).update(found[1])
    for rid in model.of("IFCRELDEFINESBYTYPE"):
        raw = model.raw(rid) or b""
        type_ref = _REFS.findall(raw[raw.rfind(b","):])
        if not type_ref:
            continue
        type_id = int(type_ref[-1])
        type_raw = model.raw(type_id) or b""
        if type_id not in psets and not any(int(r) in mt_sets for r in _REFS.findall(type_raw)):
            continue
        args = model.get(rid)[1]
        type_ent = _deref(model, args[5])
        if not type_ent:
            continue
        type_sets = {}
        # A type object's own property sets: HasPropertySets is its fifth attribute.
        for ref in (type_ent[1][5] if len(type_ent[1]) > 5 and isinstance(type_ent[1][5], list) else []):
            found = props_of(ref)
            if found:
                type_sets.setdefault(found[0], {}).update(found[1])
        type_sets_rel = psets.get(type_id, {})
        for obj in args[4] or []:
            mine = psets.setdefault(obj[1], {})
            for name, values in list(type_sets.items()) + list(type_sets_rel.items()):
                merged = dict(values)
                merged.update(mine.get(name, {}))           # the instance's own value wins
                mine[name] = merged

    out: dict[str, Any] = {"length_unit_m": scale, "site": {}, "project": {}, "elements": []}

    # The project and its own MarineTwin settings.
    for eid in model.of("IFCPROJECT"):
        args = model.get(eid)[1]
        out["project"] = {"name": args[2] or "", **psets.get(eid, {}).get("MT_Project", {})}
        break

    # The site.
    site = {}
    for eid in model.of("IFCSITE")[:1]:
        kind, args = model.get(eid)
        if True:
            lat, lon = _angle(args[9] if len(args) > 9 else None), _angle(args[10] if len(args) > 10 else None)
            elev = args[11] if len(args) > 11 and isinstance(args[11], (int, float)) else None
            if lat is not None and lon is not None and not (lat == 0 and lon == 0):
                site.update(latitude=round(lat, 7), longitude=round(lon, 7), source="IfcSite")
            if elev is not None:
                site["elevation"] = round(float(elev) * scale, 3)
            site["name"] = args[2] or ""
    proj = out["project"]
    if "latitude" not in site:
        try:
            lat, lon = float(proj.get("MT_Latitude")), float(proj.get("MT_Longitude"))
            site.update(latitude=lat, longitude=lon, source="MT_Project")
        except (TypeError, ValueError):
            pass

    # The map conversion: eastings, northings and the grid's rotation.
    rotation = None
    for eid in model.of("IFCMAPCONVERSION")[:1]:
        kind, args = model.get(eid)
        if True:
            east, north, height = (float(args[2] or 0), float(args[3] or 0), float(args[4] or 0))
            abscissa = float(args[5]) if isinstance(args[5], (int, float)) else 1.0
            ordinate = float(args[6]) if isinstance(args[6], (int, float)) else 0.0
            rotation = math.degrees(math.atan2(ordinate, abscissa))
            crs = _deref(model, args[1])
            crs_name = str(crs[1][0]) if crs else ""
            site.update(eastings=east, northings=north, crs=crs_name)
            utm = _epsg_utm(crs_name) or _epsg_utm(str(proj.get("MT_EPSG", "")))
            if "latitude" not in site and utm:
                lat, lon = utm_to_latlon(east, north, *utm)
                site.update(latitude=round(lat, 7), longitude=round(lon, 7), source=f"IfcMapConversion, {crs_name or proj.get('MT_EPSG')}")
    if rotation is None:
        # True north in the model's plan, from the main 3D context: the angle that turns it to north.
        for eid in model.of("IFCGEOMETRICREPRESENTATIONCONTEXT"):
            kind, args = model.get(eid)
            if len(args) > 5 and args[5] is not None:
                nx, ny, _ = _direction(model, args[5], (0.0, 1.0, 0.0))
                rotation = math.degrees(math.atan2(nx, ny))
                break
    site["rotation"] = round(rotation or 0.0, 3)
    site["epsg"] = str(proj.get("MT_EPSG") or site.get("crs") or "")
    out["site"] = site

    datum = str(proj.get("MT_VerticalDatum") or "")
    m = re.search(r"MSL\s*[-−–]\s*(\d+(?:\.\d+)?)", datum) or re.search(r"MSL\s*=?\s*\+?\s*(\d+(?:\.\d+)?)\s*m?\s*CD", datum)
    out["msl_cd"] = float(m.group(1)) if m else None
    terminal = str(proj.get("MT_TerminalType") or "").strip().lower()
    out["terminal_type"] = TERMINALS.get(terminal)

    # Element positions are kept relative to the site's own origin, so a site placed at its
    # map eastings and northings still gives positions in metres from the site.
    site_origin = (0.0, 0.0, 0.0)
    for eid in model.of("IFCSITE")[:1]:
        kind, args = model.get(eid)
        if isinstance(args[5], tuple):
            ox, oy, _ = _placement(model, args[5])
            site_origin = (ox * scale, oy * scale, 0.0)   # elevations stay as modelled: mCD
            break

    # The elements: products with a name MarineTwin can track. They are the ones placed in
    # the building (contained in a storey or site, or parts of an assembly), and anything
    # carrying an MT_ property set.
    candidates: dict[int, None] = {}
    for rel_type, at in (("IFCRELCONTAINEDINSPATIALSTRUCTURE", 4), ("IFCRELAGGREGATES", 5)):
        for rid in model.of(rel_type):
            args = model.get(rid)[1]
            for ref in (args[at] if len(args) > at and isinstance(args[at], list) else []):
                if isinstance(ref, tuple):
                    candidates[ref[1]] = None
    for eid in psets:
        candidates[eid] = None
    for eid in sorted(candidates):
        ent = model.get(eid)
        if not ent:
            continue
        kind, args = ent
        if not kind.startswith("IFC") or kind in PRODUCT_SKIP or len(args) < 7:
            continue
        if kind.startswith("IFCREL") or kind.endswith("TYPE") or not isinstance(args[0], str) or len(args[0]) != 22:
            continue
        placement = args[5]
        if not (isinstance(placement, tuple) and model.get(placement[1], ("",))[0] == "IFCLOCALPLACEMENT"):
            continue
        name = (args[2] or "").strip()
        tag = args[7] if len(args) > 7 and isinstance(args[7], str) else ""
        if tag and not _kind_from_name(name) and _kind_from_name(tag.strip()):
            name = tag.strip()                        # an older export: the ID is in Tag, Name is Family:Type:Id
        sets = psets.get(eid, {})
        common, furniture = sets.get("MT_Common", {}), sets.get("MT_Furniture", {})
        mt_kind = str(common.get("MT_Kind") or "").strip().lower() or None
        if mt_kind == "other" and name.upper().startswith("RR"):
            mt_kind = "ramp"
        by_name = _kind_from_name(name) if name else None
        if not name or not (mt_kind or by_name):
            continue                                  # untracked detail: no MarineTwin kind and no guide name
        element_kind = mt_kind or by_name or CLASS_KIND.get(kind, "other")
        x, y, z = (c * scale - o for c, o in zip(_placement(model, placement), site_origin))

        def num(value):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        wall = num(common.get("MT_WallThickness"))
        if wall is not None and scale == 1.0 and wall < 0.2:
            wall *= 1000                              # a length exported in metres
        out["elements"].append({
            "global_id": args[0], "ifc_class": kind, "name": name, "tag": tag,
            "kind": element_kind, "material": str(common.get("MT_Material") or KIND_MATERIAL.get(element_kind, "steel")).lower(),
            "zone": str(common.get("MT_Zone") or KIND_ZONE.get(element_kind, "splash")).lower(),
            "wall_mm": wall, "triton_element": str(common.get("MT_TritonElement") or ""),
            "design_ur": num(common.get("MT_DesignUR")),
            "sensors": [s.strip().lower().replace(" ", "_") for s in re.split(r"[;,]", str(common.get("MT_Sensors") or "")) if s.strip()],
            "legend": str(common.get("MT_Legend") or "").strip(),
            "rated_reaction": num(furniture.get("MT_RatedReaction")), "rated_energy": num(furniture.get("MT_RatedEnergy")),
            "bollard_capacity": num(furniture.get("MT_BollardCapacity")),
            "x": round(x, 3), "y": round(y, 3), "z": round(z, 3),
        })
    # Several elements often share one name: every pile of a design section is MP1-DS03. Each
    # becomes its own element, numbered along the berth (MP1-DS03-01, -02, ...).
    by_name: dict[str, list[dict[str, Any]]] = {}
    for e in out["elements"]:
        by_name.setdefault(e["name"], []).append(e)
    for name, same in by_name.items():
        if len(same) > 1:
            same.sort(key=lambda e: (e["x"], e["y"], e["z"], e["global_id"]))
            width = max(2, len(str(len(same))))
            for i, e in enumerate(same, 1):
                e["group"] = name
                e["name"] = f"{name}-{i:0{width}d}"
    out["elements"].sort(key=lambda e: e["name"])
    return out


def read_file(path) -> dict[str, Any]:
    # Mapped rather than read: a 200 MB export is indexed in place, without a copy in memory.
    with open(path, "rb") as f:
        try:
            buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:  # an empty file cannot be mapped
            return read(b"")
        try:
            return read(buf)
        finally:
            buf.close()
