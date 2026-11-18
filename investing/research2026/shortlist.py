#!/usr/bin/env python3
"""Score Phase 2 shortlist candidates on independent 100,000-path sets across models (forward, plain
bootstrap, Student-t, split-sample forward models). Writes results/phase2_shortlist.json.

  python3 -I investing/research2026/shortlist.py --cache <cache>
"""
import argparse, json, sys, warnings
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lots, sim, sleeves as sv  # noqa: E402
from run_phase2 import Paths, universe_X, r, BASE_P  # noqa: E402

CANDIDATES = {
    # A: aggressive growth
    "A1_NDX60_SEMI15_NVDA5_SCV5_EM15": {"NDX": .60, "SEMI": .15, "NVDA": .05, "SCV": .05, "EM": .15},
    "A2_NDX60_SEMI20_EM20": {"NDX": .60, "SEMI": .20, "EM": .20},
    "A3_NDX60_SEMI25_EM15": {"NDX": .60, "SEMI": .25, "EM": .15},
    "A4_NDX60_WORLD20_EM20": {"NDX": .60, "WORLD": .20, "EM": .20},
    "A5_NDX50_SEMI25_WORLD15_GOLD10": {"NDX": .50, "SEMI": .25, "WORLD": .15, "GOLD": .10},
    "A6_CORNER_NDX45_SEMI40_NVDA15": {"NDX": .45, "SEMI": .40, "NVDA": .15},
    # B: optimised growth and risk
    "B1_WORLD25_NDX45_SCV10_EM10_GOLD10": {"WORLD": .25, "NDX": .45, "SCV": .10, "EM": .10, "GOLD": .10},
    "B2_WORLD35_NDX45_EM10_GOLD10": {"WORLD": .35, "NDX": .45, "EM": .10, "GOLD": .10},
    "B3_WORLD40_NDX45_GOLD15": {"WORLD": .40, "NDX": .45, "GOLD": .15},
    "B4_WORLD35_NDX40_EM5_GOLD20": {"WORLD": .35, "NDX": .40, "EM": .05, "GOLD": .20},
    "B5_WORLD30_NDX45_SEMI10_GOLD15": {"WORLD": .30, "NDX": .45, "SEMI": .10, "GOLD": .15},
    # C: capital preservation with growth
    "C1_WORLD55_NDX5_GOLD20_CASH20": {"WORLD": .55, "NDX": .05, "GOLD": .20, "CASH": .20},
    "C2_WORLD50_NDX15_GOLD15_CASH20": {"WORLD": .50, "NDX": .15, "GOLD": .15, "CASH": .20},
    "C3_WORLD45_NDX15_GOLD15_CASH25": {"WORLD": .45, "NDX": .15, "GOLD": .15, "CASH": .25},
    # references
    **BASE_P,
    "ALL_NVDA": {"NVDA": 1.0}, "ALL_SEMI": {"SEMI": 1.0},
}


def score(R, cols, port):
    out = {}
    for c in (0, 100, 150, 200):
        s = lots.simulate_lots(R, cols, port, contrib=c, method="self_balance")
        sm = lots.summarize(s["liq"], float(s["deposits"][-1]), s["V"], s["after_tax"])
        out[f"c{c}"] = {k: sm[k] for k in ("median", "mean", "p5", "p95", "p_ge_10000", "p_ge_12500", "p_ge_15000",
                                           "p_double_invested", "p_loss10", "p_loss20", "p_loss30", "p_loss40", "p_loss50",
                                           "p_path_dd30", "after_tax_median")}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--shard", default="0/1", help="i/n: score every n-th candidate starting at i")
    ap.add_argument("--merge", action="store_true", help="merge shard files into phase2_shortlist.json")
    a = ap.parse_args()
    out_dir = HERE / "results"
    if a.merge:
        res = {}
        for f in sorted(out_dir.glob("phase2_shortlist_part*.json")):
            res.update(json.loads(f.read_text()))
        (out_dir / "phase2_shortlist.json").write_text(json.dumps(res, indent=1))
        for f in out_dir.glob("phase2_shortlist_part*.json"):
            f.unlink()
        print("merged", len(res))
        return
    k, n = map(int, a.shard.split("/"))
    warnings.filterwarnings("ignore")
    daily, px, fx = sv.build(Path(a.cache), start="1999-03-01")
    dd = sv.apply_shift(daily, sv.cost_shift(sv.tracking_gaps(daily, px)), 252)
    mm = sv.monthly(dd)
    X = universe_X(mm, "long")
    sets = {"forward": Paths(X, 100_000, seed=880_001), "bootstrap": Paths(X, 100_000, seed=880_002, kind="raw"),
            "forward_est_2000_12": Paths(X.loc[:"2012-12-31"], 50_000, seed=880_003),
            "forward_est_2013_26": Paths(X.loc["2013-01-31":], 50_000, seed=880_004)}
    res = {}
    for i, (name, port) in enumerate(CANDIDATES.items()):
        if i % n != k:
            continue
        keys = list(port)
        res[name] = {"weights": port}
        for tag, ps in sets.items():
            res[name][tag] = score(ps.R(keys), keys, port)
        cols_t = keys + [c for c in ("WORLD", "CASH") if c not in keys]
        Rt = sim.t_mc(X[cols_t], n_paths=50_000, seed=880_005)
        res[name]["t_mc"] = score(Rt, cols_t, port)
        print(name, flush=True)
    (out_dir / f"phase2_shortlist_part{k}.json").write_text(json.dumps(r(res), indent=1))


if __name__ == "__main__":
    main()
