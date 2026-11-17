#!/usr/bin/env python3
"""Detailed NB3 trade list with intratrade paths, for verification and prop-firm simulation.

Reproduces the NB3 rules exactly as tested in intraday_lab.py (noise_break family, first signal of
the day, bracket stop/target, flat by 15:55) and records, per trade:
  date, direction, signal bar, entry minute and fill, stop distance, exit minute, price and reason,
  net R (after costs) and gross R (no slippage, no commission),
  and the minute-by-minute best and worst unrealised P&L in R (`path_hi`, `path_lo`), capped at the
  exit, so drawdown rules that follow intraday equity can be modelled.

Cost / execution knobs (for stress tests): slippage ticks per market/stop fill, commission per share
per side, entry delay in 5-minute bars, target needing a trade-through of N ticks, missed entries.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday_lab as il  # noqa: E402

EOD = il.EOD_MIN


@dataclass(frozen=True)
class Exec:
    slip_ticks: float = 2.0
    tick: float = 0.01
    commission: float = 0.005        # per share (or per unit of price exposure) per side
    entry_delay_bars: int = 0        # extra 5-minute bars between signal and entry
    target_through_ticks: float = 0  # 0 = limit fills on touch (as tested)
    miss_prob: float = 0.0           # chance an entry order is missed entirely


@dataclass
class Trade:
    dkey: int
    direction: int
    signal_bar: int
    entry_min: int
    fill: float
    dist: float
    exit_min: int
    exit_px: float
    reason: str
    r_net: float
    r_gross: float
    path_hi: np.ndarray = field(repr=False)
    path_lo: np.ndarray = field(repr=False)


def extract(d: dict, band: float = 1.0, stop_atr: float = 0.30, rr: float = 3.0, ex: Exec = Exec(),
            last_entry_min: int = 330, rng: np.random.Generator | None = None,
            sig: np.ndarray | None = None) -> list[Trade]:
    sig = il.signals(d, "noise_break", band) if sig is None else sig
    o, h, l, cf = d["o"], d["h"], d["l"], d["cf"]
    slip = ex.slip_ticks * ex.tick
    out: list[Trade] = []
    for i in range(sig.shape[0]):
        atr = d["atr_prev"][i]
        if np.isnan(atr):
            continue
        bars = np.flatnonzero(sig[i] != 0)
        bars = bars[(bars + 1) * 5 < last_entry_min]
        if len(bars) == 0:
            continue
        b = int(bars[0])
        if rng is not None and ex.miss_prob > 0 and rng.random() < ex.miss_prob:
            continue
        direction = int(sig[i, b])
        em = (b + 1 + ex.entry_delay_bars) * 5
        valid = np.flatnonzero(~np.isnan(o[i, em:EOD]))
        if len(valid) == 0:
            continue
        ei = em + int(valid[0])
        raw_entry = o[i, ei]
        fill = raw_entry + direction * slip
        dist = stop_atr * atr
        stop = fill - direction * dist
        target = fill + direction * rr * dist
        through = ex.target_through_ticks * ex.tick
        exit_min, exit_px, reason, raw_exit = EOD, np.nan, "EOD", np.nan
        his, los = [], []
        for t in range(ei, EOD):
            hh, ll, oo = h[i, t], l[i, t], o[i, t]
            if np.isnan(hh):
                his.append(his[-1] if his else 0.0); los.append(los[-1] if los else 0.0)
                continue
            fav = (hh - fill) if direction > 0 else (fill - ll)
            adv = (ll - fill) if direction > 0 else (fill - hh)
            stop_hit = (ll <= stop) if direction > 0 else (hh >= stop)
            tgt_hit = t > ei and ((hh >= target + through) if direction > 0 else (ll <= target - through))
            if stop_hit:                                   # stop first on ties (conservative)
                gap = t > ei and ((oo <= stop) if direction > 0 else (oo >= stop))
                raw_exit = oo if gap else stop
                exit_px = raw_exit - direction * slip
                exit_min, reason = t, ("STOPGAP" if gap else "STOP")
                his.append(min(fav, rr * dist) / dist); los.append((direction * (exit_px - fill)) / dist)
                break
            if tgt_hit:
                gap = (oo >= target) if direction > 0 else (oo <= target)
                raw_exit = exit_px = oo if gap else target
                exit_min, reason = t, "TARGET"
                his.append(direction * (exit_px - fill) / dist); los.append(max(adv, -dist) / dist)
                break
            his.append(fav / dist); los.append(adv / dist)
        if np.isnan(exit_px):
            raw_exit = cf[i, EOD - 1]
            exit_px = raw_exit - direction * slip
            his.append(max(his[-1] if his else 0.0, direction * (exit_px - fill) / dist))
            los.append(min(los[-1] if los else 0.0, direction * (exit_px - fill) / dist))
        r_net = (direction * (exit_px - fill) - 2 * ex.commission) / dist
        r_gross = direction * (raw_exit - raw_entry) / dist
        out.append(Trade(int(d["dkey"][i]), direction, b, ei, float(fill), float(dist), int(exit_min),
                         float(exit_px), reason, float(r_net), float(r_gross),
                         np.array(his, dtype=np.float32), np.array(los, dtype=np.float32)))
    return out
