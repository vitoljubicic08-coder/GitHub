#!/usr/bin/env python3
"""Run the pre-registered round-2 grid (SHORTLIST_2.md) and write every combination's result.

Usage:
  python3 backtest/run_grid.py --cache <inst cache> --period dev --out backtest/grid_dev.csv
  python3 backtest/run_grid.py --cache <inst cache> --period holdout --only finalists.json --out ...
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

TICKERS = ["SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "TLT", "USO", "XLE", "XLF", "SMH",
           "AAPL", "NVDA", "TSLA", "AMZN", "MSFT", "META", "AMD"]
FAMILIES = ([("vwap_fade", k) for k in (1.5, 2.0, 2.5, 3.0)] + [("vwap_break", k) for k in (1.0, 1.5, 2.0)]
            + [("noise_fade", k) for k in (1.0, 1.5, 2.0, 2.5)] + [("noise_break", k) for k in (1.0, 1.5)]
            + [("orb", m) for m in (5, 15, 30)] + [("orb_fail", m) for m in (5, 15, 30)]
            + [("rsi", (2, 5, 95)), ("rsi", (14, 25, 75))] + [("gap_fade", g) for g in (0.005, 0.01)]
            + [("vwap_pullback", 0)])
STOPS = (0.1, 0.2, 0.3)
MAX_TRADES = (1, 2)
PERIODS = {"dev": (20230301, 20241231), "holdout": (20250101, 20260331), "all": (0, 99999999)}


def key(ticker, family, param, stop, mt, rr) -> str:
    return f"{ticker}|{family}|{json.dumps(param)}|{stop}|{mt}|{rr}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--period", choices=PERIODS, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="JSON list of combination keys to run (holdout)")
    args = ap.parse_args()
    only = set(json.load(open(args.only))) if args.only else None
    start, end = PERIODS[args.period]
    t0 = time.time()
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["key", "ticker", "family", "param", "stop_atr", "max_trades", "rr", "trades", "win_rate",
                    "avg_r", "pf", "total_r", "pos_months", "months", "by_year"])
        for tk in TICKERS:
            if only is not None and not any(k.startswith(tk + "|") for k in only):
                continue
            full = il.load_instrument(args.cache, tk)
            mask = (full["dkey"] >= start) & (full["dkey"] <= end)
            d = il.subset(full, start, end)
            for fam, param in FAMILIES:
                sig_full = il.signals(full, fam, param)
                sig = sig_full[mask]
                for stop in STOPS:
                    for mt in MAX_TRADES:
                        if only is not None and not any(key(tk, fam, param, stop, mt, rr) in only for rr in il.RRS):
                            continue
                        res = il.trades(d, sig, stop, max_trades=mt)
                        for rr in il.RRS:
                            k = key(tk, fam, param, stop, mt, rr)
                            if only is not None and k not in only:
                                continue
                            r, dk = res[rr]
                            s = il.stats(r, dk)
                            if not s["n"]:
                                continue
                            w.writerow([k, tk, fam, json.dumps(param), stop, mt, rr, s["n"], round(s["win"], 2),
                                        round(s["avg"], 4), round(s["pf"], 3), round(float(r.sum()), 2),
                                        s["pos_months"], s["months"], json.dumps({y: round(v, 1) for y, v in s["by_year"].items()})])
            print(f"{tk} done ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
