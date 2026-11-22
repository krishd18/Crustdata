# Data Designer — Agent catalogue and contracts

> Runtime agents (A0–A15) do the job; verification agents (V1–V8) prove each one works before and after wiring. Every agent: Pydantic I/O models, a CLI (`python -m datadesigner.agents.aNN --in <fixture.json> --mode replay`), unit tests, a contract test, and a back-test threshold in `verification/thresholds.yaml`. Diagram: [`diagrams/agents.mmd`](./diagrams/agents.mmd).

---

## 1. Shared contract

```python
class AgentContext(BaseModel):         # injected, never built inside an agent
    run_id: str; clock: Clock; config: Config; stores: Stores
    crustdata: CrustdataClient; claude: ClaudeClient; mail: MailProvider; web: WebClient; budget: Budget; log: Logger

class BaseAgent(Generic[I, O]):
    name: str; input_model: type[I]; output_model: type[O]
    deterministic: bool                 # False only where Claude is called (still schema-bound + cached)
    def run(self, inp: I, ctx: AgentContext) -> O: ...
```

Common types (in `datadesigner/core/types.py`):

| Type | Fields |
|---|---|
| `Evidence` | evidence_id, source (`crustdata.company_enrich`, `mca`, `gst`, `media:<outlet>`…), url_or_endpoint, passage_or_field, value, record_date, retrieved_at, content_sha256, tier (`T1`/`T1-M`/`T2`/`T3`/`T4`), media_tier (`A`–`D`/null) |
| `Claim` | claim_id, kind (`business`/`bio`/`tech`/`premise`/`criterion`), type, subject, text, value, unit, as_of, critical, span{doc_id,page,start,end}, slide |
| `Verdict` | claim_id, cls (`VERIFIED`/`PARTIALLY_VERIFIED`/`UNVERIFIED`/`OUTDATED`/`NOT_VERIFIABLE`/`FALSE`/`NOT_CHECKED`), code (V1…X3), evidence_ids[], missing, credit_floor, credit_ceiling, rule_id |
| `Inference` | statement, theme, strength (`STRONG`/`MODERATE`/`WEAK`), n_supporting, share, corroboration_ids[], quotes[] |
| `Metric` | id, value, unit, period, points, band, quality_tag, inputs[{name,value,evidence_id}], formula |
| `Cost` | credits, llm_tokens_in, llm_tokens_out, inr |

Errors: `SourceUnavailable` → N2 · `BudgetExhausted` → N5 · `EntityUnresolved` → N4/HOLD · `ParseFailed` → "could not parse" (never a guess) · `ContractError` (400 from an API) → fail fast, surface in logs.

---

## 2. Runtime agents

### A0 · Orchestrator (state machine; `datadesigner/orchestrator`)
- **In:** `RunRequest{text|mandate|pack, family?, limits}` · **Out:** `Run{run_id, state, stages[], memo_ids[]}`
- Routes the families (plan §4.2B), writes a checkpoint after every stage, resumes on restart, joins duplicate in-flight requests, runs the journal reconciler first.

### A1 · Query Reasoner (Claude `reason` role + `config/terms.yaml`)
- **In:** `QueryInput{text, client_profile, now}`
- **Out:** `ReasoningCard{family, rows[{phrase, intent, parameters[{name, metric_ids, operator, value, role, measured_at, origin: from_query|default|assumed_confirm|proposed_confirm}]}], premises[], time_windows[{phrase, start, end}], n_requested, questions[≤3]}` + `Mandate` or `ResearchPlan`
- **Rules:**
  - Map every phrase to a term-library entry when one exists. Anything else is `proposed_confirm`.
  - Numbers come only from the query, config or the client profile, never invented.
  - Resolve relative time with `clock`.
  - Extract implicit premises ("that listed on NSE in October") for checking.
- **Prompt:** `prompts/query_reasoner.md` · **Back-test:** family accuracy, parameter recall, invented numbers = 0, determinism.

### A2 · Scout (deterministic, Crustdata)
- **In:** `Mandate|ResearchPlan` · **Out:** `CandidateSet{candidates[{crustdata_company_id, name, domain, fields, stream_ids[]}], funnel{stream→count}, excluded[{id, reason, evidence_id}], cost}`
- **Steps:**
  1. Validate filter values with autocomplete (cached).
  2. Compile filters (never `>=`; use `=>`).
  3. Run the streams:
     - A: company search;
     - B: reliable news;
     - C: jobs in a region;
     - D: registry (operator);
     - E: watcher;
     - F: client lists;
     - G: people in a region, grouped by employer.
  4. Paginate by cursor.
  5. Dedup by id/domain/CIN, with the lookalike guard (fuzz ≥ 90 but different domain → kept apart, flagged).
  6. Pre-score.
  7. Budgeted enrich, ≤ 25 per call.
