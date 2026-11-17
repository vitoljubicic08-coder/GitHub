"""Lucid "steady" profile: optional second trade, research parity, payout advice, scaling plan, safety."""
import csv
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from nb3bot.config import load
from nb3bot.replay.data import load_sessions
from nb3bot.replay.runner import replay_backtest
from nb3bot.replay.simlive import build, run_day
from nb3bot.risk.account import PRESETS, AccountTracker
from nb3bot.risk.payout import PAYOUT_PRESETS, advice
from nb3bot.strategy.nb3v2 import NB3V2Params
from nb3bot.tests.test_app import synthetic

HERE = Path(__file__).resolve().parents[1]
PROFILE = HERE / "profiles" / "lucid_flex_50k_steady.toml"
REFERENCE = HERE / "validation" / "reference_lucid_steady_qqq_trades.csv"
STEADY = NB3V2Params(reward_risk=1.5, max_trades_per_day=2)


class SecondTradeTests(unittest.TestCase):
    def test_second_trade_only_after_the_first_closes(self):
        ss = synthetic(at_minute=22, move=6.0, then=0.02)        # keeps rising: target, then a new signal
        key = ss[14].key
        one = [t for t in replay_backtest(ss, NB3V2Params(reward_risk=1.5))[0] if t.dkey == key]
        two = [t for t in replay_backtest(ss, STEADY)[0] if t.dkey == key]
        self.assertEqual(len(one), 1)
        self.assertEqual(len(two), 2)
        first, second = two
        self.assertEqual(first.reason, "TARGET")
        self.assertGreater(second.entry_min, first.exit_min)
        self.assertGreater((second.signal_bar + 1) * 5, first.exit_min)

    def test_default_parameters_are_nb3_v2(self):
        p = NB3V2Params()
        self.assertEqual((p.reward_risk, p.max_trades_per_day, p.stop_atr, p.band_mult), (3.0, 1, 0.30, 1.0))

    @unittest.skipUnless(os.environ.get("NB3_QQQ_DATA"), "set NB3_QQQ_DATA to the research cache")
    def test_matches_research_trade_for_trade(self):
        with open(REFERENCE) as fh:
            ref = [(int(r["dkey"]), int(r["exit_min"]), int(r["signal_bar"]), int(r["direction"]), float(r["r_net"]))
                   for r in csv.DictReader(fh)]
        trades, _ = replay_backtest(load_sessions(os.environ["NB3_QQQ_DATA"], "QQQ"), STEADY, end_key=20260331)
        got = sorted((t.dkey, t.exit_min, t.signal_bar, t.direction, t.r_net) for t in trades)
        self.assertEqual(len(got), len(ref))
        for a, b in zip(got, sorted(ref)):
            self.assertEqual(a[:4], b[:4])
            self.assertAlmostEqual(a[4], b[4], places=8)


class LiveStackTests(unittest.TestCase):
    def test_two_trades_in_one_session_through_the_full_bot(self):
        cfg = load(PROFILE)
        cfg = replace(cfg, data=replace(cfg.data, qqq_provider="replay", mnq_provider="replay", allow_empty_minutes=False),
                      risk=replace(cfg.risk, max_contracts=1))
        ss = synthetic(at_minute=22, move=6.0, then=0.02)
        rig = build(cfg, ss, ss[14].key, tempfile.mkdtemp())
        run_day(rig, ss[14].key)
        tr = sorted(rig.store.trades(), key=lambda t: t["session"])
        self.assertEqual(len(tr), 2)
        self.assertEqual([t["session"] for t in tr], [ss[14].key, ss[14].key * 10 + 1])
        self.assertEqual(tr[0]["exit_reason"], "TARGET")
        self.assertEqual(rig.broker.positions(), [])
        self.assertEqual(rig.broker.open_orders(), [])
        rig.store.close()


