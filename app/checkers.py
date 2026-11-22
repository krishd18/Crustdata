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
CANON = {"bangalore": "bengaluru", "gurgaon": "gurugram", "dodda ballapur": "doddaballapura",
         "nelmangala": "nelamangala", "new delhi": "delhi", "bombay": "mumbai", "madras": "chennai"}
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
    registry: dict | None = None          # primary legal entity from public.Public.registry()
    documents: list = field(default_factory=list)  # third-party public documents (invoices, e-way bills...)

    def docs_in(self, place: str | None = None, since: datetime | None = None) -> list[dict]:
        """Third-party documents that place the company somewhere (optionally in `place`, after `since`)."""
        out = []
        st = state_of(place) if place else None
        for d in self.documents:
            ps = d.get("places") or []
            hit = [p for p in ps if not place or mentions(p, place) or (st and state_of(p) == st)]
            if not hit:
                continue
            if since and not (d.get("date") and d["date"] >= since.strftime("%Y-%m-%d")):
                continue
            out.append({**d, "hit": hit})
        return out
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


def _registry_ev(r: Record, what: str) -> Evidence | None:
    reg = r.registry
    if not reg or not (reg.get("cin") or reg.get("legal_name")):
        return None
    src = (reg.get("sources") or [{}])[0]
    label = f"{reg.get('legal_name') or ''} CIN {reg.get('cin') or '?'}".strip()
    return Evidence(source=f"Company registry listing ({host(src.get('url')) if src.get('fetchable') else 'via web search'})",
                    field=f"CIN / {what}", value=f"{label}: {what} {reg.get(what) or ''}".strip(),
                    retrieved_at=src.get("retrieved_at") or r.retrieved_at, url=src.get("url"))


def check_identity(c: Claim, r: Record) -> Finding:
    reg = r.registry or {}
    if c.metric == "founded_year" or (c.year and not c.place):
        rec_year = r.g("basic_info.year_founded")
        reg_year = reg.get("year")
        claimed = int(c.year or c.number or 0)
        ev = ([r.ev("basic_info.year_founded")] if rec_year else []) + [x for x in [_registry_ev(r, "incorporated")] if x]
        if ev and reg_year and not reg.get("incorporated"):
            ev[-1].value = f"{reg.get('legal_name') or ''} CIN {reg['cin']} (the CIN encodes incorporation year {reg_year})".strip()
        if not rec_year and not reg_year:
            return _pending(c, "cannot verify", "No founding or incorporation year on record.",
                            checked=[f"{ENRICH} basic_info.year_founded", "company registry search"])
        if claimed in {int(y) for y in (rec_year, reg_year) if y}:
            both = rec_year and reg_year and int(rec_year) == int(reg_year) == claimed
            return Finding(c, "verified", f"{'Profile and registry both show' if both else 'Record shows'} {claimed}.", ev)
        shown = " and ".join(x for x in [f"profile says founded {rec_year}" if rec_year else "",
                                          f"registry says incorporated {reg_year}" if reg_year else ""] if x)
        return Finding(c, "contradicted", f"Claim says {claimed}; {shown}.", ev, request=request_for(c)[0])
    if c.place and reg.get("registered_state") and state_of(c.place):
        rev = _registry_ev(r, "registered_state")
        if reg.get("registered_office") and mentions(reg["registered_office"], c.place):
            return Finding(c, "verified", f"Registered office is in {c.place}.", [x for x in [_registry_ev(r, "registered_office")] if x])
        if state_of(reg["registered_state"]) == state_of(c.place):
            return _pending(c, "consistent", f"Registered in {reg['registered_state']} (from the CIN); the registry snippet doesn't name the city.",
                            [x for x in [rev] if x])
        return Finding(c, "contradicted", f"Claim says {c.place}; the company is registered in {reg['registered_state']}.",
                       [x for x in [rev] if x], request=request_for(c)[0])
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
        doc_cities = {norm(p) for d in r.docs_in() for p in d["hit"]}
        cities = {CANON.get(x, x) for x in cities | doc_cities} - {""}
        ev = [r.ev("locations.all_office_addresses", f"{len(cities)} distinct cities: " + ", ".join(sorted(cities)[:12]))]
        ev += _doc_ev(r, r.docs_in())
        if n is None:
            return _pending(c, "cannot verify", "No count to compare.", ev)
        if len(cities) >= n:
            return Finding(c, "verified", f"{len(cities)} distinct cities across addresses, job posts and public documents.", ev)
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
    docs = r.docs_in(c.place)
    ev += _doc_ev(r, docs)  # supporting evidence; the site count stays address-based
    checked = [f"{ENRICH} locations.all_office_addresses ({len(r.g('locations.all_office_addresses') or [])} addresses)",
               f"{JOBS} ({len(r.jobs)} recent posts)", f"public documents ({len(r.documents)} found)"]
    if n is None:
        return _pending(c, "cannot verify" if not matched else "partial", f"{len(matched)} addresses on record{where}.", ev, checked)
    if len(matched) >= n:
        return Finding(c, "verified", f"{len(matched)} addresses on record{where}, at least the {n} claimed.", ev, checked)
    if matched or job_hits:
        return _pending(c, "partial", f"{len(matched)} of {n} sites found on record{where}"
                        + (f"; {len(job_hits)} job posts there" if job_hits else "") + ".", ev, checked)
    return _pending(c, "cannot verify", f"No addresses or job posts on record{where}.", ev, checked)


