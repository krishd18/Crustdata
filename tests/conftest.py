import pytest

MAIL_VARS = ["MAIL_TRANSPORT", "MAIL_FROM", "MAIL_REPLY_TO", "MAIL_BCC", "RESEND_API_KEY",
             "SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USER", "SMTP_PASSWORD"]


@pytest.fixture(autouse=True)
def _no_real_email(monkeypatch):
    """A developer's .env may hold real mail credentials: tests never use them."""
    for v in MAIL_VARS:
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("MAIL_TRANSPORT", "file")
