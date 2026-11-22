"""The six-step workflow, shared by the web API, the JSON check endpoint and the CLI.

  1 FIND       find.shortlist()                     -> searches row, then add_from_search()
  2 SCREEN     start_run(mode="screen")             -> the target's public claims only
  3 REACH OUT  outbox.draft(kind="intro")           -> person approves -> sent once
  4 CHECK      set_deck() + start_run(mode="check") -> claims register
  5 REQUEST    outbox.draft(kind="request")         -> person approves -> sent once
  6 RE-CHECK   start_run(mode="check") again        -> diff against step 4
"""
from __future__ import annotations

import json
import threading
import uuid
from collections import Counter

from . import engine, store
from .crust import now_iso
from .ingest import Parsed

STEPS = [
    ("find", "Find"), ("screen", "Screen"), ("reach_out", "Reach out"),
    ("check", "Check"), ("request", "Request"), ("recheck", "Re-check"),
]


def clean_domain(d: str | None) -> str | None:
    d = (d or "").strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").split("/")[0]
    return d or None


def create_dossier(name: str, domain: str | None = None, city: str | None = None, teaser: str = "",
                   company_id: int | None = None, search_id: str | None = None, signals=None) -> str:
    did = f"d_{uuid.uuid4().hex[:10]}"
    store.x("INSERT INTO dossiers (id, name, domain, city, teaser, company_id, created_at, search_id, signals)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (did, name.strip(), clean_domain(domain), (city or "").strip() or None, teaser or "", company_id,
             now_iso(), search_id, json.dumps(signals) if signals else None))
    return did


def set_deck(did: str, parsed: Parsed):
    store.x("UPDATE dossiers SET teaser=?, deck_meta=? WHERE id=?",
            (parsed.text, json.dumps({**parsed.to_dict(), "received_at": now_iso()}), did))


def start_run(did: str, mode: str, token: str, background: bool = True, stop=None) -> str:
    seq = (store.q("SELECT COALESCE(MAX(seq),0) AS s FROM runs WHERE dossier_id=?", (did,), one=True) or {}).get("s", 0) + 1
    rid = f"r_{uuid.uuid4().hex[:10]}"
    store.x("INSERT INTO runs (id, dossier_id, seq, status, started_at, progress, mode) VALUES (?,?,?,?,?,?,?)",
            (rid, did, seq, "running", now_iso(), "[]", mode))
    if background:
        threading.Thread(target=engine.run, args=(rid, token), daemon=True).start()
    else:
        engine.run(rid, token, stop)
    return rid


def cancel_run(rid: str) -> bool:
    """A person pressed Stop: flag the worker and mark the run stopped right away."""
    from . import cancel
    cancel.cancel(rid)
    r = store.q("SELECT progress FROM runs WHERE id=? AND status='running'", (rid,), one=True)
    if not r:
        return False
    steps = json.loads(r["progress"] or "[]") + ["Stop requested: finishing the call in flight, nothing new is sent"]
    store.x("UPDATE runs SET status='cancelled', finished_at=?, progress=? WHERE id=? AND status='running'",
            (now_iso(), json.dumps(steps), rid))
    return True


def add_from_search(sid: str, company_ids: list[int]) -> list[str]:
    s = store.q("SELECT * FROM searches WHERE id=?", (sid,), one=True)
    if not s:
        raise KeyError(sid)
    rows = {r["crustdata_company_id"]: r for r in json.loads(s["result"])["rows"]}
    out = []
    for cid in company_ids:
        r = rows.get(cid)
        if not r:
            continue
        existing = store.q(f"SELECT id FROM dossiers WHERE company_id=? AND {LIVE}", (cid,), one=True)
        if existing:
            out.append(existing["id"])
            continue
        out.append(create_dossier(r["name"], r.get("domain"), None, "", cid, sid,
                                  {"signals": r.get("signals"), "hq": r.get("hq"), "thesis": json.loads(s["result"])["thesis"]}))
    return out


# ---------------------------------------------------------------------------
# Flush: clear the pipeline in one go. Targets are hidden, not deleted, so the
# last flush can be restored, and the send journal is never touched: a send that
# was already approved still completes exactly once.
# ---------------------------------------------------------------------------
LIVE = "flushed_at IS NULL AND deleted_at IS NULL"  # a target still in the pipeline


