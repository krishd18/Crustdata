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

    import pytest
    with pytest.raises(engine.NeedsPerson) as e:
        engine.resolve(FakeCrust(), "Sri Murugan Logistics", None, None)
    assert len(e.value.candidates) == 2
    assert engine.resolve(FakeCrust(), "Sri Murugan Logistics", None, "Madurai")["crustdata_company_id"] == 2


def test_rule_extractor_finds_core_claims():
    text = ("Chennai-registered, est. 2014. 250 employees. +40% YoY. 6 warehouses in TN. Backed by X Ventures. "
            "Ex-Delhivery leadership. We serve Amazon. Product live since 2019. Cuts damage 40%. "
            "₹100 Cr revenue by 2028.\nWhy did they close Hosur?")
    types = {c["type"] for c in _extract_rules(text)}
    assert types >= {"identity", "workforce", "growth", "footprint", "investors", "people", "customers",
                     "dates", "efficacy", "forward_looking", "premise"}
