#!/usr/bin/env python3
"""Round 4 lab: popular discretionary setups made mechanical, structure-based stops, NB3 confluence.

Reuses intraday_lab's data (1-minute grid, 5-minute bars, VWAP, noise band, previous-day ATR) and its
fill model: signal on a 5-minute bar close, market entry at the next bar's open + 2 ticks, stop checked
before target inside the same minute, 15:55 exit, $0.005/share per side.

New here:
  * `bracket()` accepts a per-signal STRUCTURAL stop level (e.g. the high of a liquidity sweep) in
    addition to the ATR stop. Distance = |fill - level| + 0.02 ATR, at least 0.05 ATR; a setup whose
    level is more than 1.0 ATR away at the signal close, or already on the wrong side, is not taken.
  * every trade reports how it ended: 0 = stop, 1 = target, 2 = time exit (15:55, or the trade's
    own time limit). "Win" = net R > 0; "target hit" = reached the full reward:risk.
  * signal families (`signals4`), each returning (signal array, stop-level array or None):
      crt m          Candle Range Theory: first m minutes form the range; a later bar trades beyond one
                     side and closes back inside -> trade toward the other side; stop beyond the sweep
      pdsw           prior-day high/low swept, close back inside -> fade; stop beyond the sweep
      judas k        Judas swing / Power of 3: first-30-minute move beyond open -/+ k*sigma, then a close
                     back through the open (until 11:30) -> trade the reversal; stop beyond the swing
      ict22 lv win   ICT 2022 model: sweep (prior-day level or 30-minute range) -> displacement fair
                     value gap the other way -> retrace into the gap; stop beyond the sweep extreme
      nrorb f m      NR7 / NR4 / inside-day filter + m-minute opening-range breakout
      orbrv k mode   opening-range breakout on "stocks in play": first 5-minute volume >= k x its
                     14-day average; bar0 = first candle's direction at 09:35, brk = later breakout
      turtle n       turtle soup: new n-day high/low made today (old extreme >= 4 sessions back),
                     close back inside -> fade
      va80 k         Market Profile 80% rule: open outside yesterday's value area, k consecutive
                     5-minute closes back inside -> trade to the other side of the value area
      hgrail x       Holy Grail style: daily trend (close vs 20-day average, strength >= x), intraday
                     pullback that touches VWAP and closes on the trend side -> trend direction
      lhh kind th    last-half-hour momentum (Gao et al. 2018): at 15:30 trade the sign of the first
                     half-hour return (fh) or of the day's return so far (day) if |return| >= th
      gapgo g        gap >= g, first 5-minute candle in the gap direction, first-bar RVOL >= 1.5
      odrive k       opening drive: 15-minute range >= k ATR, close in its outer 20% -> continuation
      nb3 flt mode   NB3 V2 signal (noise band 1.0, first signal, bars opening 09:30-14:50) with a
                     confluence filter; mode first = only the day's first signal, pass = first one
                     that passes the filter
      smt kind       SMT divergence between two correlated instruments (see `smt_signals`)
"""
from __future__ import annotations

import numpy as np

import intraday_lab as il

PERIODS = {"dev": (20230301, 20241231), "holdout": (20250101, 20260331), "all": (0, 99999999)}
RRS4 = (1.0, 2.0, 3.0)
BUF_ATR, MIN_ATR, MAX_ATR = 0.02, 0.05, 1.0
NB3_LAST_BAR = 64                                     # signal bars opening 09:30-14:50
BARS = np.arange(78)


# ----------------------------------------------------------------------------
# Extra features (computed on the full history, before any period subset)
# ----------------------------------------------------------------------------
def _prev(a: np.ndarray) -> np.ndarray:
    return np.r_[np.nan, a[:-1]].astype(float)


