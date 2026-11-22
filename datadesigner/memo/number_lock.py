"""Number lock (plan §4.2C): every number in memo prose must trace to the ledger/run values; a sentence with an
untraceable number is dropped (or the original kept when smoothing)."""
from __future__ import annotations

import re

NUM = re.compile(r"(?<![\w.\-])\d[\d,]*(?:\.\d+)?")


def numbers(s: str) -> set[str]:
    return {n.replace(",", "").lstrip("+").rstrip(".") for n in NUM.findall(s or "")}


def allowed_from(obj) -> set[str]:
    out: set[str] = set()

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
        elif isinstance(x, bool) or x is None:
            return
        elif isinstance(x, (int, float)):
            out.update({str(x), f"{x:g}", f"{float(x):.1f}", f"{float(x):.2f}", str(int(x)) if float(x).is_integer() else str(x)})
        else:
            out.update(numbers(str(x)))
    walk(obj)
    return out


def check_sentence(s: str, allowed: set[str]) -> bool:
    return numbers(s) <= allowed


def lock_text(text: str, allowed: set[str]) -> tuple[str, list[str]]:
    kept, dropped = [], []
    for line in text.splitlines():
        if check_sentence(line, allowed):
            kept.append(line)
        else:
            dropped.append(line)
    return "\n".join(kept), dropped
