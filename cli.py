#!/usr/bin/env python3
"""Competitor Move Desk — command line.

    # offline: no keys, no credits, no network. Four verdicts, reproducible.
    python3 cli.py demo

    # live
    export CRUSTDATA_API_KEY=... ANTHROPIC_API_KEY=...
    python3 cli.py ask --requester ops@client.in \\
        --question "Did Delhivery start hiring in Guwahati since September 2026?"

    # resume a case that was killed mid-run (same arguments, same case id)
    python3 cli.py ask --requester ops@client.in --question "..."

    # inspect what happened
    python3 cli.py show <case_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from desk import load_config
from desk.crustdata import CrustdataClient
from desk.desk import CompetitorMoveDesk
from desk.fixtures import DEMO_QUESTIONS, FakeCrustdataClient
from desk.journal import Journal
from desk.ledger import CostLedger
from desk.llm import AnthropicLLM, default_offline_llm
from desk.models import Case
from desk.rivals import RivalRegistry


def _build(requester: str, questions: list[str], *, offline: bool, approval: str):
    config = load_config()
    case_id = Case.new_id(requester, questions)
    journal = Journal(case_id, config.journal_dir)
    ledger = CostLedger(journal, inr_per_credit=config.pricing.inr_per_credit)

    if offline:
        client = FakeCrustdataClient(ledger)
        llm = default_offline_llm()
    else:
        client = CrustdataClient(
            os.environ.get("CRUSTDATA_API_KEY", ""),
            ledger,
            api_base=config.api_base,
            api_version=config.api_version,
            web_search_rpm=config.limits.web_search_rpm,
            max_retries=config.limits.max_retries_per_call,
        )
        llm = AnthropicLLM()

    desk = CompetitorMoveDesk(
        config=config,
        client=client,  # type: ignore[arg-type]
        llm=llm,
        ledger=ledger,
        journal=journal,
        registry=RivalRegistry.load(),
        approval_mode=approval,
    )
    return desk, journal, ledger, case_id


def cmd_ask(args: argparse.Namespace) -> int:
    desk, journal, ledger, case_id = _build(
        args.requester, args.question, offline=args.offline, approval=args.approval
    )
    print(f"case {case_id}  ({'offline' if args.offline else 'live'})\n")

    result = desk.run(args.requester, args.question)

    if result.halted:
        print("HALTED —", result.halt_reason)
        print(f"journal: {journal.path}")
        return 2

    print(result.memo)
    print(f"\njournal: {journal.path}")
    print(f"ledger:  {json.dumps(ledger.summary())}")
    if result.decision and not result.decision.approved:
        print("\nNot sent. " + (result.decision.note or ""))
    elif result.sent:
        print(f"\nSent. Memo written to {journal.dir}/{case_id}.memo.md")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    args.requester = "ops@client.example"
    args.question = DEMO_QUESTIONS
    args.offline = True
    args.approval = args.approval or "auto"
    return cmd_ask(args)


def cmd_show(args: argparse.Namespace) -> int:
    config = load_config()
    journal = Journal(args.case_id, config.journal_dir)
    if not os.path.exists(journal.path):
        print(f"no case {args.case_id} in {config.journal_dir}")
        return 1

    state = journal.replay()
    print(f"case {args.case_id}")
    print(f"  finished steps:        {len(state.finished)}")
    print(f"  in flight, read-only:  {len(state.in_flight_readonly)}")
    print(f"  in flight, IRREVERSIBLE: {len(state.in_flight_irreversible)}")
    print(f"  answers recorded:      {len(state.answers)}")
    print(f"  api calls:             {len(state.api_calls)}")
    print(f"  closed:                {state.closed}")
    if state.needs_adjudication:
        print("\n  NEEDS A PERSON: an irreversible step was begun and never")
        print("  confirmed. Decide whether it took effect before continuing.")
    for a in state.answers:
        print(f"\n  [{a.get('verdict')}] {a.get('question')}")
        for e in a.get("evidence", [])[:2]:
            print(f"      {e.get('record_date') or 'undated'}  {e.get('source_url')}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    from scripts.doctor import main as doctor_main  # noqa: PLC0415

    sys.argv = ["doctor"] + (["--probe-live"] if args.probe_live else [])
    return doctor_main()


def main() -> int:
    p = argparse.ArgumentParser(prog="cli.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    ask = sub.add_parser("ask", help="run a case")
    ask.add_argument("--requester", required=True)
    ask.add_argument("--question", action="append", required=True)
    ask.add_argument("--offline", action="store_true", help="no network, no credits")
    ask.add_argument(
        "--approval",
        default="interactive",
        choices=["interactive", "file", "auto"],
        help="auto skips human review: tests and rehearsals only",
    )
    ask.set_defaults(func=cmd_ask)

    demo = sub.add_parser("demo", help="offline run showing all four verdicts")
    demo.add_argument("--approval", default="auto",
                      choices=["interactive", "file", "auto"])
    demo.set_defaults(func=cmd_demo)

    show = sub.add_parser("show", help="inspect a case journal")
    show.add_argument("case_id")
    show.set_defaults(func=cmd_show)

    doc = sub.add_parser(
        "doctor", help="preflight: which keys and endpoints actually work"
    )
    doc.add_argument("--probe-live", action="store_true")
    doc.set_defaults(func=cmd_doctor)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