def _value_area(h5, l5, v5, frac=0.70, nbins=60):
    """Per-day value area (VAL, VAH, POC) from 5-minute bars, volume spread evenly over each bar's range."""
    n = h5.shape[0]
    out = np.full((n, 3), np.nan)
    for i in range(n):
        ok = ~np.isnan(h5[i]) & ~np.isnan(l5[i]) & (v5[i] > 0)
        if ok.sum() < 10:
            continue
        hi, lo, vol = h5[i, ok], l5[i, ok], v5[i, ok]
        top, bot = hi.max(), lo.min()
        if top <= bot:
            continue
        edges = np.linspace(bot, top, nbins + 1)
        mid = (edges[:-1] + edges[1:]) / 2
        cover = (mid[None, :] >= lo[:, None]) & (mid[None, :] <= hi[:, None])
        cnt = cover.sum(1)
        cover[cnt == 0, np.clip(np.searchsorted(mid, lo[cnt == 0]), 0, nbins - 1)] = True
        w = (vol / cover.sum(1))[:, None] * cover
        prof = w.sum(0)
        poc = int(prof.argmax())
        a = b = poc
        tot, need = prof[poc], frac * prof.sum()
        while tot < need and (a > 0 or b < nbins - 1):
            up = prof[b + 1] if b < nbins - 1 else -1
            dn = prof[a - 1] if a > 0 else -1
            if up >= dn:
                b += 1; tot += up
            else:
                a -= 1; tot += dn
        out[i] = (edges[a], edges[b + 1], mid[poc])
    return out


def enrich(d: dict) -> dict:
    """Adds daily context features. Everything for day i uses only days < i (or today's bars up to t)."""
    h, l, cf, v5 = d["h"], d["l"], d["cf"], d["v5"]
    n = len(d["dkey"])
    with np.errstate(all="ignore"):
        dh, dl = np.nanmax(h, 1), np.nanmin(l, 1)
    dc = cf[:, -1]
    rng = dh - dl
    d["dh"], d["dl"], d["dc"] = dh, dl, dc

    def nr(k):
        out = np.zeros(n, bool)
        for i in range(k, n):
            out[i] = rng[i - 1] <= np.nanmin(rng[i - k:i])
        return out
    d["nr7"], d["nr4"] = nr(7), nr(4)
    inside = np.zeros(n, bool)
    inside[2:] = (dh[1:-1] <= dh[:-2]) & (dl[1:-1] >= dl[:-2])
    d["inside"] = inside
    sma = np.full(n, np.nan)
    hi_n, lo_n, hi_age, lo_age = {}, {}, {}, {}
    for look in (10, 20):
        hi_n[look], lo_n[look] = np.full(n, np.nan), np.full(n, np.nan)
        hi_age[look], lo_age[look] = np.zeros(n), np.zeros(n)
    for i in range(20, n):
        sma[i] = np.nanmean(dc[i - 20:i])
        for look in (10, 20):
            wh, wl = dh[i - look:i], dl[i - look:i]
            hi_n[look][i], lo_n[look][i] = np.nanmax(wh), np.nanmin(wl)
            hi_age[look][i] = look - np.nanargmax(wh)        # sessions since the old extreme
            lo_age[look][i] = look - np.nanargmin(wl)
    d["sma20_prev"] = sma
    d["trend_prev"] = _prev(dc) / sma - 1                 # yesterday's close vs the 20 closes before today
    d["hi_n"], d["lo_n"], d["hi_age"], d["lo_age"] = hi_n, lo_n, hi_age, lo_age
    # relative volume: first 5-minute bar and cumulative-by-bar, vs the previous 14 sessions
    cum = np.cumsum(v5, 1)
    rv0 = np.full(n, np.nan)
    rvc = np.full(cum.shape, np.nan)
    for i in range(14, n):
        with np.errstate(all="ignore"):
            rv0[i] = v5[i, 0] / np.mean(v5[i - 14:i, 0])
            rvc[i] = cum[i] / np.mean(cum[i - 14:i], 0)
    d["rv0"], d["rvc"] = rv0, rvc
    atr = d["atr_prev"]
    ar = np.full(n, np.nan)
    for i in range(60, n):
        ar[i] = atr[i] / np.nanmedian(atr[i - 60:i])
    d["atr_ratio"] = ar
    va = _value_area(d["h5"], d["l5"], v5)
    d["val_prev"], d["vah_prev"], d["poc_prev"] = _prev(va[:, 0]), _prev(va[:, 1]), _prev(va[:, 2])
    d["gap"] = d["day_open"] / d["prev_close"] - 1
    return d


