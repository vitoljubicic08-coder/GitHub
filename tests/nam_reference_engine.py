"""Bar-by-bar reference model of the NAM (noise-area momentum) Pine engine on 5-minute bars.

Mirrors the Pine "NAM SIGNAL ENGINE" block statement by statement (same state, same update order),
so it can be checked against the research simulator in backtest/index_momentum.py.
"""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
LOOKBACK = 14
BARS_PER_DAY = 78
OPEN_MOD = 570          # 09:30
SESSION_END_MOD = 960   # 16:00
FIRST_CHECK_MOD = 600   # first decision at the close of the bar ending 10:00
LAST_CHECK_MOD = 930    # last decision at the close of the bar ending 15:30
EOD_SUBMIT_MOD = 950    # the 15:50 bar: flatten at the next open (15:55)


def _na(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


class NamEngine:
    def __init__(self) -> None:
        self.hist: list[list[float]] = []      # completed sessions' |close/open - 1| per bar index
        self.sess_date_key: int | None = None
        self.day_open = float("nan")
        self.prev_close = float("nan")
        self.last_rth_close = float("nan")
        self.today = [float("nan")] * BARS_PER_DAY
        self.cum_pv = 0.0
        self.cum_v = 0.0
        self.pos = 0

    def update(self, t: datetime, o, h, l, c, v, is_market: bool = True, confirmed: bool = True):
        """Returns (long_entry, short_entry, exit_signal, eod_exit) for this confirmed bar."""
        ny = t.astimezone(TZ)
        mod = ny.hour * 60 + ny.minute
        date_key = ny.year * 10000 + ny.month * 100 + ny.day
        in_regular = is_market and ny.weekday() <= 4 and OPEN_MOD <= mod < SESSION_END_MOD
        long_e = short_e = exit_s = eod = False
        if not (confirmed and in_regular):
            return long_e, short_e, exit_s, eod

        if self.sess_date_key is None or date_key != self.sess_date_key:
            if self.sess_date_key is not None:
                if not _na(self.day_open):
                    self.hist.append(self.today)
                    if len(self.hist) > LOOKBACK:
                        self.hist.pop(0)
                self.prev_close = self.last_rth_close
            self.sess_date_key = date_key
            self.day_open = o if mod == OPEN_MOD else float("nan")
            self.today = [float("nan")] * BARS_PER_DAY
            self.cum_pv = 0.0
            self.cum_v = 0.0
            self.pos = 0

        self.last_rth_close = c
        vol = 0.0 if _na(v) else v
        self.cum_pv += (h + l + c) / 3 * vol
        self.cum_v += vol
        vwap = self.cum_pv / self.cum_v if self.cum_v > 0 else float("nan")
        k = (mod - OPEN_MOD) // 5
        if not _na(self.day_open):
            self.today[k] = abs(c / self.day_open - 1)

        close_mod = mod + 5
        is_check = close_mod % 30 == 0 and FIRST_CHECK_MOD <= close_mod <= LAST_CHECK_MOD
        if is_check and len(self.hist) == LOOKBACK and not _na(self.day_open) and not _na(self.prev_close):
            col = [row[k] for row in self.hist if not _na(row[k])]
            if col:
                sigma = sum(col) / len(col)
                upper = max(self.day_open, self.prev_close) * (1 + sigma)
                lower = min(self.day_open, self.prev_close) * (1 - sigma)
                if self.pos == 1:
                    stop = upper if _na(vwap) else max(upper, vwap)
                    if c < stop and not c > upper:
                        exit_s, self.pos = True, 0
                elif self.pos == -1:
                    stop = lower if _na(vwap) else min(lower, vwap)
                    if c > stop and not c < lower:
                        exit_s, self.pos = True, 0
                if self.pos == 0:
                    if c > upper:
                        long_e, self.pos = True, 1
                    elif c < lower:
                        short_e, self.pos = True, -1

        if mod == EOD_SUBMIT_MOD and self.pos != 0:
            eod, self.pos = True, 0
        return long_e, short_e, exit_s, eod
