"""Stop button support: a person can stop any step that spends credits or model time.

Every job has an id (a run id for background runs, or an id the browser sends in
the `x-job-id` header for requests it waits on). `cancel(job_id)` sets a flag that
is checked:
  - before every Crustdata call (Crust._request), so no new credits are spent;
  - before and during every model call, which runs on a helper thread while the
    caller waits on the flag, so the step stops at once instead of waiting
    for a slow response. A call already sent can't be recalled: the provider
    may still bill it, but its answer is thrown away.

`Cancelled` derives from BaseException (like asyncio.CancelledError), so the
`except Exception` fallbacks around individual sources don't swallow it and a
stopped run really stops.
"""
from __future__ import annotations

import threading

_jobs: dict[str, threading.Event] = {}
_lock = threading.Lock()


class Cancelled(BaseException):
    """A person pressed Stop."""


def token(job_id: str | None) -> threading.Event | None:
    """The flag for a job (created on first use, so a Stop that arrives first still counts)."""
    if not job_id:
        return None
    with _lock:
        if len(_jobs) > 2000:  # forget the oldest browser job ids (runs remove their own)
            for k in list(_jobs)[:1000]:
                _jobs.pop(k, None)
        return _jobs.setdefault(job_id, threading.Event())


def cancel(job_id: str) -> None:
    ev = token(job_id)
    if ev:
        ev.set()


def done(job_id: str | None) -> None:
    if job_id:
        with _lock:
            _jobs.pop(job_id, None)


def check(ev: threading.Event | None) -> None:
    if ev is not None and ev.is_set():
        raise Cancelled()


def call(ev: threading.Event | None, fn, *args, **kwargs):
    """Run fn, but return control the moment ev is set (raising Cancelled).

    Without a flag this is a plain call. With one, fn runs on a daemon thread; if
    Stop is pressed first, that thread finishes on its own and its result is dropped.
    """
    if ev is None:
        return fn(*args, **kwargs)
    check(ev)
    box: dict = {}
    finished = threading.Event()

    def work():
        try:
            box["value"] = fn(*args, **kwargs)
        except BaseException as e:  # handed back to the caller below
            box["error"] = e
        finally:
            finished.set()

    threading.Thread(target=work, daemon=True).start()
    while not finished.wait(0.2):
        check(ev)
    if "error" in box:
        raise box["error"]
    return box["value"]
