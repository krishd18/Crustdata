"""Source gateway (plan §3.1C): one shared httpx client, per-endpoint rate limit, retries with backoff +
jitter honouring Retry-After / X-RateLimit-Reset, circuit breaker per source, cassettes (live|record|replay),
raw-blob storage and cost capture (X-Credits-Used)."""
from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx

from .budget import Budget
from .errors import CassetteMiss, ContractError, SourceUnavailable
from .ids import canon, sha256
from .logging import get_logger
from .settings import ROOT, http_mode

CASSETTES = ROOT / "tests" / "cassettes"
SECRET_HEADERS = {"authorization", "x-api-key", "cookie", "set-cookie", "proxy-authorization"}
log = get_logger("gateway")


@dataclass
class Resp:
    status: int
    headers: dict
    body: Any
    sha: str = ""
    cached: bool = False
    credits: float = 0.0
    url: str = ""


@dataclass
class Breaker:
    failures_to_open: int = 5
    half_open_after_s: float = 60
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        return time.time() - self.opened_at >= self.half_open_after_s  # half-open: one trial

    def ok(self) -> None:
        self.failures, self.opened_at = 0, None

    def fail(self) -> None:
        self.failures += 1
        if self.failures >= self.failures_to_open:
            self.opened_at = time.time()


@dataclass
class Bucket:
    rpm: float
    last: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def wait(self, sleep: Callable[[float], None]) -> None:
        if not self.rpm:
            return
        with self.lock:
            gap = 60.0 / self.rpm - (time.time() - self.last)
            if gap > 0:
                sleep(gap)
            self.last = time.time()


class CassetteIndex:
    def __init__(self, root: Path = CASSETTES):
        self.root, self._idx = root, None

    def find(self, key: str) -> Path | None:
        if self._idx is None:
            self._idx = {p.stem: p for p in self.root.rglob("*.json")} if self.root.exists() else {}
        p = self._idx.get(key)
        if p is None:  # files written after indexing
            hits = list(self.root.rglob(f"{key}.json")) if self.root.exists() else []
            p = hits[0] if hits else None
            if p:
                self._idx[key] = p
        return p

    def add(self, key: str, p: Path) -> None:
        if self._idx is not None:
            self._idx[key] = p


def request_key(method: str, path: str, body: Any) -> str:
    return sha256(canon([method.upper(), path, body]))


