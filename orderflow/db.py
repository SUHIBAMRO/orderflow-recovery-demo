"""DB-API persistence. PostgreSQL for deployment; SQLite for portable verification."""
import contextlib
import json
import sqlite3
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
 id TEXT PRIMARY KEY, scenario TEXT NOT NULL, customer TEXT NOT NULL,
 vehicle TEXT NOT NULL, owner_last4 TEXT NOT NULL, status TEXT NOT NULL,
 phase TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', policy_ref TEXT NOT NULL DEFAULT '',
 roadtax_ref TEXT NOT NULL DEFAULT '', refund_ref TEXT NOT NULL DEFAULT '',
 roadtax_cents INTEGER NOT NULL CHECK(roadtax_cents > 0), currency TEXT NOT NULL,
 attempt INTEGER NOT NULL DEFAULT 0, next_attempt DOUBLE PRECISION NOT NULL DEFAULT 0,
 photos_received INTEGER NOT NULL DEFAULT 0, owner_corrected INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, created_at DOUBLE PRECISION NOT NULL,
 updated_at DOUBLE PRECISION NOT NULL, request_key TEXT UNIQUE NOT NULL,
 request_body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
 occurred_at DOUBLE PRECISION NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL,
 details TEXT NOT NULL, policy_version TEXT NOT NULL, order_version INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_order ON events(order_id, occurred_at);
CREATE TABLE IF NOT EXISTS actions (
 request_key TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
 request_body TEXT NOT NULL, result TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS wakeups (
 id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id),
 delivered INTEGER NOT NULL DEFAULT 0, created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_operations (
 request_key TEXT PRIMARY KEY, kind TEXT NOT NULL, order_id TEXT NOT NULL,
 request_body TEXT NOT NULL, response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS provider_calls (
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL, kind TEXT NOT NULL,
 order_id TEXT NOT NULL, code TEXT NOT NULL, occurred_at DOUBLE PRECISION NOT NULL
);
"""


class Session:
    def __init__(self, conn, postgres):
        self.conn, self.postgres = conn, postgres

    def execute(self, sql, args=()):
        return self.conn.execute(sql.replace("?", "%s") if self.postgres else sql, args)

    def one(self, sql, args=()):
        r = self.execute(sql, args).fetchone()
        return dict(r) if r else None

    def all(self, sql, args=()):
        return [dict(r) for r in self.execute(sql, args).fetchall()]

    def order(self, order_id):
        return self.one("SELECT * FROM orders WHERE id=?" + (" FOR UPDATE" if self.postgres else ""), (order_id,))


class Database:
    def __init__(self, url):
        self.url = url
        self.postgres = url.startswith(("postgresql://", "postgres://"))

    def connect(self):
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row
            return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5)
        path = self.url.removeprefix("sqlite:///")
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(path, timeout=20)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        return c

    @contextlib.contextmanager
    def transaction(self):
        c = self.connect()
        try:
            if not self.postgres:
                c.execute("BEGIN IMMEDIATE")
            yield Session(c, self.postgres)
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def initialize(self):
        with self.transaction() as s:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    s.execute(statement)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
