"""Calendar/DST, contracts, sizing, account loss-limit tracking and the pre-trade guard."""
import math
import unittest
from datetime import date, datetime, timedelta, timezone

from nb3bot.contracts import front_contract, projectx_contract_id, third_friday
from nb3bot.risk.account import PRESETS, AccountTracker, FirmRules
from nb3bot.risk.guard import TradeContext, edge_status, evaluate
from nb3bot.risk.sizing import convert_stop, size_trade
from nb3bot.timeutil import NY, TradingCalendar, fmt_dual, minute_index, minute_start

# NYSE's published calendar (www.nyse.com/markets/hours-calendars, read 2026-11-17)
NYSE_2026_2028 = {
    2026: ["2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
           "2026-09-07", "2026-11-26", "2026-12-25"],
    2027: ["2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
           "2027-09-06", "2027-11-25", "2027-12-24"],
    2028: ["2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04",
           "2028-11-23", "2028-12-25"],
}
EARLY = ["2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03", "2028-11-24"]


class CalendarTests(unittest.TestCase):
    def test_matches_published_nyse_holidays(self):
        cal = TradingCalendar()
        for y, days in NYSE_2026_2028.items():
            got = sorted(d.isoformat() for d in __import__("nb3bot.timeutil", fromlist=["x"]).nyse_holidays(y)
                         if d.year == y and d.isoformat() not in ("2025-01-09",))
            self.assertEqual(got, days, y)
        for d in EARLY:
            self.assertTrue(cal.is_early_close(date.fromisoformat(d)), d)
        self.assertFalse(cal.is_early_close(date(2027, 7, 2)))
        self.assertFalse(cal.is_trading_day(date(2025, 1, 9)))        # national day of mourning

    def test_dst_session_open_in_utc(self):
        self.assertEqual(minute_start(20260306, 0), datetime(2026, 3, 6, 14, 30, tzinfo=timezone.utc))  # EST
        self.assertEqual(minute_start(20260309, 0), datetime(2026, 3, 9, 13, 30, tzinfo=timezone.utc))  # EDT
        self.assertEqual(minute_index(datetime(2026, 11, 2, 9, 30, tzinfo=NY)), 0)
        self.assertIsNone(minute_index(datetime(2026, 11, 2, 16, 0, tzinfo=NY)))
        # the US switches before Europe: on 2026-03-09 Zagreb is 5 h ahead instead of 6
        self.assertIn("09:30:00 New York / 14:30:00 Zagreb", fmt_dual(minute_start(20260309, 0)))


class ContractTests(unittest.TestCase):
    def test_roll_schedule(self):
        self.assertEqual(third_friday(2026, 12), date(2026, 12, 18))
        self.assertEqual(front_contract(date(2026, 12, 9))[:2], (2026, 12))
        self.assertEqual(front_contract(date(2026, 12, 10))[:2], (2027, 3))
        self.assertEqual(projectx_contract_id("MNQ", 2026, 12), "CON.F.US.MNQ.Z26")


class SizingTests(unittest.TestCase):
    kw = dict(tick_size=0.25, tick_value=0.5, commission_rt=1.22, slip_ticks_per_side=1, extra_stop_slip_ticks=4,
              reward_risk=3.0, max_contracts=3, firm_max_contracts=50)

    def test_whole_contracts_never_rounded_up(self):
        r = size_trade(124.0, 350, **self.kw)          # 496 ticks: $248 + $1.22 + $1.00 = $250.22 per MNQ
        self.assertEqual((r.contracts, r.stop_ticks, r.target_ticks), (1, 496, 1488))
        self.assertAlmostEqual(r.risk_per_contract, 250.22)
        self.assertEqual(size_trade(124.0, 500, **self.kw).contracts, 1)     # 500/250.22 = 1.998 -> 1
        self.assertEqual(size_trade(124.0, 500.44, **self.kw).contracts, 2)

    def test_skip_when_one_contract_exceeds_budget(self):
        r = size_trade(124.0, 250, **self.kw)
        self.assertEqual(r.contracts, 0)
        self.assertIn("more than the $250 budget", r.reason)

    def test_conversion(self):
        self.assertAlmostEqual(convert_stop(3.0, "qqq_ratio", 600.0, 24800.0), 124.0)
        self.assertTrue(math.isnan(convert_stop(3.0, "qqq_ratio", 600.0, float("nan"))))


