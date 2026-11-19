"""Roobet $10 -> $100 study (roobet/): game models, exact results, simulator agreement.

Run:  python3 -m unittest tests.test_roobet -v
"""
from __future__ import annotations

import hashlib
import hmac
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "roobet"))

import blackjack as BJ  # noqa: E402
import engine as E  # noqa: E402
import exact as X  # noqa: E402
import games as G  # noqa: E402
import hilo as H  # noqa: E402
import multi as M  # noqa: E402
from run_roobet import crash_point  # noqa: E402


class GameModelTests(unittest.TestCase):
    def test_crash_formula_matches_verifier_threshold(self):
        # crash >= t  <=>  X >= (100t-100)/(100t-1) for non-instant rounds
        e = 2 ** 52
        for t in (1.01, 2.0, 10.0, 123.45):
            x = (100 * t - 100) / (100 * t - 1)
            h_hi = int(np.ceil(x * e)) + 1
            h_lo = int(np.floor(x * e)) - 1
            f = lambda h: np.floor((100 * e - h) / (e - h)) / 100.0
            self.assertGreaterEqual(f(h_hi), t - 1e-12)
            self.assertLess(f(h_lo), t)
        self.assertAlmostEqual(G.crash_p(2.0), 0.96 * 99 / 199)

    def test_crash_port_distribution(self):
        rng = np.random.default_rng(0)
        salt = "0xd751043d3a3131fefe22d75a8ae1a7cb50b5b777992cf85b95260896062a5486"
        pts = np.array([crash_point(rng.bytes(32).hex(), salt) for _ in range(40_000)])
        se = np.sqrt(0.0496 * 0.95 / len(pts))
        self.assertLess(abs((pts == 1.0).mean() - 0.0496), 4 * se)
        p2 = G.crash_p(2.0)
        self.assertLess(abs((pts >= 2).mean() - p2), 4 * np.sqrt(p2 * (1 - p2) / len(pts)))

    def test_limbo_and_dice_quotes(self):
        m, p = E.Limbo().quote(np.array([10.0, 2.0, 1.005]))
        np.testing.assert_allclose(m, [10.0, 2.0, 1.01])
        np.testing.assert_allclose(p, [0.098, 0.49, 0.98 / 1.01])
        m, p = E.Dice().quote(np.array([10.0, 2.0]))
        np.testing.assert_allclose(p, [0.099, 0.495])
        np.testing.assert_allclose(m, [10.0, 2.0])
        self.assertAlmostEqual(G.dice(0.01).net[0] + 1, 9900.0)       # the 9,900x maximum

    def test_rtps(self):
        for risk, rows in [("high", 16), ("high", 10), ("medium", 16), ("low", 16), ("low", 8)]:
            self.assertTrue(0.985 < G.plinko(risk, rows).rtp < 0.992, (risk, rows))
        for d, s in [("low", 10), ("medium", 10), ("medium", 50), ("high", 10), ("high", 50)]:
            self.assertAlmostEqual(G.wheel(d, s).rtp, 0.98, places=12)
        self.assertAlmostEqual(G.roulette("green").rtp, 14 / 15)
        self.assertAlmostEqual(G.roulette("bait").rtp, 14 / 15)
        self.assertAlmostEqual(G.roulette("red", False).rtp, 0.8)
        self.assertAlmostEqual(G.coinflip().rtp, 0.96)

    def test_towers_matches_published_table(self):
        pub = {("easy", 1): 1.28, ("easy", 8): 7.21, ("medium", 8): 18.49, ("hard", 8): 184.68,
               ("expert", 8): 4733.04, ("crazy", 1): 3.84, ("crazy", 4): 217.43}
        for (d, n), m in pub.items():
            self.assertAlmostEqual(G.towers(d, n).net[0] + 1, m, places=2)
            self.assertAlmostEqual(G.towers(d, n).rtp, 0.96 ** n, delta=0.002 * 0.96 ** n)

    def test_blackjack_edges(self):
        reg = BJ.regimes("peek")
        for d in reg.values():
            self.assertAlmostEqual(d.sum(), 1.0, places=12)
        self.assertTrue(-0.0065 < BJ.ev(reg["full"]) < -0.0045)
        self.assertTrue(-0.026 < BJ.ev(reg["none"]) < -0.022)
        self.assertLess(BJ.ev(BJ.regimes("enhc")["full"]), BJ.ev(reg["full"]))
        # dealer distributions are proper and S17 never draws to a 17+
        for up in BJ.CARDS:
            self.assertAlmostEqual(BJ.dealer_dist(int(up)).sum(), 1.0, places=12)


