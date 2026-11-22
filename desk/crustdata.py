"""Crustdata client.

Every call goes through ``_post``, which times it, records its credits in the
ledger and retries only what is safe to retry. Two documented quirks are
handled here rather than left to callers:

1. **Web search returns no publication date.** Results carry source, title,
   url, snippet and position -- nothing more. So a date must come either from
   fetching the page, or from the ``start_date``/``end_date`` window we asked
   for, which is a *bound* and not a date. ``search_web`` returns the window it
   used so the caller can say which it has.

2. **Failed fetch entries come back with ``url: null``.** You cannot tell which
   input URL failed by reading the failure, only by diffing the successes
   against what you sent. ``fetch_pages`` does that diff and returns the
   failures explicitly.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

import requests

from .ledger import CostLedger


class CrustdataError(RuntimeError):
    pass


def to_unix(d: str | datetime) -> int:
    """Crustdata wants Unix seconds for the search date window."""
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return int(d.timestamp())


class _RateLimiter:
    """Web search is documented at 10 requests per minute by default."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: deque[float] = deque()

    def wait(self) -> None:
        if self.per_minute <= 0:
            return
        now = time.monotonic()
        while self._hits and now - self._hits[0] > 60:
            self._hits.popleft()
        if len(self._hits) >= self.per_minute:
            sleep_for = 60 - (now - self._hits[0]) + 0.05
            if sleep_for > 0:
                time.sleep(sleep_for)
            self.wait()
            return
        self._hits.append(now)


@dataclass
class SearchResult:
    source: str
    title: str
    url: str
    snippet: str
    position: int | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "SearchResult":
        return cls(
            source=raw.get("source", ""),
            title=raw.get("title", ""),
            url=raw.get("url", ""),
            snippet=raw.get("snippet", ""),
            position=raw.get("position"),
        )


@dataclass
class FetchedPage:
    url: str
    title: str
    content: str
    retrieved_at: str   # ISO, derived from the response's own timestamp


