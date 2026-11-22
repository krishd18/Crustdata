"""Thesis -> Crustdata search parameters."""
import json

from app import thesis_ai


def filters_of(thesis, floor=10):
    p = thesis_ai.normalise(thesis_ai.rule_parse(thesis))
    f, applied = thesis_ai.to_filters(p, floor)
    return p, f, {a["field"]: a for a in applied}


def test_rules_read_the_users_actual_theses():
    p, f, a = filters_of("Acquirable logistic Companies with $5 Million + revenue in MH ")
    assert p["what"] == "logistic companies" and p["locations"] == ["Maharashtra"]
    assert a["revenue.estimated.lower_bound_usd"]["value"] == 5_000_000
    assert a["revenue.acquisition_status"]["value"] == ""
    assert "Public Company" in a["basic_info.company_type"]["value"]

    # "in MH logistics": the place comes first, the sector word goes back into the query
    p, f, a = filters_of("Companies with $50 Million + revenue in MH logistics")
    assert p["locations"] == ["Maharashtra"] and "logistics" in p["what"]
    assert a["revenue.estimated.lower_bound_usd"]["value"] == 50_000_000

    p, f, a = filters_of("warehousing and fulfilment operators in TN/KA")
    assert p["locations"] == ["Tamil Nadu", "Karnataka"] and "revenue.estimated.lower_bound_usd" not in a


def test_rupee_amounts_are_converted_at_the_configured_rate(monkeypatch):
    monkeypatch.setenv("USD_INR", "80")
    p, f, a = filters_of("3PL operators with revenue above ₹50 crore in Karnataka")
    assert a["revenue.estimated.lower_bound_usd"]["value"] == 6_250_000   # 50 cr = 500M INR / 80


def test_model_output_is_validated_not_trusted():
    raw = {"what": "cold-chain logistics companies",
           "locations": [{"name": "MH", "kind": "state"}, {"name": "India", "kind": "country"}],
           "revenue_min": {"amount": 10, "unit": "million", "currency": "USD"},
           "revenue_max": {"amount": "lots", "unit": "million"},                 # junk -> dropped
           "headcount_min": 50, "headcount_max": -3,                             # out of range -> dropped
           "last_round_types": ["series_a", "series_z"],                          # unknown round -> dropped
           "founded_after": 2015, "acquirable": True, "unsupported": ["with good culture"]}
    p = thesis_ai.normalise(raw)
    assert p["locations"] == ["Maharashtra"] and p["country"] == "IND"
    assert p["revenue_min_usd"] == 10_000_000 and p["revenue_max_usd"] is None
    assert p["headcount_min"] == 50 and p["headcount_max"] is None
    assert p["last_round_types"] == ["series_a"] and p["exclude_public"] is True
    f, applied = thesis_ai.to_filters(p, 10)
    fields = [x["field"] for x in applied]
    assert fields.count("headcount.total") == 1                                   # the thesis's 50 beats the UI floor
    assert next(x for x in applied if x["field"] == "headcount.total")["value"] == 50
    assert "basic_info.year_founded" in fields and p["unsupported"] == ["with good culture"]


def test_interpret_uses_the_model_and_falls_back_to_rules():
    def good(prompt, **kw):
        assert "Acquirable" in prompt
        return json.dumps({"what": "logistics companies", "locations": [{"name": "Maharashtra", "kind": "state"}],
                           "revenue_min": {"amount": 5, "unit": "million", "currency": "USD"}, "acquirable": True}), {}, "qwen (Mantle)"
    it = thesis_ai.interpret("Acquirable logistic Companies with $5 Million + revenue in MH", llm=good)
    assert it["parser"] == "qwen (Mantle)" and it["params"]["revenue_min_usd"] == 5_000_000

    def bad(prompt, **kw):
        return "sorry, I can't", {}, "qwen (Mantle)"
    it = thesis_ai.interpret("Acquirable logistic Companies with $5 Million + revenue in MH", llm=bad)
    assert it["parser"] == "rules" and it["error"] and it["params"]["revenue_min_usd"] == 5_000_000
