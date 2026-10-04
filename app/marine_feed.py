"""MarineTwin's real sensors: what the kit costs, and the door a logger sends readings through.

A logger on the quay (or the fake one this module writes for a demonstration)
sends its readings by HTTPS POST with the asset's key; they land exactly as a
CSV import would, through ``marine.write_rows``. The costs are budget figures,
in US dollars, for planning and for showing a client what a monitoring system
takes. They are not quotes.
"""

from __future__ import annotations

import hmac
import json
import math
import random
import secrets
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import marine, marine_triton

# What each reading is measured with, and how it reaches MarineTwin.
#   logger:  wired to a channel on the quay's data logger
#   station: a prism read by one robotic total station for the whole berth
#   gateway: a wireless pad with its own gateway
#   survey:  a person measures it and the result is imported
#   none:    an engineer's grade, typed in
SENSOR_KIT: dict[str, dict[str, Any]] = {
    "strain": {"item": "Vibrating-wire strain gauge (Geokon 4000, Sisgeo)", "low": 250, "high": 600,
               "route": "logger", "life": "15–25 years"},
    "corrosion": {"item": "Permanent ultrasonic thickness pad (Emerson Permasense)", "low": 3000, "high": 6000,
                  "route": "gateway", "life": "10+ years, battery 5–10"},
    "displacement": {"item": "Survey prism on the cope", "low": 100, "high": 300,
                     "route": "station", "life": "10+ years"},
    "tilt": {"item": "Vibrating-wire tiltmeter (Geokon 6350)", "low": 800, "high": 1800,
             "route": "logger", "life": "15–20 years"},
    "chloride": {"item": "Embedded multi-depth corrosion probe (Sensortec Anode-Ladder)", "low": 1500, "high": 3000,
                 "route": "logger", "life": "life of the concrete"},
    "crack_width": {"item": "Vibrating-wire crackmeter (Geokon 4420)", "low": 400, "high": 900,
                    "route": "logger", "life": "15–20 years"},
    "half_cell": {"item": "Embedded reference electrode (Force Technology ERE 20)", "low": 300, "high": 800,
                  "route": "logger", "life": "life of the concrete"},
    "fender_reaction": {"item": "Fender load monitoring (Trelleborg SmartPort)", "low": 5000, "high": 15000,
                        "route": "logger", "life": "about 10 years"},
    "bollard_load": {"item": "Strain-gauged bollard base", "low": 2000, "high": 5000,
                     "route": "logger", "life": "15 years"},
    "rail_gauge": {"item": "Rail survey (line)", "low": 0, "high": 0, "route": "survey", "life": "—"},
    "rail_level": {"item": "Rail survey (level)", "low": 0, "high": 0, "route": "survey", "life": "—"},
    "inspection": {"item": "Engineer's inspection", "low": 0, "high": 0, "route": "none", "life": "—"},
}

ROUTE_WORDS = {"logger": "Logger channel", "station": "Total station", "gateway": "Own wireless gateway",
               "survey": "Survey, imported as CSV", "none": "Typed in"}

# One junction box and one multiplexer per 16 channels; one logger takes four multiplexers.
CHANNELS_PER_BOX = 16
CHANNELS_PER_LOGGER = 64
CABLE_M_PER_SENSOR = 40


