"""Public record (news, registry, documents), using snippets seen on a live Stockarea run."""
from app.checkers import check
from app.crust import CallRecord
from app.models import Claim
from app.public import Public
from tests.test_checkers import rec

REG_NAME = [
    {"title": "STOCKAREA ASSETS PRIVATE LIMITED", "url": "https://www.google.com/goto?url=x1",
     "snippet": "STOCKAREA ASSETS PRIVATE LIMITED (CIN: U77100TN2026PTC190679) is a Private company incorporated on 11 Mar 2026."},
    {"title": "Stockarea - 2026 Company Profile & Team", "url": "https://tracxn.com/d/companies/stockarea/__0YIR",
     "snippet": "Oct 6, 2026 — Legal entities associated with Stockarea ; CIN: U74999TN2019PTC165990 ; Location: India ; "
                "Current Status: Active ; Date of Incorporation: May 24, 2019"},
    {"title": "Interaction Between Stock Area, Stock Abundance", "url": "https://journal.example/fish.pdf",
     "snippet": "by GH Winters · 1985 — Interaction between stockarea, stock abundance, and catchability coefficient."},
]
REG_DOMAIN = [
    {"title": "MEINIGAR TECHNOLOGIES PRIVATE LIMITED", "url": "https://www.google.com/goto?url=x2",
     "snippet": "Status Under CIRP, NA, Filing Status For Last 2 Years ; Email ID, legal@stockarea.io, Website ; Address, Kuppu Arcade, Chennai"},
    {"title": "Meinigar Technologies Private Limited - Company Profile", "url": "https://www.google.com/goto?url=x3",
     "snippet": "Meinigar Technologies Private Limited's registered office is in Chennai, Tamil Nadu. Its website is stockarea.io. "
                "Call +91 98731 44145"},
]
NEWS = [
    {"title": "Renovate your Supply Chain with Stockarea.", "url": "https://www.google.com/goto?url=n1",
     "snippet": "Mumbai, Maharashtra Apr 18, 2021 (Issuewire.com) - Stockarea, one of the biggest third-party logistics partner in India"},
    {"title": "How Nigerian businesses can benefit from On-demand Warehousing", "url": "https://news.example/ng",
     "snippet": "By Henry Uche. Mr Ayo Olunuga is a logistics professional."},
    {"title": "GST officials raid Stockarea warehouse in Chennai", "url": "https://news.example/raid",
     "snippet": "Nov 2, 2026 — Officials raided a Stockarea warehousing facility over alleged input credit claims."},
]
DOCS = [
    {"title": "e-Way Bill", "url": "https://www.google.com/goto?url=d1",
     "snippet": "Feb 14, 2026 — 11/1A/82 STOCKAREA W769 RING ROAD 302026. JAIPUR, RAJASTHAN, 302026. 3- Goods Details."},
    {"title": "MON 3507", "url": "https://www.google.com/goto?url=d2",
     "snippet": "Nov 4, 2026 — STOCKAREA W719, NO 46/6, BUDIHAL VILLAGE. NELAMANGALA TALUK, BANGALORE KARNATAKA. Description of Goods. HSN"},
    {"title": "Interaction Between Stock Area", "url": "https://journal.example/fish.pdf",
     "snippet": "Interaction between stockarea, stock abundance and catchability."},
    {"title": "How to Integrate Receipts with SAP Customer Checkout", "url": "https://sap.example/x.pdf",
     "snippet": "stockArea. The warehouse that is assigned to the sales item. taxAmount."},
]


class FakeCrust:
    def web_search(self, q, **kw):
        if kw.get("sources") == ["news"]:
            res = NEWS
        elif "filetype:pdf" in q:
            res = DOCS
        elif "invoice" in q:  # the paperwork query: here it re-finds a registry page and a blog page
            res = [REG_NAME[0], {"title": "Supply Chain - Logistics Brew", "url": "https://stockarea.io/blogs/x",
                                 "snippet": "Stockarea enables decentralised inventory. By Stockarea"}]
        elif "stockarea.io" in q:
            res = REG_DOMAIN
        else:
            res = REG_NAME
        return res, CallRecord("/web/search/live", 1, "2026-11-22T00:00:00Z", 1, 200)


def gather():
    company = {"basic_info": {"year_founded": 2019, "description": "Stockarea runs a warehousing and fulfilment network"},
               "news": []}
    return Public(FakeCrust(), "Stockarea", "stockarea.io", company, max_pdfs=0, analyse=False).gather()


def test_registry_entities_links_and_primary():
    reg = gather()["registry"]
    by_cin = {e["cin"]: e for e in reg["entities"] if e["cin"]}
    assert by_cin["U74999TN2019PTC165990"]["registered_state"] == "Tamil Nadu"
    assert by_cin["U74999TN2019PTC165990"]["year"] == 2019
    assert by_cin["U77100TN2026PTC190679"]["link"] == "name match"        # a sister/unrelated entity, not the target
    meinigar = next(e for e in reg["entities"] if (e["legal_name"] or "").startswith("MEINIGAR"))
    assert meinigar["link"] == "website/email domain"
    assert reg["primary"]["cin"] == "U74999TN2019PTC165990"
    roles = {e["cin"]: e["role"] for e in reg["entities"] if e["cin"]}
    assert roles["U74999TN2019PTC165990"].startswith("operating entity")
    assert roles["U77100TN2026PTC190679"] == "similar name only"


