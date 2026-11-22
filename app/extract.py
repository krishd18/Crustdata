"""Turn a teaser / deck / web page into typed, checkable claims.

Readers, in order:
  1. Claude (structured output, fixed schema) when ANTHROPIC_API_KEY is set;
  2. for decks, the Bedrock model chain used for news (Mantle Qwen first), when
     its key is set. Real decks are fragments ("Team of 30+", "Repeat Orders: 90%",
     a number on one line and its label on the next) that rules can't read;
  3. a rule-based extractor.
Every model claim must quote the source verbatim and its number must appear in that
quote; both are checked in code and anything that fails is dropped.
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


def deck_model_available() -> bool:
    """The Bedrock/NVIDIA chain can read decks (SECONDLOOK_DECK_MODEL=off turns it off)."""
    from . import news_ai
    return os.getenv("SECONDLOOK_DECK_MODEL", "on").lower() != "off" and news_ai.available()


def extract(text: str, *, company: str, kind: str = "deck", usage: dict | None = None,
            stop=None, info: dict | None = None) -> list[Claim]:
    """info (optional) is filled with how the text was read: reader, counts, error."""
    from .cancel import call
    from .htmltext import to_text

    text = to_text(text or "").strip()
    info = info if info is not None else {}
    if not text:
        return []
    raw = None
    info["reader"] = "rules"
    if llm_available():
        try:
            raw = call(stop, _extract_llm, text, company=company, kind=kind, usage=usage)
            info["reader"] = "claude"
        except Exception as e:  # never let the LLM take the pipeline down
            log.warning("LLM extraction failed, falling back to rules: %s", e)
            info["error"] = str(e)[:200]
    if raw is None and kind == "deck" and deck_model_available():
        try:
            raw, meta = call(stop, _extract_bedrock, text, company=company, usage=usage)
            info.update(meta)
            # the rules are a floor: a claim type the model missed but the rules found is kept
            have = {d.get("type") for d in raw}
            extra = [d for d in _extract_rules(text, kind=kind) if d["type"] not in have]
            if extra:
                info["added_by_rules"] = len(extra)
                raw = raw + extra
        except Exception as e:
            log.warning("deck model failed, falling back to rules: %s", e)
            info["error"] = f"{type(e).__name__}: {str(e)[:200]}"
    if raw is None:
        raw = _extract_rules(text, kind=kind)
        info["reader"] = "rules"
    claims = []
    for i, d in enumerate(raw):
        d = {**d, "id": f"{kind[:1]}{i + 1}", "source": kind}
        if d.get("type") not in CLAIM_TYPES:
            continue
        if d["type"] == "premise" and kind != "deck":  # only the analyst's own questions carry premises
            continue
        if d["type"] in ("customers", "investors") and not (d.get("entity") or "").strip():
            continue  # nothing to look up without a name
        if d["type"] == "people" and not ((d.get("entity") or "").strip() or (d.get("person") or "").strip()):
            continue  # needs a former employer or a named leader
        claims.append(Claim.from_dict(d))
    info["claims"] = len(claims)
    return claims


DECK_PROMPT = """List every checkable fact that {company} states about ITSELF in this pitch deck.
An analyst will check each one against public records.

The text was extracted from slides: lines are fragments, a figure can sit on one line and its label
on the next, bullets have no full stops. Read it as slides.

Include (when present):
- each founder or leader named, with their title            -> type "people", "person" = the name
- a leader's former employer ("ex-Acme", "10 years at Acme") -> type "people", "entity" = employer
- team size ("Team of 45+")                                  -> "workforce", metric "employees"
- HQ, offices, cities, warehouses, sites (one claim per place) -> "identity" (HQ / founding year) or "footprint"
- named customers or partners (one claim per name)           -> "customers", "entity" = the name
- named investors                                            -> "investors", "entity" = the name
- the company's own growth ("QoQ growth: 35%", "2x YoY")     -> "growth"
- the company's own operating results: customers or sign-ups, orders, repeat rate, GMV, savings or
  accuracy its product delivers                              -> "efficacy"
- "live since", "operating since"                            -> "dates"
- targets, plans, the fundraising ask                        -> "forward_looking"
- a question the analyst wrote that assumes an event ("Why did they exit Pune?") -> "premise"

Leave out: market sizes (TAM/SAM), industry statistics and studies about the market, slide titles,
taglines, and contact details.

