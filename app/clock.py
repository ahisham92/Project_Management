"""What time it is where the project is, and whether tonight's backup has run.

A server keeps UTC and a scheduler runs on UTC, but "every day at midnight"
means midnight in Cairo, and Egypt puts its clocks forward in April and back
in October. Fixing a UTC hour gets it right for half the year and an hour out
for the other half.

So the hour is kept in the project's own zone and converted each time it is
asked for. `zoneinfo` is in the standard library and reads the system's own
timezone database; where that database is missing — a bare Windows install —
Egypt's rule is written out below so the answer is still right rather than
silently an hour off.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone, tzinfo
from typing import Any

DEFAULT_ZONE = "Africa/Cairo"
DEFAULT_HOUR = 0                                  # midnight


def zone(name: str = DEFAULT_ZONE):
    """The named zone, or a stand-in that keeps the same rule."""
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name or DEFAULT_ZONE)
    except Exception:                             # noqa: BLE001 - the fallback is the point
        return _Egypt() if (name or DEFAULT_ZONE) in ("Africa/Cairo", "Egypt") else timezone.utc


def now(name: str = DEFAULT_ZONE, at: datetime | None = None) -> datetime:
    """The wall clock in that zone, from a UTC instant."""
    moment = at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone(name))


def local_date(name: str = DEFAULT_ZONE, at: datetime | None = None) -> str:
    """Today's date there, which is not always today's date here."""
    return now(name, at).date().isoformat()


def utc_hour(hour: int = DEFAULT_HOUR, name: str = DEFAULT_ZONE,
             at: datetime | None = None) -> str:
    """That local hour as a UTC time today, for setting a scheduler by.

    Written out because a host that only runs UTC schedules needs to be told a
    UTC time, and the right one moves with the clocks.
    """
    here = now(name, at)
    wanted = here.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    return wanted.astimezone(timezone.utc).strftime("%H:%M")


def offset_words(name: str = DEFAULT_ZONE, at: datetime | None = None) -> str:
    """"UTC+3" — so a printed instruction can be checked by eye."""
    shift = now(name, at).utcoffset() or timedelta(0)
    minutes = int(shift.total_seconds() // 60)
    sign = "+" if minutes >= 0 else "-"
    minutes = abs(minutes)
    return f"UTC{sign}{minutes // 60}" + (f":{minutes % 60:02d}" if minutes % 60 else "")


def due(last_run: Any, hour: int = DEFAULT_HOUR, name: str = DEFAULT_ZONE,
        at: datetime | None = None) -> bool:
    """Whether tonight's backup still owes us a run.

    `last_run` is when the last successful one started, in UTC, as the database
    keeps it. A run is owed once the local day has turned past the appointed
    hour and nothing has run since — so a missed night is caught the moment
    anybody looks, rather than waiting a further day.
    """
    here = now(name, at)
    appointed = here.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    if here < appointed:
        # Not yet tonight's hour; the day that is owed is yesterday's.
        appointed -= timedelta(days=1)

    if not last_run:
        return True
    stamp = parse_utc(last_run)
    return stamp is None or stamp.astimezone(zone(name)) < appointed


def parse_utc(value: Any) -> datetime | None:
    """A "YYYY-MM-DD HH:MM:SS" stamp out of SQLite, read as UTC."""
    text = str(value or "").strip().replace("T", " ")
    if not text:
        return None
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], shape).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def next_run(hour: int = DEFAULT_HOUR, name: str = DEFAULT_ZONE,
             at: datetime | None = None) -> datetime:
    """When the next one is due, in local time."""
    here = now(name, at)
    appointed = here.replace(hour=int(hour) % 24, minute=0, second=0, microsecond=0)
    return appointed if appointed > here else appointed + timedelta(days=1)


class _Egypt(tzinfo):
    """Egypt's clock, for a machine with no timezone database.

    Since 2023 the clocks go forward on the last Friday of April and back on
    the last Thursday of October. Only used when `zoneinfo` cannot find the
    real rule, which on a Linux host it always can.
    """

    def utcoffset(self, dt):                      # noqa: D102 - the rule itself
        return timedelta(hours=3 if self._summer(dt) else 2)

    def dst(self, dt):                            # noqa: D102
        return timedelta(hours=1) if self._summer(dt) else timedelta(0)

    def tzname(self, dt):                         # noqa: D102
        return "EEST" if self._summer(dt) else "EET"

    @staticmethod
    def _summer(dt) -> bool:
        if dt is None:
            return False
        forward = _last_weekday(dt.year, 4, 4)    # last Friday of April
        back = _last_weekday(dt.year, 10, 3)      # last Thursday of October
        return forward <= dt.date() < back


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """The last Friday of April, and its like."""
    day = date(year, month, 1) + timedelta(days=31)
    day = day.replace(day=1) - timedelta(days=1)  # the last day of `month`
    return day - timedelta(days=(day.weekday() - weekday) % 7)