def align(a: dict, b: dict) -> tuple[dict, dict]:
    """The two instruments restricted to their common sessions, in the same order."""
    common = np.intersect1d(a["dkey"], b["dkey"])
    return _take(a, np.isin(a["dkey"], common)), _take(b, np.isin(b["dkey"], common))


def _take(d: dict, m: np.ndarray) -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, np.ndarray) and v.shape[:1] == m.shape:
            out[k] = v[m]
        elif isinstance(v, dict):
            out[k] = {kk: (vv[m] if isinstance(vv, np.ndarray) and vv.shape[:1] == m.shape else vv)
                      for kk, vv in v.items()}
        else:
            out[k] = v
    return out


def subset(d: dict, start: int, end: int) -> dict:
    return _take(d, (d["dkey"] >= start) & (d["dkey"] <= end))


# ----------------------------------------------------------------------------
# Signals: (sig, lvl) with sig in {-1, 0, +1} at 5-minute bar closes, lvl = structural stop price
# ----------------------------------------------------------------------------
def _runmax(a):
    return np.fmax.accumulate(a, axis=1)


def _runmin(a):
    return np.fmin.accumulate(a, axis=1)


def _prevbar(a, fill=np.nan):
    return np.concatenate([np.full((a.shape[0], 1), fill), a[:, :-1]], axis=1)


