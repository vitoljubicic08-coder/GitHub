#!/usr/bin/env python3
"""Grid tester for intraday arrow strategies with fixed reward:risk brackets.

Signals are evaluated on 5-minute bar closes (what a Pine indicator on a 5-minute chart sees); the
market order fills at the next 5-minute bar's open plus slippage. The trade then has a fixed stop at
`stop_atr` x previous daily ATR(14) and a limit target at RR x that distance, and is closed at the
15:55 open otherwise. Fills are simulated on the 1-minute path (like TradingView's Bar Magnifier);
when the stop and target fall in the same minute the stop is assumed first (conservative).
Costs: 2 ticks of slippage on entry, stop and end-of-day fills (none on the limit target) and
0.005 USD/share per side. Results are in R (net P&L / stop distance).

Signal families (direction: +1 buy / -1 sell):
  vwap_fade k     close beyond VWAP +/- k * volume-weighted std-dev -> fade back toward VWAP
  vwap_break k    same bands, trade in the breakout direction
  noise_fade k    close beyond open*(1 +/- k*sigma_t) (14-day time-of-day noise band) -> fade
  noise_break k   same bands, breakout direction
  orb m           close beyond the first m minutes' high/low -> breakout direction
  orb_fail m      range broken then a close back inside -> trade back into the range
  rsi n lo hi     5-minute RSI(n) <= lo -> buy, >= hi -> sell (intraday, resets daily)
  gap_fade g      |open / prev close - 1| >= g -> at the 09:35 close fade toward the prior close
  vwap_pullback   first-30-minute direction; first touch of VWAP after 10:00 -> trade that direction
"""
from __future__ import annotations

import glob
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SLIP_TICKS = 2
TICK = 0.01
COMMISSION = 0.005
EOD_MIN = 385
RRS = (0.33, 0.5, 1.0, 2.0, 3.0)


# ----------------------------------------------------------------------------
# Data and features
# ----------------------------------------------------------------------------
def _ffill_rows(a: np.ndarray) -> np.ndarray:
    idx = np.where(~np.isnan(a), np.arange(a.shape[1])[None, :], 0)
    np.maximum.accumulate(idx, axis=1, out=idx)
    return np.take_along_axis(a, idx, axis=1)


def load_instrument(cache_dir: str | Path, ticker: str) -> dict:
    dk, gr, pc = [], [], []
    for path in sorted(glob.glob(str(Path(cache_dir) / "market_*.npz"))):
        z = np.load(path)
        m = z["tick"] == ticker
        dk.append(z["dkey"][m]); gr.append(z["grid"][m]); pc.append(z["prev_close"][m])
    dkey = np.concatenate(dk)
    order = np.argsort(dkey)
    grid = np.concatenate(gr)[order].astype(np.float64)
    o, h, l, c, v = (grid[:, :, i] for i in range(5))
    v = np.nan_to_num(v)
    cf = _ffill_rows(c)
    n = len(dkey)
    # 5-minute bars
    sh = (n, 78, 5)
    with np.errstate(all="ignore"):
        h5 = np.nanmax(h.reshape(sh), axis=2)
        l5 = np.nanmin(l.reshape(sh), axis=2)
    c5 = cf[:, 4::5]                                  # close at each bar end (forward-filled)
    o5 = np.full((n, 78), np.nan)
    for j in range(4, -1, -1):                        # first valid open in each 5-minute bar
        col = o.reshape(sh)[:, :, j]
        o5 = np.where(~np.isnan(col), col, o5)
    v5 = v.reshape(sh).sum(axis=2)
    has5 = ~np.isnan(c.reshape(sh)).all(axis=2)
    day_open = o[:, 0]
    # VWAP and volume-weighted std-dev at each bar end
    tp = (np.nan_to_num(h) + np.nan_to_num(l) + np.nan_to_num(cf)) / 3
    cv = np.cumsum(v, axis=1)
    with np.errstate(all="ignore"):
        vwap = np.cumsum(tp * v, axis=1) / cv
        var = np.cumsum(v * tp * tp, axis=1) / cv - vwap ** 2
    vsd = np.sqrt(np.clip(var, 0, None))
    vwap5, vsd5 = vwap[:, 4::5], vsd[:, 4::5]
    # 14-day time-of-day noise sigma (previous sessions only)
    move = np.abs(c5 / day_open[:, None] - 1)
    sig5 = np.full_like(move, np.nan)
    for i in range(14, n):
        sig5[i] = np.nanmean(move[i - 14:i], axis=0)
    # previous-day ATR(14), Wilder
    with np.errstate(all="ignore"):
        dh, dl = np.nanmax(h, axis=1), np.nanmin(l, axis=1)
    dc = np.array([row[~np.isnan(row)][-1] if (~np.isnan(row)).any() else np.nan for row in c])
    atr_prev = np.full(n, np.nan)
    atr, trs = None, []
    for i in range(n):
        atr_prev[i] = np.nan if atr is None else atr
        pcl = dc[i - 1] if i > 0 else np.nan
        tr = dh[i] - dl[i] if np.isnan(pcl) else max(dh[i] - dl[i], abs(dh[i] - pcl), abs(dl[i] - pcl))
        if atr is None:
            trs.append(tr)
            if len(trs) == 14:
                atr = float(np.mean(trs))
        else:
            atr = (atr * 13 + tr) / 14
    prev_high = np.r_[np.nan, dh[:-1]]
    prev_low = np.r_[np.nan, dl[:-1]]
    return {"ticker": ticker, "dkey": dkey, "o": o, "h": h, "l": l, "cf": cf, "c5": c5, "h5": h5, "l5": l5,
            "o5": o5, "v5": v5, "prev_high": prev_high, "prev_low": prev_low,
            "has5": has5, "day_open": day_open, "prev_close": np.concatenate(pc)[order], "vwap5": vwap5,
            "vsd5": vsd5, "sig5": sig5, "atr_prev": atr_prev}


