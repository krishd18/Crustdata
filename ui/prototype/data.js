/* Data Designer UI prototype — sample data.
   Every company is "(sample)": numbers mirror docs/WALKTHROUGH.md so the prototype,
   the docs and tools/rubric_check.py tell the same story. No real company data. */
window.DD = {
  asOf: "22 Nov 2026, 16:30 IST",
  env: "replay",
  budgetToday: { used: 607, cap: 2000 },

  tabs: {
    investing: [
      { q: "acquirable logistic companies in maharashtra", key: "acquire" },
      { q: "Find ten Indian B2B software companies founded since 2023 whose team grew by half in the last six months, and tell me who founded each and what they did before.", key: "findlist" }
    ],
    research: [
      { q: "Which Indian fintech companies are hiring the most engineers this quarter, and what does their hiring say about what each will launch next?", key: "research" },
      { q: "Which cold-chain operators in Maharashtra opened new sites this year?", key: "research" }
    ],
    compliance: [
      { q: "Check this carrier onboarding pack (vendor profile)", key: "acquire" },
      { q: "Fact-check this deck: Company C (sample), 14 slides", key: "acquire" }
    ]
  },

  /* ---------- reasoning cards (STANDARDS §5) ---------- */
  cards: {
    acquire: {
      family: "ACQUIRE", mandate: "M-2026-11-22-014", rubric: "R1-2026.11.22-2", credits: 450, minutes: 20,
      rows: [
        { phrase: "acquirable", intent: "Can it be bought?", params: "private or LLP · not acquired / subsidiary · active, not insolvent", metric: "AQ-01…03", role: "hard", origin: "from query" },
        { phrase: "", intent: "", params: "revenue ₹25–400 cr · founder-led · no institutional round in 24 months", metric: "AQ-04…06", role: "soft", origin: "assumed — confirm" },
        { phrase: "", intent: "Is it worth buying?", params: "health grade ≥ B · solvency ≥ 3 · cash quality ≥ 2 · no earnings flag", metric: "C2 · EQ", role: "min-band", origin: "term library" },
        { phrase: "", intent: "", params: "sound tech claims: TC-C ≥ 2", metric: "C11", role: "min-band", origin: "term library" },
        { phrase: "", intent: "", params: "capable team: leadership ≥ FIT WITH GAPS", metric: "C9 · LF-C", role: "min-band", origin: "term library" },
        { phrase: "logistic", intent: "sector", params: "3PL, warehousing, freight, road transport, cold chain, last-mile, courier · NIC 49/52/53", metric: "industry", role: "filter + hard", origin: "from query" },
        { phrase: "in maharashtra", intent: "geography", params: "operates in Maharashtra (GST state code 27) · regional fit", metric: "FP-01 · RG-C", role: "hard + scored", origin: "from query" }
      ],
      questions: [
        { q: "What does “in Maharashtra” mean?", opts: ["Operates there", "Majority of operations there (≥ 40%)", "Headquartered there"], def: 0 },
        { q: "Size for “acquirable”?", opts: ["₹25–400 cr revenue (client profile)", "Custom band"], def: 0 },
        { q: "Include listed companies?", opts: ["No", "Yes"], def: 0 }
      ]
    },
    findlist: {
      family: "FIND_LIST", mandate: "RM-2026-11-22-031", rubric: "R3-2026.11.22-1", credits: 150, minutes: 8,
      rows: [
        { phrase: "ten", intent: "output size", params: "up to 10 rows, ranked by 6-month growth", metric: "—", role: "output", origin: "from query" },
        { phrase: "Indian", intent: "HQ country", params: "locations.country in [\"IND\"]", metric: "filter", role: "filter + hard", origin: "from query" },
        { phrase: "B2B software", intent: "sells software to businesses", params: "industry “Software Development” (autocomplete) + B2B classifier, quote-locked", metric: "classifier", role: "filter + hard", origin: "from query" },
        { phrase: "founded since 2023", intent: "founding year ≥ 2023", params: "basic_info.year_founded => 2023 · CIN year cross-check", metric: "filter", role: "filter + hard", origin: "from query" },
        { phrase: "team grew by half…", intent: "6-month headcount growth ≥ 50%", params: "headcount.growth_percent.6m => 50", metric: "GR-HC", role: "filter + hard", origin: "from query" },
        { phrase: "(guard)", intent: "so 2 → 3 is not “half”", params: "headcount.total => 10", metric: "—", role: "hard", origin: "proposed — confirm" },
        { phrase: "who founded each", intent: "founders", params: "company/enrich people.founders + MCA directors", metric: "attribute", role: "attribute", origin: "from query" },
        { phrase: "what they did before", intent: "prior roles", params: "person/enrich past employment → 🟢 P5 unless T1", metric: "attribute", role: "attribute", origin: "from query" }
      ],
      questions: [
        { q: "Apply the 10-staff guard?", opts: ["Yes — at least 10 staff today", "No guard"], def: 0 },
        { q: "If fewer than ten qualify…", opts: ["Show fewer, never pad", "Show near-misses too"], def: 1 }
      ]
    },
    research: {
      family: "RESEARCH_QA", mandate: "RM-2026-11-22-032", rubric: "R3-2026.11.22-1", credits: 120, minutes: 8,
      rows: [
        { phrase: "Indian", intent: "HQ country", params: "company.locations.country = IND", metric: "filter", role: "filter", origin: "from query" },
        { phrase: "fintech", intent: "tech-first financial services", params: "fintech categories (autocomplete) + classifier; banks, NBFCs, insurers excluded unless tech-first", metric: "classifier", role: "hard", origin: "term library" },
        { phrase: "hiring the most engineers", intent: "rank by deduped engineering postings", params: "job_details.category = Engineering · dedup (company, title, city, 14 d)", metric: "HR-01", role: "metric", origin: "proxy — postings ≠ hires" },
        { phrase: "this quarter", intent: "1 Oct → 22 Nov 2026", params: "metadata.date_added => 2026-10-01", metric: "window", role: "window", origin: "resolved by clock" },
        { phrase: "what each will launch next", intent: "themes in postings", params: "themes.yaml + clustering, quoted titles", metric: "Inference Strength", role: "inference", origin: "labelled, never a fact" },
        { phrase: "(output size)", intent: "top 10", params: "—", metric: "—", role: "output", origin: "default — confirm" }
      ],
      questions: [
        { q: "How many companies?", opts: ["Top 10", "Top 5", "Top 20"], def: 0 },
        { q: "Count by", opts: ["Deduped postings", "Raw postings"], def: 0 }
      ]
    }
  },

  /* ---------- runs (stage timeline + log) ---------- */
  runs: {
    acquire: {
      id: "run_2026-11-22_014", memo: "market",
      stages: [
        { name: "Reason", credits: 0 }, { name: "Search A–G", credits: 164 }, { name: "Enrich top 100", credits: 200 },
        { name: "GSTIN lookup", credits: 30 }, { name: "Constraint gate", credits: 0 }, { name: "R1 score", credits: 0 }, { name: "Market IM", credits: 0 }
      ],
      log: [
        ["company/search", "Stream A · HQ in Maharashtra · industry set · headcount 50–2000", "300 companies", 69],
        ["person/search", "Stream G · 60 km around Mumbai, Pune, Nagpur, Nashik, Sambhajinagar", "2,000 people → 140 employers", 60],
        ["job/search", "Stream C · logistics roles in those cities · 90 days", "900 openings → 110 companies", 27],
        ["web/search/live", "Stream B · reliable media allow-list (media.yaml v2)", "8 queries → 15 companies", 8],
        ["merge", "dedup across streams", "380 companies", 0],
        ["company/enrich", "top 100 by pre-score, 4 batches of 25", "100 profiles", 200],
        ["web/enrich/live", "GSTIN from websites, top 30", "27 GSTINs → state code 27 for 22", 30],
        ["gate", "hard constraints · location basis = operates", "38 fail · 10 excluded on estimates · 52 pass", 0],
        ["R1", "S1–S9 floor/ceiling, R1-2026.11.22-2", "8 RECOMMEND · 19 CONSIDER · 25 NOT RECOMMENDED", 0],
        ["claude-sonnet-5-5", "memo smoother · number lock", "Market IM drafted · 0 numbers changed", 0]
      ]
    },
    findlist: {
      id: "run_2026-11-22_031", memo: "findlist",
      stages: [
        { name: "Reason", credits: 0 }, { name: "Autocomplete", credits: 0 }, { name: "company/search", credits: 47 }, { name: "Enrich 25", credits: 50 },
        { name: "B2B classifier", credits: 0 }, { name: "Founders", credits: 21 }, { name: "R3 + memo", credits: 0 }
      ],
      log: [
        ["company/search/autocomplete", "industry “software”", "Software Development confirmed", 0],
        ["company/search", "IND · Software Development · founded => 2023 · growth 6m => 50 · total => 10", "143 companies", 47],
        ["sort", "client-side by growth_percent.6m · 10-staff guard", "112 remain", 0],
        ["company/enrich", "top 25 · basic_info, headcount, people, taxonomy", "25 profiles", 50],
        ["claude-haiku-5-5", "B2B classifier · quoted description · structured output", "19 B2B · 4 B2C · 2 ambiguous", 0],
        ["cross-check", "CIN year · Wayback first capture", "1 conflict → excluded", 0],
        ["person/enrich", "founders of first 10 qualifying", "21 founders", 21],
        ["R3", "Q1–Q6", "COMPLETE · confidence MEDIUM", 0]
      ]
    },
    research: {
      id: "run_2026-11-22_032", memo: "research",
      stages: [
        { name: "Reason", credits: 0 }, { name: "Autocomplete", credits: 0 }, { name: "company/search", credits: 30 }, { name: "Job aggregation", credits: 0 },
        { name: "Listings + dedup", credits: 45 }, { name: "Classifier", credits: 0 }, { name: "Corroborate", credits: 20 }, { name: "R3 + memo", credits: 0 }
      ],
      log: [
        ["company/search/autocomplete", "taxonomy.categories × 5 (fin, pay, lend, insur, wealth)", "fintech category values", 0],
        ["company/search", "IND + fintech categories OR Financial Services · limit 1000", "1,000 candidate ids", 30],
        ["job/search", "aggregation · Engineering · date_added => 2026-10-01 · group by company", "top 50 buckets", 0],
        ["job/search", "listings for top 25 (≤ 200 each) → dedup", "1,480 → 1,190 unique postings", 45],
        ["claude-haiku-5-5", "fintech classifier · quoted descriptions", "2 incumbents excluded · 1 ambiguous listed", 0],
        ["web/search/live", "reliable-media corroboration, top 10 themes", "4 corroborations", 20],
        ["R3", "Q1–Q6", "COMPLETE · confidence MEDIUM", 0]
      ]
    }
  },

  /* ---------- Market IM (Step 1 output) ---------- */
  market: {
    id: "MIM-2026-11-22-014",
    funnel: [["Found", 380], ["Enriched", 100], ["Passed gate", 52], ["Recommend", 8]],
    split: { recommend: 8, consider: 19, notrec: 25 }, credits: 394,
    rows: [
      { name: "Company C", hq: "Delhi", regions: "West, North, South (4 states)", mh: 62, rev: "₹150–220 cr", floor: 72.5, ceil: 81.25, req: "2 met · 2 open", label: "RECOMMEND", note: "HQ Delhi, most fleet in Mumbai — included because basis = operates" },
      { name: "Company A", hq: "Pune", regions: "West (1 state)", mh: 100, rev: "₹60–90 cr", floor: 70, ceil: 80, req: "2 met · 2 open", label: "RECOMMEND" },
      { name: "Company B", hq: "Mumbai", regions: "West, South (3)", mh: 85, rev: "₹200–310 cr", floor: 66.25, ceil: 80, req: "1 met · 3 open", label: "RECOMMEND" },
      { name: "Company F", hq: "Nagpur", regions: "West, Central (2)", mh: 92, rev: "₹30–45 cr", floor: 63.75, ceil: 75, req: "2 met · 2 open", label: "RECOMMEND" },
      { name: "Company H", hq: "Bengaluru", regions: "South, West (5)", mh: 41, rev: "₹90–140 cr", floor: 62.5, ceil: 71.25, req: "2 met · 2 open", label: "RECOMMEND" },
      { name: "Company J", hq: "Mumbai", regions: "West (2)", mh: 78, rev: "₹40–70 cr", floor: 55, ceil: 68.75, req: "1 met · 2 open · 1 unmet", label: "CONSIDER" },
      { name: "Company N", hq: "Thane", regions: "West (1)", mh: 100, rev: "₹25–35 cr", floor: 41.25, ceil: 58.75, req: "0 met · 4 open", label: "NOT RECOMMENDED" }
    ],
    excluded: "Company G (sample): revenue band ₹520–700 cr is above ₹400 cr (Crustdata estimate) — restorable."
  },

  /* ---------- Company IM (Step 4 output) ---------- */
  company: {
    id: "IM-2026-11-29-003", name: "Company C", cin: "U……DL2011PTC……", profile: "target", rubric: "R2-2026.11.22-2 · sha 41d7…",
    suggestion: "PURSUE WITH CONDITIONS", floor: 68.75, ceil: 76.25, coverage: 97.0, rule: 4,
    reqs: { met: 6, open: 1, unmet: 0 },
    gates: [["G1", "Entity match 0.98"], ["G2", "Active"], ["G3", "No sanctions hit"], ["G4", "No critical FALSE"], ["G5", "In mandate"], ["G6", "Statements consistent"], ["G7", "Coverage 97.0%"], ["G8", "No false credential"]],
    score: [
      { c: "C1", name: "Claim integrity (deck)", val: "85.7% → 3, −1 for a non-critical FALSE", pf: 2, pc: 3, w: 20, f: 10.00, cl: 15.00, why: "(10 ✅ + 2 × 0.75 + 1 × 0.5) ÷ 14 critical claims = 85.7% → 3 points; one non-critical FALSE (GST states) costs 1 point." },
      { c: "C2", name: "Financial health", val: "grade B", pf: 3, pc: 3, w: 20, f: 15.00, cl: 15.00, why: "Pillar medians → mean 2.79 → grade B (≥ 2.75)." },
      { c: "C3", name: "Growth", val: "revenue CAGR 21%", pf: 3, pc: 3, w: 10, f: 7.50, cl: 7.50, why: "FY23–FY26 from MCA AOC-4 filings (T1)." },
      { c: "C4", name: "Market position", val: "+12 pp vs competitors", pf: 3, pc: 3, w: 10, f: 7.50, cl: 7.50, why: "Segment share 11% → 1; growth gap vs competitor median +12 pp → 2; composite rounds to 3." },
      { c: "C5", name: "Governance", val: "1 flag: FY24 filing late", pf: 3, pc: 3, w: 5, f: 3.75, cl: 3.75, why: "MCA filing dates (T1)." },
      { c: "C6", name: "Reputation & legal", val: "none confirmed", pf: 4, pc: 4, w: 5, f: 5.00, cl: 5.00, why: "eCourts + reliable media allow-list, no confirmed matter." },
      { c: "C7", name: "Mandate fit, verified", val: "85% (ceiling 100%)", pf: 3, pc: 4, w: 5, f: 3.75, cl: 5.00, why: "Revenue verified; founder-led verified; round history unverified." },
      { c: "C9", name: "Leadership fit", val: "FIT WITH GAPS", pf: 3, pc: 3, w: 15, f: 11.25, cl: 11.25, why: "LF-C 3.29 → rounded down 3.0; gap: no technology leader." },
      { c: "C10", name: "Regional fit", val: "MH share 63.4% · network fit 25%", pf: 3, pc: 3, w: 5, f: 3.75, cl: 3.75, why: "GST, staff, openings, sites and fleet weighted; adds 1 state where the client is weak." },
      { c: "C11", name: "Tech soundness", val: "TC-C 1.0 (ceiling 2.0)", pf: 1, pc: 2, w: 5, f: 1.25, cl: 2.50, why: "55% of tech claims verified; engineering 3% of staff although the deck claims ‘tech-led’." }
    ],
    requirements: [["Health grade ≥ B", "met", "B"], ["Solvency ≥ 3", "met", "3"], ["Cash quality ≥ 2", "met", "2.5"], ["No earnings-quality flag", "met", "none"], ["Leadership ≥ FIT WITH GAPS", "met", "3"], ["Governance ≤ 1 flag", "met", "1"], ["Tech soundness ≥ 2", "open", "floor 1, ceiling 2"]],
    why: [
      ["It is outgrowing its market.", "Revenue +21% a year FY23–FY26 (MCA) vs competitor median 9% and segment growth 11%."],
      ["Its ratios are strong where a buyer needs them.", "D/E 0.55, net debt/EBITDA 1.0, interest cover 4.8, DSCR 1.6; Z″ 3.1 safe, M-score −2.41 clean → grade B."],
      ["It fits the Maharashtra mandate with a proven team.", "63% Maharashtra footprint (GST 27, VAHAN-sampled fleet, tier-A report of the Bhiwandi hub)."]
    ],
    hold: [
      ["The deck overstates facts.", "“GST-registered in 6 states” is FALSE (4 active, 1 cancelled); the award appears only in paid brand content."],
      ["The tech story is thin.", "55% of tech claims verified; engineering 3% of staff; no tech head."],
      ["Margins are thin and collections slow.", "EBITDA 9.4%, DSO 78 days, FCF margin 1.8%."]
    ],
    conditions: [
      ["Contract extract for the top-customer renewal", "+5.00"], ["Evidence for API integrations and IoT sensors", "+1.25 · closes tech requirement"],
      ["Written reconciliation of GST registrations", "before any term sheet"], ["Plan or candidate for a technology head", "leadership gap"], ["Receivables ageing > 90 days", "working-capital risk"]
    ],
    wouldBe: "Would be PURSUE if conditions 1 + 2 are met → floor 75.00 (rule 3), every requirement met.",
    claims: [
      { s: 2, t: "Incorporated in 2011", crit: true, cls: "verified", code: "V1", ev: "MCA master data", tier: "T1", date: "22 Nov 2026" },
      { s: 3, t: "GST-registered in 6 states", crit: false, cls: "false", code: "F1", ev: "GST search by PAN: 4 active, 1 cancelled", tier: "T1", date: "22 Nov 2026" },
      { s: 4, t: "FY26 revenue ₹186 cr", crit: true, cls: "verified", code: "V2", ev: "FY26 AOC-4 filed Oct 2026", tier: "T1", date: "14 Oct 2026" },
      { s: 4, t: "640 employees", crit: true, cls: "verified", code: "V4", ev: "EPFO establishment search: 655 members", tier: "T1", date: "31 Oct 2026" },
      { s: 5, t: "48 trucks", crit: true, cls: "verified", code: "V1", ev: "48 RC copies; 20 sampled match VAHAN", tier: "T1", date: "20 Nov 2026" },
      { s: 5, t: "Most of our fleet operates from Mumbai", crit: true, cls: "partial", code: "P3", ev: "33 of 48 RCs MH-registered (T1); e-way-bill summary 71% MH origin (T3)", tier: "T1/T3", date: "20 Nov 2026" },
      { s: 6, t: "4.2 lakh sq ft across 6 sites", crit: true, cls: "partial", code: "P3", ev: "5 of 6 lease deeds + GST places = 3.6 lakh sq ft", tier: "T3/T1", date: "18 Nov 2026" },
      { s: 7, t: "5-year contract with a national FMCG company (2026)", crit: true, cls: "verified", code: "V5", ev: "Tier-A business daily, own reporting", tier: "T1-M", date: "3 Mar 2026" },
      { s: 7, t: "Serves 3 of India’s top-10 e-commerce firms", crit: true, cls: "unverified", code: "U2", ev: "Deck only · missing: customer references", tier: "T3", date: "—" },
      { s: 7, t: "Top customer contract renewed to 2029", crit: true, cls: "nv", code: "N1", ev: "Missing: contract extract", tier: "—", date: "—" },
      { s: 9, t: "“Best 3PL 2025” award", crit: false, cls: "unverified", code: "U2", ev: "Only on a ‘brand connect’ page (media tier D = self-published)", tier: "T4", date: "—" },
      { s: 10, t: "ISO 9001:2015 certified", crit: false, cls: "outdated", code: "O2", ev: "Certificate copy expired Jan 2025", tier: "T3", date: "Jan 2025" },
      { s: 14, t: "₹500 cr revenue by FY29", crit: false, cls: "nc", code: "X1", ev: "Projection — not checked", tier: "—", date: "—" }
    ],
    leaders: [
      { role: "CEO, founder", yrs: 22, scale: "yes · 4,000-staff 3PL", rec: "clean", bio: [["director since 2011", "verified", "V1"], ["ex-VP ops, national 3PL", "partial", "P5"], ["20+ years in logistics", "partial", "P5"]] },
      { role: "CFO", yrs: 6, scale: "no", rec: "clean", bio: [["KMP since 2021", "verified", "V1"], ["12 years in finance", "partial", "P5"], ["led a ₹200 cr debt raise", "unverified", "U2"]] },
      { role: "COO", yrs: 13, scale: "yes", rec: "clean", bio: [["ran a 2 million sq ft network", "verified", "V5"]] },
      { role: "Head of Sales", yrs: 14, scale: "yes", rec: "clean", bio: [["director since 2022", "verified", "V1"], ["ex-regional head, e-commerce logistics", "partial", "P5"]] }
    ],
    lf: [["LF-01", "Role coverage", "4 of 5 (no tech head) = 80%", 3], ["LF-02", "Domain experience", "median 13.5 yrs", 3], ["LF-03", "Scale experience", "3 of 4 = 75%", 4], ["LF-04", "Track record", "100% clean", 4], ["LF-05", "Bio integrity", "83.3%", 3], ["LF-06", "Stability", "CXO churn 12%", 3], ["LF-07", "Strategy–capability", "3 of 4 pillars = 75%", 3]],
    pillars: [["Growth", "revenue CAGR 21%", 3], ["Profitability", "EBITDA 9.4% · PAT 3.1% · ROCE 16% · ROE 14%", 2.5], ["Liquidity", "current 1.42 · quick 1.05", 2.5], ["Solvency", "D/E 0.55 · ND/EBITDA 1.0 · ICR 4.8 · DSCR 1.6", 3], ["Working capital", "DSO 78 d · CCC 52 d", 2], ["Cash quality", "CFO/EBITDA 78% · FCF margin 1.8%", 2.5], ["Earnings quality", "Z″ 3.1 · M −2.41 · F-score 6", 4]],
    tech: [["In-house WMS", "partial", "P", "Job posts for WMS developers (T2)"], ["Real-time tracking app", "verified", "V", "App-store listing (independent platform)"], ["API integrations with 3 marketplaces", "unverified", "U2", "Deck only"], ["IoT temperature sensors", "nv", "N1", "Missing: device inventory or vendor invoice"], ["AI route optimisation", "unverified", "U2", "Deck only"]],
    regions: [["Maharashtra", 63.4], ["Delhi", 14.1], ["Karnataka", 12.3], ["Gujarat", 10.2]]
  },

  /* ---------- Research memos ---------- */
  findlist: {
    id: "RM-2026-11-22-031", status: "COMPLETE", confidence: "MEDIUM", credits: 118,
    answer: "10 Indian B2B software companies founded in 2023 or later grew their teams by at least 50% in the last six months. Company K (+128%), Company L (+96%) and Company M (+81%) lead. Founders mostly come from product and engineering roles at Indian SaaS and fintech firms (per public profiles).",
    rows: [
      { n: "Company K", hq: "Bengaluru", yr: "2023", from: 18, to: 41, g: 128, b2b: "“API platform for finance teams”", f: [["Senior PM at a payments company", "partial", "P5"], ["Engineering lead at a SaaS firm", "partial", "P5"]] },
      { n: "Company L", hq: "Pune", yr: "2024", from: 25, to: 49, g: 96, b2b: "“compliance automation for manufacturers”", f: [["Director since 2024 (MCA); before: plant-ops consultant", "verified", "V1"]] },
      { n: "Company M", hq: "Gurugram", yr: "2023", from: 32, to: 58, g: 81, b2b: "“warehouse software for 3PLs”", f: [["Prior role not found (missing: public profile)", "nv", "N1"]] },
      { n: "Company D", hq: "Hyderabad", yr: "2023", from: 22, to: 38, g: 73, b2b: "“payroll APIs for staffing firms”", f: [["Product lead at an HR-tech company", "partial", "P5"]] },
      { n: "Company E", hq: "Chennai", yr: "2024", from: 14, to: 23, g: 64, b2b: "“contract analytics for legal teams”", f: [["Associate at a law firm", "partial", "P5"], ["ML engineer at a SaaS firm", "partial", "P5"]] }
    ],
    near: ["Company X: growth +47% (below 50%).", "Company Y: consumer app (B2C, quoted).", "Company Z: CIN year 2020 vs profile 2023 (conflict → excluded).", "Company W: 3 → 7 staff, excluded by the 10-staff guard you confirmed."],
    r3: [["Q1 criteria compliance", "100%"], ["Q2a coverage", "100%"], ["Q2b attributes ✅/🟢", "92%"], ["Q3 rows", "10 / 10"], ["Q4 T1 share", "14%"], ["Q6 padding", "none"]]
  },
  research: {
    id: "RM-2026-11-22-032", status: "COMPLETE", confidence: "MEDIUM", credits: 95, window: "1 Oct – 22 Nov 2026",
    answer: "Company P (41 deduped engineering postings), Company Q (33) and Company R (29) are hiring the most engineers among Indian fintechs this quarter. P’s hiring points strongly to credit on UPI; Q and R point, moderately, to card issuing and wealth products.",
    rows: [
      { n: "Company P", d: 41, raw: 57, share: 62, themes: "credit on UPI · risk ML" },
      { n: "Company Q", d: 33, raw: 38, share: 55, themes: "card issuing · fraud" },
      { n: "Company R", d: 29, raw: 34, share: 48, themes: "wealth · mutual-fund rails" },
      { n: "Company S", d: 24, raw: 31, share: 44, themes: "merchant lending" },
      { n: "Company T", d: 21, raw: 23, share: 51, themes: "account aggregator" },
      { n: "Company U", d: 18, raw: 22, share: 39, themes: "cross-border payments" }
    ],
    inferences: [
      { n: "Company P", next: "credit lines on UPI", strength: "STRONG", posts: 9, share: 31, corr: "Tier-A business daily, own reporting", quote: "Senior Engineer, Credit on UPI — Bengaluru" },
      { n: "Company Q", next: "card issuing for SMEs", strength: "MODERATE", posts: 6, share: 18, corr: "—", quote: "Backend Engineer, Card Issuing Platform" },
      { n: "Company R", next: "wealth products on mutual-fund rails", strength: "MODERATE", posts: 5, share: 17, corr: "—", quote: "SDE II, Wealth — MF Orders" }
    ]
  },

  /* ---------- approvals (Gmail SMTP, exactly once) ---------- */
  approvals: [
    { id: "ACT-7f3a", kind: "Document request", tmpl: "doc_request", to: "cfo@company-c.example", company: "Company C", subject: "Two documents for our review — contract extract and integration evidence", status: "pending",
      body: "Hello,\n\nThank you for sharing your deck. To complete our review we would be grateful for:\n\n1. An extract of the renewed contract with your top customer (term and renewal date are enough).\n2. Evidence for the API integrations and IoT sensors on slide 8 — integration listings or vendor invoices.\n\nWe will handle these under our NDA dated 24 Nov 2026.\n\nKind regards,\nCorporate Development" },
    { id: "ACT-91c0", kind: "Teaser request", tmpl: "teaser_request", to: "founder@company-a.example", company: "Company A", subject: "Introduction — exploring a partnership in Maharashtra logistics", status: "pending",
      body: "Hello,\n\nWe are a mid-size 3PL looking at partners with a strong Maharashtra network. Would you be open to sharing a short teaser or deck?\n\nKind regards,\nCorporate Development" },
    { id: "ACT-2b11", kind: "Clarification", tmpl: "clarification", to: "ceo@company-b.example", company: "Company B", subject: "A quick clarification on your warehouse footprint", status: "sent",
      body: "Hello,\n\nCould you confirm the total warehouse area across your sites? Our public-record check found 3 of 4 sites.\n\nKind regards,\nCorporate Development" }
  ],

  audit: [
    ["16:02:11", "reasoning.confirmed", "M-2026-11-22-014 v1 · 3 answers · basis = operates", "a91c…"],
    ["16:02:12", "mandate.frozen", "rubric R1-2026.11.22-2 · terms.yaml v3", "3f0e…"],
    ["16:02:13", "run.started", "budget 450 credits · deadline 20 min", "77b2…"],
    ["16:09:40", "market_im.drafted", "8 RECOMMEND · 19 CONSIDER · 25 NOT RECOMMENDED · 394 credits", "c4d8…"],
    ["16:11:02", "shortlist.picked", "Company C, A, B → screen", "0be1…"],
    ["16:20:55", "company_im.drafted", "IM-2026-11-29-003 · 68.75–76.25 · rule 4", "41d7…"],
    ["16:24:30", "action.intent", "ACT-2b11 clarification → Company B · Message-ID <act-2b11@datadesigner.local>", "e2a9…"],
    ["16:24:31", "action.sent", "smtp.gmail.com:587 STARTTLS · 250 OK", "e2aa…"],
    ["16:24:33", "action.reconciled", "IMAP [Gmail]/Sent Mail rfc822msgid match", "e2ab…"]
  ],

  connections: [
    { name: "Crustdata API", icon: "db", detail: "api.crustdata.com · x-api-version 2025-11-01", key: "CRUSTDATA_API_KEY", state: "ok", note: "smoke: /account/endpoints 200 · 0 credits" },
    { name: "Claude API", icon: "spark", detail: "claude-sonnet-5-5 · claude-haiku-5-5 · claude-opus-5-5", key: "ANTHROPIC_API_KEY", state: "ask", note: "asked on first run by tools/setup_secrets.py" },
    { name: "Gmail SMTP", icon: "mail", detail: "smtp.gmail.com:587 STARTTLS · IMAP reconcile imap.gmail.com:993", key: "GMAIL_ADDRESS · GMAIL_APP_PASSWORD", state: "ask", note: "16-character app password · 2-Step Verification required" },
    { name: "Mail mode", icon: "shield", detail: "MAIL_MODE=test → every email redirected to TEST_INBOX", key: "TEST_INBOX", state: "ok", note: "switch to live only for the demo" }
  ],

  analyst: {
    "Why is claim integrity only 2 of 4?": "C1 counts the 14 critical deck claims: 10 VERIFIED (1.0 each), 2 PARTIALLY (0.75), 1 UNVERIFIED (0.5) and 1 NOT VERIFIABLE (0 on the floor). That is 85.7% → 3 points. The non-critical FALSE (“GST-registered in 6 states”) costs 1 point → 2. Ceiling: 92.9% → 4 − 1 = 3.",
    "What would make this a PURSUE?": "Conditions 1 + 2: the contract extract (+5.00) and evidence for the API integrations and IoT sensors (+1.25). That lifts the floor to 75.00 — rule 3 — and closes the open tech requirement.",
    "Does a Delhi-HQ company count for Maharashtra?": "Yes, because you confirmed basis = operates. Company C is headquartered in Delhi but holds a GST registration with state code 27 and 63% of its footprint (GST, staff, openings, sites, fleet) is in Maharashtra.",
    "Is the leadership fit?": "FIT WITH GAPS (3.0). CEO, COO and Head of Sales have run larger operations and none links to a failed company. Gap: no technology leader for the deck’s “tech-led platform” pillar."
  }
};
