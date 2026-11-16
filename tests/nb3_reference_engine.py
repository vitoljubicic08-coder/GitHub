"""Bar-by-bar reference model of the NB3 (QQQ noise-band breakout, 1:3) Pine engine on 5-minute bars.

Mirrors the Pine "NB3 SIGNAL ENGINE" block statement by statement. The previous daily ATR(14) is an
input, as in Pine where it comes from request.security(..., ta.atr(14)[1], lookahead_on).
"""
from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
LOOKBACK = 14
BARS_PER_DAY = 78
BAND_MULT = 1.5
STOP_ATR = 0.20
REWARD_RISK = 3.0
OPEN_MOD = 570
SESSION_END_MOD = 960
LAST_SIGNAL_MOD = 890   # last signal bar opens 14:50; its entry fills at the 14:55 open
EOD_SUBMIT_MOD = 950


def _na(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


class Nb3Engine:
    def __init__(self, band_mult: float = BAND_MULT, stop_atr: float = STOP_ATR) -> None:
        self.band_mult = band_mult      # V1: 1.5 / 0.20; V2: 1.0 / 0.30
        self.stop_atr = stop_atr
        self.hist: list[list[float]] = []
        self.sess_date_key: int | None = None
        self.day_open = float("nan")
        self.today = [float("nan")] * BARS_PER_DAY
        self.traded_today = False
        self.sess_atr = float("nan")
        self.stop_dist = float("nan")

    def update(self, t: datetime, o, h, l, c, prev_daily_atr, is_market: bool = True, confirmed: bool = True):
        """Returns (buy_signal, sell_signal) for this bar."""
        ny = t.astimezone(TZ)
        mod = ny.hour * 60 + ny.minute
        date_key = ny.year * 10000 + ny.month * 100 + ny.day
        in_regular = is_market and ny.weekday() <= 4 and OPEN_MOD <= mod < SESSION_END_MOD
        buy = sell = False
        if not (confirmed and in_regular):
            return buy, sell
        if self.sess_date_key is None or date_key != self.sess_date_key:
            if self.sess_date_key is not None and not _na(self.day_open):
                self.hist.append(self.today)
                if len(self.hist) > LOOKBACK:
                    self.hist.pop(0)
            self.sess_date_key = date_key
            self.day_open = o if mod == OPEN_MOD else float("nan")
            self.today = [float("nan")] * BARS_PER_DAY
            self.traded_today = False
            self.sess_atr = prev_daily_atr
        k = (mod - OPEN_MOD) // 5
        if not _na(self.day_open):
            self.today[k] = abs(c / self.day_open - 1)
        if (not self.traded_today and mod <= LAST_SIGNAL_MOD and len(self.hist) == LOOKBACK
                and not _na(self.day_open) and not _na(self.sess_atr) and self.sess_atr > 0):
            col = [row[k] for row in self.hist if not _na(row[k])]
            if col:
                sigma = sum(col) / len(col)
                upper = self.day_open * (1 + self.band_mult * sigma)
                lower = self.day_open * (1 - self.band_mult * sigma)
                if c > upper:
                    buy, self.traded_today = True, True
                elif c < lower:
                    sell, self.traded_today = True, True
                self.stop_dist = self.stop_atr * self.sess_atr
        return buy, sell
