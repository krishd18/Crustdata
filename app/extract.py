"""Turn a teaser / deck / web page into typed, checkable claims.

Claude does the reading (structured output, fixed schema). If no Anthropic
credentials are available, a regex extractor keeps the demo working.
Verdicts are never made here: this module only extracts.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .models import CLAIM_TYPES, METRICS, Claim

log = logging.getLogger("secondlook.extract")

MODEL = os.getenv("SECONDLOOK_MODEL", "claude-opus-5-5")

_nullable = lambda t: {"anyOf": [{"type": t}, {"type": "null"}]}  # noqa: E731

SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "verbatim span from the source"},
                    "type": {"type": "string", "enum": CLAIM_TYPES},
                    "metric": {"anyOf": [{"type": "string", "enum": METRICS}, {"type": "null"}]},
                    "number": _nullable("number"),
                    "place": _nullable("string"),
                    "entity": _nullable("string"),
                    "person": _nullable("string"),
                    "year": _nullable("integer"),
                    "event": _nullable("string"),
                },
                "required": ["text", "type", "metric", "number", "place", "entity", "person", "year", "event"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["claims"],
    "additionalProperties": False,
}

PROMPT = """You extract checkable factual claims a company makes about itself, for a diligence analyst.

Source kind: {kind}
Company: {company}

Rules:
- One claim per distinct fact. Copy `text` verbatim from the source (short span).
- type:
  identity = where registered / HQ / founding year;  workforce = headcount;
  growth = growth rates (% YoY etc.);  footprint = number/location of sites, warehouses, offices;
  investors = who backed them;  people = leadership background ("ex-Delhivery");
  customers = named clients;  dates = "live since", "operating since";
  efficacy = performance/outcome claims ("cuts damage 40%");
  forward_looking = projections, targets, plans;
  premise = a QUESTION from the analyst that assumes a fact (e.g. "Why did they close Hosur?").
- metric: the normalised quantity, when there is one (employees, warehouses, sites, cities, clients,
  yoy_growth_pct, revenue, founded_year, area_sqft, efficacy_pct, other). null if none.
- number: the numeric value (40% -> 40, 250+ -> 250, "est. 2014" -> 2014). null if none.
- place: city/state if the claim names one (expand abbreviations: TN -> Tamil Nadu, KA -> Karnataka).
- entity: investor, customer, or former employer named in the claim.
- person: the person named, if the claim is about a specific person.
- year: a year the claim names. event: for premise questions, the assumed event (e.g. "closed").
- Skip marketing fluff with nothing checkable. Do not invent claims.

