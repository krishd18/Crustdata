---
name: e2e
description: Run the full end-to-end case matrix and the determinism check; optionally the live runs of the organiser sample inputs.
argument-hint: "[live]"
disable-model-invocation: true
---
1. `make e2e` (all cases in replay ×3) → confirm byte-identical outputs and ≥ 90% pass with zero wrong VERIFIED/FALSE.
2. If "$ARGUMENTS" contains "live", run `make e2e-live` for the two organiser sample inputs (budget-capped; Claude and Crustdata live, mail in test mode) and write reports/e2e/live_drift.md.
3. Run the citation-auditor and rubric-auditor sub-agents on the outputs. Summarise pass rate, failures and next fixes.