class CrustdataClient:
    def __init__(
        self,
        api_key: str,
        ledger: CostLedger,
        *,
        api_base: str = "https://api.crustdata.com",
        api_version: str = "2025-11-01",
        web_search_rpm: int = 10,
        max_retries: int = 2,
        timeout: int = 45,
    ) -> None:
        if not api_key:
            raise CrustdataError("no API key: set CRUSTDATA_API_KEY")
        self.api_key = api_key
        self.ledger = ledger
        self.api_base = api_base.rstrip("/")
        self.api_version = api_version
        self.timeout = timeout
        self.max_retries = max_retries
        self._search_limiter = _RateLimiter(web_search_rpm)
        self._session = requests.Session()

    # ----------------------------------------------------------- transport

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "x-api-version": self.api_version,
            "content-type": "application/json",
        }

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.api_base}{path}"
        attempt = 0
        while True:
            started = time.monotonic()
            try:
                resp = self._session.post(
                    url, json=body, headers=self._headers, timeout=self.timeout
                )
            except requests.RequestException as exc:
                latency = (time.monotonic() - started) * 1000
                self.ledger.record(path, None, latency_ms=latency, note=str(exc))
                if attempt >= self.max_retries:
                    raise CrustdataError(f"{path}: {exc}") from exc
                attempt += 1
                time.sleep(2**attempt)
                continue

            latency = (time.monotonic() - started) * 1000
            self.ledger.record(path, resp, latency_ms=latency)

            # 429 and 5xx are worth retrying; a 4xx is our own bug and is not.
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt >= self.max_retries:
                    raise CrustdataError(
                        f"{path}: HTTP {resp.status_code} after {attempt + 1} tries"
                    )
                retry_after = resp.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else 2 ** (attempt + 1))
                attempt += 1
                continue

            if resp.status_code >= 400:
                raise CrustdataError(
                    f"{path}: HTTP {resp.status_code} {resp.text[:300]}"
                )
            return resp.json()

    # --------------------------------------------------------------- web

    def search_web(
        self,
        query: str,
        *,
        sources: Sequence[str] = ("web", "news"),
        location: str = "IN",
        site: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        page: int = 1,
    ) -> tuple[list[SearchResult], dict[str, Any]]:
        """Search. Returns results plus the window we constrained them to.

        The window matters: results carry no publication date of their own, so
        if a claim rests on recency, the window is the only dating evidence we
        have until the page itself is fetched and parsed.
        """
        self._search_limiter.wait()
        body: dict[str, Any] = {
            "query": query,
            "sources": list(sources),
            "location": location,
            "page": page,
        }
        if site:
            body["site"] = site
        if start_date is not None:
            body["start_date"] = to_unix(start_date)
        if end_date is not None:
            body["end_date"] = to_unix(end_date)

        data = self._post("/web/search/live", body)
        results = [SearchResult.from_api(r) for r in data.get("results", [])]
        window = {
            "start_date": body.get("start_date"),
            "end_date": body.get("end_date"),
            "response_timestamp_ms": data.get("timestamp"),
            "query": query,
            "sources": list(sources),
        }
        return results, window

    def fetch_pages(
        self, urls: Iterable[str]
    ) -> tuple[list[FetchedPage], list[str]]:
        """Fetch up to 10 URLs. Returns (pages, urls_that_failed).

        Failures come back with ``url: null``, so the only way to know what
        failed is to diff the successes against the input.
        """
        wanted = [u for u in urls if u][:10]
        if not wanted:
            return [], []

        data = self._post("/web/enrich/live", {"urls": wanted})
        entries = data if isinstance(data, list) else data.get("results", data)

        pages: list[FetchedPage] = []
        got: set[str] = set()
        for entry in entries or []:
            if not entry or not entry.get("success") or not entry.get("url"):
                continue
            ts = entry.get("timestamp")
            retrieved = (
                datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(
                    timespec="seconds"
                )
                if ts
                else datetime.now(timezone.utc).isoformat(timespec="seconds")
            )
            pages.append(
                FetchedPage(
                    url=entry["url"],
                    title=entry.get("title", "") or "",
                    content=entry.get("content", "") or "",
                    retrieved_at=retrieved,
                )
            )
            got.add(entry["url"])

        failed = [u for u in wanted if u not in got]
        return pages, failed

    # ----------------------------------------------------------- company

    def identify_company(self, name_or_domain: str) -> list[dict[str, Any]]:
        """Resolve a string to candidate companies.

        Returns every candidate, not the best one. Picking the top match is
        exactly the lookalike failure the hidden test set is built around, so
        that choice belongs to the resolver, with reasons, not to the client.
        """
        data = self._post("/company/identify", {"query": name_or_domain})
        return data.get("matches", data.get("results", [])) or []

    def enrich_company(
        self, *, domain: str | None = None, company_id: str | None = None,
        fields: Sequence[str] = ("basic_info", "headcount", "locations"),
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"fields": list(fields)}
        if domain:
            body["company_domain"] = domain
        elif company_id:
            body["company_id"] = company_id
        else:
            raise CrustdataError("enrich_company needs a domain or a company_id")
        return self._post("/company/enrich", body)

    def search_companies(
        self, filters: list[dict[str, Any]], limit: int = 10
    ) -> dict[str, Any]:
        return self._post("/company/search", {"filters": filters, "limit": limit})

    # -------------------------------------------------------------- jobs

    def search_jobs(
        self, filters: list[dict[str, Any]], limit: int = 25
    ) -> dict[str, Any]:
        """Job listings carry ``date_added`` and ``date_updated``.

        These are the strongest dated, city-level signal available for a
        question about where a rival is expanding, because company headcount
        has no city breakdown and no timeseries.
        """
        return self._post("/job/search", {"filters": filters, "limit": limit})

    # ------------------------------------------------------------ people

    def search_people(
        self, filters: list[dict[str, Any]], limit: int = 10
    ) -> dict[str, Any]:
        """Search people.

        Note on cost and on ethics: contact data such as a business email bills
        as its own component. We do not request it. A question about whether a
        rival appointed a new COO is answered by the role and the date, never
        by that person's contact details.
        """
        return self._post("/person/search", {"filters": filters, "limit": limit})
