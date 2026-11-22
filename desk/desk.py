"""The orchestrator: a case from request to memo.

Per question, in this order and no other:

    plan -> resolve the company -> check the premise -> gather evidence
         -> decide -> record

Each stage runs through ``journal.once``, so a kill at any point resumes from
the last completed stage rather than from the top. That is not only about the
demo: searches cost credits, and redoing them after every crash is a real bill.

Cost is attributed per question by snapshotting the ledger either side of the
work, so the memo can say what each answer cost rather than only what the case
cost.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .approval import ApprovalGate, Decision
from .config import Config
from .crustdata import CrustdataClient
from .entail import EntailmentChecker
from .evidence import EvidenceGatherer, Gathering, default_window
from .journal import Journal, RecordKind, once
from .ledger import CostLedger
from .llm import LLM
from .memo import render_case
from .models import Answer, Case, Evidence, SourceKind, Verdict
from .premise import PremiseChecker
from .resolve import EntityResolver, Resolution
from .rivals import RivalRegistry
from .verdict import decide


@dataclass
class CaseResult:
    case: Case
    memo: str
    decision: Decision | None
    sent: bool
    halted: bool = False
    halt_reason: str | None = None


class CompetitorMoveDesk:
    def __init__(
        self,
        *,
        config: Config,
        client: CrustdataClient,
        llm: LLM,
        ledger: CostLedger,
        journal: Journal,
        registry: RivalRegistry | None = None,
        approval_mode: str = "interactive",
    ) -> None:
        self.config = config
        self.client = client
        self.llm = llm
        self.ledger = ledger
        self.journal = journal
        self.registry = registry or RivalRegistry.load()

        self.entailment = EntailmentChecker(
            llm, threshold=config.evidence_bar.min_entailment_score
        )
        self.gatherer = EvidenceGatherer(
            client,
            self.entailment,
            max_fetches=config.limits.max_fetches_per_question,
            search_pages=config.limits.max_search_pages,
        )
        self.resolver = EntityResolver(self.registry, client)
        self.premise = PremiseChecker(llm, self._find_support)
        self.gate = ApprovalGate(
            journal,
            mode=approval_mode,  # type: ignore[arg-type]
            timeout_seconds=config.approval.approval_timeout_seconds,
        )

    # ------------------------------------------------------------------

    def run(self, requester: str, questions: list[str]) -> CaseResult:
        case_id = Case.new_id(requester, questions)
        case = Case(
            case_id=case_id,
            requester=requester,
            questions=questions,
            schema_version=self.config.schema_version,
        )

        state = self.journal.replay()
        if state.needs_adjudication:
            reason = (
                "An irreversible step was begun and never confirmed. A person "
                "must decide whether it took effect before this case continues."
            )
            return CaseResult(
                case=case, memo="", decision=None, sent=False,
                halted=True, halt_reason=reason,
            )

        if not state.finished:
            self.journal.append(
                RecordKind.CASE_OPENED, requester=requester, questions=questions
            )

        started = time.monotonic()
        for question in questions:
            if time.monotonic() - started > self.config.limits.max_wall_seconds:
                case.answers.append(
                    Answer(
                        question=question,
                        verdict=Verdict.CANNOT_VERIFY,
                        missing=(
                            "The run reached its time limit before this question "
                            "was researched."
                        ),
                    )
                )
                continue
            case.answers.append(self._answer_one(case_id, question))

        memo = render_case(case)

        summary = (
            f"{len(case.answers)} question(s), "
            f"{case.billable_questions} answered, "
            f"{case.total_credits:g} credits"
        )
        decision = self.gate.request(memo, summary=summary)

        sent = False
        if decision.approved:
            sent = self._send(case_id, requester, memo)
            case.status = "sent" if sent else "awaiting_approval"
        else:
            case.status = "awaiting_approval"

        self.journal.append(
            RecordKind.CASE_CLOSED,
            status=case.status,
            totals=case.to_dict()["totals"],
        )
        return CaseResult(case=case, memo=memo, decision=decision, sent=sent)

    # ------------------------------------------------------------------

    def _answer_one(self, case_id: str, question: str) -> Answer:
        started = time.monotonic()
        credits_before = self.ledger.total_credits

        plan = once(self.journal, "plan", {"q": question},
                    lambda: self.premise.plan(question))

        resolution = once(
            self.journal, "resolve", {"q": question},
            lambda: self._resolve_for(question),
        )
        resolution_obj = _rehydrate_resolution(resolution)

        # An ambiguous or unknown company short-circuits: researching the
        # wrong entity thoroughly is worse than not researching at all.
        if resolution_obj is not None and resolution_obj.status != "resolved":
            answer = decide(
                question,
                bar=self.config.evidence_bar,
                resolution=resolution_obj,
                premise=None,
                gathering=None,
            )
            return self._finish(answer, credits_before, started)

        since, until = default_window()
        search_terms = (
            resolution_obj.search_terms
            if resolution_obj and resolution_obj.search_terms
            else [question]
        )

        premise = once(
            self.journal, "premise", {"q": question},
            lambda: _premise_to_dict(self.premise.check(question, plan)),
        )
        premise_obj = _rehydrate_premise(premise)

        if premise_obj is not None and not premise_obj.holds:
            context = once(
                self.journal, "gather_context", {"q": question},
                lambda: _gathering_to_dict(
                    self.gatherer.gather(
                        _context_claim(question, search_terms),
                        queries=(premise_obj.queries or [question])[:2],
                        since=since, until=until,
                    )
                ),
            )
            answer = decide(
                question,
                bar=self.config.evidence_bar,
                resolution=resolution_obj,
                premise=premise_obj,
                gathering=_rehydrate_gathering(context),
            )
            return self._finish(answer, credits_before, started)

        claim = str(plan.get("claim") or question)
        gathering = once(
            self.journal, "gather", {"q": question},
            lambda: _gathering_to_dict(
                self.gatherer.gather(
                    claim,
                    queries=(plan.get("queries") or [question])[:3],
                    since=since, until=until,
                )
            ),
        )

        answer = decide(
            question,
            bar=self.config.evidence_bar,
            resolution=resolution_obj,
            premise=premise_obj,
            gathering=_rehydrate_gathering(gathering),
            since=since,
            until=until,
        )
        return self._finish(answer, credits_before, started)

    def _finish(
        self, answer: Answer, credits_before: float, started: float
    ) -> Answer:
        answer.credits_used = round(self.ledger.total_credits - credits_before, 4)
        answer.cost_inr = round(
            answer.credits_used * self.config.pricing.inr_per_credit, 4
        )
        answer.elapsed_seconds = round(time.monotonic() - started, 2)
        self.journal.append(RecordKind.ANSWER_RECORDED, answer=answer.to_dict())
        return answer

    def _resolve_for(self, question: str) -> dict[str, Any] | None:
        mentioned = self.registry.mentioned_in(question)
        if not mentioned:
            return None
        if len(mentioned) > 1:
            # Several rivals named in one question is a legitimate shape
            # ("which rivals hired in Guwahati"), not ambiguity. Resolve the
            # first and let the gatherer widen across the rest.
            terms: list[str] = []
            for m in mentioned:
                terms.extend(m.rival.search_terms())
            return {
                "query": question,
                "status": "resolved",
                "entity": {"display_name": "multiple named rivals"},
                "candidates": [],
                "search_terms": terms,
                "cautions": [m.caution for m in mentioned if m.caution],
                "why": f"{len(mentioned)} rivals named in the question",
            }
        return _resolution_to_dict(self.resolver.resolve(mentioned[0].matched_on))

    def _find_support(self, claim: str) -> list[Evidence]:
        """Used by the premise checker. Narrow and cheap on purpose."""
        since, until = default_window()
        g = self.gatherer.gather(
            claim, queries=[claim], since=since, until=until, stop_after=1
        )
        return g.accepted

    def _send(self, case_id: str, requester: str, memo: str) -> bool:
        """The irreversible action. Journalled before, confirmed after."""

        def deliver() -> dict[str, Any]:
            # Replace with the real transport. Writing the file IS the send
            # here, and it is deliberately the last thing that happens.
            path = f"{self.journal.dir}/{case_id}.memo.md"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(memo)
            return {"delivered_to": requester, "path": path}

        result = once(
            self.journal, "send_memo", {"to": requester, "case": case_id},
            deliver, irreversible=True,
        )
        return bool(result)


# ---------------------------------------------------------------------------
# The journal stores plain JSON, so these convert each stage's object to and
# from dicts. Kept as functions rather than methods to make it obvious that
# nothing survives a restart except what was serialised.
# ---------------------------------------------------------------------------


def _resolution_to_dict(r: Resolution) -> dict[str, Any]:
    return {
        "query": r.query,
        "status": r.status,
        "entity": r.entity.to_dict() if r.entity else None,
        "candidates": [c.to_dict() for c in r.candidates],
        "search_terms": r.search_terms,
        "cautions": r.cautions,
        "why": r.why,
    }


def _rehydrate_resolution(d: dict[str, Any] | None) -> Resolution | None:
    if not d:
        return None
    from .models import EntityCandidate

    return Resolution(
        query=d.get("query", ""),
        status=d.get("status", "unknown"),
        entity=EntityCandidate(**d["entity"]) if d.get("entity") else None,
        candidates=[EntityCandidate(**c) for c in d.get("candidates", [])],
        search_terms=d.get("search_terms", []),
        cautions=d.get("cautions", []),
        why=d.get("why", ""),
    )


def _premise_to_dict(p) -> dict[str, Any]:
    return {
        "question": p.question,
        "presuppositions": p.presuppositions,
        "unsupported": p.unsupported,
        "claim": p.claim,
        "queries": p.queries,
        "error": p.error,
        "supported_keys": list(p.supported.keys()),
    }


def _rehydrate_premise(d: dict[str, Any] | None):
    if not d:
        return None
    from .premise import PremiseCheck

    return PremiseCheck(
        question=d.get("question", ""),
        presuppositions=d.get("presuppositions", []),
        supported={k: [] for k in d.get("supported_keys", [])},
        unsupported=d.get("unsupported", []),
        claim=d.get("claim", ""),
        queries=d.get("queries", []),
        error=d.get("error"),
    )


def _gathering_to_dict(g: Gathering) -> dict[str, Any]:
    return {
        "claim": g.claim,
        "accepted": [e.to_dict() for e in g.accepted],
        "rejected": g.rejected,
        "searched": g.searched,
        "fetched": g.fetched,
        "fetch_failures": g.fetch_failures,
        "window": g.window,
        "note": g.note,
    }


def _rehydrate_gathering(d: dict[str, Any] | None) -> Gathering | None:
    if not d:
        return None
    from .models import DateKind

    accepted = []
    for e in d.get("accepted", []):
        accepted.append(
            Evidence(
                claim=e["claim"],
                exact_passage=e["exact_passage"],
                source_url=e["source_url"],
                source_kind=SourceKind(e["source_kind"]),
                record_date=e.get("record_date"),
                date_kind=DateKind(e["date_kind"]),
                retrieved_at=e.get("retrieved_at", ""),
                passage_offset=e.get("passage_offset"),
                entailment_score=e.get("entailment_score"),
                source_domain=e.get("source_domain"),
                note=e.get("note"),
            )
        )
    return Gathering(
        claim=d.get("claim", ""),
        accepted=accepted,
        rejected=d.get("rejected", []),
        searched=d.get("searched", []),
        fetched=d.get("fetched", []),
        fetch_failures=d.get("fetch_failures", []),
        window=d.get("window"),
        note=d.get("note"),
    )


def _context_claim(question: str, terms: list[str]) -> str:
    who = terms[0] if terms else ""
    return f"{who} {question}".strip()
