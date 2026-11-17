"""Round-4 lab: bracket fills with ATR and structural stops, and a crafted Candle Range Theory day.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backtest"))

import lab4  # noqa: E402


def day(path: np.ndarray) -> dict:
    """One session whose every minute trades at a single price (open = high = low = close)."""
    p = path[None, :].astype(float)
    return {"o": p, "h": p, "l": p, "cf": p, "c5": p[:, 4::5], "atr_prev": np.array([1.0]),
            "dkey": np.array([20240102])}


RISING = 100 + 0.01 * np.maximum(0, np.arange(390) - 5)      # flat to minute 5, then +0.01 per minute


class BracketTests(unittest.TestCase):
    def one(self, d, direction, stop, lvl=None, rr=3.0):
        sig = np.zeros((1, 78), np.int8)
        sig[0, 0] = direction
        lv = None
        if lvl is not None:
            lv = np.full((1, 78), np.nan)
            lv[0, 0] = lvl
        res = lab4.bracket(d, sig, stop, lv, rrs=(rr,))[rr]
        return res["r"], res["kind"]

    def test_long_reaches_target(self):
        r, k = self.one(day(RISING), 1, 0.1)
        # fill 100.00 + 2 ticks = 100.02, stop distance 0.10, target 100.32 (no slippage on the limit)
        self.assertEqual(list(k), [1])
        self.assertAlmostEqual(r[0], (0.30 - 0.01) / 0.10, places=6)

    def test_short_is_stopped_with_slippage(self):
        r, k = self.one(day(RISING), -1, 0.1)
        # fill 99.98, stop 100.08, exit 100.08 + 2 ticks
        self.assertEqual(list(k), [0])
        self.assertAlmostEqual(r[0], (-(100.10 - 99.98) - 0.01) / 0.10, places=6)

    def test_structural_stop_distance(self):
        r, k = self.one(day(RISING), 1, "struct", lvl=99.90)
        dist = (100.02 - 99.90) + 0.02            # beyond the level + 0.02 ATR
        self.assertEqual(list(k), [1])
        self.assertAlmostEqual(r[0], (3 * dist - 0.01) / dist, places=6)

    def test_structural_level_too_far_or_wrong_side_is_skipped(self):
        for lvl in (98.5, 100.5):                 # 1.5 ATR away / above a long's entry
            r, _ = self.one(day(RISING), 1, "struct", lvl=lvl)
            self.assertEqual(len(r), 0)

    def test_time_exit(self):
        r, k = self.one(day(np.full(390, 100.0)), 1, 0.5)
        self.assertEqual(list(k), [2])
        self.assertAlmostEqual(r[0], ((99.98 - 100.02) - 0.01) / 0.5, places=6)


class CrtTests(unittest.TestCase):
    def test_sweep_of_first_hour_high_then_close_back_inside_is_a_short(self):
        path = np.full(390, 100.0)
        path[:60] = np.linspace(99.0, 101.0, 60)        # first hour: range 99 .. 101
        path[60:65] = 100.5
        path[65:70] = [100.8, 101.4, 101.2, 100.9, 100.7]   # bar 13 sweeps 101 and closes back inside
        path[70:] = 100.6
        d = day(path)
        h = d["h"]
        d.update({"h5": np.nanmax(h.reshape(1, 78, 5), 2), "l5": np.nanmin(h.reshape(1, 78, 5), 2),
                  "o5": h[:, ::5], "has5": np.ones((1, 78), bool)})
        sig, lvl = lab4.signals4(d, "crt", 60)
        first = int(np.flatnonzero(sig[0])[0])
        self.assertEqual((first, sig[0, first]), (13, -1))
        self.assertAlmostEqual(lvl[0, first], 101.4)


if __name__ == "__main__":
    unittest.main()
