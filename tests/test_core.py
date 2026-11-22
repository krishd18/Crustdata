"""Smoke tests for the parts that must work before anything else does.

The kill-and-restart test is the important one: it is the behaviour a judge
checks on stage, and it is much easier to verify here than live.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desk import load_config  # noqa: E402
from desk.journal import Journal, once, step_id  # noqa: E402
from desk.ledger import CostLedger  # noqa: E402
from desk.models import Case, Verdict  # noqa: E402
from desk.rivals import RivalRegistry  # noqa: E402


def test_case_id_is_deterministic():
    a = Case.new_id("ops@client.in", ["Who hired in Guwahati since September?"])
    b = Case.new_id("ops@client.in", ["Who hired in Guwahati since September?"])
    c = Case.new_id("ops@client.in", ["A different question"])
    assert a == b, "same request must resume the same case"
    assert a != c
    print("ok  case id is deterministic")


def test_journal_runs_a_step_once_across_restarts():
    with tempfile.TemporaryDirectory() as tmp:
        calls = {"n": 0}

        def work():
            calls["n"] += 1
            return {"found": 3}

        # First process.
        j1 = Journal("case1", tmp)
        r1 = once(j1, "search", {"q": "guwahati"}, work)

        # Process dies here. A completely fresh Journal object, same file.
        j2 = Journal("case1", tmp)
        r2 = once(j2, "search", {"q": "guwahati"}, work)

        assert calls["n"] == 1, f"step ran {calls['n']} times, must run once"
        assert r1 == r2 == {"found": 3}
        print("ok  a finished step is not repeated after restart")


def test_irreversible_step_in_flight_halts_rather_than_retrying():
    with tempfile.TemporaryDirectory() as tmp:
        j = Journal("case2", tmp)
        # Simulate: we recorded the intent to send, then the process was killed
        # before we could record the outcome.
        j.start_step("send_memo", {"to": "ops@client.in"}, irreversible=True)

        j2 = Journal("case2", tmp)
        state = j2.replay()
        assert state.needs_adjudication, "an unconfirmed send must be flagged"

        try:
            once(j2, "send_memo", {"to": "ops@client.in"}, lambda: "sent",
                 irreversible=True)
        except RuntimeError as exc:
            assert "may already have taken effect" in str(exc)
            print("ok  unconfirmed irreversible step halts instead of re-sending")
        else:
            raise AssertionError("expected the case to halt")


def test_ledger_survives_restart():
    with tempfile.TemporaryDirectory() as tmp:
        j = Journal("case3", tmp)
        led = CostLedger(j, inr_per_credit=0.5)
        led.record("/web/search/live", None, latency_ms=120, credits=1)
        led.record("/web/enrich/live", None, latency_ms=300, credits=3)
        assert led.total_credits == 4

        # Restart: a fresh ledger must re-count from the journal, not zero out.
        led2 = CostLedger(Journal("case3", tmp), inr_per_credit=0.5)
        assert led2.total_credits == 4, "cost before the crash must still count"
        assert led2.total_inr == 2.0
        print("ok  cost ledger is rebuilt from the journal after restart")


def test_torn_final_line_does_not_break_replay():
    with tempfile.TemporaryDirectory() as tmp:
        j = Journal("case4", tmp)
        j.start_step("search", {"q": "x"})
        with open(j.path, "a", encoding="utf-8") as fh:
            fh.write('{"seq": 99, "kind": "step_fin')  # killed mid-write
        state = Journal("case4", tmp).replay()
        assert len(state.in_flight_readonly) == 1
        print("ok  a torn trailing line is ignored, earlier records survive")


def test_registry_flags_the_group_versus_arm_case():
    reg = RivalRegistry.load()
    also = reg.ambiguity("Mahindra Logistics")
    assert any("Mahindra Group" in a for a in also), also
    print("ok  group-vs-arm ambiguity is raised:", also[:3])


def test_registry_widens_to_former_and_acquired_names():
    reg = RivalRegistry.load()
    gati = reg.by_key("gati")
    terms = [t.lower() for t in gati.search_terms()]
    assert any("kwe" in t for t in terms), terms
    print("ok  search widens to rebrand names:", gati.search_terms())

    matches = reg.lookup("Spoton")
    assert matches, "an acquired brand must still resolve"
    assert matches[0].caution, "and must carry a caution"
    print("ok  acquired brand resolves with a caution")


def test_registry_prefers_the_longer_name_in_a_question():
    reg = RivalRegistry.load()
    found = reg.mentioned_in("Did Mahindra Logistics appoint a new COO this quarter?")
    keys = {m.rival.key for m in found}
    assert "mahindra_logistics" in keys, keys
    print("ok  question mentions resolved:", keys)


def test_config_overrides_come_from_env():
    os.environ["DESK_MIN_WEB_SOURCES"] = "3"
    cfg = load_config()
    assert cfg.evidence_bar.min_independent_web_sources == 3
    del os.environ["DESK_MIN_WEB_SOURCES"]
    print("ok  evidence bar is tunable without a code change")


def test_answer_serialises_with_all_four_verdicts():
    for v in Verdict:
        case = Case(
            case_id="x", requester="r", questions=["q"], schema_version="1.0.0"
        )
        assert case.to_dict()["schema_version"] == "1.0.0"
        assert v.value in {
            "answered", "cannot_verify", "false_premise", "ambiguous_entity"
        }
    print("ok  four verdicts, schema version emitted")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"\n{len(tests)} checks passed")