def _ceil(a: int, b: int) -> int:
    return -(-a // b)


def kit(counts: dict[str, int]) -> dict[str, Any]:
    """The kit for ``counts`` sensors of each kind: lines of (item, quantity, each, total, why),
    the hardware total, installation, and what it costs a year to keep running."""
    lines: list[dict[str, Any]] = []

    def add(item: str, qty: int, low: float, high: float, why: str, group: str) -> None:
        if qty > 0:
            lines.append({"item": item, "qty": qty, "low": low, "high": high,
                          "total_low": qty * low, "total_high": qty * high, "why": why, "group": group})

    for kind, n in sorted(counts.items(), key=lambda kv: -SENSOR_KIT.get(kv[0], {}).get("high", 0) * kv[1]):
        spec = SENSOR_KIT.get(kind)
        if spec and spec["high"] > 0:
            add(spec["item"], n, spec["low"], spec["high"],
                f"{marine.SENSOR_KINDS[kind]['name']}, {ROUTE_WORDS[spec['route']].lower()}", "Sensors")
    channels = sum(n for kind, n in counts.items() if SENSOR_KIT.get(kind, {}).get("route") == "logger")
    boxes = _ceil(channels, CHANNELS_PER_BOX)
    loggers = _ceil(channels, CHANNELS_PER_LOGGER)
    add("Junction box, IP68 stainless, above the splash zone", boxes, 400, 900,
        f"one per {CHANNELS_PER_BOX} sensors, gathers their cables", "Connection")
    add("Armoured signal cable in conduit", channels * CABLE_M_PER_SENSOR, 8, 15,
        f"about {CABLE_M_PER_SENSOR} m per sensor, priced per metre", "Connection")
    add("Multiplexer (Campbell AM16/32B)", boxes, 1500, 2200,
        f"lets one logger read {CHANNELS_PER_BOX} sensors", "Connection")
    add("Data logger (Campbell CR6 or CR1000X)", loggers, 3000, 4500,
        "reads the sensors, keeps the readings, sends them", "Logger cabinet")
    add("4G modem and data SIM (Campbell CELL210, Teltonika)", loggers, 300, 800,
        "sends the readings to MarineTwin over HTTPS", "Logger cabinet")
    add("Solar panel, battery and charge regulator", loggers, 800, 1500,
        "runs the cabinet without the port's mains", "Logger cabinet")
    add("Lockable stainless cabinet on a post", loggers, 1000, 2500,
        "holds the logger, modem and battery", "Logger cabinet")
    if counts.get("displacement"):
        add("Robotic total station with monitoring software (Leica TM60 + GeoMoS)", 1, 40000, 70000,
            "reads every prism on the berth, sends readings itself", "Other")
    if counts.get("corrosion"):
        add("Wireless gateway for the thickness pads", 1, 3000, 5000,
            "collects the pads' readings, sends them itself", "Other")
    low = sum(line["total_low"] for line in lines)
    high = sum(line["total_high"] for line in lines)
    surveys = [k for k in ("rail_gauge", "rail_level") if counts.get(k)]
    return {
        "lines": lines, "channels": channels, "boxes": boxes, "loggers": loggers,
        "sensors": sum(counts.values()),
        "hardware_low": low, "hardware_high": high,
        # Installation and commissioning: from about the hardware's cost to twice it, more for diving work.
        "install_low": low, "install_high": 2 * high,
        "total_low": 2 * low, "total_high": 3 * high,
        # A year: the SIMs' data plus 5–10 % of the hardware for calibration, batteries and repairs.
        "yearly_low": loggers * 120 + 0.05 * low, "yearly_high": loggers * 360 + 0.10 * high,
        "surveys": bool(surveys),
    }


def counts_for(conn: sqlite3.Connection, asset_id: int, element_id: int | None = None) -> dict[str, int]:
    sql = ("SELECT s.kind, COUNT(*) AS n FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
           " WHERE e.asset_id = ?")
    args: list[Any] = [asset_id]
    if element_id is not None:
        sql += " AND e.id = ?"
        args.append(element_id)
    return {r["kind"]: r["n"] for r in conn.execute(sql + " GROUP BY s.kind", args)}


# --- the key ----------------------------------------------------------------------------

def key_for(conn: sqlite3.Connection, asset_id: int, renew: bool = False) -> str:
    """The asset's feed key, made the first time it is asked for. Renewing it shuts out the old one."""
    row = conn.execute("SELECT feed_key FROM marine_assets WHERE id = ?", (asset_id,)).fetchone()
    if row is None:
        return ""
    if row["feed_key"] and not renew:
        return row["feed_key"]
    key = "mt_" + secrets.token_urlsafe(24)
    conn.execute("UPDATE marine_assets SET feed_key = ? WHERE id = ?", (key, asset_id))
    return key


def key_matches(asset: Any, given: str) -> bool:
    stored = asset["feed_key"] if asset is not None else ""
    return bool(stored) and bool(given) and hmac.compare_digest(stored.encode(), given.strip().encode())


# --- what a logger sends -----------------------------------------------------------------

MAX_ROWS = 10_000


def receive(conn: sqlite3.Connection, asset_id: int, payload: Any, device: str = "") -> dict[str, Any]:
    """Readings a logger sent, as parsed JSON: a list of readings, or ``{"device": …, "readings": [...]}``.
    Written like an import and logged, so the page can show what arrived and when."""
    if isinstance(payload, dict):
        device = str(payload.get("device") or device or "")
        rows = payload.get("readings")
    else:
        rows = payload
    if not isinstance(rows, list):
        result = {"written": 0, "sensors": 0, "problem_count": 1,
                  "problems": ["Send a list of readings, or an object with a “readings” list."]}
    elif len(rows) > MAX_ROWS:
        result = {"written": 0, "sensors": 0, "problem_count": 1,
                  "problems": [f"At most {MAX_ROWS:,} readings at a time; send them in smaller batches."]}
    else:
        result = marine.write_rows(conn, asset_id, rows, device=device[:60])
    log(conn, asset_id, device[:60], result)
    return result


def receive_csv(conn: sqlite3.Connection, asset_id: int, text: str, device: str = "") -> dict[str, Any]:
    """The same, sent as a CSV file's text (the columns of the import)."""
    result = marine.import_csv(conn, asset_id, text, device=device[:60])
    log(conn, asset_id, device[:60], result)
    return result


def log(conn: sqlite3.Connection, asset_id: int, device: str, result: dict[str, Any]) -> None:
    conn.execute("INSERT INTO marine_feed_log (asset_id, at, device, written, problems, first_problem)"
                 " VALUES (?, ?, ?, ?, ?, ?)",
                 (asset_id, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), device,
                  result["written"], result.get("problem_count", len(result["problems"])),
                  (result["problems"] or [""])[0]))
    # Keep the last few hundred; the readings themselves are what matters.
    conn.execute("DELETE FROM marine_feed_log WHERE asset_id = ? AND id NOT IN"
                 " (SELECT id FROM marine_feed_log WHERE asset_id = ? ORDER BY id DESC LIMIT 300)",
                 (asset_id, asset_id))


