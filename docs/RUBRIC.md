# Data Designer — Rubric cards (quick reference)

> Compact view of every rubric Data Designer applies. The canonical definitions and metric bands are in [STANDARDS.md](./STANDARDS.md); the machine version is `config/rubric.yaml`; `tools/rubric_check.py` reproduces every worked number. Version **R-2026.11.22-3** (R1/R2 weights unchanged since -2; R3 and Inference Strength added in -3).

---

## Card 0 · Verdict classes and credits (every claim)

| Class | Codes | Credit floor / ceiling |
|---|---|---|
| ✅ VERIFIED | V1 T1 field · V2 filed financials · V3 earliest evidence · V4 T1 lower bound · V5 reliable media (1 tier-A or 2 independent tier-B, own reporting) | 1.0 / 1.0 |
| 🟢 PARTIALLY VERIFIED | P1 licensed lower bound · P2 estimate band · P3 partial compound · P4 company-sourced media · P5 own public profile | 0.75 / 0.75 |
| 🟡 UNVERIFIED | U1 counterparty doc · U2 self-published / press release / sponsored · U3 lower bound below claim | 0.5 / 0.5 |
| ⏳ OUTDATED | O1 past freshness · O2 superseded / expired | 0.5 / 0.5 |
| ⚪ NOT VERIFIABLE | N1 no public source · N2 source down · N3 conflict · N4 entity · N5 budget · N6 captcha · N7 premise unknown | 0 / 1.0 |
| ❌ FALSE | F1 T1 · F2 own higher-authority doc · F3 premise · F4 2 reliable reports (or tier-A + T1) | 0 / 0; −1 point on C1 per non-critical FALSE |
| ⚫ NOT CHECKED | X1 projection · X2 opinion · X3 out of scope | excluded |

## Card 1 · Scoring math (all rubrics)

```
points 0–4 per criterion (bands from the metric dictionary; edge → better band)
composites = mean of components, rounded DOWN to the nearest 0.5
contribution = weight × points ÷ 4
floor   = missing inputs scored 0       ceiling = missing inputs scored 4
coverage = Σ weight × share of inputs with evidence ÷ 100
```

## Card 2 · R1 Scouting (Step 1)

| S1 constraint fit (soft) 15 | S2 growth 15 | S3 scale fit 10 | S4 leadership fit (public: LF-01, 02, 06) 15 | S5 org mix 5 | S6 market 10 | S7 PMF 10 | S8 regional fit 10 | S9 quality signals 10 |
|---|---|---|---|---|---|---|---|---|

- **Labels:** RECOMMEND (floor ≥ 60 and no risk flag) · CONSIDER (ceiling ≥ 60) · NOT RECOMMENDED (ceiling < 60).
- **Requirement cap:** an unmet requirement caps the label one level.

## Card 3 · R2 Decision (Step 4)

**Gates (first that fires wins):**
1. G1 entity < 0.85 → Hold
2. G2 not active → Reject (source down → Hold)
3. G3 sanctions confirmed → Reject (possible → Hold)
4. G4 critical FALSE by T1/T1-M → Reject
5. G5 out of mandate → Reject
6. G6 statements inconsistent → Hold
7. G7 coverage < 60% → Hold
8. **G8 false leadership credential → Hold (never auto-reject)**

| Criterion | Target wt | Vendor wt |
|---|---|---|
| C1 Claim integrity (deck fact-check) | 20 | 20 |
| C2 Financial health (grade A4…E0) | 20 | 15 |
| C3 Growth | 10 | 5 |
| C4 Market position | 10 | 0 |
| C5 Governance (company flags) | 5 | 10 |
| C6 Reputation & legal (confirmed only) | 5 | 10 |
| C7 Mandate fit, verified | 5 | 5 |
| C8 Operational capacity | 0 | 15 |
| C9 Leadership fit (LF-C) | 15 | 5 |
| C10 Regional fit (RG-C) | 5 | 10 |
| C11 Tech soundness (TC-C) | 5 | 5 |
| **Total** | **100** | **100** |

## Card 4 · Decision rule and wording

```
gate → its outcome · ceiling < 50 → negative · floor ≥ 75 → positive · floor ≥ 50 → positive with conditions · else hold
then: any query requirement UNMET → cap one level
```

| Outcome | Target | Vendor |
|---|---|---|
| positive | PURSUE | CLEAR |
| positive with conditions | PURSUE WITH CONDITIONS | CLEAR WITH CONDITIONS |
| hold | HOLD — MORE EVIDENCE NEEDED | HOLD FOR A PERSON |
| negative | PASS | REJECT |

