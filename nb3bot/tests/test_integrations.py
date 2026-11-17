"""ProjectX adapter (fake HTTP, request formats from the official docs), data providers, safety, dashboard."""
import json
import tempfile
import unittest
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from nb3bot.broker.base import BracketEntry, BrokerError, UncertainOrderState
from nb3bot.broker.projectx import ProjectXBroker, ProjectXClient
from nb3bot.config import Config, validate
from nb3bot.data.base import MinuteBar, SessionFeed, check_feed, check_ratio
from nb3bot.data.providers import MassiveMinutes
from nb3bot.safety import KillSwitch, authorization_status, write_authorization
from nb3bot.timeutil import minute_start


class Resp:
    def __init__(self, code, body):
        self.status_code, self._b = code, body
        self.text = json.dumps(body)

    def json(self):
        return self._b


class FakeHTTP:
    """Scripted responses per path; each entry is a Resp or an exception to raise."""

    def __init__(self, script):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls = []

    def post(self, url, json=None, timeout=None, headers=None):
        path = url.split("api.example", 1)[-1]
        self.calls.append((path, json))
        r = self.script[path].pop(0) if len(self.script.get(path, [])) > 1 else self.script[path][0]
        if isinstance(r, Exception):
            raise r
        return r

    get = post


LOGIN = Resp(200, {"token": "T", "success": True, "errorCode": 0})


def client(script):
    s = {"/api/Auth/loginKey": [LOGIN], **script}
    http = FakeHTTP(s)
    return ProjectXClient("https://api.example", "user", "key", session=http), http


class ProjectXTests(unittest.TestCase):
    def test_bracket_order_body_matches_documentation(self):
        cl, http = client({"/api/Order/place": [Resp(200, {"orderId": 9056, "success": True, "errorCode": 0})]})
        oid = ProjectXBroker(cl, 465).place_bracket_entry(BracketEntry("CON.F.US.MNQ.Z26", -1, 1, 496, 1488, "NB3V2-20261117-465"))
        self.assertEqual(oid, "9056")
        path, body = http.calls[-1]
        self.assertEqual(path, "/api/Order/place")
        self.assertEqual((body["type"], body["side"], body["size"], body["customTag"]), (2, 1, 1, "NB3V2-20261117-465"))
        self.assertEqual(body["stopLossBracket"], {"ticks": 496, "type": 4})
        self.assertEqual(body["takeProfitBracket"], {"ticks": 1488, "type": 1})

    def test_position_brackets_mode_rejection_is_reported(self):
        msg = "Brackets cannot be used with Position Brackets. You must enable Auto OCO Brackets."
        cl, _ = client({"/api/Order/place": [Resp(200, {"orderId": 9057, "success": False, "errorCode": 2, "errorMessage": msg})]})
        with self.assertRaisesRegex(BrokerError, "Auto OCO"):
            ProjectXBroker(cl, 465).place_bracket_entry(BracketEntry("C", 1, 1, 10, 30, "t"))

    def test_order_timeout_is_uncertain_and_not_retried(self):
        cl, http = client({"/api/Order/place": [requests.ConnectionError("reset")]})
        with self.assertRaises(UncertainOrderState):
            ProjectXBroker(cl, 465).place_bracket_entry(BracketEntry("C", 1, 1, 10, 30, "t"))
        self.assertEqual(sum(1 for p, _ in http.calls if p == "/api/Order/place"), 1)

    def test_read_calls_retry_and_relogin(self):
        pos = Resp(200, {"positions": [{"id": 1, "accountId": 465, "contractId": "C", "type": 2, "size": 2,
                                        "averagePrice": 25000.5}], "success": True, "errorCode": 0})
        cl, http = client({"/api/Position/searchOpen": [Resp(500, {}), Resp(401, {}), pos]})
        cl._sleep = None
        import nb3bot.broker.projectx as px
        orig = px.time.sleep
        px.time.sleep = lambda s: None
        try:
            p = ProjectXBroker(cl, 465).positions()
        finally:
            px.time.sleep = orig
        self.assertEqual((p[0].size, p[0].avg_price), (-2, 25000.5))
        self.assertEqual(sum(1 for c, _ in http.calls if c == "/api/Auth/loginKey"), 2)

    def test_parsing_orders_and_fills(self):
        cl, _ = client({"/api/Order/search": [Resp(200, {"success": True, "orders": [
            {"id": 36598, "accountId": 704, "contractId": "C", "status": 2, "type": 2, "side": 0, "size": 1,
             "fillVolume": 1, "filledPrice": 6335.25, "customTag": "tag-1", "creationTimestamp": "2025-07-18T21:00:01+00:00"}]})],
                        "/api/Trade/search": [Resp(200, {"success": True, "trades": [
                            {"id": 1, "contractId": "C", "creationTimestamp": "2025-01-21T16:13:52+00:00", "price": 6065.25,
                             "profitAndLoss": 50.0, "fees": 1.4, "commissions": 0.35, "side": 1, "size": 1, "voided": False,
                             "orderId": 14328}]})]})
        b = ProjectXBroker(cl, 704)
        o = b.find_order_by_tag("tag-1", datetime(2025, 7, 18, tzinfo=timezone.utc))
        self.assertEqual((o.status, o.type, o.side, o.fill_price), ("filled", "market", 1, 6335.25))
        f = b.fills(datetime(2025, 1, 1, tzinfo=timezone.utc))[0]
        self.assertEqual((f.pnl, round(f.fees, 2), f.side), (50.0, 1.75, -1))

    def test_missing_credentials_message(self):
        from nb3bot.broker.base import BrokerUnavailable
        cfg = Config().broker
        cfg.username_env, cfg.api_key_env = "NB3_TEST_NOPE_U", "NB3_TEST_NOPE_K"
        with self.assertRaisesRegex(BrokerUnavailable, "environment variables"):
            ProjectXClient.from_env(cfg)


