"""News analysis: the model's output is only kept where it can quote the article."""
import json

from app import news_ai
from app.public import Public
from tests.test_public import FakeCrust

ARTICLES = [
    {"id": "n1", "title": "GST officials raid Stockarea warehouse in Chennai", "date": "2026-11-02",
     "text": "Officials raided a Stockarea warehousing facility over alleged input credit claims. "
             "The company, which says it runs 120 warehouses, said it is cooperating."},
    {"id": "n2", "title": "Stock Area fish survey", "date": None, "text": "A fisheries survey of the stock area."},
]


def fake_llm(payload):
    def _call(prompt, **kw):
        assert "Stockarea" in prompt and "n1" in prompt
        return json.dumps(payload), {"prompt_tokens": 100, "completion_tokens": 50}
    return _call


GOOD = {"items": [
    {"id": "n1", "about_target": True, "event_type": "legal_or_regulatory", "sentiment": "negative",
     "written_by_company": False, "summary": "GST officials searched a Stockarea warehouse.",
     "figures": [{"quote": "runs 120 warehouses", "metric": "warehouses", "number": 120, "place": None},
                 {"quote": "runs 300 warehouses", "metric": "warehouses", "number": 300, "place": None},   # invented
                 {"quote": "runs 120 warehouses", "metric": "warehouses", "number": 999, "place": None}],  # wrong number
     "concerns": [{"issue": "GST raid", "quote": "Officials raided a Stockarea warehousing facility"},
                  {"issue": "Founder arrested", "quote": "the founder was arrested"}]},                     # invented
    {"id": "n2", "about_target": False, "event_type": "other", "sentiment": "neutral", "written_by_company": False,
     "summary": "Unrelated.", "figures": [], "concerns": []},
]}


def test_only_quoted_figures_and_concerns_survive():
    out = news_ai.analyze(ARTICLES, "Stockarea", "stockarea.io", llm=fake_llm(GOOD))
    a = out["items"]["n1"]
    assert [f["number"] for f in a["figures"]] == [120]
    assert [c["issue"] for c in a["concerns"]] == ["GST raid"]
    assert a["unquoted_dropped"] == 3
    assert out["items"]["n2"]["about_target"] is False


def test_model_failure_is_reported_not_raised():
    def boom(prompt, **kw):
        raise TimeoutError("read timed out")
    out = news_ai.analyze(ARTICLES, "Stockarea", llm=boom)
    assert out["items"] == {} and "TimeoutError" in out["error"]


def test_model_reply_wrapped_in_prose_or_fences_still_parses():
    wrapped = "Here you go:\n```json\n" + json.dumps(GOOD) + "\n```"
    out = news_ai.analyze(ARTICLES, "Stockarea", llm=lambda p, **k: (wrapped, {}))
    assert "n1" in out["items"]


class Resp:
    def __init__(self, status, payload):
        self.status_code, self._p = status, payload
        self.text = json.dumps(payload)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._p


def test_bedrock_is_tried_first_and_retries_with_inference_profile(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "k")
    monkeypatch.setenv("BEDROCK_MODEL", "openai.gpt-6.1-sol")
    monkeypatch.delenv("NEWS_PROVIDERS", raising=False)
    seen = []

    def post(url, json=None, headers=None, timeout=None):
        seen.append(url)
        assert headers["authorization"] == "Bearer k"
        if "/model/openai." in url:
            return Resp(400, {"message": "Retry your request with the ID or ARN of an inference profile"})
        return Resp(200, {"output": {"message": {"content": [{"reasoningContent": {}}, {"text": '{"items": []}'}]}},
                          "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15}})

    monkeypatch.setattr(news_ai.httpx, "post", post)
    text, usage, used = news_ai.call("hi")
    assert text == '{"items": []}' and usage["total_tokens"] == 15
    assert seen[1].endswith("/model/global.openai.gpt-6.1-sol/converse") and used.startswith("global.openai.gpt-6.1-sol")


def test_claude_on_bedrock_gets_no_sampling_parameters(monkeypatch):
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "k")
    monkeypatch.setenv("BEDROCK_MODEL", "anthropic.claude-opus-4-8")
    monkeypatch.delenv("NEWS_PROVIDERS", raising=False)
    sent = {}

    def post(url, json=None, headers=None, timeout=None):
        sent.update(json)
        return Resp(200, {"output": {"message": {"content": [{"text": "{}"}]}}, "usage": {}})

    monkeypatch.setattr(news_ai.httpx, "post", post)
    news_ai.call("hi")
    assert "temperature" not in sent["inferenceConfig"]


def test_inference_profile_arn_is_encoded_and_sets_the_region(monkeypatch):
    arn = "arn:aws:bedrock:us-west-2:111122223333:inference-profile/us.anthropic.claude-opus-4-8"
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "k")
    monkeypatch.setenv("BEDROCK_MODEL", arn)
    monkeypatch.delenv("NEWS_PROVIDERS", raising=False)
    urls = []

    def post(url, json=None, headers=None, timeout=None):
        urls.append(url)
        return Resp(200, {"output": {"message": {"content": [{"text": "{}"}]}}, "usage": {}})

    monkeypatch.setattr(news_ai.httpx, "post", post)
    news_ai.call("hi")
    assert urls == ["https://bedrock-runtime.us-west-2.amazonaws.com/model/"
                    "arn%3Aaws%3Abedrock%3Aus-west-2%3A111122223333%3Ainference-profile%2Fus.anthropic.claude-opus-4-8/converse"]


