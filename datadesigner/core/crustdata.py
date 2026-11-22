"""Typed Crustdata client (plan §3.1C table). Every call goes through the gateway. Headers:
authorization: Bearer, x-api-version, content-type. Field names confirmed live — docs/API_NOTES.md."""
from __future__ import annotations

from typing import Any

from .gateway import Gateway, Resp

ENRICH_GROUPS = {"basic_info", "headcount", "people", "funding", "hiring", "revenue", "competitors", "news",
                 "web_traffic", "employee_reviews", "taxonomy", "locations"}


class CrustdataClient:
    def __init__(self, gateway: Gateway, settings, sources_cfg: dict):
        self.g, self.s = gateway, settings
        self.cfg = (sources_cfg or {}).get("crustdata", {})
        self.ep = self.cfg.get("endpoints", {})

    def _headers(self) -> dict:
        key = self.s.crustdata_api_key if self.g.mode == "replay" else self.s.secret("crustdata_api_key")
        return {"authorization": f"Bearer {key}", "x-api-version": self.s.crustdata_api_version,
                "content-type": "application/json"}

    def _call(self, name: str, body: Any, est: float = 0.0, critical: bool = True, method: str = "POST") -> Resp:
        e = self.ep.get(name, {})
        path = e.get("path", "/" + name)
        retry = self.cfg.get("retry", {})
        return self.g.request("crustdata", name, method, self.s.crustdata_base_url.rstrip("/") + path, path, body,
                              self._headers(), rpm=e.get("rpm", 0), est_credits=est, critical=critical,
                              ttl_s=e.get("ttl_s"), max_retries=retry.get("max", 4))

    # --- company ---------------------------------------------------------
    def company_autocomplete(self, field: str, query: str, limit: int = 20) -> list[str]:
        r = self._call("company_autocomplete", {"field": field, "query": query, "limit": min(limit, 100)})
        return [s["value"] for s in r.body.get("suggestions", [])]

    def company_search(self, filters: dict, fields: list[str], sorts: list | None = None, limit: int = 100,
                       cursor: str | None = None, critical: bool = True) -> Resp:
        body: dict = {"filters": filters, "fields": fields, "limit": min(limit, 1000)}
        if sorts:
            body["sorts"] = sorts
        if cursor:
            body["cursor"] = cursor
        return self._call("company_search", body, est=0.03 * limit + 0.3 * limit / 10, critical=critical)

    def company_identify(self, *, names: list[str] | None = None, domains: list[str] | None = None,
                         exact_match: bool = False) -> Resp:
        body: dict = {"exact_match": exact_match}
        if names:
            body["names"] = names[:25]
        elif domains:
            body["domains"] = domains[:25]
        return self._call("company_identify", body, est=0.2 * len(names or domains or []))

    def company_enrich(self, ids: list[int], fields: list[str], critical: bool = True) -> Resp:
        bad = set(fields) - ENRICH_GROUPS
        if bad:
            raise ValueError(f"unknown enrich groups {bad}")
        return self._call("company_enrich", {"crustdata_company_ids": list(ids)[:25], "fields": fields},
                          est=2.0 * len(ids[:25]), critical=critical)

    # --- person ----------------------------------------------------------
    def person_search(self, filters: dict, fields: list[str] | None = None, limit: int = 50, cursor: str | None = None) -> Resp:
        body: dict = {"filters": filters, "limit": limit}
        if fields:
            body["fields"] = fields
        if cursor:
            body["cursor"] = cursor
        return self._call("person_search", body, est=0.13 * limit)

    def person_enrich(self, profile_urls: list[str], fields: list[str] | None = None) -> Resp:
        body: dict = {"professional_network_profile_urls": profile_urls[:25]}
        if fields:
            body["fields"] = fields
        return self._call("person_enrich", body, est=1.0 * len(profile_urls[:25]))

    def contact_enrich(self, profile_url: str) -> Resp:
        """Business email only (policy, config/sources.yaml)."""
        return self._call("contact_enrich", {"professional_network_profile_urls": [profile_url], "fields": ["business_email"]}, est=1.0)

    # --- jobs ------------------------------------------------------------
    def job_search(self, filters: dict, fields: list[str] | None = None, sorts: list | None = None, limit: int = 100,
                   cursor: str | None = None, aggregations: list | None = None, critical: bool = True) -> Resp:
        body: dict = {"filters": filters, "limit": limit}
        for k, v in (("fields", fields), ("sorts", sorts), ("cursor", cursor), ("aggregations", aggregations)):
            if v:
                body[k] = v
        return self._call("job_search", body, est=0.03 * limit, critical=critical)

    # --- web -------------------------------------------------------------
    def web_search(self, query: str, sources: list[str] | None = None, site: str | None = None,
                   start_date: int | None = None, end_date: int | None = None, page: int = 1, critical: bool = False) -> Resp:
        body: dict = {"query": query, "sources": sources or ["news"], "page": page}
        for k, v in (("site", site), ("start_date", start_date), ("end_date", end_date)):
            if v:
                body[k] = v
        return self._call("web_search", body, est=1.0, critical=critical)

    def web_fetch(self, urls: list[str], critical: bool = False) -> Resp:
        return self._call("web_fetch", {"urls": urls[:10]}, est=1.0 * len(urls[:10]), critical=critical)

    def account_endpoints(self) -> Resp:
        return self._call("account_endpoints", None, method="GET")
