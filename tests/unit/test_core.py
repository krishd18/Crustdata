import json, httpx, pytest
from types import SimpleNamespace
from pydantic import BaseModel
from datadesigner.core import normalize, quote_lock
from datadesigner.core.budget import Budget
from datadesigner.core.claude import ClaudeClient, strict_schema
from datadesigner.core.errors import BudgetExhausted, ContractError, ParseFailed, SourceUnavailable, CassetteMiss
from datadesigner.core.gateway import Gateway
from datadesigner.core.logging import redact
from datadesigner.core.stores import Stores
from datadesigner.core.clock import Clock


def test_normalize_units_and_digits():
    assert normalize.parse_amount("₹1,20,00,000") == (12000000.0, "INR")
    assert normalize.parse_amount("1.2 crore")[0] == 12000000.0
    assert normalize.parse_amount("$12 million") == (12000000.0, "USD")
    assert normalize.company_name("XYZ Logistics Private Limited") == normalize.company_name("XYZ Logistics Pvt. Ltd.")


def test_quote_lock_verbatim_and_fields():
    raw = "Revenue from operations: 18,600 lakh in FY26"
    assert quote_lock.lock("18600 lakh", raw) is not None
    assert quote_lock.lock("19,600 lakh", raw) is None          # a planted fake passage never locks
    assert quote_lock.lock_field("a.b.0", 5, json.dumps({"a": {"b": [5]}}))
    assert not quote_lock.lock_field("a.b.0", 6, json.dumps({"a": {"b": [5]}}))


def test_clock_windows():
    c = Clock("2026-11-22T16:30:00+05:30")
    s, e, lbl = c.quarter_window()
    assert (str(s), str(e)) == ("2026-10-01", "2026-11-22") and "Q3 FY2026-27" in lbl


def test_redactor():
    out = redact("key sk-ant-api03-abcdefghijkl and cd_0123456789abcdef mail a@b.com PAN ABCDE1234F")
    assert "sk-ant-[REDACTED]" in out and "cd_[REDACTED]" in out and "[EMAIL]" in out and "[PAN]" in out


def test_budget_noncritical_stop():
    b = Budget(max_credits=10, deadline_s=0)
    b.charge(8.5)
    b.check(0.5, critical=True)
    with pytest.raises(BudgetExhausted):
        b.check(0.1, critical=False)
    with pytest.raises(BudgetExhausted):
        b.check(5, critical=True)


def _gw(handler, mode="live"):
    return Gateway(Stores(":memory:"), {"crustdata": {"breaker": {"failures_to_open": 5}}}, mode=mode,
                   transport=httpx.MockTransport(handler), sleep=lambda s: None)


def test_gateway_retry_429_then_ok_and_cost():
    n = {"i": 0}
    def h(req):
        n["i"] += 1
        return httpx.Response(429, headers={"retry-after": "1"}) if n["i"] < 3 else httpx.Response(200, json={"ok": 1}, headers={"x-credits-used": "2"})
    g = _gw(h)
    r = g.request("crustdata", "company_enrich", "POST", "https://x/company/enrich", "/company/enrich", {"a": 1})
    assert r.body == {"ok": 1} and n["i"] == 3 and g.stores.cost_summary()["credits"] == 2


def test_gateway_400_is_contract_error_and_breaker_opens():
    g = _gw(lambda req: httpx.Response(400, json={"e": "bad"}))
    with pytest.raises(ContractError):
        g.request("crustdata", "x", "POST", "https://x/a", "/a", {})
    g2 = _gw(lambda req: httpx.Response(500))
    with pytest.raises(SourceUnavailable):
        g2.request("crustdata", "x", "POST", "https://x/a", "/a", {}, max_retries=10)
    with pytest.raises(SourceUnavailable, match="breaker"):
        g2.request("crustdata", "x", "POST", "https://x/a", "/a", {})


def test_replay_miss_fails():
    with pytest.raises(CassetteMiss):
        _gw(lambda r: httpx.Response(200), mode="replay").request("crustdata", "x", "POST", "https://x/zz", "/zz", {"never": "recorded"})


class Out(BaseModel):
    label: str
    default: str | None


def test_strict_schema_keeps_property_named_default():
    s = strict_schema(Out)
    assert "default" in s["properties"] and s["additionalProperties"] is False and set(s["required"]) == {"label", "default"}


class FakeSDK:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw["model"])
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=r)], usage=SimpleNamespace(input_tokens=5, output_tokens=5, cache_read_input_tokens=0), _request_id="req_x")


class Overloaded(Exception):
    status_code = 529


CFG = {"roles": {"classify": {"models": ["m1", "m2"], "max_tokens": 10}}, "retries": {"reask_on_schema_error": 1}}


def _cc(replies):
    return ClaudeClient(Stores(":memory:"), CFG, SimpleNamespace(claude_model_classify="auto"), sdk_client=FakeSDK(replies), mode="live")


def test_claude_reask_once_then_fail_closed():
    with pytest.raises(ParseFailed):
        _cc(["not json", "{}"]).generate_json("classify", "s", "u", Out)
    out, _ = _cc(["oops", '{"label":"b2b","default":null}']).generate_json("classify", "s", "u", Out)
    assert out.label == "b2b"


def test_claude_529_falls_back_and_cache_is_deterministic():
    cc = _cc([Overloaded("overloaded"), '{"label":"x","default":null}'])
    out, u = cc.generate_json("classify", "s", "u", Out)
    assert u["model"] == "m2" and cc._sdk.calls == ["m1", "m2"]
    again, u2 = cc.generate_json("classify", "s", "u", Out)   # served from llm_cache, no new call
    assert again == out and u2["cached"] and len(cc._sdk.calls) == 2
