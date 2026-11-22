"""Read the news about a target with an LLM.

Providers, tried in order (NEWS_PROVIDERS, comma-separated):
  mantle   Amazon Bedrock "Mantle" endpoint (OpenAI-compatible chat completions),
           BEDROCK_MANTLE_URL + BEDROCK_MANTLE_MODEL, key AWS_BEARER_TOKEN_BEDROCK
  bedrock  Amazon Bedrock Converse API, same key, model BEDROCK_MODEL, region BEDROCK_REGION
  nvidia   NVIDIA API (OpenAI-compatible), NVIDIA_API_KEY, model NEWS_MODEL
           (default moonshotai/kimi-k3.1-pro; often queues for minutes)
Default order: mantle if configured, else bedrock if its key is set, else nvidia.

The model reads every article found by public.Public.news() in one call and returns,
per article: is it about this company, the event, sentiment, whether the company
wrote it, a one-line summary, figures it states, and concerns it raises.

Guard rails, because this feeds diligence:
  - every figure and concern must carry a verbatim quote, and the quote is checked
    against the article text in code; anything the model can't quote is dropped
  - concerns become "needs confirmation" flags, never verdicts
  - any model failure (timeout, bad JSON) leaves the run going on the keyword scan
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.parse import quote

import httpx

log = logging.getLogger("secondlook.news_ai")

NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
EVENTS = ["funding", "acquisition", "expansion", "new_customer", "partnership", "product_launch", "leadership_change",
          "layoffs", "legal_or_regulatory", "insolvency", "fraud_allegation", "accident", "award", "financial_results",
          "opinion_or_listicle", "other"]
METRICS = ["employees", "warehouses", "sites", "cities", "clients", "yoy_growth_pct", "revenue", "founded_year",
           "area_sqft", "funding_usd", "other"]


def model() -> str:
    """The NVIDIA model name (kept for compatibility); see providers() for the full order."""
    return os.getenv("NEWS_MODEL", "moonshotai/kimi-k3.1-pro")


def bedrock_model() -> str:
    return os.getenv("BEDROCK_MODEL", "openai.gpt-6.1-sol")


def mantle_model() -> str:
    return os.getenv("BEDROCK_MANTLE_MODEL", "qwen.qwen3-vl-235b-a22b-instruct")


def providers() -> list[str]:
    if os.getenv("NEWS_PROVIDERS"):
        return [p.strip() for p in os.environ["NEWS_PROVIDERS"].split(",") if p.strip()]
    if os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
        return ["mantle"] if os.getenv("BEDROCK_MANTLE_URL") else ["bedrock"]
    return ["nvidia"]


def describe() -> str:
    names = {"mantle": f"{mantle_model()} (Amazon Bedrock Mantle)", "bedrock": f"{bedrock_model()} (Amazon Bedrock)",
             "nvidia": f"{model()} (NVIDIA)"}
    return " → ".join(names.get(p, p) for p in providers())


def available() -> bool:
    keys = {"mantle": "AWS_BEARER_TOKEN_BEDROCK", "bedrock": "AWS_BEARER_TOKEN_BEDROCK", "nvidia": "NVIDIA_API_KEY"}
    return any(os.getenv(keys.get(p, "")) for p in providers())


PROMPT = """You are helping a corporate-development analyst screen a company before a meeting.
Company: {company}{domain}

Below are {n} news items found by a web search. For EACH item, decide:
- about_target: is it actually about this company (not a namesake or a passing mention)?
- event_type: one of {events}
- sentiment toward the company: positive | neutral | negative
- written_by_company: true if it is a press release or the company's own post
- summary: one plain sentence, no hype
- figures: facts with numbers it states about THIS company. For each: "quote" (copied
  EXACTLY from the item, max 200 chars), "metric" (one of {metrics}), "number", "place" (or null)
- concerns: anything a buyer should ask about (legal trouble, insolvency, layoffs, fraud
  allegations, accidents, customer losses, contradictions). For each: "issue" (short) and
  "quote" (copied EXACTLY from the item). No concern without a quote. Empty list if none.

Rules: use only what the item says; do not use outside knowledge; do not guess.
Reply with ONLY this JSON, no prose, no code fence:
{{"items": [{{"id": "...", "about_target": true, "event_type": "...", "sentiment": "...",
  "written_by_company": false, "summary": "...", "figures": [], "concerns": []}}]}}

