"""Check what a question takes for granted, before answering it.

"Why did Mahindra Logistics exit Kolkata?" does not ask whether the exit
happened. It assumes it, and asks for a reason. An answering-first pipeline
will dutifully produce a reason, and the reason will be fluent and wrong.

So the presupposition is checked first, and an unsupported one ends the
question. Nothing downstream ever runs.

One honesty point that matters, and that the output wording has to carry: we
can establish that **no source we found states the assumption**. We cannot
establish that the assumption is false. Those are different claims, and the
memo makes the weaker, true one.

The line against ``cannot_verify``:

    false_premise   the question's *assumption* is unsupported
    cannot_verify   the assumption is fine; the *answer* could not be found
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .llm import LLM, LLMError
from .models import Evidence

FindSupport = Callable[[str], list[Evidence]]

_SYSTEM = (
    "You identify what a question takes for granted. You never answer the "
    "question. Reply with a JSON object only."
)

_PROMPT = """A client has asked an analyst the question below about a company.

QUESTION: {question}

List what the question assumes to be true as a precondition of being
answerable at all. A question like "why did X close its Y office" assumes
that X closed its Y office. A question like "how many trucks does X run"
assumes nothing beyond X existing.

Return JSON:
{{
  "claim": "the question restated as a plain claim to be checked",
  "presuppositions": ["each assumption, as a standalone factual claim"],
  "queries": ["search queries that would find evidence for or against them"],
  "needs_city_signal": true or false
}}

Keep presuppositions to things that would make the question unanswerable if
false. Do not list the existence of well-known companies."""


@dataclass
class PremiseCheck:
    question: str
    presuppositions: list[str] = field(default_factory=list)
    supported: dict[str, list[Evidence]] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)
    evidence_against: list[Evidence] = field(default_factory=list)
    claim: str = ""
    queries: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def holds(self) -> bool:
        """True when nothing the question assumes was left unsupported."""
        return not self.unsupported and self.error is None

    def failure_sentence(self) -> str:
        """What the memo says. Deliberately the weaker, defensible claim."""
        if not self.unsupported:
            return ""
        assumption = self.unsupported[0]
        return (
            f"The question assumes {assumption}. No source found states that, "
            "so the question cannot be answered as asked. This is not a finding "
            "that it did not happen -- only that nothing we can cite says it did."
        )


class PremiseChecker:
    def __init__(self, llm: LLM, find_support: FindSupport) -> None:
        self.llm = llm
        self.find_support = find_support

    def plan(self, question: str) -> dict:
        try:
            return self.llm.json(
                purpose="plan",
                system=_SYSTEM,
                prompt=_PROMPT.format(question=question),
            )
        except LLMError:
            # A planner failure must not become an answer. Treat the question
            # as carrying an unknown assumption and let the caller refuse.
            return {}

    def check(self, question: str, plan: dict | None = None) -> PremiseCheck:
        plan = plan if plan is not None else self.plan(question)
        if not plan:
            return PremiseCheck(
                question=question,
                error="could not determine what the question assumes",
            )

        presuppositions = [
            p for p in plan.get("presuppositions", []) if isinstance(p, str) and p.strip()
        ]
        result = PremiseCheck(
            question=question,
            presuppositions=presuppositions,
            claim=str(plan.get("claim", "")),
            queries=[q for q in plan.get("queries", []) if isinstance(q, str)],
        )

        for assumption in presuppositions:
            evidence = self.find_support(assumption)
            if evidence:
                result.supported[assumption] = evidence
            else:
                result.unsupported.append(assumption)

        return result
