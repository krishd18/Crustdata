# Kickoff notes

No kickoff kit (input/output formats, client records) is present in the organiser repository on branch `hackathon-Rohan` at build time (only `README.md` and `OBJECTIVE.md`). Until it arrives:
- **Input:** free text (`POST /runs {"text": …}`, `datadesigner ask "…"`) or a pack (`{"pack_id"|"pack": {company, pages|files, extracts, …}}`).
- **Output:** memo Markdown/HTML + JSON (`GET /runs/{id}/memo?format=md|html|json`); fields per `config/schema.yaml` — fill `organiser_output_map` when the kit lands (config only).
- **Client profile (sample):** mid-size Indian 3PL, present in Delhi, Gujarat, Karnataka; weak in Maharashtra (walkthrough sample). Put the real one in `config/client.yaml` (read by A1 and A14).
- **Prices:** Crustdata from `GET /account/endpoints` (runtime.lock.json); ₹/credit planning rate in `config/sources.yaml` (`inr_per_credit`, replace with the organisers' figure).
