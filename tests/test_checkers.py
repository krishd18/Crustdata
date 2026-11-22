"""The corrected test cases from the spec, run offline against fixed records."""
from datetime import datetime, timezone

from app.checkers import Record, check
from app.extract import _extract_rules
from app.models import Claim
from app import engine

NOW = datetime(2026, 11, 22, tzinfo=timezone.utc)


def rec(**over):
    company = {
        "basic_info": {"name": "Acme Warehousing", "year_founded": 2019, "employee_count_range": "51-200"},
        "headcount": {"total": 140, "growth_percent": {"yoy": 28.6}, "by_region_absolute": {"Hosur": 9}},
        "hiring": {"openings_growth_percent": None},
        "funding": {"investors": None},
        "news": [],
        "locations": {
            "headquarters": "Guindy Industrial Estate, Ekkaduthangal, Tamil Nādu, India",
            "city": "Guindy", "state": "Tamil Nādu",
            "all_office_addresses": [
                "Acme W1, Sriperumbudur, Tamil Nadu, 602105, IN",
                "Acme W2, Hosur, Tamil Nadu, 635109, IN",
                "Acme W3, Coimbatore, Tamil Nadu, 641032, IN",
                "Acme W4, Nelamangala, Bangalore, Karnataka, 562123, IN",
            ],
        },
        "people": {"founders": [{
            "crustdata_person_id": 1,
            "basic_profile": {"name": "Asha Rao", "current_title": "CEO"},
            "experience": {"employment_details": {"current": [{"employer_name": "Acme Warehousing"}],
                                                  "past": [{"employer_name": "Delhivery", "employee_title": "VP Operations",
                                                            "employee_start_date": "2015-01-01", "employee_end_date": "2019-02-01"}]}},
        }]},
    }
    company.update(over.pop("company", {}))
    jobs = over.pop("jobs", [
        {"job_details": {"title": "Warehouse Supervisor - Hosur", "url": "https://example.com/j/1"},
         "location": {"raw": "Hosur, Tamil Nadu, India", "city": "Hosur", "state": "Tamil Nadu"},
         "metadata": {"date_added": "2026-11-04T00:00:00"}},
    ])
    return Record(name="Acme Warehousing", domain="acme.in", company=company, retrieved_at="2026-11-22T00:00:00Z",
                  jobs=jobs, jobs_total=len(jobs), today=NOW, **over)


def C(type_, **kw):
    return Claim(id="t", text=kw.pop("text", type_), type=type_, **kw)


def test_workforce_claim_below_record_is_contradicted():
    f = check(C("workforce", metric="employees", number=60), rec())
    assert f.verdict == "contradicted" and "140" in f.reason


def test_workforce_claim_above_record_is_consistent_and_asks_for_epfo():
    f = check(C("workforce", metric="employees", number=250), rec())
    assert f.verdict == "consistent" and not f.final
    assert "EPFO" in f.request


def test_investor_with_no_record_cannot_verify_and_lists_sources():
    f = check(C("investors", entity="Sequoia"), rec())     # no crust client → no web hits
    assert f.verdict == "cannot verify"
    assert any("funding.investors" in s for s in f.sources_checked)
    assert any("news" in s for s in f.sources_checked)


def test_premise_with_recent_job_posts_is_false():
    f = check(C("premise", text="Why did they close Hosur?", place="Hosur", event="closed"), rec())
    assert f.verdict == "false premise"
    assert "04 Nov 2026" in f.evidence[0].value


def test_premise_without_recent_posts_is_only_unsupported():
    old = [{"job_details": {"title": "x"}, "location": {"raw": "Hosur, Tamil Nadu"}, "metadata": {"date_added": "2025-01-01T00:00:00"}}]
    f = check(C("premise", text="Why did they close Hosur?", place="Hosur"), rec(jobs=old))
    assert f.verdict == "unsupported premise"


def test_footprint_partial_and_verified():
    assert check(C("footprint", metric="warehouses", number=6, place="Tamil Nadu"), rec()).verdict == "partial"
    assert check(C("footprint", metric="warehouses", number=3, place="Tamil Nadu"), rec()).verdict == "verified"


def test_identity_year_and_city():
    assert check(C("identity", metric="founded_year", number=2014, year=2014), rec()).verdict == "contradicted"
    assert check(C("identity", metric="founded_year", number=2019, year=2019), rec()).verdict == "verified"
    # HQ string is "Guindy … Tamil Nādu": Chennai isn't named, same state → consistent, never contradicted
    assert check(C("identity", place="Chennai"), rec()).verdict == "consistent"
    assert check(C("identity", place="Pune"), rec()).verdict == "contradicted"


