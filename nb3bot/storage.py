"""Persistent state (SQLite) and the append-only audit log (JSON lines).

The database survives crashes and restarts. An order intent is written BEFORE the order is sent, so
after a restart the bot knows a signal was already acted on and asks the broker what happened instead
of sending it again.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL, updated TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY, session INTEGER, bar INTEGER, direction INTEGER,
    payload TEXT, created TEXT, UNIQUE(session));
CREATE TABLE IF NOT EXISTS intents (tag TEXT PRIMARY KEY, session INTEGER UNIQUE, status TEXT, payload TEXT,
    broker_order_id TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, session INTEGER UNIQUE, tag TEXT, payload TEXT,
    pnl REAL, r_multiple REAL, created TEXT);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, ts TEXT, level TEXT, kind TEXT, payload TEXT);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        try:
            self.db.close()
        except Exception:  # noqa: BLE001 - closing twice or at interpreter exit is harmless
            pass

    def __del__(self):
        self.close()

    # ------------------------------------------------------------------ key/value
    def put(self, k: str, v) -> None:
        with self._lock:
            self.db.execute("INSERT INTO kv(k, v, updated) VALUES(?,?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v, "
                            "updated=excluded.updated", (k, json.dumps(v, default=str), _now()))

    def get(self, k: str, default=None):
        with self._lock:
            row = self.db.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    # ------------------------------------------------------------------ signals / intents / trades
    def record_signal(self, sig: dict) -> bool:
        """False if a signal for this session already exists (duplicate protection)."""
        with self._lock:
            try:
                self.db.execute("INSERT INTO signals(session, bar, direction, payload, created) VALUES(?,?,?,?,?)",
                                (sig["session"], sig["bar"], sig["direction"], json.dumps(sig), _now()))
                return True
            except sqlite3.IntegrityError:
                return False

    def create_intent(self, tag: str, session: int, payload: dict) -> bool:
        """Persist the order intent before sending. False if this session already has one."""
        with self._lock:
            try:
                self.db.execute("INSERT INTO intents(tag, session, status, payload, created, updated) VALUES(?,?,?,?,?,?)",
                                (tag, session, "created", json.dumps(payload, default=str), _now(), _now()))
                return True
            except sqlite3.IntegrityError:
                return False

    def update_intent(self, tag: str, status: str, broker_order_id: str | None = None, **extra) -> None:
        with self._lock:
            row = self.db.execute("SELECT payload FROM intents WHERE tag=?", (tag,)).fetchone()
            payload = json.loads(row[0]) if row else {}
            payload.update(extra)
            self.db.execute("UPDATE intents SET status=?, broker_order_id=COALESCE(?, broker_order_id), payload=?, "
                            "updated=? WHERE tag=?", (status, broker_order_id, json.dumps(payload, default=str), _now(), tag))

    def intent_for_session(self, session: int) -> dict | None:
        with self._lock:
            row = self.db.execute("SELECT tag, status, payload, broker_order_id FROM intents WHERE session=?",
                                  (session,)).fetchone()
        if not row:
            return None
        return {"tag": row[0], "status": row[1], "payload": json.loads(row[2]), "broker_order_id": row[3]}

    def open_intents(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT tag, session, status, payload, broker_order_id FROM intents WHERE status NOT IN "
                                   "('closed', 'skipped', 'rejected', 'failed_flat')").fetchall()
        return [{"tag": r[0], "session": r[1], "status": r[2], "payload": json.loads(r[3]), "broker_order_id": r[4]}
                for r in rows]

    def record_trade(self, session: int, tag: str, payload: dict, pnl: float, r: float) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO trades(session, tag, payload, pnl, r_multiple, created) VALUES(?,?,?,?,?,?)",
                            (session, tag, json.dumps(payload, default=str), pnl, r, _now()))

    def trades(self, limit: int = 10000) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT session, tag, payload, pnl, r_multiple FROM trades ORDER BY session DESC LIMIT ?",
                                   (limit,)).fetchall()
        return [{"session": r[0], "tag": r[1], **json.loads(r[2]), "pnl": r[3], "r_multiple": r[4]} for r in rows]

    def traded_session(self, session: int) -> bool:
        with self._lock:
            a = self.db.execute("SELECT 1 FROM intents WHERE session=? AND status NOT IN ('skipped', 'rejected')",
                                (session,)).fetchone()
        return a is not None

    # ------------------------------------------------------------------ events
    def event(self, level: str, kind: str, payload: dict) -> None:
        with self._lock:
            self.db.execute("INSERT INTO events(ts, level, kind, payload) VALUES(?,?,?,?)",
                            (_now(), level, kind, json.dumps(payload, default=str)))

    def recent_events(self, n: int = 100) -> list[dict]:
        with self._lock:
            rows = self.db.execute("SELECT ts, level, kind, payload FROM events ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return [{"ts": r[0], "level": r[1], "kind": r[2], **json.loads(r[3])} for r in rows]


class Audit:
    """Append-only JSON-lines audit log (one file per UTC day) mirrored into the database events table."""

    def __init__(self, log_dir: str | Path, store: Store | None = None, echo: bool = True):
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store = store
        self.echo = echo
        self._lock = threading.Lock()

    def log(self, kind: str, level: str = "INFO", **payload) -> None:
        ts = datetime.now(timezone.utc)
        rec = {"ts": ts.isoformat(timespec="milliseconds"), "level": level, "kind": kind, **payload}
        line = json.dumps(rec, default=str)
        with self._lock:
            with open(self.dir / f"audit-{ts:%Y%m%d}.jsonl", "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        if self.store is not None:
            self.store.event(level, kind, payload)
        if self.echo:
            print(f"[{rec['ts'][11:23]}] {level:<5} {kind}: " + ", ".join(f"{k}={v}" for k, v in payload.items())[:400],
                  flush=True)
