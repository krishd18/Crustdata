# Prompt: memo_smoother (A13) · Claude role: reason (claude-sonnet-5-5) · structured output: SmoothedSections · number lock re-checks the output

> Sent via `datadesigner/core/claude.py::generate_json`: the System section goes in `system` with `cache_control` (prompt caching); untrusted content is wrapped in `<document>` tags; the response must validate against the named Pydantic model (`output_config.format`, JSON schema). Models and effort come from `config/llm.yaml`, never from this file.

## System
Improve the readability of the memo sentences below for a busy decision-maker. Rules:
- Keep every number, date, percentage, currency amount, company name, person name, class badge and code EXACTLY as given.
- Do not add facts, adjectives without a metric, or opinions. Do not remove caveats or "INFERENCE — not a verified fact" labels.
- Keep the suggestion first. Return the same number of sentences, each mapped to its id.
Every output sentence is re-checked by the number lock; any sentence that changes a value is discarded.

## Output
{ "sentences": [{ "id": str, "text": str }] }
