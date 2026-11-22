"""Cross-source inconsistency detection.

Compares the target's *own* statements across sources (deck, website pages,
its company-profile description, founders' profile summaries). No outside
verdict is needed: if the company says 40% in one place and 25% in another,
that is worth raising either way.
"""
from __future__ import annotations

from collections import defaultdict

from .models import Claim

SKIP = {None, "other"}


def find(claims_by_source: dict[str, tuple[list[Claim], str | None]]) -> list[dict]:
    """claims_by_source: {source label: (claims, url)} -> list of conflicts."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for label, (claims, url) in claims_by_source.items():
        for c in claims:
            if c.metric in SKIP or c.number is None:
                continue
            key = c.metric
            if c.metric in ("warehouses", "sites") and c.place:
                key = f"{c.metric}:{c.place.lower()}"
            groups[key].append({"source": label, "url": url, "value": float(c.number), "text": c.text})

    out = []
    for key, items in groups.items():
        sources = {i["source"] for i in items}
        if len(sources) < 2:
            continue
        vals = sorted({i["value"] for i in items})
        lo, hi = vals[0], vals[-1]
        exact = key.startswith("founded_year")
        if (exact and lo != hi) or (not exact and hi > 0 and (hi - lo) / hi > 0.10):
            out.append({
                "metric": key,
                "values": items,
                "summary": " vs ".join(f"{_f(i['value'])} ({i['source']})" for i in items),
            })
    return out


def _f(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else str(v)