def status(conn: sqlite3.Connection, asset_id: int) -> dict[str, Any]:
    """What the page's live panel shows: the last deliveries and every sensor a logger feeds."""
    deliveries = [dict(r) for r in conn.execute(
        "SELECT at, device, written, problems, first_problem FROM marine_feed_log WHERE asset_id = ?"
        " ORDER BY id DESC LIMIT 12", (asset_id,))]
    fed = []
    for r in conn.execute(
            "SELECT s.id, s.label, s.kind, s.feed_device, e.name AS element, e.id AS element_id,"
            " (SELECT COUNT(*) FROM marine_readings WHERE sensor_id = s.id) AS count,"
            " (SELECT value FROM marine_readings WHERE sensor_id = s.id ORDER BY at DESC LIMIT 1) AS latest,"
            " (SELECT at FROM marine_readings WHERE sensor_id = s.id ORDER BY at DESC LIMIT 1) AS latest_at"
            " FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
            " WHERE e.asset_id = ? AND s.feed_device != '' ORDER BY s.label", (asset_id,)):
        spec = marine.SENSOR_KINDS.get(r["kind"], {"name": r["kind"], "unit": ""})
        row = dict(r)
        if row["latest"] is not None:
            row["latest"] = float(f"{row['latest']:.4g}")          # what the gauge can claim
        fed.append({**row, "kind_name": spec["name"], "unit": spec["unit"]})
    return {"deliveries": deliveries, "fed": fed}


