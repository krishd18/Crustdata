"""Turn a plain-English FIND thesis into Crustdata /company/search parameters.

  "Acquirable logistic companies with $5 Million+ revenue in MH"
     -> query "logistics companies"
        + HQ Maharashtra, revenue.estimated.lower_bound_usd >= 5,000,000,
          not acquired, not public / government / nonprofit

The LLM (the news-model provider chain: Bedrock Mantle first) only fills a fixed,
closed-vocabulary schema. Code validates every value, converts money, and builds the
filters itself, so a model mistake can't produce an invalid or surprising query.
Whatever can't be mapped comes back as "not applied" and is shown to the user.
If no model is available or it fails, a rule-based reader is used instead.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time

from . import news_ai
from .find import INDIA, STATES

log = logging.getLogger("secondlook.thesis")

ROUND_TYPES = ["pre_seed", "seed", "angel", "series_a", "series_b", "series_c", "series_d", "series_e",
               "series_unknown", "private_equity", "debt_financing", "grant", "equity_crowdfunding", "undisclosed"]
UNITS = {"none": 1, "thousand": 1e3, "lakh": 1e5, "million": 1e6, "crore": 1e7, "billion": 1e9}
NOT_ACQUIRABLE_TYPES = ["Public Company", "Government Agency", "Nonprofit", "Educational Institution"]

PROMPT = """Convert a corporate-development search request into search parameters.

Request: "{thesis}"

