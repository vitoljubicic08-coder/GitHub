#!/usr/bin/env python3
"""EXTRA (not pre-registered): round-6 picks with 3 MNQ ticks of slippage on every market and stop fill
(instead of 1), on 2023-26 at today's volatility, full edge. Tight stops are the most exposed to this.

  python3 backtest/lucid6_stress.py --inst <10-year cache>
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lucid5 as lc  # noqa: E402
import run_lucid5 as rl  # noqa: E402
import run_lucid6 as r6  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    a = ap.parse_args()
    r6._init(a.inst)
    picks = json.loads((r6.OUT / "picks.json").read_text())
    out = {}
    for name, r in picks.items():
        v, es, fs, keep = r6.parse(r)
        for ticks in (1.0, 3.0):
            pool = r6.pool6(r6._D["d"], rl.CHECK, v, slip_ticks=ticks)
            st = lc.streams(pool, r6.N_CHECK, r6.H, rl.BLOCK, r6.SEED + 1)
            m = {"mean_r": pool["mean_r"], **r6.run_one(pool, st, v, es, fs, keep)}
            out[f"{name} | {ticks:.0f} tick"] = m
            print(f"{name:24s} {ticks:.0f} tick: meanR {m['mean_r']:+.3f} paid 3m {100*m['pay_3m']:.1f}% 12m {100*m['pay_12m']:.1f}% "
                  f"cash12 {m['cash_12m_mean']:+.0f} (median {m['cash_12m_median']:+.0f}) ahead12 {100*m['p_ahead_12m']:.1f}%")
    (r6.OUT / "stress_slippage.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
