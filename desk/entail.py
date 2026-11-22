"""Does this passage, read alone, state this claim?

The brief is unusually specific here: the source must state the fact itself,
and a page about the same topic is not enough. That rules out the ordinary
retrieval habit of citing the page the answer was found near.

So each candidate passage is checked in isolation -- the claim and the span,
with no surrounding page, no question, and no other evidence. If the span does
not carry the claim on its own, it is discarded rather than down-weighted. A
judge can check this in about ten seconds by reading one quoted sentence, so
half-passing is worse than not trying.

Two failure modes the prompt names explicitly, because they are the ones that
slip through:

* **Topical overlap.** A passage about a company's Guwahati operations does not
  state that the company started hiring there in September.
* **Direction.** "X denied exiting Kolkata" does not state that X exited
  Kolkata; it states the opposite.
"""

from __future__ import annotations

from dataclasses import dataclass

from .llm import LLM, LLMError

_SYSTEM = (
    "You judge whether a single passage of text states a specific claim. "
    "You are strict. Reply with a JSON object only."
)

_PROMPT = """Decide whether the passage below, read on its own, states the claim.

CLAIM: {claim}
PASSAGE:
{passage}
END PASSAGE

Rules:
- The passage must state the claim, not merely discuss the same subject.
- If the passage implies the opposite, or reports someone denying it, that is
  not support.
- If the passage is about a different entity with a similar name, that is not
  support.
- Missing a specific in the claim (a city, a date, a number) means the passage
  does not state the claim.
- Being plausible, or consistent with the claim, is not stating it.

Return JSON:
{{
  "score": 0.0 to 1.0,
  "states_claim": true or false,
  "why": "one sentence, naming what is present or missing"
}}"""


@dataclass
class Entailment:
    score: float
    states_claim: bool
    why: str

    @classmethod
    def failed(cls, why: str) -> "Entailment":
        return cls(score=0.0, states_claim=False, why=why)


class EntailmentChecker:
    def __init__(self, llm: LLM, threshold: float = 0.75) -> None:
        self.llm = llm
        self.threshold = threshold

    def check(self, claim: str, passage: str) -> Entailment:
        if not claim.strip() or not passage.strip():
            return Entailment.failed("empty claim or passage")

        try:
            raw = self.llm.json(
                purpose="entail",
                system=_SYSTEM,
                prompt=_PROMPT.format(claim=claim.strip(), passage=passage.strip()),
                max_tokens=300,
            )
        except LLMError as exc:
            # An unreadable judgement is not a pass. Evidence we cannot verify
            # is evidence we do not use.
            return Entailment.failed(f"entailment check failed: {exc}")

        try:
            score = float(raw.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0

        states = bool(raw.get("states_claim")) and score >= self.threshold
        return Entailment(
            score=score,
            states_claim=states,
            why=str(raw.get("why", "")),
        )
