"""Outgoing messages: queued in the database (the outbox), then delivered by a sender with
retries. Queuing and delivery are separate so a crash or a provider outage never loses a message
and never sends one twice from our side (each message has a unique dedupe key).

Consent rules enforced here:
  * reminders and follow-ups only to customers who said yes to reminders;
  * rebooking/marketing messages only with marketing consent (ZEK Art. 50 for consumers);
  * non-urgent kinds wait for the end of quiet hours.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import random
from pathlib import Path

from .db import audit, transaction
from .timeutil import from_iso, to_iso

log = logging.getLogger("quotebook.outbox")

TRANSACTIONAL = {"confirmed", "declined", "cancelled", "rescheduled", "owner_new"}
NEEDS_REMINDER_CONSENT = {"reminder", "followup"}
NEEDS_MARKETING_CONSENT = {"rebook", "review"}
QUIET_HOURS_APPLY = NEEDS_REMINDER_CONSENT | NEEDS_MARKETING_CONSENT


class TransientError(Exception):
    """Provider down, timeout, rate limited: try again later."""


class PermanentError(Exception):
    """Bad number, blocked recipient, rejected content: do not retry."""


class DryRunSender:
    """The only sender shipped. Writes each message as one JSON line to a local file; nothing
    leaves the machine."""
    name = "dryrun"

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, channel: str, recipient: str, body: str, dedupe_key: str) -> str:
        rec = {"channel": channel, "to": recipient, "body": body, "key": dedupe_key}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return "dryrun-" + dedupe_key


def make_sender(cfg, env, var_dir):
    if cfg.messaging.get("send_enabled") or env.allow_live_send:
        raise RuntimeError("Live sending is not implemented in this MVP. Connecting WhatsApp, SMS or e-mail "
                           "needs the client's own approved account and your explicit approval (see docs/DEPLOY.md).")
    return DryRunSender(Path(var_dir) / "outbox_dryrun.jsonl")


def in_quiet_hours(cfg, when_utc: dt.datetime) -> bool:
    m = cfg.messaging
    qs = dt.time.fromisoformat(m["quiet_start"])
    qe = dt.time.fromisoformat(m["quiet_end"])
    t = when_utc.astimezone(cfg.tz).time()
    return (t >= qs or t < qe) if qs > qe else (qs <= t < qe)


def next_allowed(cfg, when_utc: dt.datetime) -> dt.datetime:
    """First moment at or after when_utc outside quiet hours."""
    if not in_quiet_hours(cfg, when_utc):
        return when_utc
    qe = dt.time.fromisoformat(cfg.messaging["quiet_end"])
    lt = when_utc.astimezone(cfg.tz)
    day = lt.date() if lt.time() < qe else lt.date() + dt.timedelta(days=1)
    return dt.datetime.combine(day, qe, tzinfo=cfg.tz).astimezone(dt.timezone.utc)


def enqueue(conn, cfg, *, kind: str, recipient: str, body: str, dedupe_key: str, now: dt.datetime,
            customer=None, booking_id=None, send_after: dt.datetime = None, channel: str = None) -> str:
    """Queue a message. Returns 'queued', 'duplicate' or the reason it was not queued."""
    if kind in NEEDS_REMINDER_CONSENT and not (customer and customer["reminder_consent"]):
        return "no_consent"
    if kind in NEEDS_MARKETING_CONSENT and not (customer and customer["marketing_consent"]):
        return "no_consent"
    if customer is not None and customer["anonymized"]:
        return "anonymized"
    when = send_after or now
    if kind in QUIET_HOURS_APPLY:
        when = next_allowed(cfg, when)
    ts = to_iso(now)
    cur = conn.execute(
        "INSERT INTO outbox(dedupe_key, kind, channel, recipient, body, booking_id, status, attempts, "
        "next_attempt_utc, created_at, updated_at) VALUES (?,?,?,?,?,?,'pending',0,?,?,?) "
        "ON CONFLICT(dedupe_key) DO NOTHING",
        (dedupe_key, kind, channel or cfg.messaging["channel"], recipient, body, booking_id, to_iso(when), ts, ts))
    return "queued" if cur.rowcount else "duplicate"


def skip_for_booking(conn, booking_id: int, kinds=("reminder",), now=None):
    """Cancel queued messages that no longer make sense (e.g. a reminder after a cancellation)."""
    q = ",".join("?" * len(kinds))
    conn.execute(f"UPDATE outbox SET status = 'skipped', updated_at = ? WHERE booking_id = ? AND status = 'pending' "
                 f"AND kind IN ({q})", (to_iso(now) if now else "", booking_id, *kinds))


def backoff(attempt: int, base_s: float = 30.0, cap_s: float = 3600.0, rng=random) -> float:
    """Exponential backoff with +-25% jitter: ~30 s, 1 min, 2 min, 4 min ... capped at 1 h."""
    d = min(base_s * (2 ** (attempt - 1)), cap_s)
    return d * (0.75 + 0.5 * rng.random())


def recover_stuck(conn, now: dt.datetime, stale_minutes: int = 10) -> int:
    """A worker that crashed mid-send leaves rows in 'sending'. Put them back in the queue.
    (At-least-once: if the provider did accept the message, the customer may get it twice;
    real providers' idempotency keys should be used when a live sender is added.)"""
    cutoff = to_iso(now - dt.timedelta(minutes=stale_minutes))
    cur = conn.execute("UPDATE outbox SET status = 'pending', updated_at = ? WHERE status = 'sending' AND updated_at <= ?",
                       (to_iso(now), cutoff))
    return cur.rowcount


def process(conn, cfg, sender, now: dt.datetime, batch: int = 20, max_consecutive_transient: int = 3,
            rng=random) -> dict:
    """Deliver due messages. Stops early when the provider looks down (several transient errors
    in a row) so we do not hammer it; the rest wait for the next run."""
    stats = {"sent": 0, "retry": 0, "dead": 0, "deferred": 0}
    max_attempts = int(cfg.messaging["max_attempts"])
    with transaction(conn):
        recover_stuck(conn, now)
        rows = conn.execute("SELECT * FROM outbox WHERE status = 'pending' AND next_attempt_utc <= ? "
                            "ORDER BY next_attempt_utc, id LIMIT ?", (to_iso(now), batch)).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            conn.execute(f"UPDATE outbox SET status = 'sending', updated_at = ? WHERE id IN ({','.join('?' * len(ids))})",
                         (to_iso(now), *ids))
    streak = 0
    for i, r in enumerate(rows):
        if streak >= max_consecutive_transient:
            with transaction(conn):
                conn.execute(f"UPDATE outbox SET status = 'pending', updated_at = ? "
                             f"WHERE id IN ({','.join('?' * len(rows[i:]))})",
                             (to_iso(now), *[x["id"] for x in rows[i:]]))
            stats["deferred"] += len(rows) - i
            break
        if r["kind"] in QUIET_HOURS_APPLY and in_quiet_hours(cfg, now):
            with transaction(conn):
                conn.execute("UPDATE outbox SET status = 'pending', next_attempt_utc = ?, updated_at = ? WHERE id = ?",
                             (to_iso(next_allowed(cfg, now)), to_iso(now), r["id"]))
            stats["deferred"] += 1
            continue
        try:
            pid = sender.send(r["channel"], r["recipient"], r["body"], r["dedupe_key"])
        except PermanentError as e:
            streak = 0
            _dead(conn, r, now, f"permanent: {e}")
            stats["dead"] += 1
            continue
        except Exception as e:  # TransientError and anything unexpected are retried
            streak += 1
            attempts = r["attempts"] + 1
            if attempts >= max_attempts:
                _dead(conn, r, now, f"gave up after {attempts} attempts: {e}")
                stats["dead"] += 1
            else:
                nxt = now + dt.timedelta(seconds=backoff(attempts, rng=rng))
                with transaction(conn):
                    conn.execute("UPDATE outbox SET status = 'pending', attempts = ?, next_attempt_utc = ?, "
                                 "last_error = ?, updated_at = ? WHERE id = ?",
                                 (attempts, to_iso(nxt), str(e)[:300], to_iso(now), r["id"]))
                stats["retry"] += 1
            log.warning("send failed for outbox %s (attempt %s): %s", r["id"], attempts, e)
            continue
        streak = 0
        with transaction(conn):
            conn.execute("UPDATE outbox SET status = 'sent', attempts = attempts + 1, provider_id = ?, updated_at = ? "
                         "WHERE id = ?", (pid, to_iso(now), r["id"]))
        stats["sent"] += 1
    return stats


def _dead(conn, r, now, why):
    with transaction(conn):
        conn.execute("UPDATE outbox SET status = 'dead', attempts = attempts + 1, last_error = ?, updated_at = ? "
                     "WHERE id = ?", (why[:300], to_iso(now), r["id"]))
        conn.execute("INSERT INTO escalations(booking_id, reason, excerpt, created_at) VALUES (?,?,?,?)",
                     (r["booking_id"], "message_failed", f"{r['kind']} to {mask(r['recipient'])}: {why}"[:300],
                      to_iso(now)))
        audit(conn, "system", "message_dead", "outbox", r["id"], json.dumps({"why": why[:200]}))


def retry_dead(conn, outbox_id: int, now: dt.datetime):
    with transaction(conn):
        conn.execute("UPDATE outbox SET status = 'pending', attempts = 0, next_attempt_utc = ?, updated_at = ? "
                     "WHERE id = ? AND status = 'dead'", (to_iso(now), to_iso(now), outbox_id))
        audit(conn, "owner", "retry_message", "outbox", outbox_id)


def mask(s: str) -> str:
    """Hide most of a phone number or e-mail address for logs and the admin list."""
    if "@" in s:
        u, _, d = s.partition("@")
        return (u[:1] + "***@" + d) if u else "***@" + d
    return (s[:4] + "*" * max(len(s) - 7, 0) + s[-3:]) if len(s) > 7 else "***"