class Gateway:
    def __init__(self, stores, sources_cfg: dict, budget: Budget | None = None, run_id: str = "-",
                 mode: str | None = None, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, cassette: str | None = None):
        self.stores, self.cfg = stores, sources_cfg or {}
        self.budget, self.run_id = budget or Budget(max_credits=0, deadline_s=0), run_id
        self.mode = mode or http_mode()
        self.sleep = sleep
        self.client = httpx.Client(timeout=60, transport=transport) if transport else httpx.Client(timeout=60)
        self.breakers: dict[str, Breaker] = {}
        self.buckets: dict[str, Bucket] = {}
        self.cassette_name = cassette or os.environ.get("DD_CASSETTE", "default")
        self.index = CassetteIndex()
        self.inr_per_credit = float(self.cfg.get("inr_per_credit", 2.0))
        self.calls: list[dict] = []   # call log for the Run screen

    # ------------------------------------------------------------------
    def _breaker(self, source: str) -> Breaker:
        b = self.cfg.get("crustdata", {}).get("breaker", {})
        return self.breakers.setdefault(source, Breaker(b.get("failures_to_open", 5), b.get("half_open_after_s", 60)))

    def _bucket(self, endpoint: str, rpm: float) -> Bucket:
        return self.buckets.setdefault(endpoint, Bucket(rpm))

    def request(self, source: str, endpoint: str, method: str, url: str, path: str, body: Any = None,
                headers: dict | None = None, rpm: float = 0, est_credits: float = 0.0, critical: bool = True,
                ttl_s: float | None = None, max_retries: int = 4) -> Resp:
        """Send one request through every guard. Raises SourceUnavailable, ContractError, BudgetExhausted, CassetteMiss."""
        key = request_key(method, path, body)
        cache_key = f"{source}:{key}"
        self.budget.check(est_credits, critical)
        if ttl_s and self.mode == "live":
            hit = self.stores.cache_get(cache_key)
            if hit is not None:
                self.stores.add_cost(self.run_id, endpoint, 0.0, "cache", cached=True)
                self._log(endpoint, body, 0.0, "cache")
                return Resp(200, {}, hit["body"], hit["sha"], cached=True, url=url)
        if self.mode == "replay":
            return self._replay(key, endpoint, body, url)
        br = self._breaker(source)
        if not br.allow():
            raise SourceUnavailable(source, "circuit breaker open")
        attempt, last_err = 0, ""
        while True:
            self._bucket(endpoint, rpm).wait(self.sleep)
            try:
                r = self.client.request(method, url, json=body, headers=headers or {})
            except httpx.HTTPError as e:
                status, last_err = 0, f"{type(e).__name__}"
                r = None
            else:
                status = r.status_code
            if r is not None and status < 400:
                br.ok()
                return self._accept(r, key, source, endpoint, body, url, ttl_s, cache_key)
            if r is not None and 400 <= status < 500 and status != 429:
                raise ContractError(f"{endpoint} {status}: {r.text[:300]}")
            br.fail()
            last_err = last_err or f"HTTP {status}"
            if attempt >= max_retries or not br.allow():
                log.warning("gateway.unavailable", source=source, endpoint=endpoint, error=last_err, attempts=attempt + 1)
                raise SourceUnavailable(source, f"{last_err} after {attempt + 1} attempts")
            self.sleep(self._backoff(attempt, r))
            attempt += 1

    @staticmethod
    def _backoff(attempt: int, r: httpx.Response | None) -> float:
        if r is not None:
            ra = r.headers.get("retry-after")
            if ra:
                try:
                    return min(float(ra), 120.0)
                except ValueError:
                    pass
            reset = r.headers.get("x-ratelimit-reset")
            if reset:
                try:
                    v = float(reset)
                    return min(max(v - time.time(), 0.5) if v > 1e9 else v, 120.0)
                except ValueError:
                    pass
        return min(2 ** attempt + random.uniform(0, 0.5), 60.0)

    def _accept(self, r: httpx.Response, key: str, source: str, endpoint: str, body: Any, url: str,
                ttl_s: float | None, cache_key: str) -> Resp:
        raw = r.content
        sha = self.stores.put_blob(raw, r.headers.get("content-type", "application/json"))
        try:
            data = r.json()
        except ValueError:
            data = r.text
        credits = float(r.headers.get("x-credits-used") or 0.0)
        rid = r.headers.get("x-request-id", "") or r.headers.get("request-id", "")
        self.budget.charge(credits)
        self.stores.add_cost(self.run_id, endpoint, credits, rid, inr=credits * self.inr_per_credit)
        hdrs = {k: v for k, v in r.headers.items() if k.lower() not in SECRET_HEADERS}
        if self.mode == "record":
            d = CASSETTES / self.cassette_name
            d.mkdir(parents=True, exist_ok=True)
            p = d / f"{key}.json"
            p.write_text(json.dumps({"endpoint": endpoint, "url": url, "request_body": body, "status": r.status_code,
                                     "headers": {k: v for k, v in hdrs.items() if k.lower() in ("content-type", "x-credits-used")},
                                     "body": data}, indent=1, ensure_ascii=False, sort_keys=True))
            self.index.add(key, p)
        if ttl_s:
            self.stores.cache_put(cache_key, {"body": data, "sha": sha}, ttl_s)
        self._log(endpoint, body, credits, "live")
        return Resp(r.status_code, hdrs, data, sha, credits=credits, url=url)

    def _replay(self, key: str, endpoint: str, body: Any, url: str) -> Resp:
        p = self.index.find(key)
        if not p:
            raise CassetteMiss(f"no cassette for {endpoint} {key[:12]} (record it with make record)")
        rec = json.loads(p.read_text())
        raw = json.dumps(rec["body"], ensure_ascii=False, sort_keys=True).encode()
        sha = self.stores.put_blob(raw)
        credits = float(rec.get("headers", {}).get("x-credits-used") or 0.0)
        self.budget.charge(credits)
        self.stores.add_cost(self.run_id, endpoint, credits, "replay", inr=credits * self.inr_per_credit)
        self._log(endpoint, body, credits, "replay")
        if rec["status"] >= 400:
            if rec["status"] == 429 or rec["status"] >= 500:
                raise SourceUnavailable(endpoint.split("_")[0], f"HTTP {rec['status']} (recorded)")
            raise ContractError(f"{endpoint} {rec['status']} (recorded)")
        return Resp(rec["status"], rec.get("headers", {}), rec["body"], sha, credits=credits, url=url)

    def _log(self, endpoint: str, body: Any, credits: float, how: str) -> None:
        self.calls.append({"at": time.strftime("%H:%M:%S"), "endpoint": endpoint, "credits": credits, "how": how,
                           "body": canon(body)[:160]})