# --- the fake logger --------------------------------------------------------------------

# How much a reading wanders from one to the next, per kind: a few times the gauge's own noise.
WANDER = {"strain": 12.0, "corrosion": 0.01, "displacement": 0.3, "tilt": 0.006, "chloride": 0.003,
          "crack_width": 0.004, "half_cell": 6.0, "fender_reaction": 0.0, "bollard_load": 0.0,
          "rail_gauge": 0.3, "rail_level": 0.3}
FAKE_DEVICE = "fake-logger"


def fake_channels(conn: sqlite3.Connection, asset: Any, limit: int = 6) -> list[dict[str, Any]]:
    """The sensors the fake logger reads: one of each logged kind, from the elements in the worst
    condition first, each starting from where its simulated record left off."""
    ratings = marine_triton.ratings(asset)
    rows = conn.execute(
        "SELECT s.*, e.name AS element FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
        " WHERE e.asset_id = ? ORDER BY e.id, s.id", (asset["id"],)).fetchall()
    chosen: dict[str, Any] = {}
    for s in rows:
        if SENSOR_KIT.get(s["kind"], {}).get("route") == "logger" and s["kind"] not in chosen:
            chosen[s["kind"]] = s
    out = []
    for s in list(chosen.values())[:limit]:
        last = conn.execute("SELECT value FROM marine_readings WHERE sensor_id = ? ORDER BY at DESC LIMIT 1",
                            (s["id"],)).fetchone()
        alert, alarm, _ = marine.limits(s, ratings)
        spec = marine.SENSOR_KINDS[s["kind"]]
        start = float(last["value"]) if last else float(alert or 0) * 0.5
        rating = float(alarm or 1.0)
        out.append({"sensor": s["label"], "kind": s["kind"], "unit": spec["unit"], "start": round(start, 4),
                    "wander": WANDER.get(s["kind"], 0.0) or round(rating * 0.04, 2),
                    "alarm": alarm, "lower_worse": bool(spec.get("lower_worse")),
                    "loads": s["kind"] in ("fender_reaction", "bollard_load"), "rating": rating})
    return out


def fake_value(channel: dict[str, Any], previous: float, rng: random.Random) -> float:
    """The next reading: a load from a berthing or a mooring line, or a slow drift back to its start."""
    if channel["loads"]:
        value = channel["rating"] * rng.uniform(0.12, 0.35)
    else:
        value = previous + 0.3 * (channel["start"] - previous) + rng.gauss(0, channel["wander"])
    return round(value, 4)


def fake_script(base_url: str, asset: Any, key: str, channels: list[dict[str, Any]]) -> str:
    """A fake logger as one Python file that runs anywhere Python 3 does, with nothing to install."""
    config = json.dumps({"url": f"{base_url}/marinetwin/api/assets/{asset['id']}/readings", "key": key,
                         "device": FAKE_DEVICE, "asset": asset["name"], "channels": channels}, indent=2)
    return FAKE_SCRIPT.replace("__CONFIG__", config)


