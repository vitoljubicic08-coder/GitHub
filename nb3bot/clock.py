"""Clocks: the real wall clock, and a simulated clock for replays and tests (time only moves when told)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from nb3bot.timeutil import UTC


class RealClock:
    simulated = False

    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep(self, seconds: float) -> None:
        time.sleep(max(0.0, seconds))


class SimClock:
    simulated = True

    def __init__(self, start: datetime):
        if start.tzinfo is None:
            raise ValueError("SimClock needs a timezone-aware start")
        self.t = start.astimezone(UTC)

    def now(self) -> datetime:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += timedelta(seconds=seconds)

    def set(self, t: datetime) -> None:
        if t > self.t:
            self.t = t.astimezone(UTC)
