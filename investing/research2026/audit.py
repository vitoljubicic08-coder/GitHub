#!/usr/bin/env python3
"""Phase 2 audit of the Phase 1 results (results/research.json).

  python3 -I investing/research2026/audit.py --monthly <Phase 1 monthly_eur.pkl> --out results/audit.json

1. Re-derives the headline Phase 1 numbers from the code and the Phase 1 monthly data (determinism check).
2. Explains the contribution "crossover" (recommended pie worse at EUR 0/100, better at EUR 200) with paired
   confidence intervals on common simulated paths.
3. Measures each defect found in the engine: CAPM applied to compound instead of arithmetic returns;
   circular bootstrap wrap; deposit-count convention; grid vs per-portfolio rebalancing mismatch.
4. Seed noise (independent seeds, 100,000 paths) and grid optimisation bias (in-sample vs fresh paths).
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import lots  # noqa: E402
import optimize as op  # noqa: E402
import sim  # noqa: E402
from run_research import FINAL, LONG, LONG_SPAN, all_portfolios, r  # noqa: E402

ORIG = all_portfolios()["ORIGINAL"]


def p10k(R, cols, port, c, **kw):
    s = lots.simulate_lots(R, cols, port, contrib=c, method=kw.pop("method", "self_balance"), **kw)
    return s


def paired(a: np.ndarray, b: np.ndarray, n_boot=2000, seed=0):
    """Mean of a-b with a bootstrap 95% interval over paths (a, b: 0/1 or values on the same paths)."""
    rng = np.random.default_rng(seed)
    d = a.astype(float) - b.astype(float)
    idx = rng.integers(0, len(d), (n_boot, len(d)))
    bs = d[idx].mean(1)
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--monthly", required=True)
    ap.add_argument("--out", default=str(HERE / "results" / "audit.json"))
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    mm = pd.read_pickle(a.monthly)
    X = sim.log_returns(mm, LONG, *LONG_SPAN)
    cols = list(X.columns)
    out = {}
    p1 = json.loads((HERE / "results" / "research.json").read_text())

    # ---- 1. reported numbers straight from the Phase 1 output file, and recomputed from code
    rep = {}
    for name, key in (("FINAL", "FINAL"), ("ORIGINAL", "ORIGINAL")):
        c = p1["contributions"][key]
        rep[name] = {"p10k_c200": c["c200_m24"]["forward"]["p_ge_10000"], "p10k_c100": c["c100_m24"]["forward"]["p_ge_10000"],
                     "p10k_c0": c["c0_m24"]["forward"]["p_ge_10000"], "median_c0": c["c0_m24"]["forward"]["median"],
                     "loss20_c0": c["c0_m24"]["forward"]["p_loss20"], "loss40_c0": c["c0_m24"]["forward"]["p_loss40"]}
    out["reported_in_json"] = rep
    Rp1, _ = sim.bootstrap_forward(X, mode="compound")                  # Phase 1 headline paths (seed 2)
    rec = {}
    for name, port in (("FINAL", FINAL), ("ORIGINAL", ORIG)):
        row = {}
        for c in (0, 100, 200):
            s = p10k(Rp1, cols, port, c)
            sm = lots.summarize(s["liq"], s["deposits"][-1])
            row[f"c{c}"] = {"p10k": sm["p_ge_10000"], "median": sm["median"], "loss20": sm["p_loss20"], "loss40": sm["p_loss40"]}
        rec[name] = row
    out["recomputed_phase1_convention"] = rec

    # ---- 2. crossover on common paths (Phase 1 convention and corrected drift)
    Rfix, labfix = sim.bootstrap_forward(X, mode="arith")
    cross = {}
    for tag, R in (("phase1", Rp1), ("corrected", Rfix)):
        rows = []
        for c in range(0, 301, 25):
            f = p10k(R, cols, FINAL, c)
            o = p10k(R, cols, ORIG, c)
            dep = f["deposits"][-1]
            m, lo, hi = paired(f["liq"] >= 10_000, o["liq"] >= 10_000)
            rows.append({"contrib": c, "deposits": dep, "final_p10k": float((f["liq"] >= 10_000).mean()),
                         "orig_p10k": float((o["liq"] >= 10_000).mean()), "diff": m, "diff_lo": lo, "diff_hi": hi,
                         "final_median": float(np.median(f["liq"])), "orig_median": float(np.median(o["liq"])),
                         "final_iqr": float(np.subtract(*np.percentile(f["liq"], [75, 25]))),
                         "orig_iqr": float(np.subtract(*np.percentile(o["liq"], [75, 25]))),
                         "required_return": sim.required_return(5000, c, 24, 10_000)})
        cross[tag] = rows
    out["crossover"] = cross

    # ---- 3a. implied arithmetic expected returns per sleeve (consensus, CAPM slope)
    b, v = sim.betas(X), sim.annual_vol(X)
    imp = {}
    for mode in ("compound", "arith"):
        mu = sim.forward_mu(cols, b, sim.SCENARIOS["consensus"], 1.0, vol=v, mode=mode)
        imp[mode] = {c: {"median_growth": float(np.expm1(mu[i] * 12)), "arith_mean": float(np.expm1(mu[i] * 12 + v[c] ** 2 / 2))}
                     for i, c in enumerate(cols)}
    out["implied_returns_consensus"] = imp

    # ---- 3b. effect of each fix on the headline numbers
    def metrics(R, port, c, **kw):
        s = p10k(R, cols, port, c, **kw)
        sm = lots.summarize(s["liq"], s["deposits"][-1])
        return {k: sm[k] for k in ("median", "mean", "p_ge_10000", "p_loss20", "p_loss40", "p5", "p95")}

    Rlin, _ = sim.bootstrap_forward(X, mode="arith", circular=False)
    eff = {}
    for name, port in (("FINAL", FINAL), ("ORIGINAL", ORIG)):
        eff[name] = {
            "phase1": {c: metrics(Rp1, port, c) for c in (0, 100, 200)},
            "corrected_drift": {c: metrics(Rfix, port, c) for c in (0, 100, 200)},
            "corrected_noncircular": {c: metrics(Rlin, port, c) for c in (0, 100, 200)},
            "corrected_23_deposits": {c: metrics(Rfix, port, c, timing="start") for c in (100, 200)},
            "corrected_rebalance_m12": {0: metrics(Rfix, port, 0, sell_rebalance_months=(12,))},
        }
    out["fix_effects"] = eff

    # ---- 4a. seed noise: 5 independent 10k-path seeds and one 100k-path run
    noise = {}
    for name, port in (("FINAL", FINAL), ("ORIGINAL", ORIG)):
        vals = {c: [] for c in (0, 100, 200)}
        for seed in (101, 102, 103, 104, 105):
            R, _ = sim.bootstrap_forward(X, mode="arith", seed=seed)
            for c in vals:
                vals[c].append(float((p10k(R, cols, port, c)["liq"] >= 10_000).mean()))
        big, _ = sim.bootstrap_forward(X, n_paths=100_000, mode="arith", seed=999)
        noise[name] = {}
        for c in vals:
            p = float((p10k(big, cols, port, c)["liq"] >= 10_000).mean())
            noise[name][c] = {"seeds_10k": vals[c], "seed_sd": float(np.std(vals[c], ddof=1)), "p_100k": p,
                              "ci95_100k": lots.binom_ci(p, 100_000)}
        del big
    out["seed_noise"] = noise

    # ---- 4b. grid optimisation bias: pick on seed-2 paths (as Phase 1 did), re-score on fresh paths
    W = op.grid(0.05)
    st_in = op.grid_stats(Rp1, cols, W)
    fresh, _ = sim.bootstrap_forward(X, n_paths=20_000, mode="compound", seed=4242)
    ok = (st_in["p_loss20"] <= 0.10) & (st_in["p_loss40"] <= 0.015)
    top = np.argsort(np.where(ok, -st_in["mean"], np.inf))[:20]
    st_out = op.grid_stats(fresh, cols, W[top])
    out["grid_bias"] = {
        "objective": "C: max mean s.t. P(loss>=20%)<=10%, P(loss>=40%)<=1.5% (Phase 1 convention, annual rebalance)",
        "top20_in_sample_mean": float(st_in["mean"][top].mean()), "top20_fresh_mean": float(st_out["mean"].mean()),
        "top20_in_sample_loss20": float(st_in["p_loss20"][top].mean()), "top20_fresh_loss20": float(st_out["p_loss20"].mean()),
        "top20_still_feasible_on_fresh_paths": int(((st_out["p_loss20"] <= 0.10) & (st_out["p_loss40"] <= 0.015)).sum()),
        "winner": dict(zip(op.GRID_SLEEVES, map(float, W[top[0]]))),
        "winner_in_sample": {k: float(st_in[k][top[0]]) for k in ("mean", "p_double", "p_loss20", "p_loss40")},
        "winner_fresh": {k: float(st_out[k][0]) for k in ("mean", "p_double", "p_loss20", "p_loss40")},
    }
    Path(a.out).write_text(json.dumps(r(out, 5), indent=1, default=str))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