Return ONLY this JSON (no prose, no code fence). Use null / [] / false when the request
doesn't say. Never invent criteria that aren't in the request.
{{
  "what": "what the companies do, as a short phrase for a text search (e.g. 'logistics and warehousing companies'); drop numbers, places and words like acquirable",
  "locations": [{{"name": "place as written or expanded (MH -> Maharashtra, KA -> Karnataka, TN -> Tamil Nadu, NCR -> Delhi)", "kind": "state | city | country"}}],
  "revenue_min": {{"amount": number, "unit": "none|thousand|lakh|million|crore|billion", "currency": "USD|INR"}} or null,
  "revenue_max": same shape or null,
  "headcount_min": integer or null,
  "headcount_max": integer or null,
  "headcount_growth_min_pct": number or null,
  "funding_min": money object or null,
  "funding_max": money object or null,
  "last_round_types": [subset of {rounds}],
  "founded_after": the FIRST founding year allowed, or null ("after 2018" -> 2019, "since 2018" -> 2018),
  "founded_before": the LAST founding year allowed, or null ("before 2015" -> 2014),
  "acquirable": true if the request asks for acquirable / buyable / acquisition targets / for sale,
  "exclude_public": true if it asks for private or unlisted companies,
  "unsupported": ["any part of the request you could not express with the fields above"]
}}"""


def _money_usd(m, inr_per_usd: float) -> float | None:
    if not isinstance(m, dict):
        return None
    try:
        amt = float(m.get("amount"))
    except (TypeError, ValueError):
        return None
    unit = UNITS.get(str(m.get("unit") or "none").lower())
    if unit is None or amt <= 0:
        return None
    usd = amt * unit
    if str(m.get("currency") or "USD").upper() == "INR":
        usd /= inr_per_usd
    return round(usd)


def _int(v, lo, hi):
    try:
        x = int(float(v))
    except (TypeError, ValueError):
        return None
    return x if lo <= x <= hi else None


def _place(name: str) -> str | None:
    p = (name or "").strip(" .,")
    if not p:
        return None
    return STATES.get(p.lower(), p)


def normalise(raw: dict) -> dict:
    """Validate the model's (or the rule reader's) output into a clean parameter set."""
    inr = float(os.getenv("USD_INR") or 84)
    locs, country = [], None
    for loc in raw.get("locations") or []:
        name = _place(loc.get("name") if isinstance(loc, dict) else str(loc))
        kind = (loc.get("kind") if isinstance(loc, dict) else "") or ""
        if not name:
            continue
        if kind == "country" or name.lower() in ("india", "ind"):
            country = "IND" if name.lower() in ("india", "ind") else name
            continue
        locs.append(name)
    if locs and all(x.lower() in {i.lower() for i in INDIA} for x in locs):
        country = country or "IND"
    p = {
        "what": (raw.get("what") or "").strip()[:120],
        "locations": locs, "country": country,
        "revenue_min_usd": _money_usd(raw.get("revenue_min"), inr),
        "revenue_max_usd": _money_usd(raw.get("revenue_max"), inr),
        "headcount_min": _int(raw.get("headcount_min"), 1, 10_000_000),
        "headcount_max": _int(raw.get("headcount_max"), 1, 10_000_000),
        "headcount_growth_min_pct": _int(raw.get("headcount_growth_min_pct"), -100, 10_000),
        "funding_min_usd": _money_usd(raw.get("funding_min"), inr),
        "funding_max_usd": _money_usd(raw.get("funding_max"), inr),
        "last_round_types": [r for r in (raw.get("last_round_types") or []) if r in ROUND_TYPES],
        "founded_after": _int(raw.get("founded_after"), 1800, 2100),
        "founded_before": _int(raw.get("founded_before"), 1800, 2100),
        "acquirable": bool(raw.get("acquirable")),
        "exclude_public": bool(raw.get("exclude_public")) or bool(raw.get("acquirable")),
        "unsupported": [str(u)[:80] for u in (raw.get("unsupported") or [])][:6],
        "inr_per_usd": inr,
    }
    if not p["what"]:
        p["what"] = "companies"
    return p


def _usd(n: float) -> str:
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if n >= div:
            return f"${round(n / div, 1):g}{suf}"
    return f"${n:g}"


def to_filters(p: dict, min_headcount_floor: int | None = None) -> tuple[dict | None, list[dict]]:
    """Parameters -> (Crustdata filter tree, [{label, field, op, value}] for the UI)."""
    conds, applied = [], []

    def add(label, field, op, value):
        conds.append({"field": field, "type": op, "value": value})
        applied.append({"label": label, "field": field, "op": op, "value": value})

    if p["country"]:
        add(f"Country {p['country']}", "locations.country", "=", p["country"])
    if p["locations"]:
        loc = [{"field": "locations.headquarters", "type": "(.)", "value": x} for x in p["locations"]]
        conds.append(loc[0] if len(loc) == 1 else {"op": "or", "conditions": loc})
        applied.append({"label": "HQ in " + " or ".join(p["locations"]), "field": "locations.headquarters",
                        "op": "(.)", "value": p["locations"]})
    if p["revenue_min_usd"]:
        add(f"Revenue ≥ {_usd(p['revenue_min_usd'])} (Crustdata estimate)", "revenue.estimated.lower_bound_usd", "=>", p["revenue_min_usd"])
    if p["revenue_max_usd"]:
        add(f"Revenue ≤ {_usd(p['revenue_max_usd'])} (Crustdata estimate)", "revenue.estimated.upper_bound_usd", "=<", p["revenue_max_usd"])
    hmin = p["headcount_min"] or min_headcount_floor
    if hmin:
        add(f"≥ {hmin} people on record", "headcount.total", "=>", hmin)
    if p["headcount_max"]:
        add(f"≤ {p['headcount_max']} people on record", "headcount.total", "=<", p["headcount_max"])
    if p["headcount_growth_min_pct"] is not None:
        add(f"Headcount growth ≥ {p['headcount_growth_min_pct']}% (12m)", "headcount.growth_percent.12m", "=>", p["headcount_growth_min_pct"])
    if p["funding_min_usd"]:
        add(f"Funding raised ≥ {_usd(p['funding_min_usd'])}", "funding.total_investment_usd", "=>", p["funding_min_usd"])
    if p["funding_max_usd"]:
        add(f"Funding raised ≤ {_usd(p['funding_max_usd'])}", "funding.total_investment_usd", "=<", p["funding_max_usd"])
    if p["last_round_types"]:
        rounds = [{"field": "funding.last_round_type", "type": "=", "value": r} for r in p["last_round_types"]]
        conds.append(rounds[0] if len(rounds) == 1 else {"op": "or", "conditions": rounds})
        applied.append({"label": "Last round: " + ", ".join(p["last_round_types"]), "field": "funding.last_round_type",
                        "op": "in", "value": p["last_round_types"]})
    if p["founded_after"]:
        add(f"Founded ≥ {p['founded_after']}", "basic_info.year_founded", "=>", p["founded_after"])
    if p["founded_before"]:
        add(f"Founded ≤ {p['founded_before']}", "basic_info.year_founded", "=<", p["founded_before"])
    if p["acquirable"]:
        add("Not already acquired", "revenue.acquisition_status", "=", "")
    if p["exclude_public"]:
        excl = NOT_ACQUIRABLE_TYPES if p["acquirable"] else ["Public Company"]
        conds.append({"op": "and", "conditions": [{"field": "basic_info.company_type", "type": "!=", "value": t} for t in excl]})
        applied.append({"label": "Not " + ", ".join(t.lower() for t in excl), "field": "basic_info.company_type",
                        "op": "not in", "value": excl})
    if not conds:
        return None, applied
    return (conds[0] if len(conds) == 1 else {"op": "and", "conditions": conds}), applied


# ---------------------------------------------------------------------------
# Rule-based reader (fallback when no model is available)
# ---------------------------------------------------------------------------
MONEY = re.compile(r"(?P<cur>\$|usd|us\$|₹|rs\.?|inr)?\s*(?P<amt>\d+(?:\.\d+)?)\s*(?P<unit>k|thousand|lakhs?|lacs?|mn|m|million|cr|crores?|bn|b|billion)?\s*(?P<cur2>usd|inr)?", re.I)
UNIT_ALIAS = {"k": "thousand", "lakh": "lakh", "lakhs": "lakh", "lac": "lakh", "lacs": "lakh", "mn": "million", "m": "million",
              "cr": "crore", "crore": "crore", "crores": "crore", "bn": "billion", "b": "billion"}


def _money_near(text: str, word: str):
    m = re.search(rf"((?:more than|over|above|at least|min(?:imum)?|>=?)?\s*[\$₹]?\s*\d[\d.,]*\s*\+?\s*(?:k|thousand|lakhs?|lacs?|mn|m|million|cr|crores?|bn|b|billion)?\s*\+?\s*(?:usd|inr)?\s*\+?)\s*(?:of\s+|in\s+)?{word}", text, re.I)
    if not m:
        m = re.search(rf"{word}\s*(?:of|above|over|>=?|at least)?\s*([\$₹]?\s*\d[\d.,]*\s*(?:k|thousand|lakhs?|lacs?|mn|m|million|cr|crores?|bn|b|billion)?\s*(?:usd|inr)?)", text, re.I)
    if not m:
        return None, None
    mm = MONEY.search(m.group(1).replace(",", ""))
    if not mm:
        return None, None
    unit = (mm.group("unit") or "none").lower()
    unit = UNIT_ALIAS.get(unit, unit)
    cur = (mm.group("cur") or mm.group("cur2") or "").lower()
    currency = "INR" if cur in ("₹", "rs", "rs.", "inr") or unit in ("lakh", "crore") else "USD"
    return {"amount": float(mm.group("amt")), "unit": unit, "currency": currency}, m.group(0)


def rule_parse(thesis: str) -> dict:
    text = " ".join(thesis.split())
    raw = {"locations": [], "unsupported": []}
    raw["revenue_min"], rev_span = _money_near(text, r"(?:revenue|turnover|sales)")
    raw["funding_min"], fund_span = _money_near(text, r"(?:funding|raised)")
    raw["acquirable"] = bool(re.search(r"\b(acquirable|acquisition targets?|buyable|for sale|to acquire)\b", text, re.I))
    raw["exclude_public"] = bool(re.search(r"\b(private|unlisted)\b", text, re.I))
    if m := re.search(r"(\d[\d,]*)\s*\+?\s*(?:employees|people|staff)", text, re.I):
        raw["headcount_min"] = int(m.group(1).replace(",", ""))
    # places after "in/across/based in"; leftover words in that tail are sector words ("in MH logistics")
    what = text
    for span in (rev_span, fund_span):
        if span:
            what = what.replace(span, " ")
    if m := re.search(r"\s(?:in|across|based in|from)\s+(.+)$", what, re.I):
        tail, what = m.group(1), what[: m.start()]
        extra = []
        for tok in re.split(r"\s*(?:/|,|\band\b|&|\bor\b)\s*|\s+", tail):
            t = tok.strip(" .")
            if not t:
                continue
            if t.lower() in STATES or t.lower() in {i.lower() for i in INDIA}:
                raw["locations"].append({"name": STATES.get(t.lower(), t.title() if t.islower() else t), "kind": "state"})
            else:
                extra.append(t)
        what = f"{what} {' '.join(extra)}"
    what = re.sub(r"\b(acquirable|acquisition targets?|buyable|companies|company|with|having|that|are|which|for sale|private|unlisted|\+)\b", " ", what, flags=re.I)
    raw["what"] = " ".join(what.split()) or "companies"
    if raw["what"] != "companies":
        raw["what"] += " companies"
    return raw


# ---------------------------------------------------------------------------
def interpret(thesis: str, *, llm=None) -> dict:
    """thesis -> {params, parser, seconds, error}. Model first, rules as fallback."""
    t0 = time.time()
    if news_ai.available() or llm:
        try:
            res = (llm or news_ai.call)(PROMPT.format(thesis=thesis.replace('"', "'"), rounds=", ".join(ROUND_TYPES)), max_tokens=800)
            raw = news_ai._parse_json(res[0])
            used = res[2] if len(res) > 2 else "model"
            return {"params": normalise(raw), "parser": used, "seconds": round(time.time() - t0, 1), "error": None}
        except Exception as e:
            log.warning("thesis model failed, using rules: %s", e)
            err = f"{type(e).__name__}: {str(e)[:120]}"
    else:
        err = None
    return {"params": normalise(rule_parse(thesis)), "parser": "rules", "seconds": round(time.time() - t0, 1), "error": err}
