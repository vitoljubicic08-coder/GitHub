"""Synthetic market data and small fixtures shared by the tests."""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from nb3bot.replay.data import Session
from nb3bot.timeutil import TradingCalendar, session_key

DATA_CANDIDATES = [os.environ.get("NB3_QQQ_DATA", ""),
                   "/tmp/claude-0/-home-user-GitHub/f4c38b43-8d2d-5827-bc2b-19009e738a12/scratchpad/inst"]


def real_data_dir() -> str | None:
    for p in DATA_CANDIDATES:
        if p and list(Path(p).glob("market_*.npz")):
            return p
    return None


def trading_days(start: date, n: int) -> list[date]:
    cal, out, d = TradingCalendar(), [], start
    while len(out) < n:
        if cal.is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def flat_session(d: date, price: float = 500.0, wiggle: float = 0.25, seed: int = 0) -> Session:
    """A quiet day: every minute moves at most `wiggle` around `price` (deterministic)."""
    rng = np.random.default_rng(seed)
    c = price + wiggle * np.sin(np.arange(390) / 7.0) + rng.uniform(-0.02, 0.02, 390)
    o = np.r_[price, c[:-1]]
    h = np.maximum(o, c) + 0.03
    l = np.minimum(o, c) - 0.03
    return Session(session_key(d), o, h, l, c, np.full(390, 1000.0))


def breakout_session(d: date, price: float = 500.0, at_minute: int = 20, move: float = 6.0, direction: int = 1,
                     then: float = 0.0) -> Session:
    """Quiet until `at_minute`, then a jump of `move` in `direction`, then drift `then` per minute."""
    s = flat_session(d, price, wiggle=0.0, seed=99)    # perfectly quiet before the breakout: no early signal
    s.c[:] = price
    s.o[:] = price
    s.h[:] = price + 0.03
    s.l[:] = price - 0.03
    for m in range(at_minute, 390):
        shift = direction * (move + then * (m - at_minute))
        s.o[m] += shift if m > at_minute else 0.0
        s.c[m] += shift
        s.h[m] = max(s.o[m], s.c[m]) + 0.03
        s.l[m] = min(s.o[m], s.c[m]) - 0.03
    return s
