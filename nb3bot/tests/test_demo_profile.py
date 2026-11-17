"""tradingview_50k_demo: Alpaca data adapter, simulated MNQ prices, single-exchange (IEX) gaps, safety."""
import math
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nb3bot.config import load, validate
from nb3bot.data.base import MinuteBar
from nb3bot.data.providers import AlpacaMinutes, ProviderError, SyntheticFutures
from nb3bot.replay.simlive import build, run_day
from nb3bot.tests.test_app import synthetic
from nb3bot.timeutil import minute_start

PROFILE = Path(__file__).resolve().parents[1] / "profiles" / "tradingview_50k_demo.toml"


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b, self.text = code, body, str(body)

    def json(self):
        return self._b


class FakeAlpaca:
    """Answers GET /v2/stocks/QQQ/bars like the documented API (two pages), records the feed asked for."""

    def __init__(self, deny_sip=False):
        self.calls, self.deny_sip = [], deny_sip

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params), dict(headers)))
        if params["feed"] == "sip" and self.deny_sip:
            return Resp(403, {"message": "subscription does not permit querying recent SIP data"})
        t0 = minute_start(20261116, 0)
        if "page_token" not in params:
            return Resp(200, {"bars": [{"t": t0.isoformat().replace("+00:00", "Z"), "o": 600, "h": 601, "l": 599.5, "c": 600.5, "v": 10}],
                              "symbol": "QQQ", "next_page_token": "p2"})
        t1 = t0 + timedelta(minutes=1)
        return Resp(200, {"bars": [{"t": t1.isoformat().replace("+00:00", "Z"), "o": 600.5, "h": 601, "l": 600, "c": 600.8, "v": 7}],
                          "symbol": "QQQ", "next_page_token": None})


class Clock:
    def __init__(self, t):
        self.t = t

    def now(self):
        return self.t


class AlpacaTests(unittest.TestCase):
    def setUp(self):
        import os
        os.environ["NB3_TEST_ALPACA_ID"], os.environ["NB3_TEST_ALPACA_SECRET"] = "id", "secret"

    def src(self, http, now):
        return AlpacaMinutes("QQQ", "https://data.example", "NB3_TEST_ALPACA_ID", "NB3_TEST_ALPACA_SECRET",
                             session=http, clock=Clock(now))

    def test_history_uses_sip_paging_and_headers(self):
        http = FakeAlpaca()
        bars = self.src(http, minute_start(20261117, 0)).fetch(minute_start(20261116, 0), minute_start(20261116, 390))
        self.assertEqual([b.c for b in bars], [600.5, 600.8])
        url, params, headers = http.calls[0]
        self.assertTrue(url.endswith("/v2/stocks/QQQ/bars"))
        self.assertEqual((params["feed"], params["timeframe"]), ("sip", "1Min"))
        self.assertEqual(headers, {"APCA-API-KEY-ID": "id", "APCA-API-SECRET-KEY": "secret"})
        self.assertEqual(http.calls[1][1]["page_token"], "p2")
        self.assertEqual(bars[0].ts, minute_start(20261116, 0))          # bar time = minute start

    def test_recent_data_uses_live_iex_feed(self):
        http = FakeAlpaca()
        now = minute_start(20261116, 3)
        self.src(http, now).fetch(minute_start(20261116, 0), now)
        self.assertEqual(http.calls[0][1]["feed"], "iex")

    def test_sip_refused_falls_back_to_iex_and_says_so(self):
        http = FakeAlpaca(deny_sip=True)
        s = self.src(http, minute_start(20261117, 0))
        bars = s.fetch(minute_start(20261116, 0), minute_start(20261116, 390))
        self.assertEqual(len(bars), 2)
        self.assertEqual(s.history_feed, "iex")
        self.assertTrue(s.notes)

    def test_missing_keys(self):
        s = AlpacaMinutes("QQQ", "https://x", "NB3_NOPE_1", "NB3_NOPE_2", session=FakeAlpaca())
        with self.assertRaisesRegex(ProviderError, "keys missing"):
            s.fetch(minute_start(20261116, 0), minute_start(20261116, 5))


