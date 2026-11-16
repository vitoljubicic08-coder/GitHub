"""Tests for NB3 Breakout V1: the bar-by-bar engine mirror and the two Pine sources.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nb3_reference_engine import TZ, Nb3Engine  # noqa: E402
from test_sip_orb_precision_v1 import strip_comments  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
INDICATOR = REPO / "nb3_breakout_v1_indicator.pine"
STRATEGY = REPO / "nb3_breakout_v1_strategy.pine"
ENGINE_RE = re.compile(r"// ==== BEGIN NB3 SIGNAL ENGINE.*?// ==== END NB3 SIGNAL ENGINE ====", re.S)
ATR = 5.0


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() <= 4:
            out.append(d)
        d += timedelta(days=1)
    return out


def run_day(eng: Nb3Engine, d: date, closes: dict[int, float], default: float = 100.1, atr: float = ATR):
    """Bars open 100 at 09:30; close = closes.get(k, default). Returns {NY bar open 'HH:MM': (buy, sell)}."""
    out = {}
    for k in range(78):
        t = datetime.combine(d, time(9, 30), tzinfo=TZ) + timedelta(minutes=5 * k)
        c = closes.get(k, default)
        o = 100.0 if k == 0 else c
        out[t.strftime("%H:%M")] = eng.update(t.astimezone(timezone.utc), o, max(o, c), min(o, c), c, atr)
    return out


def warmed(start: date) -> tuple[Nb3Engine, date]:
    """15 quiet days (every bar closes at 100.1, so sigma = 0.001 and the band is 100 +/- 0.15)."""
    eng = Nb3Engine()
    days = weekdays(start, 16)
    for d in days[:15]:
        run_day(eng, d, {})
    return eng, days[15]


def fired(out: dict, side: int) -> list[str]:
    return [t for t, s in out.items() if s[side]]


class Nb3EngineTests(unittest.TestCase):

    def test_needs_14_sessions_of_history(self):
        eng = Nb3Engine()
        days = weekdays(date(2026, 6, 1), 15)
        for d in days[:13]:
            run_day(eng, d, {})
        out = run_day(eng, days[13], {k: 101.0 for k in range(78)})
        self.assertEqual(fired(out, 0) + fired(out, 1), [])          # 13 sessions: nothing
        out = run_day(eng, days[14], {k: 103.0 for k in range(78)})
        self.assertEqual(fired(out, 0), ["09:30"])                    # 14 sessions: first bar fires

    def test_buy_when_close_beyond_band_once_per_day(self):
        eng, d = warmed(date(2026, 6, 1))
        closes = {k: 100.1 for k in range(78)}
        closes.update({10: 100.2, 11: 100.3, 20: 99.0})              # band upper = 100.15
        out = run_day(eng, d, closes)
        self.assertEqual(fired(out, 0), ["10:20"])
        self.assertEqual(fired(out, 1), [])                           # later sell ignored: one per day
        self.assertAlmostEqual(eng.stop_dist, 0.20 * ATR)

    def test_sell_signal(self):
        eng, d = warmed(date(2026, 6, 1))
        out = run_day(eng, d, {5: 99.8})
        self.assertEqual((fired(out, 0), fired(out, 1)), ([], ["09:55"]))

    def test_no_signal_after_1450(self):
        eng, d = warmed(date(2026, 6, 1))
        self.assertEqual(fired(run_day(eng, d, {65: 101.0, 70: 101.0}), 0), [])     # 14:55 and later
        eng, d = warmed(date(2026, 6, 1))
        self.assertEqual(fired(run_day(eng, d, {64: 101.0}), 0), ["14:50"])

    def test_no_signal_without_atr(self):
        eng, d = warmed(date(2026, 6, 1))
        out = run_day(eng, d, {10: 101.0}, atr=float("nan"))
        self.assertEqual(fired(out, 0), [])

    def test_new_york_time_across_dst(self):
        for start in (date(2026, 1, 5), date(2026, 7, 6)):
            with self.subTest(start=start):
                eng, d = warmed(start)
                self.assertEqual(fired(run_day(eng, d, {6: 101.0}), 0), ["10:00"])


class Nb3PineSourceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.ind_src = INDICATOR.read_text(encoding="utf-8")
        cls.str_src = STRATEGY.read_text(encoding="utf-8")
        cls.ind = strip_comments(cls.ind_src)
        cls.strat = strip_comments(cls.str_src)

    def test_version_and_engine_identical(self):
        for src in (self.ind_src, self.str_src):
            self.assertTrue(src.startswith("//@version=6\n"))
        a, b = ENGINE_RE.findall(self.ind_src), ENGINE_RE.findall(self.str_src)
        self.assertEqual((len(a), len(b)), (1, 1))
        self.assertEqual(a[0], b[0])

    def test_no_inputs_and_safe_daily_request(self):
        for code in (self.ind, self.strat):
            self.assertNotRegex(code, r"\binput\s*[.(]|\boffset\s*=")
            calls = re.findall(r"request\.security\(.*\)", code)
            self.assertEqual(len(calls), 1)
            self.assertIn("ta.atr(LOOKBACK)[1]", calls[0])
            self.assertIn("lookahead = barmerge.lookahead_on", calls[0])
            self.assertIn("if barstate.isconfirmed and inRegular", code)

    def test_only_two_arrows_and_alerts(self):
        self.assertEqual(len(re.findall(r"\bplotshape\s*\(", self.ind)), 2)
        for pattern in (r"\bbgcolor\s*\(", r"\bbarcolor\s*\(", r"\bline\.new\b", r"\blabel\.new\b", r"\bbox\.new\b",
                        r"\btable\.new\b", r"\bfill\s*\(", r"\bplotchar\s*\("):
            self.assertNotRegex(self.ind, pattern)
        for p in re.findall(r"^\s*plot\s*\(.*$", self.ind, re.M):
            self.assertIn("display = display.data_window", p)
        self.assertEqual(re.findall(r'alertcondition\([^,]+, title = "([^"]+)"', self.ind), ["NB3 BUY", "NB3 SELL"])
        self.assertIn("alert.freq_once_per_bar_close", self.ind)
        buy = re.search(r"plotshape\(buySignal.*\)", self.ind).group(0)
        sell = re.search(r"plotshape\(sellSignal.*\)", self.ind).group(0)
        self.assertIn("shape.arrowup", buy)
        self.assertIn("color.rgb(0, 200, 0)", buy)
        self.assertIn("shape.arrowdown", sell)
        self.assertIn("color.rgb(220, 0, 0)", sell)

    def test_strategy_bracket_and_properties(self):
        header = re.search(r"strategy\((.*?)\)\n", self.strat, re.S).group(1)
        for token in ("initial_capital = 10000", "commission_value = 0.005", "slippage = 2", "margin_long = 100"):
            self.assertIn(token, header)
        exits = re.findall(r"strategy\.exit\(.*\)", self.strat)
        self.assertEqual(len(exits), 2)
        for e in exits:
            self.assertIn("loss = stopTicks", e)
            self.assertIn("profit = targetTicks", e)
        for token in ("STOP_ATR        = 0.20", "REWARD_RISK     = 3.0", "BAND_MULT       = 1.5"):
            self.assertIn(token, self.strat)

    def test_block_indentation_and_brackets(self):
        for name, code in (("indicator", self.ind), ("strategy", self.strat)):
            depth = 0
            for n, line in enumerate(code.splitlines(), 1):
                self.assertNotIn("\t", line)
                if not line.strip():
                    continue
                indent = len(line) - len(line.lstrip(" "))
                if depth == 0:
                    self.assertEqual(indent % 4, 0, f"{name}:{n}")
                else:
                    self.assertNotEqual(indent % 4, 0, f"{name}:{n}")
                no_str = re.sub(r"\"[^\"]*\"", "\"\"", line)
                depth += no_str.count("(") + no_str.count("[") - no_str.count(")") - no_str.count("]")
            self.assertEqual(depth, 0, name)


if __name__ == "__main__":
    unittest.main()
