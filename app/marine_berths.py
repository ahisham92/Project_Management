"""Who berths where: the quay's berths, the ships calling, and the berth plan that puts them together.

The berths come from the 3D view (it finds them from the crane stoppers along the quay and sends them
here), or are estimated from the quay's length until it has been opened; either can be changed. The
ship calls start as a typical week for the terminal, flagged, with their lines, sizes and boxes, and
the person replaces or amends them (one by one, or a CSV from the port community system or the lines'
schedules). The plan gives each call a berth by the rule chosen, and says why and how long it waited.
"""

from __future__ import annotations

import csv
import io
import random
from datetime import datetime, timedelta
from typing import Any, Iterable

# --- flags --------------------------------------------------------------------------------------

# The flags ships fly most, drawn simply: (name, layout, colours). Layouts: "h" horizontal stripes,
# "v" vertical stripes, "nordic" a cross off centre, "canton" stripes with a block top left,
# "disc" a disc on a field, "quarters" four quarters, "hoist" stripes with a band at the hoist,
# "triangle" stripes with a triangle at the hoist, "diag" a field with a diagonal band.
FLAGS: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "PA": ("Panama", "quarters", ("#ffffff", "#d21034", "#005293", "#ffffff")),
    "LR": ("Liberia", "canton", ("#bf0a30", "#ffffff", "#002868")),
    "MH": ("Marshall Islands", "diag", ("#003893", "#ffffff", "#dd7500")),
    "MT": ("Malta", "v", ("#ffffff", "#cf142b")),
    "SG": ("Singapore", "h", ("#ef3340", "#ffffff")),
    "HK": ("Hong Kong", "disc", ("#de2910", "#ffffff")),
    "BS": ("Bahamas", "triangle", ("#00778b", "#ffc72c", "#00778b", "#000000")),
    "GR": ("Greece", "canton", ("#0d5eaf", "#ffffff", "#0d5eaf")),
    "CY": ("Cyprus", "disc", ("#ffffff", "#d57800")),
    "PT": ("Portugal", "v", ("#046a38", "#da291c", "#da291c")),
    "DK": ("Denmark", "nordic", ("#c8102e", "#ffffff")),
    "NO": ("Norway", "nordic", ("#ba0c2f", "#00205b")),
    "DE": ("Germany", "h", ("#000000", "#dd0000", "#ffce00")),
    "FR": ("France", "v", ("#002395", "#ffffff", "#ed2939")),
    "GB": ("United Kingdom", "nordic", ("#012169", "#c8102e")),
    "JP": ("Japan", "disc", ("#ffffff", "#bc002d")),
    "CN": ("China", "disc", ("#de2910", "#ffde00")),
    "NG": ("Nigeria", "v", ("#008751", "#ffffff", "#008751")),
    "GH": ("Ghana", "h", ("#ce1126", "#fcd116", "#006b3f")),
    "CI": ("Côte d'Ivoire", "v", ("#f77f00", "#ffffff", "#009e60")),
    "SA": ("Saudi Arabia", "h", ("#006c35", "#006c35")),
    "AE": ("United Arab Emirates", "hoist", ("#00732f", "#ffffff", "#000000", "#ff0000")),
    "EG": ("Egypt", "h", ("#ce1126", "#ffffff", "#000000")),
    "IT": ("Italy", "v", ("#009246", "#ffffff", "#ce2b37")),
    "NL": ("Netherlands", "h", ("#ae1c28", "#ffffff", "#21468b")),
}


def flag_name(code: str | None) -> str:
    return FLAGS.get((code or "").upper(), (code or "Unknown",))[0]


