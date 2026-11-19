"""SQLite storage: schema, migrations, transactions with retry, backup and restore.

Double bookings are blocked twice: the booking service checks for overlaps inside a
BEGIN IMMEDIATE transaction (SQLite then lets only one writer in at a time), and database
triggers reject any insert or update that would overlap an active booking on the same resource,
whatever code path wrote it.
"""
from __future__ import annotations

import contextlib
import logging
import random
import shutil
import sqlite3
import time
from pathlib import Path

from .timeutil import to_iso, utcnow

log = logging.getLogger("quotebook.db")

ACTIVE = ("held", "pending_owner", "confirmed")

# Each entry upgrades the schema by one version. Never edit a released entry; append a new one.
MIGRATIONS = [
    # v1
    """
    CREATE TABLE customers(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT NOT NULL UNIQUE,
        email TEXT,
        lang TEXT NOT NULL DEFAULT 'hr',
        reminder_consent INTEGER NOT NULL DEFAULT 0,
        marketing_consent INTEGER NOT NULL DEFAULT 0,
        consent_updated_at TEXT,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        anonymized INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE conversations(
        id TEXT PRIMARY KEY,
        channel TEXT NOT NULL,
        lang TEXT NOT NULL,
        state TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        customer_id INTEGER REFERENCES customers(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE messages(
        id INTEGER PRIMARY KEY,
        conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
        direction TEXT NOT NULL CHECK(direction IN ('in','out')),
        text TEXT NOT NULL,
        external_id TEXT,
        reply_to INTEGER,
        created_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX messages_inbound_dedupe ON messages(conversation_id, external_id)
        WHERE direction = 'in' AND external_id IS NOT NULL;
    CREATE TABLE bookings(
        id INTEGER PRIMARY KEY,
        ref TEXT NOT NULL UNIQUE,
        customer_id INTEGER REFERENCES customers(id),
        service_id TEXT NOT NULL,
        resource_id TEXT NOT NULL,
        start_utc TEXT NOT NULL,
        end_utc TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN
            ('held','pending_owner','confirmed','declined','cancelled','expired','completed')),
        price_low REAL,
        price_high REAL,
        details TEXT NOT NULL DEFAULT '{}',
        hold_expires_utc TEXT,
        idempotency_key TEXT UNIQUE,
        conversation_id TEXT,
        source TEXT NOT NULL DEFAULT 'assistant',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK(end_utc > start_utc)
    );
    CREATE INDEX bookings_resource_time ON bookings(resource_id, start_utc);
    CREATE TABLE blocks(
        id INTEGER PRIMARY KEY,
        resource_id TEXT,
        start_utc TEXT NOT NULL,
        end_utc TEXT NOT NULL,
        reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        CHECK(end_utc > start_utc)
    );
    CREATE TABLE outbox(
        id INTEGER PRIMARY KEY,
        dedupe_key TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL,
        channel TEXT NOT NULL,
        recipient TEXT NOT NULL,
        body TEXT NOT NULL,
        booking_id INTEGER,
        status TEXT NOT NULL CHECK(status IN ('pending','sending','sent','dead','skipped')),
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_utc TEXT NOT NULL,
        last_error TEXT,
        provider_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX outbox_due ON outbox(status, next_attempt_utc);
    CREATE TABLE escalations(
        id INTEGER PRIMARY KEY,
        conversation_id TEXT,
        booking_id INTEGER,
        reason TEXT NOT NULL,
        excerpt TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
        created_at TEXT NOT NULL,
        resolved_at TEXT
    );
    CREATE TABLE audit(
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        actor TEXT NOT NULL,
        action TEXT NOT NULL,
        entity TEXT NOT NULL,
        entity_id TEXT,
        details TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);

    -- Last line of defence against double bookings: no two active bookings may overlap on
    -- one resource. An expired hold (hold_expires_utc in the past) no longer blocks the slot.
    CREATE TRIGGER bookings_no_overlap_insert BEFORE INSERT ON bookings
    WHEN NEW.status IN ('held','pending_owner','confirmed') AND EXISTS (
        SELECT 1 FROM bookings b
        WHERE b.resource_id = NEW.resource_id
          AND b.status IN ('held','pending_owner','confirmed')
          AND NOT (b.status = 'held' AND b.hold_expires_utc <= strftime('%Y-%m-%dT%H:%M:%SZ','now'))
          AND b.start_utc < NEW.end_utc AND NEW.start_utc < b.end_utc)
    BEGIN SELECT RAISE(ABORT, 'booking overlaps an existing booking'); END;

    CREATE TRIGGER bookings_no_overlap_update BEFORE UPDATE OF start_utc, end_utc, resource_id, status ON bookings
    WHEN NEW.status IN ('held','pending_owner','confirmed') AND EXISTS (
        SELECT 1 FROM bookings b
        WHERE b.id != NEW.id
          AND b.resource_id = NEW.resource_id
          AND b.status IN ('held','pending_owner','confirmed')
          AND NOT (b.status = 'held' AND b.hold_expires_utc <= strftime('%Y-%m-%dT%H:%M:%SZ','now'))
          AND b.start_utc < NEW.end_utc AND NEW.start_utc < b.end_utc)
    BEGIN SELECT RAISE(ABORT, 'booking overlaps an existing booking'); END;
    """,
]
SCHEMA_VERSION = len(MIGRATIONS)


