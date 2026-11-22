"""Exactly-once delivery of the intro and the diligence request list.

Order of operations for one send:
  1. A person approves the draft             -> status 'approved' (durable)
  2. attempts += 1, inflight = 1 is journaled -> durable, BEFORE any network I/O
  3. transport.send(idem_key, message)        -> real delivery
  4. local ledger marker for idem_key         -> durable
  5. status 'sent', inflight = 0              -> durable

`inflight = 1` means "an attempt may have reached the provider". Whenever a
row with inflight = 1 is sent again (startup recovery, or a person pressing
Retry), the transport is asked whether repeating is safe:

  * file mailbox  - always: it dedupes on the key itself.
  * Resend        - yes within its 24 h idempotency window (same key, same
                    payload -> the provider returns the original email).
  * SMTP          - never: SMTP has no idempotency. The row becomes
                    'uncertain' and a person checks the Sent folder, then
                    either resends or marks it sent. It is never sent twice
                    by the machine.

A failure the transport knows happened BEFORE the provider accepted anything
(bad credentials, refused recipient, connection refused) clears inflight, so a
retry is always safe. Permanent ones mark the row 'failed'.

Statuses: awaiting_approval -> approved -> sent | failed | uncertain
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import smtplib
import socket
import ssl
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from pathlib import Path

import httpx

from . import store
from .crust import now_iso

log = logging.getLogger("secondlook.outbox")

MAILBOX = store.DATA_DIR / "mailbox"
MAILBOX.mkdir(parents=True, exist_ok=True)

_send_lock = threading.Lock()  # one delivery at a time in this process (double-clicks)


def _crash(point: str):
    # Fault injection for the kill test. Simulates `kill -9` at a precise point.
    if os.getenv("SECONDLOOK_CRASH_AT") == point:
        log.warning("crash injected at %s", point)
        os._exit(137)


class MailError(Exception):
    """kind: 'permanent' (not sent, won't work on retry), 'retryable' (not sent),
    'ambiguous' (may or may not have been accepted by the provider)."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


# ---- transports -------------------------------------------------------------------
class _Ledger:
    """Local record of every confirmed delivery, shared by all transports.

    The marker is written right after the provider confirms, so a crash
    between the provider's OK and the DB update is healed on restart without
    asking the provider again.
    """

    name = "base"

    def __init__(self, root: Path = MAILBOX):
        self.root = root
        self.sent_dir = root / "sent"
        self.sent_dir.mkdir(parents=True, exist_ok=True)
        self.log = root / "deliveries.log"

    def delivered(self, key: str) -> dict | None:
        p = self.sent_dir / f"{key}.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    def _record(self, key: str, msg: dict, provider_id: str | None):
        p = self.sent_dir / f"{key}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"to": msg["to"], "subject": msg["subject"], "transport": self.name,
                                   "provider_id": provider_id, "at": now_iso()}), encoding="utf-8")
        os.replace(tmp, p)
        with open(self.log, "a", encoding="utf-8") as f:  # one line per real delivery
            f.write(f"{now_iso()} {key} -> {msg['to']} via {self.name}\n")

    def deliveries(self, key: str | None = None) -> int:
        if not self.log.exists():
            return 0
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return sum(1 for ln in lines if key is None or f" {key} " in ln)

    def safe_to_repeat(self, last_attempt_at: str | None) -> bool:
        return False

    def describe(self) -> dict:
        return {"transport": self.name, "real": True}


class FileMailTransport(_Ledger):
    """Demo mailbox on disk. Idempotent by key: a second send with the same key is a no-op."""

    name = "file"

    def delivered(self, key: str) -> dict | None:
        legacy = self.root / f"{key}.json"  # mailbox files written before the shared ledger existed
        return super().delivered(key) or ({"transport": "file", "at": None} if legacy.exists() else None)

    def send(self, key: str, msg: dict) -> str:
        if self.delivered(key):
            return "duplicate-suppressed"
        target = self.root / f"{key}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(msg, indent=2), encoding="utf-8")
        os.replace(tmp, target)
        self._record(key, msg, None)
        return "delivered"

    def safe_to_repeat(self, last_attempt_at):
        return True

    def describe(self):
        return {"transport": "file", "real": False, "where": str(self.root),
                "note": "Demo mailbox: nothing leaves this machine. Set RESEND_API_KEY or SMTP_HOST to send real email."}


