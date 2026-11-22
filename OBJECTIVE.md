# Data Designer — Objective & Architecture

> Every claim a counterparty makes, checked before you sign.
> ContextCon 05 · BITS Pilani · "Services, Replaced"

## Objective

**The job today.** A mid-size Indian 3PL (the event's fictional client) pays compliance teams,
diligence firms and M&A advisors to decide whom to trust: new carriers and warehouse
subcontractors, JV partners, and acquisition targets. Analysts spend days per counterparty
checking claims by hand.

**What Data Designer does.** It takes the pack a counterparty sends the client (teaser, capability deck,
onboarding form, or its public website) and does the whole job:

1. **Find** (optional) — shortlist acquisition targets from live company data.
2. **Screen** — check a target's public claims for early red flags.
3. **Reach out** — draft an intro / teaser request; sent only after a person approves.
4. **Check** — extract every claim, verify it against live public records, and give each a verdict
   with an exact, dated source.
5. **Decide** — *Clear / Clear with conditions / Hold for a person / Reject*.
6. **Request** — turn every unsettled claim into a specific document to ask for
   (EPFO statement, lease deeds, GST addresses, customer reference); sent after approval.
7. **Re-check** — before the second meeting, re-run and show what changed.

**Tracks:** Trust and compliance + Investing (Open track only if organizers allow late test cases).

**Buyer:** the client's compliance/procurement team (vendors) and strategy/CFO office (targets, partners).

### Ground rules the service enforces

| Rule | How |
|---|---|
| Every fact has a source | Quote-locked citations: the passage/field must appear verbatim in the fetched content, with its date |
| No guessing | Deterministic verdict rules; the LLM only extracts claims and proposes passages |
| Wrong is worse than unknown | `cannot verify` + what is missing; headcount from profiles is a **lower bound only** |
| False premise needs evidence | No evidence either way = `unsupported premise`, not `false premise` |
| Irreversible actions need a person | Approval queue; emails go to a test inbox during the event |
| Exactly once, even after a kill | Append-only action journal + idempotency keys; evidence cache so restarts don't re-spend |
| Survives source failure | Retries with backoff, fallback chains, circuit breaker; total failure = `cannot verify — source unavailable` |
| Limits | Per-run credit budget and deadline; every call's cost logged from `X-Credits-Used` |
| Requirement changes | Output schema, verdict rules, critical claims and limits live in config |

**Verdicts:** verified · consistent (lower bound) · contradicted · self-reported · earliest evidence ·
stale · cannot verify · false premise · unsupported premise · projection (not checked)

**Evidence tiers:** independent public records > counterparty-provided documents > self-published claims.

**Pass mark:** ≥ 90% verdict accuracy on `tests/cases.jsonl`, zero wrong `verified`/`contradicted`,
100% of claims sourced or marked `cannot verify` with a reason, every action exactly once after a kill.

## Architecture

```
                        ┌──────────────────────────────┐
  Input pack ──────────►│ 0. Intake                    │  kickoff-kit format · PDF · PPTX · URL · text
  (or Find query)       └──────────────┬───────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │ 1. Claim extractor (LLM)     │  typed claims + exact span/page
                        └──────────────┬───────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │ 2. Entity resolver           │  company/identify + domain/city/year
                        │    unsure ──► HOLD (person)  │
                        └──────────────┬───────────────┘
                                       ▼
 ┌─────────────────────┐  ┌──────────────────────────────┐  ┌──────────────────────┐
 │ Config              │─►│ 3. Evidence collectors       │◄─│ Source gateway       │
 │ schema · rules ·    │  │    per claim type            │  │ retries · backoff ·  │
 │ critical claims ·   │  │    budget + deadline guard   │  │ fallback chains ·    │
 │ budget · deadline   │  └──────────────┬───────────────┘  │ circuit breaker      │
 └─────────────────────┘                 │                  └──────────┬───────────┘
                                         │                             │
                                         │       ┌─────────────────────┴──────────────┐
                                         │       │ Crustdata: company identify/enrich,│
                                         │       │ person enrich, job search,         │
                                         │       │ web search/fetch, watchers         │
                                         │       │ Other: registry pages, IBBI,       │
                                         │       │ sanctions lists, news, Internet    │
                                         │       │ Archive                            │
                                         │       └────────────────────────────────────┘
                                         ▼
                        ┌──────────────────────────────┐
                        │ 4. Quote lock                │  passage/field present verbatim? else drop
                        └──────────────┬───────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │ 5. Verdict engine (rules)    │  per claim type · evidence tier · staleness
                        └──────────────┬───────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │ 6. Decision + register +     │  Clear / Conditions / Hold / Reject
                        │    "ask them for this" list  │  + inconsistency check
                        └──────────────┬───────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │ 7. Approval queue (person)   │
                        └──────────────┬───────────────┘
                                       ▼
                        ┌──────────────────────────────┐
                        │ 8. Action executor           │  journal-before-send · idempotency key
                        │    email (test inbox)        │  → exactly once after kill/restart
                        └──────────────────────────────┘

  Cross-cutting stores
  ├─ Evidence ledger   every fact: source URL/field, exact passage, retrieval date, content hash
  ├─ Evidence cache    keyed by company ID + TTL — restarts and repeat counterparties cost nothing
  ├─ Cost ledger       credits per call (X-Credits-Used) + LLM tokens, per run
  ├─ Action journal    append-only; replayed on restart
  └─ Logs              every call, retry, fallback and decision (personal data redacted)

  Re-check: snapshot ─► re-run stages 3–6 ─► diff since last meeting
            (optionally triggered by a Crustdata person watch on founders/CXOs)
```

### Scaling notes (design question)

- **100× volume:** job queue + workers, evidence cache with TTL, Crustdata batch endpoints
  (person enrich is rate-limited, so it is the bottleneck).
- **Second client:** per-tenant config, cost ledger and journal; shared cache for public data only.
