import datetime as dt
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from quotebook.config import ConfigError, Env, load_config, validate
from quotebook.db import SCHEMA_VERSION, Database
from quotebook.llm import LLMInterpreter, redact
from quotebook.seed import seed
from quotebook.transcripts import write_transcripts
from tests.helpers import ROOT, AppCase


class Migrations(unittest.TestCase):
    def test_fresh_idempotent_and_newer_schema_refused(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(Path(d) / "x.sqlite3")
            self.assertEqual(db.migrate(), SCHEMA_VERSION)
            self.assertEqual(db.migrate(), SCHEMA_VERSION)
            c = db.connect()
            c.execute("UPDATE schema_version SET version = 99")
            c.close()
            with self.assertRaises(RuntimeError):
                db.migrate()


class BackupRestore(AppCase):
    def test_round_trip_and_corrupt_backup_rejected(self):
        cid, b = self.book_via_chat()
        bak = self.app.db.backup(Path(self.tmp) / "b.sqlite3")
        self.app.owner_cancel(b["id"])
        self.app.close_conn()
        self.app.db.restore(bak)
        self.assertEqual(self.app.conn.execute("SELECT status FROM bookings").fetchone()[0], "pending_owner")
        bad = Path(self.tmp) / "bad.sqlite3"
        bad.write_bytes(b"not a database")
        with self.assertRaises((RuntimeError, sqlite3.DatabaseError)):
            self.app.db.restore(bad)


class Retention(AppCase):
    def test_purge_and_export(self):
        cid, b = self.book_via_chat()
        data = self.app.export_customer("099 000 1000")
        self.assertEqual(data["customer"]["name"], "Ana Demo")
        self.assertEqual(len(data["bookings"]), 1)
        self.assertTrue(data["messages"])
        self.clock.advance(days=800)
        out = self.app.purge()
        self.assertEqual(out["conversations"], 1)
        self.assertEqual(out["customers_anonymised"], 1)
        c = self.conn.execute("SELECT * FROM customers").fetchone()
        self.assertEqual((c["name"], c["phone"], c["anonymized"]), ("anonymised", f"anon-{c['id']}", 1))
        self.assertEqual(self.app.export_customer("099 000 1000"), {})

    def test_customer_with_future_booking_is_kept(self):
        self.clock.advance(days=0)
        cid, b = self.book_via_chat()
        self.conn.execute("UPDATE customers SET last_seen_at = '2020-01-01T00:00:00Z'")
        self.assertEqual(self.app.purge()["customers_anonymised"], 0)


class Config(unittest.TestCase):
    def test_demo_configs_valid(self):
        for f in ("demo_detailing.json", "demo_cleaning.json"):
            self.assertEqual(validate(json.loads((ROOT / "config" / f).read_text())), [])

    def test_errors_are_reported(self):
        raw = json.loads((ROOT / "config" / "demo_detailing.json").read_text())
        raw["hours"]["mon"] = [["17:00", "08:00"]]
        raw["services"][0]["price"]["by_size"].pop("van")
        raw["services"][1]["resources"] = ["box9"]
        raw["messaging"]["send_enabled"] = True
        errs = validate(raw)
        self.assertEqual(len(errs), 4, errs)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(raw, f)
        with self.assertRaises(ConfigError):
            load_config(f.name)
        Path(f.name).unlink()

    def test_secrets_only_from_environment(self):
        env = Env.from_environ({"QB_ADMIN_TOKEN": "t", "QB_ALLOW_LIVE_SEND": "yes"})
        self.assertEqual((env.admin_token, env.allow_live_send), ("t", False))


def fake_response(payload=None, stop="end_turn"):
    text = json.dumps(payload) if isinstance(payload, dict) else (payload or "")
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="thinking", thinking=""),
                                                      SimpleNamespace(type="text", text=text)])


class FakeClient:
    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.requests = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.requests.append(kw)
        b = self.behaviour(len(self.requests))
        if isinstance(b, Exception):
            raise b
        return b