class ResendTransport(_Ledger):
    """Resend HTTP API. Its Idempotency-Key header makes a repeat with the same key
    and payload return the original email (keys are kept for 24 hours)."""

    name = "resend"
    URL = "https://api.resend.com/emails"
    WINDOW = timedelta(hours=23)  # a margin inside Resend's 24 h

    def __init__(self, api_key: str, sender: str, reply_to: str | None = None, bcc: list[str] | None = None, root=MAILBOX):
        super().__init__(root)
        self.api_key, self.sender, self.reply_to, self.bcc = api_key, sender, reply_to, bcc or []

    def send(self, key: str, msg: dict) -> str:
        if self.delivered(key):
            return "duplicate-suppressed"
        payload = {"from": _from_header(self.sender, msg.get("from_name")), "to": [msg["to"]],
                   "subject": msg["subject"], "text": msg["body"],
                   "headers": {"X-SecondLook-Key": key}}
        if self.reply_to:
            payload["reply_to"] = self.reply_to
        if self.bcc:
            payload["bcc"] = self.bcc
        try:
            r = httpx.post(self.URL, json=payload, timeout=30, headers={
                "Authorization": f"Bearer {self.api_key}", "Idempotency-Key": key})
        except httpx.ConnectError as e:
            raise MailError("retryable", f"could not reach Resend: {e}")
        except httpx.HTTPError as e:  # timeouts etc.: the request may have landed
            raise MailError("ambiguous", f"Resend request did not complete: {e}")
        if r.status_code in (200, 201):
            pid = (r.json() or {}).get("id")
            self._record(key, msg, pid)
            return f"delivered ({pid})" if pid else "delivered"
        err = _resend_error(r)
        if r.status_code == 409 and "concurrent" in err:
            raise MailError("ambiguous", f"Resend is still processing this key: {err}")
        if r.status_code == 429:
            raise MailError("retryable", f"Resend rate limit: {err}")
        if r.status_code >= 500:
            raise MailError("ambiguous", f"Resend server error {r.status_code}: {err}")
        raise MailError("permanent", f"Resend rejected the email ({r.status_code}): {err}")

    def safe_to_repeat(self, last_attempt_at):
        t = _parse_ts(last_attempt_at)
        return t is not None and datetime.now(timezone.utc) - t < self.WINDOW

    def describe(self):
        return {"transport": "resend", "real": True, "from": self.sender, "reply_to": self.reply_to,
                "bcc": self.bcc, "idempotent": "24h (provider-side Idempotency-Key)"}


