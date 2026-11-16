#!/usr/bin/env python3
"""Round 3: score strategy combinations by the chance of passing a prop-firm evaluation in one month.

Evaluation model ($50K): profit target +$3,000, trailing drawdown $2,000 (follows the highest closed
balance, stops trailing at the starting balance), 21 trading days, trades in the order they happen,
at most 2 trades per day. A month is simulated by drawing 21 random trading days (with replacement)
from the period's own days, including days without a signal. Risk per trade is chosen from RISKS on
the development period and then kept fixed for the holdout.

Usage:
  python3 backtest/run_grid3.py --cache <inst cache> --period dev --out backtest/grid3_dev.csv
  python3 backtest/run_grid3.py --cache <inst cache> --period holdout --only finalists.json --risk-from grid3_dev.csv --out ...
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday_lab as il  # noqa: E402
from run_grid import FAMILIES as BASE_FAMILIES, TICKERS  # noqa: E402

FAMILIES = BASE_FAMILIES + [("pd_sweep", 0), ("pd_break", 0), ("fvg", 1.5), ("fvg", 2.0), ("fvg_sb", 1.5),
                            ("fvg_sb", 2.0), ("delta_div", 0.25), ("delta_div", 0.5), ("orb", 60), ("orb_fail", 60)]
STOPS = (0.1, 0.2, 0.3)
MAX_TRADES = (1, 2)
RISKS = (150, 250, 350, 500, 750)
START, DD, TARGET, DAYS = 50000.0, 2000.0, 3000.0, 21
PERIODS = {"dev": (20230301, 20241231), "holdout": (20250101, 20260331)}


def key(ticker, family, param, stop, mt, rr) -> str:
    return f"{ticker}|{family}|{json.dumps(param)}|{stop}|{mt}|{rr}"


def day_slots(r: np.ndarray, dk: np.ndarray, all_days: np.ndarray, width: int = 2) -> np.ndarray:
    """(n_days, width) array of R per trade slot for every trading day (0 = no trade)."""
    pos = {int(k): i for i, k in enumerate(all_days)}
    slots = np.zeros((len(all_days), width))
    fill = np.zeros(len(all_days), dtype=int)
    for x, k in zip(r, dk):
        i = pos[int(k)]
        if fill[i] < width:
            slots[i, fill[i]] = x
            fill[i] += 1
    return slots


def pass_prob(slots: np.ndarray, risk: float, rng: np.random.Generator, n_sims: int = 2000) -> float:
    idx = rng.integers(len(slots), size=(n_sims, DAYS))
    steps = slots[idx].reshape(n_sims, -1) * risk
    bal = START + np.cumsum(steps, axis=1)
    peak = np.maximum(np.maximum.accumulate(bal, axis=1), START)
    floor = np.minimum(peak - DD, START)
    fail, win = bal <= floor, bal >= START + TARGET
    first_fail = np.where(fail.any(1), fail.argmax(1), 10 ** 6)
    first_win = np.where(win.any(1), win.argmax(1), 10 ** 6)
    return float(np.mean(first_win < first_fail))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--period", choices=PERIODS, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only")
    ap.add_argument("--risk-from", help="dev CSV whose chosen risk is reused (holdout)")
    args = ap.parse_args()
    only = set(json.load(open(args.only))) if args.only else None
    fixed_risk = {}
    if args.risk_from:
        fixed_risk = {r["key"]: float(r["best_risk"]) for r in csv.DictReader(open(args.risk_from)) if r["best_risk"]}
    start, end = PERIODS[args.period]
    rng = np.random.default_rng(2026)
    t0 = time.time()
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "ticker", "family", "param", "stop_atr", "max_trades", "rr", "trades", "win_rate", "avg_r",
                    "pf", "by_year", "eligible", "best_risk", "pass_prob"])
        for tk in TICKERS:
            if only is not None and not any(k.startswith(tk + "|") for k in only):
                continue
            full = il.load_instrument(args.cache, tk)
            mask = (full["dkey"] >= start) & (full["dkey"] <= end)
            d = il.subset(full, start, end)
            for fam, param in FAMILIES:
                sig = il.signals(full, fam, param)[mask]
                for stop in STOPS:
                    for mt in MAX_TRADES:
                        keys = [key(tk, fam, param, stop, mt, rr) for rr in il.RRS]
                        if only is not None and not any(k in only for k in keys):
                            continue
                        res = il.trades(d, sig, stop, max_trades=mt)
                        for rr, k in zip(il.RRS, keys):
                            if only is not None and k not in only:
                                continue
                            r, dk = res[rr]
                            s = il.stats(r, dk)
                            if not s["n"]:
                                continue
                            by = s["by_year"]
                            eligible = (s["n"] >= 150 and s["avg"] > 0 and by.get(2023, 0) > 0 and by.get(2024, 0) > 0)
                            best_risk, best_p = "", ""
                            if eligible or only is not None:
                                slots = day_slots(r, dk, d["dkey"])
                                risks = (fixed_risk[k],) if k in fixed_risk else RISKS
                                pp = [(pass_prob(slots, rk, rng), rk) for rk in risks]
                                best_p, best_risk = max(pp)
                            w.writerow([k, tk, fam, json.dumps(param), stop, mt, rr, s["n"], round(s["win"], 2),
                                        round(s["avg"], 4), round(s["pf"], 3),
                                        json.dumps({y: round(v, 1) for y, v in by.items()}), int(eligible),
                                        best_risk, "" if best_p == "" else round(best_p, 4)])
            print(f"{tk} done ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
