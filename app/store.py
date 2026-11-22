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
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None)  # autocommit; explicit txns below
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")  # the send journal must survive a kill
    return con


def init():
    with connect() as con:
        con.executescript(SCHEMA)


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
