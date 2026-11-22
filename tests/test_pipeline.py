"""End-to-end tests for the reasoning layers.

These run offline, so they cost nothing and can be run in a loop while
changing the evidence bar. The point of most of them is to pin behaviour that
is easy to break in the direction of answering more: every test below that
asserts a refusal is guarding against a change that would turn that refusal
into a confident answer.
"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desk import load_config  # noqa: E402
from desk.dating import date_of_page, in_window  # noqa: E402
from desk.desk import CompetitorMoveDesk  # noqa: E402
from desk.entail import EntailmentChecker  # noqa: E402
from desk.evidence import registrable_domain  # noqa: E402
from desk.fixtures import DEMO_QUESTIONS, FakeCrustdataClient  # noqa: E402
from desk.journal import Journal  # noqa: E402
from desk.ledger import CostLedger  # noqa: E402
from desk.llm import default_offline_llm  # noqa: E402
from desk.models import Case, DateKind, Verdict  # noqa: E402
from desk.rivals import RivalRegistry  # noqa: E402


def _desk(tmp: str, requester: str, questions: list[str], approval: str = "auto"):
    config = load_config().with_overrides(journal_dir=tmp)
    case_id = Case.new_id(requester, questions)
    journal = Journal(case_id, tmp)
    ledger = CostLedger(journal)
    client = FakeCrustdataClient(ledger)
    desk = CompetitorMoveDesk(
        config=config,
        client=client,
        llm=default_offline_llm(),
        ledger=ledger,
        journal=journal,
        registry=RivalRegistry.load(),
        approval_mode=approval,
    )
    return desk, journal, ledger, client


def test_all_four_verdicts_are_reachable():
    with tempfile.TemporaryDirectory() as tmp:
        desk, _, _, _ = _desk(tmp, "ops@client.example", DEMO_QUESTIONS)
        result = desk.run("ops@client.example", DEMO_QUESTIONS)
        verdicts = [a.verdict for a in result.case.answers]
        assert Verdict.ANSWERED in verdicts
        assert Verdict.FALSE_PREMISE in verdicts
        assert Verdict.AMBIGUOUS_ENTITY in verdicts
        assert Verdict.CANNOT_VERIFY in verdicts
        print("ok  all four verdicts reachable:", [v.value for v in verdicts])


def test_only_answered_questions_are_billed():
    with tempfile.TemporaryDirectory() as tmp:
        desk, _, _, _ = _desk(tmp, "ops@client.example", DEMO_QUESTIONS)
        result = desk.run("ops@client.example", DEMO_QUESTIONS)
        billed = [a for a in result.case.answers if a.billable]
        assert all(a.verdict is Verdict.ANSWERED for a in billed)
        assert result.case.billable_questions == 1
        print("ok  only the answered question is billed")


def test_ambiguous_entity_costs_nothing():
    """Refusing early must be cheap, or the incentive runs the wrong way."""
    with tempfile.TemporaryDirectory() as tmp:
        q = ["How many people does Mahindra employ in logistics?"]
        desk, _, _, client = _desk(tmp, "ops@client.example", q)
        result = desk.run("ops@client.example", q)
        answer = result.case.answers[0]
        assert answer.verdict is Verdict.AMBIGUOUS_ENTITY
        assert answer.credits_used == 0, answer.credits_used
        assert client.searches == [], "must not search before knowing the company"
        print("ok  ambiguity short-circuits before any paid call")


def test_answered_evidence_has_passage_date_and_two_domains():
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Did Delhivery start hiring in Guwahati since September 2026?"]
        desk, _, _, _ = _desk(tmp, "ops@client.example", q)
        answer = desk.run("ops@client.example", q).case.answers[0]
        assert answer.verdict is Verdict.ANSWERED
        assert len(answer.evidence) >= 2
        domains = {e.source_domain for e in answer.evidence}
        assert len(domains) >= 2, f"needs independent publishers, got {domains}"
        for e in answer.evidence:
            assert e.exact_passage.strip(), "every citation needs a passage"
            assert e.record_date, "every citation needs a date"
            assert e.date_kind is DateKind.PUBLISHED
        print("ok  answered claim carries passages, dates and 2 domains:", domains)


def test_undated_source_cannot_answer_a_dated_question():
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Is Snowman Logistics expanding cold chain capacity this quarter?"]
        desk, _, _, _ = _desk(tmp, "ops@client.example", q)
        answer = desk.run("ops@client.example", q).case.answers[0]
        assert answer.verdict is Verdict.CANNOT_VERIFY
        assert "date" in (answer.missing or "").lower()
        print("ok  undated source refuses a dated question:", answer.missing[:60])


def test_false_premise_does_not_claim_the_negative():
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Why did Mahindra Logistics exit Kolkata?"]
        desk, _, _, _ = _desk(tmp, "ops@client.example", q)
        answer = desk.run("ops@client.example", q).case.answers[0]
        assert answer.verdict is Verdict.FALSE_PREMISE
        text = (answer.what_sources_show or "").lower()
        assert "not evidence" in text or "absence" in text, text
        print("ok  false premise reports silence, not disproof")


def test_entailment_rejects_a_topical_passage():
    llm = default_offline_llm()
    checker = EntailmentChecker(llm, threshold=0.75)
    claim = "Delhivery started hiring in Guwahati in September 2026"
    topical = (
        "Guwahati has become a hub for regional distribution, with several "
        "national operators maintaining a presence in the city."
    )
    states = (
        "Delhivery started hiring in Guwahati in September 2026, posting "
        "warehouse roles."
    )
    assert not checker.check(claim, topical).states_claim
    assert checker.check(claim, states).states_claim
    print("ok  a page about the same topic is not evidence")


def test_dating_prefers_published_and_never_promotes_modified():
    published = date_of_page(
        '<meta property="article:published_time" content="2026-10-14T06:00:00Z">'
    )
    assert published.value == "2026-10-14"
    assert published.kind is DateKind.PUBLISHED
    assert published.is_a_real_date

    modified_only = date_of_page(
        '<html><head>'
        '<meta property="article:modified_time" content="2026-11-01T00:00:00Z">'
        '</head><body><p>No publication date anywhere.</p></body></html>'
    )
    assert modified_only.kind is not DateKind.PUBLISHED
    assert not modified_only.is_a_real_date, "a modified date is not a pub date"
    print("ok  modified date is not promoted to published")


def test_search_window_is_a_bound_not_a_date():
    d = date_of_page(
        "<html><body>nothing dated here</body></html>",
        search_window=(1757000000, 1760000000),
    )
    assert d.value is None
    assert d.confidence == "bound"
    assert not d.is_a_real_date
    print("ok  a search window is reported as a bound, not a date")


def test_independence_is_counted_by_domain_not_url():
    a = registrable_domain("https://www.example.co.in/news/one")
    b = registrable_domain("https://example.co.in/news/two")
    c = registrable_domain("https://other.example.net/x")
    assert a == b, (a, b)
    assert a != c
    print("ok  two paths on one site are one source")


def test_in_window_excludes_records_before_the_period():
    assert in_window("2026-10-01", "2026-09-01", "2026-11-01")
    assert not in_window("2026-08-01", "2026-09-01", "2026-11-01")
    assert not in_window(None, "2026-09-01", None)
    print("ok  window filtering excludes records outside the period")


def test_case_resumes_after_a_crash_without_redoing_paid_work():
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Did Delhivery start hiring in Guwahati since September 2026?"]
        requester = "ops@client.example"

        desk1, journal, ledger1, client1 = _desk(tmp, requester, q)
        desk1.run(requester, q)
        first_searches = len(client1.searches)
        first_credits = ledger1.total_credits
        assert first_searches > 0

        # Same request, fresh everything: the journal is all that carries over.
        desk2, journal2, ledger2, client2 = _desk(tmp, requester, q)
        desk2.run(requester, q)

        assert client2.searches == [], (
            f"resumed run repeated {len(client2.searches)} paid searches"
        )
        assert ledger2.total_credits == first_credits, (
            "credits must not grow on a resumed run"
        )
        print(f"ok  resumed run repeated 0 of {first_searches} paid searches")


def test_unconfirmed_send_halts_the_whole_case():
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Did Delhivery start hiring in Guwahati since September 2026?"]
        requester = "ops@client.example"
        case_id = Case.new_id(requester, q)

        # The process died between recording the intent to send and the send.
        j = Journal(case_id, tmp)
        j.start_step("send_memo", {"to": requester, "case": case_id},
                     irreversible=True)

        desk, _, _, _ = _desk(tmp, requester, q)
        result = desk.run(requester, q)
        assert result.halted
        assert not result.sent
        assert "never confirmed" in (result.halt_reason or "")
        print("ok  an unconfirmed send halts the case for a person")


def test_declined_approval_does_not_send():
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Did Delhivery start hiring in Guwahati since September 2026?"]
        desk, journal, _, _ = _desk(tmp, "ops@client.example", q, approval="file")
        desk.gate.timeout_seconds = 1  # nobody is watching
        result = desk.run("ops@client.example", q)
        assert not result.sent
        assert result.decision and not result.decision.approved
        assert "refusal" in (result.decision.note or "")
        assert not os.path.exists(f"{tmp}/{result.case.case_id}.memo.md")
        print("ok  an unanswered approval is a refusal, and nothing is sent")


def test_auto_approval_is_recorded_as_unreviewed():
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Did Delhivery start hiring in Guwahati since September 2026?"]
        desk, _, _, _ = _desk(tmp, "ops@client.example", q, approval="auto")
        result = desk.run("ops@client.example", q)
        assert result.decision and result.decision.approved
        assert "No person reviewed" in (result.decision.note or "")
        print("ok  auto-approval is labelled as unreviewed in the record")


def test_raising_the_bar_turns_an_answer_into_a_refusal():
    """The evidence bar is a real parameter, not decoration."""
    with tempfile.TemporaryDirectory() as tmp:
        q = ["Did Delhivery start hiring in Guwahati since September 2026?"]
        os.environ["DESK_MIN_WEB_SOURCES"] = "3"
        try:
            desk, _, _, _ = _desk(tmp, "strict@client.example", q)
            answer = desk.run("strict@client.example", q).case.answers[0]
            assert answer.verdict is Verdict.CANNOT_VERIFY
            assert "bar is 3" in (answer.missing or "")
        finally:
            del os.environ["DESK_MIN_WEB_SOURCES"]
        print("ok  raising the bar to 3 sources flips the answer to a refusal")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
