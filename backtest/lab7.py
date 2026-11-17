#!/usr/bin/env python3
"""Round 7: improving NB3's edge with the rest of the "Beat the Market" design (Zarattini, Aziz & Barbon,
2024, intraday momentum on SPY) and an index-futures portfolio, on 10 years of 1-minute data.

Signal variants (all keep NB3's core: price closes outside a noise band around the session open built
from the 14-day average absolute move at that time of day):
  k        band width multiple (NB3: 1.0)
  gap      False = band around the open (NB3); True = upper band from max(open, previous close),
           lower band from min(open, previous close) (the paper's gap adjustment)
  check30  False = every 5-minute close (NB3); True = only closes at :00 / :30 (the paper)
  regime   False = every day; True = only days whose previous ATR(14) >= its 60-day median
Exit variants:
  ("bracket", stop_atr, rr)  fixed stop and target (lab6.bracket6, NB3 = (0.3, 3))
  ("trail", stop_atr)        hard stop at stop_atr x ATR; otherwise exit at the next bar's open after a
                             check-time close back through the trailing level max(upper band, VWAP)
                             for longs / min(lower band, VWAP) for shorts (the paper's exit); flat 15:55
Instruments are executed as micro futures (`FUTURES`): 1 futures tick of slippage per market/stop fill,
$1.50 per round turn charged in R per contract.
"""
from __future__ import annotations

import numpy as np

import intraday_lab as il
import lab4
import lab6

BARS = np.arange(78)
NB3_LAST_BAR = 64
COMM_RT = 1.50
# ETF -> micro future: (name, futures points per ETF dollar, $ per point, tick in points)
FUTURES = {"QQQ": ("MNQ", 41.3, 2.0, 0.25), "SPY": ("MES", 10.09, 5.0, 0.25),
           "IWM": ("M2K", 10.1, 5.0, 0.10), "DIA": ("MYM", 100.5, 0.5, 1.0)}


def usd_per_etf_dollar(tk: str) -> float:
    _, ratio, pv, _ = FUTURES[tk]
    return ratio * pv


def tick_in_etf(tk: str) -> float:
    _, ratio, _, tick = FUTURES[tk]
    return tick / ratio


def add_regime(d: dict) -> dict:
    atr = d["atr_prev"]
    ar = np.full(len(atr), np.nan)
    for i in range(60, len(atr)):
        ar[i] = atr[i] / np.nanmedian(atr[i - 60:i])
    d["atr_ratio"] = ar
    return d


def bands(d: dict, k: float, gap: bool):
    op, pc = d["day_open"], d["prev_close"]
    up_ref = np.fmax(op, pc) if gap else op
    dn_ref = np.fmin(op, pc) if gap else op
    return up_ref[:, None] * (1 + k * d["sig5"]), dn_ref[:, None] * (1 - k * d["sig5"])


def signals7(d: dict, k: float = 1.0, gap: bool = False, check30: bool = False, regime: bool = False) -> np.ndarray:
    up, dn = bands(d, k, gap)
    c5 = d["c5"]
    sig = np.zeros(c5.shape, np.int8)
    with np.errstate(invalid="ignore"):
        sig[c5 > up], sig[c5 < dn] = 1, -1
    sig[:, NB3_LAST_BAR + 1:] = 0
    if check30:
        sig[:, ((BARS + 1) * 5) % 30 != 0] = 0
    if regime:
        with np.errstate(invalid="ignore"):
            sig[~(d["atr_ratio"] >= 1.0)] = 0
    sig[~d["has5"]] = 0
    return sig


