"""Tests for the offline broker emulator in backtest/sip_orb_backtest.py.

Each scenario uses hand-built bars whose fills, P&L and exit reasons can be
computed by hand, so the emulator's arithmetic is checked exactly.

Run:  python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "backtest"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import sip_orb_backtest as bt  # noqa: E402
from sip_orb_reference_engine import TZ, position_size  # noqa: E402

DAY = date(2026, 6, 17)       # Wednesday
NEXT_DAY = date(2026, 6, 18)
MISSING = "missing"


class FixedDaily:
    """Previous-day ATR(14) = 1.00 and 14-day volume sum = 28,000,000 for every date."""

    def previous(self, d):
        return 1.0, 28_000_000.0


def t_ny(d: date, hh: int, mm: int) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=TZ)


def session(d, opening, base, overrides=None, end=(15, 55)):
    """09:30 opening bar, then flat `base` bars (o, h, l, c) until `end`, with overrides."""
    o, h, l, c, v = opening
    bars = [(t_ny(d, 9, 30), o, h, l, c, v, True)]
    cur, last = t_ny(d, 9, 35), t_ny(d, *end)
    while cur <= last:
        ohlc = (overrides or {}).get((cur.hour, cur.minute), base)
        if ohlc != MISSING:
            bars.append((cur, *ohlc, 50_000.0, True))
        cur += timedelta(minutes=5)
    return bars


def history(before: date, n: int = 14):
    """n earlier weekdays with doji openings (never signal) at 50.00."""
    days, cur = [], before
    while len(days) < n:
        cur -= timedelta(days=1)
        if cur.weekday() <= 4:
            days.append(cur)
    bars = []
    for d in sorted(days):
        bars += session(d, (50.0, 50.5, 49.5, 50.0, 100_000.0), (50.0, 50.0, 50.0, 50.0))
    return bars


BULL_OPEN = (100.00, 100.50, 99.80, 100.30, 250_000.0)
BEAR_OPEN = (100.00, 100.10, 99.50, 99.70, 250_000.0)
BUY_BAR = (100.30, 100.65, 100.25, 100.60)    # 09:35 close 100.60 > 100.50
SELL_BAR = (99.70, 99.75, 99.35, 99.40)       # 09:35 close 99.40 < 99.50
LONG_BASE = (100.80, 100.90, 100.75, 100.80)  # stays above the 100.72 stop
SHORT_BASE = (99.20, 99.25, 99.10, 99.20)     # stays below the 99.28 stop


def run(bars):
    trades, equity, open_count = bt.simulate_symbol("TEST", bars, FixedDaily())
    return trades, equity, open_count


class BrokerEmulatorTests(unittest.TestCase):

    def long_day(self, overrides=None, end=(15, 55)):
        ov = {(9, 35): BUY_BAR}
        ov.update(overrides or {})
        return history(DAY) + session(DAY, BULL_OPEN, LONG_BASE, ov, end)

    def test_long_exits_at_1555_open(self):
        trades, equity, open_count = run(self.long_day({(15, 55): (101.50, 101.60, 101.40, 101.50)}))
        self.assertEqual((len(trades), open_count), (1, 0))
        tr = trades[0]
        qty = position_size(10_000, 1.0, 100.60, 0.01)            # min(250, floor(10000/100.62)) = 99
        self.assertEqual((tr.side, tr.qty, tr.exit_reason), ("LONG", qty, "EOD 15:55"))
        self.assertEqual(qty, 99)
        self.assertEqual(tr.signal_bar_time, t_ny(DAY, 9, 35).isoformat())  # arrow's bar
        self.assertEqual(tr.entry_time, t_ny(DAY, 9, 40).isoformat())    # next bar's open
        self.assertEqual(tr.exit_time, t_ny(DAY, 15, 55).isoformat())
        self.assertAlmostEqual(tr.entry_price, 100.82)            # 100.80 + 2 ticks
        self.assertAlmostEqual(tr.stop_price, 100.72)             # fill - 0.10 x ATR
        self.assertAlmostEqual(tr.exit_price, 101.48)             # 101.50 - 2 ticks
        self.assertAlmostEqual(tr.commission, 0.99)               # 99 x 0.005 x 2
        self.assertAlmostEqual(tr.net_pnl, (101.48 - 100.82) * 99 - 0.99, places=6)
        self.assertAlmostEqual(tr.r_multiple, tr.net_pnl / (99 * 0.1), places=9)
        self.assertAlmostEqual(equity, 10_000 + tr.net_pnl, places=6)

    def test_long_stop_inside_bar(self):
        trades, *_ = run(self.long_day({(10, 30): (100.80, 100.85, 100.50, 100.60)}))
        tr = trades[0]
        self.assertEqual(tr.exit_reason, "Stop")
        self.assertEqual(tr.exit_time, t_ny(DAY, 10, 30).isoformat())
        self.assertAlmostEqual(tr.exit_price, 100.70)             # 100.72 - 2 ticks
        self.assertAlmostEqual(tr.net_pnl, (100.70 - 100.82) * 99 - 0.99, places=6)
        self.assertAlmostEqual(tr.r_multiple, -1.3, places=6)     # slippage + commission beyond -1R

    def test_long_gap_through_stop_fills_at_open(self):
        trades, *_ = run(self.long_day({(10, 30): (100.40, 100.45, 100.30, 100.35)}))
        tr = trades[0]
        self.assertEqual(tr.exit_reason, "Stop (gap)")
        self.assertAlmostEqual(tr.exit_price, 100.38)             # open 100.40 - 2 ticks

    def test_stop_can_fill_on_the_entry_bar(self):
        trades, *_ = run(self.long_day({(9, 40): (100.80, 100.85, 100.60, 100.65)}))
        tr = trades[0]
        self.assertEqual((tr.exit_reason, tr.entry_time, tr.exit_time),
                         ("Stop", t_ny(DAY, 9, 40).isoformat(), t_ny(DAY, 9, 40).isoformat()))

    def test_short_mirror_image(self):
        bars = history(DAY) + session(DAY, BEAR_OPEN, SHORT_BASE,
                                      {(9, 35): SELL_BAR, (15, 55): (98.50, 98.60, 98.40, 98.50)})
        trades, *_ = run(bars)
        tr = trades[0]
        self.assertEqual((tr.side, tr.qty, tr.exit_reason), ("SHORT", 100, "EOD 15:55"))  # floor(10000/99.42)
        self.assertAlmostEqual(tr.entry_price, 99.18)             # sold 2 ticks below the open
        self.assertAlmostEqual(tr.stop_price, 99.28)
        self.assertAlmostEqual(tr.exit_price, 98.52)              # bought back 2 ticks above
        self.assertAlmostEqual(tr.net_pnl, (99.18 - 98.52) * 100 - 1.0, places=6)

    def test_short_stop(self):
        bars = history(DAY) + session(DAY, BEAR_OPEN, SHORT_BASE,
                                      {(9, 35): SELL_BAR, (11, 0): (99.20, 99.40, 99.15, 99.35)})
        tr = run(bars)[0][0]
        self.assertEqual(tr.exit_reason, "Stop")
        self.assertAlmostEqual(tr.exit_price, 99.30)              # 99.28 + 2 ticks

    def test_missing_1550_bar_uses_failsafe_at_1555_close(self):
        trades, *_ = run(self.long_day({(15, 50): MISSING, (15, 55): (101.0, 101.1, 100.9, 101.0)}))
        tr = trades[0]
        self.assertEqual(tr.exit_reason, "EOD failsafe")
        self.assertEqual(tr.exit_time, t_ny(DAY, 16, 0).isoformat())
        self.assertAlmostEqual(tr.exit_price, 100.98)

    def test_early_close_day_flattens_on_last_regular_bar(self):
        trades, _, open_count = run(self.long_day(end=(12, 55)))
        tr = trades[0]
        self.assertEqual((tr.exit_reason, open_count), ("EOD failsafe", 0))
        self.assertEqual(tr.exit_time, t_ny(DAY, 13, 0).isoformat())
        self.assertAlmostEqual(tr.exit_price, 100.78)

    def test_equity_compounds_into_next_trade_size(self):
        bars = self.long_day({(15, 55): (101.50, 101.60, 101.40, 101.50)})
        bars += session(NEXT_DAY, BULL_OPEN, LONG_BASE, {(9, 35): BUY_BAR})
        trades, *_ = run(bars)
        self.assertEqual(len(trades), 2)
        first, second = trades
        self.assertAlmostEqual(second.equity_before, 10_000 + first.net_pnl, places=2)
        self.assertEqual(second.qty, position_size(10_000 + first.net_pnl, 1.0, 100.60, 0.01))

    def test_no_trade_without_signal(self):
        bars = history(DAY) + session(DAY, BULL_OPEN, (100.30, 100.45, 100.20, 100.40))
        self.assertEqual(run(bars)[0], [])


class DailyReferenceTests(unittest.TestCase):

    def test_atr_and_volume_use_previous_completed_day(self):
        start = date(2026, 1, 1)
        rows = [(start + timedelta(days=i), 10.0, 11.0, 9.0, 10.0, 1_000_000.0 + i) for i in range(20)]
        ref = bt.DailyReference(rows)
        self.assertEqual(ref.previous(rows[13][0]), (None, None))     # only 13 completed days
        atr, vol_sum = ref.previous(rows[14][0])                      # 14 completed days
        self.assertAlmostEqual(atr, 2.0)
        self.assertEqual(vol_sum, sum(1_000_000.0 + i for i in range(14)))
        self.assertEqual(ref.previous(rows[0][0]), (None, None))

    def test_atr_is_wilder_rma_seeded_with_sma(self):
        start = date(2026, 1, 1)
        ranges = [1.0] * 14 + [3.0]
        rows = [(start + timedelta(days=i), 10.0, 10.0 + r / 2, 10.0 - r / 2, 10.0, 1e6)
                for i, r in enumerate(ranges)]
        rows.append((start + timedelta(days=15), 10.0, 10.5, 9.5, 10.0, 1e6))
        ref = bt.DailyReference(rows)
        atr, _ = ref.previous(rows[-1][0])
        self.assertAlmostEqual(atr, (1.0 * 13 + 3.0) / 14)


class EndToEndTests(unittest.TestCase):

    def test_csv_round_trip_and_summary(self):
        bars = history(DAY) + session(DAY, BULL_OPEN, LONG_BASE,
                                      {(9, 35): BUY_BAR, (15, 55): (101.50, 101.60, 101.40, 101.50)})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "intraday").mkdir()
            (root / "daily").mkdir()
            with (root / "intraday" / "TEST.csv").open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["time", "open", "high", "low", "close", "volume"])
                for t, o, h, l, c, v, _m in bars:
                    w.writerow([t.isoformat(), o, h, l, c, v])
            with (root / "daily" / "TEST.csv").open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["date", "open", "high", "low", "close", "volume"])
                d = DAY - timedelta(days=60)
                while d < DAY:      # constant 1.00 true range, 2M shares a day
                    w.writerow([d.isoformat(), 100.0, 100.5, 99.5, 100.0, 2_000_000])
                    d += timedelta(days=1)
            out = root / "out"
            self.assertEqual(bt.main(["--data", str(root), "--out", str(out), "--min-trades", "1"]), 0)
            summary = json.loads((out / "summary.json").read_text())
            with (out / "trades.csv").open() as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(summary["trades"], 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exit_reason"], "EOD 15:55")
        self.assertAlmostEqual(float(rows[0]["net_pnl"]), (101.48 - 100.82) * 99 - 0.99, places=3)


if __name__ == "__main__":
    unittest.main()
