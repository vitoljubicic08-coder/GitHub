"""Round-7 lab: the trailing exit leaves at the next bar's open after a check-time close through max(band, VWAP).

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backtest"))

import lab7  # noqa: E402


def day(path, vwap):
    p = path[None, :].astype(float)
    sh = (1, 78, 5)
    return {"o": p, "h": p, "l": p, "cf": p, "c5": p[:, 4::5], "atr_prev": np.array([1.0]),
            "h5": p.reshape(sh).max(2), "l5": p.reshape(sh).min(2), "dkey": np.array([20240102]),
            "day_open": np.array([100.0]), "prev_close": np.array([100.0]), "sig5": np.full((1, 78), 0.001),
            "vwap5": np.full((1, 78), vwap), "has5": np.ones((1, 78), bool)}


class TrailTests(unittest.TestCase):
    def test_exit_after_close_back_below_vwap(self):
        path = np.full(390, 100.0)
        path[0:5] = 100.5                       # bar 0 closes above the 100.1 band -> long at minute 5
        path[5:30] = 100.8
        path[30:35] = 100.2                     # bar 6 closes at 100.2 < VWAP 100.3 -> exit at minute 35's open
        path[35:] = 99.0
        d = day(path, vwap=100.3)
        sig = lab7.signals7(d, 1.0)
        t = lab7.trail_trades(d, sig, 1.0, 1.0, False, False, slip=0.0)
        self.assertEqual(list(t["kind"]), [3])
        self.assertEqual(int(t["exit"][0]), 35)
        self.assertAlmostEqual(t["r"][0], (99.0 - 100.8) / 1.0)

    def test_check30_waits_for_the_half_hour(self):
        path = np.full(390, 100.0)
        path[0:5] = 100.5
        path[5:30] = 100.8
        path[30:35] = 100.2                     # bar 6 closes at minute 35: not a :00/:30 close
        path[35:] = 100.25                      # bar 11 closes at minute 60 (10:30) below VWAP -> exit at 60
        d = day(path, vwap=100.3)
        sig = lab7.signals7(d, 1.0)             # bar 0 ends at 09:35, so signals must also use check30
        sig30 = lab7.signals7(d, 1.0, check30=True)
        self.assertEqual(int(np.flatnonzero(sig[0])[0]), 0)
        self.assertEqual(int(np.flatnonzero(sig30[0])[0]), 5)
        t = lab7.trail_trades(d, sig30, 1.0, 1.0, False, True, slip=0.0)
        self.assertEqual(int(t["exit"][0]), 60)

    def test_hard_stop_beats_trail(self):
        path = np.full(390, 100.0)
        path[0:5] = 100.5
        path[5:8] = 100.8
        path[8:] = 99.5                         # through the 0.3 stop (100.5) within the bar
        d = day(path, vwap=100.3)
        t = lab7.trail_trades(d, lab7.signals7(d, 1.0), 0.3, 1.0, False, False, slip=0.0)
        self.assertEqual(list(t["kind"]), [0])


if __name__ == "__main__":
    unittest.main()
