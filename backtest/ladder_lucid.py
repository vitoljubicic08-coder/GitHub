#!/usr/bin/env python3
"""Faster first payouts with the same per-account odds: run several LucidFlex accounts at once, staggered.

Every account is traded exactly like backtest_10y_steady.py (steady setting, bot rules, trade until the
limit). A "program" starts on day t0 and runs 12 months (252 trading days):
  sequential   one account at a time; a new one the day after one ends
  ladder K     a new account every 21 trading days until K are running; whenever one ends it is
               replaced the next day (LucidFlex allows 10 evaluations / 5 funded accounts at once)
Programs are started on every 5th trading day of 2016-01 .. 2025-03 (the last start with 12 months
after it), on real history in date order (no resampling).

  python3 backtest/ladder_lucid.py --inst <10-year cache> [--today-vol]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import intraday_lab as il  # noqa: E402
import backtest_10y_steady as bt  # noqa: E402

H, STAGGER = 252, 21


def one_account(pool, i0):
    """Trade one account from day i0. Returns (end_day or None, [(day, amount)])."""
    a = {"phase": "eval", "P": 0.0, "peak": 0.0, "floor": -bt.MLL, "fixed": False, "best": 0.0, "win": 0, "cyc": 0.0}
    pays = []
    for i in range(i0, pool["n"]):
        if a["phase"] == "eval_passed":
            a.update(phase="funded", P=0.0, peak=0.0, floor=-bt.MLL, fixed=False)
        day = 0.0
        for j in (1, 2):
            if not pool[f"has{j}"][i]:
                continue
            dpr = pool[f"dpr{j}"][i]
            cap = 40 if a["phase"] == "eval" else (20 if a["P"] < 1000 else 30 if a["P"] < 2000 else 40)
            c, rpc = bt.contracts(dpr, cap)
            if c < 1:
                continue
            worst = c * (rpc + bt.GAP_USD)
            if day - worst < -bt.DAILY_LOSS:
                continue
            if a["phase"] == "eval" and day + c * (bt.RR * dpr - bt.COMM - bt.SLIP_TICKS * bt.TICK_USD) > bt.CONS * bt.TARGET:
                continue
            if a["P"] + day + c * pool[f"lo{j}"][i] * dpr - c * bt.COMM / 2 <= a["floor"]:
                return i, pays
            day += c * (pool[f"r{j}"][i] * dpr - bt.COMM)
        a["P"] += day
        if not a["fixed"]:
            a["peak"] = max(a["peak"], a["P"])
            a["floor"] = max(a["floor"], min(a["peak"] - bt.MLL, bt.LOCK))
        if a["phase"] == "eval":
            a["best"] = max(a["best"], day)
            if a["P"] >= bt.TARGET and a["best"] <= bt.CONS * a["P"]:
                a["phase"] = "eval_passed"
        else:
            a["cyc"] += day
            a["win"] += day >= bt.WIN_DAY
            amt = min(0.5 * a["P"], bt.PAY_CAP, a["P"] - bt.LOCK - bt.KEEP)
            if a["win"] >= bt.WIN_DAYS and a["cyc"] > 0 and amt >= bt.PAY_MIN:
                pays.append((i, amt))
                a.update(P=a["P"] - amt, fixed=True, floor=bt.LOCK, win=0, cyc=0.0)
                if len(pays) >= bt.MAX_PAY:
                    return i, pays
    return None, pays


def program(acc, t0, k):
    """acc[i] = precomputed one_account result for a start on day i. Returns (first payout day, fees, cash)."""
    end_t = t0 + H
    starts = [t0 + STAGGER * m for m in range(k) if t0 + STAGGER * m < end_t] if k > 1 else [t0]
    queue, fees, cash, first = list(starts), 0.0, 0.0, None
    while queue:
        s = queue.pop(0)
        if s >= end_t:
            continue
        fees += bt.FEE
        e, pays = acc[s]
        for dday, amt in pays:
            if dday < end_t:
                cash += amt * bt.SPLIT - bt.XFER
                first = dday if first is None else min(first, dday)
        if e is not None and e + 1 < end_t:
            queue.append(e + 1)
            queue.sort()
    return first, fees, cash


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    ap.add_argument("--today-vol", action="store_true")
    a = ap.parse_args()
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    d = il.load_instrument(a.inst, "QQQ")
    _, pool = bt.build(d, a.today_vol)
    acc = [one_account(pool, i) for i in range(pool["n"])]
    dk = d["dkey"]
    t0s = [i for i in range(0, pool["n"] - H, 5) if 20160101 <= dk[i] <= 20250331]
    out = {}
    print(f"{'program':12s} {'paid<=3m':>8s} {'paid<=6m':>8s} {'paid<=12m':>9s} {'median months to 1st payout':>28s} "
          f"{'fees 12m':>9s} {'net 12m mean':>12s} {'net 12m median':>14s} {'net per $1 fees':>15s}")
    for name, k in (("sequential", 1), ("ladder 2", 2), ("ladder 3", 3), ("ladder 5", 5)):
        res = [program(acc, t0, k) for t0 in t0s]
        first = np.array([(f - t0) if f is not None else np.nan for (f, _, _), t0 in zip(res, t0s)])
        fees = np.array([r[1] for r in res])
        net = np.array([r[2] - r[1] for r in res])
        row = {"paid_3m": float(np.mean(first < 63)), "paid_6m": float(np.mean(first < 126)), "paid_12m": float(np.mean(~np.isnan(first))),
               "median_months_to_first": float(np.nanmedian(first) / 21), "fees_mean": float(fees.mean()),
               "net_mean": float(net.mean()), "net_median": float(np.median(net)),
               "net_per_fee": float(net.mean() / fees.mean()), "p_ahead": float((net > 0).mean())}
        out[name] = row
        print(f"{name:12s} {100 * row['paid_3m']:7.0f}% {100 * row['paid_6m']:7.0f}% {100 * row['paid_12m']:8.0f}% "
              f"{row['median_months_to_first']:28.1f} {row['fees_mean']:9.0f} {row['net_mean']:+12.0f} {row['net_median']:+14.0f} "
              f"{row['net_per_fee']:15.2f}   ahead {100 * row['p_ahead']:.0f}%")
    out["program_starts"] = len(t0s)
    name = "ladder_lucid" + ("_todayvol" if a.today_vol else "") + ".json"
    (HERE / "results_round5" / name).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