def flag_svg(code: str | None, width: int = 24) -> str:
    """A small flag as inline SVG (flag emoji do not show on Windows)."""
    code = (code or "").upper()
    name, layout, c = FLAGS.get(code, (code or "No flag given", "h", ("#9e9e9e", "#e0e0e0")))
    w, h = 30, 20
    parts: list[str] = []
    rect = lambda x, y, ww, hh, col: parts.append(f'<rect x="{x}" y="{y}" width="{ww}" height="{hh}" fill="{col}"/>')  # noqa: E731
    if layout == "h":
        for i, col in enumerate(c):
            rect(0, i * h / len(c), w, h / len(c) + 0.2, col)
    elif layout == "v":
        for i, col in enumerate(c):
            rect(i * w / len(c), 0, w / len(c) + 0.2, h, col)
    elif layout == "nordic":
        rect(0, 0, w, h, c[0])
        rect(9, 0, 4, h, c[1])
        rect(0, 8, w, 4, c[1])
    elif layout == "canton":
        for i in range(5):
            rect(0, i * h / 5, w, h / 5 + 0.2, c[0] if i % 2 == 0 else c[1])
        rect(0, 0, 12, 12, c[2])
        if code == "GR":
            rect(5, 0, 2, 12, c[1])
            rect(0, 5, 12, 2, c[1])
        else:
            parts.append(f'<circle cx="6" cy="6" r="2.5" fill="{c[1]}"/>')
    elif layout == "disc":
        rect(0, 0, w, h, c[0])
        centred = code in ("JP",)
        parts.append(f'<circle cx="{w / 2 if centred else 8}" cy="{h / 2 if centred else 7}" r="{6 if centred else 3.5}" fill="{c[1]}"/>')
    elif layout == "quarters":
        rect(0, 0, w / 2, h / 2, c[0])
        rect(w / 2, 0, w / 2, h / 2, c[1])
        rect(0, h / 2, w / 2, h / 2, c[2])
        rect(w / 2, h / 2, w / 2, h / 2, c[3])
        parts.append(f'<circle cx="7.5" cy="5" r="2" fill="{c[2]}"/><circle cx="22.5" cy="15" r="2" fill="{c[1]}"/>')
    elif layout == "hoist":
        for i, col in enumerate(c[:3]):
            rect(0, i * h / 3, w, h / 3 + 0.2, col)
        rect(0, 0, 8, h, c[3])
    elif layout == "triangle":
        for i, col in enumerate(c[:3]):
            rect(0, i * h / 3, w, h / 3 + 0.2, col)
        parts.append(f'<polygon points="0,0 13,10 0,20" fill="{c[3]}"/>')
    elif layout == "diag":
        rect(0, 0, w, h, c[0])
        parts.append(f'<polygon points="0,20 30,2 30,6 0,20" fill="{c[1]}"/><polygon points="0,20 30,6 30,10" fill="{c[2]}"/>')
    return (f'<svg class="mt-flag" viewBox="0 0 {w} {h}" width="{width}" height="{round(width * h / w)}" role="img" '
            f'aria-label="{name}"><title>{name}</title>{"".join(parts)}<rect width="{w}" height="{h}" fill="none" '
            f'stroke="rgba(0,0,0,.25)"/></svg>')


# --- the ships ---------------------------------------------------------------------------------

