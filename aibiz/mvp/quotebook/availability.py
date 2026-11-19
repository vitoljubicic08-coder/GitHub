"""Free time slots from opening hours, public holidays, owner blocks and existing bookings."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from .config import DAYS
from .timeutil import croatian_holidays, from_iso, to_iso

ACTIVE_SQL = ("status IN ('pending_owner','confirmed') OR "
              "(status = 'held' AND hold_expires_utc > ?)")


@dataclass(frozen=True)
class Slot:
    start: dt.datetime   # aware, UTC
    end: dt.datetime
    resource_id: str

    def key(self) -> str:
        return f"{to_iso(self.start)}|{self.resource_id}"


def is_closed_day(cfg, day: dt.date) -> bool:
    return (day in cfg.closed_dates or day in croatian_holidays(day.year)
            or not cfg.hours.get(DAYS[day.weekday()]))


def busy_intervals(conn, resource_id: str, start: dt.datetime, end: dt.datetime, now: dt.datetime,
                   buffer_min: int = 0, exclude_booking_id=None) -> list:
    """Bookings (padded by the buffer) and owner blocks that touch [start, end)."""
    pad = dt.timedelta(minutes=buffer_min)
    lo, hi = to_iso(start - pad), to_iso(end + pad)
    rows = conn.execute(
        f"SELECT id, start_utc, end_utc FROM bookings WHERE resource_id = ? AND ({ACTIVE_SQL}) "
        "AND start_utc < ? AND end_utc > ?", (resource_id, to_iso(now), hi, lo)).fetchall()
    out = [(from_iso(r["start_utc"]) - pad, from_iso(r["end_utc"]) + pad)
           for r in rows if r["id"] != exclude_booking_id]
    rows = conn.execute("SELECT start_utc, end_utc FROM blocks WHERE (resource_id IS NULL OR resource_id = ?) "
                        "AND start_utc < ? AND end_utc > ?", (resource_id, to_iso(end), to_iso(start))).fetchall()
    out += [(from_iso(r["start_utc"]), from_iso(r["end_utc"])) for r in rows]
    return out


def is_free(conn, resource_id, start, end, now, buffer_min=0, exclude_booking_id=None) -> bool:
    return not any(a < end and start < b for a, b in
                   busy_intervals(conn, resource_id, start, end, now, buffer_min, exclude_booking_id))


def within_hours(cfg, start: dt.datetime, end: dt.datetime) -> bool:
    ls, le = start.astimezone(cfg.tz), end.astimezone(cfg.tz)
    if ls.date() != le.date() or is_closed_day(cfg, ls.date()):
        return False
    return any(a <= ls.time() and le.time() <= z for a, z in cfg.hours[DAYS[ls.weekday()]])


def day_slots(conn, cfg, service, minutes: int, day: dt.date, now: dt.datetime, *, ignore_notice=False,
              exclude_booking_id=None) -> list:
    """All bookable starts on one local day, earliest first, first free resource for each."""
    b = cfg.booking
    if is_closed_day(cfg, day):
        return []
    earliest = now + dt.timedelta(hours=0 if ignore_notice else b["min_notice_hours"])
    latest_day = (now.astimezone(cfg.tz) + dt.timedelta(days=b["horizon_days"])).date()
    if day > latest_day:
        return []
    step = dt.timedelta(minutes=b["slot_step_minutes"])
    dur = dt.timedelta(minutes=minutes)
    out = []
    for open_t, close_t in cfg.hours[DAYS[day.weekday()]]:
        t = dt.datetime.combine(day, open_t, tzinfo=cfg.tz)
        close = dt.datetime.combine(day, close_t, tzinfo=cfg.tz)
        while t + dur <= close:
            # walking in local wall-clock time keeps 08:00, 08:30 ... correct across DST changes
            su, eu = t.astimezone(dt.timezone.utc), (t + dur).astimezone(dt.timezone.utc)
            if su >= earliest:
                for rid in service.resources:
                    if is_free(conn, rid, su, eu, now, b["buffer_minutes"], exclude_booking_id):
                        out.append(Slot(su, eu, rid))
                        break
            t = t + step
    return out


def suggest(conn, cfg, service, minutes: int, now: dt.datetime, *, date: dt.date = None, time: dt.time = None,
            window=None, n: int = 3, exclude_booking_id=None) -> list:
    """Up to n options closest to what the customer asked for, spread out so they are real choices."""
    tz = cfg.tz
    today = now.astimezone(tz).date()
    start_day = max(date or today, today)
    horizon = cfg.booking["horizon_days"]
    picked = []
    for k in range(horizon + 1):
        day = start_day + dt.timedelta(days=k)
        slots = day_slots(conn, cfg, service, minutes, day, now, exclude_booking_id=exclude_booking_id)
        if not slots:
            continue
        if window and k == 0:
            inwin = [s for s in slots if window[0] <= s.start.astimezone(tz).hour < window[1]]
            slots = inwin or slots
        if time and k == 0:
            target = dt.datetime.combine(day, time, tzinfo=tz)
            slots = sorted(slots, key=lambda s: abs((s.start - target).total_seconds()))
        for s in slots:
            if all(abs((s.start - p.start).total_seconds()) >= 90 * 60 for p in picked):
                picked.append(s)
                if len(picked) >= n:
                    return sorted(picked, key=lambda x: x.start)
        if date and picked and k >= 1:
            break
    return sorted(picked, key=lambda x: x.start)
