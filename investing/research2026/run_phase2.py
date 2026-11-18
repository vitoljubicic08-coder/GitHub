#!/usr/bin/env python3
"""Phase 2: corrected forward model, re-optimisation with out-of-sample checks, contributions 0/100/150/200,
per-lot taxes, nominal and real outcomes, 100,000-path estimates with confidence intervals.

  python3 -I investing/research2026/run_phase2.py --cache <cache> stage

Stages (run in order; each writes results/phase2_<stage>.json):
  grid     5%-step search over 269,941 pies for objectives A-F on 10,000 in-sample paths, winners re-scored on
           fresh 100,000-path sets and on split-sample models (estimated on 2000-12, scored on 2013-26 and back)
  sweeps   gold 0-25%, emerging-market and small-cap-value swaps, factor and stock alternatives
  final    the three portfolios (A, B, C) and comparators: 100,000 paths x 3 models, contributions, taxes,
           inflation, history, stress tests, exit and bear-market rules

All probabilities are model estimates under the stated assumptions, not forecasts.
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
import portfolios as pf  # noqa: E402
import sim  # noqa: E402
import sleeves as sv  # noqa: E402

CORE = ["CASH", "WORLD", "SPX", "NDX", "SEMI", "NVDA", "SPEC", "SCV", "EM", "EUROPE", "GOLD", "TECH", "HEALTH",
        "STAPLES", "UTIL", "ENERGY", "MOMENTUM", "MIDGROWTH", "MIDCAP"]
UNIVERSES = {
    "long": (CORE, ("2000-09-30", "2026-10-31")),
    "mid": (CORE + ["QUALITY_SP", "EQW", "SOFTWARE"], ("2006-01-31", "2026-10-31")),
    "short": (CORE + ["QUALITY_SP", "EQW", "SOFTWARE", "QUALITY", "LOWVOL", "GOOGL", "META", "TSM", "MSFT", "AMZN",
                      "AVGO"], ("2013-08-31", "2026-10-31")),
}
CONTRIBS = (0, 100, 150, 200)
INFLATION = {"base": 0.025, "high": 0.035}   # ECB Sept 2026: 2.5% (2027), 2.1% (2028); "high" = Croatia-like +1 pp
FACTOR_ALPHA = {"QUALITY": 0.01, "QUALITY_SP": 0.01, "LOWVOL": 0.01, "MOMENTUM": 0.01, "SCV": 0.01}

PHASE1 = {"NDX": .30, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .20}
BASE_P = {
    "ORIGINAL": {"NDX": .40, "SEMI": .25, "NVDA": .15, "SPX": .10, "SPEC": .10},
    "PHASE1": PHASE1,
    "NASDAQ": {"NDX": 1.0}, "SP500": {"SPX": 1.0}, "WORLD": {"WORLD": 1.0},
    "SAVINGS": {"CASH": 1.0}, "LOW_RISK_50_50": {"WORLD": .5, "CASH": .5},
}


def r(x, nd=5):
    if isinstance(x, dict):
        return {str(k): r(v, nd) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [r(v, nd) for v in x]
    if isinstance(x, (float, np.floating)):
        return round(float(x), nd)
    if isinstance(x, np.integer):
        return int(x)
    return x


class Paths:
    """Index-based path set: draws block-bootstrap month indices once, then builds return paths for any subset
    of sleeves on demand (memory stays small at 100,000 paths)."""

    def __init__(self, X: pd.DataFrame, n: int, seed: int, kind: str = "forward", horizon: int = 24,
                 scenario_defs=None, mean_block=6):
        self.X, self.kind, self.n, self.T = X, kind, n, horizon
        self.cols = list(X.columns)
        rng = np.random.default_rng(seed)
        self.idx = sim.stationary_bootstrap(len(X), n, horizon, mean_block, rng).astype(np.int32)
        A = X.to_numpy()
        if kind == "raw":
            self.base, self.D, self.lab = A, None, None
            return
        defs = scenario_defs or sim.SCENARIOS
        combos = [(s, sl) for s in defs for sl in sim.SLOPES]
        b, v = sim.betas(X), sim.annual_vol(X)
        self.base = A - A.mean(axis=0)
        self.D = np.stack([sim.forward_mu(self.cols, b, defs[s], sl, vol=v, mode="arith") for s, sl in combos])
        self.lab = (np.arange(n) % len(combos)).astype(np.int16)
        self.labels = [f"{s}/{sl}" for s, sl in combos]

    def R(self, cols, horizon=None) -> np.ndarray:
        j = [self.cols.index(c) for c in cols]
        T = self.T if horizon is None else horizon
        out = self.base[:, j][self.idx[:, :T]]
        if self.D is not None:
            out = out + self.D[:, j][self.lab][:, None, :]
        return out


def hist_windows(X: pd.DataFrame, cols, horizon=24) -> np.ndarray:
    A = X[list(cols)].to_numpy()
    return np.stack([A[s:s + horizon] for s in range(len(A) - horizon + 1)])


def universe_X(mm, name):
    cols, span = UNIVERSES[name]
    return sim.log_returns(mm, cols, *span)


def universe_of(port):
    for u in ("long", "mid", "short"):
        if all(k in UNIVERSES[u][0] for k in port):
            return u
    raise ValueError(port)


def evaluate(pathsets: dict, port: dict, contribs=CONTRIBS, horizons=(12, 24), method="self_balance"):
    """Outcome statistics for one pie across path sets, contributions and horizons, with per-lot tax and
    real (inflation-adjusted) versions."""
    keys = list(port)
    res = {}
    for name, ps in pathsets.items():
        R = ps.R(keys) if isinstance(ps, Paths) else ps[1]
        cols = keys if isinstance(ps, Paths) else ps[0]
        res[name] = {}
        for h in horizons:
            if R.shape[1] < h:
                continue
            for c in contribs:
                s = lots.simulate_lots(R[:, :h], cols, port, contrib=c, method=method)
                dep = float(s["deposits"][-1])
                row = lots.summarize(s["liq"], dep, s["V"], s["after_tax"])
                n = len(s["liq"])
                for k in ("p_ge_10000", "p_double_invested", "p_loss20", "p_loss40"):
                    row[k + "_ci"] = lots.binom_ci(row[k], n)
                row["mean_tax"] = float(s["tax"].mean())
                row["exempt_share_median"] = float(np.median(s["exempt_value"] / s["liq"]))
                for tag, pi in INFLATION.items():
                    defl = (1 + pi) ** (h / 12)
                    rr = lots.summarize(s["liq"], dep, deflator=defl)
                    row[f"real_{tag}"] = {k: rr[k] for k in ("median", "p5", "p95", "p_ge_10000", "p_profit", "p_loss20")}
                row["n_paths"] = n
                res[name][f"c{c}_m{h}"] = row
        if isinstance(ps, Paths) and ps.lab is not None:
            s = lots.simulate_lots(R, keys, port)
            res[name]["by_scenario_c0"] = {ps.labels[k]: {"median": float(np.median(s["liq"][ps.lab == k])),
                                                           "p_double": float((s["liq"][ps.lab == k] >= 10_000).mean()),
                                                           "p_loss20": float((s["liq"][ps.lab == k] <= 4_000).mean())}
                                           for k in range(len(ps.labels))}
    return res


# ------------------------------------------------------------------------------------------------ grid
def grid_scores(ps: Paths, W: np.ndarray, chunk=400):
    """Lump-sum and contribution statistics for every pie in W (target split, no selling)."""
    sl = op.GRID_SLEEVES
    R = ps.R(sl)
    A = {c: lots.grid_matrices(R, sl, sl, contrib=c)[0] for c in CONTRIBS}
    out = {k: [] for k in ("mean", "median", "p5", "p_double", "p_loss20", "p_loss40", "sortino",
                           "p10k_c100", "p10k_c150", "p10k_c200", "median_c200", "p_loss20_c200")}
    for a in range(0, len(W), chunk):
        w = W[a:a + chunk]
        V = w @ A[0].T
        out["mean"].append(V.mean(1))
        out["median"].append(np.median(V, 1))
        out["p5"].append(np.percentile(V, 5, axis=1))
        out["p_double"].append((V >= 10_000).mean(1))
        out["p_loss20"].append((V <= 4_000).mean(1))
        out["p_loss40"].append((V <= 3_000).mean(1))
        dn = np.sqrt((np.minimum(V - 5000, 0) ** 2).mean(1))
        out["sortino"].append((V.mean(1) - 5000) / np.maximum(dn, 1e-9))
        for c in (100, 150, 200):
            Vc = w @ A[c].T
            out[f"p10k_c{c}"].append((Vc >= 10_000).mean(1))
            if c == 200:
                out["median_c200"].append(np.median(Vc, 1))
                out["p_loss20_c200"].append((Vc <= 0.8 * 9800).mean(1))
    return {k: np.concatenate(v) for k, v in out.items()}


OBJECTIVES = {
    "A_max_p_double": lambda s: s["p_double"] + 1e-9 * s["mean"],
    "B_max_mean": lambda s: s["mean"],
    "C_max_median": lambda s: s["median"],
    "D_best_sortino": lambda s: s["sortino"],
    "E_min_loss40_unconstrained": lambda s: -s["p_loss40"] + 1e-9 * s["median"],
    "E2_min_loss40_median_ge_5500": lambda s: np.where(s["median"] >= 5500, -s["p_loss40"] + 1e-9 * s["median"], -np.inf),
    "F_max_p10k_c100": lambda s: s["p10k_c100"] + 1e-9 * s["median"],
    "F_max_p10k_c150": lambda s: s["p10k_c150"] + 1e-9 * s["median"],
    "F_max_p10k_c200": lambda s: s["p10k_c200"] + 1e-9 * s["median"],
}


def stage_grid(mm, out_dir):
    XL = universe_X(mm, "long")
    W = op.grid(0.05)
    ins = Paths(XL, 10_000, seed=2001)
    st = grid_scores(ins, W)
    fresh = Paths(XL, 100_000, seed=777_001)
    # split-sample: model estimated on one half of history, scored on the other
    X1 = XL.loc[:"2012-12-31"]
    X2 = XL.loc["2013-01-31":]
    halves = {"est_2000_12": Paths(X1, 10_000, seed=31), "est_2013_26": Paths(X2, 10_000, seed=32)}
    halves_eval = {"est_2000_12": Paths(X2, 50_000, seed=41), "est_2013_26": Paths(X1, 50_000, seed=42)}
    res = {"n_pies": len(W), "objectives": {}, "split_sample": {}, "frontier": []}
    winners = {}
    for name, f in OBJECTIVES.items():
        i = int(np.argmax(f(st)))
        winners[name] = i
    idx = sorted(set(winners.values()))
    st_fresh = grid_scores(fresh, W[idx], chunk=50)
    pos = {i: k for k, i in enumerate(idx)}
    for name, i in winners.items():
        res["objectives"][name] = {"weights": dict(zip(op.GRID_SLEEVES, map(float, W[i]))),
                                   "in_sample": {k: float(v[i]) for k, v in st.items()},
                                   "fresh_100k": {k: float(v[pos[i]]) for k, v in st_fresh.items()}}
    for tag in halves:
        sh = grid_scores(halves[tag], W)
        res["split_sample"][tag] = {}
        for name in ("A_max_p_double", "C_max_median", "D_best_sortino", "F_max_p10k_c200"):
            i = int(np.argmax(OBJECTIVES[name](sh)))
            ev = grid_scores(halves_eval[tag], W[[i]], chunk=1)
            res["split_sample"][tag][name] = {"weights": dict(zip(op.GRID_SLEEVES, map(float, W[i]))),
                                              "in_sample": {k: float(v[i]) for k, v in sh.items()},
                                              "other_half": {k: float(v[0]) for k, v in ev.items()}}
    # efficient frontier: for each loss-40% cap, the best chance of doubling and the best median
    caps = (0.0025, 0.005, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10)
    front_idx = []
    for cap in caps:
        ok = st["p_loss40"] <= cap
        i_d = int(np.argmax(np.where(ok, st["p_double"] + 1e-9 * st["mean"], -np.inf)))
        i_m = int(np.argmax(np.where(ok, st["median"], -np.inf)))
        front_idx += [i_d, i_m]
        res["frontier"].append({"loss40_cap": cap, "max_p_double": {"weights": dict(zip(op.GRID_SLEEVES, map(float, W[i_d]))), **{k: float(v[i_d]) for k, v in st.items()}},
                                "max_median": {"weights": dict(zip(op.GRID_SLEEVES, map(float, W[i_m]))), **{k: float(v[i_m]) for k, v in st.items()}}})
    fi = sorted(set(front_idx))
    sf = grid_scores(fresh, W[fi], chunk=50)
    fpos = {i: k for k, i in enumerate(fi)}
    for row, cap in zip(res["frontier"], caps):
        for key in ("max_p_double", "max_median"):
            w = np.array([row[key]["weights"][s] for s in op.GRID_SLEEVES])
            i = int(np.where((W == w).all(1))[0][0])
            row[key]["fresh_100k"] = {k: float(v[fpos[i]]) for k, v in sf.items()}
    # cloud for the frontier chart: a thinned sample of all pies (in-sample)
    rng = np.random.default_rng(5)
    pick = rng.choice(len(W), 3000, replace=False)
    res["cloud"] = [{"p_loss40": float(st["p_loss40"][i]), "p_double": float(st["p_double"][i]), "median": float(st["median"][i])} for i in pick]
    (out_dir / "phase2_grid.json").write_text(json.dumps(r(res), indent=1))
    print("grid done")


# ------------------------------------------------------------------------------------------------ sweeps
def sweep_portfolios():
    P = {}
    core = {"NDX": .375, "SEMI": .25, "SCV": .25, "EM": .125}
    for g in (0, 5, 10, 15, 20, 25):
        P[f"GOLD_{g:02d}"] = {**{k: v * (1 - g / 100) for k, v in core.items()}, **({"GOLD": g / 100} if g else {})}
    P["GOLD10_WORLD10"] = {"NDX": .30, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .10, "WORLD": .10}
    P["GOLD10_CASH10"] = {"NDX": .30, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .10, "CASH": .10}
    P["EM_00_TO_SCV"] = {"NDX": .30, "SEMI": .20, "SCV": .30, "GOLD": .20}
    P["EM_TO_WORLD"] = {"NDX": .30, "SEMI": .20, "SCV": .20, "WORLD": .10, "GOLD": .20}
    P["EM_20"] = {"NDX": .30, "SEMI": .20, "SCV": .10, "EM": .20, "GOLD": .20}
    P["SCV_TO_WORLD"] = {"NDX": .30, "SEMI": .20, "WORLD": .20, "EM": .10, "GOLD": .20}
    P["SCV_TO_SPX"] = {"NDX": .30, "SEMI": .20, "SPX": .20, "EM": .10, "GOLD": .20}
    P["SCV_TO_MIDGROWTH"] = {"NDX": .30, "SEMI": .20, "MIDGROWTH": .20, "EM": .10, "GOLD": .20}
    P["SCV_TO_MIDCAP"] = {"NDX": .30, "SEMI": .20, "MIDCAP": .20, "EM": .10, "GOLD": .20}
    P["SEMI_10_NDX_40"] = {"NDX": .40, "SEMI": .10, "SCV": .20, "EM": .10, "GOLD": .20}
    P["PLUS_NVDA5"] = {"NDX": .25, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .20, "NVDA": .05}
    # mid universe (from 2006): quality, equal weight, software
    P["SCV_TO_QUALITY_SP"] = {"NDX": .30, "SEMI": .20, "QUALITY_SP": .20, "EM": .10, "GOLD": .20}
    P["SCV_TO_EQW"] = {"NDX": .30, "SEMI": .20, "EQW": .20, "EM": .10, "GOLD": .20}
    P["SEMI_TO_SOFTWARE"] = {"NDX": .30, "SOFTWARE": .20, "SCV": .20, "EM": .10, "GOLD": .20}
    # short universe (from Aug 2013): low volatility, MSCI quality, momentum, a value-tech stock basket
    P["GOLD10_LOWVOL10"] = {"NDX": .30, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .10, "LOWVOL": .10}
    P["SCV_TO_QUALITY"] = {"NDX": .30, "SEMI": .20, "QUALITY": .20, "EM": .10, "GOLD": .20}
    P["NDX_TO_MOMENTUM"] = {"MOMENTUM": .30, "SEMI": .20, "SCV": .20, "EM": .10, "GOLD": .20}
    P["VALUE_TECH_10"] = {"NDX": .20, "GOOGL": 1 / 30, "META": 1 / 30, "TSM": 1 / 30, "SEMI": .20, "SCV": .20, "EM": .10,
                          "GOLD": .20}
    return P


def stage_sweeps(mm, out_dir):
    P = {**BASE_P, **sweep_portfolios()}
    res = {}
    cache = {}
    for name, port in P.items():
        u = universe_of(port)
        if u not in cache:
            X = universe_X(mm, u)
            cache[u] = {"forward": Paths(X, 50_000, seed=9100 + len(cache)),
                        "forward_factor_alpha": Paths(X, 50_000, seed=9200 + len(cache), scenario_defs={
                            k: {**v, "factor_alpha": FACTOR_ALPHA} for k, v in sim.SCENARIOS.items()}),
                        "bootstrap": Paths(X, 50_000, seed=9300 + len(cache), kind="raw")}
        res[name] = {"universe": u, **evaluate(cache[u], port, contribs=(0, 200), horizons=(24,))}
        # same-universe reference: the Phase 1 pie on the same paths, for apples-to-apples comparisons
        if u != "long" and f"PHASE1@{u}" not in res:
            res[f"PHASE1@{u}"] = {"universe": u, **evaluate(cache[u], PHASE1, contribs=(0, 200), horizons=(24,))}
            res[f"ORIGINAL@{u}"] = {"universe": u, **evaluate(cache[u], BASE_P["ORIGINAL"], contribs=(0, 200), horizons=(24,))}
        print("sweep", name, flush=True)
    (out_dir / "phase2_sweeps.json").write_text(json.dumps(r(res), indent=1))


# ------------------------------------------------------------------------------------------------ final
def stage_final(mm, dd, out_dir, finalists: dict, shard=(0, 1)):
    P = {**BASE_P, **finalists}
    k_sh, n_sh = shard
    X = universe_X(mm, "long")
    sets = {"forward": Paths(X, 100_000, seed=123_457), "bootstrap": Paths(X, 100_000, seed=123_458, kind="raw")}
    res = {"portfolios": P, "evaluation": {}, "history": {}, "stress": {}, "t_mc": {}, "hist_windows": {},
           "exit_rules": {}, "longer": {}, "methods": {}}
    for i_p, (name, port) in enumerate(P.items()):
        if i_p % n_sh != k_sh:
            continue
        res["evaluation"][name] = evaluate(sets, port)
        keys = list(port)
        Rt = sim.t_mc(X[keys + (["WORLD"] if "WORLD" not in keys else []) + (["CASH"] if "CASH" not in keys else [])],
                      n_paths=50_000, seed=55)
        cols_t = keys + (["WORLD"] if "WORLD" not in keys else []) + (["CASH"] if "CASH" not in keys else [])
        res["t_mc"][name] = evaluate({"t_mc": (cols_t, Rt)}, port, horizons=(24,))["t_mc"]
        H = hist_windows(X, cols_t)
        res["hist_windows"][name] = evaluate({"hist": (cols_t, H)}, port, horizons=(24,))["hist"]
        # history and crises (daily euro series)
        vd = pf.run(dd.loc["2000-09-01":], port, "annual")
        vm = pf.run(mm.loc["2000-09-30":], port, "annual")
        vm = pd.concat([pd.Series([1.0], index=[vm.index[0] - pd.offsets.MonthEnd(1)]), vm])
        m = pf.metrics(vd, vm, mm["CASH"])
        m["crises"] = pf.crisis_table(dd, port)
        res["history"][name] = m
        res["stress"][name] = {k: float(sum(port[s] * sh.get(s, 0.0) for s in port)) if all(s in sh for s in port) else None
                               for k, sh in STRESS.items()}
        # longer horizons (lump sum and EUR 200/month), per-lot tax
        R60 = Paths(X, 30_000, seed=600, horizon=60).R(keys)
        res["longer"][name] = {}
        for c in (0, 200):
            for h in (24, 36, 60):
                s = lots.simulate_lots(R60[:, :h], keys, port, contrib=c, method="self_balance")
                dep = float(s["deposits"][-1])
                res["longer"][name][f"c{c}_m{h}"] = {"deposits": dep, "median": float(np.median(s["liq"])),
                                                     "p_profit": float((s["liq"] > dep).mean()),
                                                     "p_double_invested": float((s["liq"] >= 2 * dep).mean()),
                                                     "p_loss20": float((s["liq"] <= 0.8 * dep).mean()),
                                                     "after_tax_median": float(np.median(s["after_tax"])),
                                                     "exempt_share_median": float(np.median(s["exempt_value"] / s["liq"]))}
        print("final", name, flush=True)
    # exit and bear-market rules for the finalists (forward paths with a 10-month warm-up)
    R34 = Paths(X, 50_000, seed=3434, horizon=34)
    for name in list(finalists) + ["PHASE1", "ORIGINAL"]:
        if list(P).index(name) % n_sh != k_sh:
            continue
        port = P[name]
        keys = list(port) + (["CASH"] if "CASH" not in port else [])
        R = R34.R(keys)
        Gp = sim.portfolio_gross(R, keys, port)
        Gc = np.exp(R[:, :, keys.index("CASH")])
        warm = np.cumprod(Gp[:, :10], axis=1)
        warm = warm / warm[:, -1:]
        res["exit_rules"][name] = {}
        for rule in ("hold", "trail20", "sma10", "glide18", "dd_buy"):
            o = sim.apply_rule(Gp[:, 10:], Gc[:, 10:], rule, warm=warm)
            f = o["final"]
            res["exit_rules"][name][rule] = {"median": float(np.median(f)), "p_ge_10000": float((f >= 10_000).mean()),
                                             "p_loss20": float((f <= 4000).mean()), "p_loss40": float((f <= 3000).mean()),
                                             "mean_tax": float(o["taxes"].mean())}
        Rm = sets["forward"].R(list(port))
        res["methods"][name] = {}
        for c in (100, 200):
            for meth in ("target", "self_balance"):
                s = lots.simulate_lots(Rm, list(port), port, contrib=c, method=meth)
                res["methods"][name][f"c{c}_{meth}"] = {"median": float(np.median(s["liq"])),
                                                        "p_ge_10000": float((s["liq"] >= 10_000).mean()),
                                                        "drift_median": float(np.median(s["drift"]))}
    (out_dir / f"phase2_final_part{k_sh}.json").write_text(json.dumps(r(res), indent=1, default=str))
    print("final done")


def merge_final(out_dir):
    parts = sorted(out_dir.glob("phase2_final_part*.json"))
    res = {}
    for f in parts:
        d = json.loads(f.read_text())
        for key, val in d.items():
            if isinstance(val, dict) and key != "portfolios":
                res.setdefault(key, {}).update(val)
            else:
                res[key] = val
    (out_dir / "phase2_final.json").write_text(json.dumps(res, indent=1))
    for f in parts:
        f.unlink()
    print("merged", len(parts))


STRESS = {   # hypothetical instant euro losses per sleeve (assumptions), as in Phase 1, plus the new sleeves
    "ai_capex_bust": {"NDX": -.40, "SEMI": -.55, "NVDA": -.65, "TECH": -.45, "SPX": -.25, "WORLD": -.22, "SCV": -.15,
                      "EM": -.20, "GOLD": .10, "CASH": .025, "SPEC": -.35, "MIDGROWTH": -.30, "MIDCAP": -.20},
    "stagflation": {"NDX": -.28, "SEMI": -.35, "NVDA": -.40, "TECH": -.30, "SPX": -.20, "WORLD": -.20, "SCV": -.22,
                    "EM": -.25, "GOLD": .15, "CASH": .03, "SPEC": -.30, "MIDGROWTH": -.28, "MIDCAP": -.22},
    "taiwan_blockade": {"NDX": -.30, "SEMI": -.45, "NVDA": -.50, "TECH": -.35, "SPX": -.18, "WORLD": -.20, "SCV": -.12,
                        "EM": -.30, "GOLD": .20, "CASH": .02, "SPEC": -.25, "MIDGROWTH": -.20, "MIDCAP": -.14},
    "usd_minus_20pct": {"NDX": -.167, "SEMI": -.15, "NVDA": -.167, "TECH": -.167, "SPX": -.167, "WORLD": -.10,
                        "SCV": -.167, "EM": -.08, "GOLD": -.05, "CASH": 0.0, "SPEC": -.167, "MIDGROWTH": -.167,
                        "MIDCAP": -.167},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("stage", choices=("grid", "sweeps", "final", "merge_final"))
    ap.add_argument("--shard", default="0/1")
    ap.add_argument("--finalists", default=str(HERE / "results" / "phase2_finalists.json"))
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    if a.stage == "merge_final":
        merge_final(HERE / "results")
        return
    cache = Path(a.cache)
    daily, px, fx = sv.build(cache, start="1999-03-01")
    shift = sv.cost_shift(sv.tracking_gaps(daily, px))
    dd = sv.apply_shift(daily, shift, 252)
    mm = sv.monthly(dd)
    out_dir = HERE / "results"
    out_dir.mkdir(exist_ok=True)
    if a.stage == "grid":
        stage_grid(mm, out_dir)
    elif a.stage == "sweeps":
        stage_sweeps(mm, out_dir)
    elif a.stage == "final":
        stage_final(mm, dd, out_dir, json.loads(Path(a.finalists).read_text()), tuple(map(int, a.shard.split("/"))))


if __name__ == "__main__":
    main()