def test_people_verified_from_history():
    f = check(C("people", entity="Delhivery"), rec())
    assert f.verdict == "verified" and "Asha Rao" in f.reason


def test_growth_direction():
    assert check(C("growth", metric="yoy_growth_pct", number=40), rec()).verdict == "consistent"
    r = rec(company={"headcount": {"total": 140, "growth_percent": {"yoy": -20}}})
    assert check(C("growth", metric="yoy_growth_pct", number=40), r).verdict == "contradicted"


def test_dates_before_founding_is_contradicted():
    assert check(C("dates", year=2015), rec()).verdict == "contradicted"
    assert check(C("dates", year=2021), rec(archive_first="20190704000000")).verdict == "verified"


def test_forward_looking_is_projection():
    assert check(C("forward_looking", text="₹100 Cr by 2028"), rec()).verdict == "projection"


def test_ambiguous_name_is_held_for_a_person():
    class FakeCrust:
        def identify(self, domain=None, name=None):
            mk = lambda i, d: {"confidence_score": 0.9, "company_data": {"crustdata_company_id": i, "basic_info": {
                "name": "Sri Murugan Logistics", "primary_domain": d, "year_founded": 2010}}}
            return ([mk(1, "smlchennai.in"), mk(2, "smlmadurai.in")], None) if name else ([], None)

        def enrich_company(self, cid, fields):
            city = {1: "Chennai", 2: "Madurai"}[cid]
            return {"locations": {"headquarters": f"{city}, Tamil Nadu"}}, None

    # a non-domain in the domain box ("semiconductor") falls back to the name
    assert engine.valid_domain("semiconductor") is None and engine.valid_domain("stockarea.io") == "stockarea.io"
    assert engine.resolve(FakeCrust(), "Sri Murugan Logistics", "semiconductor", "Madurai")["crustdata_company_id"] == 2

    import pytest
    with pytest.raises(engine.NeedsPerson) as e:
        engine.resolve(FakeCrust(), "Sri Murugan Logistics", None, None)
    assert len(e.value.candidates) == 2
    assert engine.resolve(FakeCrust(), "Sri Murugan Logistics", None, "Madurai")["crustdata_company_id"] == 2


class FakeSearch:
    """Stands in for Crust.web_search with canned results."""
    def __init__(self, results):
        self.results = results

    def web_search(self, q):
        from app.crust import CallRecord
        return self.results, CallRecord("/web/search/live", 1, "2026-11-22T00:00:00Z", 1, 200)


def leader_rec(results):
    r = rec()
    r.company["basic_info"]["professional_network_url"] = "https://www.linkedin.com/company/acme-warehousing"
    r.company["people"]["founders"][0]["social_handles"] = {
        "professional_network_identifier": {"profile_url": "https://www.linkedin.com/in/asha-rao"}}
    r.crust = FakeSearch(results)
    return r


# The three cases below are the live false positives seen on the first real run.
def test_leaders_own_post_is_self_reported_not_verified():
    r = leader_rec([{"title": "Acme Warehousing network", "snippet": "Acme Warehousing ships for Amazon, Flipkart",
                     "url": "https://www.linkedin.com/posts/asha-rao_acme-logistics-activity-71887851"}])
    f = check(C("customers", entity="Amazon"), r)
    assert f.verdict == "self-reported"


def test_ex_employer_on_a_profile_is_not_a_customer():
    r = leader_rec([{"title": "Ops Manager", "snippet": "Operations Manager @Acme Warehousing | Ex - Flipkart",
                     "url": "https://in.linkedin.com/in/someone-916b29288"}])
    assert check(C("customers", entity="Flipkart"), r).verdict == "cannot verify"


def test_unrelated_percentage_on_third_party_social_does_not_support_efficacy():
    r = leader_rec([{"title": "post", "snippet": "#AcmeWarehousing Acme Warehousing approach drives 40% faster warehouse operations",
                     "url": "https://www.facebook.com/Other.Logistics/posts/123"}])
    f = check(C("efficacy", metric="efficacy_pct", number=40, entity="inventory damage"), r)
    assert f.verdict == "self-reported"


