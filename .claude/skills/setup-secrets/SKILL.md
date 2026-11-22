---
name: setup-secrets
description: First-run intake of the Claude API key and Gmail credentials into the gitignored .env, then live verification. Use at the start of any session where tools/setup_secrets.py --check reports missing values, or when a Claude or Gmail call fails with an auth error.
disable-model-invocation: false
allowed-tools: Bash(python3 tools/setup_secrets.py:*), Bash(git check-ignore:*), Bash(make secrets-check), Read, Edit
---
1. Run `python3 tools/setup_secrets.py --check`. It prints only variable NAMES. If it says `missing: none`, skip to step 4.
2. Ask the user ONE message listing every missing item:
   - `DD_ANTHROPIC_API_KEY` — Claude API key (`sk-ant-…`, from console.anthropic.com → API keys)
   - `GMAIL_ADDRESS` — the Gmail account Data Designer sends from
   - `GMAIL_APP_PASSWORD` — 16-letter app password (Google Account → Security → 2-Step Verification → App passwords)
   - `TEST_INBOX` — inbox for test emails (e.g. `you+dd-test@gmail.com`)
   Tell them the safest path is to run `make setup-secrets` in their own terminal (hidden input), or to paste the values here.
3. If they paste values: write each into `.env` by replacing its `__ASK_USER__` line with the **Edit tool**. Strip spaces from the app password. Never put a value in a shell command, a commit, a log or your reply. Never echo the values back; say only which variables were set.
4. Run `python3 tools/setup_secrets.py --verify --send-test` and report ✓/✗ per check (no values). On a Gmail auth failure, explain 2-Step Verification + app password and ask again.
5. Run `git check-ignore .env` (must print `.env`) and `make secrets-check` (must be clean).
6. Remind the user once to rotate the keys and revoke the app password after the event.
