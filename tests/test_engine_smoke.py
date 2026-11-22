"""End-to-end engine run against a stubbed Crustdata client (no network)."""
import json

from app import engine, store
from app.crust import CallRecord, now_iso
from tests.test_checkers import rec as fixture_record

SAMPLE = json.load(open("samples/stockarea.json", encoding="utf-8"))


class StubCrust:
    def __init__(self, token, cancel=None):
        self.calls = []
        self.company = fixture_record().company
        self.company["basic_info"].update({"name": "Stockarea", "primary_domain": "stockarea.io",
                                           "description": "We run 12 warehouses and a team of 90."})

    def _rec(self, path, cr):
        r = CallRecord(path, cr, now_iso(), 1, 200)
        self.calls.append(r)
        return r

    @property
    def credits_used(self):
        return sum(c.credits for c in self.calls)

    def identify(self, domain=None, name=None):
        return [{"company_data": {"crustdata_company_id": 14499, "basic_info": self.company["basic_info"]}}], self._rec("/company/identify", 0.2)

    def enrich_company(self, cid, fields):
        return self.company, self._rec("/company/enrich", 2)

    def jobs(self, cid, limit=50):
        r = fixture_record()
        return r.jobs, len(r.jobs), self._rec("/job/search", 0.03)

    def web_search(self, q):
        return [{"title": "Stockarea home", "url": "https://stockarea.io/", "snippet": "Stockarea serves Amazon"}], self._rec("/web/search/live", 1)

    def web_fetch(self, urls):
        return [{"url": urls[0], "content": "Stockarea: 15 warehouses in Tamil Nadu. Cuts damage by 25%.", "success": True}], self._rec("/web/enrich/live", 1)

    def enrich_people(self, urls):
        return [], self._rec("/person/enrich", 1)


def test_full_run(monkeypatch, tmp_path):
    monkeypatch.setattr(engine, "Crust", StubCrust)
    monkeypatch.setattr(engine, "archive_first", lambda d: ("20190801000000", now_iso()))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    store.init()
    store.x("INSERT INTO dossiers (id,name,domain,city,teaser,created_at) VALUES ('d_t','Stockarea','stockarea.io','Chennai',?,?)",
            (SAMPLE["teaser"], now_iso()))
    for seq, rid in [(1, "r_t1"), (2, "r_t2")]:
        store.x("INSERT INTO runs (id,dossier_id,seq,status,started_at,progress) VALUES (?,?,?,?,?,'[]')",
                (rid, "d_t", seq, "running", now_iso()))
        engine.run(rid, "tok")
        row = store.q("SELECT * FROM runs WHERE id=?", (rid,), one=True)
        assert row["status"] == "done", row["error"]
    res = json.loads(row["result"])
    verdicts = {f["claim"]["type"]: f["verdict"] for f in res["findings"]}
    assert verdicts["workforce"] == "contradicted"
    assert verdicts["premise"] in ("false premise", "unsupported premise")
    assert verdicts["forward_looking"] == "projection"
    assert res["requests"], "unsettled claims must produce requests"
    assert res["inconsistencies"], "deck 60 vs profile 90 employees should conflict"
    assert res["cost"]["credits"] > 0
    store.x("DELETE FROM runs WHERE dossier_id='d_t'")
    store.x("DELETE FROM dossiers WHERE id='d_t'")
