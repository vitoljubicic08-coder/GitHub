#!/usr/bin/env python3
"""Round 8 lab: outside data (dealer gamma, VIX, FOMC days), order-flow proxies, standard deviations and
ICT OTE entries, all as additions to the NB3 signal on QQQ executed as MNQ (SHORTLIST_8.md).

Everything that filters a day uses only information known before the session opens (previous day's
GEX / VIX close; the FOMC calendar is published in advance). Bar filters use only the signal bar and
earlier bars of the same session.

Order flow: the dataset has 1-minute OHLCV, no bid/ask. "Delta" is the usual bar proxy:
volume x close-location value, CLV = (2 close - high - low) / (high - low), on 5-minute bars.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

import intraday_lab as il
import lab6
import prop_sim as ps

BARS = np.arange(78)
COMM_RT = 1.50
USD_PER_QQQ = ps.K * ps.PT
HERE = Path(__file__).resolve().parent


# ----------------------------------------------------------------------------- outside data
def _read_dates_values(path: Path, date_col: str, val_col: str):
    dk, v = [], []
    with open(path) as fh:
        for r in csv.DictReader(fh):
            s = r[date_col][:10].replace("-", "")
            try:
                v.append(float(r[val_col])); dk.append(int(s))
            except ValueError:
                continue
    o = np.argsort(dk)
    return np.array(dk)[o], np.array(v)[o]


def load_external(ext_dir: str | Path) -> dict:
    ext = Path(ext_dir)
    gd, gex = _read_dates_values(ext / "DIX.csv", "date", "gex")
    vd, vix = _read_dates_values(ext / "VIX.csv", "Date", "Close")
    v3d, vix3m = _read_dates_values(ext / "VIX3M.csv", "Date", "Close")
    with open(HERE / "data_round8" / "fomc_statement_dates.csv") as fh:
        fomc = {int(r["date"]) for r in csv.DictReader(fh)}
    return {"gex": (gd, gex), "vix": (vd, vix), "vix3m": (v3d, vix3m), "fomc": fomc}


def prev_values(dkeys: np.ndarray, dates: np.ndarray, values: np.ndarray) -> np.ndarray:
    """Value of the last date strictly before each session (known at the open)."""
    pos = np.searchsorted(dates, dkeys, side="left") - 1
    return np.where(pos >= 0, values[np.maximum(pos, 0)], np.nan)


def trailing_rank(dates: np.ndarray, values: np.ndarray, window: int = 252) -> np.ndarray:
    """Percentile of each value within the previous `window` values (inclusive of itself)."""
    out = np.full(len(values), np.nan)
    for i in range(window, len(values)):
        w = values[i - window:i + 1]
        out[i] = (w < values[i]).mean()
    return out


def day_features(d: dict, ext: dict) -> dict:
    dk = d["dkey"]
    gd, gex = ext["gex"]
    vd, vix = ext["vix"]
    v3d, v3 = ext["vix3m"]
    vmed = np.array([np.median(vix[max(0, i - 252):i + 1]) for i in range(len(vix))])
    pos = np.searchsorted(v3d, vd)                    # VIX3M close of the same date as each VIX close
    same = (pos < len(v3d)) & (v3d[np.minimum(pos, len(v3d) - 1)] == vd)
    v3_on_v = np.where(same, v3[np.minimum(pos, len(v3) - 1)], np.nan)
    dc = d["cf"][:, -1]
    trend = np.full(len(dk), np.nan)                  # yesterday's close vs the 20 closes before today
    for i in range(21, len(dk)):
        trend[i] = dc[i - 1] / np.nanmean(dc[i - 20:i]) - 1
    return {"gex_prev": prev_values(dk, gd, gex), "gex_rank_prev": prev_values(dk, gd, trailing_rank(gd, gex)),
            "vix_prev": prev_values(dk, vd, vix), "vix_rel_prev": prev_values(dk, vd, vix / vmed),
            "vix_ratio_prev": prev_values(dk, vd, vix / v3_on_v), "fomc": np.isin(dk, list(ext["fomc"])),
            "trend_prev": trend}


def bar_features(d: dict) -> dict:
    h5, l5, c5, v5 = d["h5"], d["l5"], d["c5"], d["v5"]
    n = len(d["dkey"])
    with np.errstate(all="ignore"):
        rng = h5 - l5
        clv = np.where(rng > 0, (2 * c5 - h5 - l5) / rng, 0.0)
        delta = np.nan_to_num(v5 * clv)
        cumd = np.cumsum(delta, 1)
        rvol = np.full(v5.shape, np.nan)
        for i in range(14, n):
            rvol[i] = v5[i] / np.mean(v5[i - 14:i], 0)
        cmax, cmin = np.fmax.accumulate(c5, 1), np.fmin.accumulate(c5, 1)
        dmax, dmin = np.maximum.accumulate(cumd, 1), np.minimum.accumulate(cumd, 1)
        drng = dmax - dmin
        div_long = (c5 >= cmax) & (cumd < dmax - 0.25 * drng)      # new high, delta lagging
        div_short = (c5 <= cmin) & (cumd > dmin + 0.25 * drng)
        vz = (c5 - d["vwap5"]) / d["vsd5"]
    return {"clv": clv, "cumd": cumd, "rvol": rvol, "div_long": div_long, "div_short": div_short, "vwap_z": vz}


# ----------------------------------------------------------------------------- filters (keep masks)
def filters(d: dict, F: dict) -> dict:
    """name -> (keep_long, keep_short), each (n, 78) bool; True = the signal may be traded."""
    n = len(d["dkey"])
    one = np.ones((n, 78), bool)

    def day(mask):
        m = np.broadcast_to(np.asarray(mask, bool)[:, None], (n, 78))
        return m, m

    with np.errstate(invalid="ignore"):
        gap = np.sign(d["day_open"] / d["prev_close"] - 1)[:, None]
        trend = np.sign(F["trend_prev"])[:, None]
        out = {
            "gex_below_median": day(F["gex_rank_prev"] < 0.5),
            "gex_bottom_third": day(F["gex_rank_prev"] < 1 / 3),
            "gex_negative": day(F["gex_prev"] < 0),
            "vix_ge_20": day(F["vix_prev"] >= 20),
            "vix_above_median": day(F["vix_rel_prev"] > 1),
            "vix_backwardation": day(F["vix_ratio_prev"] >= 1.0),
            "vix_ratio_ge_0p9": day(F["vix_ratio_prev"] >= 0.9),
            "skip_fomc": day(~F["fomc"]),
            "only_fomc": day(F["fomc"]),
            "rvol_ge_1p5": (F["rvol"] >= 1.5, F["rvol"] >= 1.5),
            "rvol_ge_1": (F["rvol"] >= 1.0, F["rvol"] >= 1.0),
            "clv_strong": (F["clv"] >= 0.2, F["clv"] <= -0.2),
            "delta_agrees": (F["cumd"] > 0, F["cumd"] < 0),
            "no_delta_divergence": (~F["div_long"], ~F["div_short"]),
            "vwap_not_extended": (F["vwap_z"] <= 2, F["vwap_z"] >= -2),
            "vwap_confirmed": (F["vwap_z"] >= 1, F["vwap_z"] <= -1),
            "gap_with": (np.broadcast_to(gap > 0, (n, 78)), np.broadcast_to(gap < 0, (n, 78))),
            "gap_against": (np.broadcast_to(gap < 0, (n, 78)), np.broadcast_to(gap > 0, (n, 78))),
            "trend_with": (np.broadcast_to(trend > 0, (n, 78)), np.broadcast_to(trend < 0, (n, 78))),
            "early": (one & (BARS[None, :] <= 12), one & (BARS[None, :] <= 12)),
            "late": (one & (BARS[None, :] > 12), one & (BARS[None, :] > 12)),
        }
    return out


def apply_filter(sig: np.ndarray, keep) -> np.ndarray:
    kl, ks = keep
    return np.where((sig > 0) & kl | (sig < 0) & ks, sig, 0).astype(np.int8)


# ----------------------------------------------------------------------------- entry / exit variants
def bracket8(d: dict, sig: np.ndarray, rr: float = 1.5, stop_atr: float = 0.3, lim=None, stp_lvl=None, tgt_lvl=None,
             window: int = 60, rr_floor: float = 1.0, rr_cap: float = 4.0, max_trades: int = 2,
             last_entry_min: int = 330, eod_min: int = il.EOD_MIN, slip: float = ps.MNQ_TICK_Q,
             tick: float = ps.MNQ_TICK_Q) -> dict:
    """lab6.bracket6 generalised: optional per-signal limit entry price, stop price and target price."""
    o, h, l, cf = d["o"], d["h"], d["l"], d["cf"]
    atr = d["atr_prev"]
    n = sig.shape[0]
    t = np.arange(390)[None, :]
    entry_min = (BARS + 1) * 5
    acc = {k: [] for k in ("r", "kind", "day", "bar", "dirn", "dist", "lo", "exit")}
    busy = np.full(n, -1)
    nan78 = np.full(sig.shape, np.nan)
    lim = nan78 if lim is None else lim
    stp_lvl = nan78 if stp_lvl is None else stp_lvl
    tgt_lvl = nan78 if tgt_lvl is None else tgt_lvl
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
        oo, hh, ll = o[sel], h[sel], l[sel]
        ar = np.arange(len(sel))
        L, S, T = lim[sel, b], stp_lvl[sel, b], tgt_lvl[sel, b]
        is_lim = ~np.isnan(L)
        with np.errstate(invalid="ignore"):
            ei_m = np.where(~np.isnan(oo) & (t >= em[:, None]), t, 999).min(1)
            fill_m = oo[ar, np.minimum(ei_m, 389)] + dirn * slip
            end = np.minimum(em + window, last_entry_min)
            inwin = (t >= em[:, None]) & (t < end[:, None])
            through = np.where(dirn[:, None] > 0, ll <= L[:, None] - tick, hh >= L[:, None] + tick) & inwin
            ei_l = np.where(through.any(1), through.argmax(1), 999)
            op = oo[ar, np.minimum(ei_l, 389)]
            fill_l = np.where(np.where(dirn > 0, op < L, op > L) & ~np.isnan(op), op, L)
            ei = np.where(is_lim, ei_l, ei_m)
            fill = np.where(is_lim, fill_l, fill_m)
            dist = np.where(~np.isnan(S), dirn * (fill - S), stop_atr * a)
            good = (ei < eod_min) & (dist >= 0.05 * a) & (dist <= 1.0 * a)
            tdist = np.where(~np.isnan(T), np.clip(dirn * (T - fill), rr_floor * dist, rr_cap * dist), rr * dist)
        busy[sel[~good]] = np.where(is_lim, end, em)[~good]
        sel, b, dirn, ei, fill, dist, tdist = sel[good], b[good], dirn[good], ei[good], fill[good], dist[good], tdist[good]
        oo, hh, ll = oo[good], hh[good], ll[good]
        if not len(sel):
            continue
        ar = np.arange(len(sel))
        stp, tgt = fill - dirn * dist, fill + dirn * tdist
        live = (t >= ei[:, None]) & (t < eod_min)
        with np.errstate(invalid="ignore"):
            s_hit = np.where(dirn[:, None] > 0, ll <= stp[:, None], hh >= stp[:, None]) & live
            g_hit = np.where(dirn[:, None] > 0, hh >= tgt[:, None], ll <= tgt[:, None]) & live & (t > ei[:, None])
        s_i = np.where(s_hit.any(1), s_hit.argmax(1), 999)
        g_i = np.where(g_hit.any(1), g_hit.argmax(1), 999)
        st = (s_i <= g_i) & (s_i < 999)
        tg = ~st & (g_i < 999)
        s_open = oo[ar, np.minimum(s_i, 389)]
        gap = st & (s_i > ei) & np.where(dirn > 0, s_open <= stp, s_open >= stp)
        px = np.where(st, np.where(gap, s_open, stp) - dirn * slip, np.nan)
        g_open = oo[ar, np.minimum(g_i, 389)]
        g_gap = tg & (g_i > ei) & np.where(dirn > 0, g_open >= tgt, g_open <= tgt)
        px = np.where(tg, np.where(g_gap, g_open, tgt), px)
        eod = ~st & ~tg
        px = np.where(eod, cf[sel, eod_min - 1] - dirn * slip, px)
        xm = np.where(st, s_i, np.where(tg, g_i, eod_min))
        r = dirn * (px - fill) / dist
        with np.errstate(invalid="ignore"):
            adv = np.where(dirn[:, None] > 0, ll - fill[:, None], fill[:, None] - hh) / dist[:, None]
            lo = np.nanmin(np.where(live & (t < xm[:, None]), adv, 0.0), 1)
            at_x = adv[ar, np.minimum(xm, 389)]
        lo = np.minimum(np.minimum(lo, np.where(tg, np.maximum(np.nan_to_num(at_x), -1.0), r)), 0.0)
        acc["r"].append(r); acc["kind"].append(np.where(st, 0, np.where(tg, 1, 2)))
        acc["day"].append(sel); acc["bar"].append(b); acc["dirn"].append(dirn)
        acc["dist"].append(dist / atr[sel]); acc["lo"].append(lo); acc["exit"].append(xm)
        busy[sel] = xm
    return {k: (np.concatenate(v) if v else np.array([])) for k, v in acc.items()}


def ote_levels(d: dict, sig: np.ndarray, entry_ret: float, target_ext: float):
    """ICT optimal trade entry on the impulse leg up to the signal bar: limit at `entry_ret` retracement of
    (session low -> high so far) for longs, stop beyond the leg's origin (+0.02 ATR), target at the leg's
    end extended by `target_ext` of the leg (0 = retest of the high; 0.27 = ICT -27% extension)."""
    hi = np.fmax.accumulate(d["h5"], 1)
    lo = np.fmin.accumulate(d["l5"], 1)
    leg = hi - lo
    buf = 0.02 * d["atr_prev"][:, None]
    lim = np.where(sig > 0, hi - entry_ret * leg, np.where(sig < 0, lo + entry_ret * leg, np.nan))
    stp = np.where(sig > 0, lo - buf, np.where(sig < 0, hi + buf, np.nan))
    tgt = np.where(sig > 0, hi + target_ext * leg, np.where(sig < 0, lo - target_ext * leg, np.nan))
    return lim, stp, tgt


def sd_targets(d: dict, sig: np.ndarray, k: float):
    """ICT-style standard-deviation projection of the 09:30-10:00 range: target = range extreme +/- k x range."""
    with np.errstate(all="ignore"):
        hi = np.nanmax(d["h5"][:, :6], 1)[:, None]
        lo = np.nanmin(d["l5"][:, :6], 1)[:, None]
    rng = hi - lo
    return np.where(sig > 0, hi + k * rng, np.where(sig < 0, lo - k * rng, np.nan))


def costed(d: dict, t: dict) -> dict:
    """Subtract the $1.50 MNQ round turn, in R per contract."""
    if len(t["r"]):
        price_dist = t["dist"] * d["atr_prev"][t["day"].astype(int)]
        t["r"] = t["r"] - COMM_RT / (price_dist * USD_PER_QQQ)
    return t


def daily_r(d: dict, t: dict) -> np.ndarray:
    out = np.zeros(len(d["dkey"]))
    if len(t["r"]):
        np.add.at(out, t["day"].astype(int), t["r"])
    return out


def overnight_returns(d: dict) -> np.ndarray:
    """Close (15:59) to next open (09:30) log returns of the session after each day (NaN at the end)."""
    with np.errstate(all="ignore"):
        dc = d["cf"][:, -1]
        return np.r_[np.log(d["day_open"][1:] / dc[:-1]), np.nan]
