# SecondLook: diligence before the second meeting

Paste a counterparty's deck or teaser. SecondLook checks each claim against live records. Anything it can't settle becomes the exact document to request before the second meeting.

Tracks: Investing, Research and markets.

**Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) covers the components, the data flow, and where data calls, approvals, retries and the cost ledger sit, plus the business architecture (actors, six-step value chain, unit economics, guardrails).

## Run it

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # then fill in CRUSTDATA_API_TOKEN (ANTHROPIC_API_KEY optional)
.venv\Scripts\python -m uvicorn app.main:app --port 8765
```

Open http://localhost:8765. Start with **Find targets**, or **Add a company directly**, and use the sample decks in step 4.

Tests: `.venv\Scripts\python -m pytest -q` (offline), and the kill test: `.venv\Scripts\python scripts\kill_test.py`.

## The workflow

```
1. FIND       company/search + enrich -> shortlist, each with sourced signals
              (headcount growth, hiring by city, funding, leadership)
2. SCREEN     check each target's PUBLIC claims (website, profiles) -> early red flags
3. REACH OUT  draft an intro asking for a teaser -> a person approves -> sent once
4. CHECK      the target's deck arrives -> claim-by-claim register + verdicts
5. REQUEST    "ask them for this" list (EPFO, leases...) -> a person approves -> sent once
6. RE-CHECK   before the second meeting -> what changed since step 4
```

**FIND reads the thesis into Crustdata parameters** ([app/thesis_ai.py](app/thesis_ai.py)). The text goes to the Bedrock model (Mantle first, the same provider chain as news analysis), which fills a fixed schema: what the companies do, locations, revenue and funding ranges (in $ or ₹ lakh/crore), headcount, growth, last round, founding years, "acquirable" and "private". Code validates every value and builds the filters itself: `revenue.estimated.*`, `headcount.*`, `funding.*`, `basic_info.year_founded`, `revenue.acquisition_status`, `basic_info.company_type`, `locations.*`. "Acquirable" means not already acquired and not public, government, nonprofit or educational. Anything that can't become a filter (e.g. "good culture") is shown as *not applied*. **Read thesis** previews all this with no Crustdata credits spent, and a rule-based reader takes over if no model is available.

Each target in the pipeline shows these six steps. A step can be skipped: a deck that arrives unasked goes straight to step 4.

**Stop, at every step** ([app/cancel.py](app/cancel.py)). Anything that calls Crustdata or a model has a **■ Stop** button: Read thesis, Find, a Screen / Check / Re-check run, a deck fetched from a URL, and the watch preview. Stop is checked before every Crustdata call and while waiting on every model call, so the step ends at once and no new credits are spent. A call already sent can't be recalled. Its credits are still counted on the run, and its answer is thrown away. A stopped run is kept as "stopped" with its cost, and the last finished register stays on screen. Sends (steps 3 and 5) have no Stop: they are a single journaled call after a person's approval. API callers send their own `x-job-id` header and stop with `POST /api/jobs/{id}/cancel`. Background runs stop with `POST /api/runs/{id}/cancel`.

## Inputs: the document parser ([app/ingest.py](app/ingest.py))

| Input | How it's read |
|---|---|
| Kickoff-kit request (JSON or text) | `parse_request()` maps it onto company + document. Nested, flat and batch shapes are accepted; see `REQUEST_KEYS` |
| PDF deck or teaser, text or scanned | `pypdf`, then `pdfplumber` if pypdf finds little text, then **OCR** ([app/ocr.py](app/ocr.py)). OCR runs on pages with no text layer, only a title, or garbled spaced-out letters. Pages are rendered with `pypdfium2` and read by the Bedrock Mantle vision model (`qwen3-vl`, about 6 s a page, 4 at a time), or by local Tesseract if installed. `SECONDLOOK_OCR=auto\|mantle\|tesseract\|off`, `OCR_MAX_PAGES` (25). Emails and phone numbers are removed before deck text goes to the claim model. Public PDFs found by web search are not OCR'd |
| PowerPoint deck (.pptx) | `python-pptx`: slide text, tables and speaker notes |
| A company website URL | Crustdata `/web/enrich/live`, HTML → text |
| Pasted text | Used as is |

Machine interfaces (synchronous, return the register as JSON):

```powershell
curl -X POST localhost:8765/api/check -H "content-type: application/json" --data "@samples/request_example.json"
curl -X POST localhost:8765/api/check -F "file=@samples/stockarea_teaser.pdf" -F "company=Stockarea" -F "domain=stockarea.io"
.venv\Scripts\python -m app.cli samples\stockarea_deck.pptx --company Stockarea --domain stockarea.io --table
```

`python scripts/make_samples.py` rebuilds the sample PDF, PPTX and JSON request.

## Public record: news, registry and documents ([app/public.py](app/public.py))

Every screen and check also collects the public record through Crustdata web search (about 7 searches, roughly 7 credits):

- **News:** the company record's `news`, plus a news-only search. Press releases are labelled as written by the company, so their figures count as its own claims. Editorial news figures go into the cross-source comparison as third-party sources.
- **Registry:** legal entities with their CIN, incorporation date, status and how each is tied to the company (website/email domain, brand page, or similar name only). The CIN encodes the state and year of registration. Only the *operating* entity, the one incorporated when the company says it was founded, feeds the identity and date checks. Other linked entities are shown as related. Entities found on earlier runs are carried forward, because search results vary from run to run.
- **Documents:** public PDFs and business paperwork (invoices, e-way bills). Cities they name become footprint evidence, and recent ones count as activity for premise questions. Direct PDF links are downloaded (size-capped) and read with the same parser as decks.
- **News analysis** ([app/news_ai.py](app/news_ai.py)): every news item goes in one call to an LLM. Providers are tried in `NEWS_PROVIDERS` order: Amazon Bedrock's OpenAI-compatible Mantle endpoint first when `BEDROCK_MANTLE_URL` is set (default model `qwen.qwen3-vl-235b-a22b-instruct`; about 11 s for a company's news), then Amazon Bedrock (`AWS_BEARER_TOKEN_BEDROCK`, model `BEDROCK_MODEL`, default `openai.gpt-6.1-sol` via the Converse API, retried with the `global.` inference profile when required), then NVIDIA (`NVIDIA_API_KEY`, Kimi K3.1 Pro `moonshotai/kimi-k3.1-pro`, changeable with `NEWS_MODEL`). Direct article links are first read in full through Crustdata `/web/enrich/live`. Per article the model returns: about this company or not, event type, sentiment, written by the company or not, a summary, figures and concerns. Every figure and concern must carry a verbatim quote, and the quote is checked against the article text in code; anything unquoted is dropped. Concerns become "needs confirmation" flags, and figures join the cross-source comparison. If the model fails or times out, the run continues on a keyword scan and says so.
- **Needs confirmation:** a registry status such as "Under CIRP", or adverse terms (raid, fraud, insolvency…) next to the company's name, becomes a flag plus a document request, never a "contradicted" verdict. A search snippet is not a registry extract.

Google redirect links can't be fetched (they show a bot check), so those results are used from their snippet and kept as links for a person to open. Emails and phone numbers are stripped from everything stored.

## How a check works

1. **Resolve the company.** Uses the domain if given (`/company/identify`). Name-only lookups that match several companies are narrowed by city; if the result is still ambiguous, the run is held until a person picks the right company.
2. **Pull records once per run.** These are the company profile (`/company/enrich`: basic info, HQ and every office address, headcount and growth, founders/CXOs with work history, funding, news), recent job posts (`/job/search`), the homepage and about page (`/web/enrich/live`), and the domain's first Internet Archive snapshot.
3. **Extract claims.** Claude reads the teaser into typed claims using a fixed schema. Without an Anthropic key, **decks are read by the Bedrock model** (the news-analysis chain, Mantle Qwen first; turn off with `SECONDLOOK_DECK_MODEL=off`). Real decks are slide fragments ("Team of 30+", "Repeat Orders: 90%", a figure on one line and its label on the next) that sentence rules can't read. The model must quote the deck word for word, and code checks each quote and that its figure is in it. Emails and phone numbers are removed before the text is sent. If the detailed prompt returns nothing, a short prompt is tried. The rule-based extractor fills any claim type the model missed, and takes over if no model is available. The Check step shows which reader was used and what was dropped. If the pasted text contains no checkable claims, the claims the company makes on its own website and profile are checked instead.
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

Drafts wait for a named person's approval. On approval, the attempt is written to the SQLite journal (`synchronous=FULL`) **before** any I/O, and the send carries an idempotency key. On startup, `outbox.recover()` finishes any approved-but-unconfirmed sends with the same key. `scripts/kill_test.py` kills the process right after the journal write and again right after delivery. Both cases end with exactly one delivery, and a second restart sends nothing.

**Delivery** ([app/outbox.py](app/outbox.py)) is picked from `.env`:

| Transport | Set | Repeat after a crash or timeout |
|---|---|---|
| **Resend** (recommended) | `RESEND_API_KEY`, `MAIL_FROM` (a verified domain) | Safe for 23 h: the same `Idempotency-Key` returns the original email |
| **SMTP** (Gmail app password, Office 365, SES SMTP…) | `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM` | Never automatic: SMTP can't dedupe |
| Demo mailbox (default) | nothing | Dedupes on the key; files land in `data/mailbox`, nothing leaves the machine |

`MAIL_REPLY_TO` and `MAIL_BCC` (a team copy of every send) are optional. The "From (your team)" field becomes the display name when `MAIL_FROM` has none.

An outbox row is `awaiting approval → approved → sent`, or `failed` / `uncertain`:

- **failed:** the provider refused, or couldn't be reached, before accepting anything (bad key, unverified domain, refused address). The error is shown and **Retry send** is safe.
- **uncertain:** an attempt may have reached the provider and repeating isn't provably safe (SMTP, a Resend attempt older than its window, or a changed transport). The machine never resends it. A person checks the Sent folder and picks **Not there, send it** or **It's there, mark sent**.

**Send a test email** (in steps 3 and 5) checks the configuration without touching the journal.

## Ethics

- Founders' data is used only to check claims the company made, and only their professional history. No contact fields are requested. Contact-like keys are stripped before anything is stored, and logs mask emails and phone numbers.
- "Contradicted" requires a contrary record in hand. Every verdict has a plain one-line reason.
- The sample teaser in `samples/` is **synthetic**. It was not issued by the company it names, and some of its claims are deliberately wrong so that every verdict type appears.

## Flush the pipeline

**Flush** (next to "Pipeline" in the sidebar) clears every target in one go. It first shows what will be cleared (targets, runs in progress, drafts awaiting approval, approved sends), and recent searches are cleared only if ticked. Runs in progress are stopped first, so no more credits are spent. Nothing is deleted: targets are hidden (`flushed_at`) and **Restore** brings back the last flush. The send journal is never touched, so a send that was already approved still completes exactly once. A company found again after a flush starts as a fresh target. To remove just one target, hover over its row and press **×**, then confirm. Its runs stop, it is hidden (`deleted_at`), and **Undo** in the sidebar puts it back (`POST /api/dossiers/{id}/delete`, `/undelete`). API: `GET /api/pipeline/flush` (preview), `POST /api/pipeline/flush {"searches": false}`, `POST /api/pipeline/restore`.

## Rate limits and failed runs

Crustdata limits requests per endpoint per minute ([docs](https://docs.crustdata.com/general/rate-limits); `/company/enrich` defaults to 15/min). [app/crust.py](app/crust.py) paces calls process-wide, across every run and search, so parallel work doesn't burst past the limit. Change the limits with `CRUSTDATA_RATE_LIMITS="/company/enrich=15,/person/enrich=15"`. A 429 is waited out (`Retry-After` / `X-RateLimit-Reset`, else 5, 10, 20, 30 s) and retried, and all callers of that endpoint back off together. A run's progress says when it is waiting. After `CRUSTDATA_MAX_WAIT` seconds (default 75) the step fails with a plain sentence. FIND enriches its top results in **one** `/company/enrich` call, not one call per company.

A failed or stopped run never replaces the last good result. Every step shows it as a note above that result, with what it cost and a **Try again** button. Runs left "running" by a server restart are marked as interrupted at startup.

## Cost

Each run records `X-Credits-Used` from every Crustdata call, plus LLM tokens, and shows the total on the dossier (**Sources & cost** tab). Set `CRUSTDATA_CREDIT_USD` and `USD_INR` to get a rupee figure. Set the per-dossier price from that measured cost. Analyst or advisor rates should only be quoted from a cited source.

## Team

- Rohan
- Aaryan Nagda