Source text:
<<<
{text}
>>>"""


def llm_available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def extract(text: str, *, company: str, kind: str = "deck", usage: dict | None = None) -> list[Claim]:
    from .htmltext import to_text

    text = to_text(text or "").strip()
    if not text:
        return []
    raw = None
    if llm_available():
        try:
            raw = _extract_llm(text, company=company, kind=kind, usage=usage)
        except Exception as e:  # never let the LLM take the pipeline down
            log.warning("LLM extraction failed, falling back to rules: %s", e)
    if raw is None:
        raw = _extract_rules(text, kind=kind)
    claims = []
    for i, d in enumerate(raw):
        d = {**d, "id": f"{kind[:1]}{i + 1}", "source": kind}
        if d.get("type") not in CLAIM_TYPES:
            continue
        if d["type"] == "premise" and kind != "deck":  # only the analyst's own questions carry premises
            continue
        claims.append(Claim.from_dict(d))
    return claims


def _extract_llm(text: str, *, company: str, kind: str, usage: dict | None) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": PROMPT.format(kind=kind, company=company, text=text[:60000])}],
    )
    if usage is not None:
        usage["input_tokens"] = usage.get("input_tokens", 0) + resp.usage.input_tokens
        usage["output_tokens"] = usage.get("output_tokens", 0) + resp.usage.output_tokens
    if resp.stop_reason == "refusal":
        raise RuntimeError("model declined")
    body = next(b.text for b in resp.content if b.type == "text")
    return json.loads(body)["claims"]


# --------------------------------------------------------------------------
# Rule-based fallback. Deliberately conservative.
# --------------------------------------------------------------------------
STATE_ABBR = {
    "TN": "Tamil Nadu", "KA": "Karnataka", "MH": "Maharashtra", "AP": "Andhra Pradesh",
    "TS": "Telangana", "KL": "Kerala", "GJ": "Gujarat", "DL": "Delhi", "UP": "Uttar Pradesh",
    "WB": "West Bengal", "HR": "Haryana", "RJ": "Rajasthan",
}

NUM = r"(\d[\d,]*(?:\.\d+)?)"

GENERIC_SEGMENTS = {
    "manufacturers", "distributors", "importers", "exporters", "brands", "retailers", "sellers", "d2c", "smes",
    "enterprises", "startups", "businesses", "customers", "clients", "e-commerce", "ecommerce", "fmcg", "b2b", "b2c",
}


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def _place(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip(" .,")
    return STATE_ABBR.get(s.upper(), s)


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\b(est|Rs|No|Pvt|Ltd|Inc|approx|Co)\.", r"\1", text)
    parts = re.split(r"(?<=[.!?])\s+|\n+|•|·|•", text)
    return [p.strip(" -*\t") for p in parts if p and p.strip(" -*\t")]


def _extract_rules(text: str, kind: str = "deck") -> list[dict]:
    out: list[dict] = []

    def add(span, type_, **kw):
        base = dict(text=span, type=type_, metric=None, number=None, place=None, entity=None,
                    person=None, year=None, event=None)
        base.update(kw)
        out.append(base)

    for s in _sentences(text):
        low = s.lower()
        if len(s) > 400:  # not a sentence (minified text, data blobs)
            continue
        if kind != "deck" and len(s.split()) < 5:  # UI labels and mock-up numbers ("5 cities"), not statements
            continue
        if s.endswith("?"):
            if kind != "deck":
                continue
            m = re.search(r"(clos\w*|shut\w*|exit\w*|wound down|lost)\s+(?:down\s+)?(?:their|the|its)?\s*([A-Z][\w]+)?", s)
            place = m.group(2) if m and m.group(2) else None
            if not place:
                pm = re.findall(r"\b([A-Z][a-z]{2,})\b", s)
                place = next((p for p in pm if p not in {"Why", "How", "When", "What", "Did", "Do"}), None)
            add(s, "premise", place=place, event=(m.group(1) if m else None))
            continue
        if re.search(r"\b(by|in|target\w*|projected?|expect\w*|plan\w*)\b.*(?<!\d)20[2-9]\d(?!\d)", low) and re.search(r"₹|rs\.?|cr\b|crore|revenue|target|arr|gmv", low):
            y = re.search(r"(?<!\d)(20[2-9]\d)(?!\d)", s)
            add(s, "forward_looking", year=int(y.group(1)) if y else None)
            continue
        if m := re.search(NUM + r"\+?\s*(employees|people|staff|team members|ftes?|member team|strong team)", low):
            add(s, "workforce", metric="employees", number=_n(m.group(1)))
        if m := re.search(r"([+-]?\d+(?:\.\d+)?)\s*%\s*(?:yoy|year[- ]on[- ]year|y-o-y|annual growth|growth)", low):
            add(s, "growth", metric="yoy_growth_pct", number=float(m.group(1)))
        if m := re.search(NUM + r"\s+(?i:(warehouses?|facilities|fulfil?ment cent(?:er|re)s?|hubs?|sites|locations|offices))"
                          r"(?:\s+(?i:in|across)\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*))?\b", s):
            metric = "warehouses" if m.group(2).lower().startswith(("warehouse", "fulfil", "facilit", "hub")) else "sites"
            add(s, "footprint", metric=metric, number=_n(m.group(1)), place=_place(m.group(3)))
        if m := re.search(r"(?:cities)\b", low):
            if c := re.search(r"(?<!tier )(?<!tier-)" + NUM + r"\+?\s+cities", low):
                add(s, "footprint", metric="cities", number=_n(c.group(1)))
        about_person = re.search(r"\b(he|she|his|her|him)\b", low)  # a bio line, not a company fact
        if m := re.search(r"\b(?:est\.?|established|founded|incorporated)\s*(?:in\s*)?((?:19|20)\d\d)", low):
            if not re.search(r"live|operat|launch", low) and not about_person:
                add(s, "identity", metric="founded_year", number=float(m.group(1)), year=int(m.group(1)))
        if m := re.search(r"([A-Z][a-z]+)[- ]registered|headquartered in ([A-Z][a-z]+)|based (?:out of|in) ([A-Z][a-z]+)|HQ(?: in|:)? ([A-Z][a-z]+)", s):
            add(s, "identity", place=next(g for g in m.groups() if g))
        if m := re.search(r"(?i:backed by) ([A-Z][\w&.\- ]+?)(?:\s+and\s+([A-Z][\w&.\- ]+?))?(?:[,.;]|$)", s):
            for g in m.groups():
                if g:
                    add(s, "investors", entity=g.strip(" .,;"))
        if m := re.search(r"\b(?i:ex)[- ]([A-Z][\w]+)|(?i:former) ([A-Z][\w]+) (?i:executives?|leaders?|leadership|team)|(?i:alumni of) ([A-Z][\w]+)", s):
            add(s, "people", entity=next(g for g in m.groups() if g))
        if m := re.search(r"(?i:we serve|serving|serves|clients include|customers include|trusted by|work(?:ing)? with|partners? to)\s+([A-Z][\w&.\-]+(?:(?:,\s*|\s+and\s+)[A-Z][\w&.\-]+)*)", s):
            for name in re.split(r",\s*|\s+and\s+", m.group(1)):
                name = name.strip(" .,;")
                if name.lower() not in GENERIC_SEGMENTS:  # "Who We Serve: Manufacturers" is a segment, not a client
                    add(s, "customers", entity=name)
        if (m := re.search(r"(?:live|operating|operational|launched|in (?:operation|production)|running) since ((?:19|20)\d\d)", low)) and not about_person:
            add(s, "dates", year=int(m.group(1)), number=float(m.group(1)))
        if m := re.search(r"(cuts?|reduces?|lowers?|improves?|increases?|boosts?|saves?)\s+([\w\s-]{2,40}?)\s+(?:by\s+)?(?:up to\s+)?(\d+(?:\.\d+)?)\s*%", low):
            add(s, "efficacy", metric="efficacy_pct", number=float(m.group(3)), entity=m.group(2).strip())
    return out
