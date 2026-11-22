# SecondLook: diligence before the second meeting

Paste a counterparty's deck or teaser. SecondLook checks each claim against live records. Anything it can't settle becomes the exact document to request before the second meeting.

Tracks: Investing, Research and markets.

## Run it

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then fill in CRUSTDATA_API_TOKEN (ANTHROPIC_API_KEY optional)
.venv\Scripts\python -m uvicorn app.main:app --port 8765
```

Open http://localhost:8765, click **Load sample**, then **Check claims**.

Tests: `.venv\Scripts\python -m pytest -q` (offline), and the kill test: `.venv\Scripts\python scripts\kill_test.py`.

## What it does

1. **Resolve the company.** Uses the domain if given (`/company/identify`). Name-only lookups that match several companies are narrowed by city; if the result is still ambiguous, the run is held until a person picks the right company.
2. **Pull records once per run.** These are the company profile (`/company/enrich`: basic info, HQ and every office address, headcount and growth, founders/CXOs with work history, funding, news), recent job posts (`/job/search`), the homepage and about page (`/web/enrich/live`), and the domain's first Internet Archive snapshot.
3. **Extract claims.** Claude reads the teaser into typed claims using a fixed schema. Without an Anthropic key, a rule-based extractor is used instead.
4. **Check each claim with deterministic code.** The LLM never decides a verdict.
5. **Build the sourced claims register.** Each row has the verdict, a one-line reason, the API field or URL, the exact value or passage, and the retrieval date.

| Claim type | How it's checked | Verdicts |
|---|---|---|
| Identity | `basic_info.year_founded`, `locations.headquarters` | verified / consistent / contradicted |
| Workforce | `headcount.total` as a **lower bound** | contradicted (only if the claim is below the record) / consistent |
| Growth | `headcount.growth_percent.yoy`, `hiring.openings_growth_percent` | contradicted (only if the direction is opposite) / consistent |
| Footprint | `locations.all_office_addresses`, job-post cities | verified / partial / cannot verify |
| Investors | `funding.investors`, news, web search | verified / cannot verify (lists every source checked) |
| People | founders' and CXOs' `experience.employment_details` | verified / contradicted (named person only) / cannot verify |
| Customers | news, web search, split into the company's own site vs. others | verified / self-reported / cannot verify |
| Dates | founding year, first archive snapshot, first news item | verified / earliest evidence / contradicted |
| Efficacy | independent web mentions of the figure | independently supported / self-reported |
| Forward-looking | not checked | projection |
| Premise in a question | job posts in that place in the last 120 days, addresses, regional headcount | false premise / unsupported premise |

## Three differentiators

- **"Ask them for this" list.** Every unsettled claim maps to one document from a fixed claim-type → document table ([app/doc_table.py](app/doc_table.py)), e.g. "250 employees" → EPFO ECR statements for 3 months. Claude only writes the email's opening and closing lines around the list and is told not to add or drop items.
- **Inconsistencies across the target's own sources.** The same metric (employees, warehouses, growth %, efficacy %) is compared across the deck, the website pages, the company's profile "About" text and the founders' profile summaries. Every conflicting figure is shown with its source.
- **Re-check before meeting 2.** Every run is a dated snapshot. **Re-check** runs every claim again and shows what changed: verdicts, record values, headcount, job count, and each previous leader's *own* profile (`/person/enrich`), so a CFO who left still shows up. An optional Crustdata person watch on the founders and CXOs can be previewed (free, shows the per-change price) and then armed.

## Irreversible action: sending the request list

Drafts wait for a named person's approval. On approval, the attempt is written to the SQLite journal (`synchronous=FULL`) **before** any I/O, and the send carries an idempotency key. On startup, `outbox.recover()` finishes any approved-but-unconfirmed sends with the same key. `scripts/kill_test.py` kills the process right after the journal write and again right after delivery. Both cases end with exactly one delivery, and a second restart sends nothing. The transport is a file-backed mailbox that behaves like an email API with an `Idempotency-Key` header. A real provider can replace it if it implements `send(key, msg)`.

## Ethics

- Founders' data is used only to check claims the company made, and only their professional history. No contact fields are requested. Contact-like keys are stripped before anything is stored, and logs mask emails and phone numbers.
- "Contradicted" requires a contrary record in hand. Every verdict has a plain one-line reason.
- The sample teaser in `samples/` is **synthetic**. It was not issued by the company it names, and some of its claims are deliberately wrong so that every verdict type appears.

## Cost

Each run records `X-Credits-Used` from every Crustdata call, plus LLM tokens, and shows the total on the dossier (**Sources & cost** tab). Set `CRUSTDATA_CREDIT_USD` and `USD_INR` to get a rupee figure. Set the per-dossier price from that measured cost. Analyst or advisor rates should only be quoted from a cited source.
