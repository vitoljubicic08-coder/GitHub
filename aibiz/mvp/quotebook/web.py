"""HTTP layer (standard library): the demo website with the chat assistant, a public free-slot
calendar, a JSON API, and the owner's admin page.

Run behind a TLS reverse proxy (Caddy, nginx) for anything beyond a local demo; see docs/DEPLOY.md.
"""
from __future__ import annotations

import datetime as dt
import hmac
import html
import json
import logging
import secrets
import threading
import time
import traceback
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from . import availability as av
from . import booking as bk
from .assistant import App, RateLimited
from .db import SCHEMA_VERSION, get_setting
from .i18n import DAY_SHORT, duration, hours_text, when
from .outbox import mask, retry_dead
from .pricing import InvalidInfo, MissingInfo, estimate
from .timeutil import from_iso, to_iso

log = logging.getLogger("quotebook.web")
STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 8 * 1024
SESSION_TTL_S = 12 * 3600
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
e = html.escape


class Sessions:
    def __init__(self):
        self.lock = threading.Lock()
        self.items = {}

    def create(self) -> tuple:
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        with self.lock:
            self.items[sid] = (time.time() + SESSION_TTL_S, csrf)
        return sid, csrf

    def get(self, sid):
        with self.lock:
            v = self.items.get(sid or "")
            if not v:
                return None
            if v[0] < time.time():
                del self.items[sid]
                return None
            return v[1]

    def drop(self, sid):
        with self.lock:
            self.items.pop(sid or "", None)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, addr, app: App, trust_proxy=False, secure_cookies=False):
        super().__init__(addr, Handler)
        self.app = app
        self.trust_proxy = trust_proxy
        self.secure_cookies = secure_cookies
        self.sessions = Sessions()