class Database:
    def __init__(self, path, busy_timeout_ms: int = 5000):
        self.path = str(path)
        self.busy_timeout_ms = busy_timeout_ms
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self.busy_timeout_ms / 1000, isolation_level=None,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    # ------------------------------------------------------------------ schema
    def version(self, conn) -> int:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL)")
        row = conn.execute("SELECT version FROM schema_version").fetchone()
        return row[0] if row else 0

    def migrate(self, backup_dir=None) -> int:
        """Apply pending migrations. An existing database is backed up first."""
        conn = self.connect()
        try:
            v = self.version(conn)
            if v > SCHEMA_VERSION:
                raise RuntimeError(f"database schema v{v} is newer than this code (v{SCHEMA_VERSION}); "
                                   "roll the code forward or restore a matching backup")
            if v == SCHEMA_VERSION:
                return v
            if v > 0 and backup_dir:
                self.backup(Path(backup_dir) / f"pre-migrate-v{v}-{int(time.time())}.sqlite3")
            for i in range(v, SCHEMA_VERSION):
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for stmt in _split_sql(MIGRATIONS[i]):
                        conn.execute(stmt)
                    conn.execute("DELETE FROM schema_version")
                    conn.execute("INSERT INTO schema_version(version) VALUES (?)", (i + 1,))
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                log.info("migrated database to v%d", i + 1)
            return SCHEMA_VERSION
        finally:
            conn.close()

    # ------------------------------------------------------------------ backup / restore
    def backup(self, dest) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        src = self.connect()
        try:
            out = sqlite3.connect(str(dest))
            with out:
                src.backup(out)
            out.close()
        finally:
            src.close()
        return dest

    def restore(self, src) -> None:
        """Replace the database with a backup file (stop the server first)."""
        src = Path(src)
        if not src.exists():
            raise FileNotFoundError(src)
        check = sqlite3.connect(str(src))
        try:
            ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            check.close()
        if ok != "ok":
            raise RuntimeError(f"backup {src} failed the integrity check: {ok}")
        for suffix in ("-wal", "-shm"):
            p = Path(self.path + suffix)
            if p.exists():
                p.unlink()
        shutil.copyfile(src, self.path)


def _split_sql(script: str) -> list:
    """Split a migration script into statements, keeping trigger bodies (BEGIN ... END;) whole."""
    stmts, buf, depth = [], [], 0
    for line in script.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        up = s.upper()
        if up.startswith("CREATE TRIGGER"):
            depth = 1
        if depth and up.endswith("END;"):
            depth = 0
            stmts.append("\n".join(buf))
            buf = []
        elif not depth and s.endswith(";"):
            stmts.append("\n".join(buf))
            buf = []
    if buf:
        stmts.append("\n".join(buf))
    return stmts


@contextlib.contextmanager
def transaction(conn, retries: int = 5, base_delay: float = 0.05):
    """BEGIN IMMEDIATE ... COMMIT, retrying the BEGIN if another writer holds the lock."""
    for attempt in range(retries + 1):
        try:
            conn.execute("BEGIN IMMEDIATE")
            break
        except sqlite3.OperationalError as e:
            if "locked" not in str(e) and "busy" not in str(e) or attempt == retries:
                raise
            time.sleep(base_delay * (2 ** attempt) * (1 + random.random()))
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def audit(conn, actor: str, action: str, entity: str, entity_id=None, details: str = "{}"):
    conn.execute("INSERT INTO audit(ts, actor, action, entity, entity_id, details) VALUES (?,?,?,?,?,?)",
                 (to_iso(utcnow()), actor, action, entity, None if entity_id is None else str(entity_id), details))


def get_setting(conn, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def set_setting(conn, key: str, value: str):
    conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, value))
