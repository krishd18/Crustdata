from __future__ import annotations

from dataclasses import asdict, dataclass, field

CLAIM_TYPES = [
    "identity", "workforce", "growth", "footprint", "investors", "people",
    "customers", "dates", "efficacy", "forward_looking", "premise",
]

# Metrics let us line up the same fact across different sources
# (deck vs website vs founder profile) for the inconsistency check.
METRICS = [
    "employees", "warehouses", "sites", "cities", "clients", "yoy_growth_pct",
    "revenue", "founded_year", "area_sqft", "efficacy_pct", "other",
]


@dataclass
class Claim:
    id: str
    text: str
    type: str
    metric: str | None = None
    number: float | None = None
    place: str | None = None
    entity: str | None = None
    person: str | None = None
    year: int | None = None
    event: str | None = None
    source: str = "deck"

    @classmethod
    def from_dict(cls, d: dict) -> "Claim":
        keys = cls.__dataclass_fields__.keys()
        return cls(**{k: d.get(k) for k in keys if k in d})


@dataclass
class Evidence:
    source: str                 # "Crustdata /company/enrich" or a URL's host
    field: str | None           # API field path, e.g. headcount.total
    value: str                  # exact value or passage
    retrieved_at: str
    url: str | None = None


@dataclass
class Finding:
    claim: Claim
    verdict: str
    reason: str                 # one plain-language line
    evidence: list[Evidence] = field(default_factory=list)
    sources_checked: list[str] = field(default_factory=list)
    request: str | None = None  # the document to ask for, when not settled
    final: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# Verdicts that leave something to ask the counterparty for.
UNSETTLED = {
    "consistent", "cannot verify", "partial", "self-reported", "earliest evidence",
    "unsupported premise", "projection",
}
