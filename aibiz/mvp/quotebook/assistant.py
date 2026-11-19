"""The application: conversation flow, owner actions and background jobs, on top of the booking,
availability, pricing and outbox modules. The web server and the CLI are thin layers over App.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import secrets
import threading
import time

from . import availability as av
from . import booking as bk
from . import outbox as ob
from . import parser as rules
from .config import Config, Env
from .db import Database, audit, get_setting, set_setting, transaction
from .i18n import duration, hours_text, t, when
from .pricing import InvalidInfo, MissingInfo, estimate
from .timeutil import from_iso, to_iso, utcnow

log = logging.getLogger("quotebook.app")

MAX_TEXT = 1000


class RateLimited(Exception):
    pass


class RateLimiter:
    """Fixed-window counter per key (conversation, IP). In memory: fine for one process."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.windows = {}

    def allow(self, key: str, limit: int, per_s: float = 60.0) -> bool:
        now = self.clock()
        with self.lock:
            start, n = self.windows.get(key, (now, 0))
            if now - start >= per_s:
                start, n = now, 0
            if n >= limit:
                self.windows[key] = (start, n)
                return False
            self.windows[key] = (start, n + 1)
            if len(self.windows) > 50_000:      # bound memory under a flood of distinct keys
                self.windows = {k: v for k, v in self.windows.items() if now - v[0] < per_s}
            return True


class Reply(dict):
    """{'text': str, 'options': [str], 'conversation_id': str, 'step': str}"""