class SmtpTransport(_Ledger):
    """Any SMTP server (Gmail with an app password, Office 365, SES SMTP, Zoho...).

    SMTP cannot dedupe, so a send interrupted after the server may have
    accepted it is never repeated automatically (see module docstring)."""

    name = "smtp"

    def __init__(self, host: str, port: int, user: str | None, password: str | None, security: str,
                 sender: str, reply_to: str | None = None, bcc: list[str] | None = None, root=MAILBOX):
        super().__init__(root)
        self.host, self.port, self.user, self.password = host, port, user, password
        self.security, self.sender, self.reply_to, self.bcc = security, sender, reply_to, bcc or []

    def build(self, key: str, msg: dict) -> EmailMessage:
        m = EmailMessage()
        m["From"] = _from_header(self.sender, msg.get("from_name"))
        m["To"] = msg["to"]
        m["Subject"] = msg["subject"]
        if self.reply_to:
            m["Reply-To"] = self.reply_to
        domain = parseaddr(self.sender)[1].partition("@")[2] or "secondlook.local"
        m["Message-ID"] = f"<{key}@{domain}>"  # stable per send: a resend shows as the same message
        m["X-SecondLook-Key"] = key
        m.set_content(msg["body"])
        return m

    def send(self, key: str, msg: dict) -> str:
        if self.delivered(key):
            return "duplicate-suppressed"
        m = self.build(key, msg)
        # Phase 1: connect + log in. Nothing can have been sent if this fails.
        try:
            if self.security == "ssl":
                s = smtplib.SMTP_SSL(self.host, self.port, timeout=30, context=ssl.create_default_context())
            else:
                s = smtplib.SMTP(self.host, self.port, timeout=30)
                if self.security == "starttls":
                    s.starttls(context=ssl.create_default_context())
            if self.user:
                s.login(self.user, self.password or "")
        except smtplib.SMTPAuthenticationError as e:
            raise MailError("permanent", f"SMTP login failed for {self.user}: {_smtp_text(e)}")
        except (OSError, smtplib.SMTPException) as e:
            raise MailError("retryable", f"could not connect to {self.host}:{self.port}: {e}")
        # Phase 2: the transaction. Refusals before DATA mean nothing was accepted.
        try:
            with s:
                s.send_message(m, to_addrs=[msg["to"], *self.bcc])
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as e:
            raise MailError("permanent", f"SMTP server refused the address: {e}")
        except smtplib.SMTPDataError as e:
            kind = "permanent" if 500 <= e.smtp_code < 600 else "retryable"
            raise MailError(kind, f"SMTP server rejected the message ({e.smtp_code}): {_smtp_text(e)}")
        except (smtplib.SMTPServerDisconnected, socket.timeout, OSError, smtplib.SMTPException) as e:
            raise MailError("ambiguous", f"connection dropped during the send: {e}")
        self._record(key, msg, m["Message-ID"])
        return "delivered"

    def describe(self):
        return {"transport": "smtp", "real": True, "server": f"{self.host}:{self.port} ({self.security})",
                "from": self.sender, "reply_to": self.reply_to, "bcc": self.bcc,
                "idempotent": "no: an interrupted send is held for a person instead of being repeated"}


def _from_header(sender: str, from_name: str | None) -> str:
    name, addr = parseaddr(sender)
    return formataddr((name or (from_name or "").strip() or "", addr)) if addr else sender


def _resend_error(r: httpx.Response) -> str:
    try:
        j = r.json()
        return f"{j.get('name') or ''} {j.get('message') or ''}".strip() or r.text[:200]
    except ValueError:
        return r.text[:200]


def _smtp_text(e) -> str:
    err = getattr(e, "smtp_error", b"")
    return err.decode(errors="replace") if isinstance(err, bytes) else str(err)


def _parse_ts(s: str | None):
    if not s:
        return None
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def config_problems() -> list[str]:
    """What's missing for the chosen transport (empty = ready)."""
    t = _choice()
    out = []
    if t in ("resend", "smtp"):
        if not parseaddr(os.getenv("MAIL_FROM", ""))[1]:
            out.append("MAIL_FROM is not set (e.g. \"Acme Strategy <deals@acme.com>\")")
    if t == "resend" and not os.getenv("RESEND_API_KEY"):
        out.append("RESEND_API_KEY is not set")
    if t == "smtp" and not os.getenv("SMTP_HOST"):
        out.append("SMTP_HOST is not set")
    if t not in ("file", "resend", "smtp"):
        out.append(f"MAIL_TRANSPORT={t!r} is not one of file, resend, smtp")
    return out


def _choice() -> str:
    t = (os.getenv("MAIL_TRANSPORT") or "").strip().lower()
    if t:
        return t
    if os.getenv("RESEND_API_KEY"):
        return "resend"
    if os.getenv("SMTP_HOST"):
        return "smtp"
    return "file"


