#!/usr/bin/env python3
"""Intraday "noise area" momentum on SPY / QQQ (after Zarattini, Aziz & Barbon, "Beat the Market", 2024).

Rules, evaluated on 1-minute data from the candidate cache's market files:
  * sigma[t] = mean over the previous 14 sessions of |close[t] / open - 1| for minute-of-day t.
  * upper[t] = max(today's open, yesterday's close) * (1 + sigma[t]);
    lower[t] = min(today's open, yesterday's close) * (1 - sigma[t]).
  * Decisions every 30 minutes from 10:00 to 15:30, using the close of the minute before; orders fill at
    that minute's open plus slippage.
  * Flat: close > upper -> long; close < lower -> short.
  * Long: exit when close < max(upper, VWAP); short: exit when close > min(lower, VWAP). After an exit,
    a new position in the other direction can open at the same check if price is beyond that bound.
  * no_churn (default): when an exit and a same-direction re-entry would happen at the same check
    (price beyond the band but on the wrong side of VWAP), the position is simply held, saving fees.
  * All positions close at the 15:55 open (the V1 strategy's end-of-day convention).
Costs: 2 ticks of slippage per fill and 0.005 USD/share per side, on an unlevered position (1x notional).
Returns are in percent of notional per trade and per day.
"""
from __future__ import annotations

import glob
from pathlib import Path

import numpy as np

SLIP = 0.02
COMMISSION = 0.005
LOOKBACK = 14
CHECKS = list(range(30, 390, 30))   # 10:00, 10:30, ..., 15:30 as minute indices from 09:30
EOD = 385


def load_market(cache_dir: str | Path, ticker: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    dk, gr, pc = [], [], []
    for path in sorted(glob.glob(str(Path(cache_dir) / "market_*.npz"))):
        z = np.load(path)
        m = z["tick"] == ticker
        dk.append(z["dkey"][m]); gr.append(z["grid"][m]); pc.append(z["prev_close"][m])
    dkey, grid, prev_close = np.concatenate(dk), np.concatenate(gr).astype(np.float64), np.concatenate(pc)
    order = np.argsort(dkey)
    return dkey[order], grid[order], prev_close[order]


def _ffill(a: np.ndarray) -> np.ndarray:
    idx = np.where(~np.isnan(a), np.arange(len(a)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = a[idx]
    return out


def run(cache_dir: str | Path, ticker: str, start: int, end: int, band_mult: float = 1.0,
        use_vwap: bool = True, take_profit: float | None = None, no_churn: bool = True) -> dict:
    dkey, grid, prev_close = load_market(cache_dir, ticker)
    n = len(dkey)
    opens = grid[:, 0, 0]
    close = np.array([_ffill(grid[i, :, 3]) for i in range(n)])
    move = np.abs(close / opens[:, None] - 1.0)
    trades, day_ret, days = [], [], []
    for i in range(LOOKBACK, n):
        if not (start <= dkey[i] <= end) or np.isnan(opens[i]) or np.isnan(prev_close[i]):
            continue
        sigma = np.nanmean(move[i - LOOKBACK:i], axis=0) * band_mult
        hi_ref, lo_ref = max(opens[i], prev_close[i]), min(opens[i], prev_close[i])
        upper, lower = hi_ref * (1 + sigma), lo_ref * (1 - sigma)
        g = grid[i]
        typical = (g[:, 1] + g[:, 2] + g[:, 3]) / 3
        vol = np.nan_to_num(g[:, 4])
        vwap = np.cumsum(np.nan_to_num(typical) * vol) / np.maximum(np.cumsum(vol), 1e-9)
        c = close[i]
        o = _ffill(g[:, 0])
        pos, entry, total, ent_t = 0, 0.0, 0.0, 0

        def fill(px: float, side: int) -> float:
            return px + side * SLIP

        hi_ = _ffill(g[:, 1]); lo_ = _ffill(g[:, 2])
        prev_t = CHECKS[0]
        for t in CHECKS + [EOD]:
            if take_profit and pos != 0:               # limit target between decisions (no slippage)
                tgt = entry * (1 + pos * take_profit)
                for m in range(prev_t, t):
                    if (pos == 1 and hi_[m] >= tgt) or (pos == -1 and lo_[m] <= tgt):
                        r = (pos * (tgt - entry) - 2 * COMMISSION) / entry
                        trades.append((dkey[i], pos, r, ent_t, m)); total += r; pos = 0
                        break
            prev_t = t
            if t == EOD:
                break
            px_dec, px_exec = c[t - 1], o[t]
            if pos == 1:
                stop = max(upper[t - 1], vwap[t - 1]) if use_vwap else upper[t - 1]
                if px_dec < stop and not (no_churn and px_dec > upper[t - 1]):   # hold instead of exit+re-buy
                    ex = fill(px_exec, -1)
                    r = (ex - entry - 2 * COMMISSION) / entry
                    trades.append((dkey[i], 1, r, ent_t, t)); total += r; pos = 0
            elif pos == -1:
                stop = min(lower[t - 1], vwap[t - 1]) if use_vwap else lower[t - 1]
                if px_dec > stop and not (no_churn and px_dec < lower[t - 1]):   # hold instead of exit+re-sell
                    ex = fill(px_exec, 1)
                    r = (entry - ex - 2 * COMMISSION) / entry
                    trades.append((dkey[i], -1, r, ent_t, t)); total += r; pos = 0
            if pos == 0:
                if px_dec > upper[t - 1]:
                    pos, entry, ent_t = 1, fill(px_exec, 1), t
                elif px_dec < lower[t - 1]:
                    pos, entry, ent_t = -1, fill(px_exec, -1), t
        if pos != 0:
            ex = fill(o[EOD], -pos)
            r = (pos * (ex - entry) - 2 * COMMISSION) / entry
            trades.append((dkey[i], pos, r, ent_t, EOD)); total += r
        day_ret.append(total); days.append(dkey[i])
    return {"trades": trades, "day_ret": np.array(day_ret), "days": np.array(days)}


def summarize(name: str, res: dict) -> str:
    tr = np.array([t[2] for t in res["trades"]])
    dr, days = res["day_ret"], res["days"]
    traded = dr[dr != 0]
    years = days // 10000
    months = days // 100
    by_year = {int(y): 100 * float(dr[years == y].sum()) for y in np.unique(years)}
    m_sum = np.array([dr[months == m].sum() for m in np.unique(months)])
    sharpe = dr.mean() / dr.std() * np.sqrt(252) if dr.std() > 0 else float("nan")
    curve = np.cumsum(dr)
    dd = (curve - np.maximum.accumulate(np.r_[0.0, curve])[1:]).min()
    return (f"{name:<28} trades {len(tr):>4} | trade win {100 * (tr > 0).mean():5.1f}% | avg/trade {100 * tr.mean():+.3f}% "
            f"| traded-day win {100 * (traded > 0).mean():5.1f}% | Sharpe {sharpe:+.2f} | +months {int((m_sum > 0).sum())}/{len(m_sum)} "
            f"| maxDD {100 * dd:.1f}% | by year " + " ".join(f"{y}:{v:+.1f}%" for y, v in by_year.items()))
