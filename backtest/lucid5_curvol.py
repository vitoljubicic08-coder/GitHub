#!/usr/bin/env python3
"""EXTRA (not pre-registered): the round-5 picks at today's volatility.

Every trade's dollar risk per MNQ is scaled so that the median one-MNQ risk of the 0.3-ATR stop on
2023-2026 equals $275 (measured on real NQ data Sep-Nov 2026, nb3_futures.py). Two readings:
  literal  the pick's dollar sizes unchanged (fewer contracts fit, more trades skipped)
  scaled   the dollar sizes multiplied by the same factor (the same contracts as in the backtest)
  python3 backtest/lucid5_curvol.py --inst <10-year cache>
"""
import argparse
import json
import sys
import warnings
from dataclasses import replace
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import intraday_lab as il  # noqa: E402
import lucid5 as lc  # noqa: E402
import run_lucid5 as rl  # noqa: E402

NOW_ONE_MNQ = 275.3


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inst", required=True)
    a = ap.parse_args()
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    d = il.load_instrument(a.inst, "QQQ")
    ref = lc.build_pool(d, *rl.CHECK, 0.3, 3.0, 1)
    scale = NOW_ONE_MNQ / float(np.median(ref["dpr1"][ref["has1"]]))
    picks = json.loads((rl.OUT / "picks.json").read_text())
    out = {"scale": scale}
    for name, r in picks.items():
        cfg = rl.row_cfg(r)
        pool = lc.build_pool(d, *rl.CHECK, cfg.stop, cfg.rr, cfg.mt)
        for j in (1, 2):
            pool[f"dpr{j}"] = pool[f"dpr{j}"] * scale
        sz = lambda s: (s[0], s[1] * scale) if s[0] == "budget" else s   # noqa: E731
        for label, c in (("literal", cfg), ("scaled", replace(cfg, eval_size=sz(cfg.eval_size), funded_size=sz(cfg.funded_size)))):
            for edge in (1.0, 0.5):
                st = lc.streams(pool, rl.N, rl.H, rl.BLOCK, rl.SEED + 1, edge_keep=edge)
                res = lc.simulate(pool, st, c)
                m = lc.metrics(res)
                m["eval_size"], m["funded_size"] = c.eval_size, c.funded_size
                out[f"{name} | {label} | edge {edge}"] = m
    (rl.OUT / "check_current_vol.json").write_text(json.dumps(out, indent=1, default=float))
    print(f"scale {scale:.3f}")
    for k, m in out.items():
        if k != "scale":
            print(f"{k:55s} sizes {m['eval_size'][1]:.0f}/{m['funded_size'][1]:.0f}  pass {100*m['pass']:.0f}%  payout12m {100*m['payout_12m']:.1f}%  net {m['net_mean']:+.0f}  med {m['net_median']:+.0f}")


if __name__ == "__main__":
    main()
