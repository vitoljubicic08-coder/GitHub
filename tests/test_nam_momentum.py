"""Tests for NAM Momentum V1: the bar-by-bar engine mirror and the two Pine sources.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import re
import sys
import unittest
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from nam_reference_engine import TZ, NamEngine  # noqa: E402
from test_sip_orb_precision_v1 import strip_comments  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
INDICATOR = REPO / "nam_momentum_v1_indicator.pine"
STRATEGY = REPO / "nam_momentum_v1_strategy.pine"
ENGINE_RE = re.compile(r"// ==== BEGIN NAM SIGNAL ENGINE.*?// ==== END NAM SIGNAL ENGINE ====", re.S)


def weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() <= 4:
            out.append(d)
        d += timedelta(days=1)
    return out


def flat_day(eng: NamEngine, d: date, open_px: float = 100.0, drift: float = 0.001):
    """78 bars; every bar closes `drift` above the open, so sigma = drift for every bar index."""
    signals = []
    for k in range(78):
        t = datetime.combine(d, time(9, 30), tzinfo=TZ) + timedelta(minutes=5 * k)
        c = open_px * (1 + drift)
        signals.append((t, eng.update(t.astimezone(timezone.utc), open_px, c, open_px, c, 1000.0)))
    return signals


def run_day(eng: NamEngine, d: date, closes: dict[int, float], default: float = 100.0):
    """Bars with close = closes.get(bar index, default); returns {bar open 'HH:MM': signals}."""
    out = {}
    for k in range(78):
        t = datetime.combine(d, time(9, 30), tzinfo=TZ) + timedelta(minutes=5 * k)
        c = closes.get(k, default)
        o = 100.0 if k == 0 else c
        # Feed UTC like TradingView's `time`; report by New York bar open time.
        out[t.strftime("%H:%M")] = eng.update(t.astimezone(timezone.utc), o, max(o, c), min(o, c), c, 1000.0)
    return out


def warmed_engine(first_day: date) -> tuple[NamEngine, date]:
    eng = NamEngine()
    days = weekdays(first_day, 16)
    for d in days[:15]:
        flat_day(eng, d)
    return eng, days[15]


def hhmm(k: int) -> str:
    m = 570 + 5 * k
    return f"{m // 60:02d}:{m % 60:02d}"


class NamEngineTests(unittest.TestCase):

    def test_no_signal_until_14_sessions_of_history(self):
        eng = NamEngine()
        days = weekdays(date(2026, 6, 1), 15)
        for d in days[:13]:
            flat_day(eng, d)
        breakout = {k: 102.0 for k in range(1, 78)}
        out = run_day(eng, days[13], breakout)               # only 13 completed sessions
        self.assertEqual(len(eng.hist), 13)
        self.assertFalse(any(v[0] or v[1] for v in out.values()))
        # Day 14's breakout raised both the band and "yesterday's close" (102): upper is now ~102.24.
        out = run_day(eng, days[14], {k: 104.0 for k in range(1, 78)})   # 14 completed sessions
        self.assertEqual(len(eng.hist), 14)
        self.assertTrue(out["09:55"][0])

    def test_long_entry_at_first_half_hour_check(self):
        eng, d = warmed_engine(date(2026, 6, 1))
        out = run_day(eng, d, {k: 100.5 for k in range(1, 78)})   # above upper = 100.1 all day
        longs = [t for t, s in out.items() if s[0]]
        self.assertEqual(longs, ["09:55"])                       # bar ending 10:00
        self.assertEqual(out["15:50"][3], True)                  # end-of-day exit
        self.assertFalse(any(s[2] for s in out.values()))        # no other exit

    def test_short_entry_and_exit_back_inside_band(self):
        eng, d = warmed_engine(date(2026, 6, 1))
        closes = {k: 99.5 for k in range(1, 12)}                 # below lower = 99.9 until 10:25 bar
        closes.update({k: 100.0 for k in range(12, 78)})         # back inside the band
        out = run_day(eng, d, closes)
        self.assertTrue(out["09:55"][1])                         # short at 10:00 check
        self.assertFalse(out["10:25"][2])                        # still below the band at 10:30
        self.assertTrue(out["10:55"][2])                         # back inside: exit at 11:00 check
        self.assertFalse(out["15:50"][3])                        # already flat

    def test_hold_instead_of_exit_and_rebuy(self):
        eng, d = warmed_engine(date(2026, 6, 1))
        # Spike far above the band early (VWAP rises), then settle just above the band but below VWAP.
        closes = {k: 103.0 for k in range(1, 6)}
        closes.update({k: 100.5 for k in range(6, 78)})         # above upper (100.2001), below VWAP
        out = run_day(eng, d, closes)
        self.assertTrue(out["09:55"][0])
        self.assertFalse(any(s[2] for s in out.values()))        # never exits: close stays > upper
        self.assertTrue(out["15:50"][3])

    def test_checks_follow_new_york_time_across_dst(self):
        for start in (date(2026, 1, 5), date(2026, 7, 6)):
            with self.subTest(start=start):
                eng, d = warmed_engine(start)
                out = run_day(eng, d, {k: 100.5 for k in range(1, 78)})
                self.assertEqual([t for t, s in out.items() if s[0]], ["09:55"])

    def test_signals_only_at_half_hour_checks(self):
        eng, d = warmed_engine(date(2026, 6, 1))
        closes = {k: 100.0 for k in range(78)}
        closes.update({k: 100.5 for k in range(8, 78)})          # crosses after the 10:00 check
        out = run_day(eng, d, closes)
        self.assertEqual([t for t, s in out.items() if s[0]], ["10:25"])   # next check: 10:30 close

    def test_unconfirmed_bars_are_ignored(self):
        eng, d = warmed_engine(date(2026, 6, 1))
        t = datetime.combine(d, time(9, 30), tzinfo=TZ)
        self.assertEqual(eng.update(t, 100, 101, 99, 100.5, 1000, confirmed=False), (False, False, False, False))
        self.assertEqual(eng.sess_date_key, int(weekdays(date(2026, 6, 1), 15)[-1].strftime("%Y%m%d")))


class NamPineSourceTests(unittest.TestCase):

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

    def test_no_inputs_lookahead_or_offsets(self):
        for code in (self.ind, self.strat):
            self.assertNotRegex(code, r"\binput\s*[.(]")
            self.assertNotRegex(code, r"request\.security|lookahead|\boffset\s*=")
            self.assertIn("if barstate.isconfirmed and inRegular", code)

    def test_indicator_visuals_and_alerts(self):
        for pattern in (r"\bbgcolor\s*\(", r"\bbarcolor\s*\(", r"\bfill\s*\(", r"\bline\.new\b", r"\blabel\.new\b",
                        r"\bbox\.new\b", r"\btable\.new\b", r"\bplotchar\s*\("):
            self.assertNotRegex(self.ind, pattern)
        self.assertEqual(len(re.findall(r"\bplotshape\s*\(", self.ind)), 3)
        for p in re.findall(r"^\s*plot\s*\(.*$", self.ind, re.M):
            self.assertIn("display = display.data_window", p)
        titles = re.findall(r'alertcondition\([^,]+, title = "([^"]+)"', self.ind)
        self.assertEqual(titles, ["NAM LONG", "NAM SHORT", "NAM EXIT"])

    def test_strategy_properties(self):
        header = re.search(r"strategy\((.*?)\)\n", self.strat, re.S).group(1)
        for token in ("initial_capital = 10000", "commission_value = 0.005", "slippage = 2",
                      "margin_long = 100", "margin_short = 100", "process_orders_on_close = false"):
            self.assertIn(token, header)
        self.assertIn("SLIPPAGE_TICKS = 2", self.strat)

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
