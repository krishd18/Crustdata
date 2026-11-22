"""Fixed claim-type -> document table.

Requests are filled from this table, never invented. Each entry says what to
ask for and why that document settles the claim. Indian context first, since
that is the buyer; generic wording works elsewhere.
"""
from __future__ import annotations

from .models import Claim

TABLE: dict[str, tuple[str, str]] = {
    "identity": (
        "Certificate of Incorporation and MCA master data (CIN, registered office address)",
        "Registry documents fix the legal entity, its registered city and incorporation date.",
    ),
    "workforce": (
        "EPFO ECR contribution statements for the last 3 months (member count per month)",
        "Public profiles only give a lower bound; PF returns show who is actually on payroll.",
    ),
    "growth": (
        "Audited financials for the last 2 financial years, or GSTR-3B summaries for the period claimed",
        "Headcount growth is a proxy; filed turnover settles the growth rate.",
    ),
    "footprint": (
        "Lease or leave-and-licence deeds for each site{place_note}, and the GST registration certificate listing additional places of business",
        "Every operating site should appear as a GST additional place of business and have a lease.",
    ),
    "investors": (
        "Shareholding pattern / cap table and the MCA allotment filing (Form PAS-3) showing {entity}",
        "An investor on the cap table appears in allotment filings; logos on a deck do not.",
    ),
    "people": (
        "CVs for the leaders described as {entity_or_claim}, with consent for a reference check with that former employer",
        "A reference at the former employer confirms role, dates and seniority.",
    ),
    "customers": (
        "A recent invoice to {entity} (amounts may be redacted) or a named reference contact there",
        "An invoice or a customer reference is the only direct proof of an active relationship.",
    ),
    "dates": (
        "The earliest customer contract or invoice from {year}, or dated product release notes",
        "A dated commercial document is the strongest evidence the product was live then.",
    ),
    "efficacy": (
        "The method and data behind the {number}% figure: sample, period, baseline, and a customer who can confirm it",
        "Outcome claims need the before/after data and an independent confirmation.",
    ),
    "forward_looking": (
        "The model behind the projection: order book, signed LOIs and pipeline by stage",
        "Projections are not facts; the inputs to the model are what can be tested.",
    ),
    "premise": (
        "Ask directly in the meeting; records do not support the premise as stated",
        "A question built on a wrong premise wastes the meeting and signals poor preparation.",
    ),
}


def request_for(claim: Claim) -> tuple[str, str]:
    doc, why = TABLE[claim.type]
    num = claim.number
    num_s = (str(int(num)) if num is not None and float(num).is_integer() else str(num)) if num is not None else "claimed"
    doc = doc.format(
        entity=claim.entity or "the named investor",
        entity_or_claim=f'"{claim.text}"' if not claim.entity else f"ex-{claim.entity}",
        year=claim.year or "the claimed year",
        number=num_s,
        place_note=f" in {claim.place}" if claim.place else "",
    )
    return doc, why
