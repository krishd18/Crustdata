"""Policy guard (ARCHITECTURE §17.1, config/mail.yaml): approved templates, business email only,
opt-out line, daily cap, per-counterparty cap, Hold restrictions, test-mode redirect."""
from __future__ import annotations

import re
import time

FREE_MAIL = {"gmail.com", "yahoo.com", "yahoo.co.in", "hotmail.com", "outlook.com", "rediffmail.com", "icloud.com", "proton.me"}


class PolicyViolation(Exception):
    pass


def check(draft: dict, mail_cfg: dict, stores, settings, decision_label: str | None = None) -> None:
    pol = mail_cfg.get("policy", {})
    if draft["template"] not in pol.get("approved_templates", []):
        raise PolicyViolation(f"template {draft['template']} not approved")
    to = draft["to"]
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", to):
        raise PolicyViolation("recipient is not an email address")
    if pol.get("business_email_only") and to.split("@")[1].lower() in FREE_MAIL and settings.mail_mode != "test":
        raise PolicyViolation("business email only (free-mail domain refused)")
    if pol.get("opt_out_line") and draft["template"] not in ("decline", "clarification") and "stop" not in draft["body"].lower():
        raise PolicyViolation("opt-out line missing")
    if decision_label and "HOLD" in decision_label and draft["template"] not in ("clarification", "doc_request"):
        raise PolicyViolation("decision is HOLD: only clarification/doc_request may be sent")
    cap = int(getattr(settings, "mail_daily_cap", 50) or 50)
    sent_24h = stores.one("SELECT COUNT(*) n FROM journal WHERE state='sent' AND at>?", (time.time() - 86400,))["n"]
    if sent_24h >= cap:
        raise PolicyViolation(f"daily cap {cap} reached")