def signals4(d: dict, family: str, p=None):
    c5, h5, l5, o5 = d["c5"], d["h5"], d["l5"], d["o5"]
    sig = np.zeros(c5.shape, np.int8)
    lvl = np.full(c5.shape, np.nan)
    with np.errstate(all="ignore"):
        if family in ("crt", "pdsw", "turtle"):
            if family == "crt":
                k = int(p) // 5
                hi = np.nanmax(h5[:, :k], 1)[:, None]
                lo = np.nanmin(l5[:, :k], 1)[:, None]
                after = BARS[None, :] >= k
            elif family == "pdsw":
                hi, lo = d["prev_high"][:, None], d["prev_low"][:, None]
                after = np.ones_like(c5, bool)
            else:
                look = int(p)
                hi, lo = d["hi_n"][look][:, None], d["lo_n"][look][:, None]
                after = np.ones_like(c5, bool)
                old_hi = (d["hi_age"][look] >= 4)[:, None]
                old_lo = (d["lo_age"][look] >= 4)[:, None]
            xh = _runmax(np.where(after, h5, np.nan))
            xl = _runmin(np.where(after, l5, np.nan))
            short = after & (xh > hi) & (c5 < hi)
            long_ = after & (xl < lo) & (c5 > lo)
            if family == "turtle":
                short &= old_hi
                long_ &= old_lo
            both = short & long_
            sig[short], sig[long_] = -1, 1
            sig[both] = 0
            lvl = np.where(sig < 0, xh, np.where(sig > 0, xl, np.nan))
        elif family == "judas":
            k = float(p)
            op = d["day_open"][:, None]
            dipped = np.maximum.accumulate(np.where(BARS[None, :] < 6, l5 < op * (1 - k * d["sig5"]), False), 1)
            popped = np.maximum.accumulate(np.where(BARS[None, :] < 6, h5 > op * (1 + k * d["sig5"]), False), 1)
            win = (BARS[None, :] >= 1) & (BARS[None, :] <= 23)
            long_ = win & dipped & (c5 > op)
            short = win & popped & (c5 < op)
            sig[long_], sig[short] = 1, -1
            sig[long_ & short] = 0
            sl = _runmin(l5)
            sh = _runmax(h5)
            lvl = np.where(sig > 0, sl, np.where(sig < 0, sh, np.nan))
        elif family == "ict22":
            lv, window = p
            sig, lvl = _ict2022(d, lv, window)
        elif family == "nrorb":
            flt, m = p
            k = int(m) // 5
            hi = np.nanmax(h5[:, :k], 1)[:, None]
            lo = np.nanmin(l5[:, :k], 1)[:, None]
            day_ok = d[flt][:, None]
            sig[(c5 > hi) & day_ok], sig[(c5 < lo) & day_ok] = 1, -1
            sig[:, :k] = 0
            lvl = np.where(sig > 0, lo, np.where(sig < 0, hi, np.nan))
        elif family == "orbrv":
            k, mode = p
            hot = (d["rv0"] >= k)[:, None]
            if mode == "bar0":
                dirn = np.sign(c5[:, 0] - o5[:, 0])
                sig[:, 0] = np.where(hot[:, 0], dirn, 0)
                lvl[:, 0] = np.where(dirn > 0, l5[:, 0], h5[:, 0])
            else:
                hi, lo = h5[:, :1], l5[:, :1]
                sig[(c5 > hi) & hot], sig[(c5 < lo) & hot] = 1, -1
                sig[:, 0] = 0
                lvl = np.where(sig > 0, lo, np.where(sig < 0, hi, np.nan))
        elif family == "va80":
            k = int(p)
            vah, val = d["vah_prev"][:, None], d["val_prev"][:, None]
            op = d["day_open"][:, None]
            inside = (c5 < vah) & (c5 > val)
            run = np.zeros(c5.shape, int)
            for b in range(78):
                run[:, b] = np.where(inside[:, b], (run[:, b - 1] if b else 0) + 1, 0)
            sig[(op > vah) & (run >= k)] = -1
            sig[(op < val) & (run >= k)] = 1
            lvl = np.where(sig < 0, _runmax(h5), np.where(sig > 0, _runmin(l5), np.nan))
        elif family == "hgrail":
            x = float(p)
            tr = d["trend_prev"][:, None]
            up, dn = tr > x, tr < -x
            vw = d["vwap5"]
            touch_l = up & (l5 <= vw) & (c5 > vw)
            touch_s = dn & (h5 >= vw) & (c5 < vw)
            sig[touch_l], sig[touch_s] = 1, -1
            sig[:, :6] = 0
            lvl = np.where(sig > 0, l5, np.where(sig < 0, h5, np.nan))
        elif family == "lhh":
            kind, th = p
            pc = d["prev_close"]
            r = (c5[:, 5] / pc - 1) if kind == "fh" else (c5[:, 71] / pc - 1)
            sig[:, 71] = np.where(np.abs(r) >= th, np.sign(r), 0)
            lvl = None
        elif family == "gapgo":
            g = float(p)
            gap = d["gap"]
            dirn = np.sign(c5[:, 0] - o5[:, 0])
            ok = (np.abs(gap) >= g) & (np.sign(gap) == dirn) & (d["rv0"] >= 1.5)
            sig[:, 0] = np.where(ok, dirn, 0)
            lvl[:, 0] = np.where(dirn > 0, l5[:, 0], h5[:, 0])
        elif family == "odrive":
            k = float(p)
            hi = np.nanmax(h5[:, :3], 1)
            lo = np.nanmin(l5[:, :3], 1)
            rg = hi - lo
            pos = (c5[:, 2] - lo) / rg
            big = rg >= k * d["atr_prev"]
            sig[:, 2] = np.where(big & (pos >= 0.8), 1, np.where(big & (pos <= 0.2), -1, 0))
            lvl[:, 2] = (hi + lo) / 2
        elif family == "nb3":
            flt, mode = p
            sig = _nb3(d, flt, mode)
            lvl = None
        else:
            raise ValueError(family)
    sig[~d["has5"]] = 0
    if lvl is not None:
        lvl = np.where(sig != 0, lvl, np.nan)
    return sig, lvl