def test_linked_entity_from_another_year_is_related_not_primary():
    # live run: a 2026 entity shared the company's domain; the company was founded in 2019
    class C2(FakeCrust):
        def web_search(self, q, **kw):
            if "stockarea.io" in q:
                return ([{"title": "STOCKAREA ASSETS PRIVATE LIMITED", "url": "https://www.google.com/goto?url=z",
                          "snippet": "STOCKAREA ASSETS PRIVATE LIMITED (CIN: U77100TN2026PTC190679) incorporated on 11 Mar 2026. "
                                     "Email legal@stockarea.io"},
                         {"title": "MEINIGAR TECHNOLOGIES PRIVATE LIMITED", "url": "https://www.google.com/goto?url=y",
                          "snippet": "Related: MUDIVILI FLEET PRIVATE LIMITED. CIN: U49231TN2023PTC161466. STOCKAREA ASSETS PRIVATE LIMITED. "
                                     "CIN: U77100TN2026PTC190679. Website stockarea.io"}],
                        CallRecord("/web/search/live", 1, "2026-11-22T00:00:00Z", 1, 200))
            if "filetype" in q or "invoice" in q or kw:
                return [], CallRecord("/web/search/live", 1, "2026-11-22T00:00:00Z", 1, 200)
            return [], CallRecord("/web/search/live", 1, "2026-11-22T00:00:00Z", 1, 200)

    company = {"basic_info": {"year_founded": 2019, "description": "warehousing network"}, "news": []}
    reg = Public(C2(), "Stockarea", "stockarea.io", company, max_pdfs=0).gather()["registry"]
    assert reg["primary"] is None
    meinigar = next(e for e in reg["entities"] if (e["legal_name"] or "").startswith("MEINIGAR"))
    assert meinigar["cin"] is None              # the CINs on its "related companies" list are not its own
    assets = next(e for e in reg["entities"] if e["cin"] == "U77100TN2026PTC190679")
    assert assets["role"] == "related entity"
    assert not any("stock abundance" in (s["snippet"] or "") for e in reg["entities"] for s in e["sources"])


def test_registry_find_survives_a_run_where_search_misses_it():
    class Empty(FakeCrust):
        def web_search(self, q, **kw):
            return [], CallRecord("/web/search/live", 1, "2026-11-23T00:00:00Z", 1, 200)

    first = gather()["registry"]["entities"]
    company = {"basic_info": {"year_founded": 2019, "description": "warehousing network"}, "news": []}
    reg = Public(Empty(), "Stockarea", "stockarea.io", company, max_pdfs=0, prior_entities=first).gather()["registry"]
    assert reg["primary"]["cin"] == "U74999TN2019PTC165990"
    assert reg["primary"]["sources"][0]["carried_over"] is True


def test_contact_details_never_stored():
    reg = gather()["registry"]
    blob = str(reg)
    assert "legal@stockarea.io" not in blob and "98731" not in blob


def test_ambiguous_registry_status_is_a_confirm_flag_not_a_verdict():
    flags = gather()["flags"]
    reg = [f for f in flags if f["kind"] == "registry"]
    assert len(reg) == 1 and "MEINIGAR" in reg[0]["text"] and reg[0]["severity"] == "confirm"
    assert "confirm on MCA21" in reg[0]["text"] and "IBC/NCLT" in reg[0]["request"]


def test_news_filtering_press_releases_and_adverse_media():
    out = gather()
    titles = [n["title"] for n in out["news"]]
    assert not any("Nigerian" in t for t in titles)
    kinds = {n["title"]: n["kind"] for n in out["news"]}
    assert kinds["Renovate your Supply Chain with Stockarea."].startswith("press release")
    adverse = [f for f in out["flags"] if f["kind"] == "adverse media"]
    assert len(adverse) == 1 and "raid" in adverse[0]["text"].lower()


def test_documents_keep_business_paperwork_and_drop_name_collisions():
    docs = gather()["documents"]
    assert [d["title"] for d in docs] == ["e-Way Bill", "MON 3507"]
    assert docs[0]["places"] == ["Jaipur"] and "Bengaluru" in docs[1]["places"]


def test_documents_feed_footprint_and_premise():
    r = rec()
    r.documents = gather()["documents"]
    f = check(Claim(id="5", text="30+ cities", type="footprint", metric="cities", number=30), r)
    assert "jaipur" in f.evidence[0].value
    # a dated invoice in Bengaluru 18 days ago is activity there, even with no job posts
    r.jobs = []
    p = check(Claim(id="6", text="Why did they exit Bengaluru?", type="premise", place="Bengaluru"), r)
    assert p.verdict == "false premise" and "document" in p.reason


def test_registry_feeds_identity_checks():
    r = rec()
    r.registry = {"legal_name": "ACME WAREHOUSING PRIVATE LIMITED", "cin": "U74999TN2019PTC165990", "year": 2019,
                  "registered_state": "Tamil Nadu", "incorporated": "May 24, 2019",
                  "sources": [{"url": "https://tracxn.com/x", "retrieved_at": "2026-11-22T00:00:00Z", "fetchable": True}]}
    f = check(Claim(id="1", text="est. 2014", type="identity", metric="founded_year", number=2014, year=2014), r)
    assert f.verdict == "contradicted" and "registry says incorporated 2019" in f.reason
    assert any("U74999TN2019PTC165990" in e.value for e in f.evidence)
    assert check(Claim(id="2", text="Pune-registered", type="identity", place="Pune"), r).verdict == "contradicted"
    assert check(Claim(id="3", text="Chennai-registered", type="identity", place="Chennai"), r).verdict == "consistent"
    assert check(Claim(id="4", text="live since 2017", type="dates", year=2017), r).verdict == "contradicted"
