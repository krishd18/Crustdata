"""Crustdata rate limits: pace calls, wait out a 429, and fail in plain words."""
import json
import time

import httpx
import pytest

from app import crust as crust_mod
from app import engine, store
from app.crust import Crust, CrustError, now_iso
from tests.test_engine_smoke import SAMPLE, StubCrust


def _client(handler):
    c = Crust("tok")
    c.http = httpx.Client(base_url="https://api.crustdata.com", transport=httpx.MockTransport(handler))
    return c


@pytest.fixture(autouse=True)
def _fresh_limits(monkeypatch):
    monkeypatch.setattr(crust_mod, "_sent", {})
    monkeypatch.setattr(crust_mod, "_blocked", {})


def test_429_is_waited_out_and_retried():
    n = []

    def handler(req):
        n.append(1)
        if len(n) == 1:
            return httpx.Response(429, json={"error": {"type": "rate_limit_error"}}, headers={"retry-after": "0.1"})
        return httpx.Response(200, json={"companies": [], "total_count": 0}, headers={"x-credits-used": "1"})

    waits = []
    c = _client(handler)
    c.on_wait = waits.append
    rows, total, rec = c.company_search({"limit": 1})
    assert len(n) == 2 and rec.status == 200 and c.credits_used == 1


def test_429_past_the_wait_budget_fails_in_plain_words(monkeypatch):
    monkeypatch.setattr(crust_mod, "MAX_WAIT", 1)
    c = _client(lambda req: httpx.Response(429, json={"error": {"type": "rate_limit_error"}}, headers={"retry-after": "0.6"}))
    with pytest.raises(CrustError) as ei:
        c.enrich_company(1, ["basic_info"])
    msg = str(ei.value)
    assert "rate limit for /company/enrich" in msg and "15 calls a minute" in msg and "try again" in msg
    assert "{" not in msg  # no raw JSON for a person to read


def test_calls_are_paced_under_the_per_minute_limit(monkeypatch):
    monkeypatch.setitem(crust_mod.LIMITS, "/company/enrich", 2)
    now = time.time()
    crust_mod._sent["/company/enrich"] = crust_mod.deque([now - 59.5, now - 59.4])  # 2 used, freeing in ~0.5 s
    sent = []

    def handler(req):
        sent.append(time.time())
        return httpx.Response(200, json=[{"matches": [{"company_data": {"crustdata_company_id": 1}}]}])

    t0 = time.time()
    _client(handler).enrich_company(1, ["basic_info"])
    assert sent and sent[0] - t0 >= 0.4  # it waited for a free slot instead of earning a 429


def test_batch_enrich_maps_each_company():
    def handler(req):
        ids = json.loads(req.content)["crustdata_company_ids"]
        return httpx.Response(200, json=[{"matched_on": str(i), "matches": [{"company_data": {
            "crustdata_company_id": i, "basic_info": {"name": f"Co {i}"}}}]} for i in ids], headers={"x-credits-used": "4"})

    out, rec = _client(handler).enrich_companies([7, 9, 7], ["basic_info"])
    assert sorted(out) == [7, 9] and out[9]["basic_info"]["name"] == "Co 9" and rec.credits == 4


def test_a_failed_run_keeps_a_plain_error_and_its_cost(monkeypatch):
    class Limited(StubCrust):
        def enrich_company(self, cid, fields):
            self._rec("/company/identify", 0.5)
            raise CrustError("/company/enrich", 429, '{"error":{"type":"rate_limit_error"}}', waited=75)

    monkeypatch.setattr(engine, "Crust", Limited)
    store.init()
    store.x("INSERT INTO dossiers (id,name,domain,city,teaser,created_at) VALUES ('d_rl','Stockarea','stockarea.io','Chennai',?,?)",
            (SAMPLE["teaser"], now_iso()))
    store.x("INSERT INTO runs (id,dossier_id,seq,status,started_at,progress,mode) VALUES ('r_rl','d_rl',1,'running',?,'[]','screen')",
            (now_iso(),))
    engine.run("r_rl", "tok")
    row = store.q("SELECT * FROM runs WHERE id='r_rl'", one=True)
    assert row["status"] == "error"
    assert row["error"].startswith("Crustdata's rate limit for /company/enrich") and "waited 75 s" in row["error"]
    assert json.loads(row["result"])["cost"]["credits"] == pytest.approx(0.7)  # identify 0.2 + 0.5 before the 429
