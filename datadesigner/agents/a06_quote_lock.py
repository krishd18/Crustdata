"""A6 Quote-Lock Verifier (ARCHITECTURE §10): accepts a candidate only if its passage exists verbatim (after
normalisation) in the stored blob, or its JSON field equals the stored value. Acceptance is purely deterministic;
an LLM-proposed passage that fails is dropped and logged (threshold: planted fake passages accepted = 0)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..core.quote_lock import lock, lock_field
from ..core.types import Evidence
from .base import BaseAgent, cli


class Candidate(BaseModel):
    claim_id: str = ""
    source: str
    url_or_endpoint: str
    blob_sha: str
    passage: str | None = None
    field_path: str | None = None
    value: Any = None
    record_date: str | None = None
    tier: str
    media_tier: str | None = None
    relation: str = "supports"
    kind: str = "field"
    attributed_to_company_quote: bool = False
    raw: str | None = None   # inline content for tests/fixtures (stored as a blob first)


class EvidenceBundle(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)
    unavailable: list[dict] = Field(default_factory=list)   # [{claim_id, source, reason, code}]


class LockedEvidence(BaseModel):
    accepted: list[Evidence] = Field(default_factory=list)
    by_claim: dict[str, list[str]] = Field(default_factory=dict)
    dropped: list[dict] = Field(default_factory=list)
    unavailable: list[dict] = Field(default_factory=list)


class QuoteLockVerifier(BaseAgent[EvidenceBundle, LockedEvidence]):
    name, input_model, output_model = "a06_quote_lock", EvidenceBundle, LockedEvidence

    def run(self, inp: EvidenceBundle, ctx) -> LockedEvidence:
        out = LockedEvidence(unavailable=inp.unavailable)
        for c in inp.candidates:
            sha = ctx.stores.put_blob(c.raw) if c.raw is not None else c.blob_sha
            blob = ctx.stores.blob(sha)
            if blob is None:
                out.dropped.append({"claim_id": c.claim_id, "source": c.source, "reason": "blob not stored"})
                continue
            if c.field_path:
                ok, off, pf = lock_field(c.field_path, c.value, blob), None, c.field_path
            elif c.passage:
                off = lock(c.passage, blob)
                ok, pf = off is not None, c.passage
            else:
                ok, off, pf = False, None, ""
            if not ok:
                ctx.log.info("a06.dropped", claim_id=c.claim_id, source=c.source, reason="not verbatim")
                out.dropped.append({"claim_id": c.claim_id, "source": c.source, "reason": "passage/field not found verbatim",
                                    "passage_or_field": (pf or "")[:200]})
                continue
            ev = ctx.evidence(source=c.source, url_or_endpoint=c.url_or_endpoint, passage_or_field=pf, value=c.value,
                              record_date=c.record_date, content_sha256=sha, tier=c.tier, media_tier=c.media_tier,
                              relation=c.relation, kind=c.kind, claim_id=c.claim_id, offset=off,
                              attributed_to_company_quote=c.attributed_to_company_quote)
            out.accepted.append(ev)
            out.by_claim.setdefault(c.claim_id, []).append(ev.evidence_id)
        return out


AGENT = QuoteLockVerifier()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
