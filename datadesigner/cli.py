"""CLI: datadesigner ask "<query>" · run --pack fixture · resume <run_id> · memo <run_id> · approvals · approve <id> · send"""
from __future__ import annotations

import argparse
import json
import sys

from .core.context import get_stores


def main(argv: list[str] | None = None) -> int:
    from .orchestrator import runner
    ap = argparse.ArgumentParser(prog="datadesigner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask"); a.add_argument("text"); a.add_argument("--no-llm", action="store_true")
    r = sub.add_parser("run"); r.add_argument("--pack", required=True); r.add_argument("--family")
    s = sub.add_parser("resume"); s.add_argument("run_id")
    m = sub.add_parser("memo"); m.add_argument("run_id")
    sub.add_parser("approvals")
    ap_ = sub.add_parser("approve"); ap_.add_argument("action_id"); ap_.add_argument("--by", default="cli-user")
    sub.add_parser("send")
    x = ap.parse_args(argv)
    st = get_stores()
    if x.cmd == "ask":
        rid = runner.create({"text": x.text, "use_llm": not x.no_llm})
        res = runner.execute(rid)
        print(res["memo"]["md"])
        print(f"\nrun {rid}", file=sys.stderr)
    elif x.cmd == "run":
        pack = json.load(open(x.pack))
        rid = runner.create({"pack": pack, "family": x.family, "text": pack.get("company", {}).get("name")})
        print(runner.execute(rid)["memo"]["md"])
    elif x.cmd == "resume":
        from .mail.executor import Executor
        from .mail.providers import make_provider
        from .core.config_loader import get_config
        from .core.settings import get_settings
        Executor(st, make_provider(get_settings(), get_config()["mail"]), get_settings(), get_config()["mail"]).reconcile_all()
        print(runner.execute(x.run_id)["memo"]["id"])
    elif x.cmd == "memo":
        print((st.checkpoint(x.run_id, "RESULT") or {}).get("memo", {}).get("md", "no memo yet"))
    elif x.cmd == "approvals":
        for row in st.rows("SELECT action_id, run_id, status, draft_json FROM approvals ORDER BY at"):
            d = json.loads(row["draft_json"])
            print(row["action_id"], row["status"], d["template"], d["to"], d["subject"])
    elif x.cmd in ("approve", "send"):
        from .core.config_loader import get_config
        from .core.settings import get_settings
        from .mail.executor import Executor
        from .mail.providers import make_provider
        ex = Executor(st, make_provider(get_settings(), get_config()["mail"]), get_settings(), get_config()["mail"])
        if x.cmd == "approve":
            ex.approve(x.action_id, x.by)
        print(ex.run_approved())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
