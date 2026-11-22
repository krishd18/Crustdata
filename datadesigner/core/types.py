"""Common types (docs/AGENTS.md §1)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Tier = Literal["T1", "T1-M", "T2", "T3", "T4"]
Cls = Literal["VERIFIED", "PARTIALLY_VERIFIED", "UNVERIFIED", "OUTDATED", "NOT_VERIFIABLE", "FALSE", "NOT_CHECKED"]
BADGE = {"VERIFIED": "✅", "PARTIALLY_VERIFIED": "🟢", "UNVERIFIED": "🟡", "OUTDATED": "⏳", "NOT_VERIFIABLE": "⚪",
         "FALSE": "❌", "NOT_CHECKED": "⚫"}


class Evidence(BaseModel):
    evidence_id: str
    source: str
    url_or_endpoint: str
    passage_or_field: str
    value: Any = None
    record_date: str | None = None
    retrieved_at: str
    content_sha256: str
    tier: Tier
    media_tier: str | None = None
    relation: Literal["supports", "contradicts", "context"] = "supports"
    kind: Literal["field", "passage", "lower_bound", "band", "earliest", "profile", "self", "superseded"] = "field"
    attributed_to_company_quote: bool = False
    offset: int | None = None


class Span(BaseModel):
    doc_id: str
    page: int
    start: int
    end: int


class Claim(BaseModel):
    claim_id: str
    kind: Literal["business", "bio", "tech", "premise", "criterion"] = "business"
    type: str = "other"
    subject: str = "company"
    text: str
    value: Any = None
    unit: str | None = None
    as_of: str | None = None
    critical: bool = False
    span: Span | None = None
    slide: int | None = None
    operational: bool = False


class Verdict(BaseModel):
    claim_id: str
    cls: Cls
    code: str
    evidence_ids: list[str] = Field(default_factory=list)
    missing: str | None = None
    credit_floor: float | None = None
    credit_ceiling: float | None = None
    rule_id: str
    note: str = ""

    @property
    def badge(self) -> str:
        return BADGE[self.cls]


class Inference(BaseModel):
    company: str
    statement: str
    theme: str
    theme_label: str
    strength: Literal["STRONG", "MODERATE", "WEAK"]
    n_supporting: int
    total: int
    share: float
    corroboration_ids: list[str] = Field(default_factory=list)
    quotes: list[str] = Field(default_factory=list)
    label: str = "INFERENCE — not a verified fact"


class Metric(BaseModel):
    id: str
    value: float | None
    unit: str = ""
    period: str = ""
    points: float | None = None
    band: str = ""
    quality_tag: str = "derived"
    inputs: list[dict] = Field(default_factory=list)
    formula: str = ""


class Cost(BaseModel):
    credits: float = 0
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    inr: float = 0
