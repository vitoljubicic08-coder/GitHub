#!/usr/bin/env python3
"""Round 9 lab: top/bottom ticking with standard deviations and ICT OTE, on gold (GLD -> Micro Gold MGC)
and the Nasdaq (QQQ -> MNQ). SHORTLIST_9.md.

Families (signals on 5-minute closes, entries at the next bar's open unless a limit is given):
  vwap_close k     a close beyond VWAP +/- k volume-weighted SD -> fade (after 10:00, signal bars to 14:50)
  vwap_reject k    the bar trades beyond VWAP +/- k SD but closes back inside -> fade
  orsd_reject k    the bar trades beyond the 09:30-10:00 range extreme +/- k x range (ICT SD projection)
                   and closes back inside -> fade
  ote e x          ICT optimal trade entry: first-hour impulse (direction of the 10:30 close vs the open,
                   leg = first-hour low..high); after 10:30 a limit at e retracement of the leg, working
                   until 14:30; stop beyond the leg's origin; target the leg's end + x of the leg
Stops: "bar" = beyond the signal bar's extreme (+0.02 ATR; the top/bottom-tick stop), or an ATR multiple.
Targets: "vwap" / "ormid" (variable, clipped to 0.5-4R) or a fixed R.
"""
from __future__ import annotations

import numpy as np

import lab8

BARS = np.arange(78)
FUT = {"GLD": {"name": "MGC", "usd_per": 10.8 * 10.0, "tick": 0.10 / 10.8, "comm_rt": 1.60},
       "QQQ": {"name": "MNQ", "usd_per": 41.3 * 2.0, "tick": 0.25 / 41.3, "comm_rt": 1.50}}


def _window(sig):
    sig[:, :6] = 0                     # after 10:00
    sig[:, 65:] = 0                    # signal bars opening by 14:50
    return sig


def signals9(d: dict, family: str, k: float):
    c5, h5, l5 = d["c5"], d["h5"], d["l5"]
    sig = np.zeros(c5.shape, np.int8)
    with np.errstate(invalid="ignore"):
        if family in ("vwap_close", "vwap_reject"):
            up = d["vwap5"] + k * d["vsd5"]
            dn = d["vwap5"] - k * d["vsd5"]
        else:                                                   # orsd_reject
            hi = np.nanmax(h5[:, :6], 1)[:, None]
            lo = np.nanmin(l5[:, :6], 1)[:, None]
            up, dn = hi + k * (hi - lo), lo - k * (hi - lo)
        if family == "vwap_close":
            short, long_ = c5 > up, c5 < dn
        else:
            short, long_ = (h5 >= up) & (c5 < up), (l5 <= dn) & (c5 > dn)
    sig[short], sig[long_] = -1, 1
    sig[short & long_] = 0
    sig[~d["has5"]] = 0
    return _window(sig)


def bar_stop(d, sig):
    buf = 0.02 * d["atr_prev"][:, None]
    return np.where(sig < 0, d["h5"] + buf, np.where(sig > 0, d["l5"] - buf, np.nan))


def target_levels(d, sig, kind):
    if kind == "vwap":
        lvl = d["vwap5"]
    else:                                                       # ormid
        with np.errstate(all="ignore"):
            lvl = np.broadcast_to(((np.nanmax(d["h5"][:, :6], 1) + np.nanmin(d["l5"][:, :6], 1)) / 2)[:, None], sig.shape)
    return np.where(sig != 0, lvl, np.nan)


def ote(d, e: float, x: float):
    """Signal at the 10:30 close (bar 11) in the first hour's direction; limit/stop/target arrays."""
    n = len(d["dkey"])
    sig = np.zeros((n, 78), np.int8)
    with np.errstate(invalid="ignore"):
        hi = np.nanmax(d["h5"][:, :12], 1)
        lo = np.nanmin(d["l5"][:, :12], 1)
        dirn = np.sign(d["c5"][:, 11] - d["day_open"])
    leg = hi - lo
    buf = 0.02 * d["atr_prev"]
    ok = (dirn != 0) & (leg > 0) & d["has5"][:, 11]
    sig[ok, 11] = dirn[ok].astype(np.int8)
    full = lambda v: np.where(sig != 0, v[:, None], np.nan)    # noqa: E731
    lim = full(np.where(dirn > 0, hi - e * leg, lo + e * leg))
    stp = full(np.where(dirn > 0, lo - buf, hi + buf))
    tgt = full(np.where(dirn > 0, hi + x * leg, lo - x * leg))
    return sig, lim, stp, tgt


def run(d: dict, tk: str, cfg: dict, cost: bool = True) -> dict:
    f = FUT[tk]
    fam = cfg["family"]
    kw = {"slip": f["tick"], "tick": f["tick"], "rr_floor": 0.5, "rr_cap": 4.0}
    if fam == "ote":
        sig, lim, stp, tgt = ote(d, cfg["e"], cfg["x"])
        t = lab8.bracket8(d, sig, lim=lim, stp_lvl=stp, tgt_lvl=tgt, window=240, max_trades=1, **kw)
    else:
        sig = signals9(d, fam, cfg["k"])
        stp = bar_stop(d, sig) if cfg["stop"] == "bar" else None
        tgt = target_levels(d, sig, cfg["target"]) if isinstance(cfg["target"], str) else None
        rr = cfg["target"] if not isinstance(cfg["target"], str) else 1.0
        t = lab8.bracket8(d, sig, rr=rr, stop_atr=0.2 if cfg["stop"] != "bar" else 0.3, stp_lvl=stp, tgt_lvl=tgt,
                          max_trades=2, **kw)
    if cost and len(t["r"]):
        price_dist = t["dist"] * d["atr_prev"][t["day"].astype(int)]
        t["r"] = t["r"] - f["comm_rt"] / (price_dist * f["usd_per"])
    return t


def configs():
    out = []
    for fam in ("vwap_close", "vwap_reject"):
        for k in (2.0, 2.5, 3.0):
            for stop in ("bar", 0.2):
                for target in ("vwap", 1.0, 2.0):
                    out.append({"family": fam, "k": k, "stop": stop, "target": target})
    for k in (2.0, 2.5, 4.0):
        for stop in ("bar", 0.2):
            for target in ("ormid", 1.0, 2.0):
                out.append({"family": "orsd_reject", "k": k, "stop": stop, "target": target})
    for e in (0.705, 0.618):
        for x in (0.0, 0.27):
            out.append({"family": "ote", "e": e, "x": x})
    return out
