#!/usr/bin/env python3
"""Reproduce every number in the November 2026 portfolio research report.

  python3 -I investing/research2026/fetch_prices.py --out <cache>
  python3 -I investing/research2026/fetch_macro.py --out <cache>/macro
  python3 -I investing/research2026/fetch_fundamentals.py --out <cache>
  python3 -I investing/research2026/fetch_etf_facts.py --out <cache>
  python3 -I investing/research2026/run_research.py --cache <cache>

Writes investing/research2026/results/research.json. Seeds are fixed, so reruns on the same data give the
same numbers. All simulated probabilities are model estimates under stated assumptions, not forecasts.

PHASE 1 REPRODUCTION: this script deliberately keeps Phase 1's forward-return convention (CAPM applied to
compound returns, `mode="compound"`), which the Phase 2 audit found overstates high-volatility sleeves. The
corrected analysis is run_phase2.py.
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

import optimize as op  # noqa: E402
import portfolios as pf  # noqa: E402
import sim  # noqa: E402
import sleeves as sv  # noqa: E402

LONG = ["CASH", "WORLD", "SPX", "NDX", "SEMI", "NVDA", "SPEC", "SCV", "EM", "EUROPE", "GOLD", "TECH", "HEALTH",
        "STAPLES", "UTIL", "ENERGY", "MOMENTUM"]
LONG_SPAN = ("2000-09-30", "2026-10-31")
SHORT_SPAN = ("2013-08-31", "2026-10-31")          # QUALITY from Aug 2013; all 10 stocks listed by then
P1 = "compound"                     # Phase 1 drift convention (see docstring)
FINAL = {"NDX": .30, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .20}
CANDIDATES = {
    "D1": {"WORLD": .35, "NDX": .25, "SEMI": .15, "SCV": .10, "GOLD": .15},
    "D2": {"NDX": .25, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .20, "NVDA": .05},
    "D3": {"WORLD": .30, "NDX": .25, "SEMI": .15, "SCV": .15, "GOLD": .15},
    "D4_FINAL": FINAL,
    "D5": {"WORLD": .20, "NDX": .25, "SEMI": .20, "SCV": .15, "EM": .05, "GOLD": .15},
    "D7": {"NDX": .30, "SEMI": .25, "SCV": .20, "EM": .05, "GOLD": .20},
}
KEY = ["ORIGINAL", "FINAL", "SP500", "NASDAQ", "LOW_RISK_50_50"]
SHOCKS = {   # hypothetical instantaneous euro returns per sleeve (assumptions, not forecasts)
    "ai_capex_bust": {"NDX": -.40, "SEMI": -.55, "NVDA": -.65, "TECH": -.45, "SPX": -.25, "WORLD": -.22, "SCV": -.15,
                      "EM": -.20, "GOLD": .10, "CASH": .025, "SPEC": -.35, "UTIL": -.10, "HEALTH": -.05,
                      "STAPLES": -.03, "ENERGY": -.10, "EUROPE": -.18, "MOMENTUM": -.30, "QUALITY": -.22},
    "stagflation": {"NDX": -.28, "SEMI": -.35, "NVDA": -.40, "TECH": -.30, "SPX": -.20, "WORLD": -.20, "SCV": -.22,
                    "EM": -.25, "GOLD": .15, "CASH": .03, "SPEC": -.30, "UTIL": -.10, "HEALTH": -.10,
                    "STAPLES": -.08, "ENERGY": .15, "EUROPE": -.22, "MOMENTUM": -.20, "QUALITY": -.18},
    "taiwan_blockade": {"NDX": -.30, "SEMI": -.45, "NVDA": -.50, "TECH": -.35, "SPX": -.18, "WORLD": -.20, "SCV": -.12,
                        "EM": -.30, "GOLD": .20, "CASH": .02, "SPEC": -.25, "UTIL": -.05, "HEALTH": -.05,
                        "STAPLES": -.03, "ENERGY": .05, "EUROPE": -.18, "MOMENTUM": -.25, "QUALITY": -.15},
    "usd_minus_20pct": {"NDX": -.167, "SEMI": -.15, "NVDA": -.167, "TECH": -.167, "SPX": -.167, "WORLD": -.10,
                        "SCV": -.167, "EM": -.08, "GOLD": -.05, "CASH": 0.0, "SPEC": -.167, "UTIL": -.167,
                        "HEALTH": -.167, "STAPLES": -.167, "ENERGY": -.167, "EUROPE": 0.0, "MOMENTUM": -.167,
                        "QUALITY": -.167},
}


def all_portfolios():
    P = dict(pf.PORTFOLIOS)
    P["FINAL"] = FINAL
    for k, v in CANDIDATES.items():
        P.setdefault(k, v)
    return P


def universe_of(port):
    return "long" if all(k in LONG for k in port) else "short"


def r(x, nd=4):
    if isinstance(x, dict):
        return {k: r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [r(v, nd) for v in x]
    if isinstance(x, (float, np.floating)):
        return round(float(x), nd)
    if isinstance(x, (np.integer,)):
        return int(x)
    return x


def windows(X: pd.DataFrame, horizon=24) -> np.ndarray:
    A = X.to_numpy()
    return np.stack([A[s:s + horizon] for s in range(len(A) - horizon + 1)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    cache = Path(ap.parse_args().cache)
    warnings.filterwarnings("ignore")
    out = {}

    # ---------------------------------------------------------------- data, costs
    daily, px, fx = sv.build(cache, start="1999-03-01")
    gaps = sv.tracking_gaps(daily, px)
    shift = sv.cost_shift(gaps)
    dd = sv.apply_shift(daily, shift, 252)
    mm = sv.monthly(dd)
    out["tracking_gaps"] = r(gaps)
    out["cost_shift"] = r({k: v for k, v in shift.items()})
    out["data_end"] = str(daily.index[-1].date())

    # ---------------------------------------------------------------- historical backtests
    P = all_portfolios()
    bt = {}
    for name, port in P.items():
        start = "2000-09-01"
        vd = pf.run(dd.loc[start:], port, "annual")
        vm = pf.run(mm.loc["2000-09-30":], port, "annual")
        vm = pd.concat([pd.Series([1.0], index=[vm.index[0] - pd.offsets.MonthEnd(1)]), vm])
        m = pf.metrics(vd, vm, mm["CASH"])
        m["crises"] = pf.crisis_table(dd, port)
        bt[name] = m
    out["backtests"] = r(bt)
    peak = {}
    for sl in ("NDX", "SPX", "WORLD", "NVDA", "TECH", "EM"):
        v = (1 + dd[sl].loc["2000-03-10":"2003-03-31"].dropna()).cumprod()
        peak[sl] = float((v / v.cummax() - 1).min())
    sox = px["^SOX"].loc["2000-03-10":"2003-03-31"].dropna()
    peak["SOX_price_usd"] = float((sox / sox.cummax() - 1).min())
    out["dotcom_from_march_2000_peak"] = r(peak)

    # ---------------------------------------------------------------- simulation inputs
    XL = sim.log_returns(mm, LONG, *LONG_SPAN)
    short_cols = LONG + ["QUALITY", "MEGA8"] + [t for t in sv.STOCKS if t != "PLTR"]   # PLTR listed 2020
    XS = sim.log_returns(mm, short_cols, *SHORT_SPAN)
    out["sim_inputs"] = {
        "long": {"from": str(XL.index[0].date()), "to": str(XL.index[-1].date()), "months": len(XL)},
        "short": {"from": str(XS.index[0].date()), "to": str(XS.index[-1].date()), "months": len(XS)},
        "beta_long": r(sim.betas(XL).to_dict(), 3),
        "vol_long": r((XL.std() * np.sqrt(12)).to_dict(), 3),
        "hist_mean_log_long": r((XL.mean() * 12).to_dict(), 3),
        "expected_returns": {f"{s}/{sl}": r(dict(zip(XL.columns, np.expm1(sim.forward_mu(XL.columns, sim.betas(XL), sim.SCENARIOS[s], sl, mode=P1) * 12))), 3)
                             for s in sim.SCENARIOS for sl in sim.SLOPES},
        "corr_long": r(XL[["WORLD", "SPX", "NDX", "SEMI", "NVDA", "SPEC", "SCV", "EM", "GOLD"]].corr().to_dict(), 2),
    }
    paths = {}
    for u, X in (("long", XL), ("short", XS)):
        Rf, lab = sim.bootstrap_forward(X, mode=P1)
        paths[u] = {"cols": list(X.columns), "forward": Rf, "labels": lab, "bootstrap": sim.bootstrap_raw(X),
                    "t_mc": sim.t_mc(X, mode=P1), "hist": windows(X)}

    # ---------------------------------------------------------------- 24-month lump-sum outcomes, all portfolios
    res = {}
    for name, port in P.items():
        u = universe_of(port)
        pa = paths[u]
        res[name] = {"universe": u}
        for model in ("forward", "bootstrap", "t_mc", "hist"):
            s = sim.simulate(pa[model], pa["cols"], port)
            res[name][model] = sim.summary(s["liq"], 5000, s["V"])
        if u == "long":                                                 # also on the short window, for comparability
            s = sim.simulate(paths["short"]["forward"], paths["short"]["cols"], port)
            res[name]["forward_2013_window"] = sim.summary(s["liq"], 5000, s["V"])
        s = sim.simulate(pa["forward"], pa["cols"], port)
        res[name]["by_scenario"] = {lab: {"median": float(np.median(s["liq"][pa["labels"] == lab])),
                                          "p_double": float((s["liq"][pa["labels"] == lab] >= 10_000).mean()),
                                          "p_loss20": float((s["liq"][pa["labels"] == lab] <= 4_000).mean())}
                                    for lab in np.unique(pa["labels"])}
    out["simulations_24m"] = r(res)

    # ---------------------------------------------------------------- grid optimisation, objectives A-C
    W = op.grid(0.05)
    grid = {}
    for model in ("forward", "bootstrap", "t_mc"):
        st = op.grid_stats(paths["long"][model], paths["long"]["cols"], W)
        grid[model] = {obj: dict(zip(("index", "stats", "weights"), op.pick(st, W, obj))) for obj in "ABC"}
        front = []
        for cap in (0.02, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20):
            ok = st["p_loss20"] <= cap
            j = int(np.argmax(np.where(ok, st["mean"], -np.inf)))
            front.append({"loss20_cap": cap, "weights": dict(zip(op.GRID_SLEEVES, map(float, W[j]))),
                          **{k: float(v[j]) for k, v in st.items()}})
        grid[model]["frontier"] = front
        if model == "forward":
            fwd_stats = st
    out["grid"] = {"n_pies": int(len(W)), "step": 0.05, "caps": op.CAPS, "results": r(grid)}
    del fwd_stats

    # ---------------------------------------------------------------- contributions
    contrib = {}
    pa = paths["long"]
    for name in ("FINAL", "ORIGINAL", "SP500", "NASDAQ", "LOW_RISK_50_50", "WORLD"):
        port = P[name]
        contrib[name] = {}
        for c in (0, 100, 200):
            for h in (12, 24):
                key = f"c{c}_m{h}"
                row = {}
                for model in ("forward", "bootstrap", "t_mc", "hist"):
                    R = pa[model]
                    if model == "hist" and R.shape[1] < h:
                        continue
                    s = sim.simulate(R, pa["cols"], port, contrib=c, method="self_balance", horizon=h, tax_horizon=h)
                    sm = sim.summary(s["liq"], 5000 + c * h, s["V"])
                    sm["after_tax_median"] = float(np.median(s["after_tax"]))
                    sm["after_tax_p_ge_10000"] = float((s["after_tax"] >= 10_000).mean())
                    row[model] = sm
                contrib[name][key] = row
    out["contributions"] = r(contrib)
    out["required_return"] = r({f"c{c}_m{h}_t{t}": sim.required_return(5000, c, h, t)
                                for c in (0, 100, 200) for h in (12, 24) for t in (10_000, 12_500, 15_000, 20_000)})

    methods = {}
    for name in ("FINAL", "ORIGINAL"):
        methods[name] = {}
        for c in (100, 200):
            for meth in ("target", "self_balance", "target_rebal"):
                s = sim.simulate(pa["forward"], pa["cols"], P[name], contrib=c, method=meth)
                methods[name][f"c{c}_{meth}"] = {"median": float(np.median(s["liq"])),
                                                 "mean": float(s["liq"].mean()),
                                                 "p_ge_10000": float((s["liq"] >= 10_000).mean()),
                                                 "after_tax_median": float(np.median(s["after_tax"])),
                                                 "drift_median": float(np.median(s["drift"])),
                                                 "tax_paid_on_rebalance_mean": float(s["tax_paid_rebal"].mean())}
    out["contribution_methods"] = r(methods)

    # ---------------------------------------------------------------- entry timing
    entry = {}
    for name in ("FINAL", "ORIGINAL", "SP500"):
        port = P[name]
        j = pa["cols"].index("CASH")
        entry[name] = {}
        for model in ("forward", "hist"):
            R = pa[model]
            Gp = sim.portfolio_gross(R, pa["cols"], port)
            Gc = np.exp(R[:, :, j])
            entry[name][model] = {}
            for plan in ("lump", "dca3", "dca6", "pullback10", "reserve20"):
                f = sim.entry_plan(Gp, Gc, plan)
                lump = sim.entry_plan(Gp, Gc, "lump")
                entry[name][model][plan] = {"median": float(np.median(f)), "mean": float(f.mean()),
                                            "p5": float(np.percentile(f, 5)), "p_loss20": float((f <= 4000).mean()),
                                            "p_ge_10000": float((f >= 10_000).mean()),
                                            "beats_lump": float((f > lump).mean())}
    out["entry"] = r(entry)

    # ---------------------------------------------------------------- exit rules (34-month paths, 10-month warm-up)
    X = XL
    exits = {}
    Rf34, _ = sim.bootstrap_forward(X, horizon=34, seed=7, mode=P1)
    hist34 = windows(X, 34)
    for name in ("FINAL", "ORIGINAL"):
        port = P[name]
        exits[name] = {}
        for model, R in (("forward", Rf34), ("hist", hist34)):
            Gp = sim.portfolio_gross(R, list(X.columns), port)
            Gc = np.exp(R[:, :, list(X.columns).index("CASH")])
            warm = np.cumprod(Gp[:, :10], axis=1)
            warm = warm / warm[:, -1:]
            exits[name][model] = {}
            for rule in ("hold", "profit_take50", "lock_target", "trail20", "sma10", "glide18", "dd_buy"):
                o = sim.apply_rule(Gp[:, 10:], Gc[:, 10:], rule, warm=warm)
                f = o["final"]
                pk = np.maximum.accumulate(o["V"], axis=1)
                exits[name][model][rule] = {"median": float(np.median(f)), "mean": float(f.mean()),
                                            "p5": float(np.percentile(f, 5)), "p_ge_10000": float((f >= 10_000).mean()),
                                            "p_loss20": float((f <= 4000).mean()), "p_loss40": float((f <= 3000).mean()),
                                            "median_mdd": float(np.median((o["V"] / pk - 1).min(1))),
                                            "mean_tax_on_switches": float(o["taxes"].mean())}
    out["exit_rules"] = r(exits)

    # ---------------------------------------------------------------- holding longer
    Rf60, _ = sim.bootstrap_forward(X, horizon=60, seed=11, mode=P1)
    longer = {}
    for name in ("FINAL", "ORIGINAL", "SP500", "NASDAQ", "WORLD"):
        s = sim.simulate(Rf60, list(X.columns), P[name], rebalance_month=12, method="target")
        longer[name] = {}
        for h in (12, 24, 36, 60):
            v = s["V"][:, h]
            longer[name][f"m{h}"] = {"median": float(np.median(v)), "p_loss": float((v < 5000).mean()),
                                     "p_loss20": float((v <= 4000).mean()), "p_double": float((v >= 10_000).mean())}
    out["holding_longer"] = r(longer)

    # ---------------------------------------------------------------- stress tests
    stress = {}
    for name, port in P.items():
        stress[name] = {k: float(sum(port[s] * sh.get(s, 0.0) for s in port)) if all(s in sh for s in port) else None
                        for k, sh in SHOCKS.items()}
    out["stress_hypothetical"] = r(stress)
    out["lognormal_tradeoff"] = r(sim.lognormal_tradeoff())

    # ---------------------------------------------------------------- individual stocks: 24-month model ranges
    stocks = {}
    for t in ["NVDA"] + sv.STOCKS:
        col = t
        Xs = sim.log_returns(mm, ["CASH", "WORLD", col], "2000-09-30", LONG_SPAN[1])
        if len(Xs) < 60:
            continue
        Rs, _ = sim.bootstrap_forward(Xs, seed=21, mode=P1)
        g = np.exp(Rs[:, :, 2].sum(1))
        stocks[t] = {"from": str(Xs.index[0].date()), "beta": float(sim.betas(Xs)[col]),
                     "vol": float(Xs[col].std() * np.sqrt(12)),
                     "p10": float(np.percentile(g, 10) - 1), "p50": float(np.median(g) - 1),
                     "p90": float(np.percentile(g, 90) - 1), "p_loss30": float((g <= 0.7).mean())}
    out["stock_ranges_24m"] = r(stocks)

    res_dir = HERE / "results"
    res_dir.mkdir(exist_ok=True)
    (res_dir / "research.json").write_text(json.dumps(out, indent=1, default=str))
    print("wrote", res_dir / "research.json")


if __name__ == "__main__":
    main()