Fields for each claim:
- "quote": copied EXACTLY from the text: one line, or adjacent lines joined with one space (max 200 chars)
- "type", "metric" (employees | warehouses | sites | cities | clients | yoy_growth_pct | revenue |
  founded_year | area_sqft | efficacy_pct | other | null)
- "number": plain number written in the quote ("45+" -> 45, "35%" -> 35, "$2 Million" -> 2000000), else null
- "place", "entity", "person", "year": as described above, else null

Example of one item:
{{"quote": "Team of 45+", "type": "workforce", "metric": "employees", "number": 45, "place": null,
  "entity": null, "person": null, "year": null}}

Reply with ONLY JSON: {{"claims": [ ...items... ]}}

Deck text:
<<<
{text}
>>>"""


SHORT_PROMPT = """Below is text from the pitch deck of {company}. List the facts it states about the company itself:
founders and their titles, team size, HQ and offices, named customers and investors, the company's own
metrics and growth, and the fundraising ask. Not market sizes or industry statistics.
Reply as JSON: {{"claims": [{{"quote": "<copied exactly from the text>", "type": "people|workforce|identity|footprint|customers|investors|growth|efficacy|dates|forward_looking", "number": <number in the quote or null>, "person": <name or null>, "entity": <company named or null>, "place": <city or null>}}]}}