def _ict2022(d, lv, window):
    c5, h5, l5, o5 = d["c5"], d["h5"], d["l5"], d["o5"]
    n = c5.shape[0]
    sig = np.zeros(c5.shape, np.int8)
    lvl = np.full(c5.shape, np.nan)
    if lv == "pd":
        L_hi, L_lo, start = d["prev_high"], d["prev_low"], 0
    else:                                             # 09:30-10:00 range, sweeps from 10:00 on
        L_hi, L_lo, start = np.nanmax(h5[:, :6], 1), np.nanmin(l5[:, :6], 1), 6
    last = 24 if window == "am" else 66
    side = np.zeros(n)                                # -1: high swept (look for shorts), +1: low swept
    ext = np.full(n, np.nan)
    gtop, gbot, gact = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, bool)
    rng5 = h5 - l5
    with np.errstate(all="ignore"):
        for b in range(start, 78):
            new_hi = (side == 0) & (h5[:, b] > L_hi)
            new_lo = (side == 0) & (l5[:, b] < L_lo)
            side = np.where(new_hi & ~new_lo, -1, np.where(new_lo & ~new_hi, 1, side))
            ext = np.where(side < 0, np.fmax(ext, h5[:, b]), np.where(side > 0, np.fmin(ext, l5[:, b]), ext))
            if b <= last:
                e_s = gact & (side < 0) & (h5[:, b] >= gbot) & (c5[:, b] <= gtop)
                e_l = gact & (side > 0) & (l5[:, b] <= gtop) & (c5[:, b] >= gbot)
                sig[e_s, b], sig[e_l, b] = -1, 1
                lvl[e_s, b], lvl[e_l, b] = ext[e_s], ext[e_l]
                gact &= ~(e_s | e_l)
            if b >= start + 2:
                avg = np.nanmean(rng5[:, :b], 1)
                disp = rng5[:, b - 1] >= 1.5 * avg
                bear = (side < 0) & disp & (h5[:, b] < l5[:, b - 2]) & (c5[:, b - 1] < o5[:, b - 1]) & (c5[:, b] < L_hi)
                bull = (side > 0) & disp & (l5[:, b] > h5[:, b - 2]) & (c5[:, b - 1] > o5[:, b - 1]) & (c5[:, b] > L_lo)
                gtop = np.where(bear, l5[:, b - 2], np.where(bull, l5[:, b], gtop))
                gbot = np.where(bear, h5[:, b], np.where(bull, h5[:, b - 2], gbot))
                gact |= bear | bull
    return sig, lvl


def _nb3(d, flt, mode):
    raw = il.signals(d, "noise_break", 1.0)
    raw[:, NB3_LAST_BAR + 1:] = 0
    c5 = d["c5"]
    dirn = raw.astype(float)
    with np.errstate(all="ignore"):
        if flt == "none":
            ok = np.ones_like(c5, bool)
        elif flt == "vwap":
            ok = np.sign(c5 - d["vwap5"]) == dirn
        elif flt == "trend":
            ok = np.sign(d["trend_prev"])[:, None] == dirn
        elif flt == "gap_with":
            ok = np.sign(d["gap"])[:, None] == dirn
        elif flt == "gap_against":
            ok = np.sign(d["gap"])[:, None] == -dirn
        elif flt == "rvol":
            ok = d["rvc"] >= 1.0
        elif flt == "atr_lo":
            ok = (d["atr_ratio"] < 1.0)[:, None] & np.ones_like(c5, bool)
        elif flt == "atr_hi":
            ok = (d["atr_ratio"] >= 1.0)[:, None] & np.ones_like(c5, bool)
        elif flt == "nr7":
            ok = d["nr7"][:, None] & np.ones_like(c5, bool)
        elif flt == "pdbrk":
            ok = ((dirn > 0) & (c5 > d["prev_high"][:, None])) | ((dirn < 0) & (c5 < d["prev_low"][:, None]))
        elif flt == "early":
            ok = np.broadcast_to(BARS[None, :] <= 12, c5.shape)
        elif flt == "late":
            ok = np.broadcast_to(BARS[None, :] > 12, c5.shape)
        elif flt == "spy":
            ok = np.sign(d["ref_c5"] - d["ref_open"][:, None]) == dirn
        else:
            raise ValueError(flt)
    if mode == "first":
        first = np.where((raw != 0).any(1), (raw != 0).argmax(1), -1)
        keep = np.zeros_like(raw)
        rows = np.flatnonzero(first >= 0)
        keep[rows, first[rows]] = raw[rows, first[rows]]
        return np.where(ok, keep, 0).astype(np.int8)
    return np.where(ok, raw, 0).astype(np.int8)