Items:
{items}"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def quoted(quote: str, text: str) -> bool:
    """The quote really is in the article (whitespace/quote-style/'...' insensitive)."""
    q = _norm(quote).strip(" .\"'")
    if len(q) < 8:
        return False
    t = _norm(text)
    return all(part.strip() in t for part in re.split(r"\.\.\.|…", q) if part.strip())


def _parse_json(content: str) -> dict:
    content = re.sub(r"^```(?:json)?|```$", "", (content or "").strip(), flags=re.M).strip()
    try:
        return json.loads(content)
    except ValueError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def call(prompt: str, **kw) -> tuple[str, dict, str]:
    """Try each provider in order; returns (content, usage, model actually used)."""
    errors = []
    for p in providers():
        fn = {"mantle": call_mantle, "bedrock": call_bedrock, "nvidia": call_nvidia}.get(p)
        if not fn:
            errors.append(f"{p}: unknown provider")
            continue
        try:
            return fn(prompt, **kw)
        except Exception as e:
            log.warning("news model %s failed: %s", p, e)
            errors.append(f"{p}: {type(e).__name__}: {str(e)[:140]}")
    raise RuntimeError(" | ".join(errors) or "no provider configured")


def call_bedrock(prompt: str, *, timeout: float | None = None, max_tokens: int = 6000,
                 temperature: float | None = None) -> tuple[str, dict, str]:
    """Bedrock Converse API with a Bedrock API key (bearer token); no AWS SDK needed."""
    key = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    if not key:
        raise RuntimeError("AWS_BEARER_TOKEN_BEDROCK not set")
    region = os.getenv("BEDROCK_REGION", "us-east-1")
    t = float(timeout or os.getenv("BEDROCK_TIMEOUT") or 90)
    mid = bedrock_model()
    cfg = {"maxTokens": max_tokens}
    if "anthropic." not in mid:  # Claude Opus 4.7+ rejects sampling parameters with a 400
        cfg["temperature"] = 0.2
    body = {"messages": [{"role": "user", "content": [{"text": prompt}]}], "inferenceConfig": cfg}
    if mid.startswith("arn:"):  # an inference-profile ARN carries its own region
        region = mid.split(":")[3] or region
    for attempt in range(2):
        # IDs may be ARNs ("arn:aws:bedrock:...:inference-profile/us.anthropic..."): encode ':' and '/'
        r = httpx.post(f"https://bedrock-runtime.{region}.amazonaws.com/model/{quote(mid, safe='')}/converse", json=body,
                       headers={"authorization": f"Bearer {key}"}, timeout=httpx.Timeout(t, connect=20))
        # Some models are only served through a cross-region inference profile.
        if (r.status_code == 400 and "inference profile" in r.text and attempt == 0
                and not mid.startswith(("global.", "us.", "eu.", "apac.", "arn:"))):
            mid = f"global.{mid}"
            continue
        break
    if r.status_code != 200:
        msg = r.json().get("message", r.text) if r.headers.get("content-type", "").startswith("application/json") else r.text
        raise RuntimeError(f"Bedrock HTTP {r.status_code} ({region}, {mid}): {str(msg)[:200]}")
    j = r.json()
    blocks = ((j.get("output") or {}).get("message") or {}).get("content") or []
    text = "".join(b.get("text", "") for b in blocks if "text" in b)
    u = j.get("usage") or {}
    return text, {"prompt_tokens": u.get("inputTokens"), "completion_tokens": u.get("outputTokens"),
                  "total_tokens": u.get("totalTokens")}, f"{mid} (Amazon Bedrock, {region})"


def _openai_chat(url: str, key: str, mdl: str, prompt: str, timeout: float, max_tokens: int, label: str,
                 temperature: float = 0.2):
    """POST an OpenAI-style chat completion (NVIDIA, Bedrock Mantle)."""
    body = {"model": mdl, "temperature": temperature, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}]}
    r = httpx.post(url, json=body, headers={"authorization": f"Bearer {key}"}, timeout=httpx.Timeout(timeout, connect=20))
    if r.status_code != 200:
        raise RuntimeError(f"{label} HTTP {r.status_code}: {r.text[:200]}")
    j = r.json()
    msg = (j.get("choices") or [{}])[0].get("message") or {}
    return msg.get("content") or "", j.get("usage") or {}, f"{mdl} ({label})"