class App:
    def __init__(self, cfg: Config, db: Database, env: Env = None, var_dir="var", clock=utcnow, interpreter=None,
                 sender=None):
        self.cfg, self.db, self.env = cfg, db, env or Env()
        self.var_dir = var_dir
        self.clock = clock
        self.interpreter = interpreter
        self.sender = sender or ob.make_sender(cfg, self.env, var_dir)
        self.limiter = RateLimiter()
        self._local = threading.local()

    # ------------------------------------------------------------------ plumbing
    @property
    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = self.db.connect()
        return c

    def close_conn(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None

    def now(self) -> dt.datetime:
        return self.clock()

    def _parse(self, text, lang, offered):
        kw = dict(today=self.now().astimezone(self.cfg.tz).date(), services=self.cfg.services, sizes=self.cfg.sizes,
                  lang_default=lang, offered=offered)
        if self.interpreter is not None:
            return self.interpreter.parse(text, **kw)
        return rules.parse(text, **kw)

    def _load_conv(self, cid, channel):
        row = self.conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        if row:
            return dict(row), json.loads(row["state"])
        return None, None

    def _save_conv(self, cid, channel, lang, state, status="open"):
        ts = to_iso(self.now())
        self.conn.execute(
            "INSERT INTO conversations(id, channel, lang, state, status, customer_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET lang = excluded.lang, state = excluded.state, "
            "status = excluded.status, customer_id = COALESCE(excluded.customer_id, conversations.customer_id), "
            "updated_at = excluded.updated_at",
            (cid, channel, lang, json.dumps(state), status, state.get("customer_id"), ts, ts))

    def _escalate(self, cid, reason, excerpt, booking_id=None):
        with transaction(self.conn):
            open_ = self.conn.execute("SELECT id FROM escalations WHERE conversation_id = ? AND status = 'open' "
                                      "AND reason = ?", (cid, reason)).fetchone()
            if open_:
                self.conn.execute("UPDATE escalations SET excerpt = substr(excerpt || ' | ' || ?, -600) WHERE id = ?",
                                  (excerpt[:300], open_["id"]))
            else:
                self.conn.execute("INSERT INTO escalations(conversation_id, booking_id, reason, excerpt, created_at) "
                                  "VALUES (?,?,?,?,?)", (cid, booking_id, reason, excerpt[:300], to_iso(self.now())))
            audit(self.conn, "assistant", "escalate", "conversation", cid, json.dumps({"reason": reason}))

    def paused(self) -> bool:
        return get_setting(self.conn, "automation_paused", "0") == "1"

    # ------------------------------------------------------------------ public entry point
    def handle_message(self, text: str, conversation_id: str = None, message_id: str = None, channel: str = "web",
                       client_key: str = "") -> Reply:
        if not isinstance(text, str):
            raise ValueError("text must be a string")
        text = text.replace("\x00", "").strip()
        if not text:
            raise ValueError("empty message")
        if len(text) > MAX_TEXT:
            raise ValueError(f"message longer than {MAX_TEXT} characters")
        new = not conversation_id
        cid = conversation_id or secrets.token_urlsafe(16)
        rl = self.cfg.rate_limits
        if not self.limiter.allow("conv:" + cid, rl["per_conversation_per_minute"]):
            raise RateLimited()
        if client_key and not self.limiter.allow("ip:" + client_key, rl["per_ip_per_minute"]):
            raise RateLimited()

        row, state = (None, None) if new else self._load_conv(cid, channel)
        if not new and row is None:
            new = True
        default_lang = self.cfg.assistant["default_language"]
        if new:
            state = {"step": "start", "lang": rules.detect_language(text, default_lang), "unclear": 0}

        # duplicate delivery of the same inbound message: return the reply we already gave
        if message_id and not new:
            dup = self.conn.execute("SELECT id FROM messages WHERE conversation_id = ? AND direction = 'in' "
                                    "AND external_id = ?", (cid, message_id)).fetchone()
            if dup:
                out = self.conn.execute("SELECT text FROM messages WHERE reply_to = ? ORDER BY id DESC LIMIT 1",
                                        (dup["id"],)).fetchone()
                return Reply(text=out["text"] if out else "", options=[], conversation_id=cid,
                             step=state["step"], duplicate=True)

        if self.paused():
            reply, options = t(self.cfg, state["lang"], "paused"), []
            self._save_conv(cid, channel, state["lang"], state)
            self._escalate(cid, "automation_paused", text)
        else:
            reply, options = self._step(cid, state, text, new)
            self._save_conv(cid, channel, state["lang"], state, "handoff" if state["step"] == "handoff" else "open")
        ts = to_iso(self.now())
        cur = self.conn.execute("INSERT INTO messages(conversation_id, direction, text, external_id, created_at) "
                                "VALUES (?,?,?,?,?)", (cid, "in", text, message_id, ts))
        self.conn.execute("INSERT INTO messages(conversation_id, direction, text, reply_to, created_at) "
                          "VALUES (?,?,?,?,?)", (cid, "out", reply, cur.lastrowid, ts))
        values = ([str(i) for i in range(1, len(options) + 1)] if state["step"] in ("offered", "resched_offered")
                  else list(options))
        return Reply(text=reply, options=options, option_values=values, conversation_id=cid, step=state["step"])

    # ------------------------------------------------------------------ dialogue
    def _step(self, cid, st, text, new):
        cfg, lang_default = self.cfg, st["lang"]
        offered = len(st.get("offers", [])) if st["step"] in ("offered", "resched_offered") else 0
        p = self._parse(text, lang_default, offered)
        if len(text.split()) >= 3:
            st["lang"] = rules.detect_language(text, st["lang"])
        L = st["lang"]
        prefix = t(cfg, L, "greeting", business=cfg.business["name"]) + "\n\n" if new else ""

        if st["step"] == "handoff":
            self._escalate(cid, st.get("handoff_reason", "handoff"), text)
            return t(cfg, L, "handoff"), []
        if p.intents & {"human", "complaint"}:
            reason = "complaint" if "complaint" in p.intents else "human_requested"
            st["step"], st["handoff_reason"] = "handoff", reason
            self._release_hold(st)
            self._escalate(cid, reason, text, st.get("booking_id"))
            return prefix + t(cfg, L, "handoff"), []
        contact_steps = ("contact_name", "contact_phone", "consent")
        if st["step"] in contact_steps and "cancel" in p.intents and not p.ref:
            self._release_hold(st)
            st["step"] = "service"
            return prefix + t(cfg, L, "hold_released") + " " + t(cfg, L, "anything_else"), []
        if st["step"] in contact_steps and not p.phone and (p.has_when() or p.service_id or p.size or p.area_m2):
            self._release_hold(st)            # the customer wants a different time or service: offer again
            st["step"] = "service"
        if "cancel" in p.intents and st["step"] not in contact_steps:
            r = self._cancel(cid, st, p, text)
            return prefix + r[0], r[1]
        if "reschedule" in p.intents or st["step"] in ("resched_ref", "resched_when", "resched_offered"):
            if "reschedule" in p.intents or st["step"] != "resched_offered" or p.choice or p.has_when():
                r = self._reschedule(cid, st, p, text)
                if r is not None:
                    return (prefix + r[0], r[1])
        if st["step"] == "cancel_ref":
            r = self._cancel(cid, st, p, text)
            return prefix + r[0], r[1]

        extra = []
        if "hours" in p.intents:
            extra.append(t(cfg, L, "hours", hours=hours_text(cfg, L)))
        if "location" in p.intents:
            loc = cfg.business.get("location", {})
            extra.append(t(cfg, L, "location", location=loc.get(L) or cfg.business.get("address", "")))
        lead = prefix + ("\n".join(extra) + "\n\n" if extra else "")

        if st["step"] in ("contact_name", "contact_phone", "consent"):
            return self._contact(cid, st, p, text, lead)

        # slot filling: take whatever the message gives us
        if p.service_id:
            if p.service_id != st.get("service_id"):
                st.pop("estimate", None)
            st["service_id"] = p.service_id
        if p.size:
            st["size"], _ = p.size, st.pop("estimate", None)
        if p.area_m2:
            st["area"], _ = p.area_m2, st.pop("estimate", None)
        if p.date or p.time or p.window:
            st["pref"] = {"date": p.date.isoformat() if p.date else (st.get("pref", {}).get("date") if not p.date_error else None),
                          "time": p.time.strftime("%H:%M") if p.time else None,
                          "window": list(p.window) if p.window else None}

        if p.date_error:
            st["unclear"] = 0
            return lead + t(cfg, L, p.date_error), []
        if p.time_error:
            return lead + t(cfg, L, "invalid_time"), []

        if st["step"] == "done" and (p.service_id or p.intents & {"book", "quote"}):
            st["step"] = "service"
            st.pop("offers", None)

        if st["step"] == "offered" and p.choice:
            return self._take_offer(cid, st, p.choice - 1, lead)

        svc = cfg.get_service(st.get("service_id", ""))
        if svc is None:
            key = "ask_service_first" if new else "ask_service"
            return self._unclear_or(cid, st, text, lead, key, p, options=[s.name(L) for s in cfg.services],
                                    faq=bool(extra), new=new)
        if "estimate" not in st:
            try:
                e = estimate(svc, cfg.measure, st.get("size", ""), st.get("area", 0), cfg.booking["slot_step_minutes"])
            except MissingInfo as m:
                st["step"] = "measure"
                if m.what == "size":
                    names = [v.get(L, k) for k, v in cfg.sizes.items()]
                    return lead + t(cfg, L, "ask_size", options=", ".join(names)), names
                return lead + t(cfg, L, "ask_area"), []
            except InvalidInfo:
                st.pop("area", None)
                st["step"] = "measure"
                return lead + t(cfg, L, "bad_area"), []
            st["estimate"] = {"low": e.low, "high": e.high, "minutes": e.minutes}
            st["quoted_at"] = to_iso(self.now())
            lead += t(cfg, L, "estimate", service=svc.name(L), low=_eur(e.low), high=_eur(e.high),
                      duration=duration(e.minutes, L)) + "\n"
        elif st["step"] == "offered" and not (p.date or p.time or p.window or p.service_id or p.size or p.area_m2):
            if extra:
                return lead.rstrip() + "\n\n" + self._offer_text(st, L, "offer"), self._offer_labels(st, L)
            return self._unclear_or(cid, st, text, lead, "choose_number", p, n=len(st.get("offers", [])),
                                    options=self._offer_labels(st, L), new=new)
        st["unclear"] = 0
        return self._offer(cid, st, svc, lead)

    def _unclear_or(self, cid, st, text, lead, key, p, options=None, faq=False, new=False, **kw):
        """Ask for what is missing. Messages that carry nothing usable count towards a hand-over to
        the owner (after assistant.max_unclear + 1 in a row)."""
        L = st["lang"]
        if p.intents & {"thanks"} and not p.service_id and st["step"] in ("start", "done"):
            return lead + t(self.cfg, L, "thanks"), []
        if faq or p.intents & {"greeting", "book", "quote", "thanks"}:
            if st["step"] == "start":
                st["step"] = "service"
            return lead + t(self.cfg, L, key, **kw), options or []
        st["unclear"] = st.get("unclear", 0) + 1
        if st["unclear"] > self.cfg.assistant["max_unclear"]:
            st["step"], st["handoff_reason"] = "handoff", "not_understood"
            self._escalate(cid, "not_understood", text)
            return lead + t(self.cfg, L, "handoff"), []
        if st["step"] == "start":
            st["step"] = "service"
        msg = t(self.cfg, L, key, **kw) if new or key == "choose_number" else t(self.cfg, L, "unclear")
        return lead + msg, options or []

    def _minutes(self, st):
        return int(st["estimate"]["minutes"])

    def _offer(self, cid, st, svc, lead, exclude_booking_id=None, key_step="offered"):
        cfg, L = self.cfg, st["lang"]
        pref = st.get("pref") or {}
        d = dt.date.fromisoformat(pref["date"]) if pref.get("date") else None
        tm = dt.time.fromisoformat(pref["time"]) if pref.get("time") else None
        win = tuple(pref["window"]) if pref.get("window") else None
        slots = av.suggest(self.conn, cfg, svc, self._minutes(st), self.now(), date=d, time=tm, window=win,
                           n=cfg.booking["max_suggestions"], exclude_booking_id=exclude_booking_id)
        if not slots:
            st["step"], st["handoff_reason"] = "handoff", "no_slots"
            self._escalate(cid, "no_slots", f"{svc.id} {pref}")
            return lead + t(cfg, L, "no_slots", days=cfg.booking["horizon_days"]), []
        st["offers"] = [{"start": to_iso(s.start), "end": to_iso(s.end), "resource": s.resource_id} for s in slots]
        st["step"] = key_step
        same_day = d is None or slots[0].start.astimezone(cfg.tz).date() == d
        note = ""
        if d is not None and not same_day and av.is_closed_day(cfg, d):
            note = t(cfg, L, "closed_day") + " "
        key = "offer" if same_day else "offer_other_day"
        return lead + note + self._offer_text(st, L, key), self._offer_labels(st, L)

    def _offer_labels(self, st, L):
        return [when(self.cfg, from_iso(o["start"]), L) for o in st.get("offers", [])]

    def _offer_text(self, st, L, key):
        labels = self._offer_labels(st, L)
        opts = "\n".join(f"{i}) {lab}" for i, lab in enumerate(labels, 1))
        return t(self.cfg, L, key, options=opts, n=len(labels))

    def _take_offer(self, cid, st, idx, lead):
        cfg, L = self.cfg, st["lang"]
        o = st["offers"][idx]
        svc = cfg.get_service(st["service_id"])
        slot = av.Slot(from_iso(o["start"]), from_iso(o["end"]), o["resource"])
        self._release_hold(st)
        b = None
        # the offered resource first, then any other bay/team that can do the job at the same time
        for rid in [o["resource"]] + [r for r in svc.resources if r != o["resource"]]:
            try:
                b = bk.hold(self.conn, cfg, svc, av.Slot(slot.start, slot.end, rid), self.now(),
                            idempotency_key=f"{cid}:{o['start']}:{rid}",
                            price=(st["estimate"]["low"], st["estimate"]["high"]),
                            details={"size": st.get("size"), "area_m2": st.get("area")}, conversation_id=cid)
                break
            except bk.SlotTaken:
                continue
            except bk.OutsideHours:
                break
        if b is None:
            r = self._offer(cid, st, svc, "")
            if st["step"] != "offered":
                return lead + r[0], r[1]
            return lead + self._offer_text(st, L, "slot_gone"), r[1]
        st["booking_id"] = b["id"]
        st["step"] = "contact_name" if not st.get("name") else ("contact_phone" if not st.get("phone") else "consent")
        msg = t(cfg, L, "held", when=when(cfg, slot.start, L), minutes=cfg.booking["hold_minutes"])
        if st["step"] == "consent":
            msg = t(cfg, L, "ask_consent")
        return lead + msg, []

    def _release_hold(self, st):
        bid = st.get("booking_id")
        if not bid:
            return
        row = self.conn.execute("SELECT status FROM bookings WHERE id = ?", (bid,)).fetchone()
        if row and row["status"] == "held":
            with transaction(self.conn):
                self.conn.execute("UPDATE bookings SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'held'",
                                  (to_iso(self.now()), bid))
            st.pop("booking_id", None)

    def _contact(self, cid, st, p, text, lead):
        cfg, L = self.cfg, st["lang"]
        if p.name:
            st["name"] = p.name
        elif st["step"] == "contact_name" and not p.phone:
            words = [w for w in text.replace(",", " ").split() if w]
            if 1 <= len(words) <= 4 and all(w.replace("-", "").replace("'", "").isalpha() for w in words):
                st["name"] = " ".join(w[:1].upper() + w[1:] for w in words)
        if p.phone:
            st["phone"] = p.phone
        elif p.phone_error:
            return lead + t(cfg, L, "bad_phone"), []
        if p.email:
            st["email"] = p.email
        if not st.get("name"):
            st["step"] = "contact_name"
            return lead + t(cfg, L, "ask_name"), []
        if not st.get("phone"):
            st["step"] = "contact_phone"
            return lead + t(cfg, L, "ask_phone"), []
        if st["step"] != "consent":
            st["step"] = "consent"
            return lead + t(cfg, L, "ask_consent"), ["da" if L == "hr" else "yes", "ne" if L == "hr" else "no"]
        if not p.intents & {"yes", "no"}:
            return lead + t(cfg, L, "ask_consent"), ["da" if L == "hr" else "yes", "ne" if L == "hr" else "no"]
        consent = "yes" in p.intents
        now = self.now()
        cust_id = bk.upsert_customer(self.conn, st["name"], st["phone"], L, now, email=st.get("email"),
                                     reminder_consent=consent)
        st["customer_id"] = cust_id
        try:
            b = bk.submit(self.conn, cfg, st["booking_id"], cust_id, now)
        except (bk.HoldExpired, bk.InvalidTransition, bk.NotFound):
            st.pop("booking_id", None)
            svc = cfg.get_service(st["service_id"])
            r = self._offer(cid, st, svc, "")
            return lead + t(cfg, L, "hold_expired") + "\n" + r[0], r[1]
        st["step"] = "done"
        st["ref"] = b["ref"]
        w = when(cfg, from_iso(b["start_utc"]), L)
        svc = cfg.get_service(b["service_id"])
        with transaction(self.conn):
            ob.enqueue(self.conn, cfg, kind="owner_new", recipient=cfg.business.get("owner_contact", "owner"),
                       body=t(cfg, "hr", "msg_owner_new", ref=b["ref"], service=svc.name("hr"),
                              when=when(cfg, from_iso(b["start_utc"]), "hr"), name=st["name"], phone=st["phone"]),
                       dedupe_key=f"owner_new:{b['id']}", now=now, booking_id=b["id"])
            if b["status"] == "confirmed":
                self._after_confirm(b)
        if b["status"] == "confirmed":
            return lead + t(cfg, L, "confirmed_now", name=st["name"], when=w, ref=b["ref"]), []
        return lead + t(cfg, L, "pending", name=st["name"], when=w, ref=b["ref"]), []

    # ------------------------------------------------------------------ manage existing bookings
    def _find_booking(self, st, p):
        """A booking may be changed from the conversation it was made in, or with ref + matching phone."""
        if p.ref and p.phone:
            row = self.conn.execute("SELECT b.* FROM bookings b JOIN customers c ON c.id = b.customer_id "
                                    "WHERE b.ref = ? AND c.phone = ? AND b.status IN ('pending_owner','confirmed')",
                                    (p.ref, p.phone)).fetchone()
            return row, True
        if st.get("ref") and not p.ref:
            row = self.conn.execute("SELECT * FROM bookings WHERE ref = ? AND status IN ('pending_owner','confirmed')",
                                    (st["ref"],)).fetchone()
            return row, bool(row)
        return None, bool(p.ref and p.phone)

    def _cancel(self, cid, st, p, text):
        cfg, L = self.cfg, st["lang"]
        row, tried = self._find_booking(st, p)
        if row is None:
            if tried or st["step"] == "cancel_ref" and (p.ref or p.phone):
                st["step"], st["handoff_reason"] = "handoff", "cancel_not_found"
                self._escalate(cid, "cancel_not_found", text)
                return t(cfg, L, "cancel_not_found"), []
            self._release_hold(st)
            st["step"] = "cancel_ref"
            return t(cfg, L, "cancel_ask_ref"), []
        now = self.now()
        b = bk.cancel(self.conn, row["id"], now, actor="customer")
        self._after_cancel(b, notify_customer=False)
        st["step"] = "done"
        return t(cfg, L, "cancel_done", ref=b["ref"], when=when(cfg, from_iso(b["start_utc"]), L)), []

    def _reschedule(self, cid, st, p, text):
        cfg, L = self.cfg, st["lang"]
        if st["step"] == "resched_offered" and p.choice:
            o = st["offers"][p.choice - 1]
            slot = av.Slot(from_iso(o["start"]), from_iso(o["end"]), o["resource"])
            try:
                b = bk.reschedule(self.conn, cfg, st["manage_id"], slot, self.now(), actor="customer")
            except bk.SlotTaken:
                svc = cfg.get_service(st["service_id"])
                r = self._offer(cid, st, svc, "", exclude_booking_id=st["manage_id"], key_step="resched_offered")
                return self._offer_text(st, L, "slot_gone") if st["step"] == "resched_offered" else r[0], r[1]
            self._after_reschedule(b)
            st["step"] = "done"
            note = t(cfg, L, "status_confirmed_note" if b["status"] == "confirmed" else "status_pending_note")
            return t(cfg, L, "resched_done", ref=b["ref"], when=when(cfg, slot.start, L), status_note=note), []
        if st["step"] in ("resched_when", "resched_offered") and st.get("manage_id"):
            if not p.has_when():
                return t(cfg, L, "resched_ask_when", ref=st.get("manage_ref", "")), []
            if p.date_error:
                return t(cfg, L, p.date_error), []
            st["pref"] = {"date": p.date.isoformat() if p.date else None,
                          "time": p.time.strftime("%H:%M") if p.time else None,
                          "window": list(p.window) if p.window else None}
            svc = cfg.get_service(st["service_id"])
            return self._offer(cid, st, svc, "", exclude_booking_id=st["manage_id"], key_step="resched_offered")
        row, tried = self._find_booking(st, p)
        if row is None:
            if tried:
                st["step"], st["handoff_reason"] = "handoff", "reschedule_not_found"
                self._escalate(cid, "reschedule_not_found", text)
                return t(cfg, L, "cancel_not_found"), []
            st["step"] = "resched_ref"
            return t(cfg, L, "cancel_ask_ref"), []
        st["manage_id"], st["manage_ref"] = row["id"], row["ref"]
        st["service_id"] = row["service_id"]
        mins = int((from_iso(row["end_utc"]) - from_iso(row["start_utc"])).total_seconds() // 60)
        st["estimate"] = {"low": row["price_low"], "high": row["price_high"], "minutes": mins}
        st["step"] = "resched_when"
        if p.has_when() and not p.date_error:
            return self._reschedule(cid, st, p, text)
        return t(cfg, L, "resched_ask_when", ref=row["ref"]), []

    # ------------------------------------------------------------------ side effects of state changes
    def _customer(self, customer_id):
        if not customer_id:
            return None
        return self.conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()

    def _msg(self, kind, b, key, **extra):
        c = self._customer(b["customer_id"])
        if c is None:
            return "no_customer"
        L = c["lang"]
        body = t(self.cfg, L, key, business=self.cfg.business["name"], ref=b["ref"],
                 when=when(self.cfg, from_iso(b["start_utc"]), L), **extra)
        return ob.enqueue(self.conn, self.cfg, kind=kind, recipient=c["phone"], body=body,
                          dedupe_key=f"{kind}:{b['id']}:{b['start_utc']}", now=self.now(), customer=c,
                          booking_id=b["id"], send_after=extra.get("_send_after"))

    def _after_confirm(self, b):
        self._msg("confirmed", b, "msg_confirmed")
        start = from_iso(b["start_utc"])
        rem = start - dt.timedelta(hours=self.cfg.messaging["reminder_hours_before"])
        if rem > self.now():
            c = self._customer(b["customer_id"])
            if c is not None:
                L = c["lang"]
                ob.enqueue(self.conn, self.cfg, kind="reminder", recipient=c["phone"],
                           body=t(self.cfg, L, "msg_reminder", business=self.cfg.business["name"], ref=b["ref"],
                                  when=when(self.cfg, start, L)),
                           dedupe_key=f"reminder:{b['id']}:{b['start_utc']}", now=self.now(), customer=c,
                           booking_id=b["id"], send_after=rem)

    def _after_cancel(self, b, notify_customer=True):
        with transaction(self.conn):
            ob.skip_for_booking(self.conn, b["id"], ("reminder",), self.now())
            if notify_customer:
                self._msg("cancelled", b, "msg_cancelled")
            ob.enqueue(self.conn, self.cfg, kind="owner_new", recipient=self.cfg.business.get("owner_contact", "owner"),
                       body=f"Otkazano: {b['ref']} ({when(self.cfg, from_iso(b['start_utc']), 'hr')})",
                       dedupe_key=f"owner_cancel:{b['id']}", now=self.now(), booking_id=b["id"])

    def _after_reschedule(self, b):
        with transaction(self.conn):
            ob.skip_for_booking(self.conn, b["id"], ("reminder",), self.now())
            self._msg("rescheduled", b, "msg_rescheduled")
            if b["status"] == "confirmed":
                start = from_iso(b["start_utc"])
                rem = start - dt.timedelta(hours=self.cfg.messaging["reminder_hours_before"])
                c = self._customer(b["customer_id"])
                if rem > self.now() and c is not None:
                    ob.enqueue(self.conn, self.cfg, kind="reminder", recipient=c["phone"],
                               body=t(self.cfg, c["lang"], "msg_reminder", business=self.cfg.business["name"],
                                      ref=b["ref"], when=when(self.cfg, start, c["lang"])),
                               dedupe_key=f"reminder:{b['id']}:{b['start_utc']}", now=self.now(), customer=c,
                               booking_id=b["id"], send_after=rem)

    # ------------------------------------------------------------------ owner actions (admin page)
    def owner_confirm(self, booking_id):
        b = bk.confirm(self.conn, booking_id, self.now())
        with transaction(self.conn):
            self._after_confirm(b)
        return b

    def owner_decline(self, booking_id, note=""):
        b = bk.decline(self.conn, booking_id, self.now(), note=note)
        with transaction(self.conn):
            if b["customer_id"]:
                self._msg("declined", b, "msg_declined")
        return b

    def owner_cancel(self, booking_id, note=""):
        b = bk.cancel(self.conn, booking_id, self.now(), actor="owner", note=note)
        with transaction(self.conn):
            ob.skip_for_booking(self.conn, b["id"], ("reminder",), self.now())
            if b["customer_id"]:
                self._msg("cancelled", b, "msg_cancelled")
        return b

    def owner_complete(self, booking_id):
        return bk.complete(self.conn, booking_id, self.now())

    def owner_reschedule(self, booking_id, start_local: dt.datetime):
        row = bk.get(self.conn, booking_id)
        mins = from_iso(row["end_utc"]) - from_iso(row["start_utc"])
        start = start_local.astimezone(dt.timezone.utc)
        b = bk.reschedule(self.conn, self.cfg, booking_id, av.Slot(start, start + mins, row["resource_id"]),
                          self.now(), actor="owner")
        self._after_reschedule(b)
        return b

    def owner_create(self, service_id, start_local: dt.datetime, resource_id, name="", phone="", note=""):
        svc = self.cfg.get_service(service_id)
        if svc is None:
            raise ValueError("unknown service")
        if resource_id not in svc.resources:
            raise ValueError("this resource does not offer that service")
        minutes = int(svc.duration.get("minutes") or max(svc.duration.get("by_size", {"x": 60}).values()))
        cid = None
        if phone:
            num = rules.normalize_phone(phone)
            if not num:
                raise ValueError("invalid phone number")
            cid = bk.upsert_customer(self.conn, name or "?", num, self.cfg.assistant["default_language"], self.now())
        return bk.owner_create(self.conn, self.cfg, svc, start_local.astimezone(dt.timezone.utc), minutes, resource_id,
                               self.now(), customer_id=cid, note=note)

    def block_time(self, start_local: dt.datetime, end_local: dt.datetime, resource_id=None, reason=""):
        if end_local <= start_local:
            raise ValueError("end must be after start")
        with transaction(self.conn):
            self.conn.execute("INSERT INTO blocks(resource_id, start_utc, end_utc, reason, created_at) VALUES (?,?,?,?,?)",
                              (resource_id or None, to_iso(start_local), to_iso(end_local), reason[:200],
                               to_iso(self.now())))
            audit(self.conn, "owner", "block", "blocks", None, json.dumps({"reason": reason[:100]}))

    def set_paused(self, paused: bool):
        with transaction(self.conn):
            set_setting(self.conn, "automation_paused", "1" if paused else "0")
            audit(self.conn, "owner", "pause" if paused else "resume", "settings")

    def resolve_escalation(self, esc_id):
        with transaction(self.conn):
            row = self.conn.execute("SELECT * FROM escalations WHERE id = ?", (esc_id,)).fetchone()
            if not row:
                raise bk.NotFound(esc_id)
            self.conn.execute("UPDATE escalations SET status = 'resolved', resolved_at = ? WHERE id = ?",
                              (to_iso(self.now()), esc_id))
            if row["conversation_id"]:
                conv = self.conn.execute("SELECT state FROM conversations WHERE id = ?", (row["conversation_id"],)).fetchone()
                if conv:
                    st = json.loads(conv["state"])
                    if st.get("step") == "handoff":
                        st["step"] = "done" if st.get("ref") else "start"
                        st["unclear"] = 0
                        self.conn.execute("UPDATE conversations SET state = ?, status = 'open' WHERE id = ?",
                                          (json.dumps(st), row["conversation_id"]))
            audit(self.conn, "owner", "resolve", "escalation", esc_id)

    # ------------------------------------------------------------------ background jobs
    def run_jobs(self) -> dict:
        now = self.now()
        with transaction(self.conn):
            expired = bk.expire_holds(self.conn, now)
        fu = self.queue_followups()
        stats = ob.process(self.conn, self.cfg, self.sender, now)
        stats.update(expired_holds=expired, followups=fu)
        return stats

    def queue_followups(self) -> int:
        """One follow-up for customers (with reminder consent) whose request ended without a booking:
        their hold expired or the owner declined, and they have nothing else booked."""
        now = self.now()
        cutoff = to_iso(now - dt.timedelta(hours=self.cfg.messaging["followup_after_hours"]))
        oldest = to_iso(now - dt.timedelta(days=7))
        rows = self.conn.execute(
            "SELECT b.*, c.lang FROM bookings b JOIN customers c ON c.id = b.customer_id "
            "WHERE b.status IN ('declined','expired') AND b.updated_at <= ? AND b.updated_at >= ? AND NOT EXISTS ("
            " SELECT 1 FROM bookings x WHERE x.customer_id = b.customer_id AND x.status IN ('pending_owner','confirmed') "
            " AND x.start_utc > ?)", (cutoff, oldest, to_iso(now))).fetchall()
        n = 0
        with transaction(self.conn):
            for b in rows:
                c = self._customer(b["customer_id"])
                svc = self.cfg.get_service(b["service_id"])
                body = t(self.cfg, c["lang"], "msg_followup", business=self.cfg.business["name"],
                         service=svc.name(c["lang"]) if svc else b["service_id"])
                if ob.enqueue(self.conn, self.cfg, kind="followup", recipient=c["phone"], body=body,
                              dedupe_key=f"followup:{c['id']}:{b['id']}", now=now, customer=c,
                              booking_id=b["id"]) == "queued":
                    n += 1
        return n

    def purge(self) -> dict:
        """Data retention: delete old conversations, anonymise long-inactive customers, trim the audit log."""
        r, now = self.cfg.retention, self.now()
        conv_cut = to_iso(now - dt.timedelta(days=r["conversation_days"]))
        cust_cut = to_iso(now - dt.timedelta(days=r["customer_inactive_days"]))
        audit_cut = to_iso(now - dt.timedelta(days=r["audit_days"]))
        with transaction(self.conn):
            c1 = self.conn.execute("DELETE FROM conversations WHERE updated_at < ?", (conv_cut,)).rowcount
            ids = [x["id"] for x in self.conn.execute(
                "SELECT id FROM customers c WHERE anonymized = 0 AND last_seen_at < ? AND NOT EXISTS ("
                "SELECT 1 FROM bookings b WHERE b.customer_id = c.id AND b.end_utc > ?)", (cust_cut, to_iso(now)))]
            for i in ids:
                self.conn.execute("UPDATE customers SET name = 'anonymised', phone = ?, email = NULL, reminder_consent = 0, "
                                  "marketing_consent = 0, anonymized = 1 WHERE id = ?", (f"anon-{i}", i))
                self.conn.execute("UPDATE outbox SET recipient = ?, body = '[removed]' WHERE recipient IN "
                                  "(SELECT phone FROM customers WHERE id = ?) OR booking_id IN "
                                  "(SELECT id FROM bookings WHERE customer_id = ?)", (f"anon-{i}", i, i))
            a = self.conn.execute("DELETE FROM audit WHERE ts < ?", (audit_cut,)).rowcount
            audit(self.conn, "system", "purge", "retention", None,
                  json.dumps({"conversations": c1, "customers": len(ids), "audit": a}))
        return {"conversations": c1, "customers_anonymised": len(ids), "audit_rows": a}

    def export_customer(self, phone: str) -> dict:
        """Everything stored about one customer (GDPR access request)."""
        num = rules.normalize_phone(phone) or phone
        c = self.conn.execute("SELECT * FROM customers WHERE phone = ?", (num,)).fetchone()
        if not c:
            return {}
        bookings = [dict(r) for r in self.conn.execute("SELECT * FROM bookings WHERE customer_id = ?", (c["id"],))]
        convs = [dict(r) for r in self.conn.execute("SELECT * FROM conversations WHERE customer_id = ?", (c["id"],))]
        msgs = [dict(r) for r in self.conn.execute(
            "SELECT m.* FROM messages m JOIN conversations v ON v.id = m.conversation_id WHERE v.customer_id = ?",
            (c["id"],))]
        out = [dict(r) for r in self.conn.execute("SELECT * FROM outbox WHERE recipient = ?", (num,))]
        return {"customer": dict(c), "bookings": bookings, "conversations": convs, "messages": msgs, "outbox": out}


def _eur(x: float) -> str:
    return f"{x:.0f}"
