"""Exactly-once executor (ARCHITECTURE §17.2, plan §4.2E): approve → intent (journal, UNIQUE) → pre-check Sent
folder → send (same deterministic Message-ID) → confirm via IMAP/Mailpit → reconciled. On restart, reconcile_all()
resolves every intent without 'reconciled'. IMAP down → 'unconfirmed' hold; never resent blindly."""
from __future__ import annotations

import json
import time
from email.message import EmailMessage
from email.utils import formatdate

from ..core.errors import SecretMissing, SourceUnavailable
from ..core.logging import get_logger
from . import guard

log = get_logger("mail")


class Executor:
    def __init__(self, stores, provider, settings, mail_cfg: dict, sleep=time.sleep, on_step=None):
        self.st, self.p, self.s, self.cfg = stores, provider, settings, mail_cfg
        self.sleep = sleep
        self.on_step = on_step or (lambda step, aid: None)   # chaos hook: kill points
        rc = mail_cfg.get("reconcile", {})
        self.timeout, self.poll = float(rc.get("confirm_timeout_s", 60)), float(rc.get("poll_every_s", 5))

    # -- approvals -----------------------------------------------------------
    def draft(self, aid: str) -> dict:
        r = self.st.one("SELECT * FROM approvals WHERE action_id=?", (aid,))
        if not r:
            raise KeyError(aid)
        d = json.loads(r["draft_json"])
        d.update(status=r["status"], decided_by=r["decided_by"], version=r["version"])
        return d

    def approve(self, aid: str, by: str) -> None:
        d = self.draft(aid)
        if d["status"] != "pending":
            return
        self.st.x("UPDATE approvals SET status='approved', decided_by=?, at=? WHERE action_id=?", (by, time.time(), aid))
        self.st.journal(aid, "approved", {"by": by})

    def reject(self, aid: str, by: str, reason: str) -> None:
        self.st.x("UPDATE approvals SET status='rejected', decided_by=?, reason=?, at=? WHERE action_id=?", (by, reason, time.time(), aid))
        self.st.journal(aid, "rejected", {"by": by, "reason": reason})

    def edit(self, aid: str, by: str, subject: str, body: str) -> str:
        """An edit is a new draft (new content → new action_id); the old one is superseded."""
        from .drafter import queue
        d = self.draft(aid)
        new = queue(self.st, d["run_id"], d["template"], d["to"], subject, body, d["company"], d.get("evidence_ids", []),
                    version=int(d.get("version", 1)) + 1)
        self.st.x("UPDATE approvals SET status='superseded', decided_by=?, at=? WHERE action_id=?", (by, time.time(), aid))
        self.st.journal(aid, "superseded", {"by": by, "new": new})
        return new

    # -- message -------------------------------------------------------------
    def message(self, d: dict) -> EmailMessage:
        heads = self.cfg.get("headers", {})
        m = EmailMessage()
        to, subject = d["to"], d["subject"]
        if self.s.mail_mode != "live":
            tm = self.cfg.get("test_mode", {})
            m[tm.get("original_to_header", "X-DD-Original-To")] = to
            to = self.s.test_inbox if self.s.mail_provider == "gmail" else (self.s.test_inbox or "test-inbox@datadesigner.local")
            subject = tm.get("subject_prefix", "[TEST] ") + subject
        frm = self.s.gmail_address if self.s.mail_provider == "gmail" else "datadesigner@datadesigner.local"
        m["From"], m["To"], m["Subject"] = frm, to, subject
        m["Message-ID"] = self.cfg.get("message_id", "<{action_id}@datadesigner.local>").format(action_id=d["action_id"])
        m["Date"] = formatdate(localtime=True)
        m[heads.get("action", "X-DD-Action-Id")] = d["action_id"]
        m[heads.get("run", "X-DD-Run-Id")] = d["run_id"]
        m.set_content(d["body"])
        return m

    # -- the exactly-once path ----------------------------------------------
    def execute(self, aid: str) -> str:
        """Returns final state: reconciled | unconfirmed | held | skipped."""
        d = self.draft(aid)
        if d["status"] != "approved":
            log.warning("mail.not_approved", action_id=aid, status=d["status"])
            return "skipped"
        states = self.st.journal_states(aid)
        if "reconciled" in states:
            return "reconciled"
        if "intent" not in states:
            guard.check(d, self.cfg, self.st, self.s)
            msg = self.message(d)
            self.st.journal(aid, "intent", {"message_id": msg["Message-ID"], "to": msg["To"]})
        self.on_step("after_intent", aid)
        return self._deliver(aid, d)

    def _deliver(self, aid: str, d: dict) -> str:
        msg = self.message(d)
        mid = msg["Message-ID"]
        try:
            already = self.p.find_sent(mid, aid)
        except SourceUnavailable as e:
            log.warning("mail.precheck_unavailable", action_id=aid, error=str(e))
            self.st.journal(aid, "unconfirmed", {"reason": str(e)})
            return "unconfirmed"
        if already:
            self.st.journal(aid, "sent", {"via": "precheck"}, mid)
            self.st.journal(aid, "reconciled", {"via": "precheck"}, mid)
            return "reconciled"
        try:
            self.on_step("before_send", aid)
            pid = self.p.send(msg)
        except SecretMissing as e:
            log.error("mail.auth_failed", action_id=aid, error=str(e))
            raise
        except Exception as e:  # noqa: BLE001 — connection drop after DATA etc.: reconcile decides
            log.warning("mail.send_error", action_id=aid, error=type(e).__name__)
            pid = ""
        self.on_step("after_send", aid)
        if pid:
            self.st.journal(aid, "sent", {"to": msg["To"]}, pid)
        return self._confirm(aid, mid)

    def _confirm(self, aid: str, mid: str) -> str:
        deadline = time.time() + self.timeout
        while True:
            try:
                if self.p.find_sent(mid, aid):
                    self.st.journal(aid, "sent", {"via": "confirm"}, mid)  # no-op if already present
                    self.st.journal(aid, "reconciled", {"via": "imap" if self.p.name == "gmail" else "mailpit"}, mid)
                    return "reconciled"
            except SourceUnavailable as e:
                self.st.journal(aid, "unconfirmed", {"reason": str(e)})
                return "unconfirmed"
            if time.time() >= deadline:
                self.st.journal(aid, "unconfirmed", {"reason": "not found within confirm timeout"})
                return "unconfirmed"
            self.sleep(self.poll)

    def reconcile_all(self) -> dict:
        """Startup: resolve every intent lacking 'reconciled'. Found → sent+reconciled. Not found → resend same Message-ID."""
        out = {}
        for r in self.st.rows("SELECT DISTINCT action_id FROM journal WHERE state='intent'"):
            aid = r["action_id"]
            states = self.st.journal_states(aid)
            if "reconciled" in states:
                continue
            d = self.draft(aid)
            out[aid] = self._deliver(aid, d)
        return out

    def run_approved(self) -> dict:
        res = self.reconcile_all()
        for r in self.st.rows("SELECT action_id FROM approvals WHERE status='approved'"):
            if r["action_id"] not in res:
                res[r["action_id"]] = self.execute(r["action_id"])
        return res
