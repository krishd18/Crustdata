"""Deterministic ids and hashing."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def sha256(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def canon(obj: Any) -> str:
    """Canonical JSON (sorted keys, no spaces) — the basis of every cache/cassette key."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def short(prefix: str, *parts: Any, n: int = 10) -> str:
    return f"{prefix}-{sha256(canon(parts))[:n]}"