def smt_signals(a: dict, b: dict, kind: str):
    """SMT divergence: trade instrument `a` when it takes liquidity that its correlated partner `b` does not.

    sess: from 10:00, a prints a new session high while b does not, and a's bar closes in its lower half
          -> short a (mirror for lows); stop above a's high.
    pd:   a has traded above its prior-day high, b has not traded above its own, and a closes back below
          its prior-day high -> short a (mirror for lows); stop beyond a's sweep extreme.
    Both dicts must be aligned (`align`)."""
    c5, h5, l5 = a["c5"], a["h5"], a["l5"]
    sig = np.zeros(c5.shape, np.int8)
    with np.errstate(all="ignore"):
        if kind == "sess":
            pa_h, pa_l = _prevbar(_runmax(a["h5"])), _prevbar(_runmin(a["l5"]))
            pb_h, pb_l = _prevbar(_runmax(b["h5"])), _prevbar(_runmin(b["l5"]))
            mid = (h5 + l5) / 2
            short = (h5 > pa_h) & ~(b["h5"] > pb_h) & (c5 < mid)
            long_ = (l5 < pa_l) & ~(b["l5"] < pb_l) & (c5 > mid)
            short[:, :6] = long_[:, :6] = False
            lv_s, lv_l = h5, l5
        else:
            xa_h, xa_l = _runmax(a["h5"]), _runmin(a["l5"])
            xb_h, xb_l = _runmax(b["h5"]), _runmin(b["l5"])
            ph, pl = a["prev_high"][:, None], a["prev_low"][:, None]
            short = (xa_h > ph) & (xb_h <= b["prev_high"][:, None]) & (c5 < ph)
            long_ = (xa_l < pl) & (xb_l >= b["prev_low"][:, None]) & (c5 > pl)
            lv_s, lv_l = xa_h, xa_l
        sig[short], sig[long_] = -1, 1
        sig[short & long_] = 0
    sig[~a["has5"] | ~b["has5"]] = 0
    lvl = np.where(sig < 0, lv_s, np.where(sig > 0, lv_l, np.nan))
    return sig, lvl


