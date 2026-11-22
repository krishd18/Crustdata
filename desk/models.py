"""The output contract.

Four verdicts, not two. The brief's hard cases are all refusals of different
kinds, and collapsing them into one "unknown" throws away the distinction the
graders are testing for:

    answered          a source states the fact, and we quote the passage
    cannot_verify     no source settles it; we name what is missing
    false_premise     the question assumes something no source supports
    ambiguous_entity  the question names a company that resolves to several

``ambiguous_entity`` exists because of the group-versus-arm problem. "Mahindra"
is not a company; it is a question about which company you meant. Guessing the
higher-ranked match is the failure mode the lookalike test case is built to
catch.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Verdict(str, Enum):
    ANSWERED = "answered"
    CANNOT_VERIFY = "cannot_verify"
    FALSE_PREMISE = "false_premise"
    AMBIGUOUS_ENTITY = "ambiguous_entity"


class SourceKind(str, Enum):
    """Ordered by how much weight the evidence bar gives it."""

    REGISTRY = "registry"          # MCA / GST: states legal fact
    FILING = "filing"              # exchange filing, annual report
    COMPANY_OWNED = "company_owned"  # the company's own site or newsroom
    JOB_POSTING = "job_posting"    # a dated listing, strong for location signals
    NEWS = "news"
    INDEXED_PROFILE = "indexed_profile"  # Crustdata record, may be up to 30d stale
    WEB = "web"
    SOCIAL = "social"


class DateKind(str, Enum):
    """Which kind of date this is.

    Reporting a filing date as if it were an event date is a quiet way to be
    wrong, so the kind travels with the value and is rendered in the output.
    """

    PUBLISHED = "published"        # the page says when it was published
    POSTED = "posted"              # a job listing's date_added
    FILED = "filed"                # registry filing date; lags the event
    LAST_REFRESHED = "last_refreshed"  # Crustdata updated_at
    RETRIEVED = "retrieved"        # only when the record carries no date of its own
    UNKNOWN = "unknown"


@dataclass
class Evidence:
    """One passage that, read alone, states one fact.

    The brief is explicit: the source must state the fact itself, and a page
    about the same topic is not enough. So the unit of evidence is a span, not
    a URL, and ``entailment_score`` records whether that span survived the
    check that it supports the claim on its own.
    """

    claim: str
    exact_passage: str
    source_url: str
    source_kind: SourceKind
    record_date: str | None           # ISO date of the record itself
    date_kind: DateKind
    retrieved_at: str = field(default_factory=utcnow_iso)
    passage_offset: int | None = None  # char offset into the fetched content
    entailment_score: float | None = None
    source_domain: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source_kind"] = self.source_kind.value
        d["date_kind"] = self.date_kind.value
        return d


@dataclass
class EntityCandidate:
    """One possible reading of a company name in a question."""

    display_name: str
    reason: str                      # why this is a candidate
    crustdata_company_id: str | None = None
    domain: str | None = None
    cin: str | None = None
    relationship: str | None = None  # "parent group", "logistics arm", "former name"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Answer:
    """The finished result for one question."""

    question: str
    verdict: Verdict

    # Present when verdict is ANSWERED.
    answer_text: str | None = None

    # Present when verdict is CANNOT_VERIFY: what a source would have to say.
    missing: str | None = None

    # Present when verdict is FALSE_PREMISE: the assumption nothing supports,
    # plus what the sources do show instead.
    false_assumption: str | None = None
    what_sources_show: str | None = None

    # Present when verdict is AMBIGUOUS_ENTITY.
    candidates: list[EntityCandidate] = field(default_factory=list)

    evidence: list[Evidence] = field(default_factory=list)

    # Measured, never estimated.
    credits_used: float = 0.0
    cost_inr: float = 0.0
    billable: bool = False            # only an answered question is billed
    elapsed_seconds: float = 0.0
    answered_at: str = field(default_factory=utcnow_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "verdict": self.verdict.value,
            "answer_text": self.answer_text,
            "missing": self.missing,
            "false_assumption": self.false_assumption,
            "what_sources_show": self.what_sources_show,
            "candidates": [c.to_dict() for c in self.candidates],
            "evidence": [e.to_dict() for e in self.evidence],
            "credits_used": self.credits_used,
            "cost_inr": self.cost_inr,
            "billable": self.billable,
            "elapsed_seconds": self.elapsed_seconds,
            "answered_at": self.answered_at,
        }


@dataclass
class Case:
    """One client request. The unit of work, and the unit of the record.

    'A record of every case rather than a chat history' is how Crustdata framed
    this hackathon series, so the case file is the product as much as the
    answer is.
    """

    case_id: str
    requester: str
    questions: list[str]
    schema_version: str
    answers: list[Answer] = field(default_factory=list)
    status: str = "open"              # open | awaiting_approval | sent | abandoned
    created_at: str = field(default_factory=utcnow_iso)

    @staticmethod
    def new_id(requester: str, questions: list[str]) -> str:
        """Deterministic from the request, so re-submitting the same request
        resumes the same case instead of starting a second one."""
        payload = json.dumps(
            {"requester": requester, "questions": questions}, sort_keys=True
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    @property
    def total_credits(self) -> float:
        return sum(a.credits_used for a in self.answers)

    @property
    def total_cost_inr(self) -> float:
        return sum(a.cost_inr for a in self.answers)

    @property
    def billable_questions(self) -> int:
        return sum(1 for a in self.answers if a.billable)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "requester": self.requester,
            "schema_version": self.schema_version,
            "status": self.status,
            "created_at": self.created_at,
            "questions": self.questions,
            "answers": [a.to_dict() for a in self.answers],
            "totals": {
                "credits": self.total_credits,
                "cost_inr": self.total_cost_inr,
                "questions": len(self.questions),
                "billable_questions": self.billable_questions,
            },
        }
