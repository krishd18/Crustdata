"""Find passages that state a claim, with a date, or find nothing.

The pipeline per claim:

    search (date-windowed)  ->  fetch pages  ->  split into passages
      ->  entailment check  ->  date the page  ->  Evidence

Two things it refuses to do, both of which make the difference between
evidence and decoration:

* It will not cite a snippet. Search snippets are truncated and often
  rewritten, so a snippet cannot honestly be quoted as what the source says.
  Only fetched page text is quotable.
* It will not keep a passage that fails the entailment check, however good the
  source looks.

Independence is counted by registrable domain, not by URL. Three articles
syndicated across three paths of one site are one source, and treating them as
three is the easiest way to clear an evidence bar without any new evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from .crustdata import CrustdataClient, CrustdataError, SearchResult
from .dating import date_of_page
from .entail import EntailmentChecker
from .models import DateKind, Evidence, SourceKind

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

_REGISTRY_HOSTS = ("mca.gov.in", "gst.gov.in", "nic.in", "gov.in")
_FILING_HOSTS = ("bseindia.com", "nseindia.com", "sebi.gov.in")


def registrable_domain(url: str) -> str:
    """Enough of the host to tell two publishers apart.

    Deliberately crude: a public-suffix list is not worth the dependency here,
    and the Indian two-level suffixes that matter (co.in, com, net.in, gov.in,
    org.in) are handled explicitly.
    """
    m = re.match(r"https?://([^/]+)", url.strip(), re.I)
    if not m:
        return url.strip().lower()
    host = m.group(1).lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level = {"co", "com", "net", "org", "gov", "ac", "edu", "nic"}
    if parts[-1] == "in" and parts[-2] in two_level:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def source_kind_for(url: str, *, from_job: bool = False) -> SourceKind:
    if from_job:
        return SourceKind.JOB_POSTING
    host = registrable_domain(url)
    if any(host.endswith(h) for h in _REGISTRY_HOSTS):
        return SourceKind.REGISTRY
    if any(host.endswith(h) for h in _FILING_HOSTS):
        return SourceKind.FILING
    return SourceKind.NEWS


def clean_text(html: str) -> str:
    text = _TAG.sub(" ", html)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    return _WS.sub(" ", text).strip()


def passages(text: str, *, max_chars: int = 420) -> list[tuple[str, int]]:
    """Split into quotable spans, each with its offset into the text.

    Spans are sentence-sized, with single short sentences merged into their
    neighbour, because a lone "He declined to comment." states nothing while
    the pair around it may.
    """
    out: list[tuple[str, int]] = []
    cursor = 0
    buffer = ""
    buffer_at = 0
    for sentence in _SENTENCE.split(text):
        sentence = sentence.strip()
        if not sentence:
            continue
        at = text.find(sentence, cursor)
        if at == -1:
            at = cursor
        cursor = at + len(sentence)
        if not buffer:
            buffer, buffer_at = sentence, at
        elif len(buffer) + len(sentence) + 1 <= max_chars:
            buffer = f"{buffer} {sentence}"
        else:
            out.append((buffer, buffer_at))
            buffer, buffer_at = sentence, at
    if buffer:
        out.append((buffer, buffer_at))
    return out


def rank_passages(
    spans: list[tuple[str, int]], claim: str, limit: int
) -> list[tuple[str, int]]:
    """Cheap pre-filter so the model only judges plausible spans.

    Term overlap is a bad judge of entailment but a fine judge of "worth
    reading", and every span it drops is a model call not made.
    """
    terms = {t for t in re.findall(r"[a-z]{4,}", claim.lower())}
    if not terms:
        return spans[:limit]
    scored = []
    for span, at in spans:
        low = span.lower()
        hits = sum(1 for t in terms if t in low)
        if hits:
            scored.append((hits, -at, span, at))
    scored.sort(reverse=True)
    return [(span, at) for _, _, span, at in scored[:limit]]


@dataclass
class Gathering:
    """Everything found for one claim, including what was rejected and why."""

    claim: str
    accepted: list[Evidence] = field(default_factory=list)
    rejected: list[dict] = field(default_factory=list)
    searched: list[str] = field(default_factory=list)
    fetched: list[str] = field(default_factory=list)
    fetch_failures: list[str] = field(default_factory=list)
    window: dict | None = None
    note: str | None = None

    @property
    def independent_domains(self) -> set[str]:
        return {
            e.source_domain
            for e in self.accepted
            if e.source_domain
        }

    def has_registry_source(self) -> bool:
        return any(
            e.source_kind in (SourceKind.REGISTRY, SourceKind.FILING)
            for e in self.accepted
        )


class EvidenceGatherer:
    def __init__(
        self,
        client: CrustdataClient,
        entailment: EntailmentChecker,
        *,
        max_fetches: int = 6,
        max_passages_per_page: int = 4,
        search_pages: int = 1,
    ) -> None:
        self.client = client
        self.entailment = entailment
        self.max_fetches = max_fetches
        self.max_passages_per_page = max_passages_per_page
        self.search_pages = search_pages

    def gather(
        self,
        claim: str,
        *,
        queries: list[str] | None = None,
        since: str | None = None,
        until: str | None = None,
        sources: tuple[str, ...] = ("news", "web"),
        stop_after: int = 3,
    ) -> Gathering:
        g = Gathering(claim=claim)
        queries = queries or [claim]

        results: list[SearchResult] = []
        for query in queries[:3]:
            try:
                found, window = self.client.search_web(
                    query,
                    sources=sources,
                    start_date=since,
                    end_date=until,
                    page=self.search_pages,
                )
            except CrustdataError as exc:
                g.note = f"search failed: {exc}"
                continue
            g.searched.append(query)
            g.window = g.window or window
            results.extend(found)

        # Prefer one page per publisher before taking a second from any.
        seen_domains: set[str] = set()
        ordered: list[SearchResult] = []
        spill: list[SearchResult] = []
        for r in results:
            if not r.url:
                continue
            dom = registrable_domain(r.url)
            if dom in seen_domains:
                spill.append(r)
            else:
                seen_domains.add(dom)
                ordered.append(r)
        ordered.extend(spill)

        urls = [r.url for r in ordered][: self.max_fetches]
        if not urls:
            g.note = g.note or "no search results"
            return g

        try:
            pages, failed = self.client.fetch_pages(urls)
        except CrustdataError as exc:
            g.note = f"fetch failed: {exc}"
            return g

        g.fetched = [p.url for p in pages]
        g.fetch_failures = failed

        window = (
            (g.window or {}).get("start_date"),
            (g.window or {}).get("end_date"),
        )

        for page in pages:
            text = clean_text(page.content)
            if not text:
                continue
            candidates = rank_passages(
                passages(text), claim, self.max_passages_per_page
            )
            for span, offset in candidates:
                verdict = self.entailment.check(claim, span)
                if not verdict.states_claim:
                    g.rejected.append(
                        {
                            "url": page.url,
                            "passage": span[:200],
                            "score": verdict.score,
                            "why": verdict.why,
                        }
                    )
                    continue

                dated = date_of_page(
                    page.content,
                    near=span,
                    retrieved_at=page.retrieved_at,
                    search_window=window,
                )
                g.accepted.append(
                    Evidence(
                        claim=claim,
                        exact_passage=span,
                        source_url=page.url,
                        source_kind=source_kind_for(page.url),
                        record_date=dated.value if dated.is_a_real_date else None,
                        date_kind=dated.kind,
                        retrieved_at=page.retrieved_at,
                        passage_offset=offset,
                        entailment_score=verdict.score,
                        source_domain=registrable_domain(page.url),
                        note=dated.why,
                    )
                )
                break  # one passage per page is enough; move to the next source

            if len(g.independent_domains) >= stop_after:
                break

        return g

    # ---------------------------------------------------------------- jobs

    def gather_hiring_signal(
        self,
        company_terms: list[str],
        city: str,
        since: str,
        *,
        limit: int = 25,
    ) -> Gathering:
        """City-level hiring evidence from dated job listings.

        This exists because company enrichment cannot answer it: headcount has
        no city breakdown and no timeseries, so "started hiring in Guwahati"
        has to come from listings, which do carry ``date_added``.
        """
        claim = f"{company_terms[0]} posted job listings in {city} on or after {since}"
        g = Gathering(claim=claim)

        filters = [
            {"field": "company_name", "type": "in", "value": company_terms},
            {"field": "location", "type": "contains", "value": city},
        ]
        try:
            data = self.client.search_jobs(filters, limit=limit)
        except CrustdataError as exc:
            g.note = f"job search failed: {exc}"
            return g

        listings = data.get("results", data.get("jobs", [])) or []
        kept = []
        for job in listings:
            posted = str(job.get("date_added") or job.get("date_updated") or "")[:10]
            if not posted:
                continue
            try:
                if date.fromisoformat(posted) < date.fromisoformat(since[:10]):
                    continue
            except ValueError:
                continue
            kept.append((posted, job))

        if not kept:
            g.note = (
                f"no listings for {company_terms[0]} in {city} dated on or after "
                f"{since}. Absence of listings is not evidence that hiring stopped."
            )
            return g

        kept.sort(reverse=True)
        for posted, job in kept[:5]:
            title = str(job.get("title") or job.get("job_title") or "role")
            location = str(job.get("location") or city)
            url = str(job.get("url") or job.get("job_url") or "")
            g.accepted.append(
                Evidence(
                    claim=claim,
                    exact_passage=f"{title} — {location} — posted {posted}",
                    source_url=url,
                    source_kind=SourceKind.JOB_POSTING,
                    record_date=posted,
                    date_kind=DateKind.POSTED,
                    entailment_score=1.0,
                    source_domain=registrable_domain(url) if url else "crustdata-jobs",
                    note="dated job listing from Crustdata job search",
                )
            )
        return g


def default_window(days_back: int = 120) -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    return (today - timedelta(days=days_back)).isoformat(), today.isoformat()
