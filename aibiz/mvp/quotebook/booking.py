"""Booking lifecycle. A slot is first *held* for a few minutes while the customer gives contact
details, then becomes *pending_owner* (default) or *confirmed*. Nothing tells the customer a
booking is confirmed unless the database row says 'confirmed'.

    held -> pending_owner -> confirmed -> completed
      |          |              |
      v          v              v
   expired    declined       cancelled
"""
from __future__ import annotations

import datetime as dt
import json
import secrets
import sqlite3

from . import availability as av
from .db import audit, transaction
from .timeutil import from_iso, to_iso

REF_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class BookingError(Exception):
    code = "booking_error"


class SlotTaken(BookingError):
    code = "slot_taken"


class OutsideHours(BookingError):
    code = "outside_hours"


class HoldExpired(BookingError):
    code = "hold_expired"


class InvalidTransition(BookingError):
    code = "invalid_transition"


class NotFound(BookingError):
    code = "not_found"


def new_ref() -> str:
    return "QB-" + "".join(secrets.choice(REF_ALPHABET) for _ in range(5))


def get(conn, booking_id=None, ref=None):
    if ref:
        row = conn.execute("SELECT * FROM bookings WHERE ref = ?", (ref.upper(),)).fetchone()
    else:
        row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not row:
        raise NotFound(ref or booking_id)
    return row


def expire_holds(conn, now: dt.datetime) -> int:
    cur = conn.execute("UPDATE bookings SET status = 'expired', updated_at = ? "
                       "WHERE status = 'held' AND hold_expires_utc <= ?", (to_iso(now), to_iso(now)))
    return cur.rowcount


def _insert(conn, **f):
    cols = ", ".join(f)
    conn.execute(f"INSERT INTO bookings({cols}) VALUES ({', '.join('?' * len(f))})", tuple(f.values()))
    return conn.execute("SELECT * FROM bookings WHERE ref = ?", (f["ref"],)).fetchone()


