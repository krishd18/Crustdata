# API notes — where the live APIs differ from the docs (22 Nov 2026)

| Area | Docs / plan said | Live behaviour | Where handled |
|---|---|---|---|
| Crustdata rate limits | 30 RPM search/identify, 15 RPM enrich | `GET /account/endpoints`: **effective 5 RPM** on company search/enrich/identify, person search/enrich, job search (token limit 100 RPM) | `config/sources.yaml` rpm: 5; runtime.lock.json |
| Crustdata search cost | ≈0.03/result | premium field groups bill per row (5 rows with headcount+taxonomy = 3.15 credits; 300 minimal rows ≈ 39) | Scout requests only needed fields; S2 uses a 300-row sector search + a free job-side aggregation |
| `company/search` growth fields | `headcount.growth_percent.6m` | filter keys `1m/3m/6m/12m`; `company/enrich` returns `mom/qoq/six_months/yoy/two_years` | `a02_scout.growth()`, `a11_research` |
| `company/enrich` people | `people.founders[]` | `people.{founders, decision_makers, cxos}`; each founder already carries `experience.employment_details.past[]` with `employee_title/employer_name/employee_start_date/employee_end_date` → no extra person/enrich call for prior roles | `a11_research.find_list` |
| `job/search` | — | `job_listings[].{crustdata_job_id, job_details{title,category,url}, company{basic_info{crustdata_company_id,name,industries}}, location{city,state}, content{description}, metadata{date_added}}`; aggregations `buckets[{key,count,metadata{company_name}}]` cost 0 credits | `a11_research.research_qa` |
| `web/search/live` | result URLs per outlet | URLs are `google.com/goto?...` redirects → outlet unknown; corroboration searches are restricted with `site=<tier-A domain>` and fetched before own-reporting checks | `a11_research.corroborate` |
| Claude structured outputs | Pydantic schema subset | rejects an empty `{}` schema (from `Any` fields) → mapped to `anyOf[string,number,boolean,null,array<string>]`; stripping keywords must not touch property names (a field called `default`) | `core/claude.py::strict_schema` (unit test) |
| Claude model | `claude-sonnet-5-5` default | team choice **`claude-sonnet-5`** for every role (accepts `output_config.format`, `effort`, `thinking: disabled`); `-5-5`/opus remain fallbacks | `config/llm.yaml`, runtime.lock.json |
| YAML | — | an unquoted `FALSE:` key parses as boolean | `config/verdicts.yaml` quotes it |
| Network (this cloud session) | — | `web.archive.org`, `smtp.gmail.com`, `imap.gmail.com` unreachable → Wayback cross-check degrades to "unavailable" (noted, never a silent pass); Gmail verified only on a machine with SMTP egress | README · How it runs |
