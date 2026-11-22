"""LLM access, behind a narrow interface.

Three reasons this is an interface rather than a direct SDK call:

1. **The demo must be rehearsable without credits.** ``ScriptedLLM`` runs the
   whole pipeline offline, so the kill-and-restart rehearsal costs nothing and
   works without a network.
2. **Each judge-facing behaviour is a separate, testable call.** Premise
   checking and entailment are small classification jobs with strict output
   shapes, not open conversation.
3. **Model keys are the team's.** Swapping provider should be one class, not a
   search through the codebase.

Every call returns JSON matching a named schema. A model that fails to produce
valid JSON twice is treated as a failure, not coaxed -- an unparseable answer
must degrade to ``cannot_verify``, never to a guess.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class LLMError(RuntimeError):
    pass


@dataclass
class LLMCall:
    """Recorded for the cost ledger: tokens are part of the per-case cost."""

    purpose: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


class LLM(Protocol):
    def json(
        self, *, purpose: str, system: str, prompt: str, max_tokens: int = 1024
    ) -> dict[str, Any]:
        """Return parsed JSON. Raise LLMError rather than returning prose."""
        ...

    @property
    def calls(self) -> list[LLMCall]:
        ...


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a reply, tolerating code fences."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError(f"no JSON object in reply: {text[:200]!r}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"invalid JSON: {exc}") from exc


class AnthropicLLM:
    """Live model. Imports the SDK lazily so the offline path needs nothing."""

    DEFAULT_MODEL = os.environ.get("DESK_MODEL", "claude-haiku-5-5")

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        max_retries: int = 1,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise LLMError("no model key: set ANTHROPIC_API_KEY")
        # Entailment and premise extraction are small classification jobs run
        # many times per case, so the cheap model is the right default and the
        # per-case cost is noticeably lower for it. Override with DESK_MODEL.
        self.model = model or self.DEFAULT_MODEL
        self.max_retries = max_retries
        self._calls: list[LLMCall] = []
        self._client = None

    def _ensure_client(self):
        if self._client is None:
            try:
                import anthropic  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover
                raise LLMError(
                    "anthropic SDK not installed: pip install anthropic"
                ) from exc
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    @property
    def calls(self) -> list[LLMCall]:
        return list(self._calls)

    def json(
        self, *, purpose: str, system: str, prompt: str, max_tokens: int = 1024
    ) -> dict[str, Any]:
        client = self._ensure_client()
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            msg = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = "".join(
                block.text for block in msg.content if getattr(block, "text", None)
            )
            self._calls.append(
                LLMCall(
                    purpose=purpose,
                    input_tokens=getattr(msg.usage, "input_tokens", 0),
                    output_tokens=getattr(msg.usage, "output_tokens", 0),
                    model=self.model,
                )
            )
            try:
                return _extract_json(text)
            except LLMError as exc:
                last = exc
                prompt = (
                    prompt
                    + "\n\nYour previous reply was not valid JSON. "
                    "Reply with the JSON object alone."
                )
        raise LLMError(f"{purpose}: no valid JSON after {self.max_retries + 1} tries: {last}")


class ScriptedLLM:
    """Deterministic stand-in. Routes on ``purpose`` to a handler.

    This is not a mock that returns a fixed blob: each handler reads the real
    prompt and applies simple, inspectable rules, so an offline run exercises
    the same control flow the live one does -- including the paths that lead to
    a refusal.
    """

    def __init__(
        self, handlers: dict[str, Callable[[str], dict[str, Any]]] | None = None
    ) -> None:
        self.handlers = handlers or {}
        self._calls: list[LLMCall] = []

    @property
    def calls(self) -> list[LLMCall]:
        return list(self._calls)

    def register(self, purpose: str, fn: Callable[[str], dict[str, Any]]) -> None:
        self.handlers[purpose] = fn

    def json(
        self, *, purpose: str, system: str, prompt: str, max_tokens: int = 1024
    ) -> dict[str, Any]:
        self._calls.append(LLMCall(purpose=purpose, model="scripted"))
        handler = self.handlers.get(purpose)
        if handler is None:
            raise LLMError(f"ScriptedLLM has no handler for {purpose!r}")
        return handler(prompt)


def default_offline_llm() -> ScriptedLLM:
    """A scripted model good enough to run the pipeline end to end.

    Deliberately conservative: when its crude rules cannot tell, it returns the
    answer that leads to a refusal. An offline run should under-claim, so that
    a passing offline demo is evidence of nothing worse than caution.
    """
    llm = ScriptedLLM()

    def plan(prompt: str) -> dict[str, Any]:
        question = _between(prompt, "QUESTION:", "\n") or ""
        return {
            "claim": question.strip().rstrip("?"),
            "presuppositions": _naive_presuppositions(question),
            "queries": [question.strip().rstrip("?")],
            "needs_city_signal": bool(
                re.search(r"\b(in|at|from)\s+[A-Z][a-z]+", question)
            ),
        }

    def entail(prompt: str) -> dict[str, Any]:
        claim = (_between(prompt, "CLAIM:", "\nPASSAGE:") or "").strip().lower()
        passage = (_between(prompt, "PASSAGE:", "\nEND PASSAGE") or "").strip().lower()
        if not claim or not passage:
            return {"score": 0.0, "states_claim": False, "why": "missing text"}
        terms = [t for t in re.findall(r"[a-z]{4,}", claim) if t not in _STOP]
        if not terms:
            return {"score": 0.0, "states_claim": False, "why": "no content terms"}
        hits = sum(1 for t in terms if t in passage)
        score = hits / len(terms)
        return {
            "score": round(score, 3),
            "states_claim": score >= 0.75,
            "why": f"{hits}/{len(terms)} content terms present in the passage",
        }

    def presupposition(prompt: str) -> dict[str, Any]:
        # Offline we cannot confirm a presupposition, so we never assert that
        # one holds. The caller treats "unsupported" as grounds to refuse.
        return {
            "supported": False,
            "why": "offline model cannot confirm a presupposition from sources",
        }

    def compose(prompt: str) -> dict[str, Any]:
        return {
            "answer": (_between(prompt, "SUPPORTED CLAIM:", "\n") or "").strip(),
            "confident": True,
        }

    llm.register("plan", plan)
    llm.register("entail", entail)
    llm.register("presupposition", presupposition)
    llm.register("compose", compose)
    return llm


_STOP = {
    "which", "what", "that", "this", "with", "from", "have", "has", "did",
    "does", "since", "been", "they", "their", "there", "when", "where", "whom",
    "into", "about", "rival", "rivals",
}


def _between(text: str, start: str, end: str) -> str | None:
    i = text.find(start)
    if i == -1:
        return None
    j = text.find(end, i + len(start))
    return text[i + len(start) : j if j != -1 else len(text)]


def _naive_presuppositions(question: str) -> list[str]:
    """Spot the question shapes that smuggle in an assumption.

    'Why did X exit Kolkata?' presupposes the exit. A question starting with
    why/when/how much is asserting that the thing happened, and that assertion
    is what has to be checked before the question is worth answering.
    """
    q = question.strip()
    m = re.match(
        r"^\s*(why|when|how much|how many|how long)\s+(did|does|is|are|has|have|was|were)\s+(.+?)\??$",
        q,
        re.I,
    )
    if m:
        return [m.group(3).strip()]
    return []