class SyntheticFuturesTests(unittest.TestCase):
    def test_prices_on_tick_grid_and_consistent(self):
        class Src:
            name, realtime = "x", True

            def fetch(self, a, b):
                return [MinuteBar(minute_start(20261116, 0), 600.01, 600.37, 599.93, 600.11)]
        b = SyntheticFutures(Src(), 41.3, 0.25).fetch(None, None)[0]
        for x in (b.o, b.h, b.l, b.c):
            self.assertEqual(x % 0.25, 0.0)
        self.assertTrue(b.l <= min(b.o, b.c) <= max(b.o, b.c) <= b.h)
        self.assertAlmostEqual(b.c, 24784.5, delta=0.25)


class IexGapTests(unittest.TestCase):
    """With allow_empty_minutes, a minute without IEX trades is normal; a stale feed still blocks entries."""

    def cfg(self):
        c = load(PROFILE)
        return replace(c, data=replace(c.data, qqq_provider="replay", eod_rebuild_delay_minutes=3))

    def test_single_empty_minutes_still_trade(self):
        ss = synthetic(at_minute=22, move=6.0)
        for m in (21, 23, 40, 41):                       # minutes with no trade on the single exchange
            s = ss[14]
            s.o[m] = s.h[m] = s.l[m] = s.c[m] = math.nan
        rig = build(self.cfg(), ss, ss[14].key, tempfile.mkdtemp())
        run_day(rig, ss[14].key)
        self.assertEqual(len(rig.store.trades()), 1)
        self.assertEqual(rig.bot.day.incomplete_bars, set())
        self.assertEqual(rig.store.get("signal_agreement")["same"], 1)       # live vs final-data check
        self.assertEqual(rig.bot.account.r.starting_balance, 50000)

    def test_stale_feed_blocks_entry(self):
        ss = synthetic(at_minute=20, move=6.0)
        for m in (21, 22, 23, 24):                       # only the bar's first minute arrives: 4 minutes old at the close
            s = ss[14]
            s.o[m] = s.h[m] = s.l[m] = s.c[m] = math.nan
        rig = build(self.cfg(), ss, ss[14].key, tempfile.mkdtemp())
        run_day(rig, ss[14].key)
        self.assertEqual(rig.store.trades(), [])
        failed = [c["check"] for c in rig.bot.day.decision["checks"] if not c["ok"]]
        self.assertIn("market_data", failed)


class ProfileSafetyTests(unittest.TestCase):
    def test_profile_is_simulation_only(self):
        from nb3bot.__main__ import safety_report
        cfg = load(PROFILE)
        safe, lines = safety_report(cfg)
        self.assertTrue(safe)
        self.assertEqual((cfg.bot.mode, cfg.broker.name, cfg.data.mnq_provider), ("paper", "paper", "synthetic"))
        self.assertIn("SIMULATED", "\n".join(lines))

    def test_synthetic_prices_can_never_reach_a_real_broker(self):
        cfg = load(PROFILE)
        bad = replace(cfg, bot=replace(cfg.bot, mode="live"), broker=replace(cfg.broker, name="projectx",
                                                                             auto_oco_brackets_confirmed=True))
        self.assertTrue(any("synthetic MNQ prices are only allowed" in e for e in validate(bad)))

    def test_safety_check_command_exit_codes(self):
        from nb3bot.__main__ import main
        with self.assertRaises(SystemExit) as e:
            main(["safety-check", "--config", str(PROFILE)])
        self.assertEqual(e.exception.code, 0)

    def test_paper_wiring_needs_no_projectx_credentials(self):
        import os
        from nb3bot.__main__ import _sources_and_broker
        from nb3bot.broker.paper import PaperBroker
        os.environ.pop("PROJECTX_USERNAME", None)
        clock, sig, exe, broker, resolver, fixed = _sources_and_broker(load(PROFILE), "paper")
        self.assertIsInstance(broker, PaperBroker)
        self.assertEqual(broker.balance, 50000)
        self.assertTrue(exe.name.startswith("synthetic:MNQ"))
        self.assertEqual(fixed.id, "SIM.MNQ")
        self.assertIsNone(resolver)

    def test_offline_demo_runs(self):
        from nb3bot.__main__ import main
        main(["demo", "--days", "1", "--pace", "0", "--port", "0"])
