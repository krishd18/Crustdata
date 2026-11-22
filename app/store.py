"""SQLite persistence: dossiers, dated run snapshots, and the send journal."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

DATA_DIR = Path(os.getenv("SECONDLOOK_DATA", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "secondlook.db"

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS dossiers (
  id TEXT PRIMARY KEY,
  name TEXT, domain TEXT, city TEXT, teaser TEXT,
  company_id INTEGER, created_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  dossier_id TEXT, seq INTEGER, status TEXT, started_at TEXT, finished_at TEXT,
  progress TEXT, result TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS outbox (
  idem_key TEXT PRIMARY KEY,
  dossier_id TEXT, run_id TEXT, recipient TEXT, subject TEXT, body TEXT,
  status TEXT,               -- awaiting_approval | approved | sent
  approved_by TEXT, created_at TEXT, approved_at TEXT, sent_at TEXT, attempts INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS watches (
  dossier_id TEXT PRIMARY KEY, watch_id INTEGER, created_at TEXT, people TEXT
);
CREATE TABLE IF NOT EXISTS searches (
  id TEXT PRIMARY KEY, thesis TEXT, created_at TEXT, result TEXT, credits REAL
);
"""

# Columns added after the first release; ALTER is a no-op if they exist.
MIGRATIONS = [
    "ALTER TABLE runs ADD COLUMN mode TEXT DEFAULT 'check'",          # screen | check
    "ALTER TABLE dossiers ADD COLUMN deck_meta TEXT",                 # parser output (kind, pages, warnings)
    "ALTER TABLE dossiers ADD COLUMN search_id TEXT",                 # which FIND search it came from
    "ALTER TABLE dossiers ADD COLUMN signals TEXT",                   # FIND signals snapshot
    "ALTER TABLE outbox ADD COLUMN kind TEXT DEFAULT 'request'",      # intro | request
    "ALTER TABLE outbox ADD COLUMN from_name TEXT",                   # display name when MAIL_FROM has none
    "ALTER TABLE outbox ADD COLUMN inflight INTEGER DEFAULT 0",       # 1 = an attempt may have reached the provider
    "ALTER TABLE outbox ADD COLUMN last_attempt_at TEXT",
    "ALTER TABLE outbox ADD COLUMN transport TEXT",                   # file | resend | smtp
    "ALTER TABLE outbox ADD COLUMN provider_id TEXT",                 # Resend email id / SMTP Message-ID
    "ALTER TABLE outbox ADD COLUMN last_error TEXT",
    "ALTER TABLE dossiers ADD COLUMN flushed_at TEXT",                # set by "Flush pipeline" (hidden, restorable)
    "ALTER TABLE searches ADD COLUMN flushed_at TEXT",
    "ALTER TABLE dossiers ADD COLUMN deleted_at TEXT",                # one target deleted from the pipeline (undoable)
]


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)  # autocommit; explicit txns below
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")  # the send journal must survive a kill
    return con


def init():
    with connect() as con:
        con.executescript(SCHEMA)
        for sql in MIGRATIONS:
            try:
                con.execute(sql)
            except sqlite3.OperationalError as e:
                if "duplicate column" not in str(e):
                    raise


def q(sql: str, args=(), one=False):
    with _lock, connect() as con:
        cur = con.execute(sql, args)
        rows = cur.fetchall()
    rows = [dict(r) for r in rows]
    return (rows[0] if rows else None) if one else rows


def x(sql: str, args=()):
    with _lock, connect() as con:
        con.execute(sql, args)


def save_progress(run_id: str, steps: list[str]):
    x("UPDATE runs SET progress=? WHERE id=?", (json.dumps(steps), run_id))
