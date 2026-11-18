"""Portfolio research engine (investing/research2026): deposits, tax lots, rebalancing, bootstrap, rules.

Run:  python3 -m unittest tests.test_research2026 -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "investing" / "research2026"))

import lots  # noqa: E402
import portfolios as pf  # noqa: E402
import sim  # noqa: E402
import sleeves as sv  # noqa: E402


def flat_paths(n=3, months=24, sleeves=2, monthly=0.0):
    return np.full((n, months, sleeves), np.log1p(monthly))


class SimulateTests(unittest.TestCase):
    def test_deposits_and_values_with_zero_returns(self):
        R = flat_paths()
        out = sim.simulate(R, ["CASH", "WORLD"], {"CASH": 0.5, "WORLD": 0.5}, contrib=100)
        self.assertEqual(out["deposits"][-1], 5000 + 24 * 100)
        cost = 0.5 * 0.0002 + 0.5 * 0.0010
        self.assertAlmostEqual(out["V"][0, -1], (5000 + 2400) * (1 - cost), places=6)

    def test_initial_lot_tax_free_after_two_years_but_not_before(self):
        R = flat_paths(n=1, months=24, sleeves=1, monthly=0.02)
        g = 1.02 ** 24
        at24 = sim.simulate(R, ["WORLD"], {"WORLD": 1.0}, horizon=24, tax_horizon=24)
        self.assertAlmostEqual(at24["after_tax"][0], at24["liq"][0])            # held > 2 years: no tax
        at12 = sim.simulate(R, ["WORLD"], {"WORLD": 1.0}, horizon=12, tax_horizon=12)
        gain = at12["liq"][0] - 5000
        self.assertAlmostEqual(at12["after_tax"][0], at12["liq"][0] - 0.12 * gain, places=6)
        self.assertGreater(at24["liq"][0], 5000 * g * 0.997)

    def test_contribution_lots_are_taxed_at_24_months(self):
        R = flat_paths(n=1, months=24, sleeves=1, monthly=0.01)
        out = sim.simulate(R, ["WORLD"], {"WORLD": 1.0}, contrib=200, horizon=24, tax_horizon=24)
        self.assertLess(out["after_tax"][0], out["liq"][0])

    def test_self_balance_tracks_targets_better_than_target_split(self):
        rng = np.random.default_rng(0)
        R = rng.normal(0.005, 0.06, (2000, 24, 2))
        R[:, :, 0] += 0.02                                                   # sleeve 0 keeps drifting up
        port = {"A": 0.5, "B": 0.5}
        tgt = sim.simulate(R, ["A", "B"], port, contrib=200, method="target")
        sb = sim.simulate(R, ["A", "B"], port, contrib=200, method="self_balance")
        self.assertLess(np.median(sb["drift"]), np.median(tgt["drift"]))
        np.testing.assert_allclose(sb["deposits"], tgt["deposits"])

    def test_rebalance_sale_pays_tax_on_gains_first_in_first_out(self):
        R = np.zeros((1, 24, 2))
        R[0, 0, 0] = np.log(2.0)                                            # sleeve A doubles in month 1
        out = sim.simulate(R, ["A", "B"], {"A": 0.5, "B": 0.5}, method="target_rebal", rebalance_month=12)
        self.assertGreater(out["tax_paid_rebal"][0], 0)
        a_val = 2500 * (1 - 0.001) * 2
        b_val = 2500 * (1 - 0.001)
        sold = a_val - (a_val + b_val) / 2
        expected_gain = sold * (1 - 2500 / a_val)
        self.assertAlmostEqual(out["tax_paid_rebal"][0], 0.12 * expected_gain, places=6)


class GeneratorTests(unittest.TestCase):
    def test_stationary_bootstrap_indices_are_valid_and_mostly_consecutive(self):
        idx = sim.stationary_bootstrap(100, 500, 24, 6, np.random.default_rng(1))
        self.assertEqual(idx.shape, (500, 24))
        self.assertTrue(((idx >= 0) & (idx < 100)).all())
        steps = (np.diff(idx, axis=1) % 100) == 1
        self.assertGreater(steps.mean(), 0.75)                              # p(new block) = 1/6

    def test_forward_bootstrap_hits_its_target_drift(self):
        rng = np.random.default_rng(2)
        X = pd.DataFrame(rng.normal(0.01, 0.04, (300, 2)), columns=["CASH", "WORLD"])
        X["CASH"] = 0.002
        R, lab = sim.bootstrap_forward(X, n_paths=8000, scenarios=["consensus"], slopes=(1.0,))
        self.assertAlmostEqual(R[:, :, 1].mean() * 12, np.log1p(0.07), delta=0.004)
        self.assertTrue((lab == "consensus/1.0").all())

    def test_required_return(self):
        self.assertAlmostEqual(sim.required_return(5000, 0, 24, 10_000), 2 ** 0.5 - 1, places=6)
        self.assertLess(sim.required_return(5000, 200, 24, 10_000), 0.02)
        self.assertLess(sim.required_return(5000, 100, 24, 10_000), sim.required_return(5000, 0, 24, 10_000))


class RulesAndBacktestTests(unittest.TestCase):
    def test_lock_target_moves_to_cash_once_target_is_hit(self):
        Gp = np.full((1, 24), 1.0)
        Gp[0, 0] = 2.1
        Gp[0, 1:] = 0.9
        Gc = np.ones((1, 24))
        hold = sim.apply_rule(Gp, Gc, "hold")
        lock = sim.apply_rule(Gp, Gc, "lock_target")
        self.assertLess(hold["final"][0], 10_000)
        self.assertGreater(lock["final"][0], 10_000 * 0.85)                  # minus switch cost and 12% tax

    def test_lump_sum_vs_dca_in_a_rising_market(self):
        Gp = np.full((1, 24), 1.02)
        Gc = np.ones((1, 24))
        self.assertGreater(sim.entry_plan(Gp, Gc, "lump")[0], sim.entry_plan(Gp, Gc, "dca6")[0])

    def test_annual_rebalance_resets_weights(self):
        idx = pd.date_range("2020-01-31", periods=24, freq="ME")
        rets = pd.DataFrame({"A": 0.05, "B": 0.0}, index=idx)
        none = pf.run(rets, {"A": 0.5, "B": 0.5}, "none")
        ann = pf.run(rets, {"A": 0.5, "B": 0.5}, "annual")
        self.assertGreater(none.iloc[-1], ann.iloc[-1])                     # drifting into the winner

    def test_lognormal_tradeoff_needs_volatility_to_double(self):
        rows = sim.lognormal_tradeoff(0.07, 2.0)
        self.assertEqual(rows[0]["p_double"], 0.0)
        self.assertLess(rows[3]["p_double"], 0.01)                          # 15% volatility
        self.assertGreater(rows[-1]["p_loss40"], rows[3]["p_loss40"])


class Phase2DriftTests(unittest.TestCase):
    """CAPM must hold for arithmetic expected returns; the world sleeve keeps its compound return."""

    def setUp(self):
        self.cols = ["CASH", "WORLD", "HI"]
        self.beta = pd.Series({"CASH": 0.0, "WORLD": 1.0, "HI": 2.0})
        self.vol = pd.Series({"CASH": 0.0, "WORLD": 0.15, "HI": 0.50})
        self.scn = {"world": 0.07, "gold": 0.05, "ai_alpha": 0.0}

    def test_world_keeps_its_compound_return(self):
        mu = sim.forward_mu(self.cols, self.beta, self.scn, vol=self.vol, mode="arith")
        self.assertAlmostEqual(np.expm1(mu[1] * 12), 0.07, places=10)

    def test_arithmetic_capm_and_volatility_drag(self):
        mu = sim.forward_mu(self.cols, self.beta, self.scn, vol=self.vol, mode="arith")
        e_w = 1.07 * np.exp(0.15 ** 2 / 2) - 1
        e_hi = np.exp(mu[2] * 12 + 0.5 ** 2 / 2) - 1                        # lognormal mean
        self.assertAlmostEqual(e_hi, sim.RF + 2.0 * (e_w - sim.RF), places=10)
        self.assertLess(np.expm1(mu[2] * 12), e_hi)                           # median below mean

    def test_phase1_compound_mode_overstates_high_volatility(self):
        old = sim.forward_mu(self.cols, self.beta, self.scn, vol=self.vol, mode="compound")
        new = sim.forward_mu(self.cols, self.beta, self.scn, vol=self.vol, mode="arith")
        self.assertGreater(old[2], new[2])
        self.assertAlmostEqual(np.expm1(old[2] * 12), sim.RF + 2.0 * (0.07 - sim.RF), places=10)

    def test_linear_bootstrap_restarts_instead_of_wrapping(self):
        rng_a, rng_b = np.random.default_rng(3), np.random.default_rng(3)
        lin = sim.stationary_bootstrap_linear(30, 4000, 24, 6, rng_a)
        circ = sim.stationary_bootstrap(30, 4000, 24, 6, rng_b)

        def after_last(idx):                       # share of moves out of the last month that go to month 0
            frm, to = idx[:, :-1], idx[:, 1:]
            m = frm == 29
            return (to[m] == 0).mean()
        self.assertGreater(after_last(circ), 0.75)  # wraps: 1 - 1/6 + (1/6)(1/30)
        self.assertLess(after_last(lin), 0.10)      # restarts at a random month: about 1/30
        self.assertTrue(((lin >= 0) & (lin < 30)).all())


class LotEngineTests(unittest.TestCase):
    def test_deposit_counts(self):
        self.assertEqual(lots.deposit_schedule(24, 200, "end").sum(), 24 * 200)
        self.assertEqual(lots.deposit_schedule(24, 200, "start").sum(), 23 * 200)

    def test_matches_linear_grid_formula_and_phase1_engine(self):
        rng = np.random.default_rng(0)
        R = rng.normal(0.006, 0.05, (500, 24, 3))
        port = {"A": 0.5, "B": 0.3, "CASH": 0.2}
        for c in (0, 150):
            s = lots.simulate_lots(R, ["A", "B", "CASH"], port, contrib=c)
            A, dep = lots.grid_matrices(R, ["A", "B", "CASH"], list(port), contrib=c)
            np.testing.assert_allclose(s["liq"], A @ np.array([0.5, 0.3, 0.2]), rtol=1e-12)
            old = sim.simulate(R, ["A", "B", "CASH"], port, contrib=c)
            np.testing.assert_allclose(s["after_tax"], old["after_tax"], rtol=1e-12)
            self.assertEqual(dep, 5000 + 24 * c)

    def test_each_lot_has_its_own_two_year_clock(self):
        R = np.full((1, 36, 1), np.log(1.01))                                   # +1% a month
        s = lots.simulate_lots(R, ["A"], {"A": 1.0}, contrib=100, horizon=36)
        tc = 0.001
        net = lambda m: (1 - tc) * (1 - tc) * 1.01 ** (36 - m)                # euro value per euro bought at month m
        taxable_gain = sum(100 * (net(m) - 1) for m in range(13, 37))           # lots bought in months 13..36
        self.assertAlmostEqual(s["tax"][0], 0.12 * taxable_gain, places=6)
        exempt = 5000 * net(0) + sum(100 * net(m) for m in range(1, 13))
        self.assertAlmostEqual(s["exempt_value"][0], exempt, places=6)

    def test_rebalance_sale_taxes_only_young_lots(self):
        R = np.zeros((1, 30, 2))
        R[0, 0, 0] = np.log(2.0)                                               # A doubles in month 1
        young = lots.simulate_lots(R, ["A", "B"], {"A": .5, "B": .5}, horizon=30, sell_rebalance_months=(12,))
        old = lots.simulate_lots(R, ["A", "B"], {"A": .5, "B": .5}, horizon=30, sell_rebalance_months=(25,))
        self.assertGreater(young["tax_rebal"][0], 0)
        self.assertEqual(old["tax_rebal"][0], 0.0)                              # initial lot older than 2 years

    def test_summary_thresholds_and_interval(self):
        f = np.array([3000.0, 6000.0, 10_000.0, 12_000.0])
        out = lots.summarize(f, 5000.0)
        self.assertEqual(out["p_ge_10000"], 0.5)
        self.assertEqual(out["p_loss40"], 0.25)
        self.assertEqual(out["p_double_invested"], 0.5)
        lo, hi = lots.binom_ci(0.5, 10_000)
        self.assertLess(hi - lo, 0.02)


class CurrencyTests(unittest.TestCase):
    def test_a_stronger_euro_lowers_euro_returns_of_dollar_assets(self):
        idx = pd.date_range("2024-01-01", periods=2, freq="D")
        r_usd = pd.DataFrame({"X": [0.0, 0.0]}, index=idx)
        fx = pd.Series([1.00, 1.10], index=idx)                                 # USD per EUR: euro +10%
        r_eur = sv.to_eur(r_usd, fx)
        self.assertAlmostEqual(r_eur["X"].iloc[1], 1 / 1.10 - 1, places=12)


if __name__ == "__main__":
    unittest.main()
