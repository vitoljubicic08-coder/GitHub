"""Simulated data for the demo: fictional customers (phone numbers in an unassigned-looking
+385 99 000 xxxx range, '.invalid' e-mail domain) and a week of bookings."""
from __future__ import annotations

import datetime as dt
import random

from . import availability as av
from . import booking as bk
from .db import transaction
from .timeutil import to_iso

NAMES = ["Ana Demo", "Marko Test", "Ivana Primjer", "Luka Fiktivni", "Petra Uzorak", "Tomislav Simulacija",
         "Maja Proba", "Josip Ogledni"]


def seed(app, n_bookings: int = 10, rng_seed: int = 42) -> dict:
    rng = random.Random(rng_seed)
    conn, cfg, now = app.conn, app.cfg, app.now()
    with transaction(conn):
        if conn.execute("SELECT COUNT(*) FROM customers WHERE phone LIKE '+38599000%'").fetchone()[0]:
            return {"seeded": False, "reason": "demo data already present"}
    custs = []
    for i, name in enumerate(NAMES):
        custs.append(bk.upsert_customer(conn, name, f"+38599000{1000 + i}", "hr" if i % 3 else "en", now,
                                        email=f"demo{i}@example.invalid", reminder_consent=bool(i % 2)))
    made = 0
    today = now.astimezone(cfg.tz).date()
    for k in range(1, 15):
        if made >= n_bookings:
            break
        day = today + dt.timedelta(days=k)
        svc = rng.choice(cfg.services)
        size = rng.choice(list(cfg.sizes)) if cfg.sizes else ""
        from .pricing import estimate
        est = estimate(svc, cfg.measure, size, rng.choice([45, 60, 75, 90]), cfg.booking["slot_step_minutes"])
        slots = av.day_slots(conn, cfg, svc, est.minutes, day, now)
        if not slots:
            continue
        s = rng.choice(slots[: max(1, len(slots) // 2)])
        b = bk.owner_create(conn, cfg, svc, s.start, est.minutes, s.resource_id, now, customer_id=rng.choice(custs),
                            note="simulated", price=(est.low, est.high))
        if rng.random() < 0.35:   # some stay as requests waiting for the owner
            with transaction(conn):
                conn.execute("UPDATE bookings SET status = 'pending_owner', source = 'assistant' WHERE id = ?", (b["id"],))
        made += 1
    with transaction(conn):
        conn.execute("INSERT INTO escalations(conversation_id, reason, excerpt, created_at) VALUES (?,?,?,?)",
                     (None, "human_requested", "(simulated) Možete li me nazvati oko većeg posla za tvrtku?",
                      to_iso(now)))
    return {"seeded": True, "customers": len(custs), "bookings": made}
