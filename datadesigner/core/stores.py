"""SQLite stores (WAL, synchronous=FULL) — plan §3.1C table list. One connection per thread."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .ids import canon, sha256

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, family TEXT, mandate_json TEXT, state TEXT,
  config_version TEXT, rubric_version TEXT, created_at REAL, updated_at REAL, request_json TEXT, limits_json TEXT);
CREATE TABLE IF NOT EXISTS checkpoints(run_id TEXT, stage TEXT, output_json TEXT, created_at REAL, PRIMARY KEY(run_id, stage));
CREATE TABLE IF NOT EXISTS evidence(evidence_id TEXT PRIMARY KEY, run_id TEXT, claim_id TEXT, source TEXT, url_or_endpoint TEXT,
  passage_or_field TEXT, value TEXT, record_date TEXT, retrieved_at TEXT, content_sha256 TEXT, tier TEXT, media_tier TEXT, offset INTEGER);
CREATE TABLE IF NOT EXISTS blobs(sha256 TEXT PRIMARY KEY, content BLOB, content_type TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, response_json TEXT, created_at REAL, ttl_s REAL);
CREATE TABLE IF NOT EXISTS llm_cache(key TEXT PRIMARY KEY, model TEXT, prompt_sha TEXT, input_sha TEXT, schema_sha TEXT, output_json TEXT,
  tokens_in INTEGER, tokens_out INTEGER, cache_read_tokens INTEGER, request_id TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS cost(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, request_id TEXT, endpoint TEXT, credits REAL,
  llm_tokens_in INTEGER, llm_tokens_out INTEGER, inr REAL, at REAL, cached INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS journal(seq INTEGER PRIMARY KEY AUTOINCREMENT, action_id TEXT, state TEXT, payload_json TEXT, provider_id TEXT,
  at REAL, prev_hash TEXT, hash TEXT, UNIQUE(action_id, state));
CREATE TABLE IF NOT EXISTS approvals(action_id TEXT PRIMARY KEY, run_id TEXT, kind TEXT, draft_json TEXT, status TEXT, decided_by TEXT,
  reason TEXT, at REAL, version INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, suggested TEXT, final TEXT, decided_by TEXT, reason TEXT, at REAL);
"""


class Stores:
    """Thin typed wrapper over one SQLite file. All writes commit immediately (crash-safe)."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._lock = threading.RLock()
        self.db.executescript(SCHEMA)

    @property
    def db(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA synchronous=FULL")
            self._local.c = c
        return c

    def x(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.db.execute(sql, args)

    def rows(self, sql: str, args: tuple = ()) -> list[dict]:
        return [dict(r) for r in self.x(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        r = self.x(sql, args).fetchone()
        return dict(r) if r else None

    # blobs ---------------------------------------------------------------
    def put_blob(self, content: bytes | str, content_type: str = "application/json") -> str:
        b = content.encode() if isinstance(content, str) else content
        h = sha256(b)
        self.x("INSERT OR IGNORE INTO blobs VALUES(?,?,?,?)", (h, b, content_type, time.time()))
        return h

    def blob(self, h: str) -> bytes | None:
        r = self.one("SELECT content FROM blobs WHERE sha256=?", (h,))
        return r["content"] if r else None

    # cache ---------------------------------------------------------------
    def cache_get(self, key: str) -> Any | None:
        r = self.one("SELECT response_json, created_at, ttl_s FROM cache WHERE key=?", (key,))
        if r and (r["ttl_s"] is None or time.time() - r["created_at"] < r["ttl_s"]):
            return json.loads(r["response_json"])
        return None

    def cache_put(self, key: str, value: Any, ttl_s: float | None) -> None:
        self.x("INSERT OR REPLACE INTO cache VALUES(?,?,?,?)", (key, canon(value), time.time(), ttl_s))

    # cost ----------------------------------------------------------------
    def add_cost(self, run_id: str, endpoint: str, credits: float = 0.0, request_id: str = "", tin: int = 0,
                 tout: int = 0, inr: float = 0.0, cached: bool = False) -> None:
        self.x("INSERT INTO cost(run_id,request_id,endpoint,credits,llm_tokens_in,llm_tokens_out,inr,at,cached) VALUES(?,?,?,?,?,?,?,?,?)",
               (run_id, request_id, endpoint, credits, tin, tout, inr, time.time(), int(cached)))

    def cost_summary(self, run_id: str | None = None) -> dict:
        q = "SELECT COALESCE(SUM(credits),0) c, COALESCE(SUM(llm_tokens_in),0) ti, COALESCE(SUM(llm_tokens_out),0) to_, COALESCE(SUM(inr),0) inr, COUNT(*) n FROM cost"
        r = self.one(q + (" WHERE run_id=?" if run_id else ""), (run_id,) if run_id else ())
        return {"credits": round(r["c"], 3), "llm_tokens_in": r["ti"], "llm_tokens_out": r["to_"], "inr": round(r["inr"], 2), "calls": r["n"]}

    # runs / checkpoints --------------------------------------------------
    def put_checkpoint(self, run_id: str, stage: str, output: Any) -> None:
        self.x("INSERT OR REPLACE INTO checkpoints VALUES(?,?,?,?)", (run_id, stage, canon(output), time.time()))

    def checkpoint(self, run_id: str, stage: str) -> Any | None:
        r = self.one("SELECT output_json FROM checkpoints WHERE run_id=? AND stage=?", (run_id, stage))
        return json.loads(r["output_json"]) if r else None

    # journal (hash-chained, append-only) ---------------------------------
    def journal(self, action_id: str, state: str, payload: Any = None, provider_id: str = "") -> bool:
        """Append (action_id,state). Returns False if that pair already exists (UNIQUE) — idempotent."""
        with self._lock:
            last = self.one("SELECT hash FROM journal ORDER BY seq DESC LIMIT 1")
            prev = last["hash"] if last else "0" * 64
            body = canon([action_id, state, payload, provider_id, prev])
            h = sha256(body)
            try:
                self.x("INSERT INTO journal(action_id,state,payload_json,provider_id,at,prev_hash,hash) VALUES(?,?,?,?,?,?,?)",
                       (action_id, state, canon(payload), provider_id, time.time(), prev, h))
                return True
            except sqlite3.IntegrityError:
                return False

    def journal_states(self, action_id: str) -> list[str]:
        return [r["state"] for r in self.rows("SELECT state FROM journal WHERE action_id=? ORDER BY seq", (action_id,))]

    def verify_chain(self) -> tuple[bool, int]:
        prev, n = "0" * 64, 0
        for r in self.rows("SELECT * FROM journal ORDER BY seq"):
            body = canon([r["action_id"], r["state"], json.loads(r["payload_json"]), r["provider_id"], prev])
            if r["prev_hash"] != prev or sha256(body) != r["hash"]:
                return False, n
            prev, n = r["hash"], n + 1
        return True, n
