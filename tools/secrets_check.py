#!/usr/bin/env python3
"""Block commits that contain API keys or passwords (Crustdata, Claude, Gmail app password, Google). Usage:
  python tools/secrets_check.py            # scan staged files (pre-commit)
  python tools/secrets_check.py --all      # scan the whole working tree (make secrets-check)
"""
import re, subprocess, sys, pathlib

PATTERNS = {
    "crustdata_key": re.compile(r"cd_[0-9a-f]{20,}"),
    "anthropic_key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "gmail_app_password": re.compile(r"(?i)(GMAIL_APP_PASSWORD|app[_ ]password)\s*[:=]\s*['\"]?[a-z]{4}\s?[a-z]{4}\s?[a-z]{4}\s?[a-z]{4}\b"),
    "google_aq_key": re.compile(r"AQ\.[A-Za-z0-9_\-]{20,}"),
    "google_aiza_key": re.compile(r"AIza[0-9A-Za-z_\-]{30,}"),
    "bearer_header": re.compile(r"(?i)authorization:\s*bearer\s+[A-Za-z0-9_\-\.]{20,}"),
}
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
ALLOW_FILES = {".env"}  # local only, gitignored — never staged

def files(all_tree: bool):
    if all_tree:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], capture_output=True, text=True).stdout
    else:
        out = subprocess.run(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"], capture_output=True, text=True).stdout
    for name in out.splitlines():
        p = pathlib.Path(name)
        if p.name in ALLOW_FILES or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.is_file():
            yield p

def main() -> int:
    bad = []
    for p in files("--all" in sys.argv):
        try:
            text = p.read_text(errors="ignore")
        except Exception:
            continue
        for label, rx in PATTERNS.items():
            for m in rx.finditer(text):
                bad.append(f"{p}: {label}: {m.group(0)[:6]}…")
    tracked_env = subprocess.run(["git", "ls-files", ".env"], capture_output=True, text=True).stdout.strip()
    if tracked_env:
        bad.append(".env is tracked by git — run: git rm --cached .env")
    if bad:
        print("SECRET CHECK FAILED:\n  " + "\n  ".join(bad))
        return 1
    print("secret check: clean")
    return 0

if __name__ == "__main__":
    sys.exit(main())