def test_mantle_is_the_default_when_configured(monkeypatch):
    monkeypatch.delenv("NEWS_PROVIDERS", raising=False)
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "k")
    monkeypatch.setenv("BEDROCK_MANTLE_URL", "https://bedrock-mantle.us-east-1.api.aws/v1/")
    monkeypatch.setenv("BEDROCK_MANTLE_MODEL", "qwen.qwen3-vl-235b-a22b-instruct")
    seen = {}

    def post(url, json=None, headers=None, timeout=None):
        seen.update(url=url, model=json["model"], auth=headers["authorization"])
        return Resp(200, {"choices": [{"message": {"content": '{"items": []}'}}], "usage": {"total_tokens": 24}})

    monkeypatch.setattr(news_ai.httpx, "post", post)
    assert news_ai.providers() == ["mantle"]
    text, usage, used = news_ai.call("hi")
    assert seen == {"url": "https://bedrock-mantle.us-east-1.api.aws/v1/chat/completions",
                    "model": "qwen.qwen3-vl-235b-a22b-instruct", "auth": "Bearer k"}
    assert "Mantle" in used and usage["total_tokens"] == 24


def test_provider_order_falls_through_and_reports_each_error(monkeypatch):
    monkeypatch.setenv("NEWS_PROVIDERS", "bedrock,nvidia")
    monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "k")
    monkeypatch.setenv("NVIDIA_API_KEY", "n")

    def post(url, json=None, headers=None, timeout=None):
        if "bedrock" in url:
            return Resp(403, {"message": "openai.gpt-6.1-sol is not available for this account."})
        return Resp(200, {"choices": [{"message": {"content": "{}"}}], "usage": {"total_tokens": 3}})

    monkeypatch.setattr(news_ai.httpx, "post", post)
    _, _, used = news_ai.call("hi")
    assert "(NVIDIA)" in used

    monkeypatch.setenv("NEWS_PROVIDERS", "bedrock")
    try:
        news_ai.call("hi")
        raise AssertionError("expected failure")
    except RuntimeError as e:
        assert "not available for this account" in str(e)


def test_quote_matching_tolerates_ellipsis_and_quote_styles():
    text = "The company’s CEO said “we serve 40 brands” in Chennai."
    assert news_ai.quoted("company's CEO said \"we serve 40 brands\"", text)
    assert news_ai.quoted("The company’s CEO ... in Chennai", text)
    assert not news_ai.quoted("we serve 400 brands", text)


def test_public_flags_come_from_analysis_when_the_model_read_the_item(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test")
    # the fake crust's raid snippet is what the model sees as n3's text
    def fake(prompt, **kw):
        ids = [ln.split(": ", 1)[1] for ln in prompt.splitlines() if ln.startswith("--- id: ")]
        items = []
        for i in ids:
            items.append({"id": i, "about_target": True, "event_type": "other", "sentiment": "neutral",
                          "written_by_company": False, "summary": "s", "figures": [],
                          "concerns": [{"issue": "Tax raid", "quote": "Officials raided a Stockarea warehousing facility"}]})
        return json.dumps({"items": items}), {}
    monkeypatch.setattr(news_ai, "call", fake)
    company = {"basic_info": {"year_founded": 2019, "description": "Stockarea runs a warehousing and fulfilment network"}, "news": []}
    out = Public(FakeCrust(), "Stockarea", "stockarea.io", company, max_pdfs=0).gather()
    flags = [f for f in out["flags"] if f["kind"] == "news analysis"]
    assert len(flags) == 1 and flags[0]["text"].startswith("Tax raid")       # only the item that contains the quote
    assert not [f for f in out["flags"] if f["kind"] == "adverse media" and "raid" in f["text"].lower()]
    assert out["news_analysis"]["analysed"] == len(out["news"])
