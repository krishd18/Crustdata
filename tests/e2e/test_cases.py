"""E2E in replay: organiser samples (recorded live), false premise, deck and vendor worked examples; 3× determinism."""
import json
import pytest
from datadesigner.core.ids import canon, sha256
from datadesigner.core.stores import Stores
from datadesigner.orchestrator import runner
NOW = "2026-11-22T16:30:00+05:30"
CASES = {l["id"]: l for l in map(json.loads, open("tests/cases.jsonl"))}


def run(req):
    st = Stores(":memory:")
    rid = runner.create({**req, "frozen_now": NOW}, st)
    return runner.execute(rid, stores=st, mode="replay")


def test_s1_find_list():
    r = run({"text": CASES["S1"]["input"], "cassette": "S1"})
    a = r["answer"]
    assert a["status"] in CASES["S1"]["expect"]["r3_status_in"] and len(a["rows"]) <= 10
    for row in a["rows"]:
        c = row["criteria"]
        assert all(c[k]["pass"] == "pass" for k in ("country", "founded", "growth", "headcount_guard", "b2b"))
        assert row["attributes"]["founded"]["value"] >= 2023 and row["attributes"]["headcount"]["now"] >= 10
        assert "per Crustdata headcount (profiles)" in row["attributes"]["headcount"]["label"]
        for f in row["attributes"].get("founders", {}).get("value", []):
            assert all(p["code"] in ("P5", "V1", "V5") for p in f["prior_roles"])


def test_s2_research_qa():
    r = run({"text": CASES["S2"]["input"], "cassette": "S2"})
    a, card = r["answer"], r["card"]
    assert card["plan"]["window_start"] == "2026-10-01" and CASES["S2"]["expect"]["caveat"] in a["caveats"]
    assert all(i["label"] == "INFERENCE — not a verified fact" and i["strength"] in ("STRONG", "MODERATE", "WEAK") for i in a["inferences"])
    names = {x["entity"]["name"] for x in a["rows"]}
    assert not names & {"Kotak Mahindra Bank", "Bajaj Finserv", "Infosys"}          # incumbents excluded with quoted reasons
    counts = [x["postings_deduped"] for x in a["rows"]]
    assert counts == sorted(counts, reverse=True)


def test_h4_false_premise_no_fabricated_list():
    a = run({"text": CASES["H4"]["input"], "cassette": "H4"})["answer"]
    assert a["rows"] == [] and a["premise_checks"][0]["code"] in ("F3", "N7") and a["status"] == "CANNOT ANSWER"


@pytest.mark.parametrize("pack", ["company_c", "acme_vendor"])
def test_check_worked_examples(pack):
    p = json.load(open(f"tests/fixtures/{pack}.json"))
    r = run({"pack_id": pack, "family": "VENDOR_CHECK" if p["profile"] == "vendor" else "DECK_CHECK", "use_llm": False, "text": pack})
    d, e = r["decision"], p["expect"]
    assert (d["floor"], d["ceiling"], d["label"]) == (e["floor"], e["ceiling"], e["label"])
    assert d["what_would_change"]["floor"] == e["wwc_floor"]
    assert r["claims"]["injection_attempts"] or pack == "acme_vendor"   # H8: injection logged, verdicts unchanged


def test_replay_determinism_x3():
    hashes = set()
    for _ in range(3):
        r = run({"text": CASES["S1"]["input"], "cassette": "S1"})
        hashes.add(sha256(canon([r["answer"]["rows"], r["answer"]["status"], r["memo"]["md"].split("as of")[0]])))
    assert len(hashes) == 1