def _doc_ev(r: Record, docs: list[dict]) -> list[Evidence]:
    if not docs:
        return []
    items = [f"{', '.join(d['hit'])}: “{d.get('title')}”{' (' + d['date'] + ')' if d.get('date') else ''}"
             f"{' [' + d['publisher'] + ']' if d.get('publisher') else ''}" for d in docs[:6]]
    return [Evidence("Public documents (invoices, e-way bills; via web search)", None, "; ".join(items),
                     docs[0].get("retrieved_at") or r.retrieved_at, docs[0].get("url"))]


SOCIAL = ("linkedin.com", "facebook.com", "x.com", "twitter.com", "instagram.com", "youtube.com", "medium.com")
# Paid/self-serve press-release wires: the company wrote it.
PR_WIRES = ("pr.com", "prlog.org", "prnewswire.com", "businesswire.com", "einpresswire.com", "openpr.com",
            "globenewswire.com", "newswire.com", "prfree.org", "pressreleasepoint.com")
# Pages that are not anyone's statement: search/app stores, contact-data directories
# (their "competitors like X" pages co-mention everyone), and document-dump sites.
SKIP_HOSTS = ("google.com", "bing.com", "play.google.com", "apps.apple.com", "zoominfo.com", "tracxn.com",
              "rocketreach.co", "signalhire.com", "contactout.com", "apollo.io", "lusha.com", "owler.com",
              "craft.co", "leadiq.com", "pdfcoffee.com", "scribd.com", "dokumen.pub", "slideshare.net")
# Words that make a co-mention a relationship ("Amazon signed Acme"), not two names on one page.
_W = r"(?<![\w-])"
RELATION = _W + (r"(clients?|customers?|partner(?:ed|s|ship)?|serv(?:es|ed|ing)|work(?:s|ed|ing)? with|signed|"
                 r"onboard\w*|chose|selected|contract(?:s|ed)?|vendor|supplier|fulfil\w*\s+for|warehous\w*\s+for)(?![\w-])")
INVESTED = _W + (r"(backed|invest(?:s|ed|ment|or|ors)|funding|funded|raise[sd]?|led by|participation from|"
                 r"portfolio|seed round|series [a-e]\b)(?![\w-])")
NEGATE = r"competitor|rival|alternative|vs\.?|versus|similar companies|companies like"


def _fragment_says(blob: str, a: str, b: str, rel: str | None) -> bool:
    """True if one sentence/fragment names both a and b (and states rel, if given).

    Search snippets stitch unrelated passages together with '...', so the
    names must co-occur inside a single fragment, never across one.
    """
    for frag in re.split(r"\.\.\.|…|(?<=[.!?])\s+", blob):
        if not (mentions(frag, a) and mentions(frag, b)):
            continue
        if re.search(NEGATE, frag, re.I):
            continue
        if rel is None or re.search(rel, frag, re.I):
            return True
    return False


def _slug(url: str | None, kind: str) -> str | None:
    m = re.search(rf"linkedin\.com/{kind}/([^/?#_]+)", url or "")
    return m.group(1).lower() if m else None


