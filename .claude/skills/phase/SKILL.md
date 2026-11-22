---
name: phase
description: Execute or resume one of the three implementation phases in IMPLEMENTATION_PLAN.md (1 Foundation & agents, 2 Verify & integrate, 3 Prove, harden & deliver).
argument-hint: <1|2|3>
disable-model-invocation: true
---
Work on Phase $ARGUMENTS only.
0. If `python3 tools/setup_secrets.py --check` reports anything missing, run the setup-secrets skill first.
1. Open IMPLEMENTATION_PLAN.md (Phase $ARGUMENTS section) and PROGRESS.md. List the unticked Definition-of-done items for this phase, in plan order.
2. Implement them one at a time, running tests in replay mode after each step. Phase 1 builds agents separately (CLI + unit + contract each); Phase 2 builds V1–V8 before wiring, and ports `ui/prototype/` without redesigning it; Phase 3 works the cases and drills.
3. Use the sub-agents the plan names: backtest-auditor (agents), citation-auditor (evidence/memos), chaos-tester (journal/orchestrator/mail), rubric-auditor (config/rubric), ui-theme-reviewer (UI).
4. Before each commit run the spec-guardian sub-agent and `make secrets-check`.
5. Tick completed items in PROGRESS.md, commit as `p$ARGUMENTS(scope): ...`, push to `hackathon-Rohan`.
Stop and report if a DoD item cannot pass without changing docs/STANDARDS.md, or if a live API or model parameter differs from the docs (record it in docs/API_NOTES.md first).