# A typical fleet for each kind of terminal: name, type, line, flag, LOA m, beam m, draught m, DWT t,
# and the boxes (or units) worked in a call, as a share of what she carries.
FLEET = {
    "container": [
        ("MSC Aurora", "Container", "MSC", "PA", 300, 48.2, 14.0, 140000, 2400),
        ("Maersk Kendal", "Container", "Maersk", "DK", 294, 32.3, 13.0, 95000, 1700),
        ("CMA CGM Thalia", "Container", "CMA CGM", "MT", 334, 42.8, 14.5, 150000, 2600),
        ("Ever Lucent", "Container", "Evergreen", "SG", 366, 48.2, 15.0, 190000, 3000),
        ("ONE Harmony", "Container", "ONE", "JP", 260, 32.3, 12.5, 70000, 1300),
        ("Hapag Riyadh", "Container", "Hapag-Lloyd", "DE", 368, 51.0, 15.5, 200000, 3200),
        ("MSC Lagos", "Container", "MSC", "LR", 229, 32.3, 12.0, 55000, 1100),
        ("Maersk Abidjan", "Container", "Maersk", "SG", 249, 37.3, 12.5, 65000, 1250),
        ("CMA CGM Tema", "Container", "CMA CGM", "FR", 228, 32.3, 11.8, 52000, 1000),
        ("Cosco Shenzhen", "Container", "COSCO", "HK", 335, 48.0, 14.8, 160000, 2700),
        ("Grimaldi Feeder", "Container", "Grimaldi", "IT", 170, 27.0, 9.5, 23000, 600),
        ("Arkas Ghana", "Container", "Arkas", "MH", 185, 30.0, 10.5, 28000, 700),
    ],
    "general_cargo": [
        ("Gulf Pioneer", "General cargo", "Gulf Shipping", "AE", 180, 28.0, 10.0, 35000, 900),
        ("BBC Lagos", "Heavy lift", "BBC Chartering", "PT", 154, 23.0, 8.8, 22000, 300),
        ("Atlantic Trader", "General cargo", "Atlantic", "LR", 190, 30.0, 10.5, 40000, 1000),
        ("Spliethoff Eems", "Multipurpose", "Spliethoff", "NL", 169, 25.2, 9.5, 28000, 700),
        ("Africa Star", "Breakbulk", "Africa Lines", "NG", 200, 32.2, 11.0, 48000, 1100),
    ],
    "roro": [
        ("Grande Lagos", "RoRo", "Grimaldi", "IT", 236, 32.3, 10.0, 26000, 1800),
        ("Hoegh Target", "Car carrier", "Höegh Autoliners", "NO", 200, 36.5, 9.5, 21000, 2500),
        ("Grande Abidjan", "RoRo", "Grimaldi", "IT", 211, 32.3, 9.8, 24000, 1500),
        ("Glovis Sun", "Car carrier", "Hyundai Glovis", "MH", 199, 32.3, 9.2, 20000, 2200),
        ("Celine", "RoRo", "CLdN", "MT", 235, 35.0, 8.0, 25000, 1400),
    ],
    "bulk": [
        ("Arabian Star", "Bulk carrier", "Bahri", "SA", 229, 32.3, 13.5, 82000, 1500),
        ("Cape Onne", "Bulk carrier", "Oldendorff", "LR", 190, 32.2, 12.0, 56000, 1100),
        ("Star Kirkenes", "Bulk carrier", "Star Bulk", "GR", 200, 32.3, 12.8, 64000, 1200),
        ("Ocean Grain", "Bulk carrier", "Ocean Grain", "CY", 180, 30.0, 11.5, 45000, 900),
    ],
}
FLEET["multipurpose"] = FLEET["container"][:6] + FLEET["general_cargo"][:3] + FLEET["roro"][:2]

SHORT_LINE = {"Evergreen": "Ever", "Hapag-Lloyd": "Hapag", "COSCO": "Cosco", "Hyundai Glovis": "Glovis",
              "Höegh Autoliners": "Hoegh", "Gulf Shipping": "Gulf", "BBC Chartering": "BBC", "Africa Lines": "Africa",
              "Ocean Grain": "Ocean", "Star Bulk": "Star"}
PLACES = ["Accra", "Dakar", "Lomé", "Cotonou", "Douala", "Luanda", "Durban", "Mombasa", "Tangier", "Algeciras", "Valencia",
          "Genoa", "Antwerp", "Rotterdam", "Hamburg", "Felixstowe", "Jeddah", "Salalah", "Colombo", "Ningbo", "Busan",
          "Santos", "Callao", "Houston", "Savannah", "Lisbon", "Casablanca", "Monrovia", "Freetown", "Conakry", "Banjul",
          "Pointe-Noire", "Walvis Bay", "Djibouti", "Aqaba", "Piraeus", "Marseille", "Le Havre", "Bremen", "Gdansk"]

FIELDS = [
    # key, label, kind, required
    ("ship", "Ship", "text", True), ("imo", "IMO number", "text", False), ("flag", "Flag", "flag", False),
    ("type", "Type", "text", False), ("line", "Line or operator", "text", False),
    ("loa", "Length overall (m)", "number", True), ("beam", "Beam (m)", "number", False),
    ("draught", "Arrival draught (m)", "number", True), ("dwt", "Deadweight (t)", "number", False),
    ("moves", "Containers or units to work", "number", True), ("eta", "Arrives (ETA)", "datetime", True),
    ("window", "Contracted berth window", "bool", False), ("wish", "Berth asked for", "number", False),
    ("notes", "Notes", "text", False),
]
COLUMNS = [f[0] for f in FIELDS]

