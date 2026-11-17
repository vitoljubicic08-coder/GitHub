"""Exchange-aware time: New York session clock, NYSE trading calendar, Zagreb display time.

All trading decisions use America/New_York wall-clock times derived from timezone-aware UTC
timestamps (zoneinfo handles daylight-saving changes, including the weeks when the US and Europe
change on different dates). Europe/Zagreb is used for display only.

NYSE calendar: full holidays and 13:00 early closes are generated from NYSE's published rules
(New Year's Day, MLK Day, Washington's Birthday, Good Friday, Memorial Day, Juneteenth, Independence
Day, Labor Day, Thanksgiving, Christmas; Saturday holidays observed on Friday, Sunday holidays on
Monday, except that a Saturday New Year's Day is not observed). Early closes: July 3 (when a weekday
and July 4 is a weekday), the day after Thanksgiving, and December 24 (when a weekday). The rules are
checked against the published calendar in the tests; `calendar_overrides` in the config can add or
remove dates if NYSE announces an exception (for example a national day of mourning).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
ZAGREB = ZoneInfo("Europe/Zagreb")
UTC = timezone.utc
OPEN = time(9, 30)
CLOSE = time(16, 0)
EARLY_CLOSE = time(13, 0)


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_ny(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("naive datetime: every timestamp must carry a timezone")
    return ts.astimezone(NY)


def session_key(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def key_to_date(key: int) -> date:
    return date(key // 10000, key // 100 % 100, key % 100)


def minute_index(ny: datetime) -> int | None:
    """Regular-session minute index (0 = the 09:30 bar) of a bar OPEN time, or None outside 09:30-15:59."""
    m = ny.hour * 60 + ny.minute - (9 * 60 + 30)
    return m if 0 <= m < 390 else None


def minute_start(key: int, m: int) -> datetime:
    """UTC start time of regular-session minute m on session `key`."""
    d = key_to_date(key)
    ny = datetime.combine(d, OPEN, NY) + timedelta(minutes=m)
    return ny.astimezone(UTC)


# ---------------------------------------------------------------------------- NYSE calendar
def _easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    return date(y, month, day)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> date:
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(y: int, month: int, weekday: int) -> date:
    d = date(y, month + 1, 1) - timedelta(days=1) if month < 12 else date(y, 12, 31)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


# Unscheduled closures announced by NYSE (national days of mourning, weather). Add new ones in the config.
SPECIAL_CLOSURES = {date(2012, 10, 29), date(2012, 10, 30), date(2018, 12, 5), date(2025, 1, 9)}


@lru_cache(maxsize=None)
def nyse_holidays(y: int) -> frozenset[date]:
    out = {d for d in SPECIAL_CLOSURES if d.year == y}
    ny_day = date(y, 1, 1)
    if ny_day.weekday() != 5:                     # a Saturday New Year's Day is not observed
        out.add(_observed(ny_day))
    out.add(_nth_weekday(y, 1, 0, 3))             # MLK Day
    out.add(_nth_weekday(y, 2, 0, 3))             # Washington's Birthday
    out.add(_easter(y) - timedelta(days=2))       # Good Friday
    out.add(_last_weekday(y, 5, 0))               # Memorial Day
    if y >= 2022:
        out.add(_observed(date(y, 6, 19)))        # Juneteenth
    out.add(_observed(date(y, 7, 4)))             # Independence Day
    out.add(_nth_weekday(y, 9, 0, 1))             # Labor Day
    out.add(_nth_weekday(y, 11, 3, 4))            # Thanksgiving
    out.add(_observed(date(y, 12, 25)))           # Christmas
    return frozenset(d for d in out if d.year == y)


@lru_cache(maxsize=None)
def nyse_early_closes(y: int) -> frozenset[date]:
    out = set()
    j3 = date(y, 7, 3)
    if j3.weekday() < 5 and date(y, 7, 4).weekday() < 5:
        out.add(j3)
    out.add(_nth_weekday(y, 11, 3, 4) + timedelta(days=1))
    c24 = date(y, 12, 24)
    if c24.weekday() < 5:
        out.add(c24)
    return frozenset(d for d in out if d not in nyse_holidays(y))


class TradingCalendar:
    def __init__(self, add_holidays: list[str] | None = None, remove_holidays: list[str] | None = None,
                 add_early_closes: list[str] | None = None):
        self.add_h = {date.fromisoformat(x) for x in (add_holidays or [])}
        self.rm_h = {date.fromisoformat(x) for x in (remove_holidays or [])}
        self.add_e = {date.fromisoformat(x) for x in (add_early_closes or [])}

    def is_holiday(self, d: date) -> bool:
        return (d in nyse_holidays(d.year) or d in self.add_h) and d not in self.rm_h

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and not self.is_holiday(d)

    def is_early_close(self, d: date) -> bool:
        return self.is_trading_day(d) and (d in nyse_early_closes(d.year) or d in self.add_e)

    def close_time(self, d: date) -> time:
        return EARLY_CLOSE if self.is_early_close(d) else CLOSE

    def previous_trading_day(self, d: date) -> date:
        d -= timedelta(days=1)
        while not self.is_trading_day(d):
            d -= timedelta(days=1)
        return d

    def next_trading_day(self, d: date) -> date:
        d += timedelta(days=1)
        while not self.is_trading_day(d):
            d += timedelta(days=1)
        return d


def fmt_dual(ts: datetime) -> str:
    """'09:35:02 New York / 15:35:02 Zagreb' for logs and the dashboard."""
    return f"{ts.astimezone(NY):%Y-%m-%d %H:%M:%S} New York / {ts.astimezone(ZAGREB):%H:%M:%S} Zagreb"
