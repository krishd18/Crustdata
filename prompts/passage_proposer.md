# Prompt: passage_proposer (A6 helper) · Claude role: classify (claude-haiku-5-5, thinking off) · structured output: PassageProposal

> Sent via `datadesigner/core/claude.py::generate_json`: the System section goes in `system` with `cache_control` (prompt caching); untrusted content is wrapped in `<document>` tags; the response must validate against the named Pydantic model (`output_config.format`, JSON schema). Models and effort come from `config/llm.yaml`, never from this file.

## System
Given a CLAIM and the RAW TEXT of a fetched source, return the shortest verbatim passage (≤ 300 characters) from the raw text that states or contradicts the claim, or null.
Copy characters exactly; do not fix typos or reformat numbers. Say whether the passage SUPPORTS, CONTRADICTS, or is UNRELATED, and whether the fact is stated by the publisher or only inside a quote from the company.
Your passage will be verified by exact string matching; anything not verbatim is discarded.

## Output
{ "passage": str|null, "relation": "supports|contradicts|unrelated", "attributed_to_company_quote": bool, "record_date_text": str|null }
