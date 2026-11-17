"""NB3 V2 signal engine, streaming (bar-by-bar) form.

This is the exact rule set that produced the verified 675-trade QQQ backtest
(`backtest/intraday_lab.py` noise_break family + `backtest/nb3_trades.py`), re-implemented so it can
run live, one completed 1-minute bar at a time. Every rule below is taken from that source:

  Instrument / data    QQQ regular session, 1-minute bars 09:30-15:59 New York (390 per day).
                       5-minute bar b covers minutes 5b..5b+4; its close is the last known 1-minute
                       close at or before minute 5b+4 (forward-filled inside the day).
  Day open             open of the 09:30 1-minute bar (missing -> no signals that day).
  Noise band           sigma_b = mean over the previous 14 sessions of |close_b / day_open - 1|,
                       ignoring missing values (numpy nanmean over the last 14 session rows,
                       including sessions whose day open was missing, exactly like the grid engine).
  Signal               BUY  when close_b > open x (1 + 1.0 x sigma_b)
                       SELL when close_b < open x (1 - 1.0 x sigma_b)
                       only on 5-minute bars that contain at least one 1-minute bar,
                       only the FIRST signal of the day, only bars whose entry minute
                       (b + 1) x 5 is before minute 330 (last signal bar opens 14:50),
                       only when the previous day's ATR(14) exists.
  Entry                market order at the first available 1-minute open at or after minute
                       (b + 1) x 5 (the next 5-minute bar's open), before minute 385 (15:55).
  Stop / target        0.30 x previous completed daily ATR(14) from the actual fill / 3 x that.
  Exit                 stop, target, or the 15:55 close (minute 384 close).
  Daily ATR(14)        Wilder (RMA), seeded with the mean of the first 14 true ranges; daily
                       high/low/close from the regular-session 1-minute bars.
There are no other filters (no regime, direction, volume or news filter) in NB3 V2.

Optional second trade (Lucid "steady" profile, research round 5; default OFF = NB3 V2 exactly):
  with max_trades_per_day = 2 the engine emits at most two signals a day. After a signal it is blocked
  until `release(exit_minute)` is called (the trade closed, or the signal was not traded); then any
  5-minute bar whose entry minute (b + 1) x 5 is after that exit minute and whose close is outside the
  band is a signal again (backtest/lab4.py bracket with max_trades=2, "pass" signals).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass, field

import numpy as np

MINUTES = 390          # 09:30 .. 15:59
BARS = 78              # 5-minute bars


@dataclass(frozen=True)
class NB3V2Params:
    band_mult: float = 1.0
    stop_atr: float = 0.30
    reward_risk: float = 3.0
    noise_lookback: int = 14
    atr_length: int = 14
    last_entry_minute: int = 330   # entry minute must be < 330 (signal bars opening 09:30..14:50)
    eod_minute: int = 385          # 15:55: flat; exit price = last close at or before minute 384
    max_trades_per_day: int = 1


@dataclass
class Signal:
    session: int              # yyyymmdd (New York)
    bar: int                  # 5-minute bar index 0..77 (bar opening at 09:30 + 5 x bar)
    direction: int            # +1 BUY / -1 SELL
    close: float              # 5-minute close that triggered
    day_open: float
    sigma: float
    upper: float
    lower: float
    atr_prev: float           # previous completed daily ATR(14)
    stop_distance: float      # stop_atr x atr_prev, in signal-instrument price units
    entry_minute: int         # (bar + 1) x 5: first minute the entry may fill

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Session:
    key: int
    atr_prev: float
    o: np.ndarray = field(default_factory=lambda: np.full(MINUTES, np.nan))
    h: np.ndarray = field(default_factory=lambda: np.full(MINUTES, np.nan))
    l: np.ndarray = field(default_factory=lambda: np.full(MINUTES, np.nan))
    c: np.ndarray = field(default_factory=lambda: np.full(MINUTES, np.nan))
    move: np.ndarray = field(default_factory=lambda: np.full(BARS, np.nan))
    last_close: float = math.nan       # forward-filled close
    next_bar: int = 0                  # next 5-minute bar to complete
    fired: int = 0                     # signals emitted today
    blocked: bool = False              # waiting for the last signal's trade to close
    release_min: int = -1              # next signal needs (bar + 1) x 5 > this minute


class NB3V2Engine:
    """Feed sessions in order: begin_session -> on_minute (any order of present minutes, increasing)
    -> complete_bar for every 5-minute bar (on time, even if its minutes are missing) -> end_session.

    `complete_bar` returns a Signal or None. The engine never looks at a minute after the bar it is
    completing, so it cannot use an incomplete 5-minute candle.
    """

    def __init__(self, params: NB3V2Params = NB3V2Params()):
        self.p = params
        self.hist: deque[np.ndarray] = deque(maxlen=params.noise_lookback)
        self.atr: float | None = None
        self._trs: list[float] = []
        self._prev_close = math.nan
        self.s: _Session | None = None
        self.sessions_seen = 0

    # ------------------------------------------------------------------ session lifecycle
    def begin_session(self, key: int) -> None:
        if self.s is not None:
            raise RuntimeError(f"session {self.s.key} not ended before {key}")
        self.s = _Session(key=key, atr_prev=math.nan if self.atr is None else self.atr)

    def on_minute(self, m: int, o: float, h: float, l: float, c: float) -> None:
        s = self._need()
        if not 0 <= m < MINUTES:
            raise ValueError(f"minute index {m} outside the regular session")
        if m < 5 * s.next_bar:
            raise ValueError(f"minute {m} arrived after its 5-minute bar was completed")
        s.o[m], s.h[m], s.l[m], s.c[m] = o, h, l, c

    def complete_bar(self, b: int) -> Signal | None:
        """Close 5-minute bar b. Must be called for b = 0, 1, 2, ... in order."""
        s = self._need()
        if b != s.next_bar:
            raise ValueError(f"bar {b} completed out of order (expected {s.next_bar})")
        s.next_bar += 1
        lo, hi = 5 * b, 5 * b + 5
        seg = s.c[lo:hi]
        has5 = bool((~np.isnan(seg)).any())
        if has5:
            s.last_close = float(seg[~np.isnan(seg)][-1])
        c5 = s.last_close
        day_open = s.o[0]
        with np.errstate(invalid="ignore", divide="ignore"):
            s.move[b] = abs(c5 / day_open - 1)
        if s.fired >= self.p.max_trades_per_day or s.blocked or not has5 or len(self.hist) < self.p.noise_lookback:
            return None
        if (b + 1) * 5 <= s.release_min:
            return None
        if (b + 1) * 5 >= self.p.last_entry_minute or math.isnan(s.atr_prev):
            return None
        sigma = self._sigma(b)
        if math.isnan(sigma) or math.isnan(day_open) or math.isnan(c5):
            return None
        upper = day_open * (1 + self.p.band_mult * sigma)
        lower = day_open * (1 - self.p.band_mult * sigma)
        if c5 > upper:
            direction = 1
        elif c5 < lower:
            direction = -1
        else:
            return None
        s.fired += 1
        s.blocked = True
        return Signal(session=s.key, bar=b, direction=direction, close=c5, day_open=float(day_open),
                      sigma=sigma, upper=upper, lower=lower, atr_prev=s.atr_prev,
                      stop_distance=self.p.stop_atr * s.atr_prev, entry_minute=(b + 1) * 5)

    def release(self, exit_minute: int) -> None:
        """The last signal's trade closed at `exit_minute` (or was not traded): later bars may signal again."""
        s = self._need()
        s.blocked = False
        s.release_min = max(s.release_min, int(exit_minute))

    @property
    def waiting_for_release(self) -> bool:
        return self.s is not None and self.s.blocked and self.s.fired < self.p.max_trades_per_day

    def end_session(self) -> None:
        s = self._need()
        while s.next_bar < BARS:            # bars after the last fed minute still update the history
            self.complete_bar(s.next_bar)
        self.hist.append(s.move.copy())
        self._update_atr(s)
        self.s = None
        self.sessions_seen += 1

    # ------------------------------------------------------------------ helpers
    def _need(self) -> _Session:
        if self.s is None:
            raise RuntimeError("no session open")
        return self.s

    def _sigma(self, b: int) -> float:
        col = np.array([row[b] for row in self.hist], dtype=np.float64)
        ok = ~np.isnan(col)
        if not ok.any():
            return math.nan
        # identical to numpy.nanmean over the (14, 78) history block used by the grid engine
        block = np.vstack(list(self.hist))
        with np.errstate(all="ignore"):
            return float(np.nanmean(block, axis=0)[b])

    def _update_atr(self, s: _Session) -> None:
        with np.errstate(all="ignore"):
            dh, dl = np.nanmax(s.h), np.nanmin(s.l)
        valid = ~np.isnan(s.c)
        dc = s.c[valid][-1] if valid.any() else np.nan
        pcl = self._prev_close
        tr = dh - dl if np.isnan(pcl) else max(dh - dl, abs(dh - pcl), abs(dl - pcl))
        if self.atr is None:
            self._trs.append(tr)
            if len(self._trs) == self.p.atr_length:
                self.atr = float(np.mean(self._trs))
        else:
            self.atr = (self.atr * (self.p.atr_length - 1) + tr) / self.p.atr_length
        self._prev_close = dc

    # ------------------------------------------------------------------ state for restarts / dashboard
    def snapshot(self) -> dict:
        return {"params": asdict(self.p), "hist": [r.tolist() for r in self.hist], "atr": self.atr,
                "trs": list(self._trs), "prev_close": self._prev_close, "sessions_seen": self.sessions_seen}

    @classmethod
    def restore(cls, snap: dict) -> "NB3V2Engine":
        e = cls(NB3V2Params(**snap["params"]))
        for r in snap["hist"]:
            e.hist.append(np.array(r, dtype=np.float64))
        e.atr, e._trs, e._prev_close = snap["atr"], list(snap["trs"]), snap["prev_close"]
        e.sessions_seen = snap["sessions_seen"]
        return e

    def warm(self) -> bool:
        """True once the noise history and the ATR are both available."""
        return len(self.hist) == self.p.noise_lookback and self.atr is not None and not math.isnan(self.atr)