class DailyLimitTests(unittest.TestCase):
    def rig(self, **risk):
        cfg = load(PROFILE)
        cfg = replace(cfg, data=replace(cfg.data, qqq_provider="replay", mnq_provider="replay", allow_empty_minutes=False),
                      risk=replace(cfg.risk, max_contracts=1, **risk))
        ss = synthetic(at_minute=22, move=6.0, then=0.02)
        return build(cfg, ss, ss[14].key, tempfile.mkdtemp()), ss[14].key

    def test_open_trade_is_closed_at_the_daily_loss_limit_and_the_day_locks(self):
        rig, key = self.rig()
        hit = []

        def big_loss(r):                                 # simulate an earlier -$900 today while the trade is open
            t = r.bot.mgr.active
            if t is not None and t.state == "OPEN" and not hit:
                r.bot.account.s.day_start_balance += 900.0
                hit.append(1)
        run_day(rig, key, hook=big_loss)
        tr = rig.store.trades()
        self.assertEqual(len(tr), 1)
        self.assertEqual(tr[0]["exit_reason"], "DAILY_LOSS_LIMIT")
        self.assertIn("daily loss limit", rig.bot.day.locked)
        self.assertEqual(rig.broker.positions(), [])
        rig.store.close()

    def test_daily_profit_cap_stops_new_entries(self):
        rig, key = self.rig(max_daily_profit=5.0)
        run_day(rig, key)
        tr = rig.store.trades()
        self.assertEqual(len(tr), 1)                     # the second signal is not traded
        self.assertIn("daily profit cap", rig.bot.day.locked)
        failed = [c["check"] for c in rig.bot.day.decision["checks"] if not c["ok"]]
        self.assertIn("day_lockout", failed)
        rig.store.close()

    def test_consistency_cap_is_lucid_40_percent_of_target_in_evaluation_only(self):
        rig, _ = self.rig()
        self.assertEqual(rig.bot.consistency_cap(), 1200.0)
        rig.bot.cfg = replace(rig.bot.cfg, risk=replace(rig.bot.cfg.risk, phase="funded"))
        self.assertIsNone(rig.bot.consistency_cap())
        rig.store.close()


class NearLimitTests(unittest.TestCase):
    def test_lucid_profile_keeps_trading_near_the_limit_default_halts(self):
        from nb3bot.risk.guard import evaluate
        from nb3bot.tests.test_time_risk import ctx
        acc = AccountTracker(PRESETS["topstep_combine_50k"])
        acc.realize(-1800)                               # $200 above the floor, worst case ~$252
        halted = evaluate(ctx(account=acc))
        self.assertIn("loss_limit_headroom", [n for n, ok, _ in halted.checks if not ok])
        relaxed = evaluate(ctx(account=acc, halt_near_limit=False, max_total_drawdown=5000, max_daily_loss=5000))
        self.assertNotIn("loss_limit_headroom", [n for n, ok, _ in relaxed.checks if not ok])
        self.assertFalse(load(PROFILE).risk.halt_near_limit)
        self.assertTrue(load(HERE / "profiles" / "tradingview_50k_demo.toml").risk.halt_near_limit)


class AccountRuleTests(unittest.TestCase):
    def test_funded_scaling_plan(self):
        acc = AccountTracker(PRESETS["lucid_flex_50k_funded"])
        for profit, cap in ((0, 20), (999, 20), (1000, 30), (1999, 30), (2000, 40), (5000, 40)):
            acc.s.day_start_balance = 50000 + profit
            self.assertEqual(acc.max_contracts_now(), cap)
        self.assertEqual(AccountTracker(PRESETS["lucid_flex_50k_eval"]).max_contracts_now(), 40)

    def test_payout_advice_keeps_500_above_the_locked_limit(self):
        rules = PAYOUT_PRESETS["lucid_flex_50k"]
        acc = AccountTracker(PRESETS["lucid_flex_50k_funded"])
        for _ in range(5):
            acc.realize(300.0)
            acc.end_of_day(win_day=rules.win_day)
        a = advice(acc, rules, 500.0)                 # profit 1,500: 50% = 750; 51,500 - 50,100 - 500 = 900
        self.assertTrue(a["eligible"])
        self.assertEqual(a["recommended"], 750.0)
        acc.payout(750.0, rules.floor_after)
        self.assertEqual((acc.s.cycle_win_days, acc.s.payouts, acc.s.floor), (0, 1, 50100.0))
        self.assertFalse(advice(acc, rules, 500.0)["eligible"])

    def test_no_payout_below_the_minimum(self):
        rules = PAYOUT_PRESETS["lucid_flex_50k"]
        acc = AccountTracker(PRESETS["lucid_flex_50k_funded"])
        for _ in range(5):
            acc.realize(200.0)
            acc.end_of_day(win_day=rules.win_day)
        a = advice(acc, rules, 500.0)                 # profit 1,000: min(500, 400) = 400 < 500
        self.assertFalse(a["eligible"])


class SafetyTests(unittest.TestCase):
    def test_profile_is_simulation_only(self):
        from nb3bot.__main__ import safety_report
        cfg = load(PROFILE)
        safe, _ = safety_report(cfg)
        self.assertTrue(safe)
        self.assertEqual((cfg.bot.mode, cfg.broker.name, cfg.data.mnq_provider), ("paper", "paper", "synthetic"))
        self.assertFalse(cfg.authorization.live_orders_enabled or cfg.authorization.practice_orders_enabled)
        self.assertEqual((cfg.strategy.reward_risk, cfg.strategy.max_trades_per_day), (1.5, 2))


if __name__ == "__main__":
    unittest.main()
