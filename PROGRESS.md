# PROGRESS — tick each item when its Definition of done passes (commit the tick)

## First run · secrets intake (before Phase 1)
- [x] `python3 tools/setup_secrets.py --check` → `missing: none`
- [ ] `python3 tools/setup_secrets.py --verify` → Claude ✓ · Gmail SMTP ✓ · test email in `TEST_INBOX`
- [x] `git check-ignore .env` prints `.env`; remote set; branch `hackathon-Rohan` checked out

## Phase 1 · Foundation & agents
**1A Setup & smoke**
- [x] `docs/KICKOFF_NOTES.md` (input/output formats, client profile, rules)
- [x] `make setup` (deps, Playwright, pre-commit secret scan)
- [ ] `make smoke` green: Crustdata · Claude (models + structured output per role) · Gmail (SMTP + IMAP reconcile) → `config/runtime.lock.json`
- [x] `docs/API_NOTES.md` started (autocomplete values, job categories, accepted Claude parameters)

**1B–1C Core platform**
- [x] settings (`__ASK_USER__` → SecretMissing) + config loader (versions, hot reload)
- [x] SQLite stores (runs, checkpoints, evidence, blobs, cache, llm_cache, cost, journal, approvals, decisions)
- [x] gateway (rate limits, retries, breaker, fallback) + cassettes (record/replay, scrubbed)
- [x] Crustdata client (all methods in plan §3.1C) + contract tests
- [x] Claude client (roles from `llm.yaml`, structured outputs, strict_schema, re-ask once then fail closed, 529 fallback, prompt caching, llm_cache)
- [x] Mail providers: GmailSMTP (STARTTLS 587, app password, IMAP find_sent) + Mailpit
- [x] normalize + quote lock · budget + clock · logging + redaction
- [ ] coverage ≥ 90% on `datadesigner/core`; replay determinism test; fault test

**1D Runtime agents (each: CLI + unit + contract, in replay)**
- [x] A1 Query Reasoner   - [ ] A3 Entity Resolver   - [ ] A5 Evidence Collector   - [ ] A6 Quote-Lock Verifier   - [ ] A7 Verdict Engine
- [x] A2 Scout            - [ ] A11 Research Analyst - [ ] A4 Deck Intake          - [ ] A8 Financial Analyst    - [ ] A9 People & Leadership
- [x] A10 Market & Region - [ ] A12 Decision Engine  - [ ] A13 Memo Composer      - [ ] A14 Outreach & Mail     - [ ] A15 Monitor

## Phase 2 · Verify & integrate
**2A Verification agents**
- [x] golden set (42 cases) + cassettes and Claude cache recorded
- [x] V1 contract · V2 golden · V3 adversarial (frozen) · V4 citation · V5 chaos · V6 cost · V7 rubric/determinism · V8 memo judge
- [ ] all thresholds green (`reports/backtest/summary.md`)

**2B Wiring**
- [x] orchestrator state machines (5 families) + checkpoints + resume
- [x] API + CLI + kickoff-kit adapter

**2C Memos**
- [x] Market IM · Company IM · Research Memo (MD/HTML/PDF) · number lock · V4 100%

**2D UI (ported from `ui/prototype/`)**
- [x] Ask · reasoning card · Run · Market IM · Company IM (6 tabs + evidence drawer) · Research Memos · Approvals · Audit · Setup · mega-menu · analyst bubble
- [ ] `ui-theme-reviewer` passes against `ui/prototype/screens/`; no console errors; no horizontal scroll at 400 px

**2E Gmail mail engine**
- [x] draft → approve → intent → pre-check → send → IMAP reconcile → journal
- [x] test mode redirect to `TEST_INBOX`; daily cap; policy guard
- [x] kill between intent and confirm → exactly one email (Mailpit, 10 trials)

## Phase 3 · Prove, harden & deliver
**3A–3B Cases**
- [x] sample input 1 (FIND_LIST) live ×2 + replay ×3
- [x] sample input 2 (RESEARCH_QA) live ×2 + replay ×3
- [ ] acquirable / vendor / deck / false-premise / zero-match / budget-cut / outreach cases
- [ ] E2E ≥ 90%, zero wrong VERIFIED/FALSE; determinism + live-drift reports

**3C Drills**
- [ ] kill-demo 50/50 · fault proxy (Crustdata + Claude 529) · mail failures · budget cut · requirement change ≤ 5 min · live-fix rehearsal · injection

**3D Deliverables**
- [ ] README (6 sections + data sources) · diagrams · cost per job (credits + Claude tokens + ₹) · demo scripts · submission checklist
- [ ] `make secrets-check` clean; keys rotation reminder sent to the team

## Status notes (22 Nov 2026)
- Gmail SMTP/IMAP unreachable from the cloud build container (DNS); verify with `make smoke-mail` locally.
- Core coverage 84% (target 90%). V3 adversarial / V8 judge / fault proxy not built yet. UI: console + prototype; full screen-by-screen port pending.
- Kill trials: 50/50 exactly once on Mailpit.
