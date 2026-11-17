"""Round-8 lab: no look-ahead in outside data, OTE levels, generalised bracket = lab6 for market entries.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backtest"))

import lab6  # noqa: E402
import lab8  # noqa: E402


class Lab8Tests(unittest.TestCase):
    def test_outside_values_come_from_the_previous_date_only(self):
        dates = np.array([20240102, 20240103, 20240104])
        vals = np.array([1.0, 2.0, 3.0])
        got = lab8.prev_values(np.array([20240102, 20240103, 20240105]), dates, vals)
        self.assertTrue(np.isnan(got[0]))
        self.assertEqual(list(got[1:]), [1.0, 3.0])

    def test_market_entries_match_lab6(self):
        rng = np.random.default_rng(1)
        p = 100 + np.cumsum(rng.normal(0, 0.03, (6, 390)), axis=1)
        d = {"o": p, "h": p + 0.01, "l": p - 0.01, "cf": p, "c5": p[:, 4::5], "atr_prev": np.ones(6), "dkey": np.arange(6)}
        sig = np.zeros((6, 78), np.int8)
        sig[:, 4] = [1, -1, 1, -1, 1, -1]
        sig[:, 30] = 1
        a = lab6.bracket6(d, sig, 1.5, 0.3, max_trades=2, slip=0.01, commission=0.0, tick=0.01)
        b = lab8.bracket8(d, sig, rr=1.5, stop_atr=0.3, max_trades=2, slip=0.01, tick=0.01)
        np.testing.assert_allclose(np.sort(a["r"]), np.sort(b["r"]))

    def test_ote_levels_for_a_long(self):
        h5 = np.full((1, 78), 100.0); l5 = np.full((1, 78), 100.0)
        h5[0, 3], l5[0, 0] = 101.0, 99.0                      # leg 99 -> 101 by bar 3
        d = {"h5": h5, "l5": l5, "atr_prev": np.array([1.0])}
        sig = np.zeros((1, 78), np.int8); sig[0, 3] = 1
        lim, stp, tgt = lab8.ote_levels(d, sig, 0.705, 0.27)
        self.assertAlmostEqual(lim[0, 3], 101.0 - 0.705 * 2.0)
        self.assertAlmostEqual(stp[0, 3], 99.0 - 0.02)
        self.assertAlmostEqual(tgt[0, 3], 101.0 + 0.27 * 2.0)


if __name__ == "__main__":
    unittest.main()