- **Back-test:** hard-filter compliance 100%, no duplicates, no lookalike merges.

### A3 · Entity Resolver (deterministic)
- **In:** `EntityHints{name, domain?, cin?, gstin?, city?, year?, profile_url?}` · **Out:** `ResolvedEntity{crustdata_company_id?, cin?, gstin?, score, status: resolved|ambiguous|unresolved, candidates[]}`
- **Score weights:** domain 0.35 · CIN/GSTIN 0.35 · name fuzz 0.15 · city 0.10 · year 0.05.
- **Status:** ≥ 0.85 resolved · 0.60–0.85 ambiguous (HOLD) · < 0.60 unresolved (N4).

### A4 · Deck Intake & Claim Extractor (parse + Claude `reason` role)
- **In:** `Pack{files[]}` · **Out:** `ClaimSet{docs[{doc_id, pages[{page, text, sha256}]}], claims[Claim]}`
- **Parsing:** PyMuPDF/pdfplumber (OCR fallback), python-pptx (slide text and notes), openpyxl.
- **Extraction:** Claude extracts business, bio and tech claims with exact spans; every span is re-checked against the page text.
- **Guards:** injection guard. Projections and opinions are typed for NOT CHECKED.

### A5 · Evidence Collector (deterministic + Claude query proposals)
- **In:** `ClaimVerdictRequest{claims[], entity}` · **Out:** `EvidenceBundle{by_claim{claim_id: Evidence[]}, unavailable[{claim_id, source, reason}]}`
- **Collectors** (from `config/collectors.yaml`):
  - `crustdata_company`, `crustdata_people`, `jobs`;
  - `media` (`web/search/live` news restricted to the `media.yaml` allow-list, then `web/enrich/live` fetch, then the own-reporting test: byline, labels, near-duplicate shingles ≥ 70%, quote-only → P4);
  - `registry` (operator extracts for MCA/GST/EPFO/VAHAN);
  - `wayback`, `docs`.
- **Order and caching:** critical claims first; the budget is checked before each call; results cached.

### A6 · Quote-Lock Verifier (deterministic)
- **In:** `EvidenceBundle` · **Out:** `LockedEvidence{accepted[], dropped[{evidence, reason}]}`
- `normalize` → `lock(passage)` or `lock_field(path, value)`. Claude (`classify` role) may *propose* a passage from a long page; acceptance is purely deterministic.

### A7 · Verdict Engine (deterministic, `config/verdicts.yaml`)
- **In:** `claims[] + LockedEvidence + entity` · **Out:** `ClaimVerdicts{verdicts[Verdict], counts_by_class}`
- **Rules:** implements the first-match procedure (STANDARDS §2.2) and rules R-01…R-21 (ARCHITECTURE §11). Tolerances from config.
- **Safety assertions:** FALSE requires `entity.status == resolved` and a quote-locked contradicting passage. No FALSE from T2 counts. No FALSE from a single media report.

### A8 · Financial Analyst (parse + deterministic)
- **In:** `statements (docs) + registry extracts` · **Out:** `FinancialReport{periods[], statements{}, fsv[{id, status, detail}], metrics[Metric], pillars{}, grade, flags[]}`
- **Parsing:** XBRL if present, else table extraction to JSON (Claude assist). **Accepted only if FSV-01…03 footing checks pass.**
- **Computation:** metrics per the dictionary (STANDARDS §4.5), then pillars → grade.

### A9 · People & Leadership (deterministic + Crustdata)
- **In:** `company + bio claims + roles.yaml` · **Out:** `PeopleReport{people[{name, role, match_confidence, bio_verdicts[], directorships[], screening{sanctions, pep, debarment}, adverse{confirmed[], unconfirmed[]}}], lf{LF-01…LF-07, composite, verdict, gaps[]}}`
- **Steps:** P1–P9 (ARCHITECTURE §14). Fairness exclusions are enforced in code: the inputs never include age, gender, religion, caste, origin, family or institution prestige.

### A10 · Market & Region Analyst (deterministic + quote-locked citations)
- **In:** `company(s) + mandate region + client network` · **Out:** `MarketRegionReport{competitors[], mk_c, market_size_range{min,max,median,sources[]}, regions[{state, zone, fp01, evidence[]}], rg02, rg03, rg_c, concentration}`