{text}"""

COUNTRIES = {"us", "usa", "u.s.", "united states", "india", "uk", "uae", "singapore"}


def _extract_bedrock(text: str, *, company: str, usage: dict | None = None, llm=None) -> tuple[list[dict], dict]:
    """Read a deck with the Bedrock/NVIDIA chain; keep only claims whose quote and number check out.

    The detailed prompt goes first. Qwen sometimes answers a sparse deck with an empty list,
    so an empty answer gets one retry with a short prompt (which reads such decks well).
    Contact details are removed before anything is sent to the model.
    """
    import time

    from . import news_ai
    from .public import scrub

    t0 = time.time()
    llm = llm or news_ai.call
    text = scrub(text)
    items, used, prompt_used = [], None, "detailed"
    for name, prompt in (("detailed", DECK_PROMPT), ("short", SHORT_PROMPT)):
        content, u, used = llm(prompt.format(company=company, text=text[:40000]), max_tokens=8000, temperature=0)
        if usage is not None:
            usage["input_tokens"] = usage.get("input_tokens", 0) + int((u or {}).get("prompt_tokens") or 0)
            usage["output_tokens"] = usage.get("output_tokens", 0) + int((u or {}).get("completion_tokens") or 0)
        items, prompt_used = news_ai._parse_json(content).get("claims") or [], name
        if items or len(text) < 200:
            break
    out, seen = [], set()
    dropped = {"unquoted": 0, "number_not_in_quote": 0, "no_number": 0, "contact_or_empty": 0}
    for it in items:
        if not isinstance(it, dict):
            continue
        for d in _clean_item(it, text, company, news_ai, dropped):
            key = (d["type"], d["metric"], d["number"], (d["entity"] or "").lower(), (d["place"] or "").lower(),
                   (d["person"] or "").lower())
            if d["number"] is None and not (d["person"] or d["entity"] or d["place"]):
                key += (d["text"].lower(),)
            if key in seen:  # the same fact on two slides counts once
                continue
            seen.add(key)
            out.append(d)
    return out, {"reader": used, "prompt": prompt_used, "seconds": round(time.time() - t0, 1),
                 "model_claims": len(items), "dropped": {k: v for k, v in dropped.items() if v}}


def _same_company(name: str | None, company: str) -> bool:
    n = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    c = re.sub(r"[^a-z0-9]", "", (company or "").lower())
    return bool(n) and (n == c or n in c or c in n)


def _clean_item(it: dict, text: str, company: str, news_ai, dropped: dict) -> list[dict]:
    q = (it.get("quote") or it.get("text") or "").strip()
    if not q or "[email]" in q or "[phone]" in q:
        dropped["contact_or_empty"] += 1
        return []
    if not news_ai.quoted(q, text):
        dropped["unquoted"] += 1
        return []
    num = it.get("number")
    try:
        num = float(num) if num is not None else None
    except (TypeError, ValueError):
        num = None
    if num is not None and not (news_ai._num_in(num, q) or _num_words_in(num, q)):
        dropped["number_not_in_quote"] += 1
        return []
    type_ = it.get("type")
    metric = it.get("metric") if it.get("metric") in METRICS else None
    entity = it.get("entity") or None
    if entity and _same_company(entity, company):
        entity = None  # the company itself is not a customer, investor or former employer
    year = it.get("year")
    year = int(year) if isinstance(year, (int, float)) and 1900 < year < 2100 else None
    if type_ == "customers" and not entity and num is not None:
        type_, metric = "efficacy", "clients"  # "Customers: 800+" is a count, not a named client
    if type_ == "growth" and metric == "yoy_growth_pct" and not re.search(r"y-?o-?y|year|annual|annum", q, re.I):
        metric = "other"  # QoQ / MoM growth is not a YoY figure
    if type_ == "growth" and not re.search(r"grow|growth|y-?o-?y|q-?o-?q|m-?o-?m|\b\d+(\.\d+)?x\b", q, re.I):
        type_ = "efficacy"  # "Repeat Orders: 90%" is an operating figure, not growth
    if type_ in ("workforce", "growth", "efficacy") and num is None:
        dropped["no_number"] += 1
        return []
    if type_ == "identity" and not (it.get("place") or year or metric == "founded_year"):
        dropped["contact_or_empty"] += 1
        return []
    base = {"text": q, "type": type_, "metric": metric, "number": num, "place": None, "entity": entity,
            "person": it.get("person") or None, "year": year, "event": it.get("event") or None}
    # several places in one field ("San Francisco, Mumbai, Indore & Bangalore") -> one claim each
    raw_place = (it.get("place") or "").strip()
    parts = [x.strip(" .") for x in re.split(r",|&|\band\b|/", raw_place) if x.strip(" .")]
    places = [x for x in parts if x.lower() not in COUNTRIES] or parts[:1]
    if not places:
        return [base]
    out = []
    hq = re.search(r"\b(HQ|head ?quarter\w*)\b", q, re.I)
    for i, pl in enumerate(places):
        d = {**base, "place": _place(pl)}
        if type_ in ("footprint", "identity") and hq and i == 0 and re.search(
                r"(HQ|head ?quarter\w*)\W+(?:in\s+|at\s+)?" + re.escape(pl), q, re.I):
            d.update(type="identity", metric=None, number=None)  # the HQ, checked against the HQ on record
        elif type_ in ("footprint", "identity") and num is None and d["type"] != "identity":
            d["metric"] = "sites"  # "office in Mumbai": a place to find on record, not a count
        elif type_ == "identity" and i > 0:
            d.update(type="footprint", metric="sites")  # other places named next to the HQ are offices
        if d["type"] == "identity" and d["metric"] == "founded_year" and d["place"]:
            # "Chennai-registered ..., est. 2019" is two checks: the year and the place
            out.append({**d, "place": None, "year": year or (int(num) if num else None)})
            d = {**d, "metric": None, "number": None, "year": None}
        out.append(d)
    return out


_SCALE = {"thousand": 1e3, "k": 1e3, "lakh": 1e5, "lac": 1e5, "million": 1e6, "mn": 1e6, "m": 1e6,
          "crore": 1e7, "cr": 1e7, "billion": 1e9, "bn": 1e9, "b": 1e9}


def _num_words_in(num: float, quote: str) -> bool:
    """'$1 MILLION' -> 1000000, '5 Lakh' -> 500000, '$41.3B' -> 41.3e9: the number is in the quote."""
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(thousand|k|lakh|lac|million|mn|m|crore|cr|billion|bn|b)\b", quote, re.I):
        v = float(m.group(1).replace(",", "")) * _SCALE[m.group(2).lower()]
        if abs(v - num) < max(1e-6, 1e-6 * abs(num)):
            return True
    return False


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
            if not re.search(r"\b(why|did|clos\w*|shut\w*|exit\w*|wound|lost|stopp\w*|left|leav\w*)\b", low):
                continue  # a rhetorical slide heading ("How reliable is the ear?"), not an analyst's question
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
        if m := (re.search(NUM + r"\+?\s*(employees|people|staff|team members|ftes?|member team|strong team)", low)
                 or re.search(r"\bteam (?:of|size:?)\s*" + NUM, low)):  # deck style: "Team of 30+"
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
        if m := re.search(r"([A-Z][a-z]+)[- ]registered|(?i:headquartered) in ([A-Z][a-z]+(?: [A-Z][a-z]+)?)"
                          r"|based (?:out of|in) ([A-Z][a-z]+(?: [A-Z][a-z]+)?)|HQ(?: in|:)? ?([A-Z][a-z]+(?: [A-Z][a-z]+)?)", s):
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
