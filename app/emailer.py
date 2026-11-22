"""Draft the diligence request email from the fixed document table.

The list itself always comes from doc_table (via the run result). Claude only
writes the short framing around it, and is told not to add or drop items; if
no LLM is configured, a plain template is used.
"""
from __future__ import annotations

import logging

from . import extract

log = logging.getLogger("secondlook.email")


def compose_intro(company: str, sender_org: str, purpose: str, why: str | None = None) -> tuple[str, str]:
    """Step 3: first contact, asking for a teaser or capability deck.

    Plain template on purpose: it states who we are and what we want, and
    makes no claims about the company beyond what the sender typed in `why`.
    """
    subject = f"{sender_org} and {company}: {purpose}"
    p = purpose.strip().rstrip(".")
    p = p[:1].lower() + p[1:]  # "Exploring X in South India" -> "exploring X in South India"
    lines = [
        f"Hello {company} team,",
        "",
        f"I'm writing from {sender_org}. We're {p}, and {company} is on our shortlist"
        + (f" because {why.strip().rstrip('.')}." if why else "."),
        "",
        "Could you share a short teaser or capability deck: what you do, where you operate, scale, and the "
        "customers you work with? If it's a fit, we'd like to set up a 30-minute call.",
        "",
        "Happy to sign an NDA first if you'd prefer.",
        "",
        "Best regards,",
        sender_org,
    ]
    return subject, "\n".join(lines)


def compose(result: dict, sender_org: str = "our team") -> tuple[str, str, dict]:
    company = result["company"]["name"]
    reqs = result.get("requests", [])
    subject = f"{company}: documents requested before our next meeting"
    items = "\n".join(f"{i}. {r['document']}\n   (re: \"{r['claim']}\")" for i, r in enumerate(reqs, 1))
    usage: dict = {}
    intro, outro = (
        f"Thank you for the time last week. Ahead of our second meeting, could you share the documents below? "
        f"Each one relates to a point in the material you sent.",
        "Redacted copies are fine where amounts are commercially sensitive. Happy to sign an NDA first if needed.",
    )
    if extract.llm_available() and reqs:
        try:
            import anthropic

            client = anthropic.Anthropic()
            resp = client.beta.messages.create(
                model=extract.MODEL, max_tokens=2000,
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": {
                    "type": "object", "additionalProperties": False, "required": ["intro", "outro"],
                    "properties": {"intro": {"type": "string"}, "outro": {"type": "string"}}}}},
                messages=[{"role": "user", "content": (
                    f"Write a 2-sentence intro and a 1-sentence close for a polite, direct email from {sender_org} "
                    f"to {company} requesting diligence documents before a second meeting. A numbered list of "
                    f"documents goes between them; do not restate, add or remove items, and make no accusations.\n\n"
                    f"The list:\n{items}")}],
            )
            usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
            if resp.stop_reason != "refusal":
                import json
                parts = json.loads(next(b.text for b in resp.content if b.type == "text"))
                intro, outro = parts["intro"], parts["outro"]
        except Exception as e:
            log.warning("email polish failed, using template: %s", e)
    body = f"Hello,\n\n{intro}\n\n{items}\n\n{outro}\n\nBest regards,\n{sender_org}"
    return subject, body, usage
