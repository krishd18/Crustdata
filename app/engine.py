"""One dossier run: resolve -> pull records -> extract -> check -> diff -> cost."""
from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx

from . import extract, inconsistency, store
from .checkers import Record, check, mentions, norm
from .crust import Crust, now_iso
from .models import Claim

log = logging.getLogger("secondlook.engine")

COMPANY_FIELDS = [
    "basic_info", "locations", "news", "people", "social_profiles", "taxonomy",
    "headcount.total", "headcount.growth_percent", "headcount.by_region_absolute",
    "hiring", "funding.investors", "funding.total_investment_usd", "funding.last_round_type",
    "funding.last_fundraise_date", "funding.num_funding_rounds",
]

# Claude Opus 5.5 list prices, USD per million tokens (input, output).
LLM_PRICE = (4.0, 20.0)


class NeedsPerson(Exception):
    def __init__(self, candidates: list[dict]):
        super().__init__("ambiguous company")
        self.candidates = candidates


# ---------------------------------------------------------------------------
_PII_KEYS = re.compile(r"email|phone|contact", re.I)


def redact(o):
    """Drop personal contact fields from anything we persist."""
    if isinstance(o, dict):
        return {k: redact(v) for k, v in o.items() if not _PII_KEYS.search(k)}
    if isinstance(o, list):
        return [redact(v) for v in o]
    return o


def resolve(crust: Crust, name: str, domain: str | None, city: str | None) -> dict:
    if domain:
        matches, _ = crust.identify(domain=domain)
        if matches:
            return matches[0]["company_data"]
    matches, _ = crust.identify(name=name)
    seen, cands = set(), []
    for m in matches:
        cd = m["company_data"]
        if cd["crustdata_company_id"] not in seen:
            seen.add(cd["crustdata_company_id"])
            cands.append({**cd, "confidence": m.get("confidence_score")})
    if not cands:
        raise NeedsPerson([])
    exact = [c for c in cands if norm(c["basic_info"]["name"]) == norm(name)]
    pool = exact or cands
    if len(pool) == 1:
        return pool[0]
    if city:  # disambiguate by city, at most 3 paid lookups
        hits = []
        for c in pool[:3]:
            prof, _ = crust.enrich_company(c["crustdata_company_id"], ["basic_info", "locations"])
            loc = (prof or {}).get("locations") or {}
            blob = " ".join([str(loc.get("headquarters") or "")] + (loc.get("all_office_addresses") or []))
            if mentions(blob, city):
                hits.append(c)
        if len(hits) == 1:
            return hits[0]
    raise NeedsPerson([{
        "crustdata_company_id": c["crustdata_company_id"], "name": c["basic_info"].get("name"),
        "domain": c["basic_info"].get("primary_domain"), "founded": c["basic_info"].get("year_founded"),
        "description": (c["basic_info"].get("description") or "")[:160],
    } for c in pool[:6]])


def archive_first(domain: str | None) -> tuple[str | None, str]:
    at = now_iso()
    if not domain:
        return None, at
    try:
        r = httpx.get("https://web.archive.org/cdx/search/cdx",
                      params={"url": domain, "output": "json", "limit": 1, "fl": "timestamp"}, timeout=20)
        rows = r.json()
        return (rows[1][0] if len(rows) > 1 else None), at
    except Exception as e:
        log.info("archive lookup failed: %s", e)
        return None, at


def leaders_snapshot(company: dict) -> list[dict]:
    out, seen = [], set()
    for grp in ("founders", "cxos"):
        for p in ((company.get("people") or {}).get(grp) or []):
            url = ((p.get("social_handles") or {}).get("professional_network_identifier") or {}).get("profile_url")
            if not url or url in seen:
                continue
            seen.add(url)
            cur = (((p.get("experience") or {}).get("employment_details") or {}).get("current") or [])
            out.append({
                "name": (p.get("basic_profile") or {}).get("name"),
                "title": (p.get("basic_profile") or {}).get("current_title"),
                "profile_url": url,
                "employers": sorted({j.get("employer_name") for j in cur if j.get("employer_name")}),
            })
    return out


