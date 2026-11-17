"""Market-data primitives and the per-session feed with its health checks."""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from nb3bot.timeutil import NY, UTC, minute_index, minute_start, session_key


@dataclass(frozen=True)
class MinuteBar:
    ts: datetime          # bar OPEN time, timezone-aware UTC
    o: float
    h: float
    l: float
    c: float
    v: float = 0.0

    def valid(self) -> bool:
        vals = (self.o, self.h, self.l, self.c)
        return (all(isinstance(x, (int, float)) and not math.isnan(x) and x > 0 for x in vals)
                and self.h >= max(self.o, self.c) - 1e-9 and self.l <= min(self.o, self.c) + 1e-9)


class MinuteSource(Protocol):
    name: str
    realtime: bool        # False if the provider says its data is delayed

    def fetch(self, start: datetime, end: datetime) -> list[MinuteBar]:
        """Completed 1-minute bars whose OPEN time is in [start, end), ascending."""
        ...


@dataclass
class SessionFeed:
    """Regular-session minute bars of one instrument for one session, with completeness tracking."""
    symbol: str
    key: int
    bars: dict[int, MinuteBar] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)
    revised: list[int] = field(default_factory=list)

    def add(self, b: MinuteBar) -> int | None:
        ny = b.ts.astimezone(NY)
        if session_key(ny.date()) != self.key:
            return None
        m = minute_index(ny)
        if m is None:
            return None
        if not b.valid():
            self.rejected.append(f"{self.symbol} {ny:%H:%M} invalid OHLC {b.o},{b.h},{b.l},{b.c}")
            return None
        if m in self.bars:
            if self.bars[m] != b:
                self.revised.append(m)
                self.bars[m] = b
            return None
        self.bars[m] = b
        return m

    def missing(self, upto_minute: int) -> list[int]:
        return [m for m in range(upto_minute + 1) if m not in self.bars]

    def last_close(self, upto_minute: int) -> float:
        for m in range(upto_minute, -1, -1):
            if m in self.bars:
                return self.bars[m].c
        return math.nan


def expected_last_minute(now: datetime, key: int, grace_s: float) -> int:
    """Index of the latest minute that must be complete at `now` (-1 if none yet)."""
    start = minute_start(key, 0)
    secs = (now - start).total_seconds() - grace_s
    return min(389, int(secs // 60) - 1)


@dataclass
class HealthReport:
    ok: bool
    detail: str


def check_feed(feed: SessionFeed, now: datetime, max_delay_s: float, bar_minutes: range | None = None) -> HealthReport:
    """Stale/missing data check: every minute that ended more than max_delay_s ago must be present."""
    last_due = expected_last_minute(now, feed.key, max_delay_s)
    if last_due < 0:
        return HealthReport(True, f"{feed.symbol}: session not started")
    window = bar_minutes if bar_minutes is not None else range(0, last_due + 1)
    miss = [m for m in window if m <= last_due and m not in feed.bars]
    if miss:
        t = minute_start(feed.key, miss[0]).astimezone(NY)
        return HealthReport(False, f"{feed.symbol}: {len(miss)} minute bar(s) missing, first {t:%H:%M} New York")
    if feed.rejected:
        return HealthReport(False, f"{feed.symbol}: rejected bad bar(s): {feed.rejected[-1]}")
    return HealthReport(True, f"{feed.symbol}: complete to {(minute_start(feed.key, last_due) + timedelta(minutes=1)).astimezone(NY):%H:%M}")


def check_ratio(sig: SessionFeed, exe: SessionFeed, m: int, max_dev: float) -> HealthReport:
    """Cross-instrument consistency: exec/signal price ratio at minute m vs today's median ratio."""
    ratios = [exe.bars[k].c / sig.bars[k].c for k in sorted(set(sig.bars) & set(exe.bars)) if k <= m]
    if m not in sig.bars or m not in exe.bars or len(ratios) < 3:
        return HealthReport(False, f"cannot compare {exe.symbol}/{sig.symbol} at minute {m}: bars missing")
    med = statistics.median(ratios)
    now = exe.bars[m].c / sig.bars[m].c
    dev = abs(now / med - 1)
    return HealthReport(dev <= max_dev, f"{exe.symbol}/{sig.symbol} ratio {now:.3f} vs median {med:.3f} ({dev:.2%})")


def ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("naive timestamp")
    return ts.astimezone(UTC)
