"""structlog JSON logs through a PII/secret redactor (plan §3.1C)."""
from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

REDACT = [
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "sk-ant-[REDACTED]"),
    (re.compile(r"cd_[0-9a-f]{8,}"), "cd_[REDACTED]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{12,}"), "Bearer [REDACTED]"),
    (re.compile(r"\b[a-z]{4}\s?[a-z]{4}\s?[a-z]{4}\s?[a-z]{4}\b(?=.*(app|password))", re.I), "[APP-PASSWORD]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+91[\-\s]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR?]"),
]


def redact(s: str) -> str:
    for rx, rep in REDACT:
        s = rx.sub(rep, s)
    return s


def _redactor(_: Any, __: str, event: dict) -> dict:
    return {k: (redact(v) if isinstance(v, str) else v) for k, v in event.items()}


_configured = False


def get_logger(name: str = "dd"):
    global _configured
    if not _configured:
        logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
        structlog.configure(
            processors=[structlog.processors.TimeStamper(fmt="iso"), structlog.processors.add_log_level,
                        _redactor, structlog.processors.JSONRenderer(sort_keys=True)],
            logger_factory=structlog.stdlib.LoggerFactory(),
        )
        _configured = True
    return structlog.get_logger(name)
