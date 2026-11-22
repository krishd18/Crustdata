"""Step 1, FIND: a thesis ("warehousing operators in TN/KA") -> a sourced shortlist.

One ranked /company/search call finds candidates; the top few are then
enriched for the signals a deal team screens on, each with its source field
and retrieval date: headcount and its growth, hiring by city, funding, and
leadership.
"""
from __future__ import annotations

import logging
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .crust import Crust, CrustError

log = logging.getLogger("secondlook.find")

STATES = {
    "tn": "Tamil Nadu", "ka": "Karnataka", "mh": "Maharashtra", "ap": "Andhra Pradesh", "ts": "Telangana",
    "tg": "Telangana", "kl": "Kerala", "gj": "Gujarat", "dl": "Delhi", "up": "Uttar Pradesh", "wb": "West Bengal",
    "hr": "Haryana", "rj": "Rajasthan", "mp": "Madhya Pradesh", "pb": "Punjab", "or": "Odisha", "od": "Odisha",
    "ncr": "Delhi",
}
INDIA = set(STATES.values()) | {
    "india", "chennai", "bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "delhi", "new delhi", "gurugram",
    "gurgaon", "noida", "kolkata", "ahmedabad", "coimbatore", "kochi", "jaipur", "hosur", "lucknow", "surat", "nagpur",
}

SEARCH_FIELDS = [
    "basic_info.name", "basic_info.primary_domain", "basic_info.year_founded", "basic_info.description",
    "basic_info.professional_network_url", "headcount.total", "headcount.growth_percent",
    "funding.total_investment_usd", "funding.last_round_type", "locations.headquarters",
    "revenue.estimated.lower_bound_usd", "revenue.estimated.upper_bound_usd", "revenue.acquisition_status",
    "basic_info.company_type",
]
ENRICH_FIELDS = [
    "basic_info", "headcount.total", "headcount.growth_percent", "headcount.by_region_absolute", "hiring",
    "funding.total_investment_usd", "funding.last_round_type", "funding.last_fundraise_date", "funding.investors",
    "people", "locations.headquarters",
]


def parse_thesis(thesis: str) -> tuple[str, list[str]]:
    """'warehousing operators in TN/KA' -> ('warehousing operators', ['Tamil Nadu', 'Karnataka'])."""
    m = re.match(r"(.+?)\s+(?:in|across|based in|from|around)\s+(.+)$", thesis.strip(), re.I)
    if not m:
        return thesis.strip(), []
    what, where = m.group(1), m.group(2)
    places = []
    for p in re.split(r"\s*(?:/|,|\band\b|&|\bor\b)\s*", where):
        p = p.strip(" .")
        if p:
            places.append(STATES.get(p.lower(), p if not p.isupper() or len(p) > 3 else p.title()))
    return what.strip(), places


def _filters(places: list[str], min_headcount: int | None):
    conds = []
    if places and all(p.lower() in {x.lower() for x in INDIA} for p in places):
        conds.append({"field": "locations.country", "type": "=", "value": "IND"})
    if places:
        loc = [{"field": "locations.headquarters", "type": "(.)", "value": p} for p in places]
        conds.append(loc[0] if len(loc) == 1 else {"op": "or", "conditions": loc})
    if min_headcount:
        conds.append({"field": "headcount.total", "type": "=>", "value": int(min_headcount)})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"op": "and", "conditions": conds}


def search(crust: Crust, thesis: str, *, min_headcount: int | None = 10, limit: int = 15, interpretation=None):
    """The thesis is read into structured parameters (thesis_ai: model first, rules as
    fallback); only what lands in a real Crustdata filter is applied as a filter."""
    from . import thesis_ai  # local import: thesis_ai imports this module's tables

    from .cancel import call
    interp = interpretation or call(getattr(crust, "cancel", None), thesis_ai.interpret, thesis)
    p = interp["params"]
    f, applied = thesis_ai.to_filters(p, min_headcount)
    what, places = p["what"], p["locations"]
    body = {"search": {"query": what, "mode": "hybrid"}, "limit": min(100, limit), "fields": SEARCH_FIELDS}
    if f:
        body["filters"] = f
    interp_out = {"parser": interp["parser"], "seconds": interp["seconds"], "error": interp["error"],
                  "applied": applied, "unsupported": p["unsupported"], "params": p, "filters": f}
    try:
        rows, _total, rec = crust.company_search(body)
        mode = "ranked"
    except CrustError as e:
        if e.status != 403:  # 403 = ranked search not enabled on this account
            raise
        words = [w for w in re.findall(r"[a-z]{4,}", what.lower()) if w not in {"operators", "companies", "providers"}]
        conds = [{"field": "taxonomy.professional_network_specialities", "type": "(.)", "value": " ".join(words[:3])}]
        body = {"filters": {"op": "and", "conditions": conds + ([f] if f else [])}, "limit": limit, "fields": SEARCH_FIELDS,
                "sorts": [{"field": "headcount.total", "order": "desc"}]}
        rows, _total, rec = crust.company_search(body)
        mode = "filters"
    return {"query": what, "places": places, "mode": mode, "rows": rows, "retrieved_at": rec.retrieved_at,
            "interpretation": interp_out}


def _sig(label, value, field, at, source="Crustdata /company/enrich", url=None):
    return {"label": label, "value": value, "source": source, "field": field, "retrieved_at": at, "url": url}


