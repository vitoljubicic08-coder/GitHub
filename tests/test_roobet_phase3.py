"""Roobet Phase 3 ($20 -> $100): start bankroll, Auto Bet semantics, tabular policies,
game switching, optimality checks, baccarat and the provably-fair dice derivation.

Run:  python3 -m unittest tests.test_roobet_phase3 -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "roobet"))

import autobet as AB  # noqa: E402
import baccarat as BC  # noqa: E402
import engine as E  # noqa: E402
import exact as X  # noqa: E402
import fairsim as F  # noqa: E402
import games as G  # noqa: E402
import tabular as TB  # noqa: E402

START = 2000


class TwentyDollarTheory(unittest.TestCase):
    def test_bounds_at_20(self):
        self.assertAlmostEqual(X.single_bet(0.99, START), 0.198)
        self.assertAlmostEqual(X.timid_limit(0.99, START), 1 - 0.8 ** 0.99)
        self.assertAlmostEqual(X.upper_bound(0.01, START), (20 - 0.0999 * 2) / (100 - 0.0999 * 2), places=4)
        self.assertLess(X.upper_bound(0.01, START), 0.2)
        self.assertGreater(X.upper_bound(0.01, START), X.timid_limit(0.99, START))
        self.assertAlmostEqual(X.upper_bound(0.0, START), 0.2)

    def test_single_bet_and_dp(self):
        ex = E.markov_exact(E.Bold(5.0), E.Dice(), levels=E.LEVELS20, start=START)
        self.assertAlmostEqual(ex["p_target"], 0.198, places=12)
        self.assertEqual(ex["reach"]["40"], ex["p_target"])
        V, pol = X.dp_target_hit(E.Dice())
        self.assertGreater(V[START], 0.198)
        self.assertLess(V[START], X.upper_bound(0.01, START))
        ex = E.markov_exact(E.PolicyTargetHit(pol), E.Dice(), levels=E.LEVELS20, start=START)
        self.assertAlmostEqual(ex["p_target"], V[START], places=9)
        # E[final] = 20 - edge x E[wagered] (exact for Dice: every multiplier is 99/chance)
        self.assertAlmostEqual(ex["mean_final"], 20 - 0.01 * ex["mean_wagered"], places=3)

    def test_target_hit_stats_match_markov(self):
        V, pol = X.dp_target_hit(E.Dice())
        P, Fm, W, K = X.target_hit_stats(E.Dice(), pol)
        self.assertAlmostEqual(P[START], V[START], places=10)
        ex = E.markov_exact(E.PolicyTargetHit(pol), E.Dice(), levels=E.LEVELS20, start=START)
        self.assertAlmostEqual(K[START], ex["mean_bets"], places=6)


class AutoBetSemantics(unittest.TestCase):
    def test_compounding_example_from_help_centre(self):
        ab = AB.AutoBet(100, 2.0, on_win="increase", win_pct=0.20, start=1000)
        st = {"i": np.array([0, 1, 2]), "j": np.array([0, 0, 0])}
        np.testing.assert_array_equal(ab.stake(st), [100, 120, 144])

    def test_reset_and_increase(self):
        ab = AB.AutoBet(10, 2.0, on_loss="increase", loss_pct=1.0, stop_profit=8000, start=START)
        st = ab.init(2)
        B = np.array([START, START])
        st = ab.update_b(st, np.array([False, True]), B)
        np.testing.assert_array_equal(ab.stake(st), [20, 10])          # loss doubles, win resets
        st = ab.update_b(st, np.array([False, False]), B)
        np.testing.assert_array_equal(ab.stake(st), [40, 20])

    def test_stops_relative_to_start(self):
        ab = AB.AutoBet(100, 2.0, stop_profit=1000, stop_loss=500, start=START)
        st = ab.init(4)
        np.testing.assert_array_equal(ab.stop(np.array([3000, 2999, 1500, 1501]), st), [True, False, True, False])
        # halts when the next bet does not fit
        big = AB.AutoBet(1500, 2.0, start=START)
        self.assertTrue(big.stop(np.array([1499]), big.init(1))[0])

    def test_geometric_every_win_lands_on_target(self):
        for c in (10.0, 2.41, 0.84):
            ab = AB.geometric(c)
            m = ab.mult
            B, j = START, 0
            while True:
                s = int(ab.stake({"i": np.array([0]), "j": np.array([j])})[0])
                if s > B:
                    break
                self.assertGreaterEqual(B - s + np.floor(s * m + 1e-9), G.TARGET)
                B, j = B - s, j + 1

    def test_autobet_markov_matches_simulation(self):
        ab = AB.AutoBet(100, 2.0, on_loss="increase", loss_pct=1.0, stop_profit=8000, start=START)
        ex = E.markov_exact(ab, E.Dice(), levels=E.LEVELS20, start=START)
        _, sm = E.simulate(ab, E.Dice(), n=60_000, seed=4, start=START, levels=E.LEVELS20)
        lo, hi = sm["p_target_ci"]
        self.assertTrue(lo - 0.003 <= ex["p_target"] <= hi + 0.003)
        self.assertAlmostEqual(ex["p_target"] + ex["p_ruin"] + ex["p_stopped"], 1.0, places=9)


class TablesAndSwitching(unittest.TestCase):
    def test_table_of_dp_policy(self):
        V, pol = X.dp_target_hit(E.Dice())
        tab = TB.two_outcome(E.Dice(), lambda B: pol[B], "dp")
        ev = TB.evaluate(tab, START)
        self.assertAlmostEqual(ev["p_target"], V[START], places=9)
        _, sm = TB.simulate(tab, n=80_000, seed=2, start=START)
        lo, hi = sm["p_target_ci"]
        self.assertTrue(lo - 0.003 <= ev["p_target"] <= hi + 0.003)

    def test_menu_picks_likeliest_option(self):
        m, p = E.towers_menu().quote(np.array([10.0]))
        self.assertAlmostEqual(p[0], 0.0625)            # hard x4 or crazy x2, not medium x7 (5.85%)
        self.assertGreaterEqual(m[0], 10.0)

    def test_bestof_takes_highest_probability(self):
        g = E.BestOf([E.Dice(), E.Limbo()])
        m, p, k = g.choose(np.array([2.0, 5000.0]))
        self.assertEqual(k[0], 0)                       # Dice 49.5% beats Limbo 49%
        self.assertEqual(k[1], 1)                       # Limbo 5000x (0.0196%) beats Dice's 9900x step
        self.assertTrue(np.all(m >= np.array([2.0, 5000.0]) - 1e-9))

    def test_max_improvement_sign(self):
        V = np.arange(G.TARGET) / G.TARGET              # value of a fair game: linear
        self.assertLess(X.max_improvement(V, (1.0, -1.0), (0.495, 0.505), b_lo=4000, b_hi=4100)[0], 0)
        self.assertGreater(X.max_improvement(V, (1.0, -1.0), (0.51, 0.49), b_lo=4000, b_hi=4100)[0], 0)


class BaccaratAndFairness(unittest.TestCase):
    def test_baccarat_8_decks(self):
        q = BC.outcome_probs(8)
        self.assertAlmostEqual(sum(q.values()), 1.0, places=9)
        self.assertAlmostEqual(q["banker"], 0.458597, places=6)
        self.assertAlmostEqual(q["player"], 0.446247, places=6)
        self.assertAlmostEqual(q["tie"], 0.095156, places=6)

    def test_roll_derivation(self):
        r = [F.roll_hundredths("s" * 64, "client", i) for i in range(5000)]
        self.assertTrue(all(0 <= x <= 9999 for x in r))
        self.assertEqual(r[:3], [F.roll_hundredths("s" * 64, "client", i) for i in range(3)])
        win = np.mean([x < 1980 for x in r])
        self.assertLess(abs(win - 0.198), 4 * np.sqrt(0.198 * 0.802 / 5000))

    def test_fair_simulator_single_bet(self):
        r = F.play_policy(np.arange(G.TARGET), 20_000, seed=3)
        self.assertLess(abs(r["p_target"] - 0.198), 4 * np.sqrt(0.198 * 0.802 / 20_000))
        self.assertEqual(r["mean_bets"], 1.0)


if __name__ == "__main__":
    unittest.main()
