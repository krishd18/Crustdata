"""Public record: news, company registry and published documents about the target.

Three Crustdata web searches (plus the news already on the company record):

  news       /company/enrich `news` + /web/search/live sources=["news"]
  registry   "<name>" CIN, "<domain>" CIN  -> legal entities, CIN, incorporation, status
  documents  "<name>" filetype:pdf         -> brochures, filings, operational documents

What comes out is evidence, not verdicts:
  - registry facts feed the identity and date checkers (CIN encodes state and year)
  - figures quoted in news / press releases join the cross-source inconsistency check
  - adverse terms (insolvency, fraud, raids...) and registry status words become
    "needs confirmation" flags with a document request, never a "contradicted"
    verdict, because a search snippet is not a registry extract.

Google redirect links (google.com/goto) can't be fetched (bot check), so those
results are used from their snippet and the link is kept for a person to open.
"""
from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse

import httpx

from .checkers import PR_WIRES, mentions, norm

log = logging.getLogger("secondlook.public")

# Indian CIN: L/U + 5-digit industry + 2-letter state + 4-digit year + 3-letter type + 6-digit number
CIN_RE = re.compile(r"\b([LU])(\d{5})([A-Z]{2})(\d{4})([A-Z]{3})(\d{6})\b")
CIN_STATES = {
    "TN": "Tamil Nadu", "KA": "Karnataka", "MH": "Maharashtra", "DL": "Delhi", "HR": "Haryana", "UP": "Uttar Pradesh",
    "WB": "West Bengal", "GJ": "Gujarat", "TG": "Telangana", "AP": "Andhra Pradesh", "KL": "Kerala", "RJ": "Rajasthan",
    "MP": "Madhya Pradesh", "PB": "Punjab", "OR": "Odisha", "BR": "Bihar", "AS": "Assam", "CH": "Chandigarh",
    "GA": "Goa", "JH": "Jharkhand", "CT": "Chhattisgarh", "UR": "Uttarakhand", "HP": "Himachal Pradesh",
}
LEGAL_RE = re.compile(r"\b([A-Z][A-Z0-9&.\- ]{2,80}?\s(?:PRIVATE LIMITED|PVT\.? LTD\.?|LIMITED|LLP))\b")
LEGAL_TITLE_RE = re.compile(r"\b([A-Z][\w&.\-]*(?:\s+[A-Z][\w&.\-]*){0,6}\s+(?:Private Limited|Pvt\.? Ltd\.?|Limited|LLP))\b")
STATUS_RE = re.compile(r"\b(under cirp|under liquidation|liquidated|strike[d]? off|struck off|under process of striking off|"
                       r"dissolved|dormant|amalgamated|converted to llp|active)\b", re.I)
BAD_STATUS = {"under cirp", "under liquidation", "liquidated", "strike off", "striked off", "struck off",
              "under process of striking off", "dissolved", "dormant", "amalgamated"}
INC_RE = re.compile(r"(?:incorporated on|registered on|date of incorporation:?|incorporated in india on)\s*"
                    r"(\d{1,2}\s+[A-Z][a-z]+\s+\d{4}|[A-Z][a-z]+\s+\d{1,2},?\s+\d{4})", re.I)
ADVERSE = re.compile(
    r"\b(fraud\w*|scam|raid(?:ed|s)?|fir\b|arrest\w*|lawsuit|sued|nclt|insolven\w*|cirp|liquidat\w*|winding[- ]up|"
    r"default(?:ed|s)?\b|shut\s?down|shuts? down|clos(?:es|ed|ure) (?:its|operations)|lay-?offs?|laid off|penalt(?:y|ies)|"
    r"fined|gst evasion|tax evasion|enforcement directorate|cheating|money laundering|data breach|fire at|blaze)\b", re.I)