def classify(r: Record, url: str | None) -> str:
    """Who published this page, relative to the target?

    own          the target's website or company page
    self         a post by one of the target's own leaders
    skip         weak signal: a personal profile (lists employers, not customers)
                 or someone else's social post
    independent  any other site (news, customer's site, case study, registry)
    """
    h = host(url)
    own = (r.domain or "").lower()
    on = lambda hosts: any(h == s or h.endswith("." + s) for s in hosts)  # noqa: E731
    if own and (h == own or h.endswith("." + own)):
        return "own"
    if on(PR_WIRES):
        return "self"
    if on(SKIP_HOSTS):
        return "skip"
    if any(h == s or h.endswith("." + s) for s in SOCIAL):
        company_slug = _slug(r.g("basic_info.professional_network_url"), "company")
        if company_slug and _slug(url, "company") == company_slug:
            return "own"
        if "/in/" in (url or ""):
            return "skip"
        leader_slugs = {_slug(((p.get("social_handles") or {}).get("professional_network_identifier") or {}).get("profile_url"), "in")
                        for p in r.people}
        post = re.search(r"linkedin\.com/posts/([^/?#]+?)_", url or "")
        if post and post.group(1).lower() in leader_slugs - {None}:
            return "self"
        return "skip"
    return "independent"


def _web_corroboration(r: Record, query: str, a: str, b: str, relation: str | None = None):
    """Return (independent_hits, self_hits, retrieved_at, n_results).

    Both names must appear; for a third-party page, one fragment must also
    state the relationship (a co-mention alone proves nothing).
    """
    res, at = r.search(query)
    ind, own_hits = [], []
    for x in res:
        blob = f"{x.get('title', '')}. {x.get('snippet', '')}"
        if not (mentions(blob, a) and mentions(blob, b)):
            continue
        related = _fragment_says(blob, a, b, relation)
        if re.search(rf"\bex\s*[-–]?\s*{re.escape(b)}", blob, re.I):  # "Ex-Flipkart" is a past employer, not a client
            continue
        kind = classify(r, x.get("url"))
        if kind == "independent":
            if related:  # a third party must say how they're related
                ind.append(x)
        elif kind in ("own", "self"):
            own_hits.append(x)
    return ind, own_hits, at, len(res)


def check_investors(c: Claim, r: Record) -> Finding:
    inv = r.g("funding.investors") or []
    hit = [i for i in inv if mentions(i, c.entity) or mentions(c.entity, i)]
    if hit:
        return Finding(c, "verified", f"{hit[0]} is listed as an investor.", [r.ev("funding.investors")])
    news = [n for n in (r.g("news") or []) if mentions(n.get("article_title"), c.entity)
            and classify(r, n.get("article_url")) == "independent"]
    if news:
        n = news[0]
        return Finding(c, "verified", "A news item names this investor.",
                       [Evidence(n.get("article_publisher_name") or ENRICH, "news.article_title", n["article_title"],
                                 r.retrieved_at, n.get("article_url"))])
    q = f'"{r.name}" "{c.entity}" funding'
    ind, _own, at, k = _web_corroboration(r, q, r.name, c.entity, relation=INVESTED)
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
    if not target:  # "Manish Singh, Co-Founder & CEO": is this person among the leaders on record?
        names = ", ".join((p.get("basic_profile") or {}).get("name", "?") for p in people) or "none"
        if c.number is not None or re.search(r"\bexit|sold|acquired|raised|revenue|figures?\b", c.text, re.I):
            # "7 figures exit": a past result, which no profile record shows
            return _pending(c, "cannot verify", "A leader's past exits or results aren't in the records checked.",
                            checked=[f"{ENRICH} people.founders/cxos"])
        hit = [p for p in people if c.person and mentions((p.get("basic_profile") or {}).get("name"), c.person)]
        if hit:
            bp = hit[0].get("basic_profile") or {}
            return Finding(c, "verified", f"{bp.get('name')} is on record as {bp.get('current_title') or 'a leader'} here.",
                           [Evidence(ENRICH, "people.founders / people.cxos",
                                     f"{bp.get('name')}: {bp.get('current_title') or ''}", r.retrieved_at)])
        return _pending(c, "cannot verify", f"{c.person or 'This person'} is not among the founders/CXOs on record ({names}).",
                        checked=[f"{ENRICH} people.founders/cxos"])
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
    news = [n for n in (r.g("news") or []) if mentions(n.get("article_title"), c.entity)
            and re.search(RELATION, n.get("article_title") or "", re.I)
            and classify(r, n.get("article_url")) == "independent"]
    if news:
        n = news[0]
        return Finding(c, "verified", "A news item links the two companies.",
                       [Evidence(n.get("article_publisher_name") or ENRICH, "news.article_title", n["article_title"],
                                 r.retrieved_at, n.get("article_url"))])
    q = f'"{r.name}" "{c.entity}"'
    ind, own, at, k = _web_corroboration(r, q, r.name, c.entity, relation=RELATION)
    if ind:
        x = ind[0]
        return Finding(c, "verified", f"{host(x['url'])} links {r.name} and {c.entity}.",
                       [Evidence(host(x["url"]), None, x.get("snippet") or x.get("title"), at, x["url"])])
    if own:
        x = own[0]
        return _pending(c, "self-reported", f"Only {r.name}'s own pages or its leaders' posts name {c.entity}.",
                        [Evidence(host(x["url"]), None, x.get("snippet") or x.get("title"), at, x["url"])],
                        checked=[f"{ENRICH} news", f"{SEARCH} '{q}' ({k} results, none independent)"])
    return _pending(c, "cannot verify", f"No news or independent source describes {c.entity} as a client of {r.name}.",
                    checked=[f"{ENRICH} news", f"{SEARCH} '{q}' ({k} results; bare co-mentions, profiles and third-party social posts ignored)"])