### A11 · Research Analyst (deterministic + Claude classification/themes)
- **In:** `ResearchPlan + CandidateSet` · **Out:** `ResearchAnswer{status: COMPLETE|PARTIAL|CANNOT_ANSWER, rows[{entity, attributes{name: {value, verdict}}, criteria{name: pass|fail|unknown}}], excluded_near_misses[], inferences[Inference], premise_checks[], caveats[], r3{Q1…Q6}}`
- **Rules:**
  - A row is kept only if every hard criterion passes on evidence.
  - Never pad to N.
  - Classifiers (B2B, fintech) return `{label, confidence, quoted_passage}`. The passage must be quote-locked, and "ambiguous" → excluded and listed.
  - Inferences use the Inference Strength rubric (STANDARDS §2.4) and are always labelled.

### A12 · Decision Engine (deterministic)
- **In:** `all reports + mandate requirements + rubric.yaml` · **Out:** `Decision{rubric_id, version, sha256, gates[], criteria[{id, value, points_floor, points_ceiling, weight}], floor, ceiling, coverage, rule_applied, requirements[{name, status}], label, conditions[], what_would_change[], drivers[]}`
- Must match `tools/rubric_check.py` exactly (V7).

### A13 · Memo Composer (Jinja + Claude smoothing under number lock)
- **In:** `Run outputs` · **Out:** `Memo{type: MARKET_IM|COMPANY_IM|RESEARCH_MEMO, id, status, sections[], md, html_path, pdf_path, json}`
- Templates follow STANDARDS §7. The number lock drops any sentence with an untraceable number, date or name.

### A14 · Outreach & Mail (deterministic)
- **In:** `Decision|Screen + asks + templates` · **Out:** `Action[]` (journal)
- **Steps:**
  - drafter (slots only from ledger facts, labelled class);
  - policy guard (business email only, test inbox, caps, opt-out, Hold restrictions);
  - approval queue;
  - executor: `action_id = sha256(run|template|recipient|content)`, Message-ID `<{action_id}@datadesigner.local>` + `X-DD-Action-Id`, journal intent → pre-check Sent folder → send → IMAP reconcile, and the same reconcile on restart;
  - providers (`config/mail.yaml`): **Gmail** (smtp.gmail.com:587 STARTTLS, app password; IMAP `[Gmail]/Sent Mail` search by `rfc822msgid`) and **Mailpit** (all automated tests); `MAIL_MODE=test` redirects to `TEST_INBOX` with `X-DD-Original-To`; `MAIL_DAILY_CAP`;
  - inbound routing (`AWAITING_PACK` → CHECK; after decision → RECHECK) via IMAP `INBOX` replies matched on `In-Reply-To`.

### A15 · Monitor / Re-check (deterministic)
- **In:** `snapshot + triggers (schedule, watcher webhook, new documents)` · **Out:** `Diff{claims_changed[], metrics_moved[], people_changes[], score_before/after, label_before/after}`

---

## 3. Verification agents (back-testers)

| ID | Module | Inputs | Checks | Output |
|---|---|---|---|---|
| V1 | `verification/v1_contract.py` | every agent + edge payloads (Hypothesis) | I/O schema validity, error types, no crash | `reports/backtest/v1.json` |
| V2 | `v2_golden.py` | `tests/golden/*.expected.yaml` + cassettes | classes, rows, labels, scores vs expectations | per-case diff |
| V3 | `v3_adversarial.py` (Claude `adversarial` role; outputs frozen into fixtures) | templates in `prompts/adversarial_case_generator.md` | generates lookalikes, duplicates, fake bios, injection, unit traps, sponsored-only claims, absent-from-list awards; asserts zero wrong VERIFIED/FALSE | generated cases + results |
| V4 | `v4_citation.py` | memos + ledger + blobs | verbatim lock, record date, tier, media tier, number lock | per-memo pass/fail |
| V5 | `v5_chaos.py` + `tools/fault_proxy.py` | orchestrator + Mailpit (never Gmail) | 50 kill trials, 429/500/529/timeout/slow injection, SMTP drop after DATA | exactly-once + resume stats |
| V6 | `v6_cost.py` | cost ledger + `X-Credits-Used` + `/account/usage/events` | ledger parity, budget-cut behaviour, deadline, ₹ per job | cost report |
| V7 | `v7_rubric.py` | decisions + `tools/rubric_check.py` | exact parity, determinism ×3, version stamps | parity report |
| V8 | `v8_memo_judge.py` (Claude `judge` role, advisory) | memos | suggestion first, each "why" names a metric, inferences labelled, plain language | advisory notes (never changes verdicts) |

The dev-time Claude Code sub-agents (`.claude/agents/`) wrap these: `backtest-auditor` (V1/V2/V3), `citation-auditor` (V4), `chaos-tester` (V5), `rubric-auditor` (V7), plus `spec-guardian` and `ui-theme-reviewer`.
