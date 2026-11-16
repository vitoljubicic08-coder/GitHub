#!/usr/bin/env python3
"""Fast vectorized simulator for SIP-ORB strategy variants on the candidate cache.

Reads the cache written by build_candidate_cache.py (1-minute regular-session paths of every stock-day
that passes the daily filters with opening RVOL >= 1) and evaluates rule variants in seconds.

Execution model (same conventions as the Pine strategy / broker emulator):
  * "close" entry: a 5-minute bar closes beyond the opening-range level inside the signal window; the
    market order fills at the next bar's open plus slippage (the V1 spec).
  * "stop" entry: a stop order one tick beyond the opening-range level; fills at max(level, minute open)
    plus slippage when the price trades through it inside the window (the paper's entry).
  * Stop-loss: fill price -/+ distance; fills at the stop, or at a worse opening gap, minus slippage.
  * Optional profit target: a limit order (no slippage) at fill +/- target_r x distance.
  * End of day: market order at the 15:55 open (minus slippage); early-close days use the last close.
  * When a stop and a target are both inside the same bar, the stop is assumed to come first, and on
    a stop-entry minute the stop counts as hit if that minute traded through it (both conservative).
  * Costs: 2 ticks of slippage per market/stop fill and 0.005 USD/share per side.
  * resolution=5 replays everything on 5-minute bars (reproduces the event-driven backtest);
    resolution=1 uses the 1-minute path for fills (like TradingView's Bar Magnifier).
Results are in R: net P&L per share / planned stop distance per share.
"""
from __future__ import annotations

import glob
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

SLIP_TICKS = 2
TICK = 0.01            # every candidate trades above 5 USD
COMMISSION = 0.005     # per share per side
EOD_MIN = 385          # 15:55
DAY_MIN = 390


@dataclass(frozen=True)
class Variant:
    name: str
    rvol_min: float = 2.0
    top_n: int | None = None           # keep only the N highest-RVOL candidates per day
    or_minutes: int = 5
    entry: str = "close"               # "close" (V1 spec) or "stop" (paper)
    window_end_min: int = 90           # signals/entries must occur before 11:00
    stop_kind: str = "atr"             # "atr" (fraction of prev ATR from fill) or "range" (opposite OR side)
    stop_atr: float = 0.10
    target_r: float | None = None
    breakeven_r: float | None = None   # move stop to entry once price reaches +x R (1-minute mode only)
    side: str = "both"                 # "both", "long", "short"
    min_price: float = 5.0
    max_price: float = 1e9
    min_atr_pct: float = 0.0           # prev ATR / price lower bound
    gap_align: bool = False            # opening gap in the trade direction
    min_gap_atr: float = 0.0           # |gap| >= x * ATR
    min_pre_ratio: float = 0.0         # premarket volume / average opening-bar volume
    spy_align: bool = False            # SPY's opening range moves the same way as the trade
    min_stop_usd: float = 0.0          # skip trades whose stop distance (known at entry) is smaller
    slip_ticks: int = SLIP_TICKS
    resolution: int = 1
    notes: str = field(default="", compare=False)


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def load_cache(cache_dir: str | Path, start: int = 0, end: int = 99999999) -> dict:
    parts: dict[str, list] = {}
    for path in sorted(glob.glob(str(Path(cache_dir) / "cand_*.npz"))):
        z = np.load(path)
        keep = (z["dkey"] >= start) & (z["dkey"] <= end)
        if not keep.any():
            continue
        for k in z.files:
            parts.setdefault(k, []).append(z[k][keep])
    data = {k: np.concatenate(v) for k, v in parts.items()}
    mk: dict[str, list] = {}
    for path in sorted(glob.glob(str(Path(cache_dir) / "market_*.npz"))):
        z = np.load(path)
        for k in z.files:
            mk.setdefault(k, []).append(z[k])
    market = {k: np.concatenate(v) for k, v in mk.items()}
    data["spy_dir"] = _spy_direction(data["dkey"], market)
    return data


def _first_valid(a: np.ndarray, start: int, stop: int) -> np.ndarray:
    seg = a[:, start:stop]
    ok = ~np.isnan(seg)
    idx = np.where(ok.any(1), ok.argmax(1), 0)
    out = seg[np.arange(len(a)), idx]
    out[~ok.any(1)] = np.nan
    return out


def _last_valid(a: np.ndarray, start: int, stop: int) -> np.ndarray:
    return _first_valid(a[:, start:stop][:, ::-1], 0, stop - start)


