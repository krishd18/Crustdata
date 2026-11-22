---
name: demo
description: Rehearse the finals demo — 3-minute run with a kill, then a 5-minute live fix.
disable-model-invocation: true
---
1. Start the app (`make run`) and Mailpit. Walk the demo script in docs/WORKFLOW.md §7 on replay data for speed, then one live sample query.
2. Approve two emails with `MAIL_MODE=test`; run `make kill-demo`; show the journal, the Mailpit (or Gmail test inbox) count and the IMAP reconcile lines.
3. Pick a random live-fix request from docs/WORKFLOW.md §5, time it, and confirm tests stay green.
Report timings and any step that exceeded its budget.