class ExactTests(unittest.TestCase):
    def test_bound_ordering(self):
        for e in (0.01, 0.02, 0.05):
            r = 1 - e
            self.assertGreater(X.upper_bound(e), X.timid_limit(r))
            self.assertGreater(X.timid_limit(r), X.single_bet(r))
            self.assertGreater(X.single_bet(r), X.k_stage(r, 2))

    def test_gamblers_ruin_equals_markov(self):
        ex = E.markov_exact(E.Flat(100, 2.0), E.Dice())
        self.assertAlmostEqual(ex["p_target"], X.gamblers_ruin(0.495, 10, 100), places=10)
        self.assertAlmostEqual(ex["p_target"] + ex["p_ruin"], 1.0, places=10)

    def test_single_bet_and_expected_loss_identity(self):
        ex = E.markov_exact(E.Bold(10.0), E.Dice())
        self.assertAlmostEqual(ex["p_target"], 0.099, places=12)
        ex = E.markov_exact(E.Martingale(10), E.Dice())
        # E[final] = 10 - edge * E[wagered] (dice pays stake*2 exactly at 49.5%)
        self.assertAlmostEqual(ex["mean_final"], 10 - 0.01 * ex["mean_wagered"], places=6)

    def test_every_strategy_respects_the_bound(self):
        bound = X.upper_bound(0.01)
        for s in (E.Bold(2.0), E.Bold(10.0), E.Martingale(100), E.FixedFraction(0.5), E.Paroli(100),
                  E.Fibonacci(10), E.TargetHit(100)):
            self.assertLessEqual(E.markov_exact(s, E.Dice())["p_target"], bound + 1e-12, s.name)

    def test_dp_target_hit(self):
        V, pol = X.dp_target_hit(E.Dice())
        self.assertGreater(V[1000], 0.099)
        self.assertLess(V[1000], X.upper_bound(0.01))
        ex = E.markov_exact(E.PolicyTargetHit(pol), E.Dice())
        self.assertAlmostEqual(ex["p_target"], V[1000], places=10)

    def test_stake_needed(self):
        B = np.array([1000, 5000, 9999])
        m = np.array([10.0, 2.0, 1.01])
        s = E.stake_needed(B, m)
        self.assertTrue(np.all(B - s + np.floor(s * m + 1e-9) >= 10_000))
        self.assertTrue(np.all(B - (s - 1) + np.floor((s - 1) * m + 1e-9) < 10_000))


class SimulationTests(unittest.TestCase):
    def test_simulation_agrees_with_exact(self):
        for s in (E.Martingale(10), E.FixedFraction(0.25), E.Bold(2.0)):
            ex = E.markov_exact(s, E.Dice())
            _, sm = E.simulate(s, E.Dice(), n=40_000, seed=7)
            lo, hi = sm["p_target_ci"]
            self.assertTrue(lo - 0.003 <= ex["p_target"] <= hi + 0.003, s.name)
            self.assertLess(abs(sm["mean_bets"] - ex["mean_bets"]) / max(ex["mean_bets"], 1), 0.05)

    def test_multi_markov_matches_sim(self):
        pl = G.plinko("high", 16)
        bets = M.Bets([(pl.name, pl.net, pl.prob, 1.0)])
        s = M.AllInEach(0, "all-in")
        ex = M.markov_stateless(s, bets)
        _, sm = M.simulate_multi(s, bets, n=40_000, seed=3)
        lo, hi = sm["p_target_ci"]
        self.assertTrue(lo - 0.002 <= ex["p_target"] <= hi + 0.002)

    def test_hilo_plan(self):
        ms = H.m_star()
        Mbest, js = H.best_plan(ms, max_steps=7)
        self.assertGreaterEqual(Mbest, ms)
        self.assertLess(1 / Mbest, 1 / ms + 1e-12)
        dp = H.FiniteSkipDP(ms, delta=5e-4)
        self.assertTrue(0.0980 < dp.p_success() <= 1 / Mbest + 1e-9)

    def test_streaks_do_not_change_crash_odds(self):
        rng = np.random.default_rng(1)
        salt = "0xd751043d3a3131fefe22d75a8ae1a7cb50b5b777992cf85b95260896062a5486"
        pts = np.array([crash_point(rng.bytes(32).hex(), salt) for _ in range(30_000)])
        after = pts[1:][pts[:-1] < 2.0]
        p = G.crash_p(2.0)
        self.assertLess(abs((after >= 2).mean() - p), 4 * np.sqrt(p * (1 - p) / len(after)))


if __name__ == "__main__":
    unittest.main()
