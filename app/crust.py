"""Thin Crustdata REST client.

Every call records what it cost (X-Credits-Used) and when it was made, so each
verdict can cite the exact API field and its retrieval date.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from . import cancel as _cancel

log = logging.getLogger("secondlook.crust")

BASE_URL = "https://api.crustdata.com"
API_VERSION = "2025-11-01"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CrustError(RuntimeError):
    def __init__(self, path: str, status: int, body: str, waited: float = 0):
        self.path, self.status, self.body, self.waited = path, status, body, waited
        super().__init__(self.friendly)

    @property
    def friendly(self) -> str:
        """What a person sees: plain words, not the raw response."""
        if self.status == 429:
            per = LIMITS.get(self.path)
            return (f"Crustdata's rate limit for {self.path} was reached"
                    + (f" (about {per} calls a minute on this plan)" if per else "")
                    + (f". SecondLook waited {self.waited:.0f} s and retried, but it was still limited" if self.waited else "")
                    + ". Wait a minute and try again.")
        if self.status in (401, 403):
            return f"Crustdata refused {self.path} (HTTP {self.status}): check CRUSTDATA_API_TOKEN and the plan's access."
        if self.status == 402:
            return "Crustdata says the account is out of credits (HTTP 402)."
        if self.status >= 500:
            return f"Crustdata had a server error on {self.path} (HTTP {self.status}). Try again shortly."
        return f"{self.path} -> HTTP {self.status}: {self.body[:300]}"


# ---- rate limits -------------------------------------------------------------
# Crustdata limits requests per endpoint per minute (docs: /company/enrich defaults to
# 15/min). Calls are paced process-wide, across every run and search, so parallel work
# doesn't burst past the limit. Override with CRUSTDATA_RATE_LIMITS="/company/enrich=15,...".
LIMITS = {"/company/enrich": 15, "/company/search": 15, "/person/enrich": 15, "/company/identify": 15}
for _kv in filter(None, os.getenv("CRUSTDATA_RATE_LIMITS", "").split(",")):
    _k, _, _v = _kv.partition("=")
    if _v.strip().isdigit():
        LIMITS[_k.strip()] = int(_v)
MAX_WAIT = float(os.getenv("CRUSTDATA_MAX_WAIT", "75"))  # seconds one call may wait on 429s

_rl_lock = threading.Lock()
_sent: dict[str, deque] = {}       # path -> send times in the last 60 s
_blocked: dict[str, float] = {}    # path -> time.time() before which nothing is sent (after a 429)


def _reserve(path: str) -> float:
    """Seconds to wait before this call may go out (0 = go now, and the slot is taken)."""
    now = time.time()
    with _rl_lock:
        wait = max(0.0, _blocked.get(path, 0) - now)
        per = LIMITS.get(path)
        q = _sent.setdefault(path, deque())
        while q and now - q[0] > 60:
            q.popleft()
        if per and len(q) >= per:
            wait = max(wait, 60 - (now - q[0]) + 0.2)
        if wait <= 0:
            q.append(now)
        return wait


def _retry_after(r: httpx.Response, attempt: int) -> float:
    """Crustdata's 429 may carry Retry-After or X-RateLimit-Reset (seconds, or an epoch time)."""
    for h in ("retry-after", "x-ratelimit-reset"):
        v = r.headers.get(h)
        try:
            t = float(v)
        except (TypeError, ValueError):
            continue
        if t > 1e9:  # epoch seconds
            t -= time.time()
        if t > 0:
            return min(t + 0.5, 65)
    return min(5 * 2 ** attempt, 30)  # 5, 10, 20, 30 s


@dataclass
class CallRecord:
    path: str
    credits: float
    retrieved_at: str
    ms: int
    status: int


