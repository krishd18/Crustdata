"""Drafter (A14): renders config/templates/*.md.j2 using ONLY ledger facts (each slot keeps its evidence id),
then queues the draft for approval. action_id = sha256(run|template|recipient|content)."""
from __future__ import annotations

import time

from jinja2 import Environment, StrictUndefined

from ..core.ids import canon, sha256


def action_id(run_id: str, template: str, recipient: str, content: str) -> str:
    return sha256(canon([run_id, template, recipient, sha256(content)]))[:32]


def render(template_src: str, ctx: dict, facts: dict[str, dict]) -> tuple[str, str, list[str]]:
    """Return (subject, body, evidence_ids). `facts` = slot → {text, evidence_id, cls}; unknown slots render ''."""
    used: list[str] = []

    def fact(slot: str) -> str:
        f = facts.get(slot)
        if not f:
            return ""
        used.append(f.get("evidence_id", ""))
        label = "" if f.get("cls") in ("VERIFIED", "PARTIALLY_VERIFIED", None) else " (as stated in your materials)"
        return f["text"] + label

    env = Environment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)
    out = env.from_string(template_src).render(fact=fact, **ctx)
    first, _, rest = out.partition("\n")
    subject = first.replace("Subject:", "").strip()
    return subject, rest.strip() + "\n", [u for u in used if u]


def queue(stores, run_id: str, template: str, to: str, subject: str, body: str, company: str, evidence_ids: list[str],
          kind: str = "email", version: int = 1) -> str:
    aid = action_id(run_id, template, to, subject + "\n" + body)
    draft = {"action_id": aid, "run_id": run_id, "template": template, "to": to, "subject": subject, "body": body,
             "company": company, "evidence_ids": evidence_ids}
    stores.x("INSERT OR IGNORE INTO approvals(action_id,run_id,kind,draft_json,status,decided_by,reason,at,version) VALUES(?,?,?,?,?,?,?,?,?)",
             (aid, run_id, kind, canon(draft), "pending", "", "", time.time(), version))
    stores.journal(aid, "drafted", {"template": template, "company": company})
    return aid
