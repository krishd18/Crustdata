"""Prove exactly-once against a real SIGKILL, not a simulated one.

Usage:
    python3 scripts/kill_demo.py <case_id>

Run it, kill -9 it partway, run it again with the same case id. Steps that
finished before the kill do not run a second time. Run it a third time to see
that a completed case does no work at all.
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desk.journal import Journal, RecordKind, once  # noqa: E402
from desk.ledger import CostLedger  # noqa: E402

STEPS = [
    ("resolve_entity", {"name": "Mahindra Logistics"}, 1.0, 0),
    ("search_jobs", {"city": "Guwahati", "since": "2026-09-01"}, 2.0, 2),
    ("fetch_pages", {"n": 3}, 2.0, 3),
    ("compose_verdict", {"question": 1}, 1.0, 0),
]


def main() -> None:
    case_id = sys.argv[1] if len(sys.argv) > 1 else "killdemo"
    journal = Journal(case_id, os.environ.get("DESK_JOURNAL_DIR", "./cases"))
    ledger = CostLedger(journal, inr_per_credit=float(
        os.environ.get("DESK_INR_PER_CREDIT", "0.5")
    ))

    state = journal.replay()
    already = len(state.finished)
    print(f"case {case_id}: {already} step(s) already done, "
          f"{ledger.total_credits:g} credits already spent")

    if state.needs_adjudication:
        print("HALTED: an irreversible step was begun and never confirmed.")
        print("        a person must decide before this case continues.")
        for sid, rec in state.in_flight_irreversible.items():
            print(f"        {rec['step']}  {sid}")
        sys.exit(2)

    for name, params, seconds, credits in STEPS:
        def work(name=name, seconds=seconds, credits=credits):
            print(f"  running {name} ... (kill me now to test)", flush=True)
            time.sleep(seconds)
            if credits:
                ledger.record(f"/fake/{name}", None, latency_ms=seconds * 1000,
                              credits=credits)
            return {"step": name, "ok": True}

        before = len(journal.replay().finished)
        once(journal, name, params, work)
        after = len(journal.replay().finished)
        if after == before:
            print(f"  skipped {name} (already done)")

    journal.append(RecordKind.CASE_CLOSED, note="all steps complete")
    print(f"case {case_id} complete: {ledger.total_credits:g} credits, "
          f"INR {ledger.total_inr:.2f}")
    print("ledger by endpoint:", ledger.by_endpoint())


if __name__ == "__main__":
    main()
