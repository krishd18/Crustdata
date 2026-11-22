"""Thin Crustdata REST client.

Every call records what it cost (X-Credits-Used) and when it was made, so each
verdict can cite the exact API field and its retrieval date.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

log = logging.getLogger("secondlook.crust")

BASE_URL = "https://api.crustdata.com"
API_VERSION = "2025-11-01"


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class CrustError(RuntimeError):
    def __init__(self, path: str, status: int, body: str):
        super().__init__(f"{path} -> HTTP {status}: {body[:300]}")
        self.path, self.status, self.body = path, status, body


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

    def __post_init__(self):
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
        t0 = time.time()
        for attempt in range(3):
            r = self.http.request(method, path, json=body, params=params)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
        credits = float(r.headers.get("x-credits-used") or 0)
        rec = CallRecord(path, credits, now_iso(), int((time.time() - t0) * 1000), r.status_code)
        self.calls.append(rec)
        log.info("crustdata %s %s -> %s (%.2f cr, %d ms)", method, path, r.status_code, credits, rec.ms)
        if r.status_code == 404:
            out = (None, rec)
        elif r.status_code >= 400:
            raise CrustError(path, r.status_code, r.text)
        else:
            out = (r.json() if r.content else None, rec)
        self._cache[key] = out
        return out

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

    def web_search(self, query: str):
        data, rec = self.post("/web/search/live", {"query": query})
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
            "track": {"field": "experience.employment_details.current", "type": "changed"},
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
