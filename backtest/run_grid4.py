#!/usr/bin/env python3
"""Run the pre-registered round-4 grid (SHORTLIST_4.md) and write every combination's aggregates.

Usage:
  python3 backtest/run_grid4.py --cache <inst cache> --period dev --out backtest/grid4_dev.csv
  python3 backtest/run_grid4.py --cache <inst cache> --period holdout --only finalists4.json --out ...
Pooled ("ALL|...") rows are built later by summing the per-instrument aggregates (select4.py).
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday_lab as il  # noqa: E402
import lab4  # noqa: E402
from run_grid import TICKERS  # noqa: E402

A4 = (0.1, 0.2, 0.3, 0.5)
S4 = A4 + ("struct",)
NB3_FILTERS = ("none", "vwap", "trend", "gap_with", "gap_against", "rvol", "atr_lo", "atr_hi", "nr7", "pdbrk",
               "early", "late", "spy")
SMT_PAIRS = (("QQQ", "SPY"), ("SPY", "QQQ"), ("SPY", "DIA"), ("DIA", "SPY"), ("IWM", "SPY"), ("SPY", "IWM"),
             ("SMH", "QQQ"), ("QQQ", "SMH"), ("NVDA", "SMH"), ("AMD", "SMH"), ("XLF", "SPY"), ("AAPL", "QQQ"),
             ("MSFT", "QQQ"))
COLS = ["key", "ticker", "family", "param", "stop", "max_trades", "rr", "n", "wins", "tgts", "stops", "sum_r",
        "sum_r2", "gross_win", "gross_loss", "by_year"]


def settings():
    """(family, param, stops, max_trades options) exactly as pre-registered."""
    s = [("crt", m, S4, (1, 2)) for m in (30, 60)]
    s += [("pdsw", None, S4, (1, 2))]
    s += [("judas", k, S4, (1,)) for k in (0.5, 1.0)]
    s += [("ict22", [lv, w], S4, (1, 2)) for lv in ("pd", "or30") for w in ("am", "all")]
    s += [("nrorb", [f, m], S4, (1,)) for f in ("nr7", "nr4", "inside") for m in (5, 15, 30)]
    s += [("orbrv", [k, mode], S4, (1,)) for k in (1.5, 2.0, 3.0) for mode in ("bar0", "brk")]
    s += [("turtle", n, S4, (1,)) for n in (10, 20)]
    s += [("va80", k, S4, (1,)) for k in (2, 6)]
    s += [("hgrail", x, S4, (1, 2)) for x in (0.0, 0.02)]
    s += [("lhh", [kind, th], (0.05, 0.1, 0.2), (1,)) for kind in ("fh", "day") for th in (0.0, 0.005)]
    s += [("gapgo", g, S4, (1,)) for g in (0.005, 0.01)]
    s += [("odrive", k, S4, (1,)) for k in (0.25, 0.4)]
    s += [("nb3", [f, mode], (0.2, 0.3, 0.5), (1,)) for f in NB3_FILTERS for mode in ("first", "pass")]
    return s


def key(ticker, family, param, stop, mt, rr) -> str:
    return f"{ticker}|{family}|{json.dumps(param)}|{stop}|{mt}|{rr}"


def load(cache, tk) -> dict:
    return lab4.enrich(il.load_instrument(cache, tk))


def attach_ref(d: dict, ref: dict) -> None:
    """Reference instrument's 5-minute closes and open on the same sessions (NaN where it has no session)."""
    pos = {int(k): i for i, k in enumerate(ref["dkey"])}
    idx = np.array([pos.get(int(k), -1) for k in d["dkey"]])
    d["ref_c5"] = np.where((idx >= 0)[:, None], ref["c5"][np.maximum(idx, 0)], np.nan)
    d["ref_open"] = np.where(idx >= 0, ref["day_open"][np.maximum(idx, 0)], np.nan)


def rows_for(tk, d, fam, param, sig, lvl, stops, mts, only, last_entry=330):
    out = []
    for stop in stops:
        if stop == "struct" and lvl is None:
            continue
        for mt in mts:
            keys = [key(tk, fam, param, stop, mt, rr) for rr in lab4.RRS4]
            if only is not None and not any(k in only for k in keys):
                continue
            res = lab4.bracket(d, sig, stop, lvl, max_trades=mt, last_entry_min=last_entry)
            for rr, k in zip(lab4.RRS4, keys):
                s = lab4.summary(res[rr], d["dkey"])
                if not s["n"]:
                    continue
                out.append([k, tk, fam, json.dumps(param), stop, mt, rr, s["n"], s["wins"], s["tgts"], s["stops"],
                            round(s["sum_r"], 5), round(s["sum_r2"], 5), round(s["gross_win"], 5),
                            round(s["gross_loss"], 5), json.dumps({y: round(v, 3) for y, v in s["by_year"].items()})])
    return out


def wanted(only, tk, fam, param):
    if only is None:
        return True
    pre = f"{fam}|{json.dumps(param)}|"
    return any(k.split("|", 1)[1].startswith(pre) and k.split("|")[0] in (tk, "ALL") for k in only)


def work(job):
    cache, tk, period, only = job
    import warnings
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    only = set(only) if only is not None else None
    if only is not None:              # pooled finalists need every instrument
        only = {k.replace("ALL|", tk + "|", 1) if k.startswith("ALL|") else k for k in only}
    start, end = lab4.PERIODS[period]
    full = load(cache, tk)
    attach_ref(full, load(cache, "QQQ" if tk == "SPY" else "SPY"))
    d = lab4.subset(full, start, end)
    rows = []
    for fam, param, stops, mts in settings():
        if not wanted(only, tk, fam, param):
            continue
        p = tuple(param) if isinstance(param, list) else param
        sig, lvl = lab4.signals4(d, fam, p)
        rows += rows_for(tk, d, fam, param, sig, lvl, stops, mts, only, 370 if fam == "lhh" else 330)
    for a, b in SMT_PAIRS:
        if a != tk:
            continue
        for kind in ("sess", "pd"):
            param = [kind, b]
            if not wanted(only, tk, "smt", param):
                continue
            fa, fb = lab4.align(full, load(cache, b))
            da, db = lab4.subset(fa, start, end), lab4.subset(fb, start, end)
            sig, lvl = lab4.smt_signals(da, db, kind)
            rows += rows_for(tk, da, "smt", param, sig, lvl, S4, (1, 2), only)
    return tk, rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--period", choices=lab4.PERIODS, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="JSON list of keys (holdout run of the finalists)")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    only = json.load(open(args.only)) if args.only else None
    t0 = time.time()
    jobs = [(args.cache, tk, args.period, only) for tk in TICKERS]
    with open(args.out, "w", newline="") as f, Pool(args.workers) as pool:
        w = csv.writer(f)
        w.writerow(COLS)
        for tk, rows in pool.imap_unordered(work, jobs):
            w.writerows(rows)
            f.flush()
            print(f"{tk}: {len(rows)} rows ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
