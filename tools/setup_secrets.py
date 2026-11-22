#!/usr/bin/env python3
"""First-run secrets intake for Data Designer. Standard library only, so it runs before `make setup`.

  python3 tools/setup_secrets.py            # ask for every missing value (hidden input for secrets), write .env
  python3 tools/setup_secrets.py --check    # list missing variables by NAME only; exit 1 if any are missing
  python3 tools/setup_secrets.py --verify   # live checks: Claude /v1/models, Gmail SMTP login (+ optional test email)

Values are never printed. .env is written with mode 600 and must stay gitignored.
"""
from __future__ import annotations

import getpass, json, os, pathlib, re, smtplib, ssl, subprocess, sys, urllib.request
from email.message import EmailMessage
from email.utils import make_msgid

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
ASK = "__ASK_USER__"

FIELDS = [  # name, prompt, secret?, validator
    ("DD_ANTHROPIC_API_KEY", "Claude API key (sk-ant-…)", True, lambda v: v.startswith("sk-ant-") and len(v) > 30),
    ("GMAIL_ADDRESS", "Gmail address to send from", False, lambda v: re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v) is not None),
    ("GMAIL_APP_PASSWORD", "Gmail app password (16 letters; spaces are ignored)", True, lambda v: len(v.replace(" ", "")) == 16),
    ("TEST_INBOX", "Inbox for test emails (e.g. you+dd-test@gmail.com)", False, lambda v: "@" in v),
    ("CRUSTDATA_API_KEY", "Crustdata API key (cd_…)", True, lambda v: v.startswith("cd_")),
]


def read_env() -> dict[str, str]:
    src = ENV if ENV.exists() else EXAMPLE
    out: dict[str, str] = {}
    for line in src.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def missing(env: dict[str, str]) -> list[str]:
    return [k for k, *_ in FIELDS if not env.get(k) or env[k] in (ASK, "cd_xxx")]


def write_env(updates: dict[str, str]) -> None:
    src = ENV if ENV.exists() else EXAMPLE
    lines, seen = [], set()
    for line in src.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k = line.split("=", 1)[0].strip()
            if k in updates:
                line, _ = f"{k}={updates[k]}", seen.add(k)
        lines.append(line)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in seen]
    ENV.write_text("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


def ignored() -> str:
    r = subprocess.run(["git", "check-ignore", "-q", str(ENV)], cwd=ROOT, stderr=subprocess.DEVNULL)
    return {0: "yes", 1: "NO — add .env to .gitignore before committing"}.get(r.returncode, "not a git repo yet (clone or git init first)")


def verify(env: dict[str, str], send_test: bool) -> int:
    ok = True
    key = env.get("DD_ANTHROPIC_API_KEY", "")
    if key and key != ASK:
        req = urllib.request.Request("https://api.anthropic.com/v1/models",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                ids = [m["id"] for m in json.load(r).get("data", [])]
            print(f"✓ Claude API: {len(ids)} models visible (e.g. {', '.join(ids[:3])})")
        except Exception as e:  # noqa: BLE001
            ok = False; print(f"✗ Claude API: {type(e).__name__} — check the key")
    addr, pw = env.get("GMAIL_ADDRESS", ""), env.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
    if addr and pw and ASK not in (addr, pw):
        try:
            with smtplib.SMTP(env.get("SMTP_HOST", "smtp.gmail.com"), int(env.get("SMTP_PORT", 587)), timeout=30) as s:
                s.starttls(context=ssl.create_default_context()); s.login(addr, pw)
                print("✓ Gmail SMTP: login accepted")
                if send_test and env.get("TEST_INBOX", ASK) != ASK:
                    m = EmailMessage(); m["From"] = addr; m["To"] = env["TEST_INBOX"]
                    m["Subject"] = "[TEST] Data Designer first-run check"; m["Message-ID"] = make_msgid(domain="datadesigner.local")
                    m.set_content("Data Designer can send mail. You can delete this message.")
                    s.send_message(m); print(f"✓ Gmail SMTP: test email sent to TEST_INBOX ({m['Message-ID']})")
        except smtplib.SMTPAuthenticationError:
            ok = False; print("✗ Gmail SMTP: authentication failed — 2-Step Verification on? app password correct?")
        except Exception as e:  # noqa: BLE001
            ok = False; print(f"✗ Gmail SMTP: {type(e).__name__}")
    return 0 if ok else 1


def main() -> int:
    env = read_env()
    if "--check" in sys.argv:
        miss = missing(env)
        print("missing: " + (", ".join(miss) if miss else "none"))
        print(".env gitignored: " + ignored())
        return 1 if miss else 0
    if "--verify" in sys.argv:
        return verify(env, send_test="--send-test" in sys.argv)
    print("Data Designer first-run setup. Secrets are hidden as you type and written only to .env (mode 600).\n")
    updates: dict[str, str] = {}
    for name, prompt, secret, valid in FIELDS:
        if name not in missing(env):
            continue
        while True:
            v = (getpass.getpass if secret else input)(f"{prompt}: ").strip()
            if name == "GMAIL_APP_PASSWORD":
                v = v.replace(" ", "")
            if valid(v):
                updates[name] = v; break
            print("  that doesn't look right — try again (Ctrl+C to stop)")
    if updates:
        write_env(updates); print(f"\nwrote {len(updates)} value(s) to .env")
    print(".env gitignored: " + ignored())
    return verify(read_env(), send_test=True)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ncancelled; nothing else written"); sys.exit(130)
