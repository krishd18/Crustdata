"""Every tunable in one place.

At hour 3 the organisers change one requirement for all tracks -- typically a
new output field or a lower cost limit. When that happens, this file and
``models.py`` are the only places that should need editing. Nothing else in the
codebase may hardcode a limit, a threshold or a schema assumption.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

# --------------------------------------------------------------------------
# Output contract version.
# Bump when the shape of an Answer changes. Emitted on every result so a
# grader can tell which contract produced a given case file.
# --------------------------------------------------------------------------
SCHEMA_VERSION = "1.0.0"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class EvidenceBar:
    """When are we allowed to answer at all?

    A wrong answer costs more than ``cannot_verify``, so this bar is the single
    most consequential number in the system. Raise it and easy cases start
    failing; lower it and the hard cases start producing confident nonsense.
    """

    # A registry record (MCA / GST) alone is enough to answer.
    registry_source_is_sufficient: bool = True

    # Otherwise, how many independent web sources must state the fact.
    # "Independent" means distinct registrable domains, not distinct URLs.
    min_independent_web_sources: int = 2

    # An indexed Crustdata record may be up to 30 days stale. Beyond this many
    # days it does not count toward the bar on its own for a recency question.
    max_indexed_record_age_days: int = 30

    # Every cited passage must pass the entailment check: does this span, read
    # alone, state the claim? Below this score the evidence is discarded, not
    # merely down-weighted.
    min_entailment_score: float = 0.75

    # A question about "since September" must be answered from records dated
    # inside the window. Evidence older than the window start cannot support a
    # claim about change within it.
    enforce_question_time_window: bool = True


@dataclass(frozen=True)
class Limits:
    """Per-run time and cost ceilings. The brief requires both."""

    max_wall_seconds: int = 180
    max_credits_per_case: int = 120
    max_credits_per_question: int = 40

    # Crustdata web search is documented at 10 requests per minute by default.
    web_search_rpm: int = 10

    # Web fetch accepts at most 10 URLs per request.
    max_urls_per_fetch: int = 10

    # How many search result pages to pull. Page N costs N credits, so this
    # climbs fast.
    max_search_pages: int = 1

    max_fetches_per_question: int = 6
    max_retries_per_call: int = 2


@dataclass(frozen=True)
class Pricing:
    """What we charge and what we pay, so the per-case rupee figure is measured.

    ``inr_per_credit`` must be set from the real plan on the day. It is left at
    zero deliberately: a fabricated number is worse than an absent one, and the
    finance judge asks for a measured cost.
    """

    inr_per_credit: float = 0.0
    inr_per_1k_model_input_tokens: float = 0.0
    inr_per_1k_model_output_tokens: float = 0.0

    # What the client pays for an answered question. Nothing is billed for
    # cannot_verify or false_premise.
    price_inr_per_answered_question: float = 0.0


@dataclass(frozen=True)
class Approval:
    """Irreversible actions wait for a person.

    On this track the harmful irreversible action is not a payment: it is
    publishing a claim about a real, named company. A wrong "rival X has exited
    this city" reaches people who never see the correction.
    """

    require_approval_before_send: bool = True

    # Even a cannot_verify memo is an outbound statement about a named company.
    require_approval_for_cannot_verify: bool = True

    approval_timeout_seconds: int = 600


@dataclass(frozen=True)
class Config:
    evidence_bar: EvidenceBar = field(default_factory=EvidenceBar)
    limits: Limits = field(default_factory=Limits)
    pricing: Pricing = field(default_factory=Pricing)
    approval: Approval = field(default_factory=Approval)

    schema_version: str = SCHEMA_VERSION

    # Crustdata
    api_base: str = "https://api.crustdata.com"
    api_version: str = "2025-11-01"

    # Where case journals are written. Must survive process death.
    journal_dir: str = "./cases"

    def with_overrides(self, **kwargs) -> "Config":
        return replace(self, **kwargs)


def load() -> Config:
    """Build the config, letting the environment override the numbers that the
    hour-3 requirement change is most likely to touch."""
    return Config(
        evidence_bar=EvidenceBar(
            min_independent_web_sources=_env_int("DESK_MIN_WEB_SOURCES", 2),
            max_indexed_record_age_days=_env_int("DESK_MAX_RECORD_AGE_DAYS", 30),
            min_entailment_score=_env_float("DESK_MIN_ENTAILMENT", 0.75),
        ),
        limits=Limits(
            max_wall_seconds=_env_int("DESK_MAX_WALL_SECONDS", 180),
            max_credits_per_case=_env_int("DESK_MAX_CREDITS_PER_CASE", 120),
            max_credits_per_question=_env_int("DESK_MAX_CREDITS_PER_QUESTION", 40),
            max_search_pages=_env_int("DESK_MAX_SEARCH_PAGES", 1),
        ),
        pricing=Pricing(
            inr_per_credit=_env_float("DESK_INR_PER_CREDIT", 0.0),
            price_inr_per_answered_question=_env_float("DESK_PRICE_INR", 0.0),
        ),
        journal_dir=os.environ.get("DESK_JOURNAL_DIR", "./cases"),
    )
