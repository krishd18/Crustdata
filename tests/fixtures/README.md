# Fixtures

- `decks/` — synthetic decks with seeded truths and lies (built in Phase 3 from V3 templates): `company_c.pdf` (WALKTHROUGH Part A), `acme_vendor_pack.pdf` (STANDARDS §6.6), plus one per hard case (H3–H9, H14).
- Named fixtures referenced in `tests/cases.jsonl` (`fixture:`) are recorded cassette sets under `tests/cassettes/<case-id>/` or synthetic JSON under `tests/fixtures/<name>.json`.
- Use fictional company and person names only. Never put API keys in fixtures or cassettes (`tools/scrub_cassettes.py` enforces this).
