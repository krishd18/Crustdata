# Data Designer — Makefile (targets are implemented during the phases in IMPLEMENTATION_PLAN.md)
SHELL := /bin/bash
PY ?= .venv/bin/python
export DD_HTTP_MODE ?= replay

.PHONY: setup setup-secrets smoke smoke-crustdata smoke-claude smoke-mail test record backtest e2e e2e-live chaos kill-demo run ui-proto lint secrets-check golden

setup:            ## venv + deps + playwright browser + pre-commit secret hook
	uv venv && uv pip install -e ".[dev]" || ($(PY) -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]")
	-$(PY) -m playwright install chromium
	printf '#!/bin/sh\npython3 tools/secrets_check.py\n' > .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
	@git check-ignore -q .env && echo ".env is ignored ✔" || (echo "ERROR: .env not ignored" && exit 1)

setup-secrets:    ## first run: hidden input for the Claude key + Gmail credentials → .env (mode 600), then live checks
	python3 tools/setup_secrets.py

smoke: smoke-crustdata smoke-claude smoke-mail   ## all live checks → config/runtime.lock.json

smoke-crustdata:  ## /account/endpoints, autocomplete, job categories (~0 credits)
	DD_HTTP_MODE=live $(PY) -m datadesigner.core.smoke --crustdata

smoke-claude:     ## /v1/models + one structured-output call per role
	DD_HTTP_MODE=live $(PY) -m datadesigner.core.smoke --claude

smoke-mail:       ## Gmail SMTP login + one [TEST] email to TEST_INBOX + IMAP Sent-folder reconcile
	DD_HTTP_MODE=live $(PY) -m datadesigner.core.smoke --mail

test:             ## unit + contract (replay)
	$(PY) -m pytest tests/unit tests/contract -q

record:           ## live run of one case → cassettes (budget-capped). usage: make record CASE=S1
	DD_HTTP_MODE=record $(PY) -m datadesigner.orchestrator.runner --case $(CASE) --record && $(PY) tools/scrub_cassettes.py

backtest:         ## V1–V8 → reports/backtest/summary.md. usage: make backtest [AGENT=A7]
	$(PY) -m verification.runner $(if $(AGENT),--agent $(AGENT),--all)

golden:           ## re-score golden decisions with the reference scorer
	$(PY) tools/rubric_check.py && $(PY) -m verification.v7_rubric

e2e:              ## all cases in replay ×3 + determinism diff
	$(PY) -m pytest tests/e2e -q

e2e-live:         ## organiser sample inputs live ×2 → reports/e2e/live_drift.md
	DD_HTTP_MODE=live $(PY) -m verification.runner --e2e --cases S1,S2 --repeat 2 --live

chaos:            ## kill trials, always on Mailpit. usage: make chaos TRIALS=50
	MAIL_PROVIDER=mailpit $(PY) tools/kill_demo.py --trials $(or $(TRIALS),50)

mailpit:          ## local Mailpit stand-in (SMTP :1025, API :8025) when Docker is unavailable
	$(PY) -m datadesigner.mail.local_mailpit

kill-demo:        ## exactly-once demo on Mailpit (start it with make mailpit)
	$(PY) tools/kill_demo.py --trials $(or $(TRIALS),5)

run:              ## API + UI
	$(PY) -m uvicorn datadesigner.api.app:app --port 8000

ui-proto:         ## open the approved UI prototype at http://localhost:8090
	python3 -m http.server 8090 -d ui/prototype

lint:
	ruff check . && ruff format --check . && true

secrets-check:
	$(PY) tools/secrets_check.py --all
