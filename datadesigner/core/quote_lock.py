"""Quote lock (plan §3.1C, ARCHITECTURE §10): nothing enters the evidence ledger unless its passage
exists verbatim (after normalisation) in a stored blob, or its JSON field equals the stored value."""
from __future__ import annotations

import json
from typing import Any

from . import normalize


def lock(passage: str, raw: str | bytes) -> int | None:
    """Offset of `passage` in `raw` after normalisation, else None. Empty/short passages never lock."""
    if not passage or len(passage.strip()) < 3:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "ignore")
    hay, needle = normalize.loose(raw), normalize.loose(passage)
    i = hay.find(needle)
    return None if i < 0 else i


def get_path(obj: Any, path: str) -> Any:
    """Resolve 'a.b[0].c' (also numeric list indices as '.0.') in a JSON object."""
    cur = obj
    for part in path.replace("[", ".").replace("]", "").split("."):
        if part == "":
            continue
        if isinstance(cur, list):
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(path)
    return cur


def lock_field(path: str, value: Any, raw: str | bytes | dict | list) -> bool:
    """True if `path` resolves in the stored JSON and equals `value` (floats compared to 1e-9)."""
    try:
        obj = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        got = get_path(obj, path)
    except Exception:  # noqa: BLE001
        return False
    if isinstance(got, float) or isinstance(value, float):
        try:
            return abs(float(got) - float(value)) < 1e-9
        except (TypeError, ValueError):
            return False
    return got == value
