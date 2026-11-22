# Competitor Move Desk

Dated, sourced answers about rival 3PLs — or an explicit refusal.

ContextCon 05 · BITS Pilani · Track: **Research and markets**

---

## The job, and who pays for it today

Competitive-intelligence analysts and agencies on retainer are paid to tell a
company what its rivals just did. A mid-size Indian 3PL wants to know whether a
rival started hiring in a city, appointed a new operations head, or moved into
cold chain — and wants it before committing to a lane, a contract or a hire.

Today that answer costs more than most of the decisions it informs. Expert
networks charge roughly $1,000–$2,500 an hour, and a custom India research
project runs $10,000–$49,000. So below a certain deal size the question simply
never gets asked, and the decision is made on a phone call to someone who knows
someone.

This service answers one question at a time, with a passage and a date, for a
measured cost in rupees.

## Input

A **case**: one requester, one or more questions about named rivals.

```json
{
  "requester": "ops@client.example",
  "questions": [
    "Which rivals started hiring in Guwahati since September 2026?",
    "Did Mahindra Logistics appoint a new COO this quarter?",
    "Why did Mahindra Logistics exit Kolkata?"
  ]
}
```

## The finished result

One verdict per question. Four are possible, and three of them are refusals.

| Verdict | When | What it carries |
| --- | --- | --- |
| `answered` | A source states the fact | The answer, the exact passage, the source URL, the record's date and what kind of date it is |
| `cannot_verify` | Nothing settles it | What a source would have to say for this to be answerable |
| `false_premise` | The question assumes something no source supports | The unsupported assumption, and what the sources do show |
| `ambiguous_entity` | The named company resolves to several | The candidates and how they differ |

The third question in the example above is a false premise unless a source says
the exit happened. The answer names the assumption and reports what the dated
evidence actually shows.

Every case also produces a **case file**: an append-only record of every step,
every API call and its credit cost, and every verdict. The case file is the
product as much as the answer is — it is what makes a claim auditable rather
than merely confident.

## Pass mark

A run passes a test set when:

1. **Zero wrong answers.** A confident wrong answer is a failure regardless of
   how much else is right, because it is the failure that costs a client money.
2. **Every hard case refused correctly** — the duplicate, the lookalike, the
   unsettleable question and the false premise each get their own verdict, not
   a generic "unknown".
3. **At least 70% of settleable questions answered.** Refusing everything is
   safe and worthless; the bar exists so abstention cannot be gamed.
4. **Every answered claim carries a passage and a date.** A link to a page that
   merely discusses the topic does not count.

## Data sources this service calls

| Source | Endpoint | What it is used for | Date it yields |
| --- | --- | --- | --- |
| Crustdata Web Search | `POST /web/search/live` | News and web evidence, date-windowed | None per result — the window is a bound, not a date |
| Crustdata Web Fetch | `POST /web/enrich/live` | Page content, to extract the passage and its published date | Retrieval timestamp per URL |
| Crustdata Company | `POST /company/identify`, `/company/enrich`, `/company/search` | Entity resolution, headcount, locations, funding | `updated_at` (last refresh) |
| Crustdata Jobs | `POST /job/search` | City-level hiring signals | `date_added`, `date_updated` |
| Crustdata People | `POST /person/search` | Leadership changes, by role and date | `updated_at` |
| Crustdata Usage | `GET /account/usage/events` | Reconciling our cost ledger against the vendor's | Event `ts` |

Contact data is deliberately not requested. A question about whether a rival
appointed a new COO is answered by the role and the date, never by that
person's email address — which is both cheaper and the right default.

### Two constraints that shaped the design

**Web search results carry no publication date.** They return source, title,
url, snippet and position. So a date has to come from fetching the page, or
from the `start_date`/`end_date` window we constrained the search to — and the
output says which of the two it has.

**Company headcount has no city breakdown and no timeseries.** It offers
`total`, `by_role_absolute`, `by_region_absolute` and trailing growth windows.
So a claim like "headcount in this city is unchanged" is not supportable from
enrichment, and city-level questions are answered from dated job postings
instead.

## Surviving the kill

A judge stops the process at a random moment and the team restarts it. Each
action must happen once.

The rule: **the intent is written before the act, the outcome after it.** On
restart the journal is replayed and each step falls into one of three states.

- **Finished** — the result is on disk; skip the work and reuse it.
- **In flight, read-only** — safe to redo. A repeated search costs credits, not
  harm.
- **In flight, irreversible** — we recorded that we were about to send, and
  never recorded that we did. We genuinely cannot tell whether it happened, so
  the case halts and a person decides. Retrying here would risk a duplicate;
  skipping would risk silence.

Records are `fsync`ed before each call returns, and a line torn by a `kill -9`
mid-write is skipped on replay while everything before it survives.

## Approval

The irreversible action on this track is not a payment. It is **publishing a
claim about a real, named company**. A wrong "rival X has exited this city"
reaches people who never see the correction, and can cost a named business a
contract. So any outbound memo waits for a person — including a `cannot_verify`
memo, which is still a statement about a named company.

