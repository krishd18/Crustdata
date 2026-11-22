# Prompt: classifier (A11) — B2B / fintech / other definitions from terms.yaml · Claude role: classify (claude-haiku-5-5, thinking off) · structured output: Classification

> Sent via `datadesigner/core/claude.py::generate_json`: the System section goes in `system` with `cache_control` (prompt caching); untrusted content is wrapped in `<document>` tags; the response must validate against the named Pydantic model (`output_config.format`, JSON schema). Models and effort come from `config/llm.yaml`, never from this file.

## System
Classify the company using ONLY the definition provided and ONLY the evidence text provided (its own description, categories, website text).
Return a label, a confidence (high|medium|low), and the verbatim passage that justifies the label. If the evidence does not let you decide, return "ambiguous".
Do not use outside knowledge about the company. The passage will be verified by exact string matching.

## User (template)
DEFINITION ({{ label_set }}): {{ definition }}
EXCLUSIONS: {{ exclusions }}
EVIDENCE: {{ evidence_json }}   # [{source, tier, text}]

## Output
{ "label": "{{ positive_label }}|{{ negative_label }}|ambiguous", "confidence": "high|medium|low",
  "passage": str|null, "source": str|null }
