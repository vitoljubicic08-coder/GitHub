import datetime as dt
import shutil
import tempfile
import unittest
from pathlib import Path

from quotebook.transcripts import NOW, Clock, fresh_app  # noqa: F401  (re-exported for tests)

ROOT = Path(__file__).resolve().parent.parent


class AppCase(unittest.TestCase):
    config = "demo_detailing.json"

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="qb-test-")
        self.clock = Clock(NOW)
        self.app = fresh_app(self.config, clock=self.clock, tmp=self.tmp, sender=getattr(self, "sender", None))
        self.conn = self.app.conn
        self.cfg = self.app.cfg

    def tearDown(self):
        self.app.close_conn()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def say(self, *messages, cid=None):
        r = None
        for m in messages:
            r = self.app.handle_message(m, cid)
            cid = r["conversation_id"]
        return r

    def local(self, y, mo, d, h, mi=0):
        return dt.datetime(y, mo, d, h, mi, tzinfo=self.cfg.tz)

    def book_via_chat(self, first="Pranje za mali auto, ponedjeljak u 9", name="Ana Demo", phone="099 000 1000",
                      consent="da", pick="1"):
        r = self.say(first)
        cid = r["conversation_id"]
        self.say(pick, name, phone, consent, cid=cid)
        row = self.conn.execute("SELECT * FROM bookings WHERE conversation_id = ? ORDER BY id DESC", (cid,)).fetchone()
        return cid, row