def _rsi(c5: np.ndarray, n: int) -> np.ndarray:
    d = np.diff(c5, axis=1, prepend=np.nan)
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    out = np.full_like(c5, np.nan)
    au = np.full(c5.shape[0], np.nan); ad = np.full(c5.shape[0], np.nan)
    for b in range(1, c5.shape[1]):
        if b == n:
            au = np.nanmean(up[:, 1:n + 1], axis=1); ad = np.nanmean(dn[:, 1:n + 1], axis=1)
        elif b > n:
            au = (au * (n - 1) + np.nan_to_num(up[:, b])) / n
            ad = (ad * (n - 1) + np.nan_to_num(dn[:, b])) / n
        if b >= n:
            with np.errstate(all="ignore"):
                out[:, b] = 100 - 100 / (1 + au / ad)
    return out


# ----------------------------------------------------------------------------
# Signals: (n_days, 78) arrays of -1/0/+1 at 5-minute bar closes
# ----------------------------------------------------------------------------
def signals(d: dict, family: str, p: float | tuple) -> np.ndarray:
    c5, n = d["c5"], d["c5"].shape[0]
    sig = np.zeros(c5.shape, dtype=np.int8)
    with np.errstate(all="ignore"):
        if family in ("vwap_fade", "vwap_break"):
            up = c5 > d["vwap5"] + p * d["vsd5"]
            dn = c5 < d["vwap5"] - p * d["vsd5"]
            sig[up], sig[dn] = -1, 1
            sig[:, :3] = 0                                   # bands need a few bars to form
        elif family in ("noise_fade", "noise_break"):
            up = c5 > d["day_open"][:, None] * (1 + p * d["sig5"])
            dn = c5 < d["day_open"][:, None] * (1 - p * d["sig5"])
            sig[up], sig[dn] = -1, 1
        elif family in ("orb", "orb_fail"):
            k = int(p) // 5
            hi = np.nanmax(d["h5"][:, :k], axis=1)[:, None]
            lo = np.nanmin(d["l5"][:, :k], axis=1)[:, None]
            if family == "orb":
                sig[c5 > hi], sig[c5 < lo] = 1, -1
            else:
                broke_up = np.maximum.accumulate(d["h5"] > hi, axis=1)
                broke_dn = np.maximum.accumulate(d["l5"] < lo, axis=1)
                sig[broke_up & (c5 < hi)], sig[broke_dn & (c5 > lo)] = -1, 1
            sig[:, :k] = 0
        elif family == "rsi":
            length, lo_t, hi_t = p
            r = _rsi(c5, length)
            sig[r <= lo_t], sig[r >= hi_t] = 1, -1
        elif family == "gap_fade":
            gap = d["day_open"] / d["prev_close"] - 1
            sig[:, 0] = np.where(gap >= p, -1, np.where(gap <= -p, 1, 0))
        elif family == "pd_sweep":                       # ICT liquidity sweep of prior-day high/low -> fade
            ph, pl = d["prev_high"][:, None], d["prev_low"][:, None]
            swept_up = np.maximum.accumulate(d["h5"] > ph, axis=1)
            swept_dn = np.maximum.accumulate(d["l5"] < pl, axis=1)
            sig[swept_up & (c5 < ph)] = -1
            sig[swept_dn & (c5 > pl)] = 1
        elif family == "pd_break":                       # close beyond prior-day high/low -> continuation
            sig[c5 > d["prev_high"][:, None]] = 1
            sig[c5 < d["prev_low"][:, None]] = -1
        elif family in ("fvg", "fvg_sb"):                # ICT fair value gap: displacement gap, then retrace into it
            o5, h5, l5 = d["o5"], d["h5"], d["l5"]
            rng5 = h5 - l5
            gdir = np.zeros(n); gtop = np.full(n, np.nan); gbot = np.full(n, np.nan)
            lo_b, hi_b = (6, 18) if family == "fvg_sb" else (2, 78)    # 10:00-11:00 window for "silver bullet"
            for b in range(2, 78):
                in_win = lo_b <= b < hi_b
                # entries: retrace into the most recent unfilled gap, closing back on its far side
                long_e = (gdir > 0) & (l5[:, b] <= gtop) & (c5[:, b] >= gbot)
                short_e = (gdir < 0) & (h5[:, b] >= gbot) & (c5[:, b] <= gtop)
                if in_win:
                    sig[long_e, b], sig[short_e, b] = 1, -1
                gdir[long_e | short_e] = 0
                # formation at bar b (displacement candle b-1 >= p x average range so far)
                avg = np.nanmean(rng5[:, :b], axis=1)
                disp = rng5[:, b - 1] >= p * avg
                bull = disp & (l5[:, b] > h5[:, b - 2]) & (c5[:, b - 1] > o5[:, b - 1])
                bear = disp & (h5[:, b] < l5[:, b - 2]) & (c5[:, b - 1] < o5[:, b - 1])
                if in_win:
                    gdir = np.where(bull, 1, np.where(bear, -1, gdir))
                    gtop = np.where(bull, l5[:, b], np.where(bear, l5[:, b - 2], gtop))
                    gbot = np.where(bull, h5[:, b - 2], np.where(bear, h5[:, b], gbot))
        elif family == "delta_div":                      # order-flow proxy: new high/low without delta confirmation
            h5, l5 = d["h5"], d["l5"]
            rng5 = h5 - l5
            clv = np.where(rng5 > 0, (2 * c5 - h5 - l5) / rng5, 0.0)
            cd = np.cumsum(np.nan_to_num(d["v5"] * clv), axis=1)
            cd_max, cd_min = np.maximum.accumulate(cd, axis=1), np.minimum.accumulate(cd, axis=1)
            cd_rng = cd_max - cd_min
            c_max = np.fmax.accumulate(c5, axis=1)
            c_min = np.fmin.accumulate(c5, axis=1)
            sig[(c5 >= c_max) & (cd < cd_max - p * cd_rng)] = -1
            sig[(c5 <= c_min) & (cd > cd_min + p * cd_rng)] = 1
            sig[:, :6] = 0
        elif family == "vwap_pullback":
            trend = np.sign(c5[:, 5] - d["day_open"])[:, None]   # direction at 10:00
            touch_long = (trend > 0) & (d["l5"] <= d["vwap5"])
            touch_short = (trend < 0) & (d["h5"] >= d["vwap5"])
            sig[touch_long], sig[touch_short] = 1, -1
            sig[:, :6] = 0
    if family.endswith("_break"):
        sig = -sig
    sig[~d["has5"]] = 0
    return sig