def delete_target(did: str) -> dict:
    """Take one target out of the pipeline: its runs stop, it is hidden, Undo restores it.
    Nothing is erased, and the send journal is untouched (an approved send still finishes)."""
    stopped = 0
    for r in store.q("SELECT id FROM runs WHERE dossier_id=? AND status='running'", (did,)):
        stopped += cancel_run(r["id"])
    store.x("UPDATE dossiers SET deleted_at=? WHERE id=?", (now_iso(), did))
    sending = (store.q("SELECT COUNT(*) AS n FROM outbox WHERE dossier_id=? AND status IN ('approved','uncertain')",
                       (did,), one=True) or {}).get("n", 0)
    return {"dossier_id": did, "deleted": True, "stopped_runs": stopped, "sends_still_completing": sending}


def undelete_target(did: str) -> dict:
    store.x("UPDATE dossiers SET deleted_at=NULL WHERE id=?", (did,))
    return {"dossier_id": did, "deleted": False}


def flush_preview() -> dict:
    live = f"SELECT id FROM dossiers WHERE {LIVE}"
    count = lambda sql, a=(): (store.q(sql, a, one=True) or {}).get("n", 0)  # noqa: E731
    last = store.q("SELECT MAX(flushed_at) AS t FROM dossiers", one=True)["t"]
    return {
        "targets": count(f"SELECT COUNT(*) AS n FROM dossiers WHERE {LIVE}"),
        "searches": count("SELECT COUNT(*) AS n FROM searches WHERE flushed_at IS NULL"),
        "running": count(f"SELECT COUNT(*) AS n FROM runs WHERE status='running' AND dossier_id IN ({live})"),
        "drafts": count(f"SELECT COUNT(*) AS n FROM outbox WHERE status='awaiting_approval' AND dossier_id IN ({live})"),
        "sending": count(f"SELECT COUNT(*) AS n FROM outbox WHERE status IN ('approved','uncertain') AND dossier_id IN ({live})"),
        "restorable": count("SELECT COUNT(*) AS n FROM dossiers WHERE flushed_at = ?", (last,)) if last else 0,
        "last_flush": last,
    }


def flush(searches: bool = False) -> dict:
    """Stop running runs, then hide every target (and optionally the search history)."""
    from datetime import datetime, timezone
    before = flush_preview()
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # distinct per flush, sorts by time
    for r in store.q("SELECT r.id FROM runs r JOIN dossiers d ON d.id=r.dossier_id"
                     f" WHERE r.status='running' AND d.{LIVE.replace(' AND ', ' AND d.')}"):
        cancel_run(r["id"])  # no more credits spent on targets being cleared
    store.x(f"UPDATE dossiers SET flushed_at=? WHERE {LIVE}", (at,))
    if searches:
        store.x("UPDATE searches SET flushed_at=? WHERE flushed_at IS NULL", (at,))
    return {"flushed_at": at, "targets": before["targets"], "searches": before["searches"] if searches else 0,
            "stopped_runs": before["running"], "drafts_hidden": before["drafts"], "sends_still_completing": before["sending"]}


def restore_last_flush() -> dict:
    last = store.q("SELECT MAX(flushed_at) AS t FROM dossiers", one=True)["t"]
    last_s = store.q("SELECT MAX(flushed_at) AS t FROM searches", one=True)["t"]
    if not last and not last_s:
        return {"targets": 0, "searches": 0}
    n = (store.q("SELECT COUNT(*) AS n FROM dossiers WHERE flushed_at=?", (last,), one=True) or {}).get("n", 0)
    store.x("UPDATE dossiers SET flushed_at=NULL WHERE flushed_at=?", (last,))
    ns = 0
    if last_s and last_s == last:  # searches cleared in the same flush come back too
        ns = (store.q("SELECT COUNT(*) AS n FROM searches WHERE flushed_at=?", (last,), one=True) or {}).get("n", 0)
        store.x("UPDATE searches SET flushed_at=NULL WHERE flushed_at=?", (last,))
    return {"targets": n, "searches": ns}


