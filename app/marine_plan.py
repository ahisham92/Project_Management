"""MarineTwin's sensors plan: what to buy for this berth, where each goes, what it costs over the
design life, and what it pays back.

* **What and where** — each kind of sensor has a rule (one per so many metres of quay, one per
  berth, so many for the quay) and the kinds of element it is fixed to. The plan counts them for
  this berth's length and spreads them evenly over the elements of the model they go on, so each
  has a place in 3D and a host element (its GlobalId) to install on.
* **Buying** — a product, its maker's page, where to buy or ask for a quote, and a price: a
  published price where one was found (October 2026), otherwise an indicative range. The logger
  cabinets, multiplexers, cable and routers they need come from ``marine_feed.kit``.
* **Over the design life** — the hardware and its installation, replacing each at the end of its
  life, the visits to keep it working, and the data.
* **What it pays back** — years added to the berth's life (the monitoring finds trouble while it
  is cheap to fix), the extreme events it gives warning of (from ``marine_risk``), and the share
  of the repairs it lets be done early (from ``marine_life``'s fix-as-you-go against doing
  nothing). Return on investment, payback year and net present value at the discount rate.
* **More sensors?** — the same with half, double or four times as many: coverage grows with
  diminishing returns while the cost grows in step, so the page shows where more stops paying.
* **Assumed data** — until real sensors are connected, every planned sensor tells a simulated
  story over the whole design life (``marine.simulate``), so year 4 or year 40 can be looked at.

Every price, life and rule is an input the person can change (``plan_*`` keys on the Inputs page).
"""

from __future__ import annotations

import math
import random
from datetime import date, timedelta
from typing import Any, Iterable

from . import marine, marine_feed, marine_life, marine_risk

