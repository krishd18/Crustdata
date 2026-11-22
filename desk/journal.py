"""Append-only case journal: the thing that survives the kill on stage.

A judge stops the process at a random moment and the team restarts it. The
requirement is that each action happens once -- not that the run completes.

The rule that makes that true: **the intent is written before the act, the
outcome after it.** On restart we replay the journal and find three kinds of
step.

    finished     we have the result; skip the work, reuse the value
    in flight, read-only     safe to redo; a search costs credits, not harm
    in flight, irreversible  we do NOT know whether it happened

That third case is the honest one, and most implementations get it wrong by
retrying. If we wrote "about to send the memo" and died, the memo may or may
not have gone out. Re-sending risks a duplicate; skipping risks silence. So
the case halts and a person adjudicates. Saying this out loud is a better
answer to the system-design question than pretending a retry is safe.

Durability: every record is flushed and fsynced before the call returns, so a
``kill -9`` immediately after cannot lose the record that was just written.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterator

from .models import utcnow_iso


class RecordKind(str, Enum):
    CASE_OPENED = "case_opened"
    STEP_STARTED = "step_started"
    STEP_FINISHED = "step_finished"
    STEP_FAILED = "step_failed"
    API_CALL = "api_call"
    ANSWER_RECORDED = "answer_recorded"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    CASE_CLOSED = "case_closed"
    HALTED_FOR_ADJUDICATION = "halted_for_adjudication"


def step_id(case_id: str, step_name: str, params: Any = None) -> str:
    """Deterministic identity for a unit of work.

    The same step with the same inputs gets the same id across restarts, which
    is what lets a replay recognise work it has already done.
    """
    payload = json.dumps(
        {"case": case_id, "step": step_name, "params": params},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:20]


@dataclass
class ReplayState:
    finished: dict[str, Any]              # step_id -> result
    in_flight_readonly: set[str]
    in_flight_irreversible: dict[str, Any]  # step_id -> the intent we recorded
    answers: list[dict[str, Any]]
    api_calls: list[dict[str, Any]]
    closed: bool

    @property
    def needs_adjudication(self) -> bool:
        return bool(self.in_flight_irreversible)


class Journal:
    """One append-only JSONL file per case."""

    def __init__(self, case_id: str, journal_dir: str = "./cases") -> None:
        self.case_id = case_id
        self.dir = journal_dir
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, f"{case_id}.jsonl")
        self._lock = threading.Lock()
        self._seq = self._last_seq()

    # ---------------------------------------------------------------- write

    def _last_seq(self) -> int:
        if not os.path.exists(self.path):
            return 0
        last = 0
        for rec in self.read():
            last = max(last, rec.get("seq", 0))
        return last

    def append(self, kind: RecordKind, **payload: Any) -> dict[str, Any]:
        """Write one record and make it durable before returning."""
        with self._lock:
            self._seq += 1
            record = {
                "seq": self._seq,
                "ts": utcnow_iso(),
                "kind": kind.value,
                "case_id": self.case_id,
                **payload,
            }
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, default=str) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
            return record

    def start_step(
        self, name: str, params: Any = None, *, irreversible: bool = False
    ) -> str:
        """Record the intent to act, before acting. Returns the step id."""
        sid = step_id(self.case_id, name, params)
        self.append(
            RecordKind.STEP_STARTED,
            step_id=sid,
            step=name,
            params=params,
            irreversible=irreversible,
        )
        return sid

    def finish_step(self, sid: str, result: Any = None) -> None:
        self.append(RecordKind.STEP_FINISHED, step_id=sid, result=result)

    def fail_step(self, sid: str, error: str) -> None:
        self.append(RecordKind.STEP_FAILED, step_id=sid, error=error)

    def halt(self, reason: str, detail: Any = None) -> None:
        self.append(
            RecordKind.HALTED_FOR_ADJUDICATION, reason=reason, detail=detail
        )

    # ----------------------------------------------------------------- read

    def read(self) -> Iterator[dict[str, Any]]:
        if not os.path.exists(self.path):
            return iter(())

        def _gen() -> Iterator[dict[str, Any]]:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        # A kill during the write can leave a torn final line.
                        # Everything before it is intact, which is the whole
                        # point of append-only.
                        continue

        return _gen()

    def replay(self) -> ReplayState:
        """Rebuild what is known, so a restart resumes instead of repeating."""
        started: dict[str, dict[str, Any]] = {}
        finished: dict[str, Any] = {}
        failed: set[str] = set()
        answers: list[dict[str, Any]] = []
        api_calls: list[dict[str, Any]] = []
        closed = False

        for rec in self.read():
            kind = rec.get("kind")
            if kind == RecordKind.STEP_STARTED.value:
                started[rec["step_id"]] = rec
            elif kind == RecordKind.STEP_FINISHED.value:
                finished[rec["step_id"]] = rec.get("result")
            elif kind == RecordKind.STEP_FAILED.value:
                failed.add(rec["step_id"])
            elif kind == RecordKind.ANSWER_RECORDED.value:
                answers.append(rec.get("answer", {}))
            elif kind == RecordKind.API_CALL.value:
                api_calls.append(rec)
            elif kind == RecordKind.CASE_CLOSED.value:
                closed = True

        in_flight_readonly: set[str] = set()
        in_flight_irreversible: dict[str, Any] = {}
        for sid, rec in started.items():
            if sid in finished or sid in failed:
                continue
            if rec.get("irreversible"):
                in_flight_irreversible[sid] = rec
            else:
                in_flight_readonly.add(sid)

        return ReplayState(
            finished=finished,
            in_flight_readonly=in_flight_readonly,
            in_flight_irreversible=in_flight_irreversible,
            answers=answers,
            api_calls=api_calls,
            closed=closed,
        )


def once(journal: Journal, name: str, params: Any, fn, *, irreversible: bool = False):
    """Run ``fn`` at most once per (case, step, params), across restarts.

    Read-only steps replay freely. An irreversible step that was begun but
    never confirmed stops the case rather than guessing, because we cannot
    tell from here whether the world already changed.
    """
    sid = step_id(journal.case_id, name, params)
    state = journal.replay()

    if sid in state.finished:
        return state.finished[sid]

    if sid in state.in_flight_irreversible:
        journal.halt(
            "irreversible step was begun but never confirmed",
            {"step_id": sid, "step": name},
        )
        raise RuntimeError(
            f"step {name} ({sid}) may already have taken effect; "
            "a person must confirm before this case continues"
        )

    journal.start_step(name, params, irreversible=irreversible)
    try:
        result = fn()
    except Exception as exc:  # noqa: BLE001 - recorded, then re-raised
        journal.fail_step(sid, f"{type(exc).__name__}: {exc}")
        raise
    journal.finish_step(sid, result)
    return result
