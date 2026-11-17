"""End-to-end: the whole bot (feeds, engine, guard, execution, paper broker, storage) on a simulated clock."""
import csv
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import date, time
from pathlib import Path

from nb3bot.config import Config
from nb3bot.replay.simlive import build, run_day, run_simulated
from nb3bot.risk.account import PRESETS
from nb3bot.tests.helpers import breakout_session, flat_session, real_data_dir, trading_days

REF = Path(__file__).resolve().parents[1] / "validation" / "reference_nb3v2_qqq_trades.csv"


def synthetic(days=16, breakout_day=15, **kw):
    ds = trading_days(date(2025, 3, 3), days)
    ss = [flat_session(d, seed=i) for i, d in enumerate(ds[:breakout_day - 1])]
    ss.append(breakout_session(ds[breakout_day - 1], **kw))
    ss += [flat_session(d, seed=50 + i) for i, d in enumerate(ds[breakout_day:])]
    return ss


class EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.dir = tempfile.mkdtemp()

    def test_signal_trade_and_eod_exit_with_default_mnq_settings(self):
        ss = synthetic(at_minute=22, move=6.0)
        rig = build(self.cfg, ss, ss[14].key, self.dir)
        run_day(rig, ss[14].key)
        tr = rig.store.trades()
        self.assertEqual(len(tr), 1)
        self.assertEqual((tr[0]["side"], tr[0]["size"], tr[0]["exit_reason"]), ("BUY", 1, "EOD"))
        dec = rig.bot.day.decision
        self.assertTrue(dec["allowed"])
        self.assertEqual(rig.broker.positions(), [])
        self.assertEqual(rig.broker.open_orders(), [])
        self.assertEqual(rig.store.get("engine_snapshot")["last_session"], ss[14].key)

    def test_data_outage_on_signal_bar_blocks_entry(self):
        ss = synthetic(at_minute=22, move=6.0)
        for m in range(20, 25):                     # the whole signal bar's QQQ minutes never arrive
            s = ss[14]
            s.o[m] = s.h[m] = s.l[m] = s.c[m] = math.nan
        ss[14].o[25] = ss[14].c[25]                 # breakout visible from minute 25 on
        rig = build(self.cfg, ss, ss[14].key, self.dir)
        run_day(rig, ss[14].key)
        self.assertEqual(rig.store.trades(), [])
        self.assertTrue(any("NOT traded" in t for _, t in rig.alerts))
        self.assertIn(4, rig.bot.day.incomplete_bars)

    def test_kill_switch_mid_trade_flattens_and_disarms(self):
        ss = synthetic(at_minute=22, move=6.0)
        rig = build(self.cfg, ss, ss[14].key, self.dir)

        def hook(r):
            if r.bot.mgr.active is not None and r.bot.mgr.active.state == "OPEN" and not r.bot.kill.active():
                r.bot.kill.trigger("test kill")
        run_day(rig, ss[14].key, hook=hook)
        self.assertFalse(rig.bot.armed)
        self.assertEqual(rig.broker.positions(), [])
        tr = rig.store.trades()
        self.assertEqual(len(tr), 1)
        self.assertTrue(tr[0]["exit_reason"].startswith("KILL"))

    def test_crash_and_restart_mid_trade_no_duplicate(self):
        ss = synthetic(at_minute=22, move=6.0)
        rig = build(self.cfg, ss, ss[14].key, self.dir)
        run_day(rig, ss[14].key, until=time(11, 0))
        self.assertEqual(rig.bot.mgr.active.state, "OPEN")
        from nb3bot.app import Bot
        b2 = Bot(rig.bot.cfg, mode="replay", clock=rig.clock, broker=rig.broker, sig_source=rig.sig_src,
                 exec_source=rig.exe_src, store=rig.store, audit=rig.bot.audit, alerter=rig.bot.alert,
                 parity_report="", contract=rig.broker.c)
        b2.startup()                                # engine state comes from the database snapshot
        rig.bot = b2
        while rig.clock.now().hour < 21:            # rest of the day (UTC)
            b2.step()
            rig.clock.sleep(5)
        tr = rig.store.trades()
        self.assertEqual(len(tr), 1)
        self.assertEqual(len(rig.broker.tags), 1)

    def test_funded_budget_skips_when_one_contract_too_risky(self):
        cfg = replace(self.cfg, risk=replace(self.cfg.risk, phase="funded", funded_risk_per_trade=10.0))
        ss = synthetic(at_minute=22, move=6.0)
        rig = build(cfg, ss, ss[14].key, self.dir)
        run_day(rig, ss[14].key)
        self.assertEqual(rig.store.trades(), [])
        failed = [c["check"] for c in rig.bot.day.decision["checks"] if not c["ok"]]
        self.assertIn("size", failed)

    def test_loss_limit_headroom_blocks_entry(self):
        ss = synthetic(at_minute=22, move=6.0)
        rig = build(self.cfg, ss, ss[14].key, self.dir)
        rig.bot.account.realize(-1700)              # $300 above the $48,000 floor
        rig.broker.balance = rig.bot.account.s.balance
        run_day(rig, ss[14].key)
        self.assertEqual(rig.store.trades(), [])
        failed = [c["check"] for c in rig.bot.day.decision["checks"] if not c["ok"]]
        self.assertIn("loss_limit_headroom", failed)


class RealDataEndToEnd(unittest.TestCase):
    @unittest.skipUnless(real_data_dir(), "QQQ research cache not available")
    def test_full_stack_matches_backtest_trades(self):
        from nb3bot.replay.data import load_sessions
        cfg = Config()
        cfg = replace(cfg, instrument=replace(cfg.instrument, tick_size=0.01, tick_value=0.01, point_value=1.0),
                      costs=replace(cfg.costs, commission_round_turn=0.01, slippage_ticks_per_side=2, extra_stop_slippage_ticks=0),
                      risk=replace(cfg.risk, evaluation_risk_per_trade=1e9, max_contracts=100, max_daily_loss=1e12,
                                   max_weekly_loss=1e12, max_total_drawdown=1e12, safety_reserve=1),
                      account=replace(cfg.account, preset="custom", starting_balance=1e9, max_loss_limit=1e8,
                                      daily_loss_limit=None, max_contracts_firm=1000))
        ss = load_sessions(real_data_dir(), "QQQ")
        res = run_simulated(cfg, ss, 20250303, 20250314, tempfile.mkdtemp(), ratio=1.0)
        ref = {int(r["dkey"]): r for r in csv.DictReader(open(REF))}
        want = [k for k in ref if 20250303 <= k <= 20250314]
        got = {t["session"]: t for t in res["trades"]}
        self.assertEqual(sorted(got), sorted(want))
        for k in want:
            r, t = ref[k], got[k]
            self.assertEqual(t["side"] == "BUY", int(r["direction"]) > 0)
            self.assertAlmostEqual(t["fill_price"], float(r["fill"]), places=9)
            self.assertEqual(t["exit_reason"], r["reason"].replace("STOPGAP", "STOP"))
            self.assertAlmostEqual(t["r_multiple"], float(r["r_net"]), delta=0.01)   # stop rounded to whole ticks
