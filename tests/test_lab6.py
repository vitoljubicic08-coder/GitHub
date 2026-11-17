"""Round-6 bracket: market entries reproduce lab4.bracket; limit entries, candle stops and breakeven behave.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backtest"))

import lab4  # noqa: E402
import lab6  # noqa: E402


def day(path: np.ndarray) -> dict:
    p = path[None, :].astype(float)
    sh = (1, 78, 5)
    return {"o": p, "h": p, "l": p, "cf": p, "c5": p[:, 4::5], "atr_prev": np.array([1.0]),
            "h5": p.reshape(sh).max(2), "l5": p.reshape(sh).min(2), "dkey": np.array([20240102])}


def signal(direction=1, bar=0):
    s = np.zeros((1, 78), np.int8)
    s[0, bar] = direction
    return s


class Bracket6Tests(unittest.TestCase):
    def test_market_entry_matches_lab4(self):
        rng = np.random.default_rng(3)
        path = 100 + np.cumsum(rng.normal(0, 0.03, (5, 390)), axis=1)
        d = {"o": path, "h": path + 0.01, "l": path - 0.01, "cf": path, "c5": path[:, 4::5],
             "atr_prev": np.full(5, 1.0), "dkey": np.arange(5)}
        sig = np.zeros((5, 78), np.int8)
        sig[:, 3] = [1, -1, 1, -1, 1]
        sig[:, 20] = [-1, 1, 1, -1, 1]
        for mt in (1, 2):
            a = lab4.bracket(d, sig, 0.1, rrs=(2.0,), max_trades=mt)[2.0]
            b = lab6.bracket6(d, sig, 2.0, 0.1, max_trades=mt)
            np.testing.assert_allclose(np.sort(a["r"]), np.sort(b["r"]))
            np.testing.assert_allclose(np.sort(a["lo"]), np.sort(b["lo"]))

    def test_limit_entry_fills_on_pullback_at_the_limit(self):
        path = np.full(390, 100.0)
        path[5:10] = 99.80                    # pullback trades through 99.90 - 1 tick
        path[10:] = np.linspace(99.9, 102.0, 380)
        r = lab6.bracket6(day(path), signal(), 1.0, 0.2, entry="limit", offset=0.10, slip=0.01)
        self.assertEqual(len(r["r"]), 1)
        self.assertEqual(r["exit"][0] > 10, True)
        self.assertEqual(r["kind"][0], 1)    # minute 5 opens at 99.80, below the 99.90 limit: filled at 99.80
        tgt_px = path[10:][np.argmax(path[10:] >= 100.0)]    # the target minute opens above 100.00
        self.assertAlmostEqual(r["r"][0], (tgt_px - 99.80 - 2 * 0.005) / 0.2)

    def test_limit_entry_unfilled_without_trade_through(self):
        path = np.full(390, 100.0)
        path[5:10] = 99.895                   # touches the limit but not one tick through
        r = lab6.bracket6(day(path), signal(), 1.0, 0.2, entry="limit", offset=0.10, slip=0.01)
        self.assertEqual(len(r["r"]), 0)

    def test_candle_stop_sits_beyond_the_signal_bar(self):
        path = np.full(390, 100.0)
        path[0:5] = [99.5, 99.8, 100.0, 100.2, 100.4]      # signal bar low 99.5
        path[5:] = 100.4 + 0.01 * np.arange(385)
        r = lab6.bracket6(day(path), signal(), 1.0, "bar", slip=0.0, commission=0.0)
        self.assertAlmostEqual(r["dist"][0], (100.4 - 99.5) + 0.02)

    def test_breakeven_turns_a_loser_into_a_scratch(self):
        path = np.full(390, 100.0)
        path[5:20] = np.linspace(100.0, 100.12, 15)        # +1.2R with a 0.1 stop, target 3R not reached
        path[20:] = np.linspace(100.12, 99.0, 370)          # then slides down
        no_be = lab6.bracket6(day(path), signal(), 3.0, 0.1, slip=0.0, commission=0.0)
        with_be = lab6.bracket6(day(path), signal(), 3.0, 0.1, be=1.0, slip=0.0, commission=0.0)
        self.assertEqual((no_be["kind"][0], with_be["kind"][0]), (0, 0))
        self.assertAlmostEqual(no_be["r"][0], -1.0, places=1)
        self.assertAlmostEqual(with_be["r"][0], 0.0, places=1)


if __name__ == "__main__":
    unittest.main()
