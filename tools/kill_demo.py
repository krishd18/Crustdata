#!/usr/bin/env python3
"""Exactly-once kill trials (V5 / make kill-demo). Each trial: draft 2 emails → approve → a child process executes
and is SIGKILLed (os._exit) at a random point (after intent / before send / after send / never) → restart reconciles →
assert each action reached Mailpit exactly once and is 'reconciled' in the journal. Always Mailpit, never Gmail.
Usage: python tools/kill_demo.py [--trials 50]"""
import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time

CHILD = r'''
import os, sys, random
from datadesigner.core.stores import Stores
from datadesigner.core.config_loader import get_config
from datadesigner.core.settings import get_settings
from datadesigner.mail.executor import Executor
from datadesigner.mail.providers import Mailpit
db, kill_at, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
st = Stores(db); s = get_settings(); cfg = get_config()["mail"]
def hook(step, aid):
    if step == kill_at: os._exit(137)
ex = Executor(st, Mailpit(s, cfg), s, cfg, sleep=lambda x: None, on_step=hook)
ex.timeout = 2
print(ex.run_approved())
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=50)
    a = ap.parse_args()
    import httpx
    from datadesigner.core.stores import Stores
    from datadesigner.mail import drafter
    env = {**os.environ, "MAIL_PROVIDER": "mailpit", "MAIL_MODE": "test"}
    ok = 0
    points = ["after_intent", "before_send", "after_send", "none"]
    for t in range(a.trials):
        db = tempfile.mktemp(suffix=".sqlite")
        st = Stores(db)
        ids = [drafter.queue(st, f"KILL-{t}-{time.time_ns()}", "doc_request", f"ops{i}@example.com", f"Trial {t} mail {i}",
                             "Please share documents. Reply stop to opt out.", "ACME (sample)", []) for i in range(2)]
        for aid in ids:
            st.x("UPDATE approvals SET status='approved', decided_by='kill-demo' WHERE action_id=?", (aid,))
            st.journal(aid, "approved", {"by": "kill-demo"})
        kill_at = random.Random(t).choice(points)
        subprocess.run([sys.executable, "-c", CHILD, db, kill_at, str(t)], env=env, capture_output=True)
        subprocess.run([sys.executable, "-c", CHILD, db, "none", str(t)], env=env, capture_output=True)   # restart → reconcile
        counts = [httpx.get("http://127.0.0.1:8025/api/v1/search", params={"query": f"message-id:{aid}@datadesigner.local"}).json()["messages_count"] for aid in ids]
        states = [st.journal_states(aid) for aid in ids]
        good = counts == [1, 1] and all("reconciled" in s for s in states)
        ok += good
        print(json.dumps({"trial": t, "kill_at": kill_at, "mailpit_counts": counts, "reconciled": [("reconciled" in s) for s in states], "ok": good}))
    print(f"exactly-once: {ok}/{a.trials} trials")
    return 0 if ok == a.trials else 1


if __name__ == "__main__":
    sys.exit(main())