def _spy_direction(dkeys: np.ndarray, market: dict) -> np.ndarray:
    spy = market["tick"] == "SPY"
    g = market["grid"][spy]
    o = _first_valid(g[:, :, 0], 0, 5)
    c = _last_valid(g[:, :, 3], 0, 5)
    lookup = dict(zip(market["dkey"][spy].tolist(), np.sign(c - o).tolist()))
    return np.array([lookup.get(int(d), 0.0) for d in dkeys])


# ----------------------------------------------------------------------------
# Selection
# ----------------------------------------------------------------------------
def select(data: dict, v: Variant) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (candidate indices, direction, OR high, OR low) for the variant."""
    g = data["grid"]
    k = v.or_minutes
    or_open = _first_valid(g[:, :, 0], 0, k)
    or_close = _last_valid(g[:, :, 3], 0, k)
    or_hi = np.nanmax(g[:, :k, 1], axis=1)
    or_lo = np.nanmin(g[:, :k, 2], axis=1)
    direction = np.sign(or_close - or_open)
    price = data["o5"]
    atr = data["prev_atr"]
    ok = (data["rvol"] >= v.rvol_min) & (direction != 0) & ~np.isnan(direction)
    ok &= (price > v.min_price) & (price <= v.max_price) & (atr / price >= v.min_atr_pct)
    if v.side == "long":
        ok &= direction > 0
    elif v.side == "short":
        ok &= direction < 0
    gap = price - data["prev_close"]
    if v.gap_align:
        ok &= np.sign(gap) == direction
    if v.min_gap_atr > 0:
        ok &= np.abs(gap) >= v.min_gap_atr * atr
    if v.min_pre_ratio > 0:
        avg_open = data["v5"] / data["rvol"]
        ok &= data["pre_vol"] >= v.min_pre_ratio * avg_open
    if v.spy_align:
        ok &= data["spy_dir"] == direction
    idx = np.flatnonzero(ok)
    if v.top_n is not None and len(idx):
        order = np.lexsort((-data["rvol"][idx], data["dkey"][idx]))
        idx = idx[order]
        days = data["dkey"][idx]
        first = np.r_[0, np.flatnonzero(days[1:] != days[:-1]) + 1]
        rank = np.arange(len(idx)) - np.repeat(first, np.diff(np.r_[first, len(idx)]))
        idx = np.sort(idx[rank < v.top_n])
    return idx, direction[idx], or_hi[idx], or_lo[idx]


# ----------------------------------------------------------------------------
# Simulation
# ----------------------------------------------------------------------------
def _bars(grid: np.ndarray, res: int) -> tuple[np.ndarray, ...]:
    o, h, l, c = (grid[:, :, i].astype(np.float64) for i in range(4))
    if res == 1:
        return o, h, l, c
    n, t = o.shape[0], DAY_MIN // res
    shape = (n, t, res)
    with np.errstate(all="ignore"):
        hh = np.nanmax(h.reshape(shape), axis=2)
        ll = np.nanmin(l.reshape(shape), axis=2)
    oo = np.full((n, t), np.nan)
    cc = np.full((n, t), np.nan)
    for j in range(res - 1, -1, -1):          # first valid open in each bar
        col = o.reshape(shape)[:, :, j]
        oo = np.where(~np.isnan(col), col, oo)
    for j in range(res):                        # last valid close in each bar
        col = c.reshape(shape)[:, :, j]
        cc = np.where(~np.isnan(col), col, cc)
    return oo, hh, ll, cc


def _first_true(mask: np.ndarray) -> np.ndarray:
    any_ = mask.any(1)
    return np.where(any_, mask.argmax(1), -1)


def _next_valid_index(o: np.ndarray) -> np.ndarray:
    t = o.shape[1]
    idx = np.where(~np.isnan(o), np.arange(t)[None, :], t)
    return np.minimum.accumulate(idx[:, ::-1], axis=1)[:, ::-1]


def simulate(data: dict, v: Variant) -> dict:
    idx, d, or_hi, or_lo = select(data, v)
    res = v.resolution
    if len(idx) == 0:
        return {"n": 0}
    grid = data["grid"][idx]
    o, h, l, c = _bars(grid, res)
    n, t = o.shape
    ar = np.arange(n)
    tt = np.arange(t)[None, :]
    nxt = _next_valid_index(o)
    slip = v.slip_ticks * TICK
    win_end = v.window_end_min // res
    or_end = v.or_minutes // res
    eod = EOD_MIN // res

    # ---- entry ------------------------------------------------------------
    if v.entry == "close":
        o5, h5, l5, c5 = _bars(grid, 5) if res != 5 else (o, h, l, c)
        b = np.arange(DAY_MIN // 5)[None, :]
        sig = ((d[:, None] > 0) & (c5 > or_hi[:, None])) | ((d[:, None] < 0) & (c5 < or_lo[:, None]))
        sig &= (b >= v.or_minutes // 5) & (b < v.window_end_min // 5)
        sb = _first_true(sig)
        has = sb >= 0
        start = np.where(has, (sb + 1) * 5 // res, t - 1)
        start = np.minimum(start, t - 1)
        ent_i = nxt[ar, start]
        has &= ent_i < eod
        ent_i = np.where(has, ent_i, 0)
        fill = o[ar, ent_i] + d * slip
    else:
        level = np.where(d > 0, or_hi + TICK, or_lo - TICK)
        trig = np.where(d[:, None] > 0, h >= level[:, None], l <= level[:, None])
        trig &= (tt >= or_end) & (tt < win_end)
        ent_i = _first_true(trig)
        has = ent_i >= 0
        ent_i = np.where(has, ent_i, 0)
        op = o[ar, ent_i]
        base = np.where(d > 0, np.fmax(level, op), np.fmin(level, op))
        fill = base + d * slip

    keep = has & ~np.isnan(fill)
    sel = np.flatnonzero(keep)
    o, h, l, c, d, fill, ent_i, nxt = o[sel], h[sel], l[sel], c[sel], d[sel], fill[sel], ent_i[sel], nxt[sel]
    or_hi, or_lo = or_hi[sel], or_lo[sel]
    gidx = idx[sel]
    n = len(sel)
    ar = np.arange(n)
    if n == 0:
        return {"n": 0}

    # ---- stop / target ------------------------------------------------------
    if v.stop_kind == "atr":
        dist = v.stop_atr * data["prev_atr"][gidx]
        stop = fill - d * dist
    else:
        stop = np.where(d > 0, or_lo - TICK, or_hi + TICK)
        dist = d * (fill - stop)
        bad = dist <= 0
        dist = np.where(bad, np.nan, dist)
    if v.min_stop_usd > 0:                       # cost control: costs are fixed in cents per share
        dist = np.where(dist >= v.min_stop_usd, dist, np.nan)
    target = fill + d * v.target_r * dist if v.target_r else None

    after = tt > ent_i[:, None]
    on_entry = tt == ent_i[:, None]
    before_eod = tt < eod
    hit_stop_bar = np.where(d[:, None] > 0, l <= stop[:, None], h >= stop[:, None])
    stop_mask = hit_stop_bar & before_eod & (after | on_entry)
    s_i = _first_true(stop_mask)

    if v.breakeven_r:
        be_level = fill + d * v.breakeven_r * dist
        reach = np.where(d[:, None] > 0, h >= be_level[:, None], l <= be_level[:, None]) & after & before_eod
        r_i = _first_true(reach)
        be_stop = fill + d * 2 * COMMISSION        # breakeven after commissions
        be_hit = np.where(d[:, None] > 0, l <= be_stop[:, None], h >= be_stop[:, None])
        be_mask = be_hit & before_eod & (tt > r_i[:, None]) & (r_i[:, None] >= 0)
        be_i = _first_true(be_mask)
        use_be = (be_i >= 0) & ((s_i < 0) | (be_i < s_i))
    if target is not None:
        tgt_mask = np.where(d[:, None] > 0, h >= target[:, None], l <= target[:, None]) & after & before_eod
        t_i = _first_true(tgt_mask)
    else:
        t_i = np.full(n, -1)

    big = t + 1
    s_k = np.where(s_i >= 0, s_i, big)
    t_k = np.where(t_i >= 0, t_i, big)
    b_k = np.where(use_be, be_i, big) if v.breakeven_r else np.full(n, big)
    first = np.minimum(np.minimum(s_k, t_k), b_k)

    exit_px = np.full(n, np.nan)
    reason = np.full(n, "EOD", dtype="U8")
    # stop (stop wins ties)
    m = (s_k == first) & (s_k < big)
    op = o[ar, np.where(m, s_k, 0)]
    gap_through = m & (s_k > ent_i) & (np.where(d > 0, op <= stop, op >= stop))
    px = np.where(gap_through, op, stop) - d * slip
    exit_px = np.where(m, px, exit_px)
    reason = np.where(m, np.where(gap_through, "STOPGAP", "STOP"), reason)
    # breakeven stop
    if v.breakeven_r:
        mb = ~m & (b_k == first) & (b_k < big)
        opb = o[ar, np.where(mb, b_k, 0)]
        be_px = np.where(np.where(d > 0, opb <= be_stop, opb >= be_stop), opb, be_stop) - d * slip
        exit_px = np.where(mb, be_px, exit_px)
        reason = np.where(mb, "BE", reason)
        m = m | mb
    # target
    mt = ~m & (t_k == first) & (t_k < big)
    if target is not None:
        opt = o[ar, np.where(mt, t_k, 0)]
        tgt_px = np.where(np.where(d > 0, opt >= target, opt <= target), opt, target)
        exit_px = np.where(mt, tgt_px, exit_px)
        reason = np.where(mt, "TARGET", reason)
    # end of day
    me = np.isnan(exit_px)
    eod_i = nxt[ar, np.minimum(eod, t - 1)]
    eod_open = np.where(eod_i < t, o[ar, np.minimum(eod_i, t - 1)], np.nan)
    last_close = _last_valid(c, 0, t)
    eod_px = np.where(np.isnan(eod_open), last_close, eod_open) - d * slip
    exit_px = np.where(me, eod_px, exit_px)

    pnl = d * (exit_px - fill) - 2 * COMMISSION
    r = pnl / dist
    gross_r = d * (exit_px - fill) / dist                              # after slippage, before commission
    exit_slip = np.where(reason == "TARGET", 0.0, slip)
    frictionless_r = (d * (exit_px - fill) + slip + exit_slip) / dist   # no slippage, no commission
    ok = ~np.isnan(r)
    return {
        "n": int(ok.sum()), "idx": gidx[ok], "r": r[ok], "dir": d[ok], "reason": reason[ok],
        "dkey": data["dkey"][gidx[ok]], "tick": data["tick"][gidx[ok]], "entry_i": ent_i[ok] * res,
        "fill": fill[ok], "exit": exit_px[ok], "dist": dist[ok], "gross_r": gross_r[ok],
        "frictionless_r": frictionless_r[ok],
    }


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------
def metrics(res: dict) -> dict:
    if not res.get("n"):
        return {"trades": 0}
    r, dk = res["r"], res["dkey"]
    wins = r[r > 0]
    losses = -r[r <= 0]
    month = dk // 100
    year = dk // 10000
    m_keys, m_inv = np.unique(month, return_inverse=True)
    m_sum = np.bincount(m_inv, weights=r)
    y_keys, y_inv = np.unique(year, return_inverse=True)
    y_sum = np.bincount(y_inv, weights=r)
    d_keys, d_inv = np.unique(dk, return_inverse=True)
    d_sum = np.bincount(d_inv, weights=r)
    curve = np.cumsum(d_sum)
    dd = float((curve - np.maximum.accumulate(np.r_[0.0, curve])[1:]).min())
    sharpe = float(d_sum.mean() / d_sum.std() * np.sqrt(252)) if d_sum.std() > 0 else float("nan")
    return {
        "trades": int(len(r)), "trades_per_day": float(len(r) / len(d_keys)),
        "win_rate": float(100 * (r > 0).mean()), "avg_r": float(r.mean()), "median_r": float(np.median(r)),
        "total_r": float(r.sum()), "pf": float(wins.sum() / losses.sum()) if losses.sum() > 0 else float("inf"),
        "pos_months": f"{int((m_sum > 0).sum())}/{len(m_sum)}", "pos_years": f"{int((y_sum > 0).sum())}/{len(y_sum)}",
        "by_year": {int(k): round(float(s), 1) for k, s in zip(y_keys, y_sum)},
        "max_dd_r": dd, "sharpe_daily": sharpe,
    }


def fmt(name: str, m: dict) -> str:
    if not m.get("trades"):
        return f"{name:<34} no trades"
    years = " ".join(f"{y % 100:02d}:{s:+7.1f}" for y, s in m["by_year"].items())
    return (f"{name:<34} {m['trades']:>6} {m['win_rate']:5.1f}% {m['avg_r']:+6.3f} {m['pf']:5.2f} "
            f"{m['pos_months']:>6} {m['sharpe_daily']:+5.2f}  {years}")


HEADER = f"{'variant':<34} {'trades':>6} {'win%':>6} {'avgR':>6} {'PF':>5} {'+mo':>6} {'shrp':>5}  by-year total R"
