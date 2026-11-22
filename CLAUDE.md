# CLAUDE.md — project instructions for Claude Code

You are building **Data Designer** for ContextCon 05 ("Services, Replaced") on branch `hackathon-Rohan`. Data Designer replaces a paid diligence/research job: it reads a query, finds companies with Crustdata, fact-checks claims against live records, scores them on a fixed rubric and writes an Information Memo. A person approves every irreversible action. The LLM is the **Claude API**; outbound email goes through **Gmail SMTP**.

## First thing in every new session: secrets intake
1. Run `python3 tools/setup_secrets.py --check`. It prints only the **names** of missing variables.
2. If any are missing (`DD_ANTHROPIC_API_KEY`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `TEST_INBOX`), **stop and ask the user once, in one message**, for all of them. Offer two ways:
   - recommended: they run `make setup-secrets` in their own terminal (hidden input, writes `.env` with mode 600);
   - or they paste the values here; then write them into `.env` with the **Edit tool only** (never via a shell command), and never repeat them back.
   For the app password, remind them: Google Account → Security → 2-Step Verification → App passwords (16 letters).
3. Run `python3 tools/setup_secrets.py --verify` (Claude `/v1/models` + Gmail SMTP login), then `make smoke` once the code exists.
4. Confirm `git check-ignore .env` prints `.env`. If the repo has no remote, ask for the organiser repository URL and use branch `hackathon-Rohan`.
Do not start Phase 1 code until step 3 passes. The Crustdata key is already in `.env`.

## Read first, in this order
1. `IMPLEMENTATION_PLAN.md`: the **3-phase** plan (1 Foundation & agents · 2 Verify & integrate · 3 Prove, harden & deliver). Tick `PROGRESS.md` as you go.
2. `docs/STANDARDS.md`: verdict classes, source tiers, metric dictionary, query reasoning, rubrics, memo format. The single source of truth.
3. `docs/AGENTS.md` (agent contracts) and `docs/TEST_PLAN.md` (back-tests and thresholds).
4. `docs/UI_THEME.md` + `ui/prototype/` (the approved look; port it, don't redesign it).
5. `docs/ARCHITECTURE.md`, `docs/WALKTHROUGH.md`, `docs/WORKFLOW.md`, `docs/COMPETITION_BRIEF.md` as needed.

## Non-negotiables
- **Secrets:** keys and passwords live only in `.env` (gitignored). Never print, log, commit or write them into cassettes, fixtures, docs, prompts or tool output. Run `make secrets-check` before every commit. The repo is public. The Claude key variable is `DD_ANTHROPIC_API_KEY` — never export it as `ANTHROPIC_API_KEY` in this shell.
- **Claude never decides** a verdict class, score, grade, label or decision. It extracts, classifies with quoted evidence, maps query words through `config/terms.yaml`, and smooths prose under number lock.
- **Structured outputs only:** every Claude call uses `output_config.format` (JSON schema) validated by Pydantic; on mismatch re-ask once, then fail closed. No forced `tool_choice`, no prefill. Models, effort and thinking settings come from `config/llm.yaml`.
- **Quote lock:** no fact enters the evidence ledger unless its passage or field exists verbatim in stored raw content with a record date.
- **Wrong is worse than unknown:** never pad lists, never upgrade a class, never mark FALSE without a higher-authority quote-locked contradiction and a resolved entity.
- **Exactly once:** irreversible actions go through the journal (intent → act → confirm, reconcile on restart). Gmail sends use a deterministic Message-ID and are reconciled against `[Gmail]/Sent Mail` over IMAP.
- **Mail safety:** a person approves every email; `MAIL_MODE=test` (default) redirects everything to `TEST_INBOX`; automated tests and chaos trials use Mailpit, never Gmail.
- **Determinism:** `llm_cache` + HTTP record/replay cassettes. Tests run in `DD_HTTP_MODE=replay` and need no live keys.
- **Config first:** thresholds, weights, term meanings, media list, roles, models, mail policy and output schema live in `config/`. Code reads them; it never hard-codes them.
- **Rubric parity:** `datadesigner/rubric/*` must give the same numbers as `tools/rubric_check.py` (V7 enforces this).

## How to work
- **Phase 1:** build the core platform, then agents A1…A15 **separately**, each with a CLI, a contract test and unit tests.
- **Phase 2:** build verification agents V1…V8 and meet `verification/thresholds.yaml`; only then wire the orchestrator, memos, UI (ported from `ui/prototype/`) and the Gmail mail engine.
- **Phase 3:** work every case end to end, run the drills, ship the deliverables.
- **Dev sub-agents** in `.claude/agents/`: `backtest-auditor` after any agent change · `citation-auditor` after evidence or memo changes · `chaos-tester` after journal, orchestrator or mail changes · `rubric-auditor` after config or rubric changes · `spec-guardian` before each commit · `ui-theme-reviewer` after UI changes.
- **Skills** (`.claude/skills/`): `/setup-secrets`, `/phase 1|2|3`, `/backtest <agent>`, `/e2e`, `/demo`.
- **When the live API differs from the docs,** follow the live API. Fix the client, add a contract test and note it in `docs/API_NOTES.md`.
- **Commit often:** `pN(scope): message` (N = phase). Push to `hackathon-Rohan`. Never force-push shared history.

## Commands
- `make setup-secrets` · `make setup` · `make smoke` (`smoke-crustdata`, `smoke-claude`, `smoke-mail`) · `make test` · `make backtest` · `make e2e` · `make chaos` · `make kill-demo` · `make run` · `make ui-proto`
- `make record CASE=<id>` spends Crustdata credits and Claude tokens, so run it only on purpose and within the case budget.

## Style
- Python 3.11+, typed (mypy-clean), ruff-formatted. Pydantic v2 models for all agent I/O.
- Small pure functions for rules and scoring, each with a docstring citing the STANDARDS section it implements.
- Logs are JSON through the PII/secret redactor.
- UI: Jinja + HTMX + `theme.css` copied unchanged from `ui/prototype/styles.css`.
