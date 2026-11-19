"""Replay scripted example conversations against a fresh database with a fixed clock and write
them to Markdown. These are real runs of the code, not hand-written examples; the tests replay
the same scripts."""
from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path

from . import booking as bk
from .assistant import App
from .config import load_config
from .db import Database
from .outbox import TransientError
from .timeutil import UTC, from_iso

ROOT = Path(__file__).resolve().parent.parent
NOW = dt.datetime(2026, 11, 19, 8, 0, tzinfo=UTC)          # Thursday 19 Nov 2026, 09:00 in Zagreb


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += dt.timedelta(**kw)


def fresh_app(config="demo_detailing.json", clock=None, sender=None, tmp=None):
    tmp = Path(tmp or tempfile.mkdtemp(prefix="qb-"))
    cfg = load_config(ROOT / "config" / config)
    db = Database(tmp / "demo.sqlite3")
    db.migrate()
    return App(cfg, db, var_dir=str(tmp), clock=clock or Clock(NOW), sender=sender)


def run_script(app, messages, conversation_id=None):
    out, cid = [], conversation_id
    for m in messages:
        if callable(m):
            note = m(app, cid)
            if note:
                out.append(("note", note))
            continue
        mid = None
        if isinstance(m, tuple):
            m, mid = m
        r = app.handle_message(m, cid, mid)
        cid = r["conversation_id"]
        out.append(("customer", m))
        out.append(("assistant", r["text"] + ("  [duplicate delivery: same reply returned]" if r.get("duplicate") else "")))
    return out, cid


def _owner_confirms(app, cid):
    row = app.conn.execute("SELECT id, ref FROM bookings WHERE conversation_id = ? AND status = 'pending_owner'",
                           (cid,)).fetchone()
    app.owner_confirm(row["id"])
    return f"Owner taps **Confirm** on {row['ref']} in the admin page."


def _someone_takes_first_offer(app, cid):
    st = json.loads(app.conn.execute("SELECT state FROM conversations WHERE id = ?", (cid,)).fetchone()["state"])
    o = st["offers"][0]
    svc = app.cfg.get_service(st["service_id"])
    start, end = from_iso(o["start"]), from_iso(o["end"])
    for rid in svc.resources:              # both bays, so that time is really gone
        bk.owner_create(app.conn, app.cfg, svc, start, int((end - start).total_seconds() // 60), rid, app.now(),
                        note="phone booking")
    return "Meanwhile the owner books both bays at the first offered time for phone customers."


SCRIPTS = [
    ("Croatian: price, free times and a request the owner confirms", "demo_detailing.json", [
        "Bok, koliko košta poliranje za SUV?", "može subota ujutro", "a ponedjeljak u 10?", "1", "Ivan Horvat",
        "091 234 5678", "da", _owner_confirms]),
    ("English: interior cleaning, and the chosen time is taken in the meantime", "demo_detailing.json", [
        "Hi, how much is a deep interior cleaning for a Golf? Friday afternoon would be ideal",
        _someone_takes_first_offer, "1", "1", "My name is Sarah Miller", "+385 98 765 4321", "no"]),
    ("Wrong dates and times are questioned, not guessed", "demo_detailing.json", [
        "Trebam pranje auta, karavan", "31.02. u 10", "15.11.", "u 25:00", "sutra u 14"]),
    ("Cleaning company: estimate from floor area", "demo_cleaning.json", [
        "Dobar dan, trebam generalno čišćenje stana od 70 m2 iduće srijede", "2", "Zovem se Maja Kovač",
        "098 111 2233", "ne"]),
    ("Complaint goes straight to the owner", "demo_detailing.json", [
        "Jučer ste mi polirali auto i ima ogrebotine, nisam zadovoljan", "halo?"]),
    ("Duplicate delivery of the same message", "demo_detailing.json", [
        ("Koliko košta keramička zaštita za mali auto?", "m-1"), ("1", "m-2"), ("1", "m-2")]),
    ("Not understood three times: handed over instead of guessing", "demo_detailing.json", [
        "asdf", "hmm ?", "???"]),
]


def _manage_script():
    """Cancel and reschedule from a new conversation, using reference + phone."""
    app = fresh_app()
    lines, cid = run_script(app, ["Pranje za mali auto, ponedjeljak u 9", "1", "Ana Demo", "099 000 1000", "da",
                                  _owner_confirms])
    ref = app.conn.execute("SELECT ref FROM bookings WHERE conversation_id = ?", (cid,)).fetchone()["ref"]
    more, _ = run_script(app, [f"Trebam pomaknuti termin {ref}, broj 099 000 1000", "utorak u 13", "1"])
    more2, _ = run_script(app, [f"Želim otkazati {ref}, mob 099 000 1000"])
    return lines + [("note", "Later, from a new chat:")] + more + [("note", "And later again:")] + more2


def _outage_script():
    """The message provider is down: messages are retried with backoff and then escalated."""
    class Down:
        name = "down"

        def send(self, *a, **k):
            raise TransientError("provider timeout (simulated)")
    clock = Clock(NOW)
    app = fresh_app(clock=clock, sender=Down())
    lines, cid = run_script(app, ["Pranje za mali auto, ponedjeljak u 9", "1", "Ana Demo", "099 000 1000", "da",
                                  _owner_confirms])
    for _ in range(8):
        app.run_jobs()
        clock.advance(hours=1)
    rows = app.conn.execute("SELECT kind, status, attempts, last_error FROM outbox ORDER BY id").fetchall()
    esc = app.conn.execute("SELECT reason, excerpt FROM escalations").fetchall()
    note = ("Simulated provider outage: " + "; ".join(f"{r['kind']} -> {r['status']} after {r['attempts']} attempts"
                                                         for r in rows if r["kind"] != "reminder")
            + f". Escalations raised for the owner: {len(esc)}.")
    return lines + [("note", note)]


def write_transcripts(path: Path) -> str:
    parts = ["# Example conversations", "",
             "Generated by `python -m quotebook transcripts` from the demo configurations with a fixed clock "
             "(Thursday 19 November 2026, 09:00 Zagreb time). Every line below is the actual output of the code. "
             "The businesses, people and phone numbers are fictional.", ""]
    scripts = [(title, lambda c=cfg, m=msgs: run_script(fresh_app(c), m)[0]) for title, cfg, msgs in SCRIPTS]
    scripts.append(("Reschedule and cancel with the booking reference", _manage_script))
    scripts.append(("Message provider outage", _outage_script))
    for title, fn in scripts:
        parts += [f"## {title}", ""]
        for who, text in fn():
            if who == "note":
                parts += [f"*{text}*", ""]
            else:
                label = "**Customer:**" if who == "customer" else "**Assistant:**"
                body = text.replace("\n", "  \n")
                parts += [f"{label} {body}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")
    return str(path)
