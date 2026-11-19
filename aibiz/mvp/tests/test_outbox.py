import datetime as dt
import json
import random
import unittest
from pathlib import Path

from quotebook import outbox as ob
from quotebook.timeutil import UTC, to_iso
from tests.helpers import AppCase


class Flaky:
    """Fails the first `fail` calls (transiently), then succeeds."""
    name = "flaky"

    def __init__(self, fail=0, permanent=False):
        self.fail, self.permanent, self.calls, self.sent = fail, permanent, 0, []

    def send(self, channel, recipient, body, key):
        self.calls += 1
        if self.permanent:
            raise ob.PermanentError("number does not exist")
        if self.calls <= self.fail:
            raise ob.TransientError("timeout")
        self.sent.append(key)
        return f"id-{self.calls}"


class OutboxCase(AppCase):
    def customer(self, reminders=1, marketing=0):
        self.conn.execute("INSERT INTO customers(name, phone, lang, reminder_consent, marketing_consent, created_at, "
                          "last_seen_at) VALUES ('Ana', '+385990001000', 'hr', ?, ?, 'x', 'x')", (reminders, marketing))
        return self.conn.execute("SELECT * FROM customers").fetchone()

    def q(self, kind="confirmed", key="k1", customer=None, at=None):
        return ob.enqueue(self.conn, self.cfg, kind=kind, recipient="+385990001000", body="hi", dedupe_key=key,
                          now=at or self.app.now(), customer=customer)


class Consent(OutboxCase):
    def test_consent_rules(self):
        no = self.customer(reminders=0)
        self.assertEqual(self.q("reminder", "r1", no), "no_consent")
        self.assertEqual(self.q("followup", "f1", no), "no_consent")
        self.assertEqual(self.q("rebook", "m1", no), "no_consent")
        self.assertEqual(self.q("confirmed", "c1", no), "queued")
        self.assertEqual(self.q("confirmed", "c1", no), "duplicate")

    def test_quiet_hours(self):
        c = self.customer()
        late = dt.datetime(2026, 11, 19, 21, 30, tzinfo=UTC)     # 22:30 Zagreb
        self.q("reminder", "r1", c, at=late)
        row = self.conn.execute("SELECT next_attempt_utc FROM outbox WHERE dedupe_key = 'r1'").fetchone()
        self.assertEqual(row[0], "2026-11-20T07:00:00Z")          # 08:00 Zagreb
        self.q("confirmed", "c1", c, at=late)                      # transactional: not delayed
        row = self.conn.execute("SELECT next_attempt_utc FROM outbox WHERE dedupe_key = 'c1'").fetchone()
        self.assertEqual(row[0], to_iso(late))