# key: what it is, the product and links, the price used (USD) and its range, installation,
# life (years), a visit every so many months at so much each, the rule, the elements it goes on,
# the reading it gives (for the assumed data), and the events it gives warning of.
#   rule: ("per_m", metres) one per so many metres of quay; ("per_berth", n); ("fixed", n);
#         ("per_km", base, extra per km)
CATALOGUE: dict[str, dict[str, Any]] = {
    "strain": {
        "name": "Strain gauges on the piles", "group": "Structure",
        "product": "Vibrating-wire weldable strain gauge, Geokon 4000 (Encardio-Rite EDS-20V-AW priced)",
        "url": "https://www.geokon.com/4000", "buy": "https://shop.encardio.com/products/eds-20v-aw",
        "buy_note": "Encardio online shop $75; Geokon through Specto Technology on request",
        "price": 250, "low": 75, "high": 400, "install": 1200,
        "how": "Arc-weld the two end blocks to the cleaned pile above low water with the setting jig, fit the coil, weld a steel cover channel over it, run armoured cable up to a junction box. Two per pile, front and back face.",
        "life": 20, "visit_months": 12, "visit": 60, "rule": ("per_m", 25), "per_host": 2,
        "hosts": ("pile", "tie_rod", "combi_wall"), "reads": "strain", "events": ("strain",),
        "tells": "Load in the piles: overloads, a ship strike, a quake, a pile losing support.",
    },
    "corrosion": {
        "name": "Wall thickness monitors", "group": "Structure",
        "product": "Emerson Rosemount Permasense ET310 wireless ultrasonic thickness monitor",
        "url": "https://www.emerson.com/en-us/catalog/rosemount-sku-permasense-et310-corrosion-erosion-monitoring-system",
        "buy": "https://www.emerson.com/en-us/catalog/rosemount-sku-permasense-et310-corrosion-erosion-monitoring-system",
        "buy_note": "Request a quote from Emerson; no published price", "price": 5000, "low": 3000, "high": 8000, "install": 1500,
        "how": "Clamp the transducer on cleaned steel in the splash and tidal zone (no couplant), from a boat or a hanging stage at low tide; it reports by WirelessHART to a gateway on the quay.",
        "life": 9, "visit_months": 24, "visit": 150, "rule": ("per_m", 50),
        "hosts": ("pile", "sheet_pile", "combi_wall"), "reads": "corrosion", "events": ("corrosion",),
        "tells": "Steel left in the wall: low water corrosion found while there is time to fit protection.",
    },
    "tilt": {
        "name": "Tilt meters on the cope", "group": "Structure",
        "product": "Biaxial MEMS tiltmeter, Geokon 6350 (Encardio-Rite EAN-52M priced)",
        "url": "https://www.geokon.com/6350", "buy": "https://shop.encardio.com/products/ean-52m",
        "buy_note": "Encardio online shop $700; Geokon through Specto or Durham Geo on request",
        "price": 1200, "low": 700, "high": 2000, "install": 400,
        "how": "Bolt the bracket to the capping beam with stainless anchors, level the sensor, cable to the logger.",
        "life": 15, "visit_months": 12, "visit": 60, "rule": ("per_m", 50),
        "hosts": ("beam", "slab", "sheet_pile", "combi_wall"), "reads": "tilt", "events": ("tilt",),
        "tells": "The wall leaning out: scour at the toe, ground settling behind, a tie rod failing.",
    },
    "crack_width": {
        "name": "Crack and joint meters", "group": "Structure",
        "product": "Vibrating-wire crackmeter, Geokon 4420",
        "url": "https://geokon.com/4420", "buy": "https://www.spectotechnology.com", "buy_note": "Quote from Specto Technology or Durham Geo",
        "price": 600, "low": 300, "high": 900, "install": 300,
        "how": "Grout the two anchors either side of the deck joint or crack, set it mid-range, fit the cover.",
        "life": 20, "visit_months": 12, "visit": 40, "rule": ("per_m", 50),
        "hosts": ("slab", "beam"), "reads": "crack_width", "events": (),
        "tells": "Cracks in the deck opening: overload, settlement, fire damage.",
    },
    "half_cell": {
        "name": "Embedded reference electrodes", "group": "Concrete",
        "product": "FORCE Technology ERE 20 MnO₂ reference electrode",
        "url": "https://www.pcte.com.au/product/ere-20-reference-electrode", "buy": "https://www.pcte.com.au/product/ere-20-reference-electrode",
        "buy_note": "PCTE (distributor), enquiry; no published price", "price": 400, "low": 200, "high": 600, "install": 500,
        "how": "In an existing deck: core to the rebar, set the electrode beside the bar (not touching), reinstate with matching mortar; in new concrete, tie it in before the pour.",
        "life": 30, "visit_months": 24, "visit": 80, "rule": ("per_m", 100),
        "hosts": ("beam", "slab"), "reads": "half_cell", "events": ("half_cell",),
        "tells": "Whether the rebar has started to corrode, years before the concrete spalls.",
    },
    "chloride": {
        "name": "Corrosion probes in the concrete", "group": "Concrete",
        "product": "FORCE Technology CorroWatch multi-depth probe (Sensortec Anode-Ladder equivalent)",
        "url": "https://www.pcte.com.au/corrowatch-embeddable-corrosion-front-probes",
        "buy": "https://www.pcte.com.au/corrowatch-embeddable-corrosion-front-probes", "buy_note": "PCTE, enquiry; no published price",
        "price": 1500, "low": 500, "high": 2500, "install": 800,
        "how": "Tie to two rebars in the cover zone so the anodes sit at staggered depths; in an existing deck, a cored pocket reinstated with mortar.",
        "life": 30, "visit_months": 24, "visit": 80, "rule": ("per_m", 100),
        "hosts": ("beam", "slab"), "reads": "chloride", "events": ("corrosion",),
        "tells": "How fast chlorides are reaching the rebar, depth by depth.",
    },
    "settlement": {
        "name": "Survey prisms on the cope", "group": "Ground",
        "product": "Leica GPR112 monitoring prism, read by a Leica Nova TM60 (below)",
        "url": "https://leica-geosystems.com/en-ae/products/total-stations/robotic-total-stations/leica-nova-tm60",
        "buy": "https://survey.crkennedy.com.au/products/LG822427/leica-nova-tm60-i-0-5--r1000-total-station", "buy_note": "Leica dealer, quote",
        "price": 250, "low": 100, "high": 400, "install": 150,
        "how": "Bolt each prism to the capping beam or the crane rail beam, facing the total station.",
        "life": 15, "visit_months": 3, "visit": 10, "rule": ("per_m", 25),
        "hosts": ("beam", "slab", "crane_rail"), "reads": "displacement", "events": ("settlement",),
        "tells": "The quay moving or settling, to the millimetre, every hour.",
    },
    "piezometer": {
        "name": "Piezometers behind the wall", "group": "Ground",
        "product": "Vibrating-wire piezometer, Geokon 4500 (Encardio-Rite EPP-30V priced)",
        "url": "https://www.spectotechnology.com/product/geokon-standard-piezometers-vw-4500/", "buy": "https://shop.encardio.com/products/epp-30v",
        "buy_note": "Encardio online shop $350; Geokon on request", "price": 600, "low": 350, "high": 900, "install": 2500,
        "how": "Grout in a borehole behind the wall (cement-bentonite), filter saturated first; cable to the logger.",
        "life": 25, "visit_months": 24, "visit": 40, "rule": ("per_m", 200),
        "hosts": ("slab", "tie_rod", "sheet_pile"), "reads": None, "events": ("piezometer",),
        "tells": "Water pressure in the fill: the warning of liquefaction or a blocked drain behind the wall.",
    },
    "mooring_load": {
        "name": "Load-monitored mooring hooks", "group": "Furniture",
        "product": "Trelleborg SmartHook quick-release hooks with load pins",
        "url": "https://www.nauticexpo.com/prod/trelleborg-marine-and-infrastructure/product-22887-519992.html",
        "buy": "https://www.nauticexpo.com/prod/trelleborg-marine-and-infrastructure/product-22887-519992.html", "buy_note": "Quote from Trelleborg",
        "price": 30000, "low": 15000, "high": 60000, "install": 6000,
        "how": "Bolt the hook assembly to the bollard foundation plate; load pins cabled to the jetty panel and the shore display.",
        "life": 20, "visit_months": 12, "visit": 400, "rule": ("per_berth", 2),
        "hosts": ("bollard",), "reads": "bollard_load", "events": ("fender_load",),
        "tells": "Line loads as ships surge in a storm: lines eased before they part or a bollard is overloaded.",
    },
    "berthing_aid": {
        "name": "Berthing aid system", "group": "Furniture",
        "product": "Trelleborg SmartDock Laser",
        "url": "https://www.trelleborg.com/en/marine-and-infrastructure/products-solutions-and-services/marine/docking-and-mooring/docking-aid-system/smart-dock-laser",
        "buy": "https://www.trelleborg.com/en/marine-and-infrastructure/products-solutions-and-services/marine/docking-and-mooring/docking-aid-system/smart-dock-laser",
        "buy_note": "Quote from Trelleborg", "price": 90000, "low": 50000, "high": 200000, "install": 15000,
        "how": "Two laser rangefinders on pedestals at the berth face, a display board for the pilot, a radio link to the pilot's unit.",
        "life": 15, "visit_months": 1, "visit": 50, "rule": ("per_berth", 1),
        "hosts": ("fender", "slab"), "reads": None, "events": ("berthing_aid",),
        "tells": "Approach speed and angle shown to the pilot: hard berthings avoided.",
    },
    "accelerometer": {
        "name": "Strong-motion accelerometers", "group": "Hazards",
        "product": "Syscom MR3000C (or Kinemetrics Obsidian, GeoSIG GMSplus)",
        "url": "https://www.syscom.ch/MR3000C", "buy": "https://www.geosig.com/GMSplus---GMSplus6-id12557.aspx", "buy_note": "Quote from the maker",
        "price": 8000, "low": 3300, "high": 15000, "install": 1500,
        "how": "Anchor-bolt to a stiff concrete plinth on the deck or at a pile cap, level it, GNSS timing and a 4G link.",
        "life": 15, "visit_months": 12, "visit": 150, "rule": ("per_km", 2, 1),
        "hosts": ("slab", "beam", "pile"), "reads": None, "events": ("accelerometer",),
        "tells": "How hard the quay was shaken, minutes after a quake: which bays to inspect first.",
    },
    "tide_gauge": {
        "name": "Radar tide gauge", "group": "Hazards",
        "product": "VEGA VEGAPULS C 21 radar level sensor (or OTT RLS)",
        "url": "https://vega.com/en-sg/products/product-catalog/level/radar/vegapuls-c-21", "buy": "https://uk.rs-online.com/web/p/level-sensors/2067074",
        "buy_note": "RS Components £725 ex VAT (about $970)", "price": 970, "low": 970, "high": 3500, "install": 800,
        "how": "On a stainless arm off the quay edge, looking straight down over open water clear of the fenders.",
        "life": 15, "visit_months": 12, "visit": 60, "rule": ("fixed", 1),
        "hosts": ("fender", "slab"), "reads": None, "events": ("tide_gauge",),
        "tells": "The sea level against the cope: storm surges and tsunamis seen coming.",
    },
    "weather_station": {
        "name": "Weather station", "group": "Hazards",
        "product": "Gill MaxiMet Marine GMX260 (or Vaisala WXT536)",
        "url": "https://www.fondriest.com/vaisala-wxt536-multi-parameter-weather-sensor.htm", "buy": "https://panbo.com/gill-maximet-marine-gmx260/",
        "buy_note": "Gill list price £1,364 (about $1,830); Vaisala WXT536 about $4,300", "price": 1830, "low": 1830, "high": 4300, "install": 600,
        "how": "On a mast 3 to 10 m above the deck, clear of the cranes' wake; cable to the logger.",
        "life": 10, "visit_months": 12, "visit": 80, "rule": ("per_km", 1, 0.5),
        "hosts": ("slab", "beam"), "reads": None, "events": ("weather_station",),
        "tells": "Wind and gusts at the cranes: stow before the gust, not after.",
    },
    "wave_buoy": {
        "name": "Wave buoy", "group": "Hazards",
        "product": "Sofar Spotter with Smart Mooring",
        "url": "https://www.sofarocean.com/products/spotter/solutions/surface", "buy": "https://spotter-configurator.sofarocean.com/",
        "buy_note": "Sofar, starting at $6,600", "price": 6600, "low": 6600, "high": 12000, "install": 3000,
        "how": "Moored on a single slack line off the berth or in the approach channel; solar powered, reports by cellular.",
        "life": 5, "visit_months": 4, "visit": 300, "rule": ("fixed", 1),
        "hosts": (), "reads": None, "events": ("wave_buoy",),
        "tells": "Waves at the berth: berthing windows and storms seen coming.",
    },
    "thermal_camera": {
        "name": "Thermal cameras", "group": "Hazards",
        "product": "Teledyne FLIR A400 (A400-24 kit)",
        "url": "https://www.globaltestsupply.com/product/flir-a400-series-thermal-imager-91901-0401",
        "buy": "https://www.globaltestsupply.com/product/flir-a400-series-thermal-imager-91901-0401",
        "buy_note": "Global Test Supply $11,050", "price": 11050, "low": 5000, "high": 15000, "install": 1500,
        "how": "In an IP66 housing on a mast over the apron and the stacks; temperature alarms in the port's video system.",
        "life": 10, "visit_months": 3, "visit": 60, "rule": ("per_m", 150),
        "hosts": ("slab", "beam"), "reads": None, "events": ("thermal_camera",),
        "tells": "A fire caught while it is small, on the apron or on a ship alongside.",
    },
}

