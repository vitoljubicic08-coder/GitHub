"""Phase 3 add-ons -> results/phase3_extra.json:

  * $10 vs $20 simulated risk profile (median bets, drawdown as % of peak) for the rule sets
    compared exactly in run_phase3.compare_10_20 (200,000 challenges each, seeds 7000+);
  * where switching games changes the optimal value at all (union DP vs Dice-only DP).
"""
from __future__ import annotations

import json
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine as E  # noqa: E402
import run_phase3 as R  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
RULES = ["One all-in bet aimed at $100", "Optimal policy (DP), Dice", "Two all-in stages", "Bold play at 2x",
         "Fixed 25% of bankroll at 2x", "Martingale $0.10", "Fibonacci $0.10", "D'Alembert $0.10",
         "Flat $1 at 2x", "Flat $1 at 1.1x"]


def make(label, b):
    pol = R.dp_policy("dice")[1]
    return {
        RULES[0]: lambda: E.Bold(10.0 if b == 1000 else 5.0),
        RULES[1]: lambda: E.PolicyTargetHit(pol),
        RULES[2]: lambda: E.Bold(10 ** 0.5 if b == 1000 else R.ROOT5),
        RULES[3]: lambda: E.Bold(2.0),
        RULES[4]: lambda: E.FixedFraction(0.25),
        RULES[5]: lambda: E.Martingale(10),
        RULES[6]: lambda: E.Fibonacci(10),
        RULES[7]: lambda: E.DAlembert(10),
        RULES[8]: lambda: E.Flat(100, 2.0),
        RULES[9]: lambda: E.Flat(100, 1.1),
    }[label]()


def job(args):
    k, label, b = args
    lv = E.LEVELS if b == 1000 else E.LEVELS20
    _, sm = E.simulate(make(label, b), E.Dice(), n=200_000, seed=7000 + k, start=b, levels=lv)
    return dict(label=label, start=b, median_bets=sm["median_bets"], p90_bets=sm["p90_bets"],
                mean_maxdd_pct=sm["mean_maxdd_pct"], median_maxdd_pct=sm["median_maxdd_pct"],
                median_maxdd=sm["median_maxdd"], sd_final=sm["sd_final"], p_target=sm["p_target"])


def switching():
    Vd, _ = R.dp_policy("dice")
    Vu, pu = R.dp_policy("union")
    diff = Vu - Vd
    k = int(np.argmax(diff))
    g = R.union_games()
    B = np.arange(len(pu))
    s = np.maximum(pu, 1)
    _, _, gi = g.choose((R.G.TARGET - B + s) / np.maximum(s, 1))
    used = {g.games[i].name: int(((gi == i) & (B > 0)).sum()) for i in np.unique(gi[1:])}
    return dict(max_gain=float(diff.max()), at_bankroll=k / 100, n_better=int((diff > 1e-15).sum()),
                gain_at_20=float(diff[2000]), policy_game_counts=used)


def main():
    jobs = [(k, lab, b) for k, (lab, b) in enumerate((lab, b) for lab in RULES for b in (1000, 2000))]
    with Pool(4) as pool:
        res = pool.map(job, jobs)
    out = dict(compare_sim=res, switching=switching())
    (OUT / "phase3_extra.json").write_text(json.dumps(out, indent=1, default=float))
    print(json.dumps(out["switching"], indent=1))


if __name__ == "__main__":
    main()
