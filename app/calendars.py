"""Working weeks and holidays: which days a team actually works.

A team's calendar is two things — the days of the week it works, and the days
it does not because they are holidays. Everything here is a pure function over
those two, so the arithmetic can be tested without a project, a database or a
request.

Two conventions worth stating, because the rest of the app leans on them:

* **A duration is in working days.** A deliverable that starts on a Thursday
  and takes 3 working days on a Sunday-to-Thursday week finishes on the
  following Sunday's Monday — the days the team is not there are not counted,
  because no work happens on them. Under the round-the-clock calendar every
  project starts with, a working day is a calendar day and nothing changes.
* **A date lands on a working day.** A start that falls on a holiday moves
  forward to the next day the team is in; so does a finish, because nothing is
  submitted on a day nobody is working.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable, Mapping, Sequence

# Monday is 0, as date.weekday() gives it.
DAY_NAMES: tuple[tuple[int, str, str], ...] = (
    (0, "Mon", "Monday"),
    (1, "Tue", "Tuesday"),
    (2, "Wed", "Wednesday"),
    (3, "Thu", "Thursday"),
    (4, "Fri", "Friday"),
    (5, "Sat", "Saturday"),
    (6, "Sun", "Sunday"),
)

# The working weeks worth offering by name. Anything else is set day by day.
WEEK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("1111100", "Monday to Friday"),
    ("1111001", "Sunday to Thursday"),
    ("1111110", "Monday to Saturday"),
    ("1111111", "Every day"),
)
EVERY_DAY = "1111111"
DEFAULT_WEEK = "1111100"

# How far a search for a working day will go before giving up. A calendar with
# no working days at all would otherwise loop forever.
LIMIT = 3660


def normalise_week(value: Any) -> str:
    """A working week as seven characters, Monday first.

    Anything unreadable becomes the round-the-clock week, which is the one that
    changes nothing — a bad value must never quietly shorten a programme.
    """
    text = "".join("1" if ch in "1yYtT" else "0" for ch in str(value or ""))
    if len(text) != 7 or "1" not in text:
        return EVERY_DAY
    return text


def week_label(value: Any) -> str:
    """A working week in words: a named pattern, or the days themselves."""
    week = normalise_week(value)
    named = dict(WEEK_PATTERNS).get(week)
    if named:
        return named
    days = [short for index, short, _long in DAY_NAMES if week[index] == "1"]
    return ", ".join(days) if days else "no days"


def working_days(week: Any) -> tuple[int, ...]:
    """Which weekdays are worked, as date.weekday() numbers."""
    text = normalise_week(week)
    return tuple(index for index in range(7) if text[index] == "1")


class Calendar:
    """One team's working week and holidays.

    Holidays are held as a set of ISO dates, so a day off is a lookup rather
    than a scan; the same holiday appearing twice costs nothing.
    """

    __slots__ = ("name", "week", "holidays", "_worked")

    def __init__(self, name: str = "", week: Any = EVERY_DAY,
                 holidays: Iterable[Any] = ()) -> None:
        self.name = str(name or "")
        self.week = normalise_week(week)
        self.holidays = {iso for iso in (_iso(day) for day in holidays) if iso}
        self._worked = set(working_days(self.week))

    # --- the one question everything else is built on ---------------------

    def works_on(self, day: Any) -> bool:
        """Is this a day the team is in?"""
        when = _date(day)
        if when is None:
            return False
        return when.weekday() in self._worked and when.isoformat() not in self.holidays

    def why_off(self, day: Any) -> str:
        """Why the team is not in, for saying so on the screen."""
        when = _date(day)
        if when is None:
            return ""
        if when.isoformat() in self.holidays:
            return "holiday"
        if when.weekday() not in self._worked:
            return "weekend"
        return ""

    # --- moving a date onto a working day ---------------------------------

    def next_working(self, day: Any) -> date | None:
        """This day, or the first working day after it."""
        return self._walk(day, 1)

    def last_working(self, day: Any) -> date | None:
        """This day, or the last working day before it."""
        return self._walk(day, -1)

    def _walk(self, day: Any, step: int) -> date | None:
        when = _date(day)
        if when is None:
            return None
        for _ in range(LIMIT):
            if self.works_on(when):
                return when
            when = when + timedelta(days=step)
        return None

    # --- counting ---------------------------------------------------------

    def add(self, day: Any, working: int) -> date | None:
        """Move a date on by a number of working days.

        Zero means the day itself, moved onto a working day if it is not one.
        A negative count walks backwards, which is what a workflow step planned
        "ten days before submission" needs.
        """
        start = self.next_working(day) if working >= 0 else self.last_working(day)
        if start is None:
            return None
        step = 1 if working >= 0 else -1
        left = abs(int(working))
        when = start
        for _ in range(LIMIT):
            if left == 0:
                return when
            when = when + timedelta(days=step)
            if self.works_on(when):
                left -= 1
        return when

    def finish_after(self, start: Any, duration: int) -> date | None:
        """The finish a start and a duration in working days imply.

        A duration of one day starts and finishes on the same day, as it does
        everywhere else in the app.
        """
        return self.add(start, max(1, int(duration or 1)) - 1)

    def duration(self, start: Any, finish: Any) -> int:
        """Working days from a start to a finish, counting both ends."""
        first, last = _date(start), _date(finish)
        if first is None or last is None or last < first:
            return 0
        counted, when = 0, first
        while when <= last and counted < LIMIT:
            if self.works_on(when):
                counted += 1
            when = when + timedelta(days=1)
        return counted

    def days_off(self, start: Any, finish: Any) -> list[date]:
        """The days between two dates, inclusive, that the team is not working."""
        first, last = _date(start), _date(finish)
        if first is None or last is None or last < first:
            return []
        off, when = [], first
        while when <= last and len(off) < LIMIT:
            if not self.works_on(when):
                off.append(when)
            when = when + timedelta(days=1)
        return off

    def holidays_between(self, start: Any, finish: Any) -> list[date]:
        """Only the holidays — a weekend is expected, a holiday is news."""
        return [day for day in self.days_off(start, finish)
                if day.isoformat() in self.holidays]


# The calendar a project has before anyone sets one up: every day is a working
# day, so durations are calendar days and nothing has moved.
ROUND_THE_CLOCK = Calendar("Every day", EVERY_DAY, ())


def from_row(row: Mapping[str, Any] | None, holidays: Iterable[Any] = ()) -> Calendar:
    """A calendar from a stored row, or the round-the-clock one when there is none."""
    if not row:
        return ROUND_THE_CLOCK
    return Calendar(row.get("name") or "", row.get("workdays"), holidays)


def as_date(value: Any) -> date | None:
    """A date from whatever was given — a date, an ISO string, or nothing."""
    return _date(value)


def _date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _iso(value: Any) -> str:
    when = _date(value)
    return when.isoformat() if when else ""


def parse_days(value: Any) -> str:
    """A working week from a list of checked weekday numbers."""
    if isinstance(value, str):
        return normalise_week(value)
    chosen = set()
    for item in value or ():
        try:
            chosen.add(int(item))
        except (TypeError, ValueError):
            continue
    return normalise_week("".join("1" if day in chosen else "0" for day in range(7)))


def summarise(calendar: Calendar, start: Any, finish: Any) -> dict[str, Any]:
    """What a calendar costs a stretch of the programme, for showing on screen."""
    holidays = calendar.holidays_between(start, finish)
    return {
        "name": calendar.name,
        "week": week_label(calendar.week),
        "working_days": calendar.duration(start, finish),
        "holidays": [day.isoformat() for day in holidays],
        "holiday_count": len(holidays),
    }


def named_week(week: Any) -> str:
    """The key of the named pattern a week matches, or "" when it matches none."""
    text = normalise_week(week)
    return text if text in dict(WEEK_PATTERNS) else ""


def week_days(week: Any) -> list[dict[str, Any]]:
    """The seven days, said and ticked, for drawing a chooser."""
    text = normalise_week(week)
    return [{"index": index, "short": short, "name": long, "worked": text[index] == "1"}
            for index, short, long in DAY_NAMES]


def busiest(calendars: Sequence[Calendar]) -> Calendar:
    """The calendar with the most working days, used when several teams share
    a deliverable and none of them owns it outright."""
    return max(calendars, key=lambda c: len(working_days(c.week)), default=ROUND_THE_CLOCK)
