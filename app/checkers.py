"""Deterministic verdicts, one checker per claim type.

Rules that keep this honest:
- "contradicted" / "false premise" only with a contrary record in hand.
- Every verdict carries a one-line reason and the exact field or passage.
- Anything not final gets a document request from the fixed table.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from .doc_table import request_for
from .models import Claim, Evidence, Finding

ENRICH = "Crustdata /company/enrich"
JOBS = "Crustdata /job/search"
SEARCH = "Crustdata /web/search/live"
ARCHIVE = "Internet Archive (first snapshot)"

CITY_STATE = {
    "chennai": "tamil nadu", "coimbatore": "tamil nadu", "hosur": "tamil nadu", "madurai": "tamil nadu",
    "tiruvallur": "tamil nadu", "sriperumbudur": "tamil nadu", "guindy": "tamil nadu",
    "bengaluru": "karnataka", "bangalore": "karnataka", "mysuru": "karnataka", "nelamangala": "karnataka",
    "mumbai": "maharashtra", "pune": "maharashtra", "bhiwandi": "maharashtra", "nagpur": "maharashtra",
    "hyderabad": "telangana", "delhi": "delhi", "new delhi": "delhi", "gurugram": "haryana",
    "gurgaon": "haryana", "sonipat": "haryana", "noida": "uttar pradesh", "lucknow": "uttar pradesh",
    "kolkata": "west bengal", "ahmedabad": "gujarat", "kochi": "kerala", "jaipur": "rajasthan",
}
ALIASES = {"bangalore": "bengaluru", "bengaluru": "bangalore", "gurgaon": "gurugram", "gurugram": "gurgaon",
           "tn": "tamil nadu", "ka": "karnataka", "mh": "maharashtra"}


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def mentions(hay: str | None, needle: str | None) -> bool:
    """Whole-word, accent-insensitive containment, with a few city aliases."""
    if not hay or not needle:
        return False
    h = f" {re.sub(r' +', ' ', norm(hay))} "
    for n in {norm(needle), ALIASES.get(norm(needle), "")} - {""}:
        if f" {n} " in h:
            return True
    return False


def state_of(place: str | None) -> str | None:
    p = norm(place)
    if p in CITY_STATE.values():
        return p
    return CITY_STATE.get(p) or CITY_STATE.get(ALIASES.get(p, ""))


def host(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def _fmt(n) -> str:
    return str(int(n)) if isinstance(n, (int, float)) and float(n).is_integer() else str(n)


@dataclass
class Record:
    name: str
    domain: str | None
    company: dict
    retrieved_at: str
    jobs: list[dict] = field(default_factory=list)
    jobs_total: int | None = None
    jobs_at: str | None = None
    archive_first: str | None = None      # YYYYMMDDhhmmss
    archive_at: str | None = None
    crust: object | None = None           # Crust, for on-demand web searches
    today: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # -- convenience accessors
    def g(self, path: str):
        cur = self.company
        for k in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    def ev(self, fieldpath: str, value=None, source: str = ENRICH) -> Evidence:
        v = self.g(fieldpath) if value is None else value
        return Evidence(source=source, field=fieldpath, value=_short(v), retrieved_at=self.retrieved_at)

    @property
    def people(self) -> list[dict]:
        seen, out = set(), []
        for grp in ("founders", "cxos", "decision_makers"):
            for p in (self.g(f"people.{grp}") or []):
                pid = p.get("crustdata_person_id")
                if pid not in seen:
                    seen.add(pid)
                    out.append(p)
        return out

    def search(self, query: str):
        if not self.crust:
            return [], None
        try:
            res, rec = self.crust.web_search(query)
            return res, rec.retrieved_at
        except Exception:
            return [], None


def _short(v) -> str:
    if isinstance(v, list):
        s = "; ".join(str(x) for x in v[:6]) + (f" (+{len(v) - 6} more)" if len(v) > 6 else "")
    else:
        s = str(v)
    return s if len(s) <= 400 else s[:397] + "…"


def _pending(claim: Claim, verdict: str, reason: str, ev=None, checked=None) -> Finding:
    doc, why = request_for(claim)
    return Finding(claim, verdict, reason, ev or [], checked or [], request=doc, final=False)


# ---------------------------------------------------------------------------
def check(claim: Claim, r: Record) -> Finding:
    fn = CHECKERS.get(claim.type)
    if not fn:
        return _pending(claim, "cannot verify", "No checker for this claim type yet.")
    return fn(claim, r)


def check_identity(c: Claim, r: Record) -> Finding:
    if c.metric == "founded_year" or (c.year and not c.place):
        rec_year = r.g("basic_info.year_founded")
        claimed = int(c.year or c.number or 0)
        if not rec_year:
            return _pending(c, "cannot verify", "No founding year on record.", checked=[f"{ENRICH} basic_info.year_founded"])
        ev = [r.ev("basic_info.year_founded")]
        if int(rec_year) == claimed:
            return Finding(c, "verified", f"Record shows founded {rec_year}.", ev)
        return Finding(c, "contradicted", f"Claim says {claimed}; record shows founded {rec_year}.", ev,
                       request=request_for(c)[0])
    if c.place:
        hq = " ".join(str(x) for x in [r.g("locations.headquarters"), r.g("locations.city"), r.g("locations.state")] if x)
        ev = [r.ev("locations.headquarters", hq or None)]
        if not hq:
            return _pending(c, "cannot verify", "No headquarters on record.", checked=[f"{ENRICH} locations"])
        if mentions(hq, c.place):
            return Finding(c, "verified", f"Record HQ is in {c.place}.", ev)
        claimed_state, hq_state = state_of(c.place), state_of(r.g("locations.state"))
        if claimed_state and hq_state and claimed_state == hq_state:
            return _pending(c, "consistent", f"Record HQ is in {r.g('locations.state')}, the same state; the city is not named.", ev)
        if claimed_state and hq_state and claimed_state != hq_state:
            return Finding(c, "contradicted", f"Claim says {c.place}; record HQ is in {r.g('locations.state')}.", ev,
                           request=request_for(c)[0])
        return _pending(c, "cannot verify", "Could not place the record HQ relative to the claim.", ev)
    return _pending(c, "cannot verify", "Nothing specific to check.")


def check_workforce(c: Claim, r: Record) -> Finding:
    total = r.g("headcount.total")
    if c.number is None or not total:
        return _pending(c, "cannot verify", "No headcount on record.", checked=[f"{ENRICH} headcount.total"])
    ev = [r.ev("headcount.total"), r.ev("basic_info.employee_count_range")]
    claimed = float(c.number)
    if claimed < total - max(3, 0.05 * total):
        return Finding(c, "contradicted",
                       f"Claimed {_fmt(claimed)}, but {total} people already list this company: the claim is below the minimum on record.",
                       ev, request=request_for(c)[0])
    return _pending(c, "consistent",
                    f"{total} profiles on record is a lower bound; it cannot confirm the total of {_fmt(claimed)}.", ev)


def check_growth(c: Claim, r: Record) -> Finding:
    yoy = r.g("headcount.growth_percent.yoy")
    openings = r.g("hiring.openings_growth_percent")
    if c.number is None or yoy is None:
        return _pending(c, "cannot verify", "No growth series on record.", checked=[f"{ENRICH} headcount.growth_percent.yoy"])
    ev = [r.ev("headcount.growth_percent.yoy", f"{yoy:+.1f}%")]
    if openings is not None:
        ev.append(r.ev("hiring.openings_growth_percent", f"{openings:+.1f}%"))
    claimed = float(c.number)
    if (claimed > 0 and yoy < -5) or (claimed < 0 and yoy > 5):
        return Finding(c, "contradicted", f"Claim says {claimed:+.0f}%; headcount moved {yoy:+.1f}% YoY, the opposite direction.",
                       ev, request=request_for(c)[0])
    return _pending(c, "consistent", f"Headcount grew {yoy:+.1f}% YoY, the same direction; it does not measure revenue growth.", ev)


def _sites_in(r: Record, place: str | None) -> list[str]:
    addrs = r.g("locations.all_office_addresses") or []
    if not place:
        return list(addrs)
    st = state_of(place)
    return [a for a in addrs if mentions(a, place) or (st and mentions(a, st))]


def check_footprint(c: Claim, r: Record) -> Finding:
    n = int(c.number) if c.number is not None else None
    if c.metric == "cities":
        cities = {norm(j.get("location", {}).get("city")) for j in r.jobs if j.get("location", {}).get("city")}
        addrs = r.g("locations.all_office_addresses") or []
        cities |= {norm(k) for k in CITY_STATE if any(mentions(a, k) for a in addrs)}
        cities.discard("")
        ev = [r.ev("locations.all_office_addresses", f"{len(cities)} distinct cities: " + ", ".join(sorted(cities)[:12]))]
        if n is None:
            return _pending(c, "cannot verify", "No count to compare.", ev)
        if len(cities) >= n:
            return Finding(c, "verified", f"{len(cities)} distinct cities across addresses and job posts.", ev)
        if cities:
            return _pending(c, "partial", f"Found {len(cities)} of {n} cities on record.", ev)
        return _pending(c, "cannot verify", "No city-level footprint on record.", ev)

    matched = _sites_in(r, c.place)
    job_hits = [j for j in r.jobs if c.place and (mentions(j.get("location", {}).get("raw"), c.place)
                                                  or mentions(j.get("location", {}).get("state"), state_of(c.place) or c.place))]
    where = f" in {c.place}" if c.place else ""
    ev = []
    if matched:
        ev.append(Evidence(ENRICH, "locations.all_office_addresses", _short(matched), r.retrieved_at))
    if job_hits:
        ev.append(Evidence(JOBS, "location.raw", _short(sorted({j['location']['raw'] for j in job_hits})), r.jobs_at or r.retrieved_at))
    checked = [f"{ENRICH} locations.all_office_addresses ({len(r.g('locations.all_office_addresses') or [])} addresses)",
               f"{JOBS} ({len(r.jobs)} recent posts)"]
    if n is None:
        return _pending(c, "cannot verify" if not matched else "partial", f"{len(matched)} addresses on record{where}.", ev, checked)
    if len(matched) >= n:
        return Finding(c, "verified", f"{len(matched)} addresses on record{where}, at least the {n} claimed.", ev, checked)
    if matched or job_hits:
        return _pending(c, "partial", f"{len(matched)} of {n} sites found on record{where}"
                        + (f"; {len(job_hits)} job posts there" if job_hits else "") + ".", ev, checked)
    return _pending(c, "cannot verify", f"No addresses or job posts on record{where}.", ev, checked)


def _web_corroboration(r: Record, query: str, a: str, b: str):
    """Return (independent_hits, self_hits, retrieved_at). Both names must appear."""
    res, at = r.search(query)
    own = norm(r.domain or "")
    ind, own_hits = [], []
    for x in res:
        blob = f"{x.get('title', '')} {x.get('snippet', '')}"
        if mentions(blob, a) and mentions(blob, b):
            (own_hits if own and own in norm(host(x.get("url"))) else ind).append(x)
    return ind, own_hits, at, len(res)


def check_investors(c: Claim, r: Record) -> Finding:
    inv = r.g("funding.investors") or []
    hit = [i for i in inv if mentions(i, c.entity) or mentions(c.entity, i)]
    if hit:
        return Finding(c, "verified", f"{hit[0]} is listed as an investor.", [r.ev("funding.investors")])
    news = [n for n in (r.g("news") or []) if mentions(n.get("article_title"), c.entity)]
    if news:
        n = news[0]
        return Finding(c, "verified", "A news item names this investor.",
                       [Evidence(n.get("article_publisher_name") or ENRICH, "news.article_title", n["article_title"],
                                 r.retrieved_at, n.get("article_url"))])
    q = f'"{r.name}" "{c.entity}" funding'
    ind, _own, at, k = _web_corroboration(r, q, r.name, c.entity)
    if ind:
        x = ind[0]
        return Finding(c, "verified", f"Independent source links {r.name} and {c.entity}.",
                       [Evidence(host(x["url"]), None, x.get("snippet") or x.get("title"), at, x["url"])])
    checked = [f"{ENRICH} funding.investors ({'none listed' if not inv else ', '.join(inv[:5])})",
               f"{ENRICH} news ({len(r.g('news') or [])} items, none name {c.entity})",
               f"{SEARCH} '{q}' ({k} results, none name both)"]
    return _pending(c, "cannot verify", f"No funding record, news or web source names {c.entity}.", checked=checked)


def _history(p: dict) -> list[dict]:
    ed = (p.get("experience") or {}).get("employment_details") or {}
    return (ed.get("current") or []) + (ed.get("past") or [])


def check_people(c: Claim, r: Record) -> Finding:
    target = c.entity
    people = r.people
    if c.person:
        people = [p for p in people if mentions((p.get("basic_profile") or {}).get("name"), c.person)] or []
        if not people:
            return _pending(c, "cannot verify", f"{c.person} is not among the founders/CXOs on record.",
                            checked=[f"{ENRICH} people.founders/cxos"])
    hits = []
    for p in people:
        for job in _history(p):
            if target and (mentions(job.get("employer_name"), target) or mentions(target, job.get("employer_name"))):
                hits.append((p, job))
    if hits:
        p, job = hits[0]
        name = (p.get("basic_profile") or {}).get("name")
        dates = f"{(job.get('employee_start_date') or '')[:7]} to {(job.get('employee_end_date') or 'now')[:7]}"
        return Finding(c, "verified", f"{name} was {job.get('employee_title')} at {job.get('employer_name')}.",
                       [Evidence(ENRICH, "people[].experience.employment_details",
                                 f"{name}: {job.get('employee_title')} @ {job.get('employer_name')} ({dates})", r.retrieved_at)])
    names = ", ".join((p.get("basic_profile") or {}).get("name", "?") for p in people)
    if c.person and people:
        p = people[0]
        hist = "; ".join(j.get("employer_name", "?") for j in _history(p))
        return Finding(c, "contradicted", f"{c.person}'s full work history does not include {target}.",
                       [Evidence(ENRICH, "people[].experience.employment_details", f"{c.person}: {hist}", r.retrieved_at)],
                       request=request_for(c)[0])
    return _pending(c, "cannot verify", f"None of the {len(people)} leaders on record ({names}) list {target}; others may.",
                    checked=[f"{ENRICH} people.founders/cxos/decision_makers"])


def check_customers(c: Claim, r: Record) -> Finding:
    news = [n for n in (r.g("news") or []) if mentions(n.get("article_title"), c.entity)]
    if news:
        n = news[0]
        return Finding(c, "verified", "A news item links the two companies.",
                       [Evidence(n.get("article_publisher_name") or ENRICH, "news.article_title", n["article_title"],
                                 r.retrieved_at, n.get("article_url"))])
    q = f'"{r.name}" "{c.entity}"'
    ind, own, at, k = _web_corroboration(r, q, r.name, c.entity)
    if ind:
        x = ind[0]
        return Finding(c, "verified", f"{host(x['url'])} links {r.name} and {c.entity}.",
                       [Evidence(host(x["url"]), None, x.get("snippet") or x.get("title"), at, x["url"])])
    if own:
        x = own[0]
        return _pending(c, "self-reported", f"Only {r.name}'s own pages name {c.entity}.",
                        [Evidence(host(x["url"]), None, x.get("snippet") or x.get("title"), at, x["url"])])
    return _pending(c, "cannot verify", f"No news or web source links {r.name} and {c.entity}.",
                    checked=[f"{ENRICH} news", f"{SEARCH} '{q}' ({k} results)"])


def check_dates(c: Claim, r: Record) -> Finding:
    y = int(c.year or c.number or 0)
    founded = r.g("basic_info.year_founded")
    arch = int(r.archive_first[:4]) if r.archive_first else None
    news_years = [int(n["article_publish_date"][:4]) for n in (r.g("news") or []) if n.get("article_publish_date")]
    first_news = min(news_years) if news_years else None
    ev = []
    if founded:
        ev.append(r.ev("basic_info.year_founded"))
    if arch:
        ev.append(Evidence(ARCHIVE, None, f"{r.domain} first archived {r.archive_first[:4]}-{r.archive_first[4:6]}-{r.archive_first[6:8]}",
                           r.archive_at or r.retrieved_at, f"https://web.archive.org/web/{r.archive_first}/{r.domain}"))
    if first_news:
        ev.append(Evidence(ENRICH, "news.article_publish_date", f"earliest news item {first_news}", r.retrieved_at))
    product_ev = [x for x in (arch, first_news) if x]
    earliest = min(product_ev) if product_ev else None
    if earliest and earliest <= y:
        return Finding(c, "verified", f"Public evidence of the business exists by {earliest}.", ev)
    if founded and y < int(founded) and (earliest is None or earliest > y):
        return Finding(c, "contradicted", f"Claims {y}, but the company was founded in {founded} and nothing public predates that.",
                       ev, request=request_for(c)[0])
    if earliest:
        return _pending(c, "earliest evidence", f"Earliest public evidence is {earliest}, after the claimed {y}.", ev)
    return _pending(c, "cannot verify", "No dated public evidence found.", ev)


def check_efficacy(c: Claim, r: Record) -> Finding:
    num = _fmt(c.number) if c.number is not None else ""
    q = f'"{r.name}" {num}%' if num else f'"{r.name}" {c.entity or ""}'
    res, at = r.search(q)
    own = norm(r.domain or "")
    for x in res:
        blob = f"{x.get('title', '')} {x.get('snippet', '')}"
        if own and own in norm(host(x.get("url"))):
            continue
        if mentions(blob, r.name) and (not num or f"{num}%" in blob.replace(" %", "%")):
            return Finding(c, "independently supported", f"{host(x['url'])} repeats the figure.",
                           [Evidence(host(x["url"]), None, x.get("snippet") or x.get("title"), at, x["url"])])
    return _pending(c, "self-reported", "Only the company states this figure; no independent source found.",
                    checked=[f"{SEARCH} '{q}' ({len(res)} results)"])


def check_forward(c: Claim, r: Record) -> Finding:
    return _pending(c, "projection", "A projection, not a fact; not checked.")


def check_premise(c: Claim, r: Record) -> Finding:
    place = c.place
    if not place:
        return _pending(c, "unsupported premise", "The question names no place or fact we can test.")
    cutoff = r.today - timedelta(days=120)
    recent_jobs = []
    for j in r.jobs:
        if not mentions(j.get("location", {}).get("raw"), place):
            continue
        d = (j.get("metadata") or {}).get("date_added") or ""
        try:
            dt = datetime.fromisoformat(d[:19]).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if dt >= cutoff:
            recent_jobs.append((dt, j))
    addrs = _sites_in(r, place) if state_of(place) is None else [a for a in (r.g("locations.all_office_addresses") or []) if mentions(a, place)]
    region = (r.g("headcount.by_region_absolute") or {})
    region_hits = {k: v for k, v in region.items() if mentions(k, place)}
    ev = []
    if recent_jobs:
        recent_jobs.sort(key=lambda t: t[0], reverse=True)
        ev.append(Evidence(JOBS, "job_details.title / metadata.date_added",
                           _short([f"{j['job_details']['title']} ({dt:%d %b %Y}) {j['job_details'].get('url', '')}" for dt, j in recent_jobs]),
                           r.jobs_at or r.retrieved_at, recent_jobs[0][1]["job_details"].get("url")))
    if addrs:
        ev.append(Evidence(ENRICH, "locations.all_office_addresses", _short(addrs), r.retrieved_at))
    if region_hits:
        ev.append(Evidence(ENRICH, "headcount.by_region_absolute", _short([f"{k}: {v}" for k, v in region_hits.items()]), r.retrieved_at))
    if recent_jobs:
        return Finding(c, "false premise",
                       f"{len(recent_jobs)} job posts in {place} in the last 120 days; the site looks active.", ev,
                       request=request_for(c)[0])
    if addrs or region_hits:
        return _pending(c, "unsupported premise", f"{place} is still on record and nothing shows a closure.", ev)
    return _pending(c, "unsupported premise", f"No record of the company in {place} at all.",
                    checked=[f"{JOBS} ({len(r.jobs)} posts)", f"{ENRICH} locations"])


CHECKERS = {
    "identity": check_identity, "workforce": check_workforce, "growth": check_growth,
    "footprint": check_footprint, "investors": check_investors, "people": check_people,
    "customers": check_customers, "dates": check_dates, "efficacy": check_efficacy,
    "forward_looking": check_forward, "premise": check_premise,
}
