"""Mechanics tests for the prop-firm lifecycle simulator (synthetic day sequences, no market data)."""
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import prop_sim as ps  # noqa: E402


def days(pnl, low=None, c=1.0, dpr=300.0):
    pnl = np.array(pnl, float)
    low = np.minimum(np.array(low if low is not None else np.minimum(pnl, 0), float), 0)
    n = len(pnl)
    return (pnl, low, np.ones(n, bool), np.full(n, c), np.full(n, dpr))


def run(firm, ev, fu, policy="max_earliest", max_att=1, pool=None, src=None):
    h = len(ev[0])
    return ps.run_stream(firm, ev, fu, h, max_att, policy, pool, src)


class DrawdownTests(unittest.TestCase):
    def test_real_time_breach_fails_even_if_day_closes_green(self):
        f = ps.FIRMS["lucid"]
        ev = days([500, 500], low=[-2100, 0])
        att, _ = run(f, ev, ev)
        self.assertEqual(att[0]["end"], "eval_failed")
        self.assertEqual(att[0]["end_day"], 0)

    def test_closed_trade_method_misses_that_breach(self):
        f = ps.FIRMS["audit_old"]
        ev = days([500, 500, 500, 500, 500, 500], low=[-2100, 0, 0, 0, 0, 0])
        att, _ = run(f, ev, ev)
        self.assertTrue(att[0]["passed"])

    def test_eod_floor_trails_closing_balance(self):
        f = replace(ps.FIRMS["lucid"], eval_consistency=None)
        # +1500 close lifts the floor to -500; after a -1000 day (balance +500) a -1100 low breaches it
        ev = days([1500, -1000, 100], low=[0, -1000, -1100])
        att, _ = run(f, ev, ev)
        self.assertEqual(att[0]["end"], "eval_failed")
        self.assertEqual(att[0]["end_day"], 2)
        static = replace(f, eval_lock=-2000.0)              # a floor that never trails would survive
        self.assertEqual(run(static, ev, ev)[0][0]["end"], "horizon")

    def test_intraday_trailing_uses_unrealised_peak(self):
        f_eod = replace(ps.FIRMS["topstep"], eval_consistency=None)
        f_intra = replace(f_eod, trail="intraday")
        pool = {"hi_path": [np.array([0.0, 1000 / 300, 1000 / 300])], "lo_path": [np.array([0.0, 0.0, -1100 / 300])]}
        ev = days([-1100], low=[-1100])
        src = np.zeros(1, int)
        self.assertEqual(run(f_eod, ev, ev, pool=pool, src=src)[0][0]["end"], "horizon")
        self.assertEqual(run(f_intra, ev, ev, pool=pool, src=src)[0][0]["end"], "eval_failed")


class EvaluationTests(unittest.TestCase):
    def test_topstep_consistency_raises_effective_target(self):
        f = ps.FIRMS["topstep"]
        a, _ = run(f, days([1700, 1400, 0]), days([0, 0, 0]))
        self.assertEqual(a[0]["days_to_pass"], 2)            # 1700 <= 0.55 x 3100
        b, _ = run(f, days([1800, 1300, 200, 0]), days([0] * 4))
        self.assertEqual(b[0]["days_to_pass"], 3)            # needs 1800 / 0.55 = 3273

    def test_monthly_fees_and_activation(self):
        f = replace(ps.FIRMS["topstep"], eval_consistency=None)
        n = 45
        pnl = [0.0] * 44 + [3000.0]
        a, cash = run(f, days(pnl), days([0.0] * n))
        # eval fee + API at days 0, 21, 42; activation on the pass day
        self.assertAlmostEqual(a[0]["fees"], 3 * 49 + 3 * 29 + 149)
        self.assertAlmostEqual(cash.sum(), -a[0]["fees"])


class FundedTests(unittest.TestCase):
    def test_topstep_payout_resets_loss_limit_to_zero(self):
        f = ps.FIRMS["topstep"]
        ev = days([1600, 1500] + [0] * 8)
        fu = days([0, 0, 0, 600, 600, 600, 600, 600, 0, -1600], low=[0] * 9 + [-1600])
        a, cash = run(f, ev, fu)
        r = a[0]
        self.assertEqual(r["payouts"], [1500.0])             # 50% of $3,000
        self.assertEqual(r["end"], "blown")                  # $1,500 balance, floor $0, -$1,600 low
        self.assertAlmostEqual(r["net_payouts"], 1500 * 0.9 - ps.TRANSFER_FEE)

    def test_cushion_policy_withdraws_less(self):
        f = ps.FIRMS["topstep"]
        ev = days([1600, 1500] + [0] * 8)
        fu = days([0, 0, 0, 600, 600, 600, 600, 600, 0, 0])
        a, _ = run(f, ev, fu, policy="above_cushion")
        self.assertEqual(a[0]["payouts"], [1000.0])          # keeps $2,000 above the $0 floor

    def test_lucid_moves_live_after_five_payouts(self):
        f = ps.FIRMS["lucid"]
        ev = days([1100, 1000, 1000] + [0] * 60)
        fu = days([0, 0, 0] + [1000.0] * 60)
        a, _ = run(f, ev, fu)
        self.assertEqual(len(a[0]["payouts"]), 5)
        self.assertEqual(a[0]["end"], "moved_live")
        self.assertTrue(all(p <= 2000 for p in a[0]["payouts"]))

    def test_tradeify_payout_caps_and_threshold(self):
        f = ps.FIRMS["tradeify"]
        ev = days([1000, 1000, 1000] + [0] * 40)
        fu = days([0, 0, 0] + [700.0] * 40)
        a, _ = run(f, ev, fu)
        p = a[0]["payouts"]
        self.assertEqual(p[:2], [1500.0, 2000.0])
        self.assertGreaterEqual(min(p), 500)


class SizingAndEdgeTests(unittest.TestCase):
    def test_contracts_floor_and_skip(self):
        pool = {"dpr": np.array([200.0, 120.0, np.nan]), "has": np.array([True, True, False]),
                "r": np.array([1.0, 1.0, 0.0]), "lo": np.array([-0.5, -0.5, 0.0])}
        st = {"idx": np.array([[0, 1, 2]]), "src": np.array([[0, 1, 2]])}
        pnl, low, tr, c, _ = ps.day_arrays(pool, st, ps.FIRMS["topstep"], 150.0, None)
        self.assertEqual(c.tolist(), [[0.0, 1.0, 0.0]])
        self.assertEqual(tr.tolist(), [[False, True, False]])

    def test_zero_edge_conversion(self):
        rng = np.random.default_rng(0)
        n = 4000
        reason = np.where(rng.random(n) < 0.3, ps.TARGET, ps.STOP).astype(np.int8)
        rg = np.where(reason == ps.TARGET, 3.0, -1.0)
        pool = {"dkey": np.arange(n), "has": np.ones(n, bool), "rg": rg, "r": rg - 0.02, "reason": reason}
        st = ps.make_streams(pool, 400, 400, "bootstrap", 10, 0.0, 1)
        self.assertAlmostEqual(float(pool["rg"][st["src"]].mean()), 0.0, delta=0.02)


if __name__ == "__main__":
    unittest.main()