def call_mantle(prompt: str, *, timeout: float | None = None, max_tokens: int = 6000,
                temperature: float = 0.2) -> tuple[str, dict, str]:
    key, base = os.getenv("AWS_BEARER_TOKEN_BEDROCK"), os.getenv("BEDROCK_MANTLE_URL")
    if not (key and base):
        raise RuntimeError("AWS_BEARER_TOKEN_BEDROCK and BEDROCK_MANTLE_URL must be set")
    return _openai_chat(f"{base.rstrip('/')}/chat/completions", key, mantle_model(), prompt,
                        float(timeout or os.getenv("BEDROCK_TIMEOUT") or 90), max_tokens, "Amazon Bedrock Mantle", temperature)


def call_nvidia(prompt: str, *, timeout: float | None = None, max_tokens: int = 6000,
                temperature: float = 0.2) -> tuple[str, dict, str]:
    key = os.getenv("NVIDIA_API_KEY")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY not set")
    return _openai_chat(NVIDIA_URL, key, model(), prompt, float(timeout or os.getenv("NEWS_MODEL_TIMEOUT") or 150),
                        max_tokens, "NVIDIA", temperature)


def analyze(items: list[dict], company: str, domain: str | None = None, *, llm=None) -> dict:
    """items: [{id, title, date, text}] -> {"items": {id: analysis}, "model", "usage", "error"}."""
    llm = llm or call  # looked up at call time, so tests can replace it
    out = {"model": describe(), "items": {}, "usage": {}, "error": None, "seconds": None}
    if not items:
        return out
    blocks = []
    for it in items:
        blocks.append(f'--- id: {it["id"]}\ntitle: {it.get("title") or ""}\ndate: {it.get("date") or "unknown"}\n'
                      f'text: {(it.get("text") or "")[:6000]}')
    prompt = PROMPT.format(company=company, domain=f" ({domain})" if domain else "", n=len(items),
                           events=", ".join(EVENTS), metrics=", ".join(METRICS), items="\n".join(blocks))
    t0 = time.time()
    try:
        res = llm(prompt)
        content, usage = res[0], res[1]
        if len(res) > 2:
            out["model"] = res[2]  # the provider that actually answered
        data = _parse_json(content)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
        out["seconds"] = round(time.time() - t0, 1)
        log.warning("news analysis failed: %s", out["error"])
        return out
    out["usage"], out["seconds"] = usage, round(time.time() - t0, 1)
    texts = {it["id"]: f'{it.get("title") or ""} {it.get("text") or ""}' for it in items}
    for a in data.get("items", []):
        iid = str(a.get("id"))
        if iid not in texts:
            continue
        text = texts[iid]
        figs, dropped = [], 0
        for f in a.get("figures") or []:
            q = str(f.get("quote") or "")
            num = f.get("number")
            if quoted(q, text) and (num is None or _num_in(num, q)):
                figs.append({"quote": q, "metric": f.get("metric") if f.get("metric") in METRICS else "other",
                             "number": num, "place": f.get("place")})
            else:
                dropped += 1
        cons = []
        for c in a.get("concerns") or []:
            if quoted(str(c.get("quote") or ""), text):
                cons.append({"issue": str(c.get("issue") or "")[:120], "quote": str(c["quote"])[:300]})
            else:
                dropped += 1
        out["items"][iid] = {
            "about_target": bool(a.get("about_target", True)),
            "event_type": a.get("event_type") if a.get("event_type") in EVENTS else "other",
            "sentiment": a.get("sentiment") if a.get("sentiment") in ("positive", "neutral", "negative") else "neutral",
            "written_by_company": bool(a.get("written_by_company")),
            "summary": str(a.get("summary") or "")[:300],
            "figures": figs, "concerns": cons, "unquoted_dropped": dropped,
        }
    return out


def _num_in(num, quote: str) -> bool:
    try:
        n = float(num)
    except (TypeError, ValueError):
        return False
    digits = re.findall(r"\d[\d,]*(?:\.\d+)?", quote)
    vals = {float(d.replace(",", "")) for d in digits}
    # "₹100 Cr" / "$1.2 Mn": allow the model to have scaled the unit
    return any(abs(v - n) < 1e-6 or (v and abs(n / v - round(n / v)) < 1e-9 and round(n / v) in (1e3, 1e5, 1e6, 1e7, 1e9))
               for v in vals)