# ---------------------------------------------------------------------------
def run(run_id: str, token: str):
    run_row = store.q("SELECT * FROM runs WHERE id=?", (run_id,), one=True)
    d = store.q("SELECT * FROM dossiers WHERE id=?", (run_row["dossier_id"],), one=True)
    steps: list[str] = []

    def step(msg: str):
        steps.append(msg)
        store.save_progress(run_id, steps)

    crust = Crust(token)
    usage: dict = {}
    try:
        step("Resolving the company")
        if d["company_id"]:
            cid = d["company_id"]
        else:
            cd = resolve(crust, d["name"], d["domain"], d["city"])
            cid = cd["crustdata_company_id"]
            store.x("UPDATE dossiers SET company_id=? WHERE id=?", (cid, d["id"]))

        step("Pulling the company record")
        company, rec = crust.enrich_company(cid, COMPANY_FIELDS)
        if not company:
            raise RuntimeError(f"No company record for id {cid}")
        name = company["basic_info"]["name"]
        domain = d["domain"] or company["basic_info"].get("primary_domain")

        step("Pulling job posts and the web archive")
        with ThreadPoolExecutor(4) as pool:
            f_jobs = pool.submit(crust.jobs, cid, 60)
            f_arch = pool.submit(archive_first, domain)
            f_site = pool.submit(_fetch_site, crust, domain)
            step("Reading the teaser")
            f_deck = pool.submit(extract.extract, d["teaser"], company=name, kind="deck", usage=usage)
            jobs, jobs_total, jrec = f_jobs.result()
            arch, arch_at = f_arch.result()
            site_pages = f_site.result()
            claims = f_deck.result()

        record = Record(name=name, domain=domain, company=company, retrieved_at=rec.retrieved_at,
                        jobs=jobs, jobs_total=jobs_total, jobs_at=jrec.retrieved_at,
                        archive_first=arch, archive_at=arch_at, crust=crust)

        step(f"Checking {len(claims)} claims")
        with ThreadPoolExecutor(6) as pool:
            findings = list(pool.map(lambda c: check(c, record), claims))

        step("Comparing the company's own sources")
        own_sources = {"Teaser / deck": (claims, None)}
        texts = []
        for p in site_pages:
            texts.append((f"Website: {p['url']}", p.get("content") or "", p["url"]))
        desc = company["basic_info"].get("description")
        if desc:
            texts.append(("Company profile 'About'", desc, company["basic_info"].get("professional_network_url")))
        for p in leaders_snapshot(company)[:4]:
            full = next((x for x in record.people if (x.get("basic_profile") or {}).get("name") == p["name"]), {})
            summ = " ".join(filter(None, [(full.get("basic_profile") or {}).get("headline"),
                                          (full.get("basic_profile") or {}).get("summary")]))
            if summ:
                texts.append((f"{p['name']} (profile)", summ, p["profile_url"]))
        with ThreadPoolExecutor(4) as pool:
            got = list(pool.map(lambda t: extract.extract(t[1][:20000], company=name, kind="website", usage=usage), texts))
        for (label, _txt, url), cl in zip(texts, got):
            own_sources[label] = (cl, url)
        conflicts = inconsistency.find(own_sources)

        prev = store.q("SELECT result FROM runs WHERE dossier_id=? AND status='done' AND id<>? ORDER BY seq DESC LIMIT 1",
                       (d["id"], run_id), one=True)
        prev = json.loads(prev["result"]) if prev else None
        leaders = leaders_snapshot(company)
        changes = []
        if prev:
            step("Re-checking leaders and diffing against the last snapshot")
            changes = _diff(prev, findings, company, jobs_total, crust)

        result = {
            "company": redact({
                "crustdata_company_id": cid, "name": name, "domain": domain,
                "hq": (company.get("locations") or {}).get("headquarters"),
                "founded": company["basic_info"].get("year_founded"),
                "headcount": (company.get("headcount") or {}).get("total"),
                "linkedin": company["basic_info"].get("professional_network_url"),
                "description": company["basic_info"].get("description"),
            }),
            "snapshot_at": now_iso(),
            "findings": [redact(f.to_dict()) for f in findings],
            "inconsistencies": conflicts,
            "requests": _requests(findings),
            "changes": changes,
            "leaders": leaders,
            "headcount_total": (company.get("headcount") or {}).get("total"),
            "jobs_total": jobs_total,
            "sources_read": [lbl for lbl in own_sources],
            "cost": _cost(crust, usage),
            "llm": "claude" if extract.llm_available() else "rules (no ANTHROPIC_API_KEY)",
        }
        store.x("UPDATE runs SET status='done', finished_at=?, result=? WHERE id=?",
                (now_iso(), json.dumps(result, default=str), run_id))
        step("Done")
    except NeedsPerson as e:
        store.x("UPDATE runs SET status='needs_person', result=? WHERE id=?",
                (json.dumps({"candidates": e.candidates, "cost": _cost(crust, usage)}), run_id))
        step("Held for a person: more than one company matches")
    except Exception as e:
        log.exception("run failed")
        store.x("UPDATE runs SET status='error', error=?, finished_at=? WHERE id=?", (str(e), now_iso(), run_id))


