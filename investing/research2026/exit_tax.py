#!/usr/bin/env python3
"""After-tax value of selling everything at months 12, 18, 24, 25 and 36, per contribution level, with every
purchase taxed as its own lot (12% on gains of lots held two years or less). Writes results/phase2_exit_tax.json.

  python3 -I investing/research2026/exit_tax.py --cache <cache> --only B_BALANCED
"""
import argparse, json, sys, warnings
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lots, sleeves as sv  # noqa: E402
from run_phase2 import Paths, universe_X, r  # noqa: E402

P = json.loads((HERE / "results" / "phase2_finalists.json").read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--only", required=True)
    a = ap.parse_args()
    warnings.filterwarnings("ignore")
    daily, px, fx = sv.build(Path(a.cache), start="1999-03-01")
    mm = sv.monthly(sv.apply_shift(daily, sv.cost_shift(sv.tracking_gaps(daily, px)), 252))
    X = universe_X(mm, "long")
    port = P[a.only]
    keys = list(port)
    R = Paths(X, 50_000, seed=1818, horizon=36).R(keys)
    out = {}
    for c in (0, 100, 150, 200):
        for h in (12, 18, 24, 25, 36):
            s = lots.simulate_lots(R[:, :h], keys, port, contrib=c, method="self_balance")
            dep = float(s["deposits"][-1])
            out[f"c{c}_m{h}"] = {"deposits": dep, "median": float(np.median(s["liq"])),
                                 "after_tax_median": float(np.median(s["after_tax"])), "mean_tax": float(s["tax"].mean()),
                                 "p_ge_10000": float((s["liq"] >= 10_000).mean()),
                                 "after_tax_p_ge_10000": float((s["after_tax"] >= 10_000).mean()),
                                 "exempt_share_median": float(np.median(s["exempt_value"] / s["liq"])),
                                 "p_loss20": float((s["liq"] <= 0.8 * dep).mean())}
    f = HERE / "results" / "phase2_exit_tax.json"
    allres = json.loads(f.read_text()) if f.exists() else {}
    allres[a.only] = r(out)
    f.write_text(json.dumps(allres, indent=1))
    print("done", a.only)


if __name__ == "__main__":
    main()