FAKE_SCRIPT = '''"""A fake data logger for MarineTwin.

It does what the logger in the quay's cabinet does: reads its sensors, keeps
the readings, and sends them to MarineTwin over HTTPS with the asset's key.
The readings are made up, starting from where each sensor's record left off.

Run it with Python 3 (nothing to install):

    python fake_logger.py              sends the last 24 hours, then a reading every 10 seconds
    python fake_logger.py --every 600  a reading every 10 minutes, like a real logger
    python fake_logger.py --alarm      sends one reading past its alarm limit, then stops

Stop it with Ctrl+C. Open the asset in MarineTwin to watch the readings arrive.
"""

import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

CONFIG = json.loads(r\'\'\'__CONFIG__\'\'\')


def send(readings):
    """POST the readings; a real logger keeps them and tries again when the network is down."""
    body = json.dumps({"device": CONFIG["device"], "readings": readings}).encode()
    request = urllib.request.Request(CONFIG["url"], data=body, method="POST", headers={
        "Content-Type": "application/json", "Authorization": "Bearer " + CONFIG["key"]})
    try:
        with urllib.request.urlopen(request, timeout=30) as answer:
            result = json.loads(answer.read())
    except urllib.error.HTTPError as error:
        print("MarineTwin refused it:", error.code, error.read().decode(errors="replace")[:300])
        return False
    except urllib.error.URLError as error:
        print("Could not reach MarineTwin, keeping the readings:", error.reason)
        return False
    print(f"{datetime.now():%H:%M:%S}  sent {len(readings)}, MarineTwin wrote {result.get('written')}"
          + (f", problems: {result['problems'][:2]}" if result.get("problems") else ""))
    return True


def next_value(channel, previous, rng):
    if channel["loads"]:
        return round(channel["rating"] * rng.uniform(0.12, 0.35), 4)
    return round(previous + 0.3 * (channel["start"] - previous) + rng.gauss(0, channel["wander"]), 4)


def main():
    every = 10.0
    if "--every" in sys.argv:
        every = float(sys.argv[sys.argv.index("--every") + 1])
    rng = random.Random()
    channels = CONFIG["channels"]
    if not channels:
        print("This asset has no sensors a logger reads. Add some in MarineTwin first.")
        return
    print(f"Fake logger for {CONFIG['asset']}: {len(channels)} sensors, sending to {CONFIG['url']}")
    if "--alarm" in sys.argv:
        c = next((c for c in channels if c["alarm"] is not None and not c["loads"]), channels[0])
        value = (c["alarm"] - abs(c["alarm"]) * 0.15) if c["lower_worse"] else (c["alarm"] or 1) * 1.1
        send([{"sensor": c["sensor"], "at": f"{datetime.now():%Y-%m-%dT%H:%M}", "value": round(value, 4),
               "note": "alarm test from the fake logger"}])
        return
    last = {c["sensor"]: c["start"] for c in channels}
    # What the logger kept while it was not sending: the last 24 hours, hourly.
    now = datetime.now().replace(second=0, microsecond=0)
    backlog = []
    for hours in range(24, 0, -1):
        at = f"{now - timedelta(hours=hours):%Y-%m-%dT%H:%M}"
        for c in channels:
            last[c["sensor"]] = next_value(c, last[c["sensor"]], rng)
            backlog.append({"sensor": c["sensor"], "at": at, "value": last[c["sensor"]]})
    pending = backlog
    while True:
        at = f"{datetime.now():%Y-%m-%dT%H:%M}"
        for c in channels:
            last[c["sensor"]] = next_value(c, last[c["sensor"]], rng)
            pending.append({"sensor": c["sensor"], "at": at, "value": last[c["sensor"]]})
        if send(pending):
            pending = []
        time.sleep(every)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
'''


def back_to_simulation(conn: sqlite3.Connection, asset_id: int, device: str = FAKE_DEVICE) -> int:
    """The fake logger's sensors go back to their simulated record, as before the demonstration."""
    ids = [r["id"] for r in conn.execute(
        "SELECT s.id FROM marine_sensors s JOIN marine_elements e ON e.id = s.element_id"
        " WHERE e.asset_id = ? AND s.feed_device = ?", (asset_id, device))]
    if ids:
        marks = ",".join("?" * len(ids))
        conn.execute(f"UPDATE marine_sensors SET simulated = 1, feed_device = '' WHERE id IN ({marks})", ids)
        marine.refresh_simulated(conn, asset_id)
    return len(ids)


def money(value: float) -> str:
    """$1,200 / $45k / $1.2M: a budget figure, rounded to what it can claim."""
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    if value >= 10_000:
        return f"${math.floor(value / 1000 + 0.5):,}k"
    if value >= 100:
        return f"${round(value, -1):,.0f}"
    return f"${value:,.0f}"
