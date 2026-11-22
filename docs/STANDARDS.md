# Data Designer — Standards: sources, verdict classes, metrics, query reasoning, rubrics, Information Memo

> Standard version **S-2026.11.22-3** (adds research answers: analytical statements & Inference Strength §2.4, R3 §6.8, Research Memo §7.5, research terms §5.2). This file is the single source of truth for how Data Designer trusts a source, classifies a claim, reads a query, measures a company, scores it and writes the memo. Config mirrors it 1:1: `media.yaml`, `verdicts.yaml`, `metrics.yaml`, `terms.yaml`, `roles.yaml`, `rubric.yaml`, `im_templates/`. Every worked number here is reproduced by `tools/rubric_check.py`.
> Architecture: [`ARCHITECTURE.md`](./ARCHITECTURE.md) · End-to-end example: [`WALKTHROUGH.md`](./WALKTHROUGH.md)

---

## 1. The process in one table

| Step | You give | Data Designer does | You get | Standard used | You decide |
|---|---|---|---|---|---|
| **R · Research answer** | A question ("Which Indian fintechs are hiring the most engineers this quarter…?") or a list request ("Find ten Indian B2B software companies…") | Reasons over the words (§5) → resolves time windows and premises → finds and checks each row → labels inferences (§2.4) | **Research Memo** (§7.5): answer box, table, inferences with strength, sources | §2 · §3 · §5 · §6.8 R3 | Confirm the reading |
| **1 · Scout & finalise** | A query ("acquirable logistics companies in Maharashtra") | **Reasons** over each word → parameters, metrics, thresholds (§5) → searches → constraint gate → R1 | **Market IM**: market view + shortlist with R1 scorecards | §3 sources · §4 metrics · §5 reasoning · §6.3 R1 | Confirm the reading; pick companies |
| **2 · Screen & reach out** | Your pick | Public-data screen, red flags, drafts the intro / teaser request | Screen summary + email for approval | §2 · §3 | Approve the email |
| **3 · Check** | Their deck and documents | **Fact-checks every deck claim**, verifies financials, checks people and **leadership fit** | Slide-by-slide claim register + metric table + leadership card | §2 · §3 · §4 | — |
| **4 · Decide** | — | Gates → R2 → floor–ceiling → fixed rule → query requirements | **Company IM**: suggestion + full "why" incl. leadership and regional fit | §6.4–6.6 · §7 | Accept or override (with reason) |
| **5 · Act** | Approval | Sends document requests / outreach exactly once | Sent log | — | Approve each email |
| **6 · Re-check** | Time or new documents | Re-verifies changed evidence; re-scores with the same rubric version | IM update: what changed and why | same version | Re-decide if the label moved |

---

## 2. Verdict classes

Every claim lands in **exactly one** of seven classes. The class is set by the procedure in §2.2. It carries a reason code, the quoted source with its record date and reliability tier, and, if unsettled, the document that would settle it.

### 2.1 The seven classes

