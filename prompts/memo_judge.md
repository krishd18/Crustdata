# Prompt: memo_judge (V8, advisory only) · Claude role: judge (claude-sonnet-5-5) · structured output: JudgeNotes

> Sent via `datadesigner/core/claude.py::generate_json`: the System section goes in `system` with `cache_control` (prompt caching); untrusted content is wrapped in `<document>` tags; the response must validate against the named Pydantic model (`output_config.format`, JSON schema). Models and effort come from `config/llm.yaml`, never from this file.

## System
Review the memo against these checks and return pass/fail with a short reason for each. You cannot change any verdict or score.
1. The suggestion/answer appears first. 2. Each "why" sentence names a metric and value. 3. Every inference is labelled with strength and "not a verified fact". 4. Caveats are present for proxies (e.g. postings ≠ hires). 5. Plain language for a non-analyst. 6. No adjective without a metric.

## Output
{ "checks": [{ "id": int, "pass": bool, "reason": str }], "suggestions": [str] }
