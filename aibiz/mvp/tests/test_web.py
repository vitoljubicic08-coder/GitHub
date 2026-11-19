"""Integration tests over real HTTP: a server on a random local port, requests with urllib."""
import http.cookiejar
import json
import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

from quotebook.config import Env
from quotebook.web import Server
from tests.helpers import AppCase


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class WebCase(AppCase):
    def setUp(self):
        super().setUp()
        self.app.env = Env(admin_token="correct-horse-battery")
        self.srv = Server(("127.0.0.1", 0), self.app)
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.th = threading.Thread(target=self.srv.serve_forever, daemon=True)
        self.th.start()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, path, data=None, ctype=None, method=None):
        body = data
        headers = {}
        if isinstance(data, dict) and ctype == "json":
            body, headers["Content-Type"] = json.dumps(data).encode(), "application/json"
        elif isinstance(data, dict):
            body, headers["Content-Type"] = urllib.parse.urlencode(data).encode(), "application/x-www-form-urlencoded"
        elif ctype:
            headers["Content-Type"] = ctype
        r = urllib.request.Request(self.base + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()

    def chat(self, text, cid=None, mid=None):
        s, h, b = self.req("/api/chat", {"text": text, "conversation_id": cid, "message_id": mid}, "json")
        return s, json.loads(b)

    def login(self):
        return self.req("/admin/login", {"token": "correct-horse-battery"})

    def csrf(self):
        s, h, b = self.req("/admin")
        return re.search(r"name='csrf' value='([^']+)'", b).group(1), b


class Public(WebCase):
    def test_home_health_calendar_slots(self):
        s, h, b = self.req("/")
        self.assertEqual(s, 200)
        self.assertIn("Sjaj Auto Detailing", b)
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Frame-Options"], "DENY")
        s, h, b = self.req("/healthz")
        self.assertEqual((s, json.loads(b)["ok"], json.loads(b)["dry_run"]), (200, True, True))
        s, h, b = self.req("/calendar?service=polish&size=large")
        self.assertIn("08:00", b)
        s, h, b = self.req("/api/slots?service=wash&size=small&date=2026-11-20")
        d = json.loads(b)
        self.assertEqual((d["minutes"], d["slots"][0]["start"]), (90, "2026-11-20T07:00:00Z"))
        self.assertEqual(self.req("/api/slots?service=nope")[0], 400)
        self.assertEqual(self.req("/static/../web.py")[0], 404)
        self.assertEqual(self.req("/nothing")[0], 404)

    def test_chat_flow_over_http(self):
        s, r = self.chat("Bok, koliko košta poliranje za SUV?", mid="a1")
        self.assertEqual(s, 200)
        cid = r["conversation_id"]
        for m in ("3", "Ivan Horvat", "091 234 5678", "da"):
            s, r = self.chat(m, cid)
        self.assertIn("JOŠ NIJE POTVRĐEN", r["text"])

    def test_bad_requests(self):
        self.assertEqual(self.req("/api/chat", b"{not json", "application/json", "POST")[0], 400)
        self.assertEqual(self.req("/api/chat", b"text=hi", "text/plain", "POST")[0], 415)
        self.assertEqual(self.req("/api/chat", json.dumps({"text": "x" * 9000}).encode(), "application/json", "POST")[0], 413)
        self.assertEqual(self.chat("")[0], 400)
        self.assertEqual(self.chat("bok", cid="short")[0], 400)
        self.assertEqual(self.chat(["list"])[0], 400)

    def test_rate_limit_returns_429(self):
        s, r = self.chat("bok")
        codes = [self.chat("bok", r["conversation_id"])[0] for _ in range(15)]
        self.assertIn(429, codes)


class Admin(WebCase):
    def test_requires_login_and_rejects_wrong_token(self):
        s, h, b = self.req("/admin")
        self.assertEqual((s, h["Location"]), (303, "/admin/login"))
        s, h, b = self.req("/admin/login", {"token": "wrong"})
        self.assertIn("Pogrešan token", b)
        s, h, b = self.req("/admin/action", {"action": "pause"})
        self.assertEqual(s, 303)                                   # not logged in -> login page
        self.assertFalse(self.app.paused())

    def test_login_brute_force_is_limited(self):
        codes = [self.req("/admin/login", {"token": f"x{i}"})[0] for i in range(7)]
        self.assertIn(429, codes)

    def test_owner_confirms_and_csrf_is_enforced(self):
        s, r = self.chat("Pranje za mali auto, ponedjeljak u 9")
        for m in ("1", "Ana Demo", "099 000 1000", "da"):
            s, r = self.chat(m, r["conversation_id"])
        s, h, _ = self.login()
        self.assertEqual(s, 303)
        self.assertIn("HttpOnly", h["Set-Cookie"])
        self.assertIn("SameSite=Strict", h["Set-Cookie"])
        token, page = self.csrf()
        self.assertIn("Treba vašu potvrdu (1)", page)
        self.assertIn("DRY RUN", page)
        bid = self.conn.execute("SELECT id FROM bookings").fetchone()[0]
        s, h, b = self.req("/admin/action", {"action": "confirm", "booking_id": bid, "csrf": "forged"})
        self.assertEqual(s, 403)
        self.assertEqual(self.conn.execute("SELECT status FROM bookings").fetchone()[0], "pending_owner")
        s, h, b = self.req("/admin/action", {"action": "confirm", "booking_id": bid, "csrf": token})
        self.assertEqual(s, 303)
        self.assertEqual(self.conn.execute("SELECT status FROM bookings").fetchone()[0], "confirmed")
        s, h, b = self.req("/admin/calendar.ics")
        self.assertIn("BEGIN:VEVENT", b)
        self.assertIn("STATUS:CONFIRMED", b)

    def test_owner_overrides(self):
        self.login()
        token, _ = self.csrf()
        s, h, b = self.req("/admin/action", {"action": "create", "service_id": "wash", "resource_id": "box1",
                                            "start": "2026-11-22T10:00", "name": "Telefon", "phone": "091 111 2222",
                                            "csrf": token})
        self.assertEqual(s, 303)
        self.assertNotIn("note=", h["Location"])                  # Sunday is fine for the owner
        s, h, b = self.req("/admin/action", {"action": "create", "service_id": "wash", "resource_id": "box1",
                                            "start": "2026-11-22T10:30", "csrf": token})
        self.assertIn("zauzet", urllib.parse.unquote(h["Location"]))   # but never on top of another booking
        self.req("/admin/action", {"action": "pause", "csrf": token})
        self.assertTrue(self.app.paused())
        s, r = self.chat("Koliko košta pranje?")
        self.assertIn("Vlasnik će vam odgovoriti", r["text"])
        self.req("/admin/action", {"action": "resume", "csrf": token})
        self.assertFalse(self.app.paused())
        s, h, b = self.req("/admin/action", {"action": "block", "start": "2026-11-20T08:00", "end": "2026-11-20T12:00",
                                            "reason": "<script>x</script>", "csrf": token})
        _, page = self.csrf()
        self.assertNotIn("<script>x</script>", page)              # owner input is escaped
        self.assertIn("&lt;script&gt;", page)

    def test_admin_disabled_without_token(self):
        self.app.env = Env(admin_token="")
        self.assertEqual(self.req("/admin")[0], 403)


if __name__ == "__main__":
    unittest.main()
