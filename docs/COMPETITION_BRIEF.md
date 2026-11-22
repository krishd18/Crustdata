# ContextCon 05 · BITS Pilani — Competition brief

> Everything about the competition in one place, from the problem statement PDF and the kickoff slides. Each section is mapped to where Data Designer meets it.

---

## 1. Challenge

**"Services, Replaced."** Pick a job a firm earns a fee for today, and build the service that does **all of it, from request to result**. Each claim has a source, and a person approves only the actions that cannot be undone.

The service is the agent system a team builds. It delivers the finished work, for example "a vendor cleared, with the evidence on file".

**Data Designer's job:** counterparty diligence and market research for the client, a mid-size Indian 3PL:
- vendor/carrier clearance;
- finding, screening and checking acquisition targets and partners;
- research questions about markets.

**Tracks:** Trust & compliance + Investing (plus Research & markets questions). There are 10 tracks plus an Open track, and a team may join 2 tracks.

## 2. The client

A fictional mid-size Indian 3PL whose counterparties are **real companies**. Its name, records and requests are released at kickoff. Organisers may change client information during the build: a new rule, an updated carrier record, a new price. → `docs/KICKOFF_NOTES.md`; config-first design.

## 3. Requirements for every service → where Data Designer meets them

| Rule | What it means | Data Designer |
|---|---|---|
| Live data | live, real-world data for at least one decision (Crustdata, registries, public APIs, web, own crawler); mock data only in tests | Crustdata + registries + reliable media; replay only in tests |
| Test cases | hidden set per request with hard cases (duplicate, lookalike, "cannot verify"); records dated after **1 Sep 2026**; Open-track teams submit 3 cases by 11:00 AM | TEST_PLAN case catalogue; record dates on every fact |
| Sources | each fact links to its record: web page, API response or filing; the exact passage or field + the record's date; the source must state the fact itself; no facts from model memory; otherwise **cannot verify** + what is missing | quote lock; 7 verdict classes; `missing:` on ⚪ |
| Approval | irreversible actions (payment, email to a client) wait for a person; payments in test mode | approval queue + journal; Gmail in test mode (redirect to a test inbox) + Mailpit for automated tests |
| Limits | each run has a time and a cost limit; record the cost of each call | budget guard; cost ledger from `X-Credits-Used` |

**Example (Buying & paying track):** a duplicate charge must be held as a possible duplicate, and an unidentifiable payee → "cannot verify, held for a person". Posting a duplicate or guessing a payee fails the case.

## 4. Deliverables

- **Code** in the organiser repository (our branch `hackathon-Rohan`). Commit throughout; the organisers follow each repo.
- **README:** states the job and who pays for it today, the input, the finished result and the pass mark, plus **each data source the service calls**.
- **Architecture diagram** in the repo: components, data flow, and where the data calls, approvals, retries and the cost ledger sit.
- The service can be one agent, a system of agents, an MCP server or a CLI tool.

**Kickoff slides, "Submit by 6:00 PM. Once at 2:30 PM. The latest counts."** Submit: Project (name, one line, theme) · Repo (public on GitHub) · Demo video (one two-minute link) · Diagram (a link anyone opens) · Every member (names, emails, ID numbers). *(Timings were later extended; follow the organisers' new times.)*

**README (judges start there):** The service · What it does now · What comes next · How it runs · What you tried · Why this way.

## 5. Environment

- Any model, framework or language; teams bring their own model keys. Data Designer uses the **Claude API** (Haiku, Sonnet, Opus by role) and sends approved email through **Gmail SMTP**.
- **Crustdata API:** people, company and job data, web search and fetch, and watchers, each with its last-refresh date. Docs at docs.crustdata.com; credits provided.
- **Kickoff-slide API list:** Person Search · Person Enrich · Company Search · Company Identify · Company Enrich · Job Search · Web Search and Fetch · Watcher · MCP server.
- Other live sources are allowed. The kickoff kit gives the input and output formats.

## 6. Format

1. **Build (7 h).** At hour 3 the organisers change one requirement for all tracks (e.g. a new output field, or a lower cost limit); the service must meet it at screening. A code freeze follows the build; the only later change allowed is the finals live fix.
2. **Screening.** The organisers run an unseen request + the hidden set, stop and restart the service, and check the README, diagram and logs. One member runs the service and answers questions. **8–12 teams** go to the finals.
3. **Finals (12-minute slot).**
   - 3 min demo, including **kill on stage**: a judge stops the process; the team restarts it and each action happens once.
   - 5 min **live fix**: the judges ask for one small change.
   - 2 min questions, including one **system design** question (100× volume, a second client).
   - 2 min changeover.

## 7. Evaluation

**Screening (no score):** correctness (hidden set + unseen request), robustness after restart, engineering (diagram, logs, cost records, README, repo history) and a working demo. A wrong answer counts against a team more than "cannot verify".

**Finals (100 points; the CS judges' scores are averaged):**

| Area | Judge | Pts | Checked | Data Designer's answer |
|---|---|---|---|---|
| Live run | CS | 20 | unseen request → correct, sourced result | query reasoning + sourced memo |
| Robustness | CS | 15 | kill on stage; each action once | journal + reconcile; `make kill-demo` |
| Design | CS | 15 | live fix + system design question | config-first playbook; scaling answers |
| Ethics | Ethics | 25 | personal data, approvals before harmful actions, explaining decisions | DPDP-aligned; approvals; fixed rubric shown before suggestions; fairness rules |
| Financial feasibility | Finance | 25 | buyer, price in ₹, measured cost per job, would a firm pay | ARCHITECTURE §21 + `reports/cost_per_job.md` |

The finals score alone decides the ranking. Teams also vote for People's Choice ("the service they would hire").

**Kickoff slide, "How winners are picked" (emphasis):** End-to-end execution 25 · Facts and verification 20 · Robustness and edge cases 20 · Customer value and idea 20 · Demo and understanding 15. Data Designer's matching evidence:
- E2E flows (Phase 3);
- quote lock + 7 classes;
- hard-case catalogue + chaos;
- Information Memo + ₹ pricing;
- demo scripts.

## 8. Teams and logistics

1–4 builders; each brings a laptop, charger and college ID.