# Which berths each kind of ship can use, by the berth's use.
FITS_USE = {
    "Container": {"container", "mixed", "multipurpose"},
    "RoRo": {"roro", "mixed"}, "Car carrier": {"roro", "mixed"},
    "General cargo": {"general_cargo", "mixed", "multipurpose", "container"},
    "Heavy lift": {"general_cargo", "mixed", "multipurpose", "container"},
    "Multipurpose": {"general_cargo", "mixed", "multipurpose", "container"},
    "Breakbulk": {"general_cargo", "mixed", "multipurpose", "container"},
    "Bulk carrier": {"bulk", "general_cargo", "mixed", "multipurpose"},
}
USES = [("container", "Containers"), ("general_cargo", "General cargo"), ("roro", "RoRo and cars"),
        ("mixed", "Any ship"), ("bulk", "Dry bulk")]
CRANE_KINDS = [("STS", "Ship-to-shore cranes on rails"), ("MHC", "Mobile harbour cranes"), ("ramp", "Ramp (RoRo)"), ("none", "Ship's own gear")]
RATE = {"STS": 25.0, "MHC": 18.0, "ramp": 110.0, "none": 10.0}   # boxes or units an hour, each crane or ramp
UKC = 0.10           # under-keel clearance: 10% of the draught (PIANC for a sheltered berth)
LENGTH_MARGIN = 15.0  # metres of berth beyond the ship's length, for her lines
MOOR_HOURS = 3.0     # berthing, mooring, lashing and unmooring
POLICIES = {
    "fcfs": ("First come, first served", "Each ship gets the first free berth that fits her, in the order she arrives. Fair and simple; the usual rule at a common-user terminal."),
    "windows": ("Berth windows first", "Liner services with a contracted window get their berth at their time; the rest fill the gaps first come, first served. The usual rule at a container terminal with weekly services."),
    "shortest": ("Shortest call first", "Of the ships waiting when a berth frees, the quickest to work goes first. It can cut the waiting when the queue is long, but a big ship can wait long; the table shows which rule does best this week."),
}


def _rng(*key: Any) -> random.Random:
    return random.Random("|".join(str(k) for k in key))