def get_transport() -> _Ledger:
    """Built from the environment on each send, so a fixed .env takes effect on Retry."""
    t = _choice()
    probs = config_problems()
    if probs:
        raise MailError("permanent", "email is not configured: " + "; ".join(probs))
    sender, reply_to, bcc = os.getenv("MAIL_FROM", ""), os.getenv("MAIL_REPLY_TO") or None, _csv(os.getenv("MAIL_BCC"))
    if t == "resend":
        return ResendTransport(os.environ["RESEND_API_KEY"], sender, reply_to, bcc)
    if t == "smtp":
        security = (os.getenv("SMTP_SECURITY") or "").lower()
        port = int(os.getenv("SMTP_PORT") or (465 if security == "ssl" else 587))
        security = security or ("ssl" if port == 465 else "starttls")
        return SmtpTransport(os.environ["SMTP_HOST"], port, os.getenv("SMTP_USER") or None,
                             os.getenv("SMTP_PASSWORD") or None, security, sender, reply_to, bcc)
    return FileMailTransport()


def describe() -> dict:
    probs = config_problems()
    if probs:
        return {"transport": _choice(), "real": False, "ready": False, "problems": probs}
    return {**get_transport().describe(), "ready": True, "problems": []}


# The ledger is shared by every transport, so delivery counts survive switching providers.
transport = FileMailTransport()


# ---- the journal ------------------------------------------------------------------
def idem_key(dossier_id: str, run_id: str, recipient: str, body: str) -> str:
    h = hashlib.sha256(f"{dossier_id}|{run_id}|{recipient.lower()}|{body}".encode()).hexdigest()
    return h[:32]


def valid_address(addr: str) -> bool:
    name, a = parseaddr(addr or "")
    local, at, domain = a.partition("@")
    return bool(local and at and "." in domain and " " not in a and "," not in (addr or ""))


def draft(dossier_id: str, run_id: str, recipient: str, subject: str, body: str, kind: str = "request",
          from_name: str | None = None) -> dict:
    key = idem_key(dossier_id, f"{kind}:{run_id}", recipient, body)
    store.x(
        "INSERT OR IGNORE INTO outbox (idem_key, dossier_id, run_id, recipient, subject, body, status, created_at, kind, from_name)"
        " VALUES (?,?,?,?,?,?, 'awaiting_approval', ?, ?, ?)",
        (key, dossier_id, run_id, recipient, subject, body, now_iso(), kind, from_name),
    )
    return store.q("SELECT * FROM outbox WHERE idem_key=?", (key,), one=True)


def _row(key: str) -> dict:
    row = store.q("SELECT * FROM outbox WHERE idem_key=?", (key,), one=True)
    if not row:
        raise KeyError(key)
    return row


def approve_and_send(key: str, approver: str) -> dict:
    row = _row(key)
    if row["status"] == "sent":
        return {**row, "result": "already-sent"}
    if row["status"] == "awaiting_approval":
        store.x("UPDATE outbox SET status='approved', approved_by=?, approved_at=? WHERE idem_key=? AND status='awaiting_approval'",
                (approver, now_iso(), key))
    return _deliver(key)


def retry(key: str, approver: str, confirm_not_sent: bool = False) -> dict:
    """A person re-runs a failed send, or resolves an uncertain one after checking."""
    row = _row(key)
    if row["status"] == "sent":
        return {**row, "result": "already-sent"}
    if row["status"] == "uncertain" and not confirm_not_sent:
        raise PermissionError("this send may already have gone out: check the Sent folder, then confirm it did not")
    if row["status"] not in ("failed", "uncertain", "approved"):
        raise PermissionError("not approved by a person")
    clear = ", inflight=0" if row["status"] == "uncertain" else ""  # a person confirmed nothing went out
    store.x(f"UPDATE outbox SET status='approved', approved_by=?, approved_at=?{clear} WHERE idem_key=?",
            (approver, now_iso(), key))
    return _deliver(key)


def mark_sent(key: str, approver: str) -> dict:
    """A person found an uncertain send in the Sent folder."""
    row = _row(key)
    if row["status"] != "uncertain":
        raise PermissionError("only an uncertain send can be marked as sent by hand")
    store.x("UPDATE outbox SET status='sent', sent_at=?, inflight=0, last_error=? WHERE idem_key=?",
            (now_iso(), f"marked sent by {approver} after checking the Sent folder", key))
    return {**_row(key), "result": "marked-sent"}


