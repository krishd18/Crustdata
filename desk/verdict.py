"""Turn gathered evidence into one of four verdicts.

The order matters, and it is not arbitrary. Each check answers a question that
makes the next one meaningless if it fails:

1. **Which company?** If the name is ambiguous, every fact after it is about an
   entity nobody chose. Stop.
2. **Is the question's assumption supported?** If not, there is nothing to
   answer. Stop.
3. **Does the evidence clear the bar?** If not, say what is missing.
4. Only now, answer.

The bar itself lives in ``config.EvidenceBar`` so it can be moved without
touching this file -- including at hour three, when the organisers change a
requirement for every team.
"""

from __future__ import annotations

from .config import EvidenceBar
from .dating import in_window
from .evidence import Gathering
from .models import Answer, Verdict
from .premise import PremiseCheck
from .resolve import Resolution


def decide(
    question: str,
    *,
    bar: EvidenceBar,
    resolution: Resolution | None,
    premise: PremiseCheck | None,
    gathering: Gathering | None,
    answer_text: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> Answer:
    # 1. Which company.
    if resolution is not None and resolution.status == "ambiguous":
        return Answer(
            question=question,
            verdict=Verdict.AMBIGUOUS_ENTITY,
            candidates=resolution.candidates,
            missing=(
                resolution.why
                + ". Name the entity you mean and the question can be answered."
            ),
            billable=False,
        )

    if resolution is not None and resolution.status == "unknown":
        return Answer(
            question=question,
            verdict=Verdict.CANNOT_VERIFY,
            missing=(
                f"No company could be matched to '{resolution.query}'. "
                "A registry identifier or a website would settle it."
            ),
            billable=False,
        )

    # 2. What the question assumes.
    if premise is not None and not premise.holds:
        if premise.error:
            return Answer(
                question=question,
                verdict=Verdict.CANNOT_VERIFY,
                missing=premise.error,
                billable=False,
            )
        return Answer(
            question=question,
            verdict=Verdict.FALSE_PREMISE,
            false_assumption=premise.unsupported[0],
            what_sources_show=_what_sources_show(gathering),
            evidence=list(gathering.accepted) if gathering else [],
            billable=False,
        )

    # 3. The bar.
    if gathering is None or not gathering.accepted:
        return Answer(
            question=question,
            verdict=Verdict.CANNOT_VERIFY,
            missing=_missing_sentence(gathering),
            billable=False,
        )

    shortfall = _shortfall(gathering, bar, since=since, until=until)
    if shortfall:
        return Answer(
            question=question,
            verdict=Verdict.CANNOT_VERIFY,
            missing=shortfall,
            evidence=list(gathering.accepted),
            billable=False,
        )

    # 4. Answer.
    return Answer(
        question=question,
        verdict=Verdict.ANSWERED,
        answer_text=answer_text or gathering.accepted[0].exact_passage,
        evidence=list(gathering.accepted),
        billable=True,
    )


def _shortfall(
    g: Gathering, bar: EvidenceBar, *, since: str | None, until: str | None
) -> str | None:
    """What the evidence is short of. None means the bar is cleared."""
    dated = [e for e in g.accepted if e.record_date]
    undated = len(g.accepted) - len(dated)

    if bar.registry_source_is_sufficient and g.has_registry_source():
        registry_dated = [
            e for e in dated if e.source_kind.value in ("registry", "filing")
        ]
        if registry_dated:
            return None

    if bar.enforce_question_time_window and (since or until):
        in_range = [e for e in dated if in_window(e.record_date, since, until)]
        if not in_range:
            if dated:
                return (
                    f"{len(dated)} source(s) state this, but none carries a date "
                    f"inside the period asked about"
                    + (f" (from {since})" if since else "")
                    + ". A dated record from within that period would settle it."
                )
            return (
                "The sources found carry no date of their own, so none can "
                "support a claim about a specific period. A dated record is "
                "what is missing."
            )
        usable = in_range
    else:
        usable = dated

    if not usable:
        return (
            f"{len(g.accepted)} passage(s) state this, but "
            + (
                "none carries a date of its own"
                if undated
                else "none could be dated"
            )
            + ". An undated source cannot support a claim about when something "
            "happened."
        )

    domains = {e.source_domain for e in usable if e.source_domain}
    if len(domains) < bar.min_independent_web_sources:
        return (
            f"Only {len(domains)} independent source(s) state this; the bar is "
            f"{bar.min_independent_web_sources}. "
            f"A second publisher, or a registry record, would settle it."
        )

    return None


def _missing_sentence(g: Gathering | None) -> str:
    if g is None:
        return "No evidence was gathered for this question."
    if g.note:
        base = g.note
    elif g.rejected:
        base = (
            f"{len(g.rejected)} passage(s) were found on this subject, but none "
            "states the claim itself"
        )
    else:
        base = "No source found states this"
    extra = ""
    if g.fetch_failures:
        extra = f" {len(g.fetch_failures)} page(s) could not be fetched."
    return base.rstrip(".") + "." + extra


def _what_sources_show(g: Gathering | None) -> str:
    """For a false premise: report what was actually found, without inventing
    a counter-claim. Silence in the sources is not proof of the negative."""
    if g is None or not g.accepted:
        return (
            "Nothing found on this subject states the assumption either way. "
            "Absence of a report is not evidence that the event did not happen."
        )
    lines = []
    for e in g.accepted[:3]:
        when = f" ({e.record_date})" if e.record_date else " (undated)"
        lines.append(f"{e.exact_passage[:200]}{when} — {e.source_url}")
    return " | ".join(lines)