def stage(did: str) -> list[dict]:
    """Which of the six steps are done for this dossier, with a short detail each."""
    d = store.q("SELECT * FROM dossiers WHERE id=?", (did,), one=True)
    runs = store.q("SELECT id, seq, status, COALESCE(mode,'check') AS mode, finished_at FROM runs WHERE dossier_id=? ORDER BY seq", (did,))
    mail = store.q("SELECT COALESCE(kind,'request') AS kind, status, sent_at FROM outbox WHERE dossier_id=?", (did,))
    screens = [r for r in runs if r["mode"] == "screen" and r["status"] == "done"]
    checks = [r for r in runs if r["mode"] == "check" and r["status"] == "done"]
    sent = lambda k: [m for m in mail if m["kind"] == k and m["status"] == "sent"]  # noqa: E731
    done = {
        "find": True,
        "screen": bool(screens),
        "reach_out": bool(sent("intro")),
        "check": bool(checks),
        "request": bool(sent("request")),
        "recheck": len(checks) >= 2,
    }
    detail = {
        "find": "from a FIND search" if d.get("search_id") else "added directly",
        "screen": f"{len(screens)} screen{'s' if len(screens) != 1 else ''}" if screens else "",
        "reach_out": f"sent {sent('intro')[0]['sent_at'][:10]}" if sent("intro") else "",
        "check": "deck checked" if checks else ("deck received" if d.get("teaser") else ""),
        "request": f"sent {sent('request')[0]['sent_at'][:10]}" if sent("request") else "",
        "recheck": f"{len(checks) - 1} re-check{'s' if len(checks) > 2 else ''}" if len(checks) >= 2 else "",
    }
    return [{"key": k, "label": lbl, "done": done[k], "detail": detail[k]} for k, lbl in STEPS]


def current_step(steps: list[dict]) -> str:
    """The step after the furthest one reached (steps can be skipped, e.g. a deck that arrives unasked)."""
    last = max((i for i, s in enumerate(steps) if s["done"]), default=0)
    return steps[min(last + 1, len(steps) - 1)]["key"]


# ---------------------------------------------------------------------------
# Machine-readable register (what the JSON check endpoint and CLI return)
# ---------------------------------------------------------------------------
def register_json(run: dict, request_id: str | None = None, document: dict | None = None) -> dict:
    res = run.get("result") or {}
    if isinstance(res, str):
        res = json.loads(res)
    if run.get("status") != "done":
        return {"request_id": request_id, "status": run.get("status"), "error": run.get("error"),
                "candidates": res.get("candidates")}
    claims = []
    for f in res.get("findings", []):
        c = f["claim"]
        claims.append({
            "id": c.get("id"), "claim": c["text"], "type": c["type"], "source": c.get("source"),
            "verdict": f["verdict"], "final": f["final"], "reason": f["reason"],
            "evidence": [{"source": e["source"], "field": e.get("field"), "value": e["value"], "url": e.get("url"),
                          "retrieved_at": e["retrieved_at"]} for e in f.get("evidence", [])],
            "sources_checked": f.get("sources_checked", []),
            "ask_for": f.get("request") if not f["final"] else None,
        })
    return {
        "request_id": request_id,
        "status": "done",
        "company": res.get("company"),
        "snapshot_at": res.get("snapshot_at"),
        "document": document,
        "claims_from": res.get("register_source"),
        "summary": dict(Counter(c["verdict"] for c in claims)),
        "claims": claims,
        "ask_them_for": [{"document": r["document"], "claim": r["claim"], "type": r["type"]} for r in res.get("requests", [])],
        "inconsistencies": res.get("inconsistencies", []),
        "changes_since_last_check": res.get("changes", []),
        "cost": res.get("cost"),
    }


def check_request(req, token: str, crust=None, stop=None) -> dict:
    """Synchronous CHECK for one kickoff-kit request: parse the document, run, return the register."""
    from .crust import Crust
    from .ingest import resolve_document

    parsed = resolve_document(req, crust or Crust(token, cancel=stop))
    did = create_dossier(req.name or req.domain or "Unknown", req.domain, req.city, parsed.text)
    set_deck(did, parsed)
    rid = start_run(did, "check", token, background=False, stop=stop)
    run = store.q("SELECT * FROM runs WHERE id=?", (rid,), one=True)
    out = register_json(run, req.id, {**parsed.to_dict()})
    out["dossier_id"] = did
    return out