def _deliver(key: str) -> dict:
    with _send_lock:
        return _deliver_locked(key)


def _deliver_locked(key: str) -> dict:
    row = _row(key)
    if row["status"] == "sent":
        return {**row, "result": "already-sent"}
    if row["status"] != "approved":
        raise PermissionError("not approved by a person")
    try:
        t = get_transport()
    except MailError as e:
        store.x("UPDATE outbox SET status='failed', last_error=? WHERE idem_key=?", (str(e), key))
        return {**_row(key), "result": "failed"}

    # A confirmed delivery whose DB update was lost to a crash: finish it, don't resend.
    done = t.delivered(key)
    if done:
        store.x("UPDATE outbox SET status='sent', sent_at=?, inflight=0, transport=?, provider_id=? WHERE idem_key=?",
                (done.get("at") or now_iso(), done.get("transport") or t.name, done.get("provider_id"), key))
        return {**_row(key), "result": "already-delivered"}

    # A previous attempt may have reached the provider: only repeat if that's safe.
    if row.get("inflight") and not (row.get("transport") in (None, t.name) and t.safe_to_repeat(row.get("last_attempt_at"))):
        why = ("SMTP can't dedupe" if t.name == "smtp" else
               "the provider's idempotency window has passed" if t.name == row.get("transport") else
               f"the transport changed from {row.get('transport')} to {t.name}")
        store.x("UPDATE outbox SET status='uncertain', last_error=? WHERE idem_key=?",
                (f"An earlier attempt was interrupted and may have been delivered; not repeated because {why}. "
                 "Check the Sent folder, then resend or mark it sent.", key))
        return {**_row(key), "result": "uncertain"}

    store.x("UPDATE outbox SET attempts=attempts+1, inflight=1, last_attempt_at=?, transport=? WHERE idem_key=?",
            (now_iso(), t.name, key))   # journal first
    _crash("after_journal")
    msg = {"to": row["recipient"], "subject": row["subject"], "body": row["body"],
           "from_name": row.get("from_name"), "idempotency_key": key}
    try:
        result = t.send(key, msg)
    except MailError as e:
        log.warning("outbox %s: %s failure: %s", key, e.kind, e)
        # Definitely not sent -> inflight=0, a Retry is always safe. Ambiguous -> keep
        # inflight=1 so the next attempt goes through the safety check above.
        clear = "" if e.kind == "ambiguous" else ", inflight=0"
        store.x(f"UPDATE outbox SET status='failed'{clear}, last_error=? WHERE idem_key=?", (f"[{e.kind}] {e}", key))
        return {**_row(key), "result": "failed", "error_kind": e.kind}
    _crash("after_transport")
    done = t.delivered(key) or {}
    store.x("UPDATE outbox SET status='sent', sent_at=?, inflight=0, last_error=NULL, provider_id=? WHERE idem_key=?",
            (now_iso(), done.get("provider_id"), key))
    log.info("outbox %s: %s via %s", key, result, t.name)
    return {**_row(key), "result": result}


def recover() -> list[dict]:
    """Run at startup: finish any approved-but-unconfirmed sends."""
    out = []
    for row in store.q("SELECT idem_key FROM outbox WHERE status='approved'"):
        out.append(_deliver(row["idem_key"]))
    if out:
        log.warning("recovered %d in-flight send(s)", len(out))
    return out


def send_test(to: str) -> dict:
    """A one-off message to check the configuration. Not journaled; a fresh key each time."""
    t = get_transport()
    key = "test-" + uuid.uuid4().hex[:24]
    msg = {"to": to, "subject": "SecondLook: test email",
           "body": f"This is a test from SecondLook via {t.name}. If you can read it, sending works.\n\nKey: {key}"}
    try:
        return {"result": t.send(key, msg), "transport": t.name, "key": key}
    except MailError as e:
        return {"result": "failed", "error_kind": e.kind, "error": str(e), "transport": t.name}