def hold(conn, cfg, service, slot: av.Slot, now: dt.datetime, *, idempotency_key: str, price=(None, None),
         details=None, conversation_id=None):
    """Reserve a slot for cfg.booking['hold_minutes']. Repeating the same idempotency key returns the
    same hold instead of a second one (duplicate clicks, retried requests)."""
    with transaction(conn):
        row = conn.execute("SELECT * FROM bookings WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
        if row:
            return row
        expire_holds(conn, now)
        if not av.within_hours(cfg, slot.start, slot.end):
            raise OutsideHours()
        if slot.start < now + dt.timedelta(hours=cfg.booking["min_notice_hours"]):
            raise SlotTaken("too soon")
        if not av.is_free(conn, slot.resource_id, slot.start, slot.end, now, cfg.booking["buffer_minutes"]):
            raise SlotTaken()
        ts = to_iso(now)
        try:
            row = _insert(conn, ref=new_ref(), service_id=service.id, resource_id=slot.resource_id,
                          start_utc=to_iso(slot.start), end_utc=to_iso(slot.end), status="held",
                          price_low=price[0], price_high=price[1], details=json.dumps(details or {}),
                          hold_expires_utc=to_iso(now + dt.timedelta(minutes=cfg.booking["hold_minutes"])),
                          idempotency_key=idempotency_key, conversation_id=conversation_id, source="assistant",
                          created_at=ts, updated_at=ts)
        except sqlite3.IntegrityError as e:
            if "overlaps" in str(e):
                raise SlotTaken() from e
            raise
        audit(conn, "assistant", "hold", "booking", row["id"], json.dumps({"slot": slot.key()}))
        return row


def submit(conn, cfg, booking_id: int, customer_id: int, now: dt.datetime, actor: str = "assistant"):
    """Customer gave details: the hold becomes a request for the owner (or confirmed, if the
    business switched owner confirmation off)."""
    with transaction(conn):
        b = get(conn, booking_id)
        if b["status"] == "expired":
            raise HoldExpired()
        if b["status"] != "held":
            raise InvalidTransition(b["status"])
        if from_iso(b["hold_expires_utc"]) <= now:
            raise HoldExpired()          # expire_holds() marks it on the next write
        status = "pending_owner" if cfg.booking["require_owner_confirmation"] else "confirmed"
        conn.execute("UPDATE bookings SET status = ?, customer_id = ?, hold_expires_utc = NULL, updated_at = ? "
                     "WHERE id = ?", (status, customer_id, to_iso(now), booking_id))
        audit(conn, actor, "submit", "booking", booking_id, json.dumps({"status": status}))
        return get(conn, booking_id)


def _transition(conn, booking_id, allowed_from, to, now, actor, note=""):
    with transaction(conn):
        b = get(conn, booking_id)
        if b["status"] not in allowed_from:
            raise InvalidTransition(f"{b['status']} -> {to}")
        conn.execute("UPDATE bookings SET status = ?, updated_at = ? WHERE id = ?", (to, to_iso(now), booking_id))
        audit(conn, actor, to, "booking", booking_id, json.dumps({"from": b["status"], "note": note}))
        return get(conn, booking_id)


def confirm(conn, booking_id, now, actor="owner"):
    return _transition(conn, booking_id, ("pending_owner",), "confirmed", now, actor)


def decline(conn, booking_id, now, actor="owner", note=""):
    return _transition(conn, booking_id, ("pending_owner", "held"), "declined", now, actor, note)


def cancel(conn, booking_id, now, actor="customer", note=""):
    return _transition(conn, booking_id, ("held", "pending_owner", "confirmed"), "cancelled", now, actor, note)


def complete(conn, booking_id, now, actor="owner"):
    return _transition(conn, booking_id, ("confirmed",), "completed", now, actor)


def reschedule(conn, cfg, booking_id, new_slot: av.Slot, now, actor="customer"):
    """Move a booking atomically: the new time is checked and taken in the same transaction, so the
    customer never ends up with two bookings or none."""
    with transaction(conn):
        b = get(conn, booking_id)
        if b["status"] not in ("pending_owner", "confirmed"):
            raise InvalidTransition(b["status"])
        expire_holds(conn, now)
        if actor != "owner":
            if not av.within_hours(cfg, new_slot.start, new_slot.end):
                raise OutsideHours()
            if new_slot.start < now + dt.timedelta(hours=cfg.booking["min_notice_hours"]):
                raise SlotTaken("too soon")
        if not av.is_free(conn, new_slot.resource_id, new_slot.start, new_slot.end, now,
                          cfg.booking["buffer_minutes"], exclude_booking_id=booking_id):
            raise SlotTaken()
        status = "confirmed" if actor == "owner" or not cfg.booking["require_owner_confirmation"] else "pending_owner"
        try:
            conn.execute("UPDATE bookings SET start_utc = ?, end_utc = ?, resource_id = ?, status = ?, updated_at = ? "
                         "WHERE id = ?", (to_iso(new_slot.start), to_iso(new_slot.end), new_slot.resource_id, status,
                                          to_iso(now), booking_id))
        except sqlite3.IntegrityError as e:
            raise SlotTaken() from e
        audit(conn, actor, "reschedule", "booking", booking_id,
              json.dumps({"from": b["start_utc"], "to": to_iso(new_slot.start)}))
        return get(conn, booking_id)


def owner_create(conn, cfg, service, start: dt.datetime, minutes: int, resource_id: str, now, *, customer_id=None,
                 note="", price=(None, None)):
    """Owner books a job by hand (phone, walk-in). Owners may book outside opening hours or at short
    notice, but never on top of another booking."""
    end = start + dt.timedelta(minutes=minutes)
    with transaction(conn):
        expire_holds(conn, now)
        if not av.is_free(conn, resource_id, start, end, now, 0):
            raise SlotTaken()
        ts = to_iso(now)
        try:
            row = _insert(conn, ref=new_ref(), customer_id=customer_id, service_id=service.id, resource_id=resource_id,
                          start_utc=to_iso(start), end_utc=to_iso(end), status="confirmed", price_low=price[0],
                          price_high=price[1], details=json.dumps({"note": note}), source="owner",
                          created_at=ts, updated_at=ts)
        except sqlite3.IntegrityError as e:
            raise SlotTaken() from e
        audit(conn, "owner", "create", "booking", row["id"])
        return row


def upsert_customer(conn, name: str, phone: str, lang: str, now, *, email=None, reminder_consent=None,
                    marketing_consent=None) -> int:
    ts = to_iso(now)
    with transaction(conn):
        row = conn.execute("SELECT id FROM customers WHERE phone = ?", (phone,)).fetchone()
        if row:
            cid = row["id"]
            conn.execute("UPDATE customers SET name = ?, lang = ?, email = COALESCE(?, email), last_seen_at = ?, "
                         "anonymized = 0 WHERE id = ?", (name, lang, email, ts, cid))
        else:
            cur = conn.execute("INSERT INTO customers(name, phone, email, lang, created_at, last_seen_at) "
                               "VALUES (?,?,?,?,?,?)", (name, phone, email, lang, ts, ts))
            cid = cur.lastrowid
        if reminder_consent is not None:
            conn.execute("UPDATE customers SET reminder_consent = ?, consent_updated_at = ? WHERE id = ?",
                         (int(bool(reminder_consent)), ts, cid))
            audit(conn, "customer", "consent", "customer", cid, json.dumps({"reminders": bool(reminder_consent)}))
        if marketing_consent is not None:
            conn.execute("UPDATE customers SET marketing_consent = ?, consent_updated_at = ? WHERE id = ?",
                         (int(bool(marketing_consent)), ts, cid))
        return cid
