"""Time helpers. All stored times are UTC ISO-8601 strings ('YYYY-MM-DDTHH:MM:SSZ'), which sort
correctly as text; business logic works in the business's local time zone."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc


def utcnow() -> dt.datetime:
    return dt.datetime.now(UTC).replace(microsecond=0)


def to_iso(t: dt.datetime) -> str:
    if t.tzinfo is None:
        raise ValueError("naive datetime")
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def local(t: dt.datetime, tz: ZoneInfo) -> dt.datetime:
    return t.astimezone(tz)


def easter(year: int) -> dt.date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def croatian_holidays(year: int) -> dict:
    """Public holidays in Croatia (Zakon o blagdanima, spomendanima i neradnim danima, as amended 2019)."""
    e = easter(year)
    return {
        dt.date(year, 1, 1): "Nova godina",
        dt.date(year, 1, 6): "Sveta tri kralja",
        e: "Uskrs",
        e + dt.timedelta(days=1): "Uskrsni ponedjeljak",
        dt.date(year, 5, 1): "Praznik rada",
        dt.date(year, 5, 30): "Dan državnosti",
        e + dt.timedelta(days=60): "Tijelovo",
        dt.date(year, 6, 22): "Dan antifašističke borbe",
        dt.date(year, 8, 5): "Dan pobjede i domovinske zahvalnosti",
        dt.date(year, 8, 15): "Velika Gospa",
        dt.date(year, 11, 1): "Svi sveti",
        dt.date(year, 11, 18): "Dan sjećanja na žrtve Domovinskog rata",
        dt.date(year, 12, 25): "Božić",
        dt.date(year, 12, 26): "Sveti Stjepan",
    }
