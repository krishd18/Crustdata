"""Normalisation (plan §3.1C): NFKC, whitespace, Indian digit grouping, ₹/Rs./INR, lakh/crore/mn/bn,
company suffixes. Used by quote lock and verdict tolerances (STANDARDS §2.2)."""
from __future__ import annotations

import re
import unicodedata

UNITS = {"lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7,
         "mn": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9, "k": 1e3, "thousand": 1e3}
SUFFIXES = [(r"\bprivate limited\b", "pvt ltd"), (r"\bpvt\.?\s*ltd\.?", "pvt ltd"), (r"\blimited\b", "ltd"),
            (r"\bltd\.", "ltd"), (r"\bl\.?l\.?p\.?\b", "llp"), (r"\bprivate\b", "pvt")]
ZW = dict.fromkeys(map(ord, "​‌‍﻿"), None)


def text(s: str) -> str:
    """NFKC + strip zero-width + collapse whitespace + unify currency signs + drop digit grouping."""
    s = unicodedata.normalize("NFKC", s or "").translate(ZW)
    s = re.sub(r"\b(?:rs\.?|inr)\s*", "₹", s, flags=re.I)
    s = re.sub(r"(?<=\d),(?=\d)", "", s)
    return re.sub(r"\s+", " ", s).strip()


def loose(s: str) -> str:
    """text() + casefold + unify quotes/dashes (for verbatim matching tolerant of typography)."""
    s = text(s).casefold()
    return s.translate(str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}))


def company_name(s: str) -> str:
    s = loose(s).replace("&", "and")
    for rx, rep in SUFFIXES:
        s = re.sub(rx, rep, s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_amount(s: str) -> tuple[float | None, str | None]:
    """'₹1,20,00,000' → (12000000,'INR'); '1.2 crore' → (12000000,'INR'); '$12 million' → (12000000,'USD').
    Currency is None when unstated; callers must not compare amounts in different currencies (H9b)."""
    t = text(s).lower()
    cur = "USD" if ("$" in t or "usd" in t) else ("INR" if ("₹" in t or "crore" in t or "lakh" in t or " cr" in t) else None)
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*(lakhs?|lac|crores?|cr|mn|million|bn|billion|k|thousand)?\b", t)
    if not m:
        return None, cur
    v = float(m.group(1)) * UNITS.get((m.group(2) or "").lower(), 1)
    return v, cur


def within(a: float, b: float, pct: float) -> bool:
    if b == 0:
        return a == 0
    return abs(a - b) / abs(b) * 100 <= pct + 1e-9
