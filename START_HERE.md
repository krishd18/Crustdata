# START HERE — using this package in a new Claude Code project

This zip is everything Claude Code needs to build **Data Designer** on your branch `hackathon-Rohan`: the 3-phase plan, specs, rubric and standards, agent contracts and test cases, config seeds, prompts, diagrams, the approved UI prototype, and a **local-only** `.env` (Crustdata key filled; Claude key and Gmail credentials asked at first run).

## 1. Put it in your repo

```bash
cd /path/to/your/clone-of-the-crustdata-repo
git fetch origin
git checkout hackathon-Rohan || git checkout -b hackathon-Rohan origin/main
unzip ~/Downloads/datadesigner-hackathon.zip -d /tmp/dd-pkg
rsync -av --ignore-existing /tmp/dd-pkg/datadesigner-hackathon/ ./   # won't overwrite organiser files
git check-ignore .env && echo ".env is ignored ✔"                      # MUST print the tick
```

If the organiser repo already has a `README.md` or `.gitignore`: merge our `.gitignore` lines into theirs (especially `.env`), and keep our README as `docs/DD_README.md` until Phase 3.

**Starting from an empty folder instead?** Unzip, `cd datadesigner-hackathon`, `git init -b hackathon-Rohan`, then `git remote add origin <organiser repo URL>`. Claude Code asks for the URL if it is missing.

## 2. Start Claude Code

```bash
claude
```

First message:

> Read CLAUDE.md, IMPLEMENTATION_PLAN.md and PROGRESS.md, then run /setup-secrets.

Claude Code checks `.env` and **asks you for**:

| What | Where to get it |
|---|---|
| Claude API key (`sk-ant-…`) | console.anthropic.com → API keys |
| Gmail address | the account Data Designer sends from |
| Gmail app password (16 letters) | Google Account → Security → 2-Step Verification (must be on) → App passwords |
| Test inbox | any address you read, e.g. `you+dd-test@gmail.com` |

Safest: when asked, run `make setup-secrets` in your own terminal; input is hidden and goes straight into `.env`. You can also paste the values into the chat; Claude Code writes them to `.env` with its Edit tool and does not echo them.

Then: `/phase 1` → `/phase 2` → `/phase 3`, using `/backtest <agent>`, `/e2e` and `/demo` along the way. The dev sub-agents in `.claude/agents/` (backtest-auditor, citation-auditor, chaos-tester, rubric-auditor, spec-guardian, ui-theme-reviewer) are picked up automatically.

## 3. See the UI now

Open `ui/prototype/index.html` in a browser (or `make ui-proto` → http://localhost:8090). It is the approved look, sampled from crustdata.com: dark theme, gradient hero, mega-menu, coloured step cards, analyst bubble. Phase 2 ports it to the app unchanged. Screenshots: `ui/prototype/screens/`.

## 4. Keys and mail (read this)

- Secrets live only in `.env`, never in a Markdown file: the hackathon repo must be **public**. `.gitignore` excludes `.env`; a pre-commit hook (`tools/secrets_check.py`) blocks Crustdata keys, Claude keys (`sk-ant-…`) and Gmail app passwords.
- The Claude key variable is `DD_ANTHROPIC_API_KEY`, so it never collides with Claude Code's own login.
- `MAIL_MODE=test` (default) sends every approved email to your test inbox. Switch to `live` only for the demo. Automated tests use Mailpit, so Gmail is never spammed.
- **Rotate the Crustdata and Claude keys and revoke the app password after the event,** since they were shared in chat.

## 5. What's inside

| Path | What |
|---|---|
| `IMPLEMENTATION_PLAN.md` | §0 first-run secrets · Phase 1 Foundation & agents · Phase 2 Verify & integrate (back-tests, wiring, memos, UI, Gmail) · Phase 3 Prove, harden & deliver |
| `CLAUDE.md` · `PROGRESS.md` | Claude Code project rules (incl. the secrets-intake protocol) · 3-phase checklist |
| `README.md` | judges' README draft (Phase 3 fills the numbers) |
| `ui/prototype/` | working UI prototype (`index.html`, `styles.css`, `app.js`, `data.js`) + 16 screenshots |
| `docs/ARCHITECTURE.md` | full system design |
| `docs/STANDARDS.md` | single source of truth: source tiers, 7 verdict classes, metric dictionary, query reasoning, rubrics, memo formats |
| `docs/RUBRIC.md` | rubric cards (R1, R2, R3, Inference Strength, composites, worked numbers) |
| `docs/AGENTS.md` | runtime agents A0–A15 + verification agents V1–V8: contracts and checks |
| `docs/TEST_PLAN.md` | test pyramid, record/replay, case catalogue, thresholds |
| `docs/WORKFLOW.md` | build loop, runtime flow, requirement-change and live-fix playbooks, submission checklist, demo scripts |
| `docs/WALKTHROUGH.md` | three requests end to end: acquirable-Maharashtra and the two organiser sample inputs |
| `docs/UI_THEME.md` | dark theme tokens sampled from crustdata.com, components, screens, porting rules |
| `docs/COMPETITION_BRIEF.md` | the competition: rules, deliverables, judging, timeline |
| `docs/diagrams/` | `architecture`, `agents`, `build_workflow` (.mmd + .png + .svg) |
| `config/` | rubric, verdicts, metrics, media allow-list, terms, themes, roles, mandate, sources, limits, **llm (Claude roles)**, **mail (Gmail)**, collectors, asks, mitigants, schema, email templates |
| `prompts/` | Claude prompt templates for every LLM step |
| `tests/cases.jsonl` | 42 seed cases (2 organiser samples + variants + hard + robustness incl. Claude and Gmail faults + change drills) |
| `tools/` | `setup_secrets.py` (first-run intake), `rubric_check.py` (reference scorer), `secrets_check.py` |
| `.claude/agents/` · `.claude/skills/` | dev sub-agents · `/setup-secrets` `/phase` `/backtest` `/e2e` `/demo` |
| `Makefile` · `pyproject.toml` | targets and dependencies (`anthropic` SDK) |
| `.env` · `.env.example` · `.gitignore` | local secrets (never commit) · template · ignore rules |
