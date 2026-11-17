"""SYNTHETIC QQQ-like minute sessions for the offline demo and tests. NOT market data.

Random walk with a U-shaped intraday volatility profile, overnight gaps and occasional trend days,
so the NB3 V2 engine produces signals. Deterministic for a given seed. Any profit or loss on this data
is meaningless; it only exercises the machinery.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from nb3bot.replay.data import Session
from nb3bot.timeutil import TradingCalendar, session_key


def synthetic_sessions(n: int, seed: int = 7, start: date = date(2025, 1, 2), price: float = 500.0) -> list[Session]:
    rng = np.random.default_rng(seed)
    cal = TradingCalendar()
    days, d = [], start
    while len(days) < n:
        if cal.is_trading_day(d):
            days.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    t = np.arange(390)
    vol_shape = 1.0 + 1.5 * np.exp(-t / 30.0) + 0.6 * np.exp(-(389 - t) / 25.0)   # busy open and close
    out = []
    p = price
    for day in days:
        p *= float(np.exp(rng.normal(0, 0.004)))                                  # overnight gap
        drift = rng.choice([0.0, 0.0, 0.00005, -0.00005]) * (1 + rng.random())   # some trend days
        r = drift + 0.0005 * vol_shape * rng.standard_normal(390)
        c = p * np.exp(np.cumsum(r))
        o = np.r_[p, c[:-1]]
        wig = np.abs(rng.normal(0, 0.0002, 390))
        h = np.maximum(o, c) * (1 + wig)
        l = np.minimum(o, c) * (1 - wig)
        o, h, l, c = (np.round(x, 2) for x in (o, h, l, c))
        h, l = np.maximum.reduce([h, o, c]), np.minimum.reduce([l, o, c])
        out.append(Session(session_key(day), o, h, l, c, np.full(390, 5000.0)))
        p = float(c[-1])
    return out