class AccountTests(unittest.TestCase):
    def test_eod_trailing_with_lock(self):
        a = AccountTracker(PRESETS["lucid_flex_50k_eval"])
        self.assertEqual(a.s.floor, 48000)
        a.realize(1500); a.mark(900)                    # intraday highs do not move an EOD floor
        self.assertEqual(a.s.floor, 48000)
        a.end_of_day()
        self.assertEqual(a.s.floor, 49500)
        a.realize(1500); a.end_of_day()
        self.assertEqual(a.s.floor, 50100)              # locked at start + $100
        a.realize(-500); a.end_of_day()
        self.assertEqual(a.s.floor, 50100)              # never moves down

    def test_intraday_trailing_uses_open_profit(self):
        a = AccountTracker(FirmRules("x", 50000, 2000, "intraday", 100.0, None, 10))
        a.mark(800)
        self.assertEqual(a.s.floor, 48800)
        a.mark(-300)
        self.assertEqual(a.remaining_allowance(), 49700 - 48800)

    def test_evaluation_pass_needs_target_and_consistency(self):
        a = AccountTracker(PRESETS["topstep_combine_50k"])
        a.realize(1800); a.end_of_day()                  # one big day
        a.realize(1300); a.end_of_day()
        self.assertFalse(a.evaluation_passed())         # 1800 > 55% of 3100
        a.realize(300); a.end_of_day()
        self.assertTrue(a.evaluation_passed())          # 1800 <= 55% of 3400
        self.assertFalse(AccountTracker(PRESETS["topstep_xfa_50k"]).evaluation_passed())

    def test_topstep_payout_moves_floor_to_zero(self):
        a = AccountTracker(PRESETS["topstep_xfa_50k"])
        a.realize(3000); a.end_of_day()
        a.payout(1500, floor_after=0.0)
        self.assertEqual((a.s.balance, a.s.floor), (1500, 0.0))


def ctx(**over):
    from nb3bot.risk.sizing import SizingResult
    now = datetime(2026, 11, 17, 15, 5, 3, tzinfo=timezone.utc)
    acc = AccountTracker(PRESETS["topstep_combine_50k"])
    base = dict(now=now, signal_bar_close=now - timedelta(seconds=3), max_signal_delay_s=45, entries_permitted=True,
                halt_reasons=[], trading_day=True, early_close=False, within_entry_window=True, data_ok=True,
                data_detail="ok", broker_ok=True, broker_detail="ok", flat_and_no_orders=True, traded_today=False,
                contract_ok=True, contract_detail="ok",
                sizing=SizingResult(1, 124, 496, 1488, 250.22, 250.22, 252.22, 350, ""), account=acc,
                max_trade_risk=350, max_daily_loss=400, max_weekly_loss=800, max_total_drawdown=1500,
                safety_reserve=500, consecutive_losses=0, halt_after_consecutive_losses=0, edge_status="ok", edge_detail="")
    base.update(over)
    return TradeContext(**base)


class GuardTests(unittest.TestCase):
    def test_all_pass(self):
        self.assertTrue(evaluate(ctx()).allowed)

    def test_each_check_can_veto(self):
        from nb3bot.risk.sizing import SizingResult
        acc = AccountTracker(PRESETS["topstep_combine_50k"])
        acc.realize(-1300)                              # $700 above the floor: worst case leaves < $500
        cases = {"armed": dict(entries_permitted=False), "no_halt": dict(halt_reasons=["x"]),
                 "trading_day": dict(trading_day=False), "not_early_close": dict(early_close=True),
                 "signal_fresh": dict(signal_bar_close=ctx().now - timedelta(seconds=90)),
                 "one_trade_per_day": dict(traded_today=True), "market_data": dict(data_ok=False),
                 "broker": dict(broker_ok=False), "flat": dict(flat_and_no_orders=False), "contract": dict(contract_ok=False),
                 "size": dict(sizing=SizingResult(0, 124, 496, 1488, 250.22, 0, 0, 250, "too big")),
                 "loss_limit_headroom": dict(account=acc), "edge_monitor": dict(edge_status="stop")}
        for name, over in cases.items():
            d = evaluate(ctx(**over))
            self.assertFalse(d.allowed, name)
            self.assertIn(name, [c[0] for c in d.checks if not c[1]], name)

    def test_edge_stop_rules(self):
        self.assertEqual(edge_status([-0.2] * 50)[0], "pause")
        self.assertEqual(edge_status([-0.05] * 100)[0], "stop")
        self.assertEqual(edge_status([0.02] * 200)[0], "stop")
        self.assertEqual(edge_status([0.25] * 200)[0], "ok")