def _fetch_site(crust: Crust, domain: str | None) -> list[dict]:
    if not domain:
        return []
    try:
        pages, _ = crust.web_fetch([f"https://{domain}", f"https://{domain}/about"])
        return pages
    except Exception as e:
        log.info("site fetch failed: %s", e)
        return []


def _requests(findings) -> list[dict]:
    out, seen = [], set()
    for f in findings:
        if not f.request or f.claim.type == "premise":
            continue
        key = f.request
        if key in seen:
            continue
        seen.add(key)
        out.append({"claim": f.claim.text, "type": f.claim.type, "verdict": f.verdict, "document": f.request,
                    "reason": f.reason})
    return out


def _cost(crust: Crust, usage: dict) -> dict:
    tin, tout = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
    llm_usd = tin / 1e6 * LLM_PRICE[0] + tout / 1e6 * LLM_PRICE[1]
    credit_usd = float(os.getenv("CRUSTDATA_CREDIT_USD") or 0) or None
    usd_inr = float(os.getenv("USD_INR") or 0) or None
    total_usd = llm_usd + (crust.credits_used * credit_usd if credit_usd else 0)
    by_ep: dict = {}
    for c in crust.calls:
        e = by_ep.setdefault(c.path, {"calls": 0, "credits": 0.0})
        e["calls"] += 1
        e["credits"] = round(e["credits"] + c.credits, 3)
    return {
        "credits": crust.credits_used, "by_endpoint": by_ep,
        "llm_input_tokens": tin, "llm_output_tokens": tout, "llm_usd": round(llm_usd, 4),
        "credit_usd": credit_usd,
        "total_usd": round(total_usd, 4) if credit_usd else None,
        "total_inr": round(total_usd * usd_inr, 2) if (credit_usd and usd_inr) else None,
    }


def _diff(prev: dict, findings, company: dict, jobs_total, crust: Crust) -> list[dict]:
    out = []
    today = datetime.now(timezone.utc).strftime("%d %b")
    old = {norm(f["claim"]["text"]): f for f in prev.get("findings", [])}
    for f in findings:
        o = old.get(norm(f.claim.text))
        if not o:
            continue
        if o["verdict"] != f.verdict:
            out.append({"kind": "verdict", "claim": f.claim.text,
                        "text": f"Verdict changed: {o['verdict']} → {f.verdict}. {f.reason}"})
        else:
            ov = [e["value"] for e in o.get("evidence", [])]
            nv = [e.value for e in f.evidence]
            if ov != nv and ov and nv:
                out.append({"kind": "evidence", "claim": f.claim.text,
                            "text": f"Record changed: {ov[0]} → {nv[0]}"})
    h_old, h_new = prev.get("headcount_total"), (company.get("headcount") or {}).get("total")
    if h_old and h_new and h_old != h_new:
        out.append({"kind": "headcount", "text": f"Headcount on record: {h_old} → {h_new} (company enrich, {today})"})
    if prev.get("jobs_total") is not None and jobs_total is not None and prev["jobs_total"] != jobs_total:
        out.append({"kind": "jobs", "text": f"Job posts on record: {prev['jobs_total']} → {jobs_total} (job search, {today})"})
    # Leaders: re-read each previous leader's own profile, so a departure shows
    # even though they have dropped off the company's people list.
    prev_leaders = prev.get("leaders") or []
    if prev_leaders:
        try:
            people, _ = crust.enrich_people([p["profile_url"] for p in prev_leaders])
        except Exception as e:
            log.info("person enrich failed: %s", e)
            people = []
        by_name = {(p.get("basic_profile") or {}).get("name"): p for p in people if p}
        for pl in prev_leaders:
            p = by_name.get(pl["name"])
            if not p:
                continue
            cur = (((p.get("experience") or {}).get("employment_details") or {}).get("current") or [])
            now_emp = sorted({j.get("employer_name") for j in cur if j.get("employer_name")})
            if now_emp and now_emp != pl["employers"]:
                out.append({"kind": "person", "text": f"{pl['name']} ({pl['title']})'s profile now shows "
                            f"{', '.join(now_emp)} (was {', '.join(pl['employers']) or 'none'}) (person enrich, {today})"})
    return out