@dataclass
class Crust:
    token: str
    base_url: str = BASE_URL
    calls: list[CallRecord] = field(default_factory=list)
    _cache: dict = field(default_factory=dict)
    # Set by a person's Stop: checked before every call, so no new credits are spent.
    cancel: threading.Event | None = None
    # Told when a call has to wait for a rate limit, so progress can say so.
    on_wait: object = None

    def __post_init__(self):
        self._lock = threading.Lock()
        self._inflight = 0
        self.http = httpx.Client(
            base_url=self.base_url,
            timeout=90,
            headers={
                "authorization": f"Bearer {self.token}",
                "content-type": "application/json",
                "x-api-version": API_VERSION,
            },
        )

    # ---- plumbing -------------------------------------------------------
    @property
    def credits_used(self) -> float:
        return round(sum(c.credits for c in self.calls), 4)

    def _request(self, method: str, path: str, body: dict | None = None, params: dict | None = None):
        key = hashlib.sha1(f"{method}{path}{json.dumps(body, sort_keys=True)}{params}".encode()).hexdigest()
        if key in self._cache:  # one run never pays twice for the same question
            return self._cache[key]
        _cancel.check(self.cancel)  # Stop pressed: no new call, so no new credits
        # With a Stop flag the call runs on a helper thread and Stop returns at once.
        # The abandoned call still records what it cost (see settle()).
        return _cancel.call(self.cancel, self._send, key, method, path, body, params)

    def _pause(self, seconds: float, why: str) -> bool:
        """Wait (Stop ends the wait). Returns False if a person pressed Stop."""
        if seconds <= 0:
            return True
        if seconds >= 3 and self.on_wait:
            self.on_wait(f"Waiting {seconds:.0f} s for Crustdata's rate limit on {why}")
        if self.cancel is not None:
            return not self.cancel.wait(seconds)
        time.sleep(seconds)
        return True

    def _send(self, key, method, path, body, params):
        with self._lock:
            self._inflight += 1
        try:
            t0, waited = time.time(), 0.0
            attempt = 0
            while True:
                w = _reserve(path)
                if w > 0:  # pace ourselves instead of earning a 429
                    if waited + w > MAX_WAIT * 2 or not self._pause(w, path):
                        _cancel.check(self.cancel)
                        raise CrustError(path, 429, "paced: limit still in use", waited)
                    waited += w
                    continue
                r = self.http.request(method, path, json=body, params=params)
                if r.status_code == 429:
                    w = _retry_after(r, attempt)
                    with _rl_lock:  # every caller of this endpoint backs off together
                        _blocked[path] = max(_blocked.get(path, 0), time.time() + w)
                    log.warning("crustdata %s rate-limited; waiting %.0f s (attempt %d)", path, w, attempt + 1)
                    if waited + w > MAX_WAIT or not self._pause(w, path):
                        break
                    waited += w
                    attempt += 1
                    continue
                if r.status_code >= 500 and attempt < 2:
                    if not self._pause(1.5 * (attempt + 1), path):
                        break
                    attempt += 1
                    continue
                break
            credits = float(r.headers.get("x-credits-used") or 0)
            rec = CallRecord(path, credits, now_iso(), int((time.time() - t0) * 1000), r.status_code)
            self.calls.append(rec)
            log.info("crustdata %s %s -> %s (%.2f cr, %d ms)", method, path, r.status_code, credits, rec.ms)
            if r.status_code == 404:
                out = (None, rec)
            elif r.status_code >= 400:
                raise CrustError(path, r.status_code, r.text, waited)
            else:
                out = (r.json() if r.content else None, rec)
            self._cache[key] = out
            return out
        finally:
            with self._lock:
                self._inflight -= 1

    def settle(self, timeout: float = 60) -> float:
        """After a Stop, wait for calls already sent to come back, so their credits are counted."""
        end = time.time() + timeout
        while self._inflight and time.time() < end:
            time.sleep(0.1)
        return self.credits_used

    def post(self, path: str, body: dict):
        return self._request("POST", path, body)

    # ---- endpoints used by SecondLook ------------------------------------
    def identify(self, *, domain: str | None = None, name: str | None = None):
        body = {"domains": [domain]} if domain else {"names": [name]}
        data, rec = self.post("/company/identify", body)
        matches = (data or [{}])[0].get("matches", []) if data else []
        return matches, rec

    def enrich_company(self, company_id: int, fields: list[str]):
        data, rec = self.post("/company/enrich", {"crustdata_company_ids": [company_id], "fields": fields})
        matches = (data or [{}])[0].get("matches", []) if data else []
        return (matches[0]["company_data"] if matches else None), rec

    def enrich_companies(self, company_ids: list[int], fields: list[str]) -> tuple[dict, CallRecord | None]:
        """Several companies in ONE call (one request against the per-minute limit)."""
        ids = [i for i in dict.fromkeys(company_ids) if i]
        if not ids:
            return {}, None
        data, rec = self.post("/company/enrich", {"crustdata_company_ids": ids[:25], "fields": fields})
        out = {}
        rows = data or []
        for i, row in enumerate(rows):
            m = (row.get("matches") or [None])[0]
            if not m:
                continue
            cd = m.get("company_data") or {}
            cid = cd.get("crustdata_company_id") or (cd.get("basic_info") or {}).get("crustdata_company_id")
            if cid is None and len(rows) == len(ids):  # one row per requested id, in order
                cid = ids[i]
            if cid is not None:
                out.setdefault(cid, cd)
        return out, rec

    def jobs(self, company_id: int, limit: int = 50):
        body = {
            "filters": {"field": "company.basic_info.company_id", "type": "=", "value": company_id},
            "limit": limit,
            "sorts": [{"field": "metadata.date_added", "order": "desc"}],
            "fields": ["job_details", "location", "metadata"],
        }
        try:
            data, rec = self.post("/job/search", body)
        except CrustError as e:  # sort not allowed on this plan/field → retry unsorted
            if e.status != 400:
                raise
            body.pop("sorts")
            data, rec = self.post("/job/search", body)
        return (data or {}).get("job_listings", []), (data or {}).get("total_count"), rec

    def company_search(self, body: dict):
        data, rec = self.post("/company/search", body)
        return (data or {}).get("companies", []), (data or {}).get("total_count"), rec

    def enrich_people(self, profile_urls: list[str]):
        # Professional history only: no contact fields are ever requested.
        if not profile_urls:
            return [], None
        data, rec = self.post(
            "/person/enrich",
            {"professional_network_profile_urls": profile_urls[:25], "fields": ["basic_profile", "experience"]},
        )
        out = []
        for row in data or []:
            for m in row.get("matches", []):
                out.append(m.get("person_data"))
        return out, rec

    def web_search(self, query: str, **kw):
        # kw: sources=["news"|"web"|...], site="example.com", start_date/end_date
        data, rec = self.post("/web/search/live", {"query": query, **kw})
        return (data or {}).get("results", []), rec

    def web_fetch(self, urls: list[str]):
        data, rec = self.post("/web/enrich/live", {"urls": urls[:10]})
        return [d for d in (data or []) if d.get("success")], rec

    # ---- watches (free to create; recurring spend per change) -------------
    def watch_person(self, profile_urls: list[str], *, preview: bool, refresh_days: int = 3,
                     preview_token: str | None = None):
        body = {
            "preview": preview,
            "entities": {"professional_network_profile_urls": profile_urls},
            # Docs recipe "Fire on a new employer, not a promotion": the current-employment
            # array takes `added`, keyed on the employer so a title change stays silent.
            "track": {"field": "experience.employment_details.current", "type": "added",
                      "keys": ["crustdata_company_id", "name"]},
            "fields": ["basic_profile", "experience"],
            "config": {"trigger": {"type": "interval", "every_hours": 24}, "refresh_frequency_days": refresh_days},
            "notifications": [],
        }
        if preview_token:
            body["preview_token"] = preview_token
        data, rec = self.post("/watch/person", body)
        return data, rec

    def watch_runs(self, watch_id: int):
        data, rec = self._request("GET", f"/watch/person/{watch_id}/runs")
        return data, rec