def signals(crust: Crust, cid: int, company: dict | None = None, at: str | None = None) -> dict:
    if company is None:
        company, rec = crust.enrich_company(cid, ENRICH_FIELDS)
        at = rec.retrieved_at
    jobs, jobs_total, jrec = crust.jobs(cid, 50)
    jat = jrec.retrieved_at
    c = company or {}
    hc = c.get("headcount") or {}
    gp = hc.get("growth_percent") or {}
    fund = c.get("funding") or {}
    hiring = c.get("hiring") or {}
    out = []
    if hc.get("total") is not None:
        out.append(_sig("Headcount on record", hc["total"], "headcount.total", at))
    if gp.get("yoy") is not None:
        out.append(_sig("Headcount growth YoY", f"{gp['yoy']:+.0f}%", "headcount.growth_percent.yoy", at))
    if gp.get("six_months") is not None:
        out.append(_sig("Headcount growth 6m", f"{gp['six_months']:+.0f}%", "headcount.growth_percent.six_months", at))
    cities = Counter((j.get("location") or {}).get("city") for j in jobs if (j.get("location") or {}).get("city"))
    if cities:
        out.append(_sig("Hiring by city", ", ".join(f"{k} {v}" for k, v in cities.most_common(5)),
                        "location.city (job posts)", jat, "Crustdata /job/search"))
    if jobs_total is not None:
        latest = max(((j.get("metadata") or {}).get("date_added") or "" for j in jobs), default="")[:10]
        out.append(_sig("Job posts on record", f"{jobs_total}" + (f" (latest {latest})" if latest else ""),
                        "total_count", jat, "Crustdata /job/search"))
    if hiring.get("openings_count") is not None:
        out.append(_sig("Open roles", hiring["openings_count"], "hiring.openings_count", at))
    if fund.get("total_investment_usd"):
        out.append(_sig("Funding raised", f"${fund['total_investment_usd']:,.0f}"
                        + (f" ({fund.get('last_round_type')}, {fund.get('last_fundraise_date')})" if fund.get("last_round_type") else ""),
                        "funding.total_investment_usd", at))
    else:
        out.append(_sig("Funding raised", "none on record", "funding.total_investment_usd", at))
    if fund.get("investors"):
        out.append(_sig("Investors", ", ".join(fund["investors"][:5]), "funding.investors", at))
    leaders = []
    for grp in ("founders", "cxos"):
        for p in ((c.get("people") or {}).get(grp) or []):
            bp = p.get("basic_profile") or {}
            item = f"{bp.get('name')} ({bp.get('current_title')})"
            if item not in leaders:
                leaders.append(item)
    if leaders:
        out.append(_sig("Leadership", "; ".join(leaders[:4]), "people.founders / people.cxos", at))
    bi = c.get("basic_info") or {}
    return {"signals": out, "hq": (c.get("locations") or {}).get("headquarters"),
            "description": (bi.get("description") or "")[:240], "linkedin": bi.get("professional_network_url")}


def shortlist(crust: Crust, thesis: str, *, min_headcount: int | None = 10, limit: int = 15, enrich_top: int = 6) -> dict:
    s = search(crust, thesis, min_headcount=min_headcount, limit=limit)
    rows = []
    for c in s["rows"]:
        bi = c.get("basic_info") or {}
        gp = (c.get("headcount") or {}).get("growth_percent") or {}
        rows.append({
            "crustdata_company_id": c.get("crustdata_company_id"),
            "name": bi.get("name"), "domain": bi.get("primary_domain"), "founded": bi.get("year_founded"),
            "hq": (c.get("locations") or {}).get("headquarters"),
            "headcount": (c.get("headcount") or {}).get("total"),
            "growth_12m": gp.get("12m"),
            "funding_usd": (c.get("funding") or {}).get("total_investment_usd"),
            "revenue_lo_usd": ((c.get("revenue") or {}).get("estimated") or {}).get("lower_bound_usd"),
            "revenue_hi_usd": ((c.get("revenue") or {}).get("estimated") or {}).get("upper_bound_usd"),
            "company_type": bi.get("company_type"),
            "acquired": (c.get("revenue") or {}).get("acquisition_status") == "acquired",
            "description": (bi.get("description") or "")[:240],
            "signals": None,
        })
    top = [r for r in rows if r["crustdata_company_id"]][:enrich_top]
    # One /company/enrich call for all of them: Crustdata limits that endpoint per minute
    # (15 by default), so six separate calls per search used most of it.
    companies, at, signals_error = {}, None, None
    if top:
        try:
            companies, rec = crust.enrich_companies([r["crustdata_company_id"] for r in top], ENRICH_FIELDS)
            at = rec.retrieved_at if rec else None
        except CrustError as e:
            signals_error = e.friendly
            log.warning("signals enrich failed: %s", e)
    top = [r for r in top if r["crustdata_company_id"] in companies]
    with ThreadPoolExecutor(4) as pool:
        for r, sig in zip(top, pool.map(lambda r: _safe_signals(crust, r["crustdata_company_id"],
                                                                  companies[r["crustdata_company_id"]], at), top)):
            if sig:
                r.update({k: v for k, v in sig.items() if k != "signals" and v})
                r["signals"] = sig["signals"]
    return {"thesis": thesis, "query": s["query"], "places": s["places"], "mode": s["mode"],
            "min_headcount": min_headcount, "retrieved_at": s["retrieved_at"], "rows": rows,
            "interpretation": s["interpretation"], "signals_error": signals_error}


def _safe_signals(crust, cid, company=None, at=None):
    try:
        return signals(crust, cid, company, at)
    except Exception as e:
        log.warning("signals failed for %s: %s", cid, e)
        return None