def estimate_berths(length: float, terminal: str, stoppers: int = 0) -> list[dict[str, Any]]:
    """Berths of about 300 m along the quay until the 3D view has found the real ones."""
    n = max(1, round(length / 290))
    each = max(length / n, 300.0)      # a model shorter than a berth is taken as a section of one
    use = {"container": "container", "roro": "roro", "bulk": "bulk", "multipurpose": "mixed"}.get(terminal, "general_cargo")
    kind = "STS" if terminal == "container" and stoppers else "ramp" if terminal == "roro" else "MHC"
    depth = {"container": 17.0, "bulk": 15.0, "roro": 11.0, "multipurpose": 16.0}.get(terminal, 13.0)
    return [{"n": i + 1, "name": f"Berth {i + 1}", "length": round(each), "depth": depth,
             "cranes": 3 if kind == "STS" else 2 if kind == "MHC" else 1, "crane_kind": kind, "use": use,
             "main": i == n // 2, "source": "estimate"} for i in range(n)]


def berths(db, asset: Any, length: float | None = None, stoppers: int = 0) -> list[dict[str, Any]]:
    rows = db.execute("SELECT * FROM marine_berths WHERE asset_id = ? ORDER BY n", (asset["id"],)).fetchall()
    if rows:
        return [dict(r) for r in rows]
    return estimate_berths(length or 300.0, asset["terminal_type"] or "container", stoppers)


def save_layout(db, asset: Any, found: Iterable[dict[str, Any]]) -> int:
    """The berths the 3D view found: kept for berths the person has not changed."""
    terminal = asset["terminal_type"] or "container"
    have = {r["n"]: dict(r) for r in db.execute("SELECT * FROM marine_berths WHERE asset_id = ?", (asset["id"],))}
    depth = {"container": 17.0, "bulk": 15.0, "roro": 11.0, "multipurpose": 16.0}.get(terminal, 13.0)
    written = 0
    for b in found:
        try:
            n, length = int(b["n"]), float(b["length"])
        except (KeyError, TypeError, ValueError):
            continue
        if not 0 < n <= 200 or not 10 <= length <= 5000:
            continue
        old = have.get(n)
        if old and old["source"] == "user":
            continue
        sts = bool(b.get("sts"))
        use = b.get("use") or ("container" if sts else {"roro": "roro", "bulk": "bulk"}.get(terminal, "mixed"))
        kind = "STS" if sts else "ramp" if use == "roro" else "MHC"
        db.execute("INSERT INTO marine_berths (asset_id, n, name, length, depth, cranes, crane_kind, use, main, source)"
                   " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'model') ON CONFLICT(asset_id, n) DO UPDATE SET length = excluded.length,"
                   " crane_kind = excluded.crane_kind, cranes = excluded.cranes, use = excluded.use, main = excluded.main",
                   (asset["id"], n, f"Berth {n}", round(length), depth, max(1, min(4, round(length / 130))) if sts else 2 if kind == "MHC" else 1,
                    kind, use, int(bool(b.get("main")))))
        written += 1
    return written


def save_berth(db, asset_id: int, n: int, form: dict[str, Any]) -> None:
    def num(key: str, lo: float, hi: float, default: float) -> float:
        try:
            v = float(form.get(key))
        except (TypeError, ValueError):
            return default
        return v if lo <= v <= hi else default

    old = db.execute("SELECT * FROM marine_berths WHERE asset_id = ? AND n = ?", (asset_id, n)).fetchone()
    old = dict(old) if old else {"name": f"Berth {n}", "length": 300, "depth": 15, "cranes": 2, "crane_kind": "MHC", "use": "mixed", "main": 0}
    kind = form.get("crane_kind") if form.get("crane_kind") in dict(CRANE_KINDS) else old["crane_kind"]
    use = form.get("use") if form.get("use") in dict(USES) else old["use"]
    db.execute("INSERT INTO marine_berths (asset_id, n, name, length, depth, cranes, crane_kind, use, main, source)"
               " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'user') ON CONFLICT(asset_id, n) DO UPDATE SET name = excluded.name,"
               " length = excluded.length, depth = excluded.depth, cranes = excluded.cranes, crane_kind = excluded.crane_kind,"
               " use = excluded.use, source = 'user'",
               (asset_id, n, (form.get("name") or old["name"]).strip()[:60], num("length", 20, 5000, old["length"]),
                num("depth", 3, 30, old["depth"]), int(num("cranes", 0, 12, old["cranes"])), kind, use, old.get("main", 0)))


def keep_estimate(db, asset: Any, estimate: list[dict[str, Any]]) -> None:
    """Before the first change to one berth, keep the others as they are shown."""
    if db.execute("SELECT 1 FROM marine_berths WHERE asset_id = ?", (asset["id"],)).fetchone():
        return
    for b in estimate:
        db.execute("INSERT INTO marine_berths (asset_id, n, name, length, depth, cranes, crane_kind, use, main, source)"
                   " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   (asset["id"], b["n"], b["name"], b["length"], b["depth"], b["cranes"], b["crane_kind"], b["use"],
                    int(bool(b.get("main"))), b.get("source", "estimate")))


def week_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def typical_calls(asset_id: int, terminal: str, the_berths: list[dict[str, Any]], start: datetime, days: int = 7) -> list[dict[str, Any]]:
    """A typical week of calls: enough ships to keep the berths about two-thirds busy (big ships hold two)."""
    rng = _rng(asset_id, start.date().isoformat(), "calls")
    fleet = FLEET.get(terminal, FLEET["container"])
    hours = days * 24
    capacity = sum(max(1, b["cranes"]) * RATE.get(b["crane_kind"], 18) for b in the_berths) or 50
    mean_moves = sum(f[8] for f in fleet) / len(fleet)
    gap = mean_moves / (0.55 * capacity)        # hours between arrivals that keep the berths two-thirds busy
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    work = 0.0
    t = rng.uniform(0, 4)
    i = 0
    while t < hours - 6 and work < 0.55 * capacity * hours:
        name, kind, line, flag, loa, beam, draught, dwt, moves = fleet[rng.randrange(len(fleet))]
        if name in used:
            # A sister ship of the same class: the same size, another name.
            prefix = SHORT_LINE.get(line, line.split()[0])
            name = next((f"{prefix} {p}" for p in rng.sample(PLACES, len(PLACES)) if f"{prefix} {p}" not in used), f"{name} {i}")
        used.add(name)
        voyage = f"{i + 1:03d}"
        boxes = int(moves * rng.uniform(0.7, 1.15))
        out.append({"id": None, "ship": name, "imo": "", "flag": flag, "type": kind, "line": line, "loa": loa, "beam": beam,
                    "draught": round(draught * rng.uniform(0.88, 1.0), 1), "dwt": dwt, "moves": boxes,
                    "eta": start + timedelta(hours=round(t, 1)), "window": int(kind == "Container" and rng.random() < 0.5),
                    "wish": None, "notes": f"Voyage {voyage}, typical", "source": "typical"})
        work += boxes
        t += rng.uniform(0.3, 1.7) * gap
        i += 1
    return out


def calls(db, asset: Any, the_berths: list[dict[str, Any]], start: datetime) -> tuple[list[dict[str, Any]], bool]:
    """The ship calls, and whether the person has made the list theirs. A typical week left as it was
    moves on with the calendar; one the person has changed stays as they left it."""
    rows = [dict(r) for r in db.execute("SELECT * FROM marine_calls WHERE asset_id = ? ORDER BY eta, id", (asset["id"],))]
    own = any(r["source"] != "typical" for r in rows)
    if rows and not own and min(r["eta"] for r in rows) < (start - timedelta(days=1)).isoformat():
        db.execute("DELETE FROM marine_calls WHERE asset_id = ? AND source = 'typical'", (asset["id"],))
        db.commit()
        rows = []
    if not rows:
        return typical_calls(int(asset["id"]), asset["terminal_type"] or "container", the_berths, start), False
    out = []
    for d in rows:
        try:
            d["eta"] = datetime.fromisoformat(d["eta"])
        except (TypeError, ValueError):
            continue
        out.append(d)
    return out, own


def clean_call(form: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
    def num(key: str, lo: float, hi: float) -> float | None:
        raw = form.get(key)
        if raw in (None, ""):
            return None
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return None
        return v if lo <= v <= hi else None

    ship = (form.get("ship") or "").strip()[:80]
    if not ship:
        return None, "Give the ship's name."
    loa, draught, moves = num("loa", 20, 500), num("draught", 1, 25), num("moves", 0, 30000)
    if loa is None or draught is None or moves is None:
        return None, f"{ship}: give the length (20 to 500 m), the draught (1 to 25 m) and what is to be worked."
    raw = (form.get("eta") or "").strip().replace(" ", "T")
    try:
        eta = datetime.fromisoformat(raw[:16])
    except ValueError:
        return None, f"{ship}: give when she arrives, as 2026-10-06 14:00."
    flag = (form.get("flag") or "").strip().upper()[:2]
    wish = num("wish", 1, 200)
    return {"ship": ship, "imo": (form.get("imo") or "").strip()[:10], "flag": flag if flag.isalpha() else "",
            "type": (form.get("type") or "Container").strip()[:40], "line": (form.get("line") or "").strip()[:60],
            "loa": loa, "beam": num("beam", 3, 80), "draught": draught, "dwt": num("dwt", 0, 500000), "moves": int(moves),
            "eta": eta.isoformat(timespec="minutes"),
            "window": int(str(form.get("window", "")).lower() in ("1", "on", "yes", "true", "y")),
            "wish": int(wish) if wish else None, "notes": (form.get("notes") or "").strip()[:200]}, ""


def insert_call(db, asset_id: int, call: dict[str, Any], source: str = "user") -> None:
    db.execute("INSERT INTO marine_calls (asset_id, ship, imo, flag, type, line, loa, beam, draught, dwt, moves, eta, window, wish,"
               " notes, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
               (asset_id, call["ship"], call["imo"], call["flag"], call["type"], call["line"], call["loa"], call["beam"],
                call["draught"], call["dwt"], call["moves"], call["eta"], call["window"], call["wish"], call["notes"], source))


def keep_typical(db, asset_id: int, typical: list[dict[str, Any]]) -> None:
    """Before the first change, the typical week becomes the person's to amend."""
    if db.execute("SELECT 1 FROM marine_calls WHERE asset_id = ?", (asset_id,)).fetchone():
        return
    for c in typical:
        insert_call(db, asset_id, {**c, "eta": c["eta"].isoformat(timespec="minutes")}, "typical")


def export_csv(the_calls: list[dict[str, Any]]) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(COLUMNS)
    for c in the_calls:
        w.writerow([c["eta"].strftime("%Y-%m-%d %H:%M") if k == "eta" else ("" if c.get(k) is None else c.get(k)) for k in COLUMNS])
    return out.getvalue()


def import_csv(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Calls from a CSV with the export's columns (the header names what each column is)."""
    reader = csv.DictReader(io.StringIO(text))
    good, bad = [], []
    aliases = {"name": "ship", "vessel": "ship", "length": "loa", "boxes": "moves", "teu": "moves", "arrival": "eta"}
    for i, row in enumerate(reader, start=2):
        row = {aliases.get((k or "").strip().lower(), (k or "").strip().lower()): v for k, v in row.items()}
        call, why = clean_call(row)
        if call:
            good.append(call)
        else:
            bad.append(f"Row {i}: {why}")
        if len(good) >= 2000:
            break
    return good, bad


# --- the plan ----------------------------------------------------------------------------------

def _fits(call: dict[str, Any], b: dict[str, Any]) -> str:
    """Why the berth (or two next to each other, taken together) will not take her, or "" when it will."""
    if call["loa"] + LENGTH_MARGIN > b["length"]:
        return f"too short ({b['length']:.0f} m for {call['loa']:.0f} m)"
    if call["draught"] * (1 + UKC) > b["depth"]:
        return f"too shallow ({b['depth']:.1f} m for {call['draught']:.1f} m draught)"
    uses = FITS_USE.get(call.get("type") or "Container", {"mixed", "container", "general_cargo", "multipurpose"})
    if b["use"] not in uses and b["use"] != "mixed":
        return f"set up for {dict(USES).get(b['use'], b['use']).lower()}"
    return ""


def _spots(the_berths: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Where a ship can lie: each berth, and each two berths next to each other along a continuous quay
    for a ship longer than one (she then holds both)."""
    out = [{**b, "ns": (b["n"],)} for b in the_berths]
    by_n = {b["n"]: b for b in the_berths}
    for b in the_berths:
        c = by_n.get(b["n"] + 1)
        if c is None or b["use"] != c["use"]:
            continue
        out.append({**b, "ns": (b["n"], c["n"]), "name": f"{b['name']} and {c['name']}", "length": b["length"] + c["length"],
                    "depth": min(b["depth"], c["depth"]), "cranes": b["cranes"] + c["cranes"],
                    "crane_kind": b["crane_kind"] if b["crane_kind"] == c["crane_kind"] else "MHC"})
    return out


def _hours(call: dict[str, Any], b: dict[str, Any]) -> float:
    cranes = max(1, min(b["cranes"] or 1, 1 + int(call["loa"] // 110))) if b["crane_kind"] != "ramp" else 1
    rate = RATE.get(b["crane_kind"], 18.0) * cranes
    return MOOR_HOURS + (call["moves"] or 0) / rate


def allocate(the_berths: list[dict[str, Any]], the_calls: list[dict[str, Any]], policy: str = "windows",
             start: datetime | None = None) -> dict[str, Any]:
    """A berth and a time for every call, by the rule chosen."""
    policy = policy if policy in POLICIES else "windows"
    start = start or min((c["eta"] for c in the_calls), default=datetime(2026, 1, 1))
    spots = _spots(the_berths)
    booked: dict[int, list[tuple[float, float]]] = {b["n"]: [] for b in the_berths}   # hours from start

    def earliest(ns: tuple[int, ...], eta: float, hours: float) -> float:
        """The first time from her arrival the berths are all free for as long as she needs them."""
        taken = sorted(iv for n in ns for iv in booked[n])
        t = eta
        for a, z in taken:
            if z <= t:
                continue
            if a >= t + hours:
                break
            t = max(t, z)
        return t
    left = [dict(c, _i=i, _eta=(c["eta"] - start).total_seconds() / 3600) for i, c in enumerate(the_calls)]
    placed: list[dict[str, Any]] = []
    unplaced: list[dict[str, Any]] = []

    def options(c: dict[str, Any]) -> list[tuple[float, int, float, dict[str, Any]]]:
        out = []
        for b in spots:
            if _fits(c, b):
                continue
            begin = earliest(b["ns"], c["_eta"], _hours(c, b))
            asked = 0 if c.get("wish") in b["ns"] else 1
            # One berth before two; then the berth asked for; then the least length to spare.
            out.append((begin + (2.0 if len(b["ns"]) > 1 else 0.0), asked, b["length"] - c["loa"], b, begin))
        return [o[:3] + (o[3], o[4]) for o in sorted(out, key=lambda o: (o[0], o[1], o[2]))]

    while left:
        if policy == "fcfs":
            pick = min(left, key=lambda c: (c["_eta"], c["_i"]))
        elif policy == "windows":
            pick = min(left, key=lambda c: (0 if c.get("window") else 1, c["_eta"], c["_i"]))
        else:
            best_begin = {c["_i"]: (options(c) or [(float("inf"), 0, 0, None, float("inf"))])[0][4] for c in left}
            first = min(best_begin.values())
            ready = [c for c in left if best_begin[c["_i"]] <= first + 1e-6]
            pick = min(ready, key=lambda c: (min((_hours(c, o[3]) for o in options(c)), default=1e9), c["_eta"]))
        left.remove(pick)
        opts = options(pick)
        if not opts:
            longest = max(the_berths, key=lambda b: b["length"])
            unplaced.append({**{k: v for k, v in pick.items() if not k.startswith("_")},
                             "why": f"No berth takes her: the longest, {longest['name']}, is {_fits(pick, longest) or 'busy'}."})
            continue
        _, _, _, b, begin = opts[0]
        hours = _hours(pick, b)
        for n in b["ns"]:
            booked[n].append((begin, begin + hours))
        wait = begin - pick["_eta"]
        reasons = [f"fits ({b['length']:.0f} m, {b['depth']:.1f} m deep)"]
        if len(b["ns"]) > 1:
            reasons.append("longer than one berth, so she holds two")
        if pick.get("wish") in b["ns"]:
            reasons.append("the berth asked for")
        if pick.get("window") and policy == "windows":
            reasons.append("contracted window")
        reasons.append("free when she arrived" if wait < 0.05 else f"first free, after {wait:.0f} h at anchor")
        placed.append({**{k: v for k, v in pick.items() if not k.startswith("_")}, "berth": b["ns"][0], "berths": list(b["ns"]),
                       "berth_name": b["name"],
                       "begin": start + timedelta(hours=begin), "end": start + timedelta(hours=begin + hours),
                       "begin_h": round(begin, 2), "end_h": round(begin + hours, 2), "eta_h": round(pick["_eta"], 2),
                       "wait": round(wait, 2), "hours": round(hours, 1), "why": ", ".join(reasons)})
    span = max([p["end_h"] for p in placed] + [24.0])
    horizon = max(span, 24.0 * 7)
    busy = {b["n"]: sum(p["hours"] for p in placed if b["n"] in p["berths"]) for b in the_berths}
    waits = [p["wait"] for p in placed]
    return {
        "policy": policy, "policy_name": POLICIES[policy][0], "start": start, "horizon": horizon,
        "placed": sorted(placed, key=lambda p: (p["begin"], p["berth"])), "unplaced": unplaced,
        "wait_total": round(sum(waits), 1), "wait_mean": round(sum(waits) / len(waits), 1) if waits else 0.0,
        "wait_max": round(max(waits), 1) if waits else 0.0, "waited": sum(1 for w in waits if w >= 1),
        "occupancy": {n: round(100 * h / horizon) for n, h in busy.items()},
        "occupancy_all": round(100 * sum(busy.values()) / (horizon * max(1, len(the_berths)))),
    }


def compare(the_berths: list[dict[str, Any]], the_calls: list[dict[str, Any]], start: datetime) -> dict[str, dict[str, Any]]:
    return {k: allocate(the_berths, the_calls, k, start) for k in POLICIES}