class DataTests(unittest.TestCase):
    def test_feed_rejects_bad_bars_and_detects_gaps(self):
        f = SessionFeed("QQQ", 20261117)
        t0 = minute_start(20261117, 0)
        self.assertIsNone(f.add(MinuteBar(t0, 600, 599, 601, 600)))                 # high < low
        for m in (0, 1, 3):
            f.add(MinuteBar(t0 + timedelta(minutes=m), 600, 600.5, 599.5, 600.1))
        h = check_feed(f, t0 + timedelta(minutes=5, seconds=30), 20)
        self.assertFalse(h.ok)
        self.assertIn("missing", h.detail)

    def test_ratio_check(self):
        a, b = SessionFeed("QQQ", 20261117), SessionFeed("MNQ", 20261117)
        t0 = minute_start(20261117, 0)
        for m in range(5):
            a.add(MinuteBar(t0 + timedelta(minutes=m), 600, 601, 599, 600))
            b.add(MinuteBar(t0 + timedelta(minutes=m), 24780, 24800, 24760, 24780 if m < 4 else 26000))
        self.assertFalse(check_ratio(a, b, 4, 0.01).ok)
        self.assertTrue(check_ratio(a, b, 3, 0.01).ok)

    def test_massive_delayed_flag(self):
        t = int(minute_start(20261117, 0).timestamp() * 1000)
        http = FakeHTTP({"/v2/aggs/ticker/QQQ/range/1/minute/": [Resp(200, {"status": "DELAYED",
                                                                                "results": [{"t": t, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}]})]})
        http.get = lambda url, params=None, headers=None, timeout=None: Resp(200, {"status": "DELAYED",
                                                                                "results": [{"t": t, "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 9}]})
        src = MassiveMinutes("QQQ", "https://api.example", "NB3_NOPE", session=http)
        bars = src.fetch(minute_start(20261117, 0), minute_start(20261117, 5))
        self.assertEqual(len(bars), 1)
        self.assertFalse(src.realtime)


class SafetyTests(unittest.TestCase):
    def test_orders_need_every_switch(self):
        d = tempfile.mkdtemp()
        cfg = Config()
        cfg.bot.state_dir = d
        rep = Path(d) / "parity.json"
        self.assertTrue(authorization_status(cfg, "paper", rep)[0])
        self.assertFalse(authorization_status(cfg, "live", rep)[0])                 # broker is paper
        cfg.broker.name, cfg.broker.account_id = "projectx", 77
        self.assertIn("live_orders_enabled is false", authorization_status(cfg, "live", rep)[1])
        cfg.authorization.live_orders_enabled = True
        self.assertIn("authorize", authorization_status(cfg, "live", rep)[1])
        with self.assertRaises(ValueError):
            write_authorization(d, "live", 77, "yes please")
        write_authorization(d, "live", 77, "I AUTHORIZE LIVE ORDERS ON ACCOUNT 77")
        self.assertIn("parity report", authorization_status(cfg, "live", rep)[1])
        rep.write_text(json.dumps({"passed": True}))
        self.assertTrue(authorization_status(cfg, "live", rep)[0])
        self.assertFalse(authorization_status(cfg, "practice", rep)[0])             # practice is separate

    def test_config_validation(self):
        cfg = Config()
        cfg.bot.mode = "live"
        errs = validate(cfg)
        self.assertTrue(any("projectx" in e for e in errs))
        self.assertTrue(any("auto_oco" in e for e in errs))

    def test_kill_switch_file(self):
        k = KillSwitch(tempfile.mkdtemp())
        self.assertFalse(k.active())
        k.trigger("why")
        self.assertTrue(k.active())
        self.assertEqual(k.reason(), "why")
        k.clear()
        self.assertFalse(k.active())


class DashboardTests(unittest.TestCase):
    def test_status_and_token_protected_kill(self):
        from nb3bot.dashboard.server import serve
        killed = []
        srv = serve("127.0.0.1", 0, lambda: {"mode": "paper"}, killed.append, lambda: None, "secret")
        port = srv.server_address[1]
        try:
            st = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status").read())
            self.assertEqual(st["mode"], "paper")
            self.assertIn(b"NB3 V2 Bot", urllib.request.urlopen(f"http://127.0.0.1:{port}/").read())
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/kill", data=b'{"token":"bad"}', method="POST")
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(req)
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/kill", data=b'{"token":"secret","reason":"t"}', method="POST")
            urllib.request.urlopen(req)
            self.assertEqual(killed, ["t"])
        finally:
            srv.shutdown()
