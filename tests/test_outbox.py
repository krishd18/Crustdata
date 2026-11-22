"""Real email transports: Resend (idempotent) and SMTP (not), with the journal's safety rules."""
import smtplib
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import outbox, store


@pytest.fixture(autouse=True)
def _db():
    store.init()


def _draft(**kw):
    tag = uuid.uuid4().hex[:8]
    return outbox.draft(f"d_{tag}", f"r_{tag}", "deals@counterparty.example", "Docs request",
                        f"1. EPFO ECR ({tag})", **kw)


class FakeResponse:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def _resend(monkeypatch, responses):
    monkeypatch.setenv("MAIL_TRANSPORT", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("MAIL_FROM", "deals@buyer.example")
    calls = []

    def post(url, json=None, headers=None, timeout=None):
        calls.append({"url": url, "json": json, "headers": headers})
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(outbox.httpx, "post", post)
    return calls


def test_resend_sends_with_idempotency_key_and_display_name(monkeypatch):
    calls = _resend(monkeypatch, [FakeResponse(200, {"id": "em_123"})])
    row = _draft(from_name="Acme Strategy")
    out = outbox.approve_and_send(row["idem_key"], "Priya")
    assert out["status"] == "sent" and out["transport"] == "resend" and out["provider_id"] == "em_123"
    assert calls[0]["headers"]["Idempotency-Key"] == row["idem_key"]
    assert calls[0]["json"]["from"] == "Acme Strategy <deals@buyer.example>"
    assert calls[0]["json"]["to"] == ["deals@counterparty.example"]
    # approving again never calls the provider
    assert outbox.approve_and_send(row["idem_key"], "Priya")["result"] == "already-sent"
    assert len(calls) == 1 and outbox.transport.deliveries(row["idem_key"]) == 1


def test_resend_rejection_is_failed_and_retry_after_fix_sends(monkeypatch):
    calls = _resend(monkeypatch, [FakeResponse(401, {"name": "invalid_api_key", "message": "bad key"}),
                                  FakeResponse(200, {"id": "em_9"})])
    row = _draft()
    out = outbox.approve_and_send(row["idem_key"], "Priya")
    assert out["status"] == "failed" and out["inflight"] == 0 and "invalid_api_key" in out["last_error"]
    out = outbox.retry(row["idem_key"], "Priya")
    assert out["status"] == "sent" and len(calls) == 2


def test_resend_timeout_retries_same_key_inside_window_only(monkeypatch):
    calls = _resend(monkeypatch, [httpx.ReadTimeout("slow"), FakeResponse(200, {"id": "em_1"})])
    row = _draft()
    out = outbox.approve_and_send(row["idem_key"], "Priya")
    assert out["status"] == "failed" and out["inflight"] == 1 and "[ambiguous]" in out["last_error"]
    out = outbox.retry(row["idem_key"], "Priya")  # safe: Resend dedupes on the same key
    assert out["status"] == "sent"
    assert calls[0]["headers"]["Idempotency-Key"] == calls[1]["headers"]["Idempotency-Key"]

    calls2 = _resend(monkeypatch, [httpx.ReadTimeout("slow")])
    row2 = _draft()
    outbox.approve_and_send(row2["idem_key"], "Priya")
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    store.x("UPDATE outbox SET last_attempt_at=? WHERE idem_key=?", (old, row2["idem_key"]))
    out = outbox.retry(row2["idem_key"], "Priya")
    assert out["status"] == "uncertain" and len(calls2) == 1  # window passed: held for a person


class FakeSMTP:
    sent = []
    fail_on_send = None
    fail_on_login = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def starttls(self, context=None):
        pass

    def login(self, user, pw):
        if FakeSMTP.fail_on_login:
            raise FakeSMTP.fail_on_login

    def send_message(self, m, to_addrs=None):
        if FakeSMTP.fail_on_send:
            raise FakeSMTP.fail_on_send
        FakeSMTP.sent.append((m, to_addrs))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def smtp(monkeypatch):
    monkeypatch.setenv("MAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_USER", "me@buyer.example")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("MAIL_FROM", "Acme Strategy <me@buyer.example>")
    monkeypatch.setenv("MAIL_BCC", "team@buyer.example")
    FakeSMTP.sent, FakeSMTP.fail_on_send, FakeSMTP.fail_on_login = [], None, None
    monkeypatch.setattr(outbox.smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def test_smtp_sends_with_stable_message_id_and_bcc(smtp):
    row = _draft()
    out = outbox.approve_and_send(row["idem_key"], "Priya")
    assert out["status"] == "sent" and out["transport"] == "smtp"
    m, to = smtp.sent[0]
    assert m["Message-ID"] == f"<{row['idem_key']}@buyer.example>"
    assert to == ["deals@counterparty.example", "team@buyer.example"] and "Bcc" not in m
    assert m["From"] == "Acme Strategy <me@buyer.example>"


def test_smtp_login_failure_is_permanent_and_safe_to_retry(smtp):
    smtp.fail_on_login = smtplib.SMTPAuthenticationError(535, b"bad credentials")
    row = _draft()
    out = outbox.approve_and_send(row["idem_key"], "Priya")
    assert out["status"] == "failed" and out["inflight"] == 0 and "login failed" in out["last_error"]
    smtp.fail_on_login = None
    assert outbox.retry(row["idem_key"], "Priya")["status"] == "sent" and len(smtp.sent) == 1


def test_smtp_dropped_mid_send_is_never_repeated_by_the_machine(smtp):
    smtp.fail_on_send = smtplib.SMTPServerDisconnected("gone")
    row = _draft()
    out = outbox.approve_and_send(row["idem_key"], "Priya")
    assert out["status"] == "failed" and out["inflight"] == 1
    smtp.fail_on_send = None
    out = outbox.retry(row["idem_key"], "Priya")
    assert out["status"] == "uncertain" and smtp.sent == []
    with pytest.raises(PermissionError):
        outbox.retry(row["idem_key"], "Priya")  # needs the person's confirmation
    out = outbox.retry(row["idem_key"], "Priya", confirm_not_sent=True)
    assert out["status"] == "sent" and len(smtp.sent) == 1


def test_smtp_recovery_holds_interrupted_send(smtp):
    row = _draft()
    store.x("UPDATE outbox SET status='approved', approved_by='Priya', attempts=1, inflight=1, transport='smtp',"
            " last_attempt_at=? WHERE idem_key=?", (datetime.now(timezone.utc).isoformat(), row["idem_key"]))
    outbox.recover()
    assert outbox._row(row["idem_key"])["status"] == "uncertain" and smtp.sent == []
    assert outbox.mark_sent(row["idem_key"], "Priya")["status"] == "sent"


def test_unconfigured_transport_fails_without_sending(monkeypatch):
    monkeypatch.setenv("MAIL_TRANSPORT", "resend")
    row = _draft()
    out = outbox.approve_and_send(row["idem_key"], "Priya")
    assert out["status"] == "failed" and "RESEND_API_KEY" in out["last_error"] and "MAIL_FROM" in out["last_error"]
    assert outbox.describe()["ready"] is False


def test_address_validation():
    assert outbox.valid_address("deals@counterparty.example")
    assert not outbox.valid_address("a@b.example, c@d.example")
    assert not outbox.valid_address("not-an-email")
