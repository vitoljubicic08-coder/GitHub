"""Round-5 Lucid Flex simulator: the vectorised engine must match prop_sim.run_stream exactly.

Run:  python3 -m unittest discover -s tests -v   (needs the research cache: NB3_INST=<inst cache>)
"""
from __future__ import annotations

import os
import sys
import unittest
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backtest"))

import intraday_lab as il  # noqa: E402
import lucid5 as lc  # noqa: E402
import prop_sim as ps  # noqa: E402

INST = os.environ.get("NB3_INST", "")


def synthetic_pool(n=300, seed=1):
    rng = np.random.default_rng(seed)
    has = rng.random(n) < 0.85
    kind = rng.choice([0, 1, 2], size=n, p=[0.5, 0.12, 0.38])
    r = np.where(kind == 0, -1.005, np.where(kind == 1, 3.0, rng.normal(0.2, 0.6, n)))
    lo = np.where(kind == 0, r, -rng.random(n) * 0.95)
    dpr = rng.uniform(150, 320, n)
    pool = {"dkey": np.arange(n), "n": n, "has1": has, "r1": np.where(has, r, 0), "lo1": np.where(has, lo, 0),
            "dpr1": np.where(has, dpr, 0), "kind1": kind.astype(float)}
    for k in ("has", "r", "lo", "dpr", "kind"):
        pool[f"{k}2"] = np.zeros(n, bool) if k == "has" else np.zeros(n)
    return pool


def reference(pool, st, cfg, H):
    firm = ps.FIRMS["lucid"]
    pp = {"has": pool["has1"], "dpr": np.where(pool["has1"], pool["dpr1"], np.nan), "r": pool["r1"], "lo": pool["lo1"]}
    s = {"idx": st["idx"], "src": st["idx"]}
    E = ps.day_arrays(pp, s, firm, cfg.eval_size[1], None)
    F = ps.day_arrays(pp, s, firm, cfg.funded_size[1], None)
    pol = "above_cushion" if cfg.keep == 2000 else "max_earliest"
    out = []
    for i in range(st["idx"].shape[0]):
        att, _ = ps.run_stream(firm, tuple(x[i] for x in E), tuple(x[i] for x in F), H, 1, pol)
        out.append(att[0])
    return out


class ParityTests(unittest.TestCase):
    def check(self, pool, cfg, H=252, n=300):
        st = lc.streams(pool, n, H, seed=5)
        res = lc.simulate(pool, st, cfg)
        ref = reference(pool, st, cfg, H)
        self.assertEqual(list(res["passed"]), [r["passed"] for r in ref])
        self.assertEqual(list(res["pass_day"] + 1), [r["days_to_pass"] if r["passed"] else 0 for r in ref])
        self.assertEqual(list(res["npay"]), [len(r["payouts"]) for r in ref])
        np.testing.assert_allclose(res["net"], [r["net_payouts"] for r in ref], atol=1e-6)
        self.assertEqual(list(res["first_pay"]), [r["first_payout_day"] if r["first_payout_day"] is not None else -1 for r in ref])

    def test_matches_prop_sim_max_earliest(self):
        self.check(synthetic_pool(), lc.Config(eval_size=("budget", 350.0), funded_size=("budget", 250.0), keep=0.0))

    def test_matches_prop_sim_keep_cushion(self):
        self.check(synthetic_pool(seed=2), lc.Config(eval_size=("budget", 700.0), funded_size=("budget", 500.0), keep=2000.0))

    @unittest.skipUnless(INST, "set NB3_INST to the research cache")
    def test_matches_prop_sim_on_real_trades(self):
        warnings.filterwarnings("ignore", category=RuntimeWarning)
        d = il.load_instrument(INST, "QQQ")
        import lab4
        d = lab4.enrich(d)
        pool = lc.build_pool(d, 20250101, 20260331, 0.3, 3.0, 1)
        self.check(pool, lc.Config(), H=504, n=200)


if __name__ == "__main__":
    unittest.main()
