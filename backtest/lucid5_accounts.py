#!/usr/bin/env python3
"""How many $130 Lucid Flex accounts until you are ahead? (round 5 follow-up, today's volatility)

Accounts are bought one after another: when one fails its evaluation, blows up when funded, or moves
to live, the next is bought the following trading day, up to a budget of N accounts. Only cash counts:
fees paid vs payouts received (after the 90% split and $30 per transfer); an open funded balance at
the end is not counted. Scenarios use the round-5 pools rescaled to today's volatility.

  python3 backtest/lucid5_accounts.py --inst <10-year cache>
"""
import argparse
import json
import sys
import warnings
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import intraday_lab as il  # noqa: E402
import lucid5 as lc  # noqa: E402
import run_lucid5 as rl  # noqa: E402

CONFIGS = {"Lucid-optimized": lc.Config(0.3, 1.5, 2, ("budget", 350.0), ("budget", 350.0), 500.0),
           "Current bot setting": rl.BASELINE}
SCENARIOS = {"2023-26 repeats": (rl.CHECK, 1.0), "2016-22 repeats (10-year test)": (rl.DESIGN, 1.0),
             "2023-26 at half its edge": (rl.CHECK, 0.5), "No edge (luck only)": (rl.DESIGN, 0.0)}
BUDGETS = (1, 2, 3, 5, 10)
HORIZONS = {"12 months": 252, "24 months": 504}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    a = ap.parse_args()
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    d = il.load_instrument(a.inst, "QQQ")
    out = []
    for cname, cfg in CONFIGS.items():
        for sname, (span, edge) in SCENARIOS.items():
            pool = rl.pool_for(d, span, cfg.stop, cfg.rr, cfg.mt, True)
            st = lc.streams(pool, rl.N, 504, rl.BLOCK, rl.SEED + 7, edge_keep=edge)
            for hname, hz in HORIZONS.items():
                for B in BUDGETS:
                    r = lc.simulate(pool, st, cfg, horizon=hz, max_accounts=B)
                    c = r["cash"]
                    got = r["first_acc"] > 0
                    out.append({"config": cname, "scenario": sname, "horizon": hname, "budget": B,
                                "p_ahead": float((c > 0).mean()), "mean_cash": float(c.mean()),
                                "median_cash": float(np.median(c)), "p5_cash": float(np.percentile(c, 5)),
                                "p_any_payout": float(got.mean()), "accounts_bought_mean": float(r["accounts"].mean()),
                                "accounts_to_first_payout_median": float(np.median(r["first_acc"][got])) if got.any() else None,
                                "spent_before_first_payout_median": float(np.median(r["cash_first"][got])) if got.any() else None,
                                "worst_cash": float(c.min())})
    (rl.OUT / "accounts_needed.json").write_text(json.dumps(out, indent=1))
    for x in out:
        print(f"{x['config'][:9]:9s} | {x['scenario'][:30]:30s} | {x['horizon']:9s} | N={x['budget']:2d} | ahead {100*x['p_ahead']:5.1f}% "
              f"| any payout {100*x['p_any_payout']:5.1f}% | mean {x['mean_cash']:+6.0f} | median {x['median_cash']:+6.0f} "
              f"| p5 {x['p5_cash']:+6.0f} | bought {x['accounts_bought_mean']:.1f} | acct# of 1st payout {x['accounts_to_first_payout_median']}")


if __name__ == "__main__":
    main()