def trail_trades(d: dict, sig: np.ndarray, stop_atr: float, k: float, gap: bool, check30: bool,
                 max_trades: int = 1, slip: float = 0.0, commission: float = 0.0, last_entry_min: int = 330,
                 eod_min: int = il.EOD_MIN) -> dict:
    o, h, l, cf, c5 = d["o"], d["h"], d["l"], d["cf"], d["c5"]
    atr = d["atr_prev"]
    up, dn = bands(d, k, gap)
    with np.errstate(invalid="ignore"):
        tl_long, tl_short = np.fmax(up, d["vwap5"]), np.fmin(dn, d["vwap5"])
    checkbar = (((BARS + 1) * 5) % 30 == 0) if check30 else np.ones(78, bool)
    n = sig.shape[0]
    t = np.arange(390)[None, :]
    entry_min = (BARS + 1) * 5
    acc = {k_: [] for k_ in ("r", "kind", "day", "bar", "dirn", "dist", "lo", "exit")}
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
        oo, hh, ll = o[sel], h[sel], l[sel]
        ei = np.where(~np.isnan(oo) & (t >= em[:, None]), t, 999).min(1)
        good = ei < eod_min
        busy[sel[~good]] = em[~good]
        sel, b, dirn, ei, oo, hh, ll = sel[good], b[good], dirn[good], ei[good], oo[good], hh[good], ll[good]
        if not len(sel):
            continue
        ar = np.arange(len(sel))
        fill = oo[ar, ei] + dirn * slip
        dist = stop_atr * atr[sel]
        stp = fill - dirn * dist
        live = (t >= ei[:, None]) & (t < eod_min)
        with np.errstate(invalid="ignore"):
            s_hit = np.where(dirn[:, None] > 0, ll <= stp[:, None], hh >= stp[:, None]) & live
            # trailing exit: a check-time close (bar index > entry bar) back through the trailing level
            cc = c5[sel]
            lvl = np.where(dirn[:, None] > 0, tl_long[sel], tl_short[sel])
            cross = np.where(dirn[:, None] > 0, cc < lvl, cc > lvl)
            cross &= checkbar[None, :] & (BARS[None, :] > b[:, None])
        s_i = np.where(s_hit.any(1), s_hit.argmax(1), 999)
        tb = np.where(cross.any(1), cross.argmax(1), 999)
        tx = np.where(tb < 999, (tb + 1) * 5, 999)                    # next bar's open
        st = (s_i < 999) & (s_i < tx) & (s_i < eod_min)
        tr = ~st & (tx < eod_min)
        s_open = oo[ar, np.minimum(s_i, 389)]
        gap_ = st & (s_i > ei) & np.where(dirn > 0, s_open <= stp, s_open >= stp)
        px = np.where(st, np.where(gap_, s_open, stp) - dirn * slip, np.nan)
        tx_c = np.minimum(tx, eod_min - 1)
        valid = ~np.isnan(oo) & (t >= tx_c[:, None])
        tx_v = np.where(valid, t, 999).min(1)
        tx_px = np.where(tx_v < eod_min, oo[ar, np.minimum(tx_v, 389)], cf[sel, eod_min - 1])
        px = np.where(tr, tx_px - dirn * slip, px)
        eod = ~st & ~tr
        px = np.where(eod, cf[sel, eod_min - 1] - dirn * slip, px)
        xm = np.where(st, s_i, np.where(tr, np.minimum(tx_v, eod_min), eod_min))
        r = (dirn * (px - fill) - 2 * commission) / dist
        with np.errstate(invalid="ignore"):
            adv = np.where(dirn[:, None] > 0, ll - fill[:, None], fill[:, None] - hh) / dist[:, None]
            lo = np.nanmin(np.where(live & (t < xm[:, None]), adv, 0.0), 1)
        lo = np.minimum(np.minimum(lo, dirn * (px - fill) / dist), 0.0)
        acc["r"].append(r); acc["kind"].append(np.where(st, 0, np.where(tr, 3, 2)))
        acc["day"].append(sel); acc["bar"].append(b); acc["dirn"].append(dirn)
        acc["dist"].append(dist / atr[sel]); acc["lo"].append(lo); acc["exit"].append(xm)
        busy[sel] = xm
    return {k_: (np.concatenate(v) if v else np.array([])) for k_, v in acc.items()}


def run(d: dict, tk: str, rule: dict) -> dict:
    """Trades of one rule set on one instrument, R net of futures slippage and commission."""
    mt = rule["mt"]
    sig = signals7(d, rule["k"], rule["gap"], rule["check30"], rule["regime"])
    if mt > 1:
        pass                                     # every signal bar is a candidate; `busy` spaces them
    else:
        first = np.where((sig != 0).any(1), (sig != 0).argmax(1), -1)
        keep = np.zeros_like(sig)
        rows = np.flatnonzero(first >= 0)
        keep[rows, first[rows]] = sig[rows, first[rows]]
        sig = keep
    slip = tick_in_etf(tk)
    ex = rule["exit"]
    if ex[0] == "bracket":
        t = lab6.bracket6(d, sig, ex[2], ex[1], max_trades=mt, slip=slip, commission=0.0, tick=slip)
    else:
        t = trail_trades(d, sig, ex[1], rule["k"], rule["gap"], rule["check30"], max_trades=mt, slip=slip)
    if len(t["r"]):
        price_dist = t["dist"] * d["atr_prev"][t["day"].astype(int)]
        t["comm_r"] = COMM_RT / (price_dist * usd_per_etf_dollar(tk))
        t["r"] = t["r"] - t["comm_r"]
    return t


def daily_r(d: dict, t: dict) -> np.ndarray:
    """Sum of R per session (0 on days without a trade), indexed like d['dkey']."""
    out = np.zeros(len(d["dkey"]))
    if len(t["r"]):
        np.add.at(out, t["day"].astype(int), t["r"])
    return out