# ----------------------------------------------------------------------------
# Bracket outcomes for every reward:risk at once
# ----------------------------------------------------------------------------
def subset(d: dict, start: int, end: int) -> dict:
    """Days with start <= dkey <= end (features were computed on the full history first)."""
    m = (d["dkey"] >= start) & (d["dkey"] <= end)
    return {k: (v[m] if isinstance(v, np.ndarray) and v.shape[:1] == m.shape else v) for k, v in d.items()}


def trades(d: dict, sig: np.ndarray, stop_atr: float, max_trades: int = 1,
           last_entry_min: int = 330) -> dict:
    """Up to `max_trades` sequential trades per day; returns {RR: (R array, dkey array)}."""
    n = sig.shape[0]
    o, h, l, cf = d["o"], d["h"], d["l"], d["cf"]
    slip = SLIP_TICKS * TICK
    out = {rr: [] for rr in RRS}
    days = {rr: [] for rr in RRS}
    for rr_i, rr in enumerate(RRS):
        busy_until = np.full(n, -1)                 # minute after which a new signal may enter
        for _ in range(max_trades):
            bars = np.arange(78)[None, :]
            entry_min = (bars + 1) * 5
            ok = (sig != 0) & (entry_min < last_entry_min) & (entry_min > busy_until[:, None])
            first = np.where(ok.any(1), ok.argmax(1), -1)
            sel = np.flatnonzero(first >= 0)
            sel = sel[~np.isnan(d["atr_prev"][sel])]
            if len(sel) == 0:
                break
            b = first[sel]
            dirn = sig[sel, b].astype(float)
            em = (b + 1) * 5
            op = o[sel]
            # first valid open at or after the entry minute
            valid = ~np.isnan(op)
            cand = np.where(valid & (np.arange(390)[None, :] >= em[:, None]), np.arange(390)[None, :], 999)
            ei = cand.min(1)
            good = ei < EOD_MIN
            sel, b, dirn, ei = sel[good], b[good], dirn[good], ei[good]
            if len(sel) == 0:
                break
            fill = o[sel, ei] + dirn * slip
            dist = stop_atr * d["atr_prev"][sel]
            stop = fill - dirn * dist
            target = fill + dirn * rr * dist
            t = np.arange(390)[None, :]
            live = (t >= ei[:, None]) & (t < EOD_MIN)
            hh, ll, oo = h[sel], l[sel], o[sel]
            stop_hit = np.where(dirn[:, None] > 0, ll <= stop[:, None], hh >= stop[:, None]) & live
            tgt_hit = np.where(dirn[:, None] > 0, hh >= target[:, None], ll <= target[:, None]) & live & (t > ei[:, None])
            s_i = np.where(stop_hit.any(1), stop_hit.argmax(1), 999)
            g_i = np.where(tgt_hit.any(1), tgt_hit.argmax(1), 999)
            ar = np.arange(len(sel))
            exit_px = np.full(len(sel), np.nan)
            exit_min = np.full(len(sel), EOD_MIN)
            st = s_i <= g_i
            s_open = oo[ar, np.minimum(s_i, 389)]
            gap = st & (s_i < 999) & (s_i > ei) & np.where(dirn > 0, s_open <= stop, s_open >= stop)
            px_stop = np.where(gap, s_open, stop) - dirn * slip
            exit_px = np.where(st & (s_i < 999), px_stop, exit_px)
            exit_min = np.where(st & (s_i < 999), s_i, exit_min)
            tg = ~st & (g_i < 999)
            g_open = oo[ar, np.minimum(g_i, 389)]
            px_tgt = np.where(np.where(dirn > 0, g_open >= target, g_open <= target) & (g_i > ei), g_open, target)
            exit_px = np.where(tg, px_tgt, exit_px)
            exit_min = np.where(tg, g_i, exit_min)
            eod = np.isnan(exit_px)
            eod_px = cf[sel, EOD_MIN - 1] - dirn * slip     # 15:55 open ~ last close before it
            exit_px = np.where(eod, eod_px, exit_px)
            r = (dirn * (exit_px - fill) - 2 * COMMISSION) / dist
            out[rr].append(r)
            days[rr].append(d["dkey"][sel])
            busy_until[sel] = exit_min
    return {rr: (np.concatenate(out[rr]) if out[rr] else np.array([]),
                 np.concatenate(days[rr]) if days[rr] else np.array([], dtype=np.int64)) for rr in RRS}


def stats(r: np.ndarray, dkeys: np.ndarray) -> dict:
    if len(r) == 0:
        return {"n": 0}
    wins, losses = r[r > 0], -r[r <= 0]
    years = dkeys // 10000
    months = dkeys // 100
    m_sum = np.array([r[months == m].sum() for m in np.unique(months)])
    return {"n": int(len(r)), "win": float(100 * (r > 0).mean()), "avg": float(r.mean()),
            "pf": float(wins.sum() / losses.sum()) if losses.sum() > 0 else float("inf"),
            "by_year": {int(y): float(r[years == y].sum()) for y in np.unique(years)},
            "pos_months": int((m_sum > 0).sum()), "months": int(len(m_sum))}