def check_dates(c: Claim, r: Record) -> Finding:
    y = int(c.year or c.number or 0)
    founded = r.g("basic_info.year_founded")
    arch = int(r.archive_first[:4]) if r.archive_first else None
    news_years = [int(n["article_publish_date"][:4]) for n in (r.g("news") or []) if n.get("article_publish_date")]
    first_news = min(news_years) if news_years else None
    ev = []
    if founded:
        ev.append(r.ev("basic_info.year_founded"))
    reg_year = (r.registry or {}).get("year")
    if reg_year:
        ev.append(_registry_ev(r, "incorporated") or Evidence("Company registry listing", "CIN", str(reg_year), r.retrieved_at))
        founded = min(int(founded), int(reg_year)) if founded else reg_year  # the earliest legal existence counts
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
    # The page must name the company, the same figure AND what it measures
    # ("damage"), so an unrelated "40% faster" elsewhere does not count.
    subject = [w for w in norm(c.entity or c.text).split() if len(w) >= 4 and w not in _STOP]
    for x in res:
        blob = f"{x.get('title', '')}. {x.get('snippet', '')}"
        if classify(r, x.get("url")) != "independent":
            continue
        # name, figure and subject must sit in the same fragment of the snippet
        ok = False
        for frag in re.split(r"\.\.\.|…|(?<=[.!?])\s+", blob):
            if (mentions(frag, r.name) and (not num or f"{num}%" in frag.replace(" %", "%"))
                    and (not subject or any(mentions(frag, w) for w in subject))):
                ok = True
                break
        if not ok:
            continue
        return Finding(c, "independently supported", f"{host(x['url'])} repeats the figure.",
                       [Evidence(host(x["url"]), None, x.get("snippet") or x.get("title"), at, x["url"])])
    return _pending(c, "self-reported", "Only the company states this figure; no independent source found.",
                    checked=[f"{SEARCH} '{q}' ({len(res)} results; social posts and the company's own pages don't count)"])


_STOP = {"cuts", "reduces", "lowers", "improves", "increases", "boosts", "saves", "with", "from", "that", "this",
         "your", "their", "inventory", "costs", "cost", "time", "rate", "rates", "percent"}


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
    # dated third-party paperwork (invoices, e-way bills) naming that city is activity too
    recent_docs = [d for d in r.docs_in(place, since=cutoff) if any(mentions(p, place) for p in d["hit"])]
    ev += _doc_ev(r, recent_docs)
    if recent_jobs or recent_docs:
        parts = []
        if recent_jobs:
            parts.append(f"{len(recent_jobs)} job post{'s' if len(recent_jobs) != 1 else ''} (latest {recent_jobs[0][0]:%d %b %Y})")
        if recent_docs:
            parts.append(f"{len(recent_docs)} dated document{'s' if len(recent_docs) != 1 else ''} naming it")
        return Finding(c, "false premise",
                       f"{' and '.join(parts)} in {place} in the last 120 days; the company is still active there.", ev,
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
