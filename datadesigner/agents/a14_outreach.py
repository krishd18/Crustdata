"""A14 Outreach & Mail (ARCHITECTURE §17): drafts from verified ledger facts + approved templates, policy guard,
approval queue. Sending is done only by the exactly-once executor (datadesigner/mail/executor.py) after approval."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..mail import drafter, guard
from .base import BaseAgent, cli


class OutreachInput(BaseModel):
    template: str                       # doc_request | teaser_request | clarification | intro | decline
    company: dict
    recipient: str
    asks: list[dict] = Field(default_factory=list)          # [{document, claim_text}]
    items: list[dict] = Field(default_factory=list)         # clarification items
    facts: dict[str, dict] = Field(default_factory=dict)    # slot → {text, evidence_id, cls}
    decision_label: str | None = None


class Actions(BaseModel):
    action_ids: list[str]
    refused: list[str] = Field(default_factory=list)


class Outreach(BaseAgent[OutreachInput, Actions]):
    name, input_model, output_model = "a14_outreach", OutreachInput, Actions

    def run(self, inp: OutreachInput, ctx) -> Actions:
        cfg = ctx.config
        client = cfg.get("client", {}) or {"name": "the client (sample 3PL)", "regions": ["Delhi", "Gujarat", "Karnataka"]}
        ctxv = {"company": inp.company, "recipient": {"name": None}, "client": client, "approver": {"name": "the reviewing analyst"},
                "asks": inp.asks, "items": inp.items, "mandate": {"region": "Maharashtra"}, "optional_reason": ""}
        subject, body, evids = drafter.render(cfg.template(inp.template), ctxv, inp.facts)
        draft = {"template": inp.template, "to": inp.recipient, "subject": subject, "body": body}
        try:
            guard.check(draft, cfg["mail"], ctx.stores, ctx.settings, inp.decision_label)
        except guard.PolicyViolation as e:
            return Actions(action_ids=[], refused=[str(e)])
        aid = drafter.queue(ctx.stores, ctx.run_id, inp.template, inp.recipient, subject, body, inp.company.get("name", ""), evids)
        return Actions(action_ids=[aid])


AGENT = Outreach()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