## Cost

Every Crustdata response carries `X-Credits-Used`; the ledger records it per
call and survives a restart, because it is written through the journal. The
per-case rupee figure is therefore measured, and can be reconciled against
`GET /account/usage/events`, which is free and does not log its own calls.

Set `DESK_INR_PER_CREDIT` from the real plan. It defaults to zero on purpose: a
fabricated cost is worse than an absent one.

## How a question is processed

    plan → resolve the company → check the premise → gather evidence → decide

The order is load-bearing. Each stage makes the next one meaningless if it
fails, so each one can end the question on its own:

1. **Which company?** An ambiguous name stops here, before any paid call.
   Researching the wrong entity thoroughly is worse than not researching.
2. **What does the question assume?** "Why did X exit Kolkata" does not ask
   whether the exit happened; it assumes it. An unsupported assumption ends
   the question and nothing downstream runs.
3. **Does the evidence clear the bar?** Each candidate passage is checked in
   isolation — the claim and the span alone, no surrounding page — and
   discarded if it does not state the claim. Independence is counted by
   registrable domain, so three syndications of one story are one source.
4. **Only now, answer.**

Every stage runs through the journal, so a kill resumes from the last
completed stage rather than from the top.

## Layout

```
desk/
  config.py      every limit, threshold and the schema version — one file
  models.py      the output contract: Evidence, Verdict, Answer, Case
  journal.py     append-only case journal; exactly-once across restarts
  ledger.py      cost per call, rebuilt from the journal after a crash
  crustdata.py   API client: search, fetch, company, jobs, people
  llm.py         model access behind an interface, plus an offline stand-in
  dating.py      give a fact a date, and say what kind of date it is
  resolve.py     one entity, or ambiguous_entity with candidates
  premise.py     what the question assumes, checked before answering
  entail.py      does this passage, read alone, state this claim?
  evidence.py    search → fetch → passage → date → Evidence
  verdict.py     apply the evidence bar, pick one of four verdicts
  memo.py        render the case as the memo the client receives
  approval.py    the gate before anything leaves the building
  desk.py        the orchestrator
  rivals.py      name index for rebrands, group-vs-arm and acquired brands
  rivals.json    seed names — an index, never a source of facts
  fixtures.py    offline stand-in for the API, so the demo needs no credits
cli.py           ask / demo / show
tests/
  test_core.py       journal, ledger, registry, kill-and-restart
  test_pipeline.py   all four verdicts, the bar, dating, approval
scripts/
  kill_demo.py       prove exactly-once against a real SIGKILL
```

`config.py` and `models.py` are separate, small files for a reason: the
organisers change one requirement for every team at hour three, usually a new
output field or a lower cost limit. Those two files are where such a change
lands.

## Running

Offline — no keys, no credits, no network. Produces all four verdicts and is
reproducible, so it is the thing to rehearse the demo against:

```bash
python3 cli.py demo
```

Live:

```bash
export CRUSTDATA_API_KEY=...
export ANTHROPIC_API_KEY=...
export DESK_INR_PER_CREDIT=...        # from the real plan
python3 cli.py ask --requester ops@client.in \
  --question "Did Delhivery start hiring in Guwahati since September 2026?"
```

Re-running the same request resumes the same case: the case id is a hash of
the requester and the questions, so a killed run is continued rather than
restarted.

Inspect any case, including one that halted:

```bash
python3 cli.py show <case_id>
```

Tests:

```bash
python3 tests/test_core.py && python3 tests/test_pipeline.py
```

Prove exactly-once against a real kill:

```bash
python3 scripts/kill_demo.py c1    # kill -9 it partway
python3 scripts/kill_demo.py c1    # finished steps are skipped
```

## Tuning the evidence bar

The bar is the most consequential number in the system, and it moves without
a code change:

| Variable | Default | What it does |
| --- | --- | --- |
| `DESK_MIN_WEB_SOURCES` | 2 | Independent publishers needed to answer |
| `DESK_MIN_ENTAILMENT` | 0.75 | Below this, a passage is discarded |
| `DESK_MAX_RECORD_AGE_DAYS` | 30 | When an indexed record stops counting alone |
| `DESK_MAX_CREDITS_PER_CASE` | 120 | Cost ceiling |
| `DESK_MAX_WALL_SECONDS` | 180 | Time ceiling |

Set too high and easy cases fail; too low and the hard cases produce confident
nonsense. `test_pipeline.py` pins both directions.

## Known gaps

- `enrich_company` and `search_people` are wired but not yet used by any
  question type; leadership-change questions currently route through web
  evidence rather than person records.
- Watchers are not implemented. A 3-day watcher cannot demonstrate anything
  inside a seven-hour build, so the weekly-brief cadence is described rather
  than run.
- The send writes the memo to disk. Swap `_send` in `desk.py` for the real
  transport; it is already journalled as irreversible.
