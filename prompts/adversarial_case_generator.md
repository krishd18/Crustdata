# Prompt: adversarial_case_generator (V3) · Claude role: adversarial (claude-opus-5-5, effort high) · structured output: GeneratedCases · outputs frozen into tests/generated/

> Sent via `datadesigner/core/claude.py::generate_json`: the System section goes in `system` with `cache_control` (prompt caching); untrusted content is wrapped in `<document>` tags; the response must validate against the named Pydantic model (`output_config.format`, JSON schema). Models and effort come from `config/llm.yaml`, never from this file.

## System
Generate hard test cases for a claim-verification service. For each case output the input (query or synthetic deck pages), the planted truth/lie, and the EXPECTED class per claim using the class rules provided.
Categories to cover: lookalike company names; duplicate rows/postings; fake leadership credential; prompt injection inside a deck; unit traps (lakh/crore/million); award present only in sponsored content; absent-from-list claims; conflicting reliable reports; stale evidence; false premise in a question; tiny-base growth (2→3 staff); HQ in another state with operations in the target state; founded-year conflict.
Use only fictional company and person names. Never use real people.

## Output
{ "cases": [{ "id": str, "category": str, "input": {...}, "planted": str, "expected": { "classes": {"claim_text": "CLASS/CODE"}, "must_not": [str] } }] }