# Invoices, e-way bills, GRNs: third-party paperwork naming the company is strong
# evidence that it operates where the paper says.
BUSINESS_DOC = re.compile(r"\b(invoice|e-?way bill|gstin|consignee|consignor|inward|outward|grn|purchase order|"
                          r"delivery challan|pvt\.?|ltd\.?|private limited|hsn)\b", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+?\d[\d\s-]{8,}\d")
DATE_RE = re.compile(r"\b([A-Z][a-z]{2} \d{1,2}, \d{4})\b")


def scrub(s: str | None) -> str:
    """No contact data in anything we store or show."""
    return PHONE_RE.sub("[phone]", EMAIL_RE.sub("[email]", s or ""))


def host(url: str | None) -> str:
    try:
        return (urlparse(url or "").hostname or "").removeprefix("www.")
    except ValueError:
        return ""


def _redirect(url: str | None) -> bool:
    return "google.com/goto" in (url or "") or host(url) in ("google.com", "bing.com")


def _date(x: dict) -> str | None:
    m = DATE_RE.search(x.get("snippet") or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%b %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _fragments(text: str) -> list[str]:
    return [f.strip() for f in re.split(r"\.\.\.|…|(?<=[.!?;])\s+|\s\|\s", text) if f.strip()]


@dataclass
class Entity:
    legal_name: str | None = None
    cin: str | None = None
    incorporated: str | None = None
    status: str | None = None
    registered_office: str | None = None
    link: str = "name match"            # "website/email domain" | "brand page" | "name match"
    sources: list[dict] = field(default_factory=list)

    @property
    def state(self) -> str | None:
        m = CIN_RE.match(self.cin or "")
        return CIN_STATES.get(m.group(3), m.group(3)) if m else None

    @property
    def year(self) -> int | None:
        if self.incorporated and re.search(r"\d{4}", self.incorporated):
            return int(re.search(r"(\d{4})", self.incorporated).group(1))
        m = CIN_RE.match(self.cin or "")
        return int(m.group(4)) if m else None

    def to_dict(self) -> dict:
        return {"legal_name": self.legal_name, "cin": self.cin, "incorporated": self.incorporated,
                "year": self.year, "registered_state": self.state, "status": self.status,
                "registered_office": self.registered_office, "link": self.link, "sources": self.sources[:4]}


class Public:
    def __init__(self, crust, name: str, domain: str | None, company: dict, max_pdfs: int = 2,
                 prior_entities: list[dict] | None = None, analyse: bool = True, max_articles: int = 4):
        self.crust, self.name, self.domain, self.company = crust, name, (domain or "").lower(), company or {}
        self.max_pdfs = max_pdfs
        self.analyse, self.max_articles = analyse, max_articles
        self.prior = prior_entities or []   # registry entities found on earlier runs of this dossier
        self.checked: list[str] = []
        desc = " ".join(str(x) for x in [(self.company.get("basic_info") or {}).get("description"),
                                         " ".join((self.company.get("taxonomy") or {}).get("categories") or [])] if x)
        stop = {"about", "their", "which", "where", "through", "across", "company", "companies", "business", "businesses",
                "solutions", "services", "provide", "provides", "india"}
        # Words about what the company does, minus its own name: the name alone can't
        # tell "Stockarea the 3PL" from "stockarea" in a fisheries paper.
        stop |= set(norm(name).split()) | set(re.findall(r"[a-z]+", self.domain))
        self.context = {w for w in re.findall(r"[a-z]{6,}", desc.lower()) if w not in stop}

    def _search(self, query: str, **kw) -> tuple[list[dict], str | None]:
        try:
            res, rec = self.crust.web_search(query, **kw) if kw else self.crust.web_search(query)
            self.checked.append(f"Crustdata /web/search/live '{query}'{' ' + str(kw) if kw else ''} ({len(res)} results)")
            return res, rec.retrieved_at
        except Exception as e:
            log.info("public search failed (%s): %s", query, e)
            self.checked.append(f"Crustdata /web/search/live '{query}' (failed)")
            return [], None

    def about_us(self, x: dict, strict: bool = True) -> bool:
        """The result names the company (and, when strict, also what it does, its domain, or
        reads like a business document addressed to it)."""
        blob = f"{x.get('title', '')} {x.get('snippet', '')}"
        if not mentions(blob, self.name):
            return False
        if not strict or (self.domain and self.domain in blob.lower()):
            return True
        if BUSINESS_DOC.search(blob):
            return True
        return not self.context or any(w in blob.lower() for w in self.context)

    # ------------------------------------------------------------------ news
    def news(self) -> list[dict]:
        items = []
        for n in (self.company.get("news") or []):
            items.append({"title": n.get("article_title"), "url": n.get("article_url"), "date": n.get("article_publish_date"),
                          "publisher": n.get("article_publisher_name") or host(n.get("article_url")),
                          "snippet": "", "via": "Crustdata /company/enrich news"})
        res, at = self._search(f'"{self.name}"', sources=["news"])
        for x in res:
            if not self.about_us(x, strict=False):  # a quoted-name news search rarely collides
                continue
            items.append({"title": x.get("title"), "url": x.get("url"), "date": _date(x),
                          "publisher": None if _redirect(x.get("url")) else host(x.get("url")),
                          "snippet": scrub(x.get("snippet")), "via": "Crustdata /web/search/live (news)", "retrieved_at": at})
        seen, out = set(), []
        for it in items:
            k = norm(it.get("title") or "")[:80]
            if k and k not in seen:
                seen.add(k)
                blob = f"{it.get('title', '')} {it.get('snippet', '')}"
                it["kind"] = ("press release (company-published)"
                              if re.search(r"issuewire|prnewswire|prlog|businesswire|einpresswire|press release", blob, re.I)
                              or any(h in (it.get("url") or "") for h in PR_WIRES) else "news")
                out.append(it)
        out.sort(key=lambda i: i.get("date") or "", reverse=True)
        out = out[:12]
        # Full text for the model: fetch direct article links through Crustdata (1 credit each);
        # Google redirect links can't be fetched, so those keep their snippet.
        direct = [n for n in out if n.get("url") and not _redirect(n["url"])][: self.max_articles]
        if direct and self.analyse:
            try:
                pages, _ = self.crust.web_fetch([n["url"] for n in direct])
                self.checked.append(f"Crustdata /web/enrich/live ({len(direct)} articles, {len(pages)} read)")
                from .htmltext import to_text
                by_url = {p.get("url"): to_text(p.get("content") or "") for p in pages}
                for n in direct:
                    body = by_url.get(n["url"])
                    if body and len(body) > len(n.get("snippet") or ""):
                        n["text"] = scrub(body)[:12000]
            except Exception as e:
                self.checked.append(f"article fetch failed ({type(e).__name__})")
        for i, n in enumerate(out):
            n["id"] = f"n{i + 1}"
        return out

    def analyse_news(self, news: list[dict]) -> dict:
        from . import news_ai

        if not (self.analyse and news_ai.available() and news):
            return {"model": None, "error": None if news_ai.available() else "no news-model key set (AWS_BEARER_TOKEN_BEDROCK or NVIDIA_API_KEY)", "items": {}}
        from .cancel import call
        res = call(getattr(self.crust, "cancel", None), news_ai.analyze,  # Stop returns at once
                   [{"id": n["id"], "title": n.get("title"), "date": n.get("date"),
                     "text": n.get("text") or n.get("snippet") or ""} for n in news],
                   self.name, self.domain or None)
        for n in news:
            if n["id"] in res["items"]:
                n["analysis"] = res["items"][n["id"]]
                if n["analysis"]["written_by_company"] and n.get("kind") == "news":
                    n["kind"] = "company post (per analysis)"
        self.checked.append(f"news analysis: {res['model']} ({len(res['items'])}/{len(news)} items"
                            + (f", failed: {res['error']}" if res["error"] else f", {res['seconds']}s") + ")")
        return {k: v for k, v in res.items() if k != "items"} | {"analysed": len(res["items"])}

    # -------------------------------------------------------------- registry
    def registry(self) -> dict:
        # Phrased like a registry listing, so aggregator pages outrank the company's own marketing.
        # Web search is not deterministic: the same query can return registry listings one
        # run and the company's marketing pages the next. Several phrasings + carrying
        # earlier finds forward keeps a found CIN from vanishing on the next run.
        queries = [(f'"{self.name}" private limited CIN incorporation date registered office', {})]
        if self.domain:
            queries += [(f'"{self.domain}" private limited CIN', {}),
                        (self.domain, {"site": "thecompanycheck.com"})]
        ents: dict[str, Entity] = {}
        for q, kw in queries:
            res, at = self._search(q, **kw)
            for x in res:
                self._parse_registry(x, at, ents)
        for p in self.prior:
            key = p.get("cin") or p.get("legal_name")
            if not key:
                continue
            e = ents.get(key) or next((v for v in ents.values() if p.get("legal_name") and v.legal_name == p["legal_name"]), None)
            if e is None:
                e = Entity(legal_name=p.get("legal_name"), cin=p.get("cin"), incorporated=p.get("incorporated"),
                           status=p.get("status"), registered_office=p.get("registered_office"), link=p.get("link", "name match"),
                           sources=[{**s, "carried_over": True} for s in p.get("sources", [])])
                ents[key] = e
            else:
                e.cin = e.cin or p.get("cin")
                e.incorporated = e.incorporated or p.get("incorporated")
                e.status = e.status or p.get("status")
                e.registered_office = e.registered_office or p.get("registered_office")
        entities = sorted(ents.values(), key=lambda e: ({"website/email domain": 0, "brand page": 1}.get(e.link, 2), e.cin is None))
        founded = (self.company.get("basic_info") or {}).get("year_founded")
        # The operating entity is the linked one incorporated when the company says it was founded.
        # A linked entity from another year is a group/sister company: listed, not used for checks.
        linked = [e for e in entities if e.cin and e.link != "name match"]
        primary = next((e for e in linked if founded and e.year == founded), None) \
            or (linked[0] if len(linked) == 1 and not founded else None)
        out = []
        for e in entities:
            d = e.to_dict()
            d["role"] = ("operating entity (used for checks)" if primary is e else
                         "related entity" if e.link != "name match" else "similar name only")
            out.append(d)
        return {"entities": out, "primary": primary.to_dict() if primary else None}

    def _parse_registry(self, x: dict, at: str | None, ents: dict):
        title, snip = x.get("title") or "", x.get("snippet") or ""
        blob = f"{title} . {snip}"
        low = blob.lower()
        if not (mentions(blob, self.name) or (self.domain and self.domain in low)):
            return
        cins = ["".join(m.groups()) for m in CIN_RE.finditer(blob)]
        legal = (LEGAL_RE.findall(title) or LEGAL_TITLE_RE.findall(title) or LEGAL_RE.findall(snip) or LEGAL_TITLE_RE.findall(snip) or [None])[0]
        legal = legal.strip().upper() if legal else None
        if not cins and not legal:
            return
        if self.domain and (f"@{self.domain}" in low or f"website is {self.domain}" in low or self.domain in low):
            link = "website/email domain"
        elif legal and mentions(legal, self.name):
            link = "name match"   # same brand in the legal name: may be a sister or unrelated company
        elif re.search(rf"(entities|entity)\s+associated with\s+{re.escape(self.name.lower())}", low) or mentions(title, self.name):
            link = "brand page"
        else:
            link = "name match"
        key = cins[0] if len(cins) == 1 else (legal or (cins[0] if cins else None))
        if not key:
            return
        # A "related companies" list names many entities: only trust a CIN printed next to the
        # legal name it belongs to; otherwise attach none rather than a neighbour's.
        if len(cins) > 1:
            cins = [c for c in cins if legal and re.search(
                rf"{re.escape(legal[:20])}[^|;]{{0,60}}{c}|{c}[^|;]{{0,60}}{re.escape(legal[:20])}", blob, re.I)]
        elif cins and legal and legal not in blob.upper().split(cins[0])[0][-160:] and legal not in title.upper():
            cins = []  # the lone CIN on the page sits next to some other name
        e = ents.get(key) or next((v for v in ents.values() if legal and v.legal_name == legal), None) or Entity()
        e.cin = e.cin or (cins[0] if cins else None)
        e.legal_name = e.legal_name or legal
        if {"website/email domain": 0, "brand page": 1}.get(link, 2) < {"website/email domain": 0, "brand page": 1}.get(e.link, 2):
            e.link = link
        if m := INC_RE.search(blob):
            e.incorporated = e.incorporated or m.group(1)
        if m := STATUS_RE.search(blob):
            # "Status Under CIRP, NA" is ambiguous (field label vs value): keep the words, let a person confirm.
            e.status = e.status or m.group(1).title()
        if m := re.search(r"registered office is (?:in|at) ([A-Z][^.;]{3,80})", blob):
            e.registered_office = e.registered_office or m.group(1).strip()
        e.sources.append({"url": x.get("url"), "title": title[:120], "snippet": scrub(snip)[:300], "retrieved_at": at,
                          "fetchable": not _redirect(x.get("url"))})
        ents[e.cin or e.legal_name] = e

    # ------------------------------------------------------------- documents
    def documents(self) -> list[dict]:
        res, at = self._search(f'"{self.name}" filetype:pdf')
        res2, _ = self._search(f'"{self.name}" invoice OR "e-way bill" OR GSTIN OR "purchase order"')
        docs, seen = [], set()
        # The brand as a brand: "Stockarea" / "STOCKAREA", not "stockArea" (a software field)
        # or "stockarea" (a fisheries term).
        brand = re.compile(rf"\b({re.escape(self.name)}|{re.escape(self.name.upper())})\b")
        for x in res + res2:
            if not self.about_us(x):
                continue
            blob = f"{x.get('title', '')} {x.get('snippet', '')}"
            if not brand.search(blob) and not (self.domain and self.domain in blob.lower()):
                continue
            u = x.get("url") or x.get("pdf_url")
            is_doc = bool(x.get("pdf_url")) or bool(re.search(r"\.pdf(\?|$)", u or "", re.I)) or bool(BUSINESS_DOC.search(blob))
            key = norm(x.get("title") or "")[:60]
            if CIN_RE.search(blob):  # registry listings belong to the registry section
                continue
            if not is_doc or key in seen:  # an ordinary web page is not a "document"
                continue
            seen.add(key)
            h = host(u)
            own = bool(self.domain) and (h == self.domain or h.endswith("." + self.domain))
            # e.g. app-stockarea.s3...amazonaws.com: the company's own file storage
            brand_host = norm(self.name).replace(" ", "") in h.replace("-", "").replace(".", "")
            snippet = scrub(x.get("snippet"))
            docs.append({"title": x.get("title"), "url": u, "date": _date(x), "snippet": snippet,
                         "publisher": "company-published" if own else
                                      f"company-hosted ({h})" if brand_host else
                                      (h if not _redirect(u) else "third-party (link via search)"),
                         "kind": "business document" if BUSINESS_DOC.search(f"{x.get('title', '')} {snippet}") else "document",
                         "places": places_in(f"{x.get('title', '')} {snippet}"),
                         "retrieved_at": at, "text": None})
        fetched = 0
        for d in docs:
            if fetched >= self.max_pdfs or _redirect(d["url"]) or not re.search(r"\.pdf(\?|$)", d["url"] or "", re.I):
                continue
            from .cancel import call
            text = call(getattr(self.crust, "cancel", None), _download_pdf_text, d["url"])
            if text:
                d["text"] = text[:30000]
                d["places"] = list(dict.fromkeys(d["places"] + places_in(text[:30000])))
                fetched += 1
        return docs

    # ----------------------------------------------------------------- flags
    def flags(self, news: list[dict], reg: dict, docs: list[dict]) -> list[dict]:
        out = []
        names = [self.name] + [e["legal_name"] for e in reg["entities"] if e["legal_name"] and e["link"] != "name match"]
        for e in reg["entities"]:
            if e["link"] == "name match":
                continue  # an unrelated company with a similar name is not a flag
            if e["status"] and e["status"].lower() in BAD_STATUS:
                out.append({"kind": "registry", "severity": "confirm",
                            "text": f"A registry listing shows '{e['status']}' next to {e['legal_name'] or e['cin']}"
                                    f"{' (CIN ' + e['cin'] + ')' if e['cin'] else ''}, linked to {self.name} by {e['link']}. "
                                    f"Search snippets can mislabel fields, so confirm on MCA21 before relying on it.",
                            "source": (e["sources"] or [{}])[0],
                            "request": f"MCA21 master data for {e['cin'] or e['legal_name']} and written confirmation of any "
                                       f"IBC/NCLT proceedings (CIRP, liquidation) involving the company"})
        for item in news:
            a = item.get("analysis")
            if not a:
                continue
            if not a["about_target"]:
                continue
            for c in a["concerns"]:
                out.append({"kind": "news analysis", "severity": "confirm",
                            "text": f"{c['issue']}: “{item.get('title')}”{' (' + item['date'] + ')' if item.get('date') else ''}.",
                            "source": {"url": item.get("url"), "title": item.get("title"), "snippet": c["quote"]},
                            "request": f"Management's written explanation of: {c['issue']} (re “{item.get('title')}”), with supporting documents"})
        for item in [n for n in news if not n.get("analysis")] + docs:  # keyword scan where the model didn't read it
            blob = f"{item.get('title') or ''}. {item.get('snippet') or ''}"
            for frag in _fragments(blob):
                m = ADVERSE.search(frag)
                if m and any(mentions(frag, n) for n in names if n):
                    out.append({"kind": "adverse media", "severity": "confirm",
                                "text": f"'{m.group(1)}' appears next to {self.name} in “{item.get('title')}”"
                                        f"{' (' + item['date'] + ')' if item.get('date') else ''}.",
                                "source": {"url": item.get("url"), "title": item.get("title"), "snippet": frag[:300]},
                                "request": f"Management's written explanation of “{item.get('title')}”, with supporting documents"})
                    break
        return out

    def gather(self) -> dict:
        news, reg, docs = self.news(), self.registry(), self.documents()
        meta = self.analyse_news(news)
        return {"news": news, "registry": reg, "documents": docs, "flags": self.flags(news, reg, docs),
                "news_analysis": meta, "sources_checked": self.checked}


def places_in(text: str) -> list[str]:
    """Known Indian cities named in a document (canonical spelling)."""
    from .checkers import CANON, CITY_STATE

    found = []
    for city in CITY_STATE:
        if city in ("guindy",):
            continue
        if mentions(text, city):
            c = CANON.get(city, city).title()
            if c not in found:
                found.append(c)
    return found


def _download_pdf_text(url: str) -> str | None:
    """Fetch a public PDF (size-capped, never executed) and return its text."""
    from .ingest import parse_pdf

    try:
        with httpx.stream("GET", url, timeout=20, follow_redirects=True,
                          headers={"user-agent": "SecondLook/0.1 (document reader)"}) as r:
            if r.status_code != 200 or "html" in r.headers.get("content-type", ""):
                return None
            buf = io.BytesIO()
            for chunk in r.iter_bytes():
                buf.write(chunk)
                if buf.tell() > 8 * 1024 * 1024:
                    return None
        data = buf.getvalue()
        if not data.startswith(b"%PDF-"):
            return None
        return parse_pdf(data, url, ocr=False).text or None  # public documents: text layer only
    except Exception as e:
        log.info("pdf download failed %s: %s", url, e)
        return None