class Handler(BaseHTTPRequestHandler):
    server_version = "quotebook/" + __version__
    sys_version = ""

    # ------------------------------------------------------------------ helpers
    @property
    def app(self) -> App:
        return self.server.app

    def log_message(self, fmt, *args):
        log.info("%s %s", self.client_ip(), fmt % args)

    def client_ip(self) -> str:
        if self.server.trust_proxy:
            xff = self.headers.get("X-Forwarded-For", "")
            if xff:
                return xff.split(",")[0].strip()
        return self.client_address[0]

    def send(self, status, body: bytes, ctype="text/html; charset=utf-8", headers=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, status, obj, headers=None):
        self.send(status, json.dumps(obj, ensure_ascii=False).encode(), "application/json; charset=utf-8", headers)

    def page(self, title, body, status=200, headers=None):
        doc = (f"<!doctype html><html lang='hr'><head><meta charset='utf-8'><meta name='viewport' "
               f"content='width=device-width, initial-scale=1'><title>{e(title)}</title>"
               f"<link rel='stylesheet' href='/static/style.css'></head><body>{body}</body></html>")
        self.send(status, doc.encode(), headers=headers)

    def read_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise PayloadTooLarge()
        return self.rfile.read(n) if n else b""

    def cookies(self) -> dict:
        out = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                out[k] = v
        return out

    def redirect(self, to, headers=None):
        h = {"Location": to}
        h.update(headers or {})
        self.send(HTTPStatus.SEE_OTHER, b"", headers=h)

    # ------------------------------------------------------------------ routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        url = urllib.parse.urlsplit(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        route = (method, url.path)
        try:
            if route == ("GET", "/"):
                return self.home()
            if route == ("GET", "/healthz"):
                return self.health()
            if route == ("GET", "/calendar"):
                return self.public_calendar(q)
            if route == ("GET", "/api/slots"):
                return self.api_slots(q)
            if route == ("POST", "/api/chat"):
                return self.api_chat()
            if method == "GET" and url.path.startswith("/static/"):
                return self.static(url.path[len("/static/"):])
            if url.path == "/admin/login":
                return self.admin_login(method)
            if route == ("POST", "/admin/logout"):
                return self.admin_logout()
            if route == ("GET", "/admin"):
                return self.admin_home(q)
            if route == ("POST", "/admin/action"):
                return self.admin_action()
            if route == ("GET", "/admin/calendar.ics"):
                return self.admin_ics()
            self.send(404, b"not found", "text/plain")
        except PayloadTooLarge:
            self.json(413, {"error": "payload_too_large"})
        except Exception:
            eid = secrets.token_hex(4)
            log.error("unhandled error %s on %s %s\n%s", eid, method, url.path, traceback.format_exc())
            self.json(500, {"error": "internal_error", "id": eid})
        finally:
            self.app.close_conn()

    # ------------------------------------------------------------------ public pages
    def static(self, name):
        p = (STATIC / name).resolve()
        if STATIC not in p.parents or not p.is_file():
            return self.send(404, b"not found", "text/plain")
        ctype = {".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".svg": "image/svg+xml"}.get(p.suffix, "application/octet-stream")
        self.send(200, p.read_bytes(), ctype)

    def health(self):
        try:
            self.app.conn.execute("SELECT 1").fetchone()
            ok = True
        except Exception:
            ok = False
        self.json(200 if ok else 503, {"ok": ok, "schema": SCHEMA_VERSION, "dry_run": True,
                                       "paused": ok and self.app.paused(), "version": __version__})

    def home(self):
        cfg = self.app.cfg
        rows = []
        for s in cfg.services:
            lows = []
            for size in (cfg.sizes or {"": None}):
                try:
                    lows.append(estimate(s, cfg.measure, size, 50, cfg.booking["slot_step_minutes"]).low)
                except (MissingInfo, InvalidInfo):
                    pass
            frm = f"od {min(lows):.0f} €" if lows else ""
            if cfg.measure == "area_m2" and s.needs_measure:
                frm = f"od {float(s.price.get('minimum', 0)):.0f} € (ovisno o m²)"
            rows.append(f"<li><strong>{e(s.name('hr'))}</strong> <span class='muted'>{e(frm)}</span></li>")
        body = f"""
<header class='site'><div class='wrap'><h1>{e(cfg.business['name'])}</h1>
<p class='muted'>Demo stranica s izmišljenom tvrtkom i simuliranim podacima. Poruke se nikome ne šalju.</p></div></header>
<main class='wrap grid'>
<section><h2>Usluge</h2><ul class='services'>{''.join(rows)}</ul>
<h2>Radno vrijeme</h2><p>{e(hours_text(cfg, 'hr'))}</p>
<p><a href='/calendar'>Pogledaj slobodne termine</a></p></section>
<section class='chat' aria-label='Asistent'>
<div class='chat-head'>Zatraži cijenu i termin <span class='badge'>automatski asistent</span></div>
<div id='log' class='log' role='log' aria-live='polite'></div>
<div id='opts' class='opts'></div>
<form id='f' class='send'><input id='msg' maxlength='1000' autocomplete='off' placeholder='Npr. koliko košta poliranje za SUV?' aria-label='Poruka'>
<button>Pošalji</button></form>
<p class='muted small'>Asistent je automatski. Vlasnik potvrđuje svaku rezervaciju. Vaše podatke koristimo samo za ovaj upit.</p>
</section></main><script src='/static/chat.js'></script>"""
        self.page(cfg.business["name"], body)

    def _slot_query(self, q):
        cfg = self.app.cfg
        svc = cfg.get_service(q.get("service", cfg.services[0].id))
        if svc is None:
            raise ValueError("unknown service")
        size = q.get("size") or (next(iter(cfg.sizes)) if cfg.sizes else "")
        area = int(q.get("area") or 60)
        est = estimate(svc, cfg.measure, size, area, cfg.booking["slot_step_minutes"])
        return svc, size, area, est

    def api_slots(self, q):
        try:
            svc, size, area, est = self._slot_query(q)
            day = dt.date.fromisoformat(q["date"]) if q.get("date") else self.app.now().astimezone(self.app.cfg.tz).date()
        except (ValueError, KeyError, MissingInfo, InvalidInfo) as ex:
            return self.json(400, {"error": "bad_request", "detail": str(ex)[:100]})
        slots = av.day_slots(self.app.conn, self.app.cfg, svc, est.minutes, day, self.app.now())
        self.json(200, {"service": svc.id, "date": day.isoformat(), "minutes": est.minutes,
                        "estimate": [est.low, est.high],
                        "slots": [{"start": to_iso(s.start), "resource": s.resource_id} for s in slots]})

    def public_calendar(self, q):
        cfg, app = self.app.cfg, self.app
        try:
            svc, size, area, est = self._slot_query(q)
        except (ValueError, MissingInfo, InvalidInfo):
            return self.page("Termini", "<main class='wrap'><p>Nepoznata usluga.</p></main>", 400)
        today = app.now().astimezone(cfg.tz).date()
        opts = "".join(f"<option value='{e(s.id)}'{' selected' if s.id == svc.id else ''}>{e(s.name('hr'))}</option>"
                       for s in cfg.services)
        size_sel = ""
        if cfg.sizes:
            size_sel = "<select name='size'>" + "".join(
                f"<option value='{e(k)}'{' selected' if k == size else ''}>{e(v.get('hr', k))}</option>"
                for k, v in cfg.sizes.items()) + "</select>"
        elif cfg.measure == "area_m2":
            size_sel = f"<input name='area' type='number' min='10' max='1000' value='{area}' aria-label='m²'> m²"
        cols = []
        for k in range(7):
            day = today + dt.timedelta(days=k)
            slots = av.day_slots(app.conn, cfg, svc, est.minutes, day, app.now())
            items = "".join(f"<li>{s.start.astimezone(cfg.tz):%H:%M}</li>" for s in slots[:12]) or "<li class='muted'>—</li>"
            cols.append(f"<div class='day'><h3>{DAY_SHORT['hr'][day.weekday()]} {day.day}.{day.month}.</h3><ul>{items}</ul></div>")
        body = (f"<main class='wrap'><h1>Slobodni termini</h1><form class='inline'><select name='service'>{opts}</select>"
                f"{size_sel}<button>Prikaži</button></form><p class='muted'>{e(svc.name('hr'))}: okvirno {est.low:.0f}–"
                f"{est.high:.0f} €, traje {e(duration(est.minutes, 'hr'))}. Termin rezervirate preko asistenta; "
                f"vlasnik ga potvrđuje.</p><div class='week'>{''.join(cols)}</div><p><a href='/'>Natrag</a></p></main>")
        self.page("Slobodni termini", body)

    def api_chat(self):
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.json(415, {"error": "expected application/json"})
        try:
            data = json.loads(self.read_body() or b"{}")
        except (ValueError, UnicodeDecodeError):
            return self.json(400, {"error": "invalid_json"})
        if not isinstance(data, dict):
            return self.json(400, {"error": "invalid_json"})
        cid, mid, text = data.get("conversation_id"), data.get("message_id"), data.get("text")
        if cid is not None and (not isinstance(cid, str) or not 8 <= len(cid) <= 64):
            return self.json(400, {"error": "bad_conversation_id"})
        if mid is not None and (not isinstance(mid, str) or len(mid) > 64):
            return self.json(400, {"error": "bad_message_id"})
        try:
            r = self.app.handle_message(text, cid, mid, "web", client_key=self.client_ip())
        except RateLimited:
            return self.json(429, {"error": "rate_limited"}, {"Retry-After": "60"})
        except ValueError as ex:
            return self.json(400, {"error": "bad_message", "detail": str(ex)[:100]})
        self.json(200, dict(r))

    # ------------------------------------------------------------------ admin
    def _session(self):
        sid = self.cookies().get("qb_admin")
        csrf = self.server.sessions.get(sid)
        return sid, csrf

    def _require_admin(self):
        if not self.app.env.admin_token:
            self.page("Admin", "<main class='wrap'><p>Admin is disabled: set QB_ADMIN_TOKEN (see docs/CONFIG.md).</p></main>", 403)
            return None
        sid, csrf = self._session()
        if not csrf:
            self.redirect("/admin/login")
            return None
        return csrf

    def admin_login(self, method):
        if not self.app.env.admin_token:
            return self.page("Admin", "<main class='wrap'><p>Admin is disabled: set QB_ADMIN_TOKEN.</p></main>", 403)
        msg = ""
        if method == "POST":
            if not self.app.limiter.allow("login:" + self.client_ip(), self.app.cfg.rate_limits["login_per_ip_per_minute"]):
                return self.page("Prijava", "<main class='wrap'><p>Previše pokušaja. Pokušajte za minutu.</p></main>", 429)
            form = urllib.parse.parse_qs(self.read_body().decode("utf-8", "replace"))
            token = (form.get("token") or [""])[0]
            if hmac.compare_digest(token.encode(), self.app.env.admin_token.encode()):
                sid, _ = self.server.sessions.create()
                flags = "HttpOnly; SameSite=Strict; Path=/admin" + ("; Secure" if self.server.secure_cookies else "")
                return self.redirect("/admin", {"Set-Cookie": f"qb_admin={sid}; Max-Age={SESSION_TTL_S}; {flags}"})
            msg = "<p class='err'>Pogrešan token.</p>"
            log.warning("failed admin login from %s", self.client_ip())
        self.page("Prijava", f"<main class='wrap narrow'><h1>Administracija</h1>{msg}<form method='post'>"
                             "<label>Token <input type='password' name='token' autocomplete='current-password'></label>"
                             "<button>Prijava</button></form></main>")

    def admin_logout(self):
        sid, csrf = self._session()
        form = urllib.parse.parse_qs(self.read_body().decode("utf-8", "replace"))
        if csrf and hmac.compare_digest((form.get("csrf") or [""])[0].encode(), csrf.encode()):
            self.server.sessions.drop(sid)
        self.redirect("/admin/login", {"Set-Cookie": "qb_admin=; Max-Age=0; Path=/admin"})

    def admin_action(self):
        csrf = self._require_admin()
        if csrf is None:
            return
        form = {k: v[0] for k, v in urllib.parse.parse_qs(self.read_body().decode("utf-8", "replace")).items()}
        if not hmac.compare_digest(form.get("csrf", "").encode(), csrf.encode()):
            return self.page("Admin", "<main class='wrap'><p>Neispravan zahtjev (CSRF).</p></main>", 403)
        app, cfg, a = self.app, self.app.cfg, form.get("action", "")
        note = ""
        try:
            bid = int(form["booking_id"]) if form.get("booking_id") else None
            if a == "confirm":
                app.owner_confirm(bid)
            elif a == "decline":
                app.owner_decline(bid, form.get("note", ""))
            elif a == "cancel":
                app.owner_cancel(bid, form.get("note", ""))
            elif a == "complete":
                app.owner_complete(bid)
            elif a == "move":
                app.owner_reschedule(bid, _local(form["start"], cfg.tz))
            elif a == "create":
                app.owner_create(form["service_id"], _local(form["start"], cfg.tz), form["resource_id"],
                                 form.get("name", ""), form.get("phone", ""), form.get("note", ""))
            elif a == "block":
                app.block_time(_local(form["start"], cfg.tz), _local(form["end"], cfg.tz), form.get("resource_id") or None,
                               form.get("reason", ""))
            elif a == "pause":
                app.set_paused(True)
            elif a == "resume":
                app.set_paused(False)
            elif a == "resolve":
                app.resolve_escalation(int(form["escalation_id"]))
            elif a == "retry":
                retry_dead(app.conn, int(form["outbox_id"]), app.now())
            elif a == "run_jobs":
                note = "Poslovi pokrenuti: " + json.dumps(app.run_jobs())
            else:
                note = "Nepoznata akcija."
        except bk.SlotTaken:
            note = "Termin je zauzet: preklapa se s drugom rezervacijom."
        except bk.BookingError as ex:
            note = f"Nije moguće: {ex.code}."
        except (ValueError, KeyError) as ex:
            note = f"Neispravan unos: {ex}"
        self.redirect("/admin" + ("?note=" + urllib.parse.quote(note[:300]) if note else ""))

    def admin_ics(self):
        if self._require_admin() is None:
            return
        rows = self.app.conn.execute("SELECT * FROM bookings WHERE status IN ('pending_owner','confirmed') "
                                     "ORDER BY start_utc").fetchall()
        self.send(200, ics(self.app.cfg, rows).encode(), "text/calendar; charset=utf-8",
                  {"Content-Disposition": "attachment; filename=quotebook.ics"})

    def admin_home(self, q):
        csrf = self._require_admin()
        if csrf is None:
            return
        app, cfg, conn = self.app, self.app.cfg, self.app.conn
        now = app.now()
        tz = cfg.tz
        hid = f"<input type='hidden' name='csrf' value='{e(csrf)}'>"

        def btn(action, label, **fields):
            extra = "".join(f"<input type='hidden' name='{e(k)}' value='{e(str(v))}'>" for k, v in fields.items())
            return (f"<form method='post' action='/admin/action' class='inline'>{hid}<input type='hidden' name='action' "
                    f"value='{e(action)}'>{extra}<button>{e(label)}</button></form>")

        def cust(r):
            if not r["customer_id"]:
                return "—"
            c = conn.execute("SELECT name, phone FROM customers WHERE id = ?", (r["customer_id"],)).fetchone()
            return f"{e(c['name'])} <span class='muted'>{e(c['phone'])}</span>" if c else "—"

        def svc_name(sid):
            s = cfg.get_service(sid)
            return e(s.name("hr") if s else sid)

        def price(r):
            return f"{r['price_low']:.0f}–{r['price_high']:.0f} €" if r["price_low"] is not None else ""

        paused = app.paused()
        note = f"<p class='note'>{e(q['note'])}</p>" if q.get("note") else ""
        pending = conn.execute("SELECT * FROM bookings WHERE status = 'pending_owner' ORDER BY start_utc").fetchall()
        pend_html = "".join(
            f"<tr><td>{e(r['ref'])}</td><td>{e(when(cfg, from_iso(r['start_utc']), 'hr'))}</td><td>{svc_name(r['service_id'])}"
            f"</td><td>{e(r['resource_id'])}</td><td>{cust(r)}</td><td>{price(r)}</td><td>"
            f"{btn('confirm', 'Potvrdi', booking_id=r['id'])}{btn('decline', 'Odbij', booking_id=r['id'])}</td></tr>"
            for r in pending) or "<tr><td colspan='7' class='muted'>Nema zahtjeva.</td></tr>"
        escs = conn.execute("SELECT * FROM escalations WHERE status = 'open' ORDER BY id DESC LIMIT 50").fetchall()
        esc_html = "".join(f"<tr><td>{e(r['created_at'][:16].replace('T', ' '))}</td><td>{e(r['reason'])}</td>"
                           f"<td>{e(r['excerpt'])}</td><td>{btn('resolve', 'Riješeno', escalation_id=r['id'])}</td></tr>"
                           for r in escs) or "<tr><td colspan='4' class='muted'>Ništa otvoreno.</td></tr>"
        upcoming = conn.execute("SELECT * FROM bookings WHERE status = 'confirmed' AND end_utc > ? ORDER BY start_utc "
                                "LIMIT 100", (to_iso(now),)).fetchall()
        up_html = "".join(
            f"<tr><td>{e(r['ref'])}</td><td>{e(when(cfg, from_iso(r['start_utc']), 'hr'))}</td><td>{svc_name(r['service_id'])}"
            f"</td><td>{e(r['resource_id'])}</td><td>{cust(r)}</td><td>{e(r['source'])}</td><td>"
            f"{btn('complete', 'Obavljeno', booking_id=r['id'])}{btn('cancel', 'Otkaži', booking_id=r['id'])}"
            f"<form method='post' action='/admin/action' class='inline'>{hid}<input type='hidden' name='action' value='move'>"
            f"<input type='hidden' name='booking_id' value='{r['id']}'><input type='datetime-local' name='start' required>"
            f"<button>Pomakni</button></form></td></tr>" for r in upcoming) or "<tr><td colspan='7' class='muted'>Nema.</td></tr>"

        today = now.astimezone(tz).date()
        cal = []
        for k in range(7):
            day = today + dt.timedelta(days=k)
            lo = dt.datetime.combine(day, dt.time(0), tzinfo=tz)
            hi = lo + dt.timedelta(days=1)
            items = []
            for r in conn.execute("SELECT * FROM bookings WHERE status IN ('held','pending_owner','confirmed') AND "
                                  "start_utc < ? AND end_utc > ? ORDER BY start_utc", (to_iso(hi), to_iso(lo))):
                if r["status"] == "held" and from_iso(r["hold_expires_utc"]) <= now:
                    continue
                s, en = from_iso(r["start_utc"]).astimezone(tz), from_iso(r["end_utc"]).astimezone(tz)
                items.append(f"<li class='st-{e(r['status'])}'>{s:%H:%M}–{en:%H:%M} {e(r['resource_id'])} "
                             f"{svc_name(r['service_id'])}</li>")
            for r in conn.execute("SELECT * FROM blocks WHERE start_utc < ? AND end_utc > ?", (to_iso(hi), to_iso(lo))):
                s, en = from_iso(r["start_utc"]).astimezone(tz), from_iso(r["end_utc"]).astimezone(tz)
                items.append(f"<li class='st-block'>{s:%H:%M}–{en:%H:%M} {e(r['resource_id'] or 'sve')} blok: "
                             f"{e(r['reason'])}</li>")
            closed = " <span class='muted'>(zatvoreno)</span>" if av.is_closed_day(cfg, day) else ""
            cal.append(f"<div class='day'><h3>{DAY_SHORT['hr'][day.weekday()]} {day.day}.{day.month}.{closed}</h3>"
                       f"<ul>{''.join(items) or '<li class=muted>—</li>'}</ul></div>")

        outbox = conn.execute("SELECT * FROM outbox ORDER BY id DESC LIMIT 30").fetchall()
        out_html = "".join(
            f"<tr><td>{e(r['created_at'][:16].replace('T', ' '))}</td><td>{e(r['kind'])}</td><td>{e(mask(r['recipient']))}</td>"
            f"<td>{e(r['status'])}{' (' + str(r['attempts']) + ')' if r['attempts'] else ''}</td>"
            f"<td class='small'>{e(r['body'][:140])}</td><td>"
            f"{btn('retry', 'Ponovi', outbox_id=r['id']) if r['status'] == 'dead' else ''}</td></tr>"
            for r in outbox) or "<tr><td colspan='6' class='muted'>Prazno.</td></tr>"
        aud = conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 25").fetchall()
        aud_html = "".join(f"<tr><td>{e(r['ts'][:19].replace('T', ' '))}</td><td>{e(r['actor'])}</td><td>{e(r['action'])}</td>"
                           f"<td>{e(r['entity'])} {e(r['entity_id'] or '')}</td></tr>" for r in aud)
        svc_opts = "".join(f"<option value='{e(s.id)}'>{e(s.name('hr'))}</option>" for s in cfg.services)
        res_opts = "".join(f"<option value='{e(r['id'])}'>{e(r['name'])}</option>" for r in cfg.resources)
        body = f"""
<header class='site'><div class='wrap row'><h1>{e(cfg.business['name'])} · administracija</h1>
<div>{btn('resume', 'Uključi asistenta') if paused else btn('pause', 'Pauziraj asistenta')}
<a href='/admin/calendar.ics'>Kalendar (.ics)</a>
<form method='post' action='/admin/logout' class='inline'>{hid}<button>Odjava</button></form></div></div></header>
<main class='wrap'>
<p class='banner'>DEMO / DRY RUN: poruke se ne šalju nikome, samo se zapisuju u lokalnu datoteku.
{'<strong> Asistent je PAUZIRAN: svi upiti idu vama.</strong>' if paused else ''}</p>{note}
<h2>Treba vašu potvrdu ({len(pending)})</h2>
<table><tr><th>Ref</th><th>Termin</th><th>Usluga</th><th>Mjesto</th><th>Kupac</th><th>Procjena</th><th></th></tr>{pend_html}</table>
<h2>Treba vas ({len(escs)})</h2>
<table><tr><th>Kada</th><th>Razlog</th><th>Poruka</th><th></th></tr>{esc_html}</table>
<h2>Sljedećih 7 dana</h2><div class='week'>{''.join(cal)}</div>
<h2>Potvrđeni termini</h2>
<table><tr><th>Ref</th><th>Termin</th><th>Usluga</th><th>Mjesto</th><th>Kupac</th><th>Izvor</th><th></th></tr>{up_html}</table>
<div class='grid'>
<section><h2>Ručni unos termina</h2><form method='post' action='/admin/action' class='stack'>{hid}
<input type='hidden' name='action' value='create'><label>Usluga <select name='service_id'>{svc_opts}</select></label>
<label>Mjesto <select name='resource_id'>{res_opts}</select></label><label>Početak <input type='datetime-local' name='start' required></label>
<label>Ime <input name='name' maxlength='80'></label><label>Mobitel <input name='phone' maxlength='30'></label>
<label>Napomena <input name='note' maxlength='200'></label><button>Spremi</button></form></section>
<section><h2>Blokiraj vrijeme</h2><form method='post' action='/admin/action' class='stack'>{hid}
<input type='hidden' name='action' value='block'><label>Mjesto <select name='resource_id'><option value=''>sve</option>{res_opts}</select></label>
<label>Od <input type='datetime-local' name='start' required></label><label>Do <input type='datetime-local' name='end' required></label>
<label>Razlog <input name='reason' maxlength='200'></label><button>Blokiraj</button></form></section></div>
<h2>Poruke (outbox)</h2>{btn('run_jobs', 'Pokreni poslove sada')}
<table><tr><th>Kada</th><th>Vrsta</th><th>Prima</th><th>Status</th><th>Tekst</th><th></th></tr>{out_html}</table>
<h2>Zapis radnji</h2><table><tr><th>Vrijeme (UTC)</th><th>Tko</th><th>Radnja</th><th>Što</th></tr>{aud_html}</table>
<p class='muted small'>Schema v{SCHEMA_VERSION} · quotebook {__version__} · automation_paused={e(get_setting(conn, 'automation_paused', '0'))}</p>
</main>"""
        self.page("Administracija", body)


class PayloadTooLarge(Exception):
    pass


def _local(s: str, tz) -> dt.datetime:
    """Parse an HTML datetime-local value ('2026-11-23T08:00') as the business's local time."""
    if not s:
        raise ValueError("missing date/time")
    return dt.datetime.fromisoformat(s[:16]).replace(tzinfo=tz)


def ics(cfg, rows) -> str:
    def esc(x):
        return str(x).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")
    out = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//quotebook//EN", "CALSCALE:GREGORIAN"]
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    for r in rows:
        svc = cfg.get_service(r["service_id"])
        out += ["BEGIN:VEVENT", f"UID:{r['ref']}@quotebook", f"DTSTAMP:{stamp}",
                f"DTSTART:{r['start_utc'].replace('-', '').replace(':', '')}",
                f"DTEND:{r['end_utc'].replace('-', '').replace(':', '')}",
                f"SUMMARY:{esc((svc.name('hr') if svc else r['service_id']) + ' ' + r['ref'])}",
                f"DESCRIPTION:{esc('Status: ' + r['status'] + ', ' + r['resource_id'])}",
                "STATUS:" + ("CONFIRMED" if r["status"] == "confirmed" else "TENTATIVE"), "END:VEVENT"]
    out.append("END:VCALENDAR")
    return "\r\n".join(out) + "\r\n"


def serve(app: App, host="127.0.0.1", port=8000, trust_proxy=False, secure_cookies=False):
    srv = Server((host, port), app, trust_proxy=trust_proxy, secure_cookies=secure_cookies)
    log.info("serving on http://%s:%d (dry run; admin %s)", host, port,
             "enabled" if app.env.admin_token else "disabled: set QB_ADMIN_TOKEN")
    return srv
