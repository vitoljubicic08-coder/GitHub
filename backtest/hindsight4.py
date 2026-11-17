"""HINDSIGHT diagnostic (not used for selection): the whole round-4 grid on the holdout vs development.

  python3 backtest/hindsight4.py backtest/results_round4/grid4_holdout_all_HINDSIGHT.csv
"""
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import select4 as s4  # noqa: E402

dev = {r["key"]: r for r in s4.with_pooled(s4.read(str(HERE / "grid4_dev.csv")))}
ho = {r["key"]: r for r in s4.with_pooled(s4.read(sys.argv[1]))}
keys = [k for k in dev if k in ho and float(dev[k]["rr"]) == 3.0]
def st(r): return s4.stats(r)
rows = [(k, st(dev[k]), st(ho[k])) for k in keys if dev[k]["n"] >= 60 and ho[k]["n"] >= 40]
def rank(a): return np.argsort(np.argsort(a))
for m in ("win", "tgt", "avg_r"):
    a = np.array([x[1][m] for x in rows]); b = np.array([x[2][m] for x in rows])
    print(f"{m}: Spearman dev vs holdout = {np.corrcoef(rank(a), rank(b))[0,1]:+.3f} over {len(rows)} settings")
for m in ("win", "tgt"):
    best = max(rows, key=lambda x: x[2][m])
    print(f"HINDSIGHT best holdout {m}: {best[0]} n={best[2]['n']} win={best[2]['win']:.3f} tgt={best[2]['tgt']:.3f} avgR={best[2]['avg_r']:+.3f} (dev win={best[1]['win']:.3f} tgt={best[1]['tgt']:.3f})")
    n70 = sum(1 for x in rows if x[2][m] >= 0.70)
    print(f"  settings with holdout {m} >= 70%: {n70}")
# top dev decile by avg R -> holdout avg
a = np.array([x[1]["avg_r"] for x in rows]); b = np.array([x[2]["avg_r"] for x in rows])
q = a >= np.percentile(a, 90)
print(f"avg R: top-10% by dev -> holdout mean {b[q].mean():+.3f}; all -> {b.mean():+.3f}; dev top-10% mean {a[q].mean():+.3f}")
tg = np.array([x[1]["tgt"] for x in rows]); tgh = np.array([x[2]["tgt"] for x in rows])
q = tg >= np.percentile(tg, 90)
print(f"target hit: top-10% by dev ({tg[q].mean():.3f}) -> holdout {tgh[q].mean():.3f}; all holdout {tgh.mean():.3f}")
out = {"settings_compared": len(rows), "max_holdout_target_hit": max(x[2]["tgt"] for x in rows),
       "max_holdout_win": max(x[2]["win"] for x in rows)}
print(json.dumps(out))