# What the plan's sensors need to work: one cabinet per 64 logger channels, a total station for the
# prisms, a gateway for the wireless thickness monitors. Read by the logger: everything but these.
OWN_LINK = {"corrosion", "settlement", "berthing_aid", "wave_buoy", "thermal_camera", "mooring_load", "accelerometer"}
SUPPORT = {
    "logger": {"name": "Logger cabinet", "product": "Campbell Scientific CR1000X + AM16/32B multiplexer + AVW200 interface, Teltonika RUT241 router, solar kit in an IP66 enclosure",
               "url": "https://www.campbellsci.com/cr1000x",
               "buy": "https://www.radwell.com/Buy/CAMPBELL%20SCIENTIFIC%20INC/CAMPBELL%20SCIENTIFIC%20INC/CR1000X",
               "buy_note": "Radwell CR1000X $4,354; router RS £149; enclosure and solar about $445",
               "price": 9500, "low": 7000, "high": 13000, "install": 2500, "life": 15, "visit_months": 6, "visit": 120,
               "how": "On a galvanised post above the splash zone: enclosure with desiccant, solar panel facing south at 10 to 15°, earth and surge protection."},
    "total_station": {"name": "Robotic total station", "product": "Leica Nova TM60 with GeoMoS monitoring software",
                      "url": "https://leica-geosystems.com/en-ae/products/total-stations/robotic-total-stations/leica-nova-tm60",
                      "buy": "https://survey.crkennedy.com.au/products/LG822427/leica-nova-tm60-i-0-5--r1000-total-station",
                      "buy_note": "Quote; a used TS16 is about $26,000 to $30,000", "price": 55000, "low": 26000, "high": 70000,
                      "install": 6000, "life": 10, "visit_months": 12, "visit": 1500,
                      "how": "In a shelter on a stable pillar off the quay, seeing every prism; reports over 4G."},
    "gateway": {"name": "Wireless gateway", "product": "Emerson WirelessHART gateway for the thickness monitors",
                "url": "https://www.emerson.com/en-us/catalog/rosemount-sku-permasense-et310-corrosion-erosion-monitoring-system",
                "buy": "https://www.emerson.com/en-us/catalog/rosemount-sku-permasense-et310-corrosion-erosion-monitoring-system",
                "buy_note": "Quote from Emerson", "price": 4000, "low": 3000, "high": 5000, "install": 800, "life": 12,
                "visit_months": 12, "visit": 100, "how": "On a mast within radio range of the monitors, powered from the cabinet."},
}
CABLE_PER_SENSOR = 40 * 12       # m of armoured cable in conduit at about $12 a metre
DATA_PER_LINK = 240              # USD a year: a data SIM per cabinet or link
PLATFORM = 24000                 # USD a year: monitoring software, hosting and part of an engineer looking at it
DENSITIES = (0.5, 1.0, 2.0, 4.0)
STATES = {"ok": "good", "due": "warning", "fault": "critical", "replace": "critical"}


