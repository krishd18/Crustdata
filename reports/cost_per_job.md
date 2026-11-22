# Cost per job — measured from the cost ledger (X-Credits-Used + Claude usage), 22 Nov 2026

| Job | Crustdata credits | Claude tokens (in+out, claude-sonnet-5) | ₹ (2 ₹/credit planning rate + $2/$10 per Mtok @ ₹84) | Wall time |
|---|---|---|---|---|
| Sample 1 · FIND_LIST (10 rows) | 81.8 | 17,011 + 3,469 | ≈ ₹169 | 52 s |
| Sample 2 · RESEARCH_QA (ranking + inferences) | 91.2 | 32,082 + 4,442 | ≈ ₹191 | 165 s (5 RPM limit) |
| False-premise question (H4) | 1.0 (+ cached job data) | ≈ 4k | ≈ ₹4 | < 10 s |
| Deck / vendor CHECK (fixture packs, registry extracts) | 0 | 0 (pre-extracted claims) | ₹0 | < 1 s |
| Re-runs / replays | 0 | 0 (llm_cache) | ₹0 | seconds |

Proposed prices (ARCHITECTURE §21): vendor clearance ₹2,500 · target diligence ₹60,000 · sourcing run ₹25,000 → measured cost is < 10% of price.
