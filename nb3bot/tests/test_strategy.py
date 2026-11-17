"""NB3 V2 engine: exact reproduction of the verified backtest, plus rule-level checks on synthetic data."""
import math
import unittest
from datetime import date
from pathlib import Path

import numpy as np

from nb3bot.replay.parity import compare, read_reference
from nb3bot.replay.runner import replay_backtest
from nb3bot.strategy.bracket import BracketSim
from nb3bot.strategy.nb3v2 import NB3V2Engine, NB3V2Params
from nb3bot.tests.helpers import breakout_session, flat_session, real_data_dir, trading_days

REF = Path(__file__).resolve().parents[1] / "validation" / "reference_nb3v2_qqq_trades.csv"


def feed(eng, s):
    eng.begin_session(s.key)
    sigs = []
    for m, o, h, l, c, _ in s.minutes():
        eng.on_minute(m, o, h, l, c)
        if m % 5 == 4:
            x = eng.complete_bar(m // 5)
            if x:
                sigs.append(x)
    eng.end_session()
    return sigs


class ParityTests(unittest.TestCase):
    @unittest.skipUnless(real_data_dir(), "QQQ 1-minute research cache not available (set NB3_QQQ_DATA)")
    def test_reproduces_all_675_verified_trades_exactly(self):
        from nb3bot.replay.data import load_sessions
        trades, _ = replay_backtest(load_sessions(real_data_dir(), "QQQ"), end_key=20260331)
        res = compare(read_reference(REF), trades)
        self.assertEqual(res.reference_trades, 675)
        self.assertEqual(res.discrepancies, [])
        self.assertTrue(res.passed)
        self.assertEqual(max(res.max_abs_diff.values()), 0.0)

    def test_reference_file_is_the_675_trade_list(self):
        ref = read_reference(REF)
        self.assertEqual(len(ref), 675)
        r = [float(x["r_net"]) for x in ref.values()]
        self.assertAlmostEqual(sum(r) / len(r), 0.195, delta=0.001)


class EngineRuleTests(unittest.TestCase):
    def setUp(self):
        self.days = trading_days(date(2025, 3, 3), 16)
        self.eng = NB3V2Engine()
        for i, d in enumerate(self.days[:14]):
            self.assertEqual(feed(self.eng, flat_session(d, seed=i)), [])   # no signal without 14 sessions of history

    def test_buy_signal_on_breakout_with_next_bar_entry(self):
        sigs = feed(self.eng, breakout_session(self.days[14], at_minute=22, move=6.0))
        self.assertEqual(len(sigs), 1)
        s = sigs[0]
        self.assertEqual((s.direction, s.bar, s.entry_minute), (1, 4, 25))
        self.assertGreater(s.close, s.upper)
        self.assertAlmostEqual(s.stop_distance, 0.30 * s.atr_prev)

    def test_sell_signal_and_first_signal_only(self):
        sigs = feed(self.eng, breakout_session(self.days[14], at_minute=40, move=6.0, direction=-1, then=0.05))
        self.assertEqual(len(sigs), 1)
        self.assertEqual(sigs[0].direction, -1)

    def test_no_signal_after_last_entry_bar(self):
        sigs = feed(self.eng, breakout_session(self.days[14], at_minute=331, move=6.0))
        self.assertEqual(sigs, [])            # 14:51 is after the last signal bar (opens 14:50)

    def test_incomplete_candle_cannot_be_used(self):
        s = breakout_session(self.days[14], at_minute=22, move=6.0)
        self.eng.begin_session(s.key)
        for m in range(20):
            self.eng.on_minute(m, s.o[m], s.h[m], s.l[m], s.c[m])
        for b in range(4):
            self.eng.complete_bar(b)
        with self.assertRaises(ValueError):    # a minute of an already completed bar is refused
            self.eng.on_minute(19, s.o[19], s.h[19], s.l[19], s.c[19])
        with self.assertRaises(ValueError):    # bars must be completed in order
            self.eng.complete_bar(6)

    def test_snapshot_restore_gives_identical_signals(self):
        snap = self.eng.snapshot()
        a = feed(self.eng, breakout_session(self.days[14], at_minute=22, move=6.0))
        b = feed(NB3V2Engine.restore(snap), breakout_session(self.days[14], at_minute=22, move=6.0))
        self.assertEqual([x.to_dict() for x in a], [x.to_dict() for x in b])

    def test_missing_open_minute_means_no_signal(self):
        s = breakout_session(self.days[14], at_minute=22, move=6.0)
        s.o[0] = s.h[0] = s.l[0] = s.c[0] = math.nan
        self.assertEqual(feed(self.eng, s), [])


class BracketTests(unittest.TestCase):
    def test_stop_first_when_both_touched(self):
        b = BracketSim(1, 100.0, 10, 1.0, 3.0, slip=0.0)
        r = b.on_minute(11, 100.0, 104.0, 98.5)
        self.assertEqual(r.reason, "STOP")

    def test_target_not_in_entry_minute(self):
        b = BracketSim(1, 100.0, 10, 1.0, 3.0, slip=0.0)
        self.assertIsNone(b.on_minute(10, 100.0, 104.0, 99.5))
        self.assertEqual(b.on_minute(11, 103.5, 104.0, 103.0).reason, "TARGET")

    def test_gap_through_stop_fills_at_open_with_slippage(self):
        b = BracketSim(1, 100.0, 10, 1.0, 3.0, slip=0.02)
        r = b.on_minute(12, 98.0, 98.2, 97.5)
        self.assertEqual((r.reason, r.raw_exit, round(r.exit_price, 2)), ("STOPGAP", 98.0, 97.98))
        net, _ = b.r_multiple()
        self.assertLess(net, -2.0)                   # the stop does not guarantee its price