def plan_inputs() -> list[dict[str, Any]]:
    """The plan's figures for the Inputs page."""
    out = [
        {"key": "plan_life_ext", "label": "Years the monitoring adds to the berth's life", "unit": "years", "default": 10,
         "source": "Trouble found early is fixed while it is small, so the berth lasts longer than its design life. 10 years is a "
                   "cautious figure; studies of monitored bridges and wharves report 10 to 25."},
        {"key": "plan_busy", "label": "How busy the berth is, on average", "unit": "% of full working", "default": 65,
         "source": "Berth occupancy; 60 to 70% is usual for a container berth."},
        {"key": "plan_margin", "label": "Profit on each container handled", "unit": "% of its value", "default": 35,
         "source": "The terminal's operating margin: 30 to 45% (EBITDA) for listed operators such as DP World and ICTSI. "
                   "The extra years are counted at this share of the containers' value, as the terminal keeps paying its costs."},
        {"key": "plan_repair_share", "label": "How much less repairs cost when found early", "unit": "%", "default": 25,
         "source": "Found by the sensors, a defect is patched rather than replaced: a quarter off the Lifecycle's 'fix as you go' "
                   "repair bill is a cautious figure (concrete repair studies report 20 to 50%)."},
        {"key": "plan_density", "label": "Sensors, against the plan", "unit": "× the plan", "default": 1,
         "source": "1 is the plan as laid out; 2 doubles every count."},
        {"key": "plan_platform", "label": "Software, hosting and a monitoring engineer", "unit": "USD a year", "default": PLATFORM,
         "source": "Indicative: a monitoring software licence and a share of an engineer's time."},
    ]
    for key, c in {**CATALOGUE, **SUPPORT}.items():
        out += [
            {"key": f"plan_{key}_price", "sub": c["name"], "label": "Price each", "unit": "USD", "default": c["price"],
             "source": f"{c['product']}. {c['buy_note']}. Range ${c['low']:,} to ${c['high']:,}."},
            {"key": f"plan_{key}_install", "sub": c["name"], "label": "Installing each", "unit": "USD", "default": c["install"],
             "source": c["how"]},
            {"key": f"plan_{key}_life", "sub": c["name"], "label": "Life", "unit": "years", "default": c["life"],
             "source": "The maker's figure where given; then replaced."},
        ]
    return out


