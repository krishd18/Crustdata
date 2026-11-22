"""An offline stand-in for the Crustdata API.

Why this exists rather than a mocking library: the demo has to be rehearsable
without a network or credits, and the kill-and-restart drill is worth running
twenty times before doing it on stage. It also makes the four verdicts
reproducible, so a change that quietly turns a refusal into an answer fails a
test instead of surprising someone in the finals.

The pages below are invented, and their domains are reserved example domains.
Nothing here may be cited as real: it exists to exercise control flow.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .crustdata import FetchedPage, SearchResult


def _recent(days_ago: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days_ago)
    ).date().isoformat()


_PAGES: dict[str, tuple[str, str]] = {
    # Two independent publishers state the Guwahati hiring claim, both dated.
    "https://logisticsweekly.example.com/guwahati-hiring": (
        "Delhivery opens Guwahati roles",
        f"""<html><head>
        <meta property="article:published_time" content="{_recent(40)}T09:00:00Z">
        </head><body>
        <p>Freight volumes in the north-east continue to grow.</p>
        <p>Delhivery started hiring in Guwahati in September 2026, posting
        warehouse and last-mile roles at its new facility in the city.</p>
        <p>Other operators have not announced similar plans.</p>
        </body></html>""",
    ),
    "https://northeastcargo.example.net/delhivery-guwahati": (
        "Delhivery adds Guwahati capacity",
        f"""<html><head><script type="application/ld+json">
        {{"@type":"NewsArticle","datePublished":"{_recent(35)}"}}
        </script></head><body>
        <p>Delhivery started hiring in Guwahati in September 2026 for its
        expanded sorting centre, according to listings seen by this
        publication.</p>
        </body></html>""",
    ),
    # Topical but does not state the claim: the entailment check must reject it.
    "https://freightnews.example.org/northeast-overview": (
        "The north-east logistics market",
        """<html><body>
        <p>Guwahati has become a hub for regional distribution, with several
        national operators maintaining a presence in the city.</p>
        <p>Delhivery, Blue Dart and others compete across the north-east.</p>
        </body></html>""",
    ),
    # Undated page: states the claim but cannot support a dated question.
    "https://tradejournal.example.com/cold-chain-expansion": (
        "Cold chain moves",
        """<html><body>
        <p>Snowman Logistics is expanding cold chain capacity with new reefer
        capacity in western India.</p>
        </body></html>""",
    ),
}

_RESULTS: dict[str, list[str]] = {
    "guwahati": [
        "https://logisticsweekly.example.com/guwahati-hiring",
        "https://northeastcargo.example.net/delhivery-guwahati",
        "https://freightnews.example.org/northeast-overview",
    ],
    "cold chain": ["https://tradejournal.example.com/cold-chain-expansion"],
    "reefer": ["https://tradejournal.example.com/cold-chain-expansion"],
}


class FakeCrustdataClient:
    """Matches the surface of ``CrustdataClient`` that the desk uses."""

    def __init__(self, ledger=None) -> None:
        self.ledger = ledger
        self.searches: list[str] = []
        self.fetches: list[str] = []

    def _charge(self, endpoint: str, credits: float) -> None:
        if self.ledger is not None:
            self.ledger.record(endpoint, None, latency_ms=10.0, credits=credits)

    def search_web(self, query, *, sources=("web", "news"), location="IN",
                   site=None, start_date=None, end_date=None, page=1):
        self.searches.append(query)
        self._charge("/web/search/live", float(page))
        urls: list[str] = []
        low = query.lower()
        for key, found in _RESULTS.items():
            if key in low:
                urls.extend(found)
        results = [
            SearchResult(
                source="news",
                title=_PAGES[u][0],
                url=u,
                snippet=_PAGES[u][0],
                position=i + 1,
            )
            for i, u in enumerate(dict.fromkeys(urls))
        ]
        window = {
            "start_date": None,
            "end_date": None,
            "response_timestamp_ms": 0,
            "query": query,
            "sources": list(sources),
        }
        return results, window

    def fetch_pages(self, urls):
        wanted = [u for u in urls if u][:10]
        self.fetches.extend(wanted)
        self._charge("/web/enrich/live", float(len(wanted)))
        pages, failed = [], []
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for u in wanted:
            if u in _PAGES:
                title, html = _PAGES[u]
                pages.append(
                    FetchedPage(url=u, title=title, content=html, retrieved_at=now)
                )
            else:
                failed.append(u)
        return pages, failed

    def identify_company(self, name_or_domain):
        self._charge("/company/identify", 1.0)
        return []

    def enrich_company(self, **kwargs):
        self._charge("/company/enrich", 1.0)
        return {}

    def search_companies(self, filters, limit=10):
        self._charge("/company/search", 1.0)
        return {"results": []}

    def search_jobs(self, filters, limit=25):
        self._charge("/job/search", 1.0)
        return {"results": []}

    def search_people(self, filters, limit=10):
        self._charge("/person/search", 1.0)
        return {"results": []}


DEMO_QUESTIONS = [
    # Expect: answered -- two independent dated publishers state it.
    "Did Delhivery start hiring in Guwahati since September 2026?",
    # Expect: false_premise -- nothing states the exit happened.
    "Why did Mahindra Logistics exit Kolkata?",
    # Expect: ambiguous_entity -- group or arm, the question does not say.
    "How many people does Mahindra employ in logistics?",
    # Expect: cannot_verify -- the only source is undated.
    "Is Snowman Logistics expanding cold chain capacity this quarter?",
]