class Delivery(OutboxCase):
    def test_retry_with_backoff_then_success(self):
        s = Flaky(fail=2)
        self.q()
        st = ob.process(self.conn, self.cfg, s, self.app.now(), rng=random.Random(1))
        self.assertEqual(st["retry"], 1)
        row = self.conn.execute("SELECT * FROM outbox").fetchone()
        self.assertEqual((row["status"], row["attempts"]), ("pending", 1))
        wait = (dt.datetime.strptime(row["next_attempt_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) - self.app.now())
        self.assertTrue(20 <= wait.total_seconds() <= 40)
        self.assertEqual(ob.process(self.conn, self.cfg, s, self.app.now())["sent"], 0)   # not due yet
        for _ in range(3):
            self.clock.advance(minutes=5)
            ob.process(self.conn, self.cfg, s, self.app.now())
        self.assertEqual(self.conn.execute("SELECT status FROM outbox").fetchone()[0], "sent")
        self.assertEqual(s.sent, ["k1"])

    def test_dead_letter_after_max_attempts_raises_escalation(self):
        s = Flaky(fail=99)
        self.q()
        for _ in range(10):
            ob.process(self.conn, self.cfg, s, self.app.now())
            self.clock.advance(hours=2)
        row = self.conn.execute("SELECT * FROM outbox").fetchone()
        self.assertEqual((row["status"], row["attempts"]), ("dead", 6))
        self.assertEqual(self.conn.execute("SELECT reason FROM escalations").fetchone()[0], "message_failed")
        ob.retry_dead(self.conn, row["id"], self.app.now())
        self.assertEqual(self.conn.execute("SELECT status FROM outbox").fetchone()[0], "pending")

    def test_permanent_error_is_not_retried(self):
        s = Flaky(permanent=True)
        self.q()
        ob.process(self.conn, self.cfg, s, self.app.now())
        self.assertEqual(s.calls, 1)
        self.assertEqual(self.conn.execute("SELECT status FROM outbox").fetchone()[0], "dead")

    def test_outage_stops_the_batch(self):
        s = Flaky(fail=99)
        for i in range(10):
            self.q(key=f"k{i}")
        st = ob.process(self.conn, self.cfg, s, self.app.now())
        self.assertEqual(s.calls, 3)                     # stops after 3 transient failures in a row
        self.assertEqual(st["deferred"], 7)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM outbox WHERE status = 'sending'").fetchone()[0], 0)

    def test_crash_mid_send_is_recovered(self):
        self.q()
        self.conn.execute("UPDATE outbox SET status = 'sending', updated_at = ?", (to_iso(self.app.now()),))
        s = Flaky()
        ob.process(self.conn, self.cfg, s, self.app.now())
        self.assertEqual(s.calls, 0)                     # too recent: another worker may still be sending
        self.clock.advance(minutes=11)
        ob.process(self.conn, self.cfg, s, self.app.now())
        self.assertEqual(self.conn.execute("SELECT status FROM outbox").fetchone()[0], "sent")

    def test_dry_run_sender_writes_locally_and_live_is_refused(self):
        self.q()
        self.app.run_jobs()
        lines = Path(self.tmp, "outbox_dryrun.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(json.loads(lines[0])["key"], "k1")
        self.cfg.raw["messaging"]["send_enabled"] = True
        with self.assertRaises(RuntimeError):
            ob.make_sender(self.cfg, self.app.env, self.tmp)

    def test_backoff_growth_and_cap(self):
        r = random.Random(0)
        d = [ob.backoff(n, rng=r) for n in range(1, 12)]
        self.assertTrue(22 <= d[0] <= 38)
        self.assertTrue(all(x <= 3600 * 1.25 for x in d))

    def test_mask(self):
        self.assertEqual(ob.mask("+385912345678"), "+385******678")
        self.assertEqual(ob.mask("ana@example.invalid"), "a***@example.invalid")


class Jobs(AppCase):
    def test_followup_once_for_expired_request_with_consent(self):
        cid, b = self.book_via_chat()
        self.app.owner_decline(b["id"])
        self.clock.advance(hours=49)
        self.assertEqual(self.app.queue_followups(), 1)
        self.assertEqual(self.app.queue_followups(), 0)          # only once
        cid2, b2 = self.book_via_chat(first="Pranje za mali auto, srijeda u 9", name="Bez Pristanka",
                                      phone="099 000 2000", consent="ne")
        self.app.owner_decline(b2["id"])
        self.clock.advance(hours=49)
        self.assertEqual(self.app.queue_followups(), 0)

    def test_reminder_moves_with_reschedule_and_disappears_on_cancel(self):
        cid, b = self.book_via_chat()
        self.app.owner_confirm(b["id"])
        rem = self.conn.execute("SELECT * FROM outbox WHERE kind = 'reminder'").fetchone()
        self.assertEqual(rem["next_attempt_utc"], "2026-11-22T08:00:00Z")   # 24 h before Mon 09:00
        self.app.owner_reschedule(b["id"], self.local(2026, 11, 25, 10))
        rows = self.conn.execute("SELECT status, next_attempt_utc FROM outbox WHERE kind = 'reminder' ORDER BY id").fetchall()
        self.assertEqual([r["status"] for r in rows], ["skipped", "pending"])
        self.app.owner_cancel(b["id"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM outbox WHERE kind = 'reminder' AND status = 'pending'")
                         .fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
