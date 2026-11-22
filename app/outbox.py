"""Exactly-once delivery of the diligence request list.

Order of operations for one send:
  1. A person approves the draft            -> row status 'approved' (durable)
  2. attempts += 1 is journaled              -> durable, BEFORE any network I/O
  3. transport.send(idem_key, message)       -> provider dedupes on idem_key
  4. row status 'sent'                       -> durable

A kill between 2 and 4 leaves the row 'approved'. On restart, recover()
re-sends with the SAME idempotency key, so the counterparty receives it once.
A kill before 2 means nothing went out, and recover() sends it once.

The transport here is a file-backed mailbox that behaves like an email API with
an Idempotency-Key header (Postmark/SES/Resend-style). Swap in a real provider
by implementing `send(key, msg)` with the same contract.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from . import store
from .crust import now_iso

log = logging.getLogger("secondlook.outbox")

MAILBOX = store.DATA_DIR / "mailbox"
MAILBOX.mkdir(parents=True, exist_ok=True)


def _crash(point: str):
    # Fault injection for the kill test. Simulates `kill -9` at a precise point.
    if os.getenv("SECONDLOOK_CRASH_AT") == point:
        log.warning("crash injected at %s", point)
        os._exit(137)


class FileMailTransport:
    """Idempotent by key: a second send with the same key is a no-op."""

    def __init__(self, root: Path = MAILBOX):
        self.root = root
        self.log = root / "deliveries.log"

    def send(self, key: str, msg: dict) -> str:
        target = self.root / f"{key}.json"
        if target.exists():
            return "duplicate-suppressed"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(msg, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        with open(self.log, "a", encoding="utf-8") as f:  # one line per real delivery
            f.write(f"{now_iso()} {key} -> {msg['to']}\n")
        return "delivered"

    def deliveries(self, key: str | None = None) -> int:
        if not self.log.exists():
            return 0
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return sum(1 for ln in lines if key is None or f" {key} " in ln)


transport = FileMailTransport()


def idem_key(dossier_id: str, run_id: str, recipient: str, body: str) -> str:
    h = hashlib.sha256(f"{dossier_id}|{run_id}|{recipient.lower()}|{body}".encode()).hexdigest()
    return h[:32]


def draft(dossier_id: str, run_id: str, recipient: str, subject: str, body: str) -> dict:
    key = idem_key(dossier_id, run_id, recipient, body)
    store.x(
        "INSERT OR IGNORE INTO outbox (idem_key, dossier_id, run_id, recipient, subject, body, status, created_at)"
        " VALUES (?,?,?,?,?,?, 'awaiting_approval', ?)",
        (key, dossier_id, run_id, recipient, subject, body, now_iso()),
    )
    return store.q("SELECT * FROM outbox WHERE idem_key=?", (key,), one=True)


def approve_and_send(key: str, approver: str) -> dict:
    row = store.q("SELECT * FROM outbox WHERE idem_key=?", (key,), one=True)
    if not row:
        raise KeyError(key)
    if row["status"] == "sent":
        return {**row, "result": "already-sent"}
    if row["status"] == "awaiting_approval":
        store.x("UPDATE outbox SET status='approved', approved_by=?, approved_at=? WHERE idem_key=? AND status='awaiting_approval'",
                (approver, now_iso(), key))
    return _deliver(key)


def _deliver(key: str) -> dict:
    row = store.q("SELECT * FROM outbox WHERE idem_key=?", (key,), one=True)
    if row["status"] == "sent":
        return {**row, "result": "already-sent"}
    if row["status"] != "approved":
        raise PermissionError("not approved by a person")
    store.x("UPDATE outbox SET attempts=attempts+1 WHERE idem_key=?", (key,))   # journal first
    _crash("after_journal")
    result = transport.send(key, {"to": row["recipient"], "subject": row["subject"], "body": row["body"],
                                  "idempotency_key": key})
    _crash("after_transport")
    store.x("UPDATE outbox SET status='sent', sent_at=? WHERE idem_key=?", (now_iso(), key))
    log.info("outbox %s: %s", key, result)
    return {**store.q("SELECT * FROM outbox WHERE idem_key=?", (key,), one=True), "result": result}


def recover() -> list[dict]:
    """Run at startup: finish any approved-but-unconfirmed sends."""
    out = []
    for row in store.q("SELECT idem_key FROM outbox WHERE status='approved'"):
        out.append(_deliver(row["idem_key"]))
    if out:
        log.warning("recovered %d in-flight send(s)", len(out))
    return out
