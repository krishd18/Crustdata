"""Give a fact a date, and say what kind of date it is.

Crustdata web search returns no publication date, so the date has to come from
somewhere else. In order of how much they are worth:

1. **Structured metadata on the fetched page** -- JSON-LD ``datePublished``,
   ``article:published_time``, and friends. This is the page asserting its own
   publication date, which is the thing the brief asks for.
2. **A visible date in the text near the passage.** Weaker: it may be the date
   of something the article describes rather than of the article.
3. **The search window we constrained the query to.** This is a *bound*, not a
   date: it says the result fell inside a range, not when it was published.
4. **The retrieval timestamp.** Says only that the page said this today.

Reporting a bound as if it were a date is the quiet way to be wrong here, so
the kind travels with the value everywhere and is printed in the output.

A modified date is never promoted to a published date. They answer different
questions, and an article edited last week may describe something from 2019.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .models import DateKind

# Structured metadata, best first.
_META_PATTERNS: list[tuple[str, str]] = [
    ("published", r'<meta[^>]+property=["\']article:published_time["\'][^>]+content=["\']([^"\']+)'),
    ("published", r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']article:published_time["\']'),
    ("published", r'<meta[^>]+name=["\'](?:pubdate|publishdate|publish-date|date|DC\.date\.issued|parsely-pub-date)["\'][^>]+content=["\']([^"\']+)'),
    ("published", r'<meta[^>]+itemprop=["\']datePublished["\'][^>]+content=["\']([^"\']+)'),
    ("published", r'<time[^>]+datetime=["\']([^"\']+)["\'][^>]*>'),
    ("modified", r'<meta[^>]+property=["\']article:modified_time["\'][^>]+content=["\']([^"\']+)'),
    ("modified", r'<meta[^>]+itemprop=["\']dateModified["\'][^>]+content=["\']([^"\']+)'),
]

_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|"
    "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)

_VISIBLE_PATTERNS = [
    rf"\b(\d{{1,2}})\s+({_MONTHS})\s+(\d{{4}})\b",      # 14 October 2026
    rf"\b({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})\b",    # October 14, 2026
    r"\b(\d{4})-(\d{2})-(\d{2})\b",                     # 2026-10-14
]

_MONTH_NUM = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


@dataclass
class DatedFact:
    value: str | None          # ISO date, or None when nothing could be found
    kind: DateKind
    confidence: str            # strong | weak | bound | none
    why: str

    @property
    def is_a_real_date(self) -> bool:
        """True only when the record itself carries a date.

        A bound and a retrieval timestamp are not dates on the record, and the
        evidence bar must not treat them as though they were.
        """
        return self.kind in (DateKind.PUBLISHED, DateKind.POSTED, DateKind.FILED)


def _parse_iso(raw: str) -> str | None:
    raw = raw.strip()
    try:
        cleaned = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(cleaned).date().isoformat()
    except ValueError:
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        try:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        except ValueError:
            return None
    return None


def _from_jsonld(html: str) -> tuple[str | None, str | None]:
    """Return (published, modified) from any JSON-LD block on the page."""
    published = modified = None
    for block in re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.S | re.I,
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            nodes = graph if isinstance(graph, list) else [node]
            for n in nodes:
                if not isinstance(n, dict):
                    continue
                published = published or n.get("datePublished") or n.get("dateCreated")
                modified = modified or n.get("dateModified")
    return (
        _parse_iso(published) if isinstance(published, str) else None,
        _parse_iso(modified) if isinstance(modified, str) else None,
    )


def _visible_dates(text: str) -> list[str]:
    out: list[str] = []
    low = text.lower()
    for pattern in _VISIBLE_PATTERNS:
        for m in re.finditer(pattern, low, re.I):
            groups = m.groups()
            try:
                if re.fullmatch(r"\d{4}", groups[0]):
                    y, mo, d = int(groups[0]), int(groups[1]), int(groups[2])
                elif groups[0].isdigit():
                    d, mo, y = int(groups[0]), _MONTH_NUM[groups[1]], int(groups[2])
                else:
                    mo, d, y = _MONTH_NUM[groups[0]], int(groups[1]), int(groups[2])
                out.append(date(y, mo, d).isoformat())
            except (ValueError, KeyError):
                continue
    return out


def date_of_page(
    html: str,
    *,
    near: str | None = None,
    retrieved_at: str | None = None,
    search_window: tuple[int | None, int | None] | None = None,
) -> DatedFact:
    """Best available date for a fetched page, labelled by kind and strength.

    ``near`` is the passage we intend to cite. When given, a visible date close
    to it is preferred over one elsewhere on the page, because a long page
    often carries many dates and only some belong to the claim.
    """
    published, modified = _from_jsonld(html)
    if published:
        return DatedFact(published, DateKind.PUBLISHED, "strong", "JSON-LD datePublished")

    for kind, pattern in _META_PATTERNS:
        m = re.search(pattern, html, re.I)
        if not m:
            continue
        parsed = _parse_iso(m.group(1))
        if not parsed:
            continue
        if kind == "published":
            return DatedFact(parsed, DateKind.PUBLISHED, "strong", "page metadata")
        # A modified date is reported as what it is, and stays weak. It does
        # not become a publication date just because no better date exists.
        modified = modified or parsed

    text = re.sub(r"<[^>]+>", " ", html)
    window_text = text
    if near:
        idx = text.find(near[:80])
        if idx != -1:
            window_text = text[max(0, idx - 600) : idx + 600]

    visible = _visible_dates(window_text)
    if visible:
        return DatedFact(
            max(visible),
            DateKind.PUBLISHED,
            "weak",
            "a date visible in the page text near the passage; "
            "may be the date of the event rather than of the page",
        )

    if modified:
        return DatedFact(
            modified,
            DateKind.UNKNOWN,
            "weak",
            "only a modified date was found; the page does not state when it "
            "was first published",
        )

    if search_window and (search_window[0] or search_window[1]):
        start, end = search_window
        bound = []
        if start:
            bound.append(
                datetime.fromtimestamp(start, tz=timezone.utc).date().isoformat()
            )
        if end:
            bound.append(
                datetime.fromtimestamp(end, tz=timezone.utc).date().isoformat()
            )
        return DatedFact(
            None,
            DateKind.UNKNOWN,
            "bound",
            "no date on the record; the search was constrained to "
            + " to ".join(bound),
        )

    return DatedFact(
        retrieved_at,
        DateKind.RETRIEVED,
        "none",
        "no date on the record; this is only when we fetched it",
    )


def in_window(
    value: str | None, start: str | None = None, end: str | None = None
) -> bool:
    """Is this date inside the window the question asks about?"""
    if not value:
        return False
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return False
    if start and d < date.fromisoformat(start[:10]):
        return False
    if end and d > date.fromisoformat(end[:10]):
        return False
    return True


def age_days(value: str | None, *, today: date | None = None) -> int | None:
    if not value:
        return None
    try:
        d = date.fromisoformat(value[:10])
    except ValueError:
        return None
    return ((today or datetime.now(timezone.utc).date()) - d).days
