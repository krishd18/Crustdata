"""Kill test for the exactly-once send.

For each crash point, a child process approves and sends a draft and is killed
(os._exit, like kill -9) at that point. A second process then starts the way
the server does (outbox.recover()). We then count real deliveries for that
idempotency key. It must be exactly 1 every time.

    python scripts/kill_test.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

CHILD = r"""
import sys
from app import store, outbox
store.init()
row = outbox.draft("d_kill", "r_{tag}", "deals@counterparty.example", "Docs request", "1. EPFO ECR ({tag})")
print(row["idem_key"], flush=True)
outbox.approve_and_send(row["idem_key"], "analyst@buyer.example")
"""

RECOVER = r"""
from app import store, outbox
store.init()
print(len(outbox.recover()))
"""


def run(code: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([PY, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)


def main() -> int:
    data = tempfile.mkdtemp(prefix="secondlook-kill-")
    base = {**os.environ, "SECONDLOOK_DATA": data, "PYTHONPATH": str(ROOT), "MAIL_TRANSPORT": "file"}
    ok = True
    for point in ["after_journal", "after_transport", None]:
        tag = uuid.uuid4().hex[:6]
        env = {**base, "SECONDLOOK_CRASH_AT": point or ""}
        child = run(CHILD.replace("{tag}", tag), env)
        key = child.stdout.split()[0]
        killed = child.returncode == 137
        rec = run(RECOVER, {**base, "SECONDLOOK_CRASH_AT": ""})
        # a second restart must also be a no-op
        rec2 = run(RECOVER, {**base, "SECONDLOOK_CRASH_AT": ""})
        log = Path(data, "mailbox", "deliveries.log")
        n = sum(1 for ln in log.read_text().splitlines() if f" {key} " in ln) if log.exists() else 0
        status = "PASS" if n == 1 else "FAIL"
        ok &= n == 1
        print(f"{status}  crash={point or 'none':16} killed={killed!s:5} recovered={rec.stdout.strip() or rec.stderr.strip()[-80:]:>2}"
              f" second_restart={rec2.stdout.strip()}  deliveries={n}")
    print("data dir:", data)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