def test_co_mention_and_press_release_do_not_verify_a_customer():
    # live hit 1: both names on a page, no relationship stated
    r = leader_rec([{"title": "Warehousing guide", "snippet": "An e-commerce giant like Amazon is adding centres. Acme Warehousing is your single partner",
                     "url": "https://www.google.com/books/x"}])
    assert check(C("customers", entity="Amazon"), r).verdict == "cannot verify"
    # live hit 2: the company's own press release on a PR wire
    r = leader_rec([{"title": "Acme Warehousing signs Flipkart", "snippet": "Acme Warehousing has signed Flipkart as a client",
                     "url": "https://www.pr.com/press-release/1"}])
    assert check(C("customers", entity="Flipkart"), r).verdict == "self-reported"


def test_names_in_different_snippet_fragments_or_competitor_lists_do_not_verify():
    # live hit: a scraped startup list; the two names sit in separate "..." fragments
    r = leader_rec([{"title": "900 logtech startups list", "url": "https://example-docs.com/list",
                     "snippet": "acme.in Acme Warehousing Early Stage Series A ... an intelligent logistics world such as Sequoia Capital modular software"}])
    assert check(C("investors", entity="Sequoia Capital"), r).verdict == "cannot verify"
    # live hit: a directory's competitor page; "customer-centric" is not "customer"
    r = leader_rec([{"title": "Acme Warehousing competitors", "url": "https://directory.example/acme",
                     "snippet": "View Acme Warehousing's top competitors like Amazon, Easyship. Amazon strives to be Earth's most customer-centric company"}])
    assert check(C("customers", entity="Amazon"), r).verdict == "cannot verify"
    # a real funding report still verifies
    r = leader_rec([{"title": "Acme Warehousing raises Series A", "url": "https://inc42.com/a",
                     "snippet": "Acme Warehousing has raised $10 Mn in a round led by Sequoia Capital"}])
    assert check(C("investors", entity="Sequoia Capital"), r).verdict == "verified"


def test_cities_count_merges_aliases():
    r = rec(jobs=[{"job_details": {}, "location": {"city": c, "raw": c}, "metadata": {}} for c in ("Bangalore", "Bengaluru", "Gurgaon", "Gurugram")])
    f = check(C("footprint", metric="cities", number=30), r)
    assert "bangalore" not in f.evidence[0].value and "gurgaon" not in f.evidence[0].value


def test_independent_news_still_verifies():
    r = leader_rec([{"title": "Amazon picks Acme Warehousing", "snippet": "Amazon has signed Acme Warehousing for Chennai",
                     "url": "https://economictimes.indiatimes.com/x"}])
    assert check(C("customers", entity="Amazon"), r).verdict == "verified"
    r = leader_rec([{"title": "Case study", "snippet": "Acme Warehousing cut damage by 40% for a client",
                     "url": "https://supplychaindigital.com/y"}])
    assert check(C("efficacy", metric="efficacy_pct", number=40, entity="inventory damage"), r).verdict == "independently supported"


def test_website_html_is_read_as_text_without_ui_noise():
    from app.extract import extract
    html = ("<html><head><script>var x = a ? b : c; go(dx < 0 ?</script><style>.a{}</style></head><body>"
            "<nav>Who We Serve Manufacturers Distributors</nav><div><b>5</b><span>cities</span></div>"
            "<p>We store stock in every tier 1 city and most tier 2 cities across India.</p>"
            "<p>Our network of 120 warehouses across India serves 500 brands.</p></body></html>")
    cl = extract(html, company="Acme", kind="website")
    assert [(c.type, c.metric, c.number) for c in cl] == [("footprint", "warehouses", 120.0)]


def test_a_persons_bio_year_is_not_a_founding_claim():
    # live hit on semilit.in: an advisor's bio was read as "company founded 1981"
    from app.extract import _extract_rules
    got = _extract_rules("He has been a faculty member at the Indian Institute of Technology Madras since 1981.", kind="website")
    assert not [c for c in got if c["type"] in ("identity", "dates")]
    assert _extract_rules("Acme was founded in 2016 in Pune.")[0]["year"] == 2016


def test_rule_extractor_finds_core_claims():
    text = ("Chennai-registered, est. 2014. 250 employees. +40% YoY. 6 warehouses in TN. Backed by X Ventures. "
            "Ex-Delhivery leadership. We serve Amazon. Product live since 2019. Cuts damage 40%. "
            "₹100 Cr revenue by 2028.\nWhy did they close Hosur?")
    types = {c["type"] for c in _extract_rules(text)}
    assert types >= {"identity", "workforce", "growth", "footprint", "investors", "people", "customers",
                     "dates", "efficacy", "forward_looking", "premise"}
