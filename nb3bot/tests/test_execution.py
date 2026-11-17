"""Execution manager + paper broker: normal flow and every failure path the bot must survive."""
import tempfile
import unittest
from datetime import datetime, timedelta

from nb3bot.alerts import Alerter
from nb3bot.broker.base import BrokerError, ContractInfo
from nb3bot.broker.paper import PaperBroker
from nb3bot.clock import SimClock
from nb3bot.config import Config
from nb3bot.data.base import MinuteBar
from nb3bot.execution.manager import TradeManager
from nb3bot.risk.account import PRESETS, AccountTracker
from nb3bot.risk.sizing import size_trade
from nb3bot.storage import Audit, Store
from nb3bot.timeutil import NY, UTC

C = ContractInfo("CON.F.US.MNQ.Z26", "MNQZ26", 0.25, 0.5, True)


def bar(clock_minute: datetime, o, h, l, c):
    return MinuteBar(clock_minute.astimezone(UTC), o, h, l, c, 100)


class Rig:
    def __init__(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = Config()
        self.clock = SimClock(datetime(2026, 11, 17, 10, 5, 3, tzinfo=NY))
        self.store = Store(f"{self.dir}/bot.sqlite")
        self.audit = Audit(f"{self.dir}/logs", self.store, echo=False)
        self.sent = []
        self.alerter = Alerter(self.cfg.alerts, self.audit, sender=lambda l, t: self.sent.append((l, t)))
        self.broker = PaperBroker(C, 50000, slip_ticks=1, commission_per_side=0.61, clock=self.clock)
        self.acc = AccountTracker(PRESETS["topstep_combine_50k"])
        self.mgr = self.new_manager()
        self.sizing = size_trade(20.0, 350, tick_size=0.25, tick_value=0.5, commission_rt=1.22, slip_ticks_per_side=1,
                                 extra_stop_slip_ticks=4, reward_risk=3, max_contracts=1, firm_max_contracts=50)
        self.signal = {"session": 20261117, "bar": 6, "direction": 1, "close": 600.0, "stop_distance": 0.48}

    def new_manager(self):
        return TradeManager(self.broker, self.store, self.audit, self.alerter, self.acc, self.cfg, self.clock)

    def at(self, hh, mm, ss=0):
        self.clock.set(datetime(2026, 11, 17, hh, mm, ss, tzinfo=NY))

    def minute(self, hh, mm, o, h, l, c):
        self.broker.on_minute(bar(datetime(2026, 11, 17, hh, mm, tzinfo=NY), o, h, l, c))

    def fill_entry(self, price=25000.0):
        self.mgr.submit(self.signal, self.sizing, C.id, 0.25, 0.5)
        self.at(10, 6, 3)
        self.minute(10, 5, price, price + 2, price - 2, price + 1)
        self.mgr.tick()        # WORKING -> PROTECTING
        self.mgr.tick()        # PROTECTING -> OPEN


class FlowTests(unittest.TestCase):
    def test_entry_bracket_target_and_journal(self):
        r = Rig()
        r.fill_entry()
        t = r.mgr.active
        self.assertEqual(t.state, "OPEN")
        self.assertEqual(t.fill_price, 25000.25)                    # open + 1 tick slippage
        self.assertEqual((t.stop_price, t.target_price), (25000.25 - 20, 25000.25 + 60))
        r.at(10, 30, 3)
        r.minute(10, 29, 25050, 25061, 25049, 25060)                 # target touched
        r.mgr.tick()
        self.assertIsNone(r.mgr.active)
        tr = r.store.trades()[0]
        self.assertEqual(tr["exit_reason"], "TARGET")
        self.assertAlmostEqual(tr["pnl"], 60 * 2 - 1.22)             # limit target: no slippage
        self.assertAlmostEqual(tr["r_multiple"], (60 * 2 - 1.22) / (80 * 0.5))
        self.assertEqual(r.broker.open_orders(), [])                  # stop cancelled by OCO: no orphan

    def test_duplicate_signal_cannot_enter_twice(self):
        r = Rig()
        self.assertTrue(r.mgr.submit(r.signal, r.sizing, C.id, 0.25, 0.5))
        r.mgr.active = None
        self.assertFalse(r.mgr.submit(r.signal, r.sizing, C.id, 0.25, 0.5))
        self.assertEqual(len(r.broker.tags), 1)

    def test_uncertain_ack_is_looked_up_never_resent(self):
        r = Rig()
        r.broker.fail_next = "uncertain"
        r.mgr.submit(r.signal, r.sizing, C.id, 0.25, 0.5)
        self.assertEqual(r.mgr.active.state, "UNCERTAIN")
        r.mgr.tick()
        self.assertEqual(r.mgr.active.state, "WORKING")
        self.assertEqual(len(r.broker.tags), 1)

    def test_rejection_is_recorded_and_nothing_else_sent(self):
        r = Rig()
        r.broker.fail_next = "reject"
        self.assertFalse(r.mgr.submit(r.signal, r.sizing, C.id, 0.25, 0.5))
        self.assertIsNone(r.mgr.active)
        self.assertEqual(r.store.intent_for_session(20261117)["status"], "rejected")
        self.assertTrue(any("rejected" in t for _, t in r.sent))

    def test_missing_bracket_is_replaced_by_bot(self):
        r = Rig()
        r.broker.fail_next = "no_brackets"
        r.mgr.submit(r.signal, r.sizing, C.id, 0.25, 0.5)
        r.at(10, 6, 3); r.minute(10, 5, 25000, 25002, 24998, 25001)
        r.mgr.tick(); r.mgr.tick()
        self.assertEqual(r.mgr.active.state, "PROTECTING")           # waits for the bracket first
        r.at(10, 6, 10); r.mgr.tick()
        self.assertEqual(r.mgr.active.state, "OPEN")
        types = sorted(o.type for o in r.broker.open_orders())
        self.assertEqual(types, ["limit", "stop"])
        self.assertTrue(any(l == "CRITICAL" and "stop missing" in t for l, t in r.sent))

    def test_protection_failure_closes_position(self):
        r = Rig()
        r.broker.fail_next = "no_brackets"
        r.broker.place_stop = lambda *a, **k: (_ for _ in ()).throw(BrokerError("stop refused"))
        r.mgr.submit(r.signal, r.sizing, C.id, 0.25, 0.5)
        r.at(10, 6, 3); r.minute(10, 5, 25000, 25002, 24998, 25001)
        r.mgr.tick(); r.mgr.tick()
        r.at(10, 6, 10); r.mgr.tick()
        self.assertEqual(r.broker.positions(), [])
        r.mgr.tick()
        self.assertIsNone(r.mgr.active)
        self.assertEqual(r.store.trades()[0]["exit_reason"], "PROTECTION_FAILED")

    def test_eod_flatten_at_1555_leaves_nothing(self):
        r = Rig()
        r.fill_entry()
        r.minute(15, 54, 25010, 25012, 25008, 25011)
        r.at(15, 55, 5)
        r.mgr.tick()
        r.mgr.tick()
        self.assertEqual(r.broker.positions(), [])
        self.assertEqual(r.broker.open_orders(), [])
        tr = r.store.trades()[0]
        self.assertEqual(tr["exit_reason"], "EOD")
        self.assertAlmostEqual(tr["exit_price"], 25011 - 0.25)      # last close minus slippage

    def test_restart_recovers_open_trade(self):
        r = Rig()
        r.fill_entry()
        r2 = r.new_manager()                                        # crash + restart: state from the database
        self.assertEqual(r2.active.tag, r.mgr.active.tag)
        self.assertEqual(r2.active.state, "OPEN")
        r.at(10, 40, 3); r.minute(10, 39, 25000, 25001, 24975, 24976)   # stop hit while "down"
        r2.tick()
        self.assertIsNone(r2.active)
        self.assertEqual(r.store.trades()[0]["exit_reason"], "STOP")
        self.assertEqual(len(r.broker.tags), 1)                      # no second entry

    def test_unknown_position_is_flattened_and_halts(self):
        r = Rig()
        r.broker.pos.size, r.broker.pos.avg = 2, 25000.0               # appeared outside the bot
        r.broker.last_bar = bar(datetime(2026, 11, 17, 10, 4, tzinfo=NY), 25000, 25001, 24999, 25000)
        self.assertFalse(r.mgr.reconcile([C.id]))
        self.assertEqual(r.broker.positions(), [])
        self.assertTrue(r.mgr.halt_reasons)

    def test_orphan_orders_cancelled(self):
        r = Rig()
        r.broker.place_stop(C.id, -1, 1, 24900.0, "stray")
        r.mgr.reconcile([C.id])
        self.assertEqual(r.broker.open_orders(), [])

    def test_kill_flattens_everything(self):
        r = Rig()
        r.fill_entry()
        r.mgr.emergency_flatten("test")
        self.assertEqual(r.broker.positions(), [])
        self.assertEqual(r.broker.open_orders(), [])
        r.mgr.tick()
        self.assertIsNone(r.mgr.active)

    def test_broker_outage_does_not_crash_and_keeps_state(self):
        r = Rig()
        r.fill_entry()
        r.broker.connected = False
        r.mgr.tick()
        self.assertEqual(r.mgr.active.state, "OPEN")
        self.assertIn("disconnected", r.mgr.last_broker_error)
        self.assertFalse(r.mgr.reconcile([C.id]))


class PaperBrokerTests(unittest.TestCase):
    def test_duplicate_tag_rejected(self):
        r = Rig()
        r.mgr.submit(r.signal, r.sizing, C.id, 0.25, 0.5)
        with self.assertRaises(BrokerError):
            r.broker.place_stop(C.id, -1, 1, 1.0, r.mgr.active.tag)

    def test_stop_gap_fill_at_open(self):
        r = Rig()
        r.fill_entry()
        r.at(11, 0, 3)
        r.minute(10, 59, 24950, 24955, 24940, 24945)                 # opens 50 points below entry
        r.mgr.tick()
        tr = r.store.trades()[0]
        self.assertEqual(tr["exit_reason"], "STOP")
        self.assertAlmostEqual(tr["exit_price"], 24950 - 0.25)       # worse than the stop price
        self.assertLess(tr["r_multiple"], -2.0)