| Class | Badge | Meaning | Reason codes | Credit (floor / ceiling) |
|---|---|---|---|---|
| **VERIFIED** | ✅ | An independent, reliable record states the same fact | **V1** matches a T1 public-record field · **V2** matches filed financials (MCA AOC-4 / exchange) · **V3** "since YEAR": earliest independent evidence ≤ YEAR · **V4** T1 lower bound ≥ claimed number (e.g. EPFO members) · **V5** reported as fact by reliable media (§3.2: one tier-A outlet's own reporting, or two independent tier-B reports) | 1.0 / 1.0 |
| **PARTIALLY VERIFIED** | 🟢 | Independent data supports it but cannot prove all of it | **P1** licensed-data lower bound ≥ claim · **P2** inside an independent estimate band · **P3** compound claim partly verified (fraction stated) · **P4** reliable media report that is itself company-sourced ("the company said") · **P5** consistent with the person's own public professional profile | 0.75 / 0.75 |
| **UNVERIFIED (SELF-REPORTED)** | 🟡 | Only the company (or its press release) says it | **U1** counterparty document only · **U2** self-published: deck, website, press release, sponsored or brand content · **U3** independent lower bound below the claim | 0.5 / 0.5 |
| **OUTDATED** | ⏳ | Evidence exists but is too old, or the claim presents an old figure as current | **O1** best evidence older than the freshness window · **O2** superseded figure or expired certificate | 0.5 / 0.5 |
| **NOT VERIFIABLE** | ⚪ | No source can settle it now | **N1** no public source exists for this fact · **N2** source down after retries/fallbacks · **N3** reliable sources conflict · **N4** entity not resolved · **N5** budget/deadline · **N6** captcha-gated, no extract · **N7** premise has no evidence | 0 / 1.0 |
| **FALSE** | ❌ | A higher-authority source states otherwise | **F1** contradicted by a T1 record · **F2** contradicted by the company's own higher-authority document (audited FS, GST registrations, lease deeds) · **F3** a question's premise is contradicted · **F4** contradicted by reliable media: two independent tier-A/B own reports, or one tier-A report consistent with T1 | 0 / 0; a non-critical FALSE costs 1 point on C1 |
| **NOT CHECKED** | ⚫ | Not a checkable statement of fact | **X1** projection or plan · **X2** opinion or marketing · **X3** outside the mandate | excluded |

### 2.2 Classification procedure (first match wins)

1. Projection, opinion or out of scope → ⚫ (X1–X3).
2. Entity match < 0.85 → ⚪ (N4).
3. Reliable sources disagree and the precedence order (§3.4) cannot resolve it → ⚪ (N3).
4. A higher-authority source contradicts the claim beyond tolerance → ❌ (F1, F2, F4).
5. A T1 record or filing matches, or reliable media report it as own reporting → ✅ (V1–V5).
6. Licensed data, an estimate band, company-sourced media, a public profile, or part of a compound claim supports it → 🟢 (P1–P5).
7. Best supporting evidence is past its freshness window → ⏳ (O1–O2).
8. Only the company's own material supports it → 🟡 (U1–U3).
9. Nothing settles it → ⚪ (N1, N2, N5–N7), naming the missing document.

**Safety rules.** FALSE needs a resolved entity and a quote-locked contradicting passage. Licensed-data counts never make a claim FALSE. A single media report never makes a claim FALSE on its own. Absence from a list is not a contradiction.
**Tolerances** (`verdicts.yaml`): money ±2% (lakh/crore rounding allowed) · counts ±5% · "since" ±1 year · names after normalisation.

### 2.3 Criteria checks in list answers

In FIND_LIST and RESEARCH_QA answers, each requested criterion ("founded since 2023", "grew by half in six months", "Indian", "B2B") is a claim about the row, classed like any other. A row is returned only if every **hard** criterion is ✅ or 🟢 with evidence. A criterion that is ❌ or ⚪ removes the row, which is listed under "near-misses" with the binding criterion. Rows are never padded to reach the requested number.

### 2.4 Analytical statements (inferences) and Inference Strength (IS)

Some questions ask for interpretation ("what does their hiring say about what each will launch next?"). Interpretations are **not claims of fact**. They are shown as **INFERENCE — not a verified fact**, with a strength computed by a fixed rule:

| Input | Definition |
|---|---|
| n | deduped postings in the window whose title, or a quote-locked description passage, matches the theme (`config/themes.yaml`); generic titles without theme words don't count |
| share | n ÷ the company's deduped engineering postings in the same window |
| corroboration | T1 (e.g. regulator approval or licence) or T1-M own reporting within 12 months stating the company is building or launching in that theme |

| Strength | Rule |
|---|---|
| **STRONG** | n ≥ 5 **and** share ≥ 25% **and** corroborated |
| **MODERATE** | (n ≥ 3 and share ≥ 10%), or STRONG thresholds without corroboration |
| **WEAK** | n ≥ 1; shown only when the company has no MODERATE+ theme (max one) |

**Template:** "Hiring suggests {company} is building {theme} — INFERENCE ({strength}): {n} of {total} engineering postings since {start}, e.g. '{quoted title}'; {corroboration or 'no independent corroboration'}."

**Dedup:** the same posting across sources or reposts (same company, normalised title, city, 14-day window) counts once. **Caveat line, always shown:** "Job postings indicate intent to hire, not hires made."

---

## 3. Source reliability

### 3.1 Tiers

| Tier | What | Can make a claim ✅ VERIFIED? | Can make it ❌ FALSE? |
|---|---|---|---|
| **T1** | Independent public records: MCA, GST, EPFO, VAHAN, exchange filings, courts, regulators, sanctions lists | Yes (V1–V4) | Yes (F1) |
| **T1-M** | **Reliable media**: allow-listed outlets, own reporting only (§3.2) | Yes for events, appointments, deals, contracts, facilities (V5); financial figures only if the article cites filings | Only with two independent reports, or one tier-A report consistent with T1 (F4) |
| **T2** | Licensed data (Crustdata): headcount, profiles, jobs, traffic, technographics | No: PARTIALLY VERIFIED at most (P1, P2, P5) | No |
| **T3** | Counterparty documents: audited FS, lease deeds, RC copies, contracts | Only when matched to T1 (otherwise U1); a higher-authority T3 can contradict a lower one (F2) | F2 only |
| **T4** | Self-published: deck, website, **press releases, sponsored / brand / partner content** | No (U2) | No |

### 3.2 Reliable-media rules (`media.yaml`, owned by the client's compliance team)

| Media tier | Default list (editable) | Weight |
|---|---|---|
| **A** | Wire services (PTI, Reuters, Bloomberg) and national business dailies (The Economic Times, Business Standard, Mint, The Hindu BusinessLine, Financial Express) | One own report verifies an event |
| **B** | National general dailies and established business/startup news sites, plus recognised logistics trade publications on the list | Two independent own reports verify an event |
| **C** | Anything not on the list: regional sites, blogs, aggregators, social posts | Context and leads only |
| **D** | Press-release distribution, sponsored, "brand connect", partner or advertorial content, the company's own newsroom | Treated as **T4** (self-published), whatever site it appears on |

**Own-reporting test.** An article counts as own reporting only if all of these hold:
- it has a staff or agency byline;
- it carries none of the labels "press release", "sponsored", "brand connect", "partner content" or "advertorial";
- it is not a near-duplicate (≥ 70% shingle overlap) of the company's press release, or of the same text published on 3+ sites within 48 hours;
- the fact is stated by the outlet, not only inside a quote from the company. A quote-only fact is **P4**.

**Independence.** Two reports are independent only if they are not near-duplicates and do not rely on the same single source.

**Corrections.** The latest version of an article is used, and any correction note is quote-locked too.

**People.** Adverse media about a person counts as *confirmed* only from T1 (court or regulator) or T1-M. Anything else is shown as an "unconfirmed mention" and is never scored.

### 3.3 Claim type × source matrix (what can verify what)

| Claim type | ✅ VERIFIED by | 🟢 PARTIALLY VERIFIED by |
|---|---|---|
| Identity, legal status, incorporation, directors | T1 (MCA, GST) | — |
| Financial figures | T1 filings (V2); T1-M citing filings (V5) | T1-M company-sourced (P4); T2 estimate band (P2) |
| Headcount | T1 EPFO (V4) | T2 profiles (P1) |
| Footprint, sites, fleet | T1 GST by PAN, VAHAN sample (V1) | T2 addresses, staff, openings; T3 e-way bills (P3) |
| Funding, M&A, appointments, contract wins, facility openings | T1 (MCA allotment/filings) or T1-M (V5); the customer's own announcement (independent of the counterparty) | T1-M company-sourced (P4) |
| Customers | Customer's own statement, T1-M, reference call recorded by the reviewer | — |
| Technology | Independent platform listing (app store, partner marketplace integration page) or T1-M (V5) | Technographics, job posts requiring the tool, public API docs, demo observed by the reviewer (P) |
| Leadership bios | T1 (MCA directorships, appointments); T1-M; the prior employer's own official page | Person's public profile (P5) |
| Awards, certifications | Issuer's register or official winners page | — |

### 3.4 Precedence when sources disagree

T1 › T1-M (tier A, or two tier-B) › T3 higher authority (audited FS, registrations) › T2 › T3 lower authority › T4.
- T1-M against T1: T1 wins, and the conflict is shown.
- Tier-A media against tier-A media: ⚪ N3 → ask.

---

## 4. Metric dictionary

### 4.1 Conventions

- **Format:** `ID · name · formula · unit · period · source priority · freshness · bands · direction`.
- **Bands:** five bands → 0–4 points (4 Strong · 3 Good · 2 Adequate · 1 Weak · 0 Critical). ↑ = higher is better.
- **Edges:** a value on a band edge goes to the **better** band.
- **Composites:** the mean of component points, **rounded down to the nearest 0.5**.
- **Units:** ₹ crore (1 decimal); ratios to 2 decimals; % to 1 decimal. USD estimates are converted at a dated FX rate (shown).
- **Period:** latest audited FY (April–March); growth uses up to 3 audited years; TTM for listed companies.
- **Quality tag:** `audited-filed` › `audited-provided` › `unaudited` › `derived` › `estimate`.
- **Missing:** `—` plus a reason code; scored 0 in the floor and 4 in the ceiling.
- **Freshness:** registry 90 d · financial statements 18 months after FY end · Crustdata 60 d from `updated_at` · reliable media 24 months for events, 5 years for adverse items · market reports 24 months.

### 4.2 Identity & legal (pass/fail; gates)

ID-01 legal status: MCA status and GSTIN active · ID-02 years operating: MCA incorporation date · ID-03 legal form: CIN type / LLPIN · ID-04 registered-office state: MCA address (the CIN's state code is the state at incorporation, so it is only a fallback) · ID-05 industry: Crustdata taxonomy (current) + NIC code in the CIN (at incorporation).

### 4.3 Region of operation (RG) and footprint (FP)

| ID | Metric | Definition | Dir | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|
| FP-01 | Operates in state S | **Yes** if a GSTIN with S's state code (e.g. 27 Maharashtra, 07 Delhi) is active (T1), or ≥ 2 of: site address in S · ≥ 10 staff located in S · ≥ 3 openings in S in 90 days (T2/T4). One weak signal = Unknown | | pass/fail | | | | |
| FP-02 | State footprint share | mean of available shares: staff in S · openings in S · sites in S · fleet registered in S (T3/T1 at CHECK) | ↑ | ≥ 60% | 40–60 | 25–40 | 10–25 | < 10 |
| RG-01 | **Regions of operation** | every state with FP-01 = Yes, grouped into zones (North, West, South, East, North-East, Central), each with its evidence and share | | context + IM map | | | | |
| RG-02 | Target-region share | FP-02 for the mandate's state or zone | ↑ | ≥ 60% | 40–60 | 25–40 | 10–25 | < 10 |
| RG-03 | Network fit | **Target:** share of the company's operating states where the client is absent or weak (client network from the kickoff kit) · **Vendor:** share of the client's required states/lanes the vendor operates in | ↑ | T ≥ 50% · V ≥ 90% | T 30–50 · V 75–90 | T 15–30 · V 50–75 | T 5–15 · V 25–50 | T < 5 · V < 25 |
| RG-04 | Regional concentration | largest state's share of operations | — | context; risk note if > 85% | | | | |
| **RG-C** | **Regional fit (composite)** | mean(RG-02, RG-03), rounded down to 0.5; only RG-03 if the mandate names no region; only RG-02 if the client network is unknown | ↑ | | | | | |

### 4.4 Scale

SC-01 revenue (₹ cr) · SC-02 headcount (lower bound) · SC-03 fleet (RC copies at CHECK) · SC-04 warehouse area (lease deeds at CHECK).

### 4.5 Financial metrics

| ID | Metric | Formula | Dir | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|---|
| GR-01 | Revenue 3-yr CAGR | (Rev₀ ÷ Rev₋₃)^(1/3) − 1 | ↑ | ≥ 25% | 15–25 | 8–15 | 0–8 | < 0 |
| GR-02 | Headcount YoY | `headcount.growth_percent` yoy | ↑ | ≥ 30% | 15–30 | 5–15 | 0–5 | < 0 |
| PR-01 | EBITDA margin | EBITDA ÷ revenue | ↑ | ≥ 15% | 10–15 | 6–10 | 3–6 | < 3 |
| PR-02 | PAT margin | PAT ÷ revenue | ↑ | ≥ 8% | 5–8 | 2–5 | 0–2 | < 0 |
| PR-03 | ROCE | EBIT ÷ (TA − CL) | ↑ | ≥ 20% | 15–20 | 10–15 | 5–10 | < 5 |
| PR-04 | ROE | PAT ÷ avg equity | ↑ | ≥ 18% | 12–18 | 8–12 | 0–8 | < 0 |
| LQ-01 | Current ratio | CA ÷ CL | ↑ | ≥ 1.75 | 1.5–1.75 | 1.2–1.5 | 1.0–1.2 | < 1.0 |
| LQ-02 | Quick ratio | (CA − inventory) ÷ CL | ↑ | ≥ 1.25 | 1.0–1.25 | 0.8–1.0 | 0.6–0.8 | < 0.6 |
| SV-01 | Debt / equity | borrowings ÷ equity | ↓ | ≤ 0.3 | 0.3–0.6 | 0.6–1.0 | 1.0–2.0 | > 2.0 |
| SV-02 | Net debt / EBITDA | (borrowings − cash) ÷ EBITDA; net cash → 4 | ↓ | ≤ 1 | 1–2 | 2–3 | 3–4 | > 4 |
| SV-03 | Interest coverage | EBIT ÷ interest | ↑ | ≥ 6 | 4–6 | 2.5–4 | 1.5–2.5 | < 1.5 |
| SV-04 | DSCR | (PAT + D&A + interest) ÷ (interest + principal due) | ↑ | ≥ 2.0 | 1.5–2.0 | 1.25–1.5 | 1.0–1.25 | < 1.0 |
| WC-01 | DSO (days) | receivables ÷ revenue × 365 | ↓ | ≤ 45 | 45–60 | 60–90 | 90–120 | > 120 |
| WC-02 | Cash conversion cycle (days) | DSO + DIO − DPO | ↓ | ≤ 30 | 30–45 | 45–75 | 75–100 | > 100 |
| CQ-01 | Cash conversion | CFO ÷ EBITDA | ↑ | ≥ 90% | 75–90 | 60–75 | 40–60 | < 40 |
| CQ-02 | FCF margin | (CFO − capex) ÷ revenue | ↑ | ≥ 6% | 3–6 | 0–3 | −3–0 | < −3 |
| EQ-01 | Altman Z″ (non-manufacturing) | 6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA + 1.05·BVE/TL | ↑ | > 2.6 | — | 1.1–2.6 | — | < 1.1 |
| EQ-02 | Beneish M-score (8-var) | standard model, 2 years | ↓ | ≤ −2.22 | — | −2.22 to −1.78 | — | > −1.78 |
| EQ-03 | Piotroski F-score | 9 binary tests | ↑ | 8–9 | 6–7 | 4–5 | 2–3 | 0–1 |
| AL-01 | Asset intensity | fixed assets ÷ revenue (context; used by "asset-light") | ↓ | ≤ 0.15 | 0.15–0.25 | 0.25–0.4 | 0.4–0.6 | > 0.6 |

**Health grade.** Pillars: Growth (GR-01) · Profitability (PR) · Liquidity (LQ) · Solvency (SV) · Working capital (WC) · Cash quality (CQ) · Earnings quality (EQ).
- Pillar = median of its metrics' points; any metric at 0 caps its pillar at 1.
- Grade = mean of the pillars: **A ≥ 3.5 · B ≥ 2.75 · C ≥ 2.0 · D ≥ 1.25 · E < 1.25**.
- A Z″ in distress or a flagged M-score caps the grade at C.

### 4.6 Technology soundness (TC)

| ID | Metric | Definition | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|
| TC-01 | Tech-claim verification | class credits over all technology claims (WMS/TMS, apps, APIs, telematics/IoT, automation, AI); evidence per §3.3 | ≥ 90% | 75–90 | 60–75 | 40–60 | < 40 |
| TC-02 | Engineering depth (only if "tech-led" is claimed) | engineering + data share of headcount (`headcount.by_role_percent`) | ≥ 12% | 8–12 | 5–8 | 2–5 | < 2 |
| **TC-C** | **Tech soundness** | TC-01; or mean(TC-01, TC-02) when tech-led positioning is claimed (rounded down to 0.5) | | | | | |

### 4.7 Leadership fit (LF): is the team fit for this company?

| ID | Metric | Definition | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|
| LF-01 | Role coverage | required roles (`roles.yaml`) for the model and stage, filled by **distinct** people: CEO · CFO/finance head · COO/ops head · sales/BD head; plus a tech head if "tech-led" is claimed; plus a cold-chain/quality head if cold chain is claimed | 100% | ≥ 80 | ≥ 60 | ≥ 40 | < 40 |
| LF-02 | Domain experience | median years of CXOs in logistics, transport, supply chain or the main customer industry (employment history T2; MCA tenure T1) | ≥ 15 y | 10–15 | 6–10 | 3–6 | < 3 |
| LF-03 | Scale experience | share of CXOs who held a director/VP+ role in an organisation at least as large (headcount) as this company is today | ≥ 75% | 50–75 | 25–50 | > 0–25 | 0 |
| LF-04 | Track record | share of directors/CXOs with no director/KMP link to struck-off, insolvent or prosecuted companies and no disqualification (MCA, IBBI) | 100% | ≥ 90 | ≥ 75 | ≥ 50 | < 50 |
| LF-05 | Bio integrity | class credits over leadership bio claims in the deck/website; any ❌ FALSE → 0 and gate G8 | ≥ 90% | 75–90 | 60–75 | 40–60 | < 40 |
| LF-06 | Stability | CXO/VP churn over 24 months (departures ÷ average count) | < 10% | 10–20 | 20–30 | 30–40 | ≥ 40 |
| LF-07 | Strategy–capability alignment | share of the deck's strategic pillars ("tech-led", "pan-India", "cold-chain entry", "IPO-ready") that have an accountable leader with ≥ 3 years in that function | 100% | ≥ 75 | ≥ 50 | ≥ 25 | < 25 |
| **LF-C** | **Leadership fit** | mean(LF-01…07), rounded down to 0.5 | | | | | |

**Leadership verdict** (shown in the suggestion box):
- **FIT**: LF-C ≥ 3.5
- **FIT WITH GAPS**: ≥ 2.5
- **WEAK FIT**: ≥ 1.5
- **NOT FIT**: < 1.5
- **NOT ASSESSABLE**: fewer than 4 of the 7 metrics measurable

The verdict always names the gap, e.g. "no technology leader for the 'tech-led' pillar".

**Fairness (hard rule).** LF uses only role-relevant professional facts. It never uses age, gender, religion, caste, region of origin, family, the prestige of an educational institution, or career breaks. Education is fact-checked if the deck claims it, but never scored.

### 4.8 Organisation, market, PMF, acquirability, reputation, verification

| ID | Metric | Definition | 4 | 3 | 2 | 1 | 0 |
|---|---|---|---|---|---|---|---|
| OR-03 | Function-mix distance | ops + sales share vs the mandate's ideal range (pp outside) | inside | ≤ 5 | ≤ 10 | ≤ 15 | > 15 |
| OR-04 | Employee rating | `employee_reviews.overall_rating` | ≥ 4.2 | 3.8–4.2 | 3.4–3.8 | 3.0–3.4 | < 3.0 |
| MK-01 | Market size | third-party estimates (T1-M or research publishers), quote-locked, shown as a range; never ✅ | context | | | | |
| MK-C | Market composite | segment CAGR (cited): ≥ 15% → 2 parts · 8–15% → 1 · < 8% → 0; **plus** growth minus competitor median: ≥ +10 pp → 2 · within ±10 → 1 · ≤ −10 → 0 | 4 | 3 | 2 | 1 | 0 |
| MK-04/05 | Share estimate · HHI | context only | | | | | |
| PM-01 | PMF signals | count of: openings growth > 0 · traffic YoY > 0 · OR-04 ≥ 3.8 · ≥ 2 verified named customers | 4 | 3 | 2 | 1 | 0 |
| RP-01 | Reputation & legal | worst **confirmed** finding (T1 or T1-M): none · minor resolved · minor open · material resolved · material open | none | minor res. | minor open | material res. | material open |
| VI-01 | Claim integrity | class credits ÷ critical claims; −1 point per non-critical ❌ (min 0) | ≥ 90% | 75–90 | 60–75 | 40–60 | < 40 |
| VI-02 | Evidence coverage | share of rubric weight backed by evidence | gate G7 ≥ 60% | | | | |
| VI-03 | Operational verification | VI-01 over operational claims (sites, fleet, locations, headcount, certifications) | ≥ 90% | 75–90 | 60–75 | 40–60 | < 40 |
| VI-04 | Mandate fit, verified | share of constraint weight confirmed by T1/T1-M/T3 | ≥ 90% | 75–90 | 50–75 | 25–50 | < 25 |

**Acquirability, feasibility part (AQ)** (the quality part comes from query reasoning, §5):
- **AQ-01** private limited or LLP (hard)
- **AQ-02** not acquired, not a subsidiary of a larger group (hard)
- **AQ-03** active and not insolvent (hard)
- **AQ-04** revenue within buyer capacity (soft, weight 3)
- **AQ-05** founder-led (soft, weight 2)
- **AQ-06** no institutional round in 24 months (soft, weight 1)

---

## 5. Query reasoning: from words to parameters

The query is **reasoned over, not keyword-matched**. Each term is mapped to its intent, the parameters that intent implies, the metric IDs that measure them, a threshold, a role and the step where it can be measured.

### 5.1 Four roles a parameter can take

| Role | Effect | Rubric stays constant? |
|---|---|---|
| **Search filter** | Narrows the searches (Step 1 streams) | yes |
| **Hard constraint** | Pass / fail / likely fail / unknown at the gate | yes |
| **Soft constraint** | Weighted inside S1 (Step 1) and C7 (Step 4) | yes |
| **Minimum-band requirement** | A floor on an existing rubric criterion. **Met** if the criterion's floor ≥ min; **unmet** if its ceiling < min; otherwise **open** (becomes a condition). One or more unmet → the label is **capped one level** (RECOMMEND → CONSIDER; PURSUE/CLEAR → … WITH CONDITIONS) | yes: weights never change |

### 5.2 Term library (`terms.yaml`; excerpt)

| Term | Intent (reasoning) | Parameters → metrics, thresholds, role |
|---|---|---|
| **acquirable** | *Can it be bought?* (feasibility) **and** *is it worth buying?* (quality) | **Feasibility:** AQ-01…03 hard · AQ-04…06 soft. **Quality, min-band requirements:** strong financial ratios = health grade ≥ B (C2 ≥ 3) and solvency pillar ≥ 3 (D/E ≤ 0.6, ICR ≥ 4, DSCR ≥ 1.5) · cash quality pillar ≥ 2 (CFO/EBITDA ≥ 60%) · no earnings-quality flag (M-score, Z″ distress) · sound tech claims = TC-C ≥ 2 · leadership fit ≥ FIT WITH GAPS (C9 ≥ 2.5) · governance ≤ 1 flag (C5 ≥ 3) · no confirmed sanctions or material litigation |
| **logistic(s)** | sector | ID-05 ∈ {3PL, warehousing, freight forwarding, road transport, cold chain, last-mile, courier}; NIC divisions 49, 52, 53 → search filter + hard |
| **in ⟨state/zone⟩** | geography | location basis (default *operates*; ARCHITECTURE §5.5) hard · RG-02 scored in regional fit · GST state code used for FP-01 |
| **profitable** | quality | PR-01 ≥ 2 and PR-02 ≥ 1 (min-band) |
| **growing / fast-growing** | momentum | GR-01 ≥ 2 / ≥ 3 (min-band); GR-02 ≥ 3 for Step 1 |
| **tech-enabled / tech-led** | capability | TC-C ≥ 2 / ≥ 3 (min-band); "tech-led" also adds a tech head to LF-01 and turns on TC-02 |
| **asset-light** | model | AL-01 ≤ 0.25 (soft) |
| **small / mid-size / large** | size | revenue bands from config (soft, AQ-04 style) |
| **debt-free / low-debt** | solvency | SV-02 net cash / SV-01 ≤ 0.3 (min-band) |
| **cold chain** | sub-sector | taxonomy + keywords (hard); adds a cold-chain/quality head to LF-01 |
| **reliable / compliant (vendor)** | trust | ID-01, G2–G4, RP-01 ≥ 3, C5 ≥ 3 (min-band) |

**Research and list terms (excerpt):**

| Term | Intent | Parameters → metrics · threshold · role |
|---|---|---|
| **Indian** | HQ country | `locations.country in ["IND"]` (company) / `company.locations.country = "IND"` (jobs) · filter + hard |
| **B2B software** | sells software to businesses | industry from autocomplete (`Software Development`; optionally `IT Services and IT Consulting`) + **B2B classifier** (quoted self-description) · filter + hard; ambiguous → excluded and listed |
| **fintech** | technology-first financial services | categories from autocomplete (fin/pay/lend/insur/wealth…) or industry `Financial Services` + **fintech classifier** (excludes traditional banks, NBFCs and insurers unless tech-first) · hard |
| **founded since YEAR** | incorporation/founding year ≥ YEAR | `basic_info.year_founded => YEAR` (T2); a CIN year or earliest Wayback capture earlier than YEAR → conflict → excluded with reason · hard |
| **team grew by X in the last N months** | headcount growth | `headcount.growth_percent.{N}m => X` (T2, profile-based; "by half" = 50) + **proposed guard** `headcount.total => 10` (confirm) · hard |
| **this quarter** | calendar quarter containing *now* (IST); also Indian FY quarter label | `metadata.date_added => quarter_start` · window (shown on the card) |
| **hiring the most engineers** | rank by deduped engineering **postings** (proxy) | `job_details.category = "Engineering"` → group by company → dedup → rank · metric |
| **who founded / what they did before** | founders and prior roles | `people.founders` (T2) + MCA directors (T1 if CIN) · `experience.employment_details.past[]` (🟢 P5 unless T1/T1-M) · attribute |
| **ten / top N** | output size | exactly up to N, never padded · output |

### 5.3 Reasoning rules

- The LLM reads the query together with the client profile and proposes the mapping **using the term library**. A parameter not in the library is shown as **"proposed — confirm"** and is never applied silently.
- Each parameter in the interpretation card shows: term → intent → metric IDs → threshold → role → measurable at which step → `from query` / `default` / `assumed — confirm`.
- At most three confirmation questions. Choices are journaled and the mandate is versioned.
- At Step 1 most quality requirements are **open** (private-company financials are not public). The Market IM lists them as "to confirm at CHECK"; they are tested on evidence at Step 4.

---

## 6. Rubrics

### 6.1 Rubric card format

Each rubric is a YAML card: `id · version · sha256 · purpose · profile · gates[] · criteria[] (id, metric IDs, bands, weight) · scoring · decision rule · labels · tie-breakers`. The IM prints its id, version and sha256.

### 6.2 Scoring math (every rubric)

```
contribution = weight × points ÷ 4          points 0–4 (composites in 0.5 steps)
floor   = missing inputs scored 0 (ratio items: missing counted as fail)
ceiling = missing inputs scored 4 (ratio items: missing counted as pass)
coverage = Σ weight × share of the criterion's inputs with evidence ÷ 100
rounding 2 decimals · ties → coverage, then C1/S1, then weight
```

### 6.3 R1 — Scouting rubric (Step 1)

**Gate:** hard constraints (incl. AQ-01…03 and the location basis).
**Risk flags** (possible sanctions/debarment name match, confirmed adverse media, strike-off) are shown, not scored, and block RECOMMEND.

| ID | Criterion | Metric(s) | Weight |
|---|---|---|---|
| S1 | Constraint fit (soft) | % of soft-constraint weight met → VI-04 bands | 15 |
| S2 | Growth momentum | GR-02 | 15 |
| S3 | Scale fit | SC-01 (else SC-02) vs mandate band: middle 50% → 4 · inside → 3 · ≤ 25% outside → 2 · ≤ 50% → 1 · further → 0 | 10 |
| S4 | Leadership fit (public) | mean(LF-01, LF-02, LF-06) | 15 |
| S5 | Org composition | OR-03 | 5 |
| S6 | Market & competition | MK-C | 10 |
| S7 | PMF signals | PM-01 | 10 |
| S8 | **Regional fit** | RG-C | 10 |
| S9 | Quality signals | mean(health grade points if filed financials are available, TC-C from public evidence) | 10 |

**Labels:**
- **RECOMMEND**: floor ≥ 60 and no risk flag
- **CONSIDER**: ceiling ≥ 60
- **NOT RECOMMENDED**: ceiling < 60

Query requirements that are unmet cap the label (§5.1).

### 6.4 R2 — Decision rubric (Step 4)

**Gates** (in order; the first that fires sets the outcome):

| Gate | Check | Fails → |
|---|---|---|
| G1 | Entity resolved (≥ 0.85) | Hold |
| G2 | ID-01 active | struck off / cancelled → Reject · source down → Hold |
| G3 | Sanctions / debarment (company + KMP) | person-confirmed → Reject · possible match → Hold |
| G4 | No critical claim ❌ FALSE by T1 or T1-M (F1/F4) | Reject |
| G5 | Hard mandate constraints met on verified data | Reject (out of mandate) |
| G6 | Statements internally consistent (FSV-01…03) | Hold |
| G7 | Coverage ≥ 60% | Hold |
| **G8** | No ❌ FALSE claim about a KMP's credentials (role, employer, title, qualification, directorship) | **Hold** for a person + clarification ask (never auto-reject) |

**Criteria:**

| ID | Criterion | Metric(s) | Target wt | Vendor wt |
|---|---|---|---|---|
| C1 | Claim integrity (deck fact-check) | VI-01 | 20 | 20 |
| C2 | Financial health | grade A 4 · B 3 · C 2 · D 1 · E 0 | 20 | 15 |
| C3 | Growth | GR-01 (GR-02 if no statements, flagged) | 10 | 5 |
| C4 | Market position | MK-C with verified revenue growth | 10 | 0 |
| C5 | Governance (company) | 4 − 1 per flag: auditor opinion not unmodified · late MCA filings · related-party > 10% of revenue · contingent liabilities > 25% of net worth · auditor change in 2 years | 5 | 10 |
| C6 | Reputation & legal | RP-01 | 5 | 10 |
| C7 | Mandate fit, verified | VI-04 | 5 | 5 |
| C8 | Operational capacity | VI-03 | 0 | 15 |
| C9 | **Leadership fit** | LF-C | 15 | 5 |
| C10 | **Regional fit** | RG-C (incl. fleet share at CHECK) | 5 | 10 |
| C11 | **Tech soundness** | TC-C | 5 | 5 |

### 6.5 Decision rule and wording

```
1. a gate fired            → gate outcome
2. ceiling < 50            → negative
3. floor ≥ 75              → positive
4. floor ≥ 50              → positive with conditions
5. otherwise               → hold
6. any query requirement UNMET → cap one level (positive → positive with conditions)
```

| Outcome | Target wording | Vendor wording |
|---|---|---|
| positive | **PURSUE** | **CLEAR** |
| positive with conditions | **PURSUE WITH CONDITIONS** | **CLEAR WITH CONDITIONS** |
| hold | **HOLD — MORE EVIDENCE NEEDED** | **HOLD FOR A PERSON** |
| negative | **PASS** | **REJECT** |

- **Conditions** = asks that close the floor–ceiling gap (ordered by points each adds) + every open query requirement + one mitigation per criterion at ≤ 1 point.
- **What would change it** = the smallest set of asks that moves the floor across the next threshold, with exact points; ties are broken in favour of the set that also closes an open requirement.

### 6.6 Worked example (R2, vendor profile, sample data)

12 critical claims: 8 ✅ · 1 🟢 · 1 🟡 · 2 ⚪.
5 operational claims: 3 ✅ · fleet 🟡 · certification ⚪.
Leadership fit 3 · regional fit 3 (lane coverage 80%) · tech soundness 3.

| Criterion | Value | Pts floor / ceil | Wt | Floor | Ceiling |
|---|---|---|---|---|---|
| C1 Claim integrity | (8 + 0.75 + 0.5) ÷ 12 = 77.1%; ceiling 93.8% | 3 / 4 | 20 | 15.00 | 20.00 |
| C2 Financial health | grade B | 3 / 3 | 15 | 11.25 | 11.25 |
| C3 Growth | revenue CAGR 18% | 3 / 3 | 5 | 3.75 | 3.75 |
| C5 Governance | 1 flag (late filing) | 3 / 3 | 10 | 7.50 | 7.50 |
| C6 Reputation & legal | none confirmed | 4 / 4 | 10 | 10.00 | 10.00 |
| C7 Mandate fit, verified | 70%; ceiling 100% | 2 / 4 | 5 | 2.50 | 5.00 |
| C8 Operational capacity | (3 + 0.5) ÷ 5 = 70%; ceiling 90% | 2 / 4 | 15 | 7.50 | 15.00 |
| C9 Leadership fit | FIT WITH GAPS | 3 / 3 | 5 | 3.75 | 3.75 |
| C10 Regional fit | lane coverage 80% | 3 / 3 | 10 | 7.50 | 7.50 |
| C11 Tech soundness | 75% of tech claims | 3 / 3 | 5 | 3.75 | 3.75 |
| **Total** | gates G1–G8 pass · coverage 92.2% | | 100 | **72.50** | **87.50** |

Rule 4 → **CLEAR WITH CONDITIONS**. If vehicle RC copies verify the fleet, C8 = 4 ÷ 5 = 80% → 3 → +3.75 → floor **76.25 → CLEAR**.

### 6.7 Change control

Any change to a band, weight, gate, credit, tolerance, media list or term mapping creates a new version and sha256. `make golden` re-scores the golden cases. A run keeps its version; a re-check shows the old and the new score if they differ.

### 6.8 R3 — Research answer rubric (FIND_LIST, RESEARCH_QA)

| Check | Definition | Required |
|---|---|---|
| Q1 Criteria compliance | rows passing every hard criterion on evidence ÷ rows returned | 100% |
| Q2a Honest coverage | requested attributes answered with a class (incl. ⚪ with `missing`) ÷ requested | 100% |
| Q2b Support | attributes ✅/🟢 ÷ requested | reported |
| Q3 Completeness | rows returned ÷ rows requested | reported; never padded |
| Q4 Source strength | facts at T1/T1-M ÷ all facts | reported |
| Q5 Inference labelling | labelled inferences ÷ inferences | 100% |
| Q6 Premise check | every extracted premise checked | all |

- **Status:**
  - **COMPLETE**: Q1, Q2a, Q3, Q5 at 100% and no FALSE premise.
  - **PARTIAL**: fewer qualifying rows or Q2b < 75%, with the reason stated.
  - **CANNOT ANSWER**: FALSE premise (F3), zero qualifying rows, or a required source unavailable, with near-misses and the binding criterion.
- **Confidence:**
  - **HIGH**: Q2b ≥ 90% and Q4 ≥ 30%.
  - **MEDIUM**: Q2b ≥ 75%.
  - **LOW**: otherwise.
- **Ranking "the most / top":** by the stated metric; ties → share → name.

---

## 7. Information Memo (IM) standard

The IM is the finished output: a suggestion for a decision-maker. It stays `DRAFT — awaiting decision` until a person accepts or overrides it.

### 7.1 Company IM (after Step 4)

| # | Section | Contents (every number sourced, dated and tier-tagged) |
|---|---|---|
| 0 | Cover | company · CIN · IM id · date · profile · rubric id/version/sha · status |
| 1 | **Suggestion box** | label · score floor–ceiling · coverage · rule · query requirements (met/open/unmet) · **leadership verdict + gap** · **regional fit (regions of operation)** · 3 reasons for · 3 against · conditions · what would change it · "suggestion only — decision by {role}" |
| 2 | Scorecard | gates + R2 table |
| 3 | Company snapshot | identity (badges) · HQ · **regions of operation map (RG-01) with share per state** · scale · ownership/AQ |
| 4 | Market & competition | MK-01 range (publishers) · segment growth · competitor table · relative growth · market view |
| 5 | Financial analysis | grade · pillars · metric table (3 years, band, quality tag) · FSV red flags · DuPont |
| 6 | **Deck fact-check** | slide-by-slide map: every claim → class badge · reason code · source tier · record date; counts per class; FALSE and OUTDATED listed first |
| 7 | **Leadership fit** | LF-01…07 table · verdict · named gaps · bio claims with classes · track record · stability |
| 8 | Technology | tech claims with classes · TC-C |
| 9 | Risks & mitigants | every criterion ≤ 1, every open/unmet requirement, every red flag → mitigant (`mitigants.yaml`) |
| 10 | Next steps | asks by points · emails pending approval |
| 11 | Appendix | sources (URL/endpoint · passage/field · record date · retrieved date · tier · media tier) · method · cost |

### 7.2 Market IM (after Step 1)

1. Suggestion box: which companies to pursue and why
2. **Interpretation card**: query → parameters (§5)
3. Market view
4. Funnel
5. Shortlist: R1 floor–ceiling · coverage · **regions of operation** · requirement status · label
6. Profiles of RECOMMEND companies
7. Excluded on estimates
8. Method & sources

### 7.3 "Why" sentence templates (LLM may only smooth wording under number lock)

- **For:** "{criterion} {p}/4 — {metric} is {value} ({band}; edge {edge}). Source: {source} ({tier}), {date}."
- **Against:** "Holding it back: {criterion} {p}/4 — {metric} {value}."
- **Requirement:** "Query asked for '{term}' → {requirement}: {met | open | unmet} ({evidence})."
- **Leadership:** "Leadership {verdict} ({LF-C}/4): {strongest metric}; gap — {gap}."
- **Region:** "Operates in {n} states ({zones}); {target} share {RG-02}%; adds {x} states where the client is weak."
- **Change:** "If {document} confirms {claim}, {criterion} {p0} → {p1} (+{Δ}); floor {F1} → {label}."

### 7.4 Writing rules

1. Suggestion and score first.
2. Every number sourced and dated, with its tier; estimates say "estimate".
3. No adjective without a metric.
4. Every claim carries its badge and code.
5. Person findings say "possible match — not confirmed" until a person confirms them.
6. The memo ends with the decision box: suggested label · final decision · decided by · reason.

### 7.5 Research Memo (FIND_LIST, RESEARCH_QA)

| # | Section | Contents |
|---|---|---|
| 1 | **Answer box** | the direct answer in 2–4 lines · status (COMPLETE / PARTIAL / CANNOT ANSWER) · confidence · as-of time (IST) and resolved windows |
| 2 | Interpretation card | phrase → parameter → metric → threshold → role (§5), incl. proxies ("postings ≠ hires") and guards |
| 3 | Results table | one row per entity; every cell carries its class badge and source; criteria columns show ✅/🟢 per row |
| 4 | Inferences | per entity: INFERENCE cards with strength, n/total, window, quotes, corroboration (§2.4) |
| 5 | Near-misses | entities failing exactly one hard criterion, with that criterion and its evidence |
| 6 | Premise checks | each premise: ✅ / ❌ (F3) / ⚪ (N7) |
| 7 | Method, caveats, sources, cost | streams and filters used (request JSON with keys redacted), dedup rules, coverage limits, sources with record dates and tiers, credits and ₹ |
