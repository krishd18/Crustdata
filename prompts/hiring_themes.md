# Prompt: hiring_themes (A11) · Claude role: reason (claude-sonnet-5-5) · structured output: ThemeSet

> Sent via `datadesigner/core/claude.py::generate_json`: the System section goes in `system` with `cache_control` (prompt caching); untrusted content is wrapped in `<document>` tags; the response must validate against the named Pydantic model (`output_config.format`, JSON schema). Models and effort come from `config/llm.yaml`, never from this file.

## System
You are given one company's deduplicated ENGINEERING job postings for a window, and a THEME TAXONOMY.
Assign each posting to at most one theme ONLY if its title, or a verbatim passage of its description, matches the theme. Generic titles without theme words (e.g. "Software Engineer") get no theme.
Return per theme: posting ids, and one verbatim quote per posting (title or ≤ 200-char description passage).
Do NOT state what the company will launch; Data Designer computes strength with a fixed rule and writes the inference sentence.

## Output
{ "themes": [{ "theme_id": str, "postings": [{ "job_id": str, "quote": str, "quote_source": "title|description" }] }],
  "unassigned_ids": [str] }
