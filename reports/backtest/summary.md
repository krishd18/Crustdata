# Back-test summary · 2026-11-22 12:45

| Check | Status | Last line |
|---|---|---|
| V1 contract (15 agents, edge payloads) | ✅ pass |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| Unit (core, rubric, verdict safety, Claude fail-closed/fallback) | ✅ pass |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| V2/V4/V7 golden e2e + rubric parity + 3× determinism | ✅ pass |   warnings.warn(PytestDeprecationWarning(_DEFAULT_FIXTURE_LOOP_SCOPE_UNSET)) |
| V7 reference scorer | ✅ pass | weights target 100 vendor 100 R1 100 |
| Secrets in cassettes | ✅ pass | cassettes: clean |
| V5 kill trials (10, Mailpit) | ✅ pass | exactly-once: 10/10 trials |