class AIInterpreter(AppCase):
    def interp(self, behaviour, **kw):
        return LLMInterpreter(self.cfg, client=FakeClient(behaviour), **kw)

    def parse(self, it, text):
        return it.parse(text, today=dt.date(2026, 11, 19), services=self.cfg.services, sizes=self.cfg.sizes)

    def test_fills_gaps_with_validated_values_only(self):
        it = self.interp(lambda n: fake_response({"language": "hr", "intents": ["book"], "service_id": "polish",
                                                  "size": "large", "area_m2": None, "date": "2026-11-23",
                                                  "time": "10:00", "name": "Hallucinated Name"}))
        p = self.parse(it, "bi mi trebalo da mi se sredi lak na velikom autu za tjedan")
        self.assertEqual((p.service_id, p.size, p.date, p.time), ("polish", "large", dt.date(2026, 11, 23), dt.time(10)))
        self.assertEqual(p.name, "")                   # not in the customer's text -> rejected
        req = it.client.requests[0]
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(req["fallbacks"], "default")

    def test_invalid_values_are_ignored(self):
        it = self.interp(lambda n: fake_response({"language": "hr", "intents": ["hack"], "service_id": "free_car",
                                                  "size": "tank", "area_m2": 5, "date": "2020-01-01", "time": "25:99",
                                                  "name": None}))
        p = self.parse(it, "nesto nejasno")
        self.assertEqual((p.service_id, p.size, p.date, p.time), ("", "", None, None))
        self.assertNotIn("hack", p.intents)

    def test_outage_refusal_and_bad_json_fall_back_to_rules(self):
        for beh in (lambda n: TimeoutError("timeout"), lambda n: fake_response({}, stop="refusal"),
                    lambda n: fake_response("not json")):
            it = self.interp(beh)
            p = self.parse(it, "poliranje za SUV")
            self.assertEqual((p.service_id, p.size, p.source), ("polish", "large", "rules"))

    def test_circuit_breaker(self):
        t = [0.0]
        it = self.interp(lambda n: ConnectionError("down"), failure_threshold=3, cooldown_s=300, clock=lambda: t[0])
        for _ in range(5):
            self.parse(it, "nesto")
        self.assertEqual(len(it.client.requests), 3)    # skipped while open
        t[0] = 301
        self.parse(it, "nesto")
        self.assertEqual(len(it.client.requests), 4)

    def test_complete_rules_result_skips_the_call_and_contact_data_is_redacted(self):
        it = self.interp(lambda n: fake_response({}))
        self.parse(it, "poliranje SUV sutra u 10")
        self.assertEqual(it.client.requests, [])
        self.assertEqual(redact("zovite 091 234 5678 ili ana@example.invalid"), "zovite [phone] ili [email]")


class Logs(unittest.TestCase):
    def test_logs_are_masked(self):
        import logging
        from quotebook.logs import JsonFormatter
        rec = logging.LogRecord("quotebook", logging.INFO, __file__, 1, "new request from %s (%s)",
                                ("+385 91 234 5678", "ana@example.invalid"), None)
        out = json.loads(JsonFormatter().format(rec))["msg"]
        self.assertNotIn("234 5678", out)
        self.assertNotIn("ana@example.invalid", out)


class SeedAndTranscripts(AppCase):
    def test_seed_is_fictional_and_idempotent(self):
        out = seed(self.app)
        self.assertTrue(out["seeded"])
        self.assertFalse(seed(self.app)["seeded"])
        phones = [r[0] for r in self.conn.execute("SELECT phone FROM customers")]
        self.assertTrue(all(p.startswith("+38599000") for p in phones))

    def test_transcripts_file(self):
        out = Path(self.tmp) / "conv.md"
        write_transcripts(out)
        text = out.read_text(encoding="utf-8")
        self.assertIn("JOŠ NIJE POTVRĐEN", text)
        self.assertIn("Message provider outage", text)


class CLI(unittest.TestCase):
    def test_commands(self):
        with tempfile.TemporaryDirectory() as d:
            base = [sys.executable, "-m", "quotebook", "--db", f"{d}/q.sqlite3", "--var", d, "--log-level", "ERROR"]

            def run(*a):
                return subprocess.run(base + list(a), cwd=ROOT, capture_output=True, text=True, timeout=60)
            self.assertEqual(run("check-config").stdout.strip(), "OK")
            self.assertIn("schema v1", run("init").stdout)
            self.assertIn('"seeded": true', run("seed").stdout)
            self.assertIn('"sent"', run("jobs").stdout)
            bak = run("backup", f"{d}/b.sqlite3").stdout.strip()
            self.assertTrue(Path(bak).exists())
            self.assertEqual(run("restore", bak).returncode, 0)
            self.assertIn("conversations", run("purge").stdout)
            bad = run("--config", f"{d}/missing.json", "init")
            self.assertNotEqual(bad.returncode, 0)


if __name__ == "__main__":
    unittest.main()
