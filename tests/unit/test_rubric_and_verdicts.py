import json, subprocess, sys
import yaml
from datadesigner.core.types import Claim, Evidence
from datadesigner.agents.a07_verdict import VerdictEngine, VerdictInput
from datadesigner.rubric.scoring import band, rdown, vi01, score, rule
from datadesigner.rubric.research import inference_strength

def test_reference_scorer_parity():
    out = subprocess.run([sys.executable, "tools/rubric_check.py"], capture_output=True, text=True).stdout
    assert "floor 72.5 ceil 81.25" in out and "floor 68.75 ceil 76.25 positive with conditions" in out and "floor 72.5 ceil 87.5" in out
    assert band(90, [90, 75, 60, 40]) == 4 and rdown(3.29) == 3.0 and vi01(12, 13, 14, 1)[:2] == (2, 3)
    assert rule(*score({"a": (100, 2.5, 3)})) == "positive_with_conditions"


def test_inference_strength_rule():
    cfg = yaml.safe_load(open("config/rubric.yaml"))["IS"]
    assert inference_strength(5, 0.3, True, cfg) == "STRONG"
    assert inference_strength(5, 0.3, False, cfg) == "MODERATE"
    assert inference_strength(1, 0.05, False, cfg) == "WEAK"


def ev(eid, tier, rel="supports", kind="field", media=None, value=None, quote=False):
    return Evidence(evidence_id=eid, source="s", url_or_endpoint=eid, passage_or_field="p", value=value, retrieved_at="x", content_sha256="h",
                    tier=tier, relation=rel, kind=kind, media_tier=media, attributed_to_company_quote=quote)


def classify(ctx, claim, evs, **kw):
    return VerdictEngine().run(VerdictInput(claims=[claim], evidence=evs, by_claim={claim.claim_id: [e.evidence_id for e in evs]}, **kw), ctx).verdicts[0]


def test_false_safety_rules(ctx):
    c = Claim(claim_id="c", type="headcount", text="640 employees", value=640)
    assert classify(ctx, c, [ev("e1", "T2", kind="lower_bound", rel="contradicts", value=300)]).cls == "UNVERIFIED"     # T2 never FALSE
    assert classify(ctx, c, [ev("e1", "T1-M", rel="contradicts", media="A")]).cls == "NOT_VERIFIABLE"                     # single media never FALSE
    assert classify(ctx, c, [ev("e1", "T1", rel="contradicts", value=200)], entity_score=0.7).code == "N4"               # unresolved entity
    assert classify(ctx, c, [ev("e1", "T1", value=200)]).cls == "FALSE"
    a = Claim(claim_id="a", type="award", text="Best 3PL 2025")
    assert classify(ctx, a, [ev("e1", "T1-M", media="D")]).code == "U2"                                                    # sponsored = self-published
    assert classify(ctx, a, [ev("e1", "T1-M", media="A"), ev("e2", "T1-M", media="A", rel="contradicts")]).code == "N3"


def test_unit_trap_and_currency(ctx):
    c = Claim(claim_id="r", type="revenue", text="revenue ₹1,20,00,000", value="₹1,20,00,000")
    assert classify(ctx, c, [ev("e", "T1", value="1.2 crore")]).cls == "VERIFIED"
    c2 = Claim(claim_id="r2", type="revenue", text="₹12 crore", value="₹12 crore")
    assert classify(ctx, c2, [ev("e", "T1", value="$12 million")]).cls != "FALSE"
