"""The gate before anything leaves the building.

On this track the irreversible action is not a payment. It is publishing a
claim about a real, named company. A wrong "rival X has exited this city"
reaches people who never see the correction, and can cost a named business a
contract it was going to win.

So the gate covers refusals too. A ``cannot_verify`` memo is still an outbound
statement about a named company, and "we could not confirm your competitor is
solvent" does damage whether or not it is hedged.

Three modes, and the dangerous one says so. ``auto`` exists for tests and
rehearsals; it records in the journal that no human saw the memo, so a case
file can never imply an approval that did not happen.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Literal

from .journal import Journal, RecordKind
from .models import utcnow_iso

Mode = Literal["interactive", "file", "auto"]


@dataclass
class Decision:
    approved: bool
    by: str
    at: str
    mode: str
    note: str | None = None

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "by": self.by,
            "at": self.at,
            "mode": self.mode,
            "note": self.note,
        }


class ApprovalGate:
    def __init__(
        self,
        journal: Journal,
        *,
        mode: Mode = "interactive",
        timeout_seconds: int = 600,
        watch_path: str | None = None,
    ) -> None:
        self.journal = journal
        self.mode = mode
        self.timeout_seconds = timeout_seconds
        self.watch_path = watch_path or os.path.join(
            journal.dir, f"{journal.case_id}.approval.json"
        )

    def request(self, memo: str, *, summary: str) -> Decision:
        self.journal.append(
            RecordKind.APPROVAL_REQUESTED,
            summary=summary,
            mode=self.mode,
            memo_chars=len(memo),
        )

        if self.mode == "auto":
            decision = Decision(
                approved=True,
                by="auto",
                at=utcnow_iso(),
                mode="auto",
                note=(
                    "AUTO-APPROVED. No person reviewed this memo. Valid for "
                    "tests and rehearsals only."
                ),
            )
        elif self.mode == "file":
            decision = self._await_file()
        else:
            decision = self._ask_stdin(memo, summary)

        self.journal.append(RecordKind.APPROVAL_DECIDED, decision=decision.to_dict())
        return decision

    # ------------------------------------------------------------------

    def _ask_stdin(self, memo: str, summary: str) -> Decision:
        print("\n" + "=" * 70)
        print("APPROVAL NEEDED — this memo makes claims about named companies")
        print("=" * 70)
        print(memo)
        print("=" * 70)
        print(summary)
        try:
            reply = input("Send this memo? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            reply = ""
        approved = reply in ("y", "yes")
        return Decision(
            approved=approved,
            by=os.environ.get("USER", "operator"),
            at=utcnow_iso(),
            mode="interactive",
            note=None if approved else "declined at the prompt",
        )

    def _await_file(self) -> Decision:
        """Wait for a reviewer to drop a decision file.

        Used when the service runs unattended: the case pauses here rather
        than sending, and the journal shows exactly how long it waited.
        """
        deadline = time.monotonic() + self.timeout_seconds
        while time.monotonic() < deadline:
            if os.path.exists(self.watch_path):
                with open(self.watch_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                return Decision(
                    approved=bool(data.get("approved")),
                    by=str(data.get("by", "reviewer")),
                    at=utcnow_iso(),
                    mode="file",
                    note=data.get("note"),
                )
            time.sleep(1)
        return Decision(
            approved=False,
            by="nobody",
            at=utcnow_iso(),
            mode="file",
            note=(
                f"no decision within {self.timeout_seconds}s. Not sending. "
                "An unanswered approval is a refusal, never a default yes."
            ),
        )
