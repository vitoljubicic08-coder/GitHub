#!/usr/bin/env python3
"""Round 6: aggressive NB3 trade management for prop accounts (tight stops, pullback limit entries,
stop behind the signal candle, breakeven stop).

`bracket6` generalises lab4.bracket (same fill model, same output fields) with:
  entry   "market": next 5-minute bar's open + slippage (as before)
          "limit":  a limit order `offset` x ATR better than the signal close, working for the next
                    `window` minutes (and never past the last entry minute); it fills only if price
                    trades THROUGH the limit by one tick, at the limit (or at the open if the minute
                    opens beyond it); no slippage on the fill; unfilled = no trade
  stop    float = ATR multiple; "bar" = beyond the signal 5-minute bar's low (long) / high (short)
          + 0.02 ATR, at least 0.05 ATR, skipped if more than 1 ATR away
  be      0 = off; k > 0: once the price has gone k R in favour, the stop moves to the entry price
          from the NEXT minute on (the original stop applies in the trigger minute: conservative)
A stop and the target in the same minute -> stop first. Target never fills in the entry minute.
"""
from __future__ import annotations

import numpy as np

import intraday_lab as il
import lab4

BARS = np.arange(78)


def nb3_signals(d: dict, mt: int) -> np.ndarray:
    return lab4.signals4(d, "nb3", ("none", "first" if mt == 1 else "pass"))[0]


def bracket6(d: dict, sig: np.ndarray, rr: float, stop, entry: str = "market", offset: float = 0.0,
             window: int = 30, be: float = 0.0, max_trades: int = 1, last_entry_min: int = 330,
             eod_min: int = il.EOD_MIN, slip: float = il.SLIP_TICKS * il.TICK, commission: float = il.COMMISSION,
             tick: float | None = None) -> dict:
    o, h, l, cf, c5 = d["o"], d["h"], d["l"], d["cf"], d["c5"]
    atr = d["atr_prev"]
    tick = slip if tick is None else tick
    n = sig.shape[0]
    t = np.arange(390)[None, :]
    entry_min = (BARS + 1) * 5
    acc = {k: [] for k in ("r", "kind", "day", "bar", "dirn", "dist", "lo", "exit")}
    busy = np.full(n, -1)
    for _ in range(max_trades):
        ok = (sig != 0) & (entry_min[None, :] < last_entry_min) & (entry_min[None, :] > busy[:, None])
        first = np.where(ok.any(1), ok.argmax(1), -1)
        sel = np.flatnonzero(first >= 0)
        sel = sel[~np.isnan(atr[sel])]
        if not len(sel):
            break
        b = first[sel]
        dirn = sig[sel, b].astype(float)
        em = (b + 1) * 5
        a = atr[sel]
        hh, ll, oo = h[sel], l[sel], o[sel]
        with np.errstate(invalid="ignore"):
            if entry == "market":
                ei = np.where(~np.isnan(oo) & (t >= em[:, None]), t, 999).min(1)
                fill = oo[np.arange(len(sel)), np.minimum(ei, 389)] + dirn * slip
                good = ei < eod_min
                busy_if_skip = em
            else:
                lim = c5[sel, b] - dirn * offset * a
                end = np.minimum(em + window, last_entry_min)
                inwin = (t >= em[:, None]) & (t < end[:, None])
                through = np.where(dirn[:, None] > 0, ll <= lim[:, None] - tick, hh >= lim[:, None] + tick) & inwin
                ei = np.where(through.any(1), through.argmax(1), 999)
                op = oo[np.arange(len(sel)), np.minimum(ei, 389)]
                better = np.where(dirn > 0, op < lim, op > lim)
                fill = np.where(better & ~np.isnan(op), op, lim)
                good = ei < eod_min
                busy_if_skip = end
            if stop == "bar":
                lv = np.where(dirn > 0, d["l5"][sel, b], d["h5"][sel, b])
                room = dirn * (fill - lv)
                dist = np.maximum(room + lab4.BUF_ATR * a, lab4.MIN_ATR * a)
                good &= (room > 0) & (dist <= lab4.MAX_ATR * a)
            else:
                dist = float(stop) * a
        busy[sel[~good]] = busy_if_skip[~good]
        keep = good
        sel, b, dirn, ei, fill, dist = sel[keep], b[keep], dirn[keep], ei[keep], fill[keep], dist[keep]
        hh, ll, oo = hh[keep], ll[keep], oo[keep]
        if not len(sel):
            continue
        ar = np.arange(len(sel))
        stp = fill - dirn * dist
        tgt = fill + dirn * rr * dist
        live = (t >= ei[:, None]) & (t < eod_min)
        with np.errstate(invalid="ignore"):
            fav_hit = lambda lvl: np.where(dirn[:, None] > 0, hh >= lvl[:, None], ll <= lvl[:, None])  # noqa: E731
            adv_hit = lambda lvl: np.where(dirn[:, None] > 0, ll <= lvl[:, None], hh >= lvl[:, None])  # noqa: E731
            g_hit = fav_hit(tgt) & live & (t > ei[:, None])
            s_orig = adv_hit(stp) & live
            if be > 0:
                trig = fav_hit(fill + dirn * be * dist) & live
                tb = np.where(trig.any(1), trig.argmax(1), 999)
                s_be = adv_hit(fill) & live & (t > tb[:, None])
                s_hit = (s_orig & (t <= tb[:, None])) | s_be
            else:
                tb = np.full(len(sel), 999)
                s_hit = s_orig
        s_i = np.where(s_hit.any(1), s_hit.argmax(1), 999)
        g_i = np.where(g_hit.any(1), g_hit.argmax(1), 999)
        st = (s_i <= g_i) & (s_i < 999)
        tg = ~st & (g_i < 999)
        stop_lvl = np.where(s_i > tb, fill, stp)                 # breakeven level after the trigger
        s_open = oo[ar, np.minimum(s_i, 389)]
        gap = st & (s_i > ei) & np.where(dirn > 0, s_open <= stop_lvl, s_open >= stop_lvl)
        px = np.where(st, np.where(gap, s_open, stop_lvl) - dirn * slip, np.nan)
        g_open = oo[ar, np.minimum(g_i, 389)]
        g_gap = tg & (g_i > ei) & np.where(dirn > 0, g_open >= tgt, g_open <= tgt)
        px = np.where(tg, np.where(g_gap, g_open, tgt), px)
        eod = ~st & ~tg
        px = np.where(eod, cf[sel, eod_min - 1] - dirn * slip, px)
        xm = np.where(st, s_i, np.where(tg, g_i, eod_min))
        r = (dirn * (px - fill) - 2 * commission) / dist
        with np.errstate(invalid="ignore"):
            adv = np.where(dirn[:, None] > 0, ll - fill[:, None], fill[:, None] - hh) / dist[:, None]
            lo = np.nanmin(np.where(live & (t < xm[:, None]), adv, 0.0), 1)
            at_x = adv[ar, np.minimum(xm, 389)]
        r_px = dirn * (px - fill) / dist
        lo = np.minimum(np.minimum(lo, np.where(tg, np.maximum(np.nan_to_num(at_x), -1.0), r_px)), 0.0)
        acc["r"].append(r); acc["kind"].append(np.where(st, 0, np.where(tg, 1, 2)))
        acc["day"].append(sel); acc["bar"].append(b); acc["dirn"].append(dirn)
        acc["dist"].append(dist / atr[sel]); acc["lo"].append(lo); acc["exit"].append(xm)
        busy[sel] = xm
    return {k: (np.concatenate(v) if v else np.array([])) for k, v in acc.items()}