def _num(given: dict[str, Any] | None, key: str, default: float) -> float:
    raw = (given or {}).get(key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    return value if math.isfinite(value) and value >= 0 else float(default)


def spec(key: str, given: dict[str, Any] | None = None) -> dict[str, Any]:
    c = dict(CATALOGUE.get(key) or SUPPORT[key])
    for f in ("price", "install", "life"):
        c[f] = _num(given, f"plan_{key}_{f}", c[f])
    c["life"] = max(1.0, c["life"])
    return c


def _count(rule: tuple, length: float, berths: int, density: float) -> int:
    kind = rule[0]
    if kind == "per_m":
        n = length / rule[1]
    elif kind == "per_berth":
        n = berths * rule[1]
    elif kind == "per_km":
        n = rule[1] + rule[2] * length / 1000
    else:
        return int(rule[1])            # one tide gauge, one buoy: more of them adds nothing
    return max(1, math.ceil(n * density - 1e-9))


def _spread(hosts: list[dict[str, Any]], n: int, seed: str) -> list[dict[str, Any]]:
    """``n`` of ``hosts`` spread as evenly as their positions allow (farthest point first)."""
    if not hosts or n <= 0:
        return []
    if n >= len(hosts):
        return [hosts[i % len(hosts)] for i in range(n)]
    rng = random.Random(seed)
    pts = [(h.get("x") or 0.0, h.get("y") or 0.0) for h in hosts]
    first = rng.randrange(len(hosts))
    chosen = [first]
    near = [math.dist(pts[first], p) for p in pts]
    while len(chosen) < n:
        k = max(range(len(pts)), key=lambda i: near[i])
        chosen.append(k)
        for i, p in enumerate(pts):
            d = math.dist(pts[k], p)
            if d < near[i]:
                near[i] = d
    return [hosts[i] for i in chosen]


def layout(asset: Any, elements: Iterable[Any], given: dict[str, Any] | None = None, density: float | None = None) -> dict[str, Any]:
    """The plan for this berth: each sensor with its host element and place, and the counts."""
    els = [dict(e) for e in elements]
    length = marine_risk.berth_length(els)
    berths = max(1, round(length / 300))
    density = _num(given, "plan_density", 1) if density is None else density
    density = min(max(density, 0.1), 10)
    sensors: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for key, c in CATALOGUE.items():
        n = _count(c["rule"], length, berths, density)
        per_host = c.get("per_host", 1)
        hosts = [e for e in els if e["kind"] in c["hosts"]] or ([e for e in els] if c["hosts"] else [])
        placed = _spread(hosts, math.ceil(n / per_host), f"{asset['id']}:{key}") if hosts else []
        tag = key[:2].upper()
        counts[key] = n
        for i in range(n):
            h = placed[(i // per_host) % len(placed)] if placed else None
            sensors.append({
                "id": f"{key}-{i + 1}", "key": key, "tag": f"{tag}{i + 1:03d}", "name": c["name"],
                "host": h["name"] if h else "", "ref": (h.get("model_ref") or h["name"]) if h else "",
                "host_kind": h["kind"] if h else "", "x": h.get("x") if h else None, "y": h.get("y") if h else None,
                "z": h.get("z") if h else None, "face": ("front", "back")[i % 2] if per_host == 2 else "",
                "reads": c["reads"],
            })
    channels = sum(n for k, n in counts.items() if k not in OWN_LINK)
    support = {"logger": max(1, math.ceil(channels / marine_feed.CHANNELS_PER_LOGGER)) if channels else 0,
               "total_station": max(1, math.ceil(length / 1500)) if counts.get("settlement") else 0,
               "gateway": max(1, math.ceil(counts.get("corrosion", 0) / 30)) if counts.get("corrosion") else 0}
    return {"sensors": sensors, "counts": counts, "support": support, "channels": channels, "length": round(length),
            "berths": berths, "density": density}


def costs(lay: dict[str, Any], given: dict[str, Any] | None = None, years: int = 50) -> dict[str, Any]:
    """What the plan costs: buying and installing, then year by year (replacements, visits, data)."""
    rate = _num(given, "discount_rate", 8) / 100
    lines = []
    for key, n in [*lay["counts"].items(), *lay["support"].items()]:
        if not n:
            continue
        c = spec(key, given)
        buy = n * c["price"]
        fit = n * (c["install"] + (CABLE_PER_SENSOR if key in CATALOGUE and key not in OWN_LINK else 0))
        visits_a_year = 12 / c["visit_months"] if c["visit_months"] else 0
        # Visits are per site, not per sensor, beyond a few: a technician checks a dozen in a visit.
        upkeep = c["visit"] * visits_a_year * (n if n <= 4 else 4 + (n - 4) / 4)
        renewals = int((years - 1e-9) // c["life"])
        lines.append({"key": key, "name": c["name"], "product": c["product"], "url": c["url"], "buy": c["buy"],
                      "buy_note": c["buy_note"], "how": c["how"], "qty": n, "price": c["price"], "low": c["low"], "high": c["high"],
                      "buy_total": buy, "install_total": fit, "life": c["life"], "renewals": renewals,
                      "upkeep": round(upkeep), "visit_months": c["visit_months"], "group": c.get("group", "Cabinets and links"),
                      "tells": c.get("tells", "")})
    links = lay["support"]["logger"] + lay["support"]["total_station"] + lay["support"]["gateway"] + lay["counts"].get("wave_buoy", 0)
    platform = _num(given, "plan_platform", PLATFORM)
    data = links * DATA_PER_LINK + platform
    capex = sum(x["buy_total"] + x["install_total"] for x in lines)
    yearly = []
    for y in range(years + 1):
        spend = capex if y == 0 else 0.0
        if y:
            spend += sum(x["upkeep"] for x in lines) + data
            spend += sum(x["buy_total"] + 0.5 * x["install_total"] for x in lines if y % max(1, round(x["life"])) == 0 and y < years)
        yearly.append({"year": y, "spend": round(spend), "pv": spend / (1 + rate) ** y})
    total = sum(r["spend"] for r in yearly)
    return {"lines": lines, "capex": round(capex), "hardware": round(sum(x["buy_total"] for x in lines)),
            "install": round(sum(x["install_total"] for x in lines)), "upkeep": round(sum(x["upkeep"] for x in lines)),
            "data": round(data), "yearly": yearly, "total": round(total), "pv": round(sum(r["pv"] for r in yearly)),
            "renewals": round(sum(r["spend"] for r in yearly[1:]) - years * (sum(x["upkeep"] for x in lines) + data)),
            "rate": rate}


def benefits(asset: Any, elements: list[dict[str, Any]], lay: dict[str, Any], rates: dict[str, float],
             given: dict[str, Any] | None = None, life: int = 50, repair_saving: float | None = None) -> dict[str, Any]:
    """What the plan pays back over the design life, and how it is made up."""
    rate = _num(given, "discount_rate", 8) / 100
    have = {e for k, n in lay["counts"].items() if n for e in CATALOGUE[k]["events"]}
    cover = 1 - math.exp(-1.6 * lay["density"])
    full = 1 - math.exp(-1.6)
    reach = cover / full                                    # 1 at the plan, less with fewer, a little more with more
    events = []
    for e in marine_risk.catalogue(asset, elements, rates, given, life):
        if not e["on"] or not e["sensors"]:
            continue
        share = sum(1 for s in e["sensors"] if s in have) / len(e["sensors"])
        if share:
            events.append({"key": e["key"], "name": e["name"], "share": share,
                           "saving": e["expected_saving"] * share * min(reach, 1.25)})
    event_saving = sum(x["saving"] for x in events)
    busy = _num(given, "plan_busy", 65) / 100
    ext = _num(given, "plan_life_ext", 10) * min(reach, 1.25)
    per_year = rates["moves_per_day"] * 365.25 * busy
    extra_containers = per_year * ext
    extra_income = extra_containers * rates["value_per_move"]
    extra_value = extra_income * _num(given, "plan_margin", 35) / 100
    repair_share = _num(given, "plan_repair_share", 25) / 100
    repairs = max(0.0, repair_saving or 0.0) * repair_share * min(reach, 1.25)
    # Present values: event and repair savings spread evenly over the life, the extra years after it.
    annuity = sum(1 / (1 + rate) ** y for y in range(1, life + 1))
    later = sum(1 / (1 + rate) ** y for y in range(life + 1, life + 1 + int(math.ceil(ext))))
    pv = (event_saving + repairs) / life * annuity + extra_value / max(ext, 1e-9) * later if ext else (event_saving + repairs) / life * annuity
    return {"events": sorted(events, key=lambda x: -x["saving"]), "event_saving": round(event_saving),
            "life_ext": ext, "extra_containers": round(extra_containers), "extra_value": round(extra_value),
            "extra_income": round(extra_income), "margin": _num(given, "plan_margin", 35),
            "repairs": round(repairs), "total": round(event_saving + extra_value + repairs), "pv": round(pv),
            "per_year_in_life": (event_saving + repairs) / life}


def assess(asset: Any, elements: Iterable[Any], rates: dict[str, float], given: dict[str, Any] | None = None,
           life: int = 50, repair_saving: float | None = None) -> dict[str, Any]:
    """The plan, what it costs, what it pays back, and the same at other densities."""
    els = [dict(e) for e in elements]
    lay = layout(asset, els, given)
    cost = costs(lay, given, life)
    gain = benefits(asset, els, lay, rates, given, life, repair_saving)
    # Payback: the year the savings made so far pass what has been spent.
    spent = saved = 0.0
    payback = None
    for row in cost["yearly"]:
        spent += row["spend"]
        saved += gain["per_year_in_life"] if row["year"] else 0
        if payback is None and row["year"] and saved >= spent:
            payback = row["year"]
    options = []
    for d in sorted({*DENSITIES, lay["density"]}):
        other = layout(asset, els, given, d)
        c = costs(other, given, life)
        b = benefits(asset, els, other, rates, given, life, repair_saving)
        options.append({"density": d, "sensors": len(other["sensors"]), "cost": c["total"], "benefit": b["total"],
                        "roi": (b["total"] - c["total"]) / c["total"] if c["total"] else 0, "npv": b["pv"] - c["pv"]})
    for prev, nxt in zip(options, options[1:]):
        extra = nxt["cost"] - prev["cost"]
        nxt["marginal"] = (nxt["benefit"] - prev["benefit"]) / extra if extra > 0 else None
    best = max(options, key=lambda o: o["npv"])
    return {"layout": lay, "cost": cost, "benefit": gain, "roi": (gain["total"] - cost["total"]) / cost["total"] if cost["total"] else 0,
            "npv": gain["pv"] - cost["pv"], "payback": payback, "options": options, "best": best}


# --- the sensors over the years: assumed readings and the maintenance check -------------------

def _sim_id(sensor_id: str) -> int:
    return sum((i + 1) * ord(ch) for i, ch in enumerate(sensor_id)) % 1_000_000


def series(asset: Any, sensor: dict[str, Any], allowance: float | None = None, life: int = 50) -> list[tuple[float, float]]:
    """A planned sensor's assumed readings, month by month over the design life: (year, value)."""
    if not sensor.get("reads"):
        return []
    start = date(2000, 1, 1)
    fake_asset = {"commissioned": start.isoformat(), "design_life": life}
    fake = {"id": _sim_id(sensor["id"]), "kind": sensor["reads"], "alert": None, "alarm": None}
    until = start + timedelta(days=round(365.25 * life))
    rows = marine.simulate(fake, None, fake_asset, allowance, until=until, history_years=life + 1, step_days=30)
    return [(round((date.fromisoformat(at) - start).days / 365.25, 3), v) for at, v in rows]


def reading_at(points: list[tuple[float, float]], year: float) -> float | None:
    before = [v for t, v in points if t <= year]
    return before[-1] if before else None


def state_of(kind: str | None, value: float | None) -> str:
    if kind is None or value is None:
        return "neutral"
    spec_ = marine.SENSOR_KINDS.get(kind, {})
    alert, alarm = spec_.get("alert"), spec_.get("alarm")
    if kind == "corrosion":
        alert, alarm = 2.0, 3.5
    if kind in ("bollard_load",):
        alert, alarm = 120.0, 150.0
    if alert is None or alarm is None:
        return "good"
    if spec_.get("lower_worse"):
        return "critical" if value <= alarm else "warning" if value <= alert else "good"
    v = abs(value) if spec_.get("absolute") else value
    return "critical" if v >= alarm else "warning" if v >= alert else "good"


def upkeep(sensor: dict[str, Any], year: float, given: dict[str, Any] | None = None) -> dict[str, str]:
    """The maintenance check for one sensor in a year of service: fine, a visit due, a fault, or
    time to replace it. Simulated, the same every time for the same sensor and year."""
    c = spec(sensor["key"], given)
    age = year % c["life"]
    rng = random.Random(f"{sensor['id']}:{int(year)}")
    if c["life"] - age < 1 and year >= 1:
        return {"status": "replace", "note": f"End of its {c['life']:.0f}-year life: replace it this year."}
    if year >= 1 and rng.random() < 0.03:
        return {"status": "fault", "note": rng.choice(["Silent for three days: check the cable and the junction box.",
                                                       "Readings jumping: a loose connection or water in the gland.",
                                                       "Reading off the scale: the gauge may have failed."])}
    months = c["visit_months"]
    # The older it is, the likelier it is drifting or dirty enough to need its visit brought forward.
    if months and year >= 1 and rng.random() < 0.04 + 0.08 * age / c["life"]:
        return {"status": "due", "note": f"Visit due (routine every {months} months): drifting or dirty, clean, check and calibrate."}
    return {"status": "ok", "note": "Working, nothing due."}


def year_view(asset: Any, lay: dict[str, Any], year: float, allowance: float | None = None, given: dict[str, Any] | None = None,
              life: int = 50) -> list[dict[str, Any]]:
    """Every planned sensor in a year: its assumed reading, its state, and its maintenance check."""
    out = []
    for s in lay["sensors"]:
        pts = series(asset, s, allowance, life) if s["reads"] else []
        value = reading_at(pts, year)
        check = upkeep(s, year, given)
        spec_ = marine.SENSOR_KINDS.get(s["reads"] or "", {})
        out.append({**s, "value": value, "unit": spec_.get("unit", ""), "reading_state": state_of(s["reads"], value),
                    "check": check["status"], "check_note": check["note"], "state": STATES[check["status"]]
                    if check["status"] != "ok" else state_of(s["reads"], value) if s["reads"] else "good"})
    return out


# --- the sensors on their own, for Revit or any viewer ------------------------------------------

def export_csv(lay: dict[str, Any], given: dict[str, Any] | None = None) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["tag", "sensor", "product", "host_element", "host_ref", "host_kind", "face", "x", "y", "z", "install", "life_years"])
    for s in lay["sensors"]:
        c = spec(s["key"], given)
        w.writerow([s["tag"], s["name"], c["product"], s["host"], s["ref"], s["host_kind"], s["face"],
                    "" if s["x"] is None else round(s["x"], 3), "" if s["y"] is None else round(s["y"], 3),
                    "" if s["z"] is None else round(s["z"], 3), c["how"], c["life"]])
    return buf.getvalue()


def _guid(text: str) -> str:
    """A stable IFC GlobalId (22 characters of IFC's base 64) from any text."""
    import hashlib
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
    n = int.from_bytes(hashlib.md5(text.encode()).digest(), "big")
    out = chars[(n >> 126) & 3]
    for i in range(21):
        out += chars[(n >> (120 - 6 * i)) & 63]
    return out


def _s(text: str) -> str:
    return "'" + str(text).replace("\\", "\\\\").replace("'", "''").encode("ascii", "replace").decode() + "'"


def export_ifc(asset: Any, lay: dict[str, Any], given: dict[str, Any] | None = None) -> str:
    """An IFC4 file with only the sensors, each an IfcSensor at its host element's position with a
    small box to see it by and an MT_Sensor property set (tag, kind, product, host, install)."""
    lines: list[str] = []
    n = 0

    def add(text: str) -> int:
        nonlocal n
        n += 1
        lines.append(f"#{n}={text};")
        return n

    owner = add("IFCPERSON($,'MarineTwin',$,$,$,$,$,$)")
    org = add("IFCORGANIZATION($,'AHM',$,$,$)")
    po = add(f"IFCPERSONANDORGANIZATION(#{owner},#{org},$)")
    app = add(f"IFCAPPLICATION(#{org},'1','MarineTwin','MarineTwin')")
    hist = add(f"IFCOWNERHISTORY(#{po},#{app},$,.ADDED.,$,$,$,0)")
    origin = add("IFCCARTESIANPOINT((0.,0.,0.))")
    zdir = add("IFCDIRECTION((0.,0.,1.))")
    xdir = add("IFCDIRECTION((1.,0.,0.))")
    world = add(f"IFCAXIS2PLACEMENT3D(#{origin},#{zdir},#{xdir})")
    ctx = add(f"IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#{world},$)")
    body = add(f"IFCGEOMETRICREPRESENTATIONSUBCONTEXT('Body','Model',*,*,*,*,#{ctx},$,.MODEL_VIEW.,$)")
    metre = add("IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.)")
    units = add(f"IFCUNITASSIGNMENT((#{metre}))")
    project = add(f"IFCPROJECT({_s(_guid('project' + str(asset['id'])))},#{hist},{_s(asset['name'] + ' sensors')},$,$,$,$,(#{ctx}),#{units})")
    site_place = add(f"IFCLOCALPLACEMENT($,#{world})")
    site = add(f"IFCSITE({_s(_guid('site' + str(asset['id'])))},#{hist},'Site',$,$,#{site_place},$,$,.ELEMENT.,$,$,$,$,$)")
    add(f"IFCRELAGGREGATES({_s(_guid('agg' + str(asset['id'])))},#{hist},$,$,#{project},(#{site}))")
    # One small box, shared by every sensor: 0.4 m square, 0.3 m high.
    profile = add("IFCRECTANGLEPROFILEDEF(.AREA.,$,$,0.4,0.4)")
    solid = add(f"IFCEXTRUDEDAREASOLID(#{profile},#{world},#{zdir},0.3)")
    rep = add(f"IFCSHAPEREPRESENTATION(#{body},'Body','SweptSolid',(#{solid}))")
    shape = add(f"IFCPRODUCTDEFINITIONSHAPE($,$,(#{rep}))")
    placed = []
    for s in lay["sensors"]:
        if s["x"] is None:
            continue
        c = spec(s["key"], given)
        pt = add(f"IFCCARTESIANPOINT(({float(s['x']):.3f},{float(s['y']):.3f},{float(s['z'] or 0):.3f}))")
        axes = add(f"IFCAXIS2PLACEMENT3D(#{pt},#{zdir},#{xdir})")
        place = add(f"IFCLOCALPLACEMENT(#{site_place},#{axes})")
        sensor = add(f"IFCSENSOR({_s(_guid(str(asset['id']) + s['id']))},#{hist},{_s(s['tag'])},{_s(s['name'])},$,#{place},#{shape},{_s(s['tag'])},.NOTDEFINED.)")
        props = [add(f"IFCPROPERTYSINGLEVALUE({_s(k)},$,IFCLABEL({_s(v)}),$)")
                 for k, v in (("Tag", s["tag"]), ("Kind", s["key"]), ("Product", c["product"]), ("HostElement", s["host"]),
                              ("HostRef", s["ref"]), ("Face", s["face"]), ("Install", c["how"]))]
        pset = add(f"IFCPROPERTYSET({_s(_guid('pset' + str(asset['id']) + s['id']))},#{hist},'MT_Sensor',$,({','.join(f'#{p}' for p in props)}))")
        add(f"IFCRELDEFINESBYPROPERTIES({_s(_guid('rel' + str(asset['id']) + s['id']))},#{hist},$,$,(#{sensor}),#{pset})")
        placed.append(sensor)
    if placed:
        add(f"IFCRELCONTAINEDINSPATIALSTRUCTURE({_s(_guid('contain' + str(asset['id'])))},#{hist},$,$,({','.join(f'#{p}' for p in placed)}),#{site})")
    head = ("ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('ViewDefinition [ReferenceView]'),'2;1');\n"
            f"FILE_NAME({_s(asset['name'] + ' sensors.ifc')},'{date.today().isoformat()}T00:00:00',('MarineTwin'),('AHM'),'MarineTwin','MarineTwin','');\n"
            "FILE_SCHEMA(('IFC4'));\nENDSEC;\nDATA;\n")
    return head + "\n".join(lines) + "\nENDSEC;\nEND-ISO-10303-21;\n"
