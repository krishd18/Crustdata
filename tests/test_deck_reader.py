"""Deck reading with the Bedrock model: quotes and figures are checked in code."""
import json

from app import extract

DECK = """[page 4]
Strong Growth
Key Metrics
Repeat Orders: 90%+
Quarter-on-Quarter growth: 50%+
[page 6]
Co-Founder & CEO
Manish Singh
[page 8]
HQ: San Francisco, US with
office is Mumbai, Indore &
Bangalore, India
Logistics & Technology
Team of 30+
Customers & Signups: 800+
Global Freight forwarding is $164bn market.
email : manish@shiplyst.com"""


def fake_llm(answers):
    calls = []

    def llm(prompt, **kw):
        calls.append(prompt)
        return json.dumps({"claims": answers[min(len(calls), len(answers)) - 1]}), {"prompt_tokens": 100, "completion_tokens": 50}, "fake"
    llm.calls = calls
    return llm


GOOD = [
    {"quote": "Team of 30+", "type": "workforce", "metric": "employees", "number": 30},
    {"quote": "Quarter-on-Quarter growth: 50%+", "type": "growth", "metric": "yoy_growth_pct", "number": 50},
    {"quote": "Repeat Orders: 90%+", "type": "growth", "number": 90},
    {"quote": "Customers & Signups: 800+", "type": "customers", "number": 800, "entity": "Shiplyst"},
    {"quote": "Co-Founder & CEO Manish Singh", "type": "people", "person": "Manish Singh", "entity": "Shiplyst"},
    {"quote": "HQ: San Francisco, US with office is Mumbai, Indore & Bangalore, India", "type": "footprint",
     "place": "San Francisco, Mumbai, Indore, Bangalore"},
    {"quote": "Team of 300 engineers", "type": "workforce", "number": 300},          # not in the deck
    {"quote": "Team of 30+", "type": "workforce", "number": 45},                      # figure not in its quote
    {"quote": "email : [email]", "type": "identity"},                                # contact line
]


def test_model_claims_are_quote_checked_and_normalised():
    out, meta = extract._extract_bedrock(DECK, company="Shiplyst", llm=fake_llm([GOOD]))
    by = {(d["type"], d.get("metric"), d.get("place"), d.get("person")): d for d in out}
    assert ("workforce", "employees", None, None) in by
    assert by[("growth", "other", None, None)]["number"] == 50       # QoQ is not YoY
    assert ("efficacy", None, None, None) in by                     # repeat orders: an operating figure, not growth
    assert by[("efficacy", "clients", None, None)]["number"] == 800  # a customer COUNT, not a named client
    people = by[("people", None, None, "Manish Singh")]
    assert people["entity"] is None                                 # the company itself is not a former employer
    assert ("identity", None, "San Francisco", None) in by          # the HQ
    assert {d["place"] for d in out if d["type"] == "footprint"} == {"Mumbai", "Indore", "Bangalore"}
    assert meta["dropped"] == {"unquoted": 1, "number_not_in_quote": 1, "contact_or_empty": 1}


def test_contact_details_never_reach_the_model_and_empty_answer_gets_the_short_prompt():
    llm = fake_llm([[], [{"quote": "Team of 30+", "type": "workforce", "number": 30}]])
    out, meta = extract._extract_bedrock(DECK, company="Shiplyst", llm=llm)
    assert len(llm.calls) == 2 and meta["prompt"] == "short" and len(out) == 1
    assert all("manish@shiplyst.com" not in c for c in llm.calls)


def test_extract_falls_back_to_rules_when_the_model_fails(monkeypatch):
    monkeypatch.setattr(extract, "deck_model_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(extract, "_extract_bedrock", boom)
    info = {}
    cl = extract.extract("A lean team of 60 employees runs operations across India.", company="X", kind="deck", info=info)
    assert info["reader"] == "rules" and "model down" in info["error"] and cl[0].type == "workforce"


def test_rhetorical_slide_question_is_not_a_premise():
    assert extract._extract_rules("HOW RELIABLE IS THE EAR?", kind="deck") == []
    assert extract._extract_rules("Why did they exit Bengaluru?", kind="deck")[0]["type"] == "premise"