# ----------------------------------------------------------------------------
# Bracket simulation with ATR or structural stops
# ----------------------------------------------------------------------------
def bracket(d: dict, sig: np.ndarray, stop, lvl=None, rrs=RRS4, max_trades: int = 1,
            last_entry_min: int = 330, eod_min: int = il.EOD_MIN) -> dict:
    """stop = ATR multiple (float) or "struct" (uses `lvl`). Returns {rr: dict of per-trade arrays}:
    r (net R), kind (0 stop / 1 target / 2 time exit), day (row index), bar, dirn, dist (stop distance in ATR)."""
    o, h, l, cf = d["o"], d["h"], d["l"], d["cf"]
    atr = d["atr_prev"]
    slip = il.SLIP_TICKS * il.TICK
    sig = sig.copy()
    if stop == "struct":
        with np.errstate(all="ignore"):
            room = sig * (d["c5"] - lvl)
            bad = np.isnan(lvl) | (room <= 0) | (room + BUF_ATR * atr[:, None] > MAX_ATR * atr[:, None])
        sig[bad] = 0
    n = sig.shape[0]
    t = np.arange(390)[None, :]
    entry_min = (BARS + 1) * 5
    out = {}
    for rr in rrs:
        acc = {k: [] for k in ("r", "kind", "day", "bar", "dirn", "dist")}
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
            ei = np.where(~np.isnan(o[sel]) & (t >= em[:, None]), t, 999).min(1)
            fill = o[sel, np.minimum(ei, 389)] + dirn * slip
            if stop == "struct":
                lv = lvl[sel, b]
                dist = np.maximum(dirn * (fill - lv) + BUF_ATR * atr[sel], MIN_ATR * atr[sel])
                good = (ei < eod_min) & (dirn * (fill - lv) > 0)
            else:
                dist = float(stop) * atr[sel]
                good = ei < eod_min
            busy[sel[~good]] = em[~good]                 # a skipped setup lets a later one through
            sel, b, dirn, ei, fill, dist = sel[good], b[good], dirn[good], ei[good], fill[good], dist[good]
            if not len(sel):
                continue
            stp = fill - dirn * dist
            tgt = fill + dirn * rr * dist
            live = (t >= ei[:, None]) & (t < eod_min)
            hh, ll, oo = h[sel], l[sel], o[sel]
            with np.errstate(invalid="ignore"):
                s_hit = np.where(dirn[:, None] > 0, ll <= stp[:, None], hh >= stp[:, None]) & live
                g_hit = np.where(dirn[:, None] > 0, hh >= tgt[:, None], ll <= tgt[:, None]) & live & (t > ei[:, None])
            s_i = np.where(s_hit.any(1), s_hit.argmax(1), 999)
            g_i = np.where(g_hit.any(1), g_hit.argmax(1), 999)
            ar = np.arange(len(sel))
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
            r = (dirn * (px - fill) - 2 * il.COMMISSION) / dist
            acc["r"].append(r)
            acc["kind"].append(np.where(st, 0, np.where(tg, 1, 2)))
            acc["day"].append(sel)
            acc["bar"].append(b)
            acc["dirn"].append(dirn)
            acc["dist"].append(dist / atr[sel])
            busy[sel] = xm
        out[rr] = {k: (np.concatenate(v) if v else np.array([])) for k, v in acc.items()}
    return out


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def summary(res: dict, dkey: np.ndarray) -> dict:
    """Aggregates that can be summed across instruments (pooled portfolios)."""
    r, kind = res["r"], res["kind"]
    if not len(r):
        return {"n": 0}
    years = dkey[res["day"].astype(int)] // 10000
    return {"n": int(len(r)), "wins": int((r > 0).sum()), "tgts": int((kind == 1).sum()),
            "stops": int((kind == 0).sum()), "sum_r": float(r.sum()), "sum_r2": float((r * r).sum()),
            "gross_win": float(r[r > 0].sum()), "gross_loss": float(-r[r <= 0].sum()),
            "by_year": {int(y): float(r[years == y].sum()) for y in np.unique(years)}}


def describe(s: dict) -> dict:
    if not s.get("n"):
        return {"n": 0}
    n = s["n"]
    mean = s["sum_r"] / n
    var = max(s["sum_r2"] / n - mean * mean, 1e-12)
    lo, hi = wilson(s["wins"], n)
    return {"n": n, "win": s["wins"] / n, "win_lo": lo, "win_hi": hi, "tgt": s["tgts"] / n,
            "tgt_lo": wilson(s["tgts"], n)[0], "avg_r": mean, "t": mean / np.sqrt(var / n),
            "pf": s["gross_win"] / s["gross_loss"] if s["gross_loss"] > 0 else float("inf")}
