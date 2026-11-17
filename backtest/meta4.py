#!/usr/bin/env python3
"""Round 4 meta-labeling (SHORTLIST_4.md): can a model learn WHICH setups reach 3R before the stop?

Stage "dev": builds the event pool (16 base settings x 18 instruments, 1:3), trains gradient-boosted
trees with 4 expanding-window time folds and reports out-of-fold results and the two thresholds.
Stage "holdout": refits on all development events and scores the holdout ONCE.

  python3 backtest/meta4.py --cache <inst> --stage dev
  python3 backtest/meta4.py --cache <inst> --stage holdout
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import intraday_lab as il  # noqa: E402
import lab4  # noqa: E402
from run_grid import TICKERS  # noqa: E402
from run_grid4 import attach_ref, load  # noqa: E402

BASE = [("crt", 30, "struct"), ("crt", 60, "struct"), ("pdsw", None, "struct"), ("judas", 0.5, "struct"),
        ("ict22", ("pd", "all"), "struct"), ("ict22", ("or30", "am"), "struct"), ("nrorb", ("nr7", 15), 0.2),
        ("orbrv", (1.5, "bar0"), "struct"), ("orbrv", (1.5, "brk"), "struct"), ("turtle", 10, "struct"),
        ("turtle", 20, "struct"), ("va80", 2, "struct"), ("hgrail", 0.0, "struct"), ("gapgo", 0.005, "struct"),
        ("odrive", 0.25, "struct"), ("nb3", ("none", "first"), 0.3)]
FEATURES = ["setting", "instrument", "bar", "dirn", "gap_atr", "atr_pct", "atr_ratio", "prev_rng_atr", "nr7", "nr4",
            "inside", "trend", "vwap_z", "noise_z", "rvol_cum", "rvol_bar0", "range_atr", "pos_in_range",
            "prev_ret", "weekday", "monthday", "stop_atr", "ref_move"]
OUT = Path(__file__).resolve().parent / "results_round4"


def events(job):
    cache, ti, tk = job
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    full = load(cache, tk)
    attach_ref(full, load(cache, "QQQ" if tk == "SPY" else "SPY"))
    dc = full["dc"]
    full["prev_rng"] = np.r_[np.nan, (full["dh"] - full["dl"])[:-1]]
    full["prev_ret"] = np.r_[np.nan, np.nan, dc[1:-1] / dc[:-2] - 1]
    out = {}
    for period in ("dev", "holdout"):
        d = lab4.subset(full, *lab4.PERIODS[period])
        rows = []
        for si, (fam, p, stop) in enumerate(BASE):
            sig, lvl = lab4.signals4(d, fam, p)
            t = lab4.bracket(d, sig, stop, lvl, rrs=(3.0,))[3.0]
            if not len(t["r"]):
                continue
            i, b, s = t["day"].astype(int), t["bar"].astype(int), t["dirn"]
            atr, op = d["atr_prev"][i], d["day_open"][i]
            with np.errstate(all="ignore"):
                hi = np.fmax.accumulate(d["h5"], 1)[i, b]
                lo = np.fmin.accumulate(d["l5"], 1)[i, b]
                c = d["c5"][i, b]
                pos = (c - lo) / (hi - lo)
                f = np.column_stack([
                    np.full(len(i), si), np.full(len(i), ti), b, s, d["gap"][i] * op / atr * s, atr / op,
                    d["atr_ratio"][i], d["prev_rng"][i] / atr, d["nr7"][i], d["nr4"][i], d["inside"][i],
                    d["trend_prev"][i] * s, (c - d["vwap5"][i, b]) / d["vsd5"][i, b] * s,
                    (c / op - 1) / d["sig5"][i, b] * s, d["rvc"][i, b], d["rv0"][i], (hi - lo) / atr,
                    np.where(s > 0, pos, 1 - pos), d["prev_ret"][i] * s,
                    [int(np.datetime64(f"{k // 10000}-{k // 100 % 100:02d}-{k % 100:02d}").astype("datetime64[D]").view("int64") + 3) % 7
                     for k in d["dkey"][i]],
                    d["dkey"][i] % 100, t["dist"], (d["ref_c5"][i, b] / d["ref_open"][i] - 1) * s])
            rows.append(np.column_stack([f, d["dkey"][i], t["r"], t["kind"]]))
        out[period] = np.vstack(rows) if rows else np.zeros((0, len(FEATURES) + 3))
    return out


def build(cache):
    with Pool(4) as pool:
        res = pool.map(events, [(cache, ti, tk) for ti, tk in enumerate(TICKERS)])
    return {p: np.vstack([r[p] for r in res]) for p in ("dev", "holdout")}


def model():
    from sklearn.ensemble import HistGradientBoostingClassifier
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=100,
                                          categorical_features=[0, 1], random_state=0)


def split(a):
    nf = len(FEATURES)
    return a[:, :nf], a[:, nf].astype(int), a[:, nf + 1], a[:, nf + 2]


def describe(name, r, kind):
    n = len(r)
    if not n:
        return {"set": name, "n": 0}
    lo, hi = lab4.wilson(int((kind == 1).sum()), n)
    wl, wh = lab4.wilson(int((r > 0).sum()), n)
    return {"set": name, "n": n, "target_hit": round(float((kind == 1).mean()), 4), "target_ci": [round(lo, 3), round(hi, 3)],
            "win": round(float((r > 0).mean()), 4), "win_ci": [round(wl, 3), round(wh, 3)],
            "avg_r": round(float(r.mean()), 4)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--stage", choices=("dev", "holdout"), required=True)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    data = build(args.cache)
    X, dk, r, kind = split(data["dev"])
    y = (kind == 1).astype(int)
    days = np.unique(dk)
    chunks = np.array_split(days, 5)
    oof = np.full(len(y), np.nan)
    for k in range(4):
        tr = np.isin(dk, np.concatenate(chunks[:k + 1]))
        te = np.isin(dk, chunks[k + 1])
        oof[te] = model().fit(X[tr], y[tr]).predict_proba(X[te])[:, 1]
    m = ~np.isnan(oof)
    th90, th97 = np.percentile(oof[m], 90), np.percentile(oof[m], 97)
    report = {"events_dev": int(len(y)), "base_rate_dev": round(float(y.mean()), 4),
              "thresholds": {"p90": round(float(th90), 5), "p97": round(float(th97), 5)},
              "dev_oof": [describe("all OOF events", r[m], kind[m]),
                          describe("OOF score >= p90", r[m & (oof >= th90)], kind[m & (oof >= th90)]),
                          describe("OOF score >= p97", r[m & (oof >= th97)], kind[m & (oof >= th97)])]}
    from sklearn.metrics import roc_auc_score
    report["dev_oof_auc"] = round(float(roc_auc_score(y[m], oof[m])), 4)
    if args.stage == "holdout":
        Xh, dkh, rh, kh = split(data["holdout"])
        ph = model().fit(X, y).predict_proba(Xh)[:, 1]
        report["holdout"] = [describe("all holdout events", rh, kh),
                             describe("score >= p90", rh[ph >= th90], kh[ph >= th90]),
                             describe("score >= p97", rh[ph >= th97], kh[ph >= th97])]
        report["holdout_auc"] = round(float(roc_auc_score((kh == 1).astype(int), ph)), 4)
    path = OUT / f"meta_{args.stage}.json"
    path.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
