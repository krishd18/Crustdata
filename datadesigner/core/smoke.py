"""make smoke: live checks for Crustdata, Claude and Gmail → config/runtime.lock.json (non-secret facts only)."""
from __future__ import annotations

import json
import sys
import time
from email.message import EmailMessage
from email.utils import make_msgid

from pydantic import BaseModel

from .config_loader import get_config
from .context import make_context
from .settings import ROOT, get_settings
from .stores import Stores

LOCK = ROOT / "config" / "runtime.lock.json"


def load() -> dict:
    return json.loads(LOCK.read_text()) if LOCK.exists() else {}


def save(d: dict) -> None:
    LOCK.write_text(json.dumps(d, indent=1, sort_keys=True) + "\n")


class Probe(BaseModel):
    label: str
    default: str | None


def crustdata() -> bool:
    ctx = make_context(run_id="smoke", mode="live", stores=Stores(":memory:"))
    ep = ctx.crustdata.account_endpoints().body
    lock = load()
    lock["crustdata"] = {"api_version": ep.get("api_version"), "token_limit_rpm": ep.get("token_limit_rpm"),
                         "endpoints": {e["path"]: {"status": e["status"], "base_credits": e.get("base_credits"), "rpm": e.get("effective_rate_limit_rpm")}
                                       for e in ep.get("endpoints", []) if e["status"] == "enabled"}}
    lock["crustdata"]["industries_software"] = ctx.crustdata.company_autocomplete("taxonomy.professional_network_industry", "software", 20)
    save(lock)
    print(f"✓ Crustdata: {len(lock['crustdata']['endpoints'])} enabled endpoints · autocomplete ok")
    return True


def claude() -> bool:
    import anthropic
    s = get_settings()
    cli = anthropic.Anthropic(api_key=s.secret("dd_anthropic_api_key"))
    avail = [m.id for m in cli.models.list(limit=100).data]
    ctx = make_context(run_id="smoke", mode="live", stores=Stores(":memory:"))
    roles = {}
    for role in get_config()["llm"]["roles"]:
        models = [m for m in ctx.claude.models_for(role) if m in avail]
        out, u = ctx.claude.generate_json(role, "Return label 'ok' and default null.", f"smoke {role} {time.time():.0f}", Probe, task="smoke")
        roles[role] = {"model": u.get("model"), "accepted": ["output_config.format", "effort" if get_config()["llm"]["roles"][role].get("effort") else None]}
    lock = load()
    lock["claude"] = {"available": avail, "roles": roles}
    save(lock)
    print(f"✓ Claude: {len(avail)} models · roles → " + ", ".join(f"{k}={v['model']}" for k, v in roles.items()))
    return True


def mail() -> bool:
    from ..mail.providers import GmailSMTP
    s, cfg = get_settings(), get_config()["mail"]
    g = GmailSMTP(s, cfg)
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = s.secret("gmail_address"), s.secret("test_inbox"), "[TEST] Data Designer smoke check"
    m["Message-ID"] = make_msgid(domain="datadesigner.local")
    m["X-DD-Action-Id"] = "smoke"
    m.set_content("Data Designer can send mail. You can delete this message.")
    mid = g.send(m)
    print("✓ Gmail SMTP: login + send ok")
    for _ in range(12):
        if g.find_sent(mid, "smoke"):
            print("✓ Gmail IMAP: found in [Gmail]/Sent Mail")
            return True
        time.sleep(5)
    print("✗ Gmail IMAP: not found within 60 s")
    return False


if __name__ == "__main__":
    which = sys.argv[1:] or ["--crustdata", "--claude", "--mail"]
    ok = True
    for w, fn in (("--crustdata", crustdata), ("--claude", claude), ("--mail", mail)):
        if w in which:
            try:
                ok = fn() and ok
            except Exception as e:  # noqa: BLE001
                print(f"✗ {w[2:]}: {type(e).__name__}: {str(e)[:160]}")
                ok = False
    sys.exit(0 if ok else 1)
