"""Render a case as the memo the client receives.

Every claim is followed by the passage that states it, its date and the kind
of date it is. That last part is what makes the memo auditable: a reader can
see at a glance whether "October 2026" is when the page was published or
merely when we fetched it.

Refusals are rendered as prominently as answers. A memo where the
``cannot_verify`` is in small print is a memo designed to be skimmed into a
wrong decision.
"""

from __future__ import annotations

from .models import Answer, Case, DateKind, Verdict

_DATE_WORDING = {
    DateKind.PUBLISHED: "published",
    DateKind.POSTED: "posted",
    DateKind.FILED: "filed",
    DateKind.LAST_REFRESHED: "record last refreshed",
    DateKind.RETRIEVED: "only retrieved",
    DateKind.UNKNOWN: "date unclear",
}

_HEADING = {
    Verdict.ANSWERED: "Answer",
    Verdict.CANNOT_VERIFY: "Cannot verify",
    Verdict.FALSE_PREMISE: "False premise",
    Verdict.AMBIGUOUS_ENTITY: "Which company?",
}


def render_answer(answer: Answer, index: int) -> str:
    out = [f"### {index}. {answer.question}", "", f"**{_HEADING[answer.verdict]}**", ""]

    if answer.verdict is Verdict.ANSWERED:
        out += [answer.answer_text or "", ""]

    elif answer.verdict is Verdict.CANNOT_VERIFY:
        out += [
            answer.missing or "No source settles this.",
            "",
            "_No answer is given because none can be sourced. "
            "This is not a finding either way._",
            "",
        ]

    elif answer.verdict is Verdict.FALSE_PREMISE:
        out += [
            f"The question assumes: **{answer.false_assumption}**",
            "",
            "No source found states that, so the question cannot be answered "
            "as asked. This is not a finding that it did not happen — only "
            "that nothing we can cite says it did.",
            "",
        ]
        if answer.what_sources_show:
            out += ["What the sources do show:", "", answer.what_sources_show, ""]

    elif answer.verdict is Verdict.AMBIGUOUS_ENTITY:
        out += [
            answer.missing or "This name matches more than one company.",
            "",
            "Candidates:",
            "",
        ]
        for c in answer.candidates:
            rel = f" — {c.relationship}" if c.relationship else ""
            out.append(f"- **{c.display_name}**{rel}  \n  {c.reason}")
        out.append("")

    if answer.evidence:
        out += ["**Sources**", ""]
        for e in answer.evidence:
            when = (
                f"{e.record_date} ({_DATE_WORDING[e.date_kind]})"
                if e.record_date
                else f"no date on the record — {_DATE_WORDING[e.date_kind]} "
                f"{e.retrieved_at[:10]}"
            )
            score = (
                f", entailment {e.entailment_score:.2f}"
                if e.entailment_score is not None
                else ""
            )
            out += [
                f"- > {e.exact_passage.strip()}",
                f"  {e.source_url}  \n  {when}{score}",
            ]
        out.append("")

    cost = f"{answer.credits_used:g} credits"
    if answer.cost_inr:
        cost += f" (INR {answer.cost_inr:.2f})"
    out += [f"_{cost} · {'billable' if answer.billable else 'not billed'}_", ""]
    return "\n".join(out)


def render_case(case: Case) -> str:
    counts: dict[str, int] = {}
    for a in case.answers:
        counts[a.verdict.value] = counts.get(a.verdict.value, 0) + 1
    summary = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in sorted(counts.items()))

    out = [
        "# Competitor Move Desk — case memo",
        "",
        f"Case `{case.case_id}` · for {case.requester} · opened {case.created_at}",
        f"Contract `{case.schema_version}`",
        "",
        f"{len(case.answers)} question(s): {summary or 'none answered'}.",
        "",
        "---",
        "",
    ]
    for i, answer in enumerate(case.answers, start=1):
        out.append(render_answer(answer, i))
        out.append("---")
        out.append("")

    out += [
        "## Cost",
        "",
        f"- {case.total_credits:g} credits across {len(case.answers)} question(s)",
        f"- INR {case.total_cost_inr:.2f}"
        + ("" if case.total_cost_inr else "  _(set DESK_INR_PER_CREDIT to price this)_"),
        f"- Billed: {case.billable_questions} of {len(case.answers)} "
        "(only answered questions are billed)",
        "",
    ]
    return "\n".join(out)
