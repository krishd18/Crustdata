"""Mail providers (plan §3.1C): GmailSMTP (smtp.gmail.com:587 STARTTLS + app password; IMAP Sent-folder
reconcile) and Mailpit (localhost:1025, no auth; find_sent via its search API). Same interface."""
from __future__ import annotations

import imaplib
import smtplib
import ssl
from email.message import EmailMessage

import httpx

from ..core.errors import SecretMissing, SourceUnavailable


class MailProvider:
    name = "base"

    def send(self, msg: EmailMessage) -> str:
        raise NotImplementedError

    def find_sent(self, message_id: str, action_id: str) -> bool:
        raise NotImplementedError


class GmailSMTP(MailProvider):
    name = "gmail"

    def __init__(self, settings, mail_cfg: dict):
        self.s, self.cfg = settings, mail_cfg.get("providers", {}).get("gmail", {})
        self.sent_folder = self.cfg.get("imap", {}).get("sent_folder", "[Gmail]/Sent Mail")
        self.action_header = mail_cfg.get("headers", {}).get("action", "X-DD-Action-Id")

    def send(self, msg: EmailMessage) -> str:
        addr, pw = self.s.secret("gmail_address"), self.s.secret("gmail_app_password")
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(addr, pw)
                s.send_message(msg)
        except smtplib.SMTPAuthenticationError as e:
            raise SecretMissing("Gmail rejected the login — check 2-Step Verification + app password; re-run /setup-secrets") from e
        return str(msg["Message-ID"])

    def find_sent(self, message_id: str, action_id: str) -> bool:
        addr, pw = self.s.secret("gmail_address"), self.s.secret("gmail_app_password")
        try:
            with imaplib.IMAP4_SSL(self.s.imap_host, self.s.imap_port) as m:
                m.login(addr, pw)
                m.select(f'"{self.sent_folder}"', readonly=True)
                _, hits = m.search(None, "X-GM-RAW", f'"rfc822msgid:{message_id.strip("<>")}"')
                if not hits or not hits[0]:
                    _, hits = m.search(None, "HEADER", self.action_header, action_id)
                return bool(hits and hits[0])
        except imaplib.IMAP4.error as e:
            raise SourceUnavailable("gmail_imap", str(e)[:120]) from e
        except OSError as e:
            raise SourceUnavailable("gmail_imap", type(e).__name__) from e


class Mailpit(MailProvider):
    """Mailpit (or the bundled local stand-in, datadesigner.mail.local_mailpit) — every automated test."""
    name = "mailpit"

    def __init__(self, settings, mail_cfg: dict):
        mp = mail_cfg.get("providers", {}).get("mailpit", {})
        self.host = mp.get("smtp", {}).get("host", "localhost")
        self.port = int(getattr(settings, "mailpit_smtp_port", 0) or mp.get("smtp", {}).get("port", 1025))
        self.api = (getattr(settings, "mailpit_api", "") or "http://localhost:8025").rstrip("/")

    def send(self, msg: EmailMessage) -> str:
        with smtplib.SMTP(self.host, self.port, timeout=30) as s:
            s.send_message(msg)
        return str(msg["Message-ID"])

    def find_sent(self, message_id: str, action_id: str) -> bool:
        try:
            r = httpx.get(f"{self.api}/api/v1/search", params={"query": f"message-id:{message_id.strip('<>')}"}, timeout=10)
            r.raise_for_status()
            return int(r.json().get("messages_count", len(r.json().get("messages", [])))) > 0
        except httpx.HTTPError as e:
            raise SourceUnavailable("mailpit_api", type(e).__name__) from e

    def count(self, message_id: str) -> int:
        r = httpx.get(f"{self.api}/api/v1/search", params={"query": f"message-id:{message_id.strip('<>')}"}, timeout=10)
        return int(r.json().get("messages_count", 0))


def make_provider(settings, mail_cfg: dict, name: str | None = None) -> MailProvider:
    n = (name or settings.mail_provider or "mailpit").lower()
    return GmailSMTP(settings, mail_cfg) if n == "gmail" else Mailpit(settings, mail_cfg)