- **Conditions:** asks ordered by the points each adds + open requirements + a mitigation for every criterion at ≤ 1.
- **What would change it:** the smallest set of asks crossing the next threshold (ties → the set that also closes a requirement).

## Card 5 · Query requirements (min-band)

**Met** if the criterion's floor ≥ min · **unmet** if its ceiling < min · **open** otherwise (becomes a condition).

"Acquirable" adds:
- C2 ≥ 3 (grade B);
- solvency ≥ 3;
- cash quality ≥ 2;
- no earnings-quality flag;
- C11 ≥ 2;
- C9 ≥ 2.5;
- C5 ≥ 3.

## Card 6 · Composites

| Composite | Formula | Verdict bands |
|---|---|---|
| **LF-C** leadership fit | mean(LF-01 roles, 02 domain, 03 scale, 04 track record, 05 bio integrity, 06 stability, 07 strategy fit) | FIT ≥ 3.5 · FIT WITH GAPS ≥ 2.5 · WEAK FIT ≥ 1.5 · NOT FIT < 1.5 · NOT ASSESSABLE if < 4 measurable |
| **RG-C** regional fit | mean(RG-02 target-region share, RG-03 network fit) | — |
| **TC-C** tech soundness | TC-01, or mean(TC-01, TC-02 engineering depth) if "tech-led" is claimed | — |
| **Health grade** | pillar = median of metric points (a 0 caps the pillar at 1); grade = mean of pillars | A ≥ 3.5 · B ≥ 2.75 · C ≥ 2.0 · D ≥ 1.25 · E; distress caps at C |
| **MK-C** market | segment CAGR parts (2/1/0) + growth vs competitor median parts (2/1/0) | — |

## Card 7 · R3 Research answer (FIND_LIST, RESEARCH_QA)

| Check | Definition | Required |
|---|---|---|
| Q1 Criteria compliance | rows passing every hard criterion on evidence ÷ rows returned | 100% (failing rows are removed) |
| Q2a Honest coverage | requested attributes answered with a class (incl. ⚪ + missing) ÷ all requested | 100% |
| Q2b Support | attributes ✅/🟢 ÷ all requested | reported |
| Q3 Completeness | rows returned ÷ rows requested | reported; **never padded** |
| Q4 Source strength | facts at T1/T1-M ÷ all facts | reported |
| Q5 Inference labelling | labelled inferences ÷ inferences | 100% |
| Q6 Premise check | premises checked ✅/❌/⚪ | all |

- **Status:**
  - **COMPLETE**: Q1, Q2a, Q3, Q5 at 100%, premises not FALSE.
  - **PARTIAL**: fewer qualifying rows, or Q2b < 75%; the memo says which.
  - **CANNOT ANSWER**: premise FALSE, zero qualifying rows, or a required source unavailable; with near-misses.
- **Confidence:**
  - **HIGH**: Q2b ≥ 90% and Q4 ≥ 30%.
  - **MEDIUM**: Q2b ≥ 75%.
  - **LOW**: otherwise.
- **Ranking ("the most"):** by the stated metric (e.g. deduped postings); ties → share → name.

## Card 8 · Inference Strength (IS) — analytical statements, e.g. "what hiring says about the next launch"

| Strength | Rule (per company × theme, window as resolved) |
|---|---|
| **STRONG** | n ≥ 5 deduped postings on the theme **and** share ≥ 25% of the company's engineering postings **and** corroborated by T1 (regulator) or T1-M own reporting within 12 months |
| **MODERATE** | (n ≥ 3 and share ≥ 10%), or STRONG thresholds met without corroboration |
| **WEAK** | n ≥ 1; shown only if the company has no MODERATE+ theme (max 1) |

- **Counting:** generic titles without theme words don't count, and each posting counts once.
- **Label:** always "INFERENCE — not a verified fact", with n, total, window, quotes and corroboration.

## Card 9 · Worked numbers (reproduced by `tools/rubric_check.py`)

| Case | Floor–ceiling | Label | What would change it |
|---|---|---|---|
| R1 Company C (sample) | 72.50–81.25 (coverage 92.9%) | RECOMMEND | — |
| R2 Company C (target) | 68.75–76.25 (coverage 97.0%) | PURSUE WITH CONDITIONS; leadership FIT WITH GAPS; tech requirement open | contract extract + tech evidence → 75.00 → PURSUE |
| R2 ACME (vendor, sample) | 72.50–87.50 (coverage 92.2%) | CLEAR WITH CONDITIONS | RC copies → 76.25 → CLEAR |

## Card 10 · Versioning

Any change to a weight, band, gate, credit, tolerance, media list, term mapping or IS/R3 threshold → new version + sha256. Runs keep their version; re-checks show both scores. `make golden` re-scores.
