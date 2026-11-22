"""Stop: a person can stop any step that spends Crustdata credits or model time."""
import json
import threading
import time

import httpx
import pytest

from app import cancel, engine, pipeline, store
from app.crust import Crust, now_iso
from tests.test_engine_smoke import SAMPLE, StubCrust


def test_call_returns_at_once_when_stopped():
    ev = threading.Event()
    threading.Timer(0.3, ev.set).start()
    t0 = time.time()
    with pytest.raises(cancel.Cancelled):
        cancel.call(ev, time.sleep, 5)  # a slow model call
    assert time.time() - t0 < 1.5


def test_call_passes_results_and_errors_through():
    ev = threading.Event()
    assert cancel.call(ev, lambda x: x * 2, 21) == 42
    assert cancel.call(None, lambda: "plain") == "plain"
    with pytest.raises(ValueError):
        cancel.call(ev, lambda: (_ for _ in ()).throw(ValueError("boom")))


def test_cancelled_is_not_swallowed_by_source_fallbacks():
    # the per-source `except Exception` fallbacks must not eat a Stop
    with pytest.raises(cancel.Cancelled):
        try:
            raise cancel.Cancelled()
        except Exception:
            pytest.fail("swallowed")


def test_crust_makes_no_call_after_stop():
    hits = []

    def handler(req):
        hits.append(req.url.path)
        return httpx.Response(200, json={"companies": [], "total_count": 0}, headers={"x-credits-used": "1"})

    ev = cancel.token("j_test_crust")
    c = Crust("tok", cancel=ev)
    c.http = httpx.Client(base_url="https://api.crustdata.com", transport=httpx.MockTransport(handler))
    c.company_search({"limit": 1})
    assert len(hits) == 1 and c.credits_used == 1
    cancel.cancel("j_test_crust")
    with pytest.raises(cancel.Cancelled):
        c.company_search({"limit": 2})
    assert len(hits) == 1  # nothing new was sent, so nothing new was billed
    cancel.done("j_test_crust")


def test_stop_returns_at_once_but_in_flight_credits_still_count():
    def slow(req):
        time.sleep(0.8)
        return httpx.Response(200, json={"companies": []}, headers={"x-credits-used": "2"})

    ev = threading.Event()
    c = Crust("tok", cancel=ev)
    c.http = httpx.Client(base_url="https://api.crustdata.com", transport=httpx.MockTransport(slow))
    threading.Timer(0.2, ev.set).start()
    t0 = time.time()
    with pytest.raises(cancel.Cancelled):
        c.company_search({"limit": 1})
    assert time.time() - t0 < 0.7  # Stop didn't wait for the slow call
    assert c.settle(5) == 2  # but the call already sent is still counted


def _dossier(did):
    store.init()
    store.x("INSERT INTO dossiers (id,name,domain,city,teaser,created_at) VALUES (?,'Stockarea','stockarea.io','Chennai',?,?)",
            (did, SAMPLE["teaser"], now_iso()))


def test_stopped_run_ends_cancelled_with_its_cost(monkeypatch):
    class StoppedMidway(StubCrust):
        def enrich_company(self, cid, fields):
            out = super().enrich_company(cid, fields)
            pipeline.cancel_run(RID[0])  # the person presses Stop while the record is being pulled
            return out

    RID = []
    monkeypatch.setattr(engine, "Crust", StoppedMidway)
    monkeypatch.setattr(engine, "archive_first", lambda d: (None, now_iso()))
    _dossier("d_stop")
    store.x("INSERT INTO runs (id,dossier_id,seq,status,started_at,progress) VALUES ('r_stop','d_stop',1,'running',?,'[]')",
            (now_iso(),))
    RID.append("r_stop")
    engine.run("r_stop", "tok")
    row = store.q("SELECT * FROM runs WHERE id='r_stop'", one=True)
    assert row["status"] == "cancelled"
    res = json.loads(row["result"])
    assert res["cost"]["credits"] > 0  # what was spent before the Stop is kept on the run
    prog = json.loads(row["progress"])
    assert prog[-1].startswith("Stopped by a person")
    assert not any(p.startswith("Checking") for p in prog)  # it never reached the claim checks


def test_stop_on_a_finished_run_changes_nothing(monkeypatch):
    monkeypatch.setattr(engine, "Crust", StubCrust)
    monkeypatch.setattr(engine, "archive_first", lambda d: (None, now_iso()))
    _dossier("d_done")
    store.x("INSERT INTO runs (id,dossier_id,seq,status,started_at,progress) VALUES ('r_done','d_done',1,'running',?,'[]')",
            (now_iso(),))
    engine.run("r_done", "tok")
    assert pipeline.cancel_run("r_done") is False
    assert store.q("SELECT status FROM runs WHERE id='r_done'", one=True)["status"] == "done"
