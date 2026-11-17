"""Bracket-order fill model: the exact execution assumptions of the verified backtest.

Used by the historical replay (to reproduce the 675 trades) and by the paper broker (on MNQ prices).
Rules, from `backtest/nb3_trades.py`:
  * entry  = first available 1-minute open at/after the entry minute, +/- slippage (market order);
  * stop   = fill -/+ stop distance; target = fill +/- reward_risk x stop distance (limit order);
  * minute by minute: the stop is checked first (if both are touched in one minute the stop wins);
    a stop touched in a later minute whose open is already beyond it fills at that open (gap);
    the target cannot fill in the entry minute; a target gapped through fills at the open;
  * stop and end-of-day fills pay slippage; the target (limit) does not;
  * end of day: exit at the last close at or before minute 384 (the 15:55 open), minus slippage.
Stops are stop-MARKET orders: they do not guarantee the stop price in gaps or fast markets.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class BracketResult:
    exit_minute: int
    exit_price: float        # after slippage
    raw_exit: float          # before slippage
    reason: str              # STOP | STOPGAP | TARGET | EOD


class BracketSim:
    def __init__(self, direction: int, raw_entry: float, entry_minute: int, stop_distance: float,
                 reward_risk: float, slip: float, target_through: float = 0.0,
                 target_distance: float | None = None):
        self.dir = direction
        self.raw_entry = raw_entry
        self.fill = raw_entry + direction * slip
        self.ei = entry_minute
        self.dist = stop_distance
        self.stop = self.fill - direction * stop_distance
        tdist = reward_risk * stop_distance if target_distance is None else target_distance
        self.target = self.fill + direction * tdist
        self.slip = slip
        self.through = target_through
        self.best = 0.0               # best unrealised move in price units (for intraday trailing)
        self.worst = 0.0
        self.result: BracketResult | None = None

    def on_minute(self, t: int, o: float, h: float, l: float) -> BracketResult | None:
        """Process minute t (t >= entry minute). Returns the result when the trade closes."""
        if self.result is not None or math.isnan(h):
            return self.result
        d = self.dir
        fav = (h - self.fill) if d > 0 else (self.fill - l)
        adv = (l - self.fill) if d > 0 else (self.fill - h)
        stop_hit = (l <= self.stop) if d > 0 else (h >= self.stop)
        tgt_hit = t > self.ei and ((h >= self.target + self.through) if d > 0 else (l <= self.target - self.through))
        if stop_hit:
            gap = t > self.ei and ((o <= self.stop) if d > 0 else (o >= self.stop))
            raw = o if gap else self.stop
            self.best = max(self.best, fav)
            self.result = BracketResult(t, raw - d * self.slip, raw, "STOPGAP" if gap else "STOP")
            self.worst = min(self.worst, d * (self.result.exit_price - self.fill))
            return self.result
        if tgt_hit:
            gap = (o >= self.target) if d > 0 else (o <= self.target)
            raw = o if gap else self.target
            self.result = BracketResult(t, raw, raw, "TARGET")
            self.best = max(self.best, d * (raw - self.fill))
            self.worst = min(self.worst, max(adv, -self.dist))
            return self.result
        self.best, self.worst = max(self.best, fav), min(self.worst, adv)
        return None

    def end_of_day(self, eod_minute: int, last_close: float) -> BracketResult:
        if self.result is None:
            self.result = BracketResult(eod_minute, last_close - self.dir * self.slip, last_close, "EOD")
        return self.result

    def r_multiple(self, commission_per_unit: float = 0.0) -> tuple[float, float]:
        """(net R after slippage and commission, gross R before both)."""
        r = self.result
        if r is None:
            raise RuntimeError("trade still open")
        net = (self.dir * (r.exit_price - self.fill) - 2 * commission_per_unit) / self.dist
        gross = self.dir * (r.raw_exit - self.raw_entry) / self.dist
        return net, gross
