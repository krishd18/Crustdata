"""SecondLook API + static UI.  Run:  uvicorn app.main:app --port 8765"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import cancel, emailer, find, ingest, outbox, pipeline, store  # noqa: E402
from .crust import Crust, CrustError, now_iso  # noqa: E402


class RedactPII(logging.Filter):
    EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
    PHONE = re.compile(r"\+?\d[\d\s-]{8,}\d")

    def filter(self, record):
        msg = record.getMessage()
        record.msg = self.PHONE.sub("[phone]", self.EMAIL.sub("[email]", msg))
        record.args = ()
        return True


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
for h in logging.getLogger().handlers:
    h.addFilter(RedactPII())
log = logging.getLogger("secondlook")

app = FastAPI(title="SecondLook")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
app.mount("/samples", StaticFiles(directory=ROOT / "samples"), name="samples")  # demo decks


def token() -> str:
    t = os.getenv("CRUSTDATA_API_TOKEN")
    if not t:
        raise HTTPException(500, "CRUSTDATA_API_TOKEN is not set (see .env.example)")
    return t


def _stop(request: Request | None):
    """The Stop flag for a request the browser waits on (it sends `x-job-id`)."""
    return cancel.token(request.headers.get("x-job-id")) if request is not None else None


def _stopped(crust: Crust | None = None) -> HTTPException:
    return HTTPException(499, {"stopped": True, "credits": crust.credits_used if crust else 0})


# ---- Stop ----------------------------------------------------------------------
@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    """Stop a request in progress (FIND, Read thesis, deck URL, kickoff-kit check, watch)."""
    cancel.cancel(job_id)
    return {"job_id": job_id, "stopped": True}


@app.post("/api/runs/{rid}/cancel")
def cancel_run(rid: str):
    """Stop a screen / check / re-check run. Credits already spent stay on the run."""
    if not store.q("SELECT id FROM runs WHERE id=?", (rid,), one=True):
        raise HTTPException(404)
    return {"run_id": rid, "stopped": pipeline.cancel_run(rid)}


def _dossier(did: str) -> dict:
    d = store.q("SELECT * FROM dossiers WHERE id=?", (did,), one=True)
    if not d:
        raise HTTPException(404, "no such dossier")
    return d


@app.exception_handler(CrustError)
def _crust_error(_request: Request, e: CrustError):
    """Any Crustdata failure reaches the page as one plain sentence."""
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": e.friendly, "status": e.status, "path": e.path},
                        status_code=e.status if e.status in (401, 402, 403, 404, 429) else 502)


@app.on_event("startup")
def _startup():
    store.init()
    # A run still "running" from before a restart has no worker any more: say so,
    # instead of leaving the page polling forever.
    store.x("UPDATE runs SET status='error', finished_at=?, error=? WHERE status='running'",
            (now_iso(), "Interrupted: the server restarted while this run was in progress. Run it again."))
    rec = outbox.recover()
    if rec:
        log.warning("startup recovery finished %d send(s)", len(rec))


# ---- pages ----------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/config")
def config():
    from . import extract
    from . import ocr
    return {"crustdata": bool(os.getenv("CRUSTDATA_API_TOKEN")), "llm": extract.llm_available(), "model": extract.MODEL,
            "mail": outbox.describe(), "ocr": ocr.describe()}


@app.get("/api/samples")
def samples():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((ROOT / "samples").glob("*.json"))]


# ---- 1. FIND ----------------------------------------------------------------
class FindBody(BaseModel):
    thesis: str
    min_headcount: int | None = 10
    limit: int = 15
    enrich_top: int = 6


@app.post("/api/find/interpret")
def interpret_thesis(body: FindBody, request: Request):
    """How a thesis will be read, before any Crustdata credits are spent."""
    from . import thesis_ai
    if not body.thesis.strip():
        raise HTTPException(400, "describe what you're looking for")
    try:
        it = cancel.call(_stop(request), thesis_ai.interpret, body.thesis)
    except cancel.Cancelled:
        raise _stopped()
    filters, applied = thesis_ai.to_filters(it["params"], body.min_headcount)
    return {"parser": it["parser"], "seconds": it["seconds"], "error": it["error"], "query": it["params"]["what"],
            "applied": applied, "unsupported": it["params"]["unsupported"], "params": it["params"], "filters": filters}


@app.post("/api/find")
def run_find(body: FindBody, request: Request):
    if not body.thesis.strip():
        raise HTTPException(400, "describe what you're looking for")
    c = Crust(token(), cancel=_stop(request))
    try:
        res = find.shortlist(c, body.thesis, min_headcount=body.min_headcount, limit=max(1, min(body.limit, 50)),
                             enrich_top=max(0, min(body.enrich_top, 15)))
    except CrustError as e:
        raise HTTPException(e.status, e.friendly)
    except cancel.Cancelled:
        c.settle(2.5)  # let calls already sent come back so their credits are counted
        log.info("FIND stopped by a person after %.2f credits", c.credits_used)
        raise _stopped(c)
    sid = f"s_{uuid.uuid4().hex[:10]}"
    res["cost"] = {"credits": c.credits_used}
    store.x("INSERT INTO searches (id, thesis, created_at, result, credits) VALUES (?,?,?,?,?)",
            (sid, body.thesis, now_iso(), json.dumps(res), c.credits_used))
    return {"id": sid, **res}


@app.get("/api/searches")
def list_searches():
    return store.q("SELECT id, thesis, created_at, credits FROM searches WHERE flushed_at IS NULL"
                   " ORDER BY created_at DESC LIMIT 20")


@app.get("/api/searches/{sid}")
def get_search(sid: str):
    s = store.q("SELECT * FROM searches WHERE id=?", (sid,), one=True)
    if not s:
        raise HTTPException(404)
    return {"id": sid, **json.loads(s["result"])}


class AddBody(BaseModel):
    company_ids: list[int]


@app.post("/api/searches/{sid}/add")
def add_targets(sid: str, body: AddBody):
    try:
        return {"dossier_ids": pipeline.add_from_search(sid, body.company_ids)}
    except KeyError:
        raise HTTPException(404)


# ---- dossiers (targets in the pipeline) ----------------------------------
class NewDossier(BaseModel):
    name: str
    domain: str | None = None
    city: str | None = None
    teaser: str = ""


@app.post("/api/dossiers")
def create_dossier(body: NewDossier):
    token()
    did = pipeline.create_dossier(body.name, body.domain, body.city, body.teaser)
    out = {"dossier_id": did, "run_id": None}
    if body.teaser.strip():  # pasted a deck straight away -> go to CHECK
        pipeline.set_deck(did, ingest.Parsed(body.teaser, "text", "pasted text"))
        out["run_id"] = pipeline.start_run(did, "check", token())
    return out


@app.get("/api/dossiers")
def list_dossiers():
    rows = store.q("""SELECT d.id, d.name, d.domain, d.created_at,
                      (SELECT COUNT(*) FROM runs r WHERE r.dossier_id=d.id) AS runs,
                      (SELECT id FROM runs r WHERE r.dossier_id=d.id ORDER BY seq DESC LIMIT 1) AS last_run
                      FROM dossiers d WHERE d.flushed_at IS NULL AND d.deleted_at IS NULL ORDER BY created_at DESC""")
    for r in rows:
        r["stage"] = pipeline.current_step(pipeline.stage(r["id"]))
    return rows


# ---- flush the pipeline (hide every target; restorable; sends unaffected) -----------
class FlushBody(BaseModel):
    searches: bool = False


@app.get("/api/pipeline/flush")
def flush_preview():
    """What a flush would clear, so the page can say it before a person confirms."""
    return pipeline.flush_preview()


@app.post("/api/pipeline/flush")
def flush_pipeline(body: FlushBody):
    out = pipeline.flush(body.searches)
    log.info("pipeline flushed: %d targets, %d searches, %d runs stopped", out["targets"], out["searches"], out["stopped_runs"])
    return out


@app.post("/api/pipeline/restore")
def restore_pipeline():
    return pipeline.restore_last_flush()


@app.post("/api/dossiers/{did}/delete")
def delete_dossier(did: str):
    """Take one target out of the pipeline (Undo puts it back)."""
    _dossier(did)
    return pipeline.delete_target(did)


@app.post("/api/dossiers/{did}/undelete")
def undelete_dossier(did: str):
    _dossier(did)
    return pipeline.undelete_target(did)


@app.get("/api/dossiers/{did}")
def get_dossier(did: str):
    d = _dossier(did)
    d["runs"] = store.q("SELECT id, seq, status, COALESCE(mode,'check') AS mode, started_at, finished_at"
                        " FROM runs WHERE dossier_id=? ORDER BY seq", (did,))
    d["watch"] = store.q("SELECT * FROM watches WHERE dossier_id=?", (did,), one=True)
    d["steps"] = pipeline.stage(did)
    d["current_step"] = pipeline.current_step(d["steps"])
    d["signals"] = json.loads(d["signals"]) if d.get("signals") else None
    d["deck_meta"] = json.loads(d["deck_meta"]) if d.get("deck_meta") else None
    d["outbox"] = list_outbox(did)
    d["has_deck"] = bool((d.get("teaser") or "").strip())
    d.pop("teaser", None)
    return d


# ---- 2. SCREEN ---------------------------------------------------------------
@app.post("/api/dossiers/{did}/screen")
def screen(did: str):
    _dossier(did)
    return {"run_id": pipeline.start_run(did, "screen", token())}


# ---- 3. REACH OUT ------------------------------------------------------------
class IntroBody(BaseModel):
    recipient: str
    sender_org: str = "our team"
    purpose: str = "exploring a potential partnership"
    why: str | None = None


@app.post("/api/dossiers/{did}/intro")
def intro_draft(did: str, body: IntroBody):
    d = _dossier(did)
    if not outbox.valid_address(body.recipient):
        raise HTTPException(400, "recipient must be one email address you were given")
    subject, text = emailer.compose_intro(d["name"], body.sender_org.strip() or "our team",
                                          body.purpose.strip() or "exploring a potential partnership", body.why)
    return outbox.draft(did, "intro", body.recipient.strip(), subject, text, kind="intro",
                        from_name=body.sender_org.strip() or None)


# ---- 4. CHECK: the deck arrives ------------------------------------------------
@app.post("/api/dossiers/{did}/deck")
async def upload_deck(did: str, request: Request, file: UploadFile | None = File(None), url: str | None = Form(None),
                      text: str | None = Form(None)):
    from starlette.concurrency import run_in_threadpool

    _dossier(did)
    stop = _stop(request)
    parts: list[ingest.Parsed] = []
    if file is not None and file.filename:
        data = await file.read()
        if len(data) > 25 * 1024 * 1024:
            raise HTTPException(413, "file over 25 MB")
        try:  # off the event loop: OCR of scanned pages takes a few seconds each, and Stop works
            parts.append(await run_in_threadpool(cancel.call, stop, ingest.parse_bytes, data, file.filename,
                                                 file.content_type or "", stop=stop))
        except cancel.Cancelled:
            raise _stopped()
    if url and url.strip():
        try:
            parts.append(await run_in_threadpool(cancel.call, stop, ingest.parse_url, url, Crust(token(), cancel=stop)))
        except cancel.Cancelled:
            raise _stopped()
        except Exception as e:
            raise HTTPException(400, f"could not read {url}: {e}")
    if text and text.strip():
        parts.append(ingest.parse_bytes(text.encode("utf-8"), "pasted text"))
    if not parts:
        raise HTTPException(400, "attach a file, give a URL, or paste text")
    merged = ingest.Parsed("\n\n".join(p.text for p in parts if p.text), parts[0].kind,
                           " + ".join(p.name or p.kind for p in parts), parts[0].pages,
                           [w for p in parts for w in p.warnings], next((p.ocr for p in parts if p.ocr), None))
    if not merged.text.strip():
        raise HTTPException(422, "no readable text: " + "; ".join(merged.warnings or ["empty document"]))
    pipeline.set_deck(did, merged)
    return {"run_id": pipeline.start_run(did, "check", token()), "parsed": merged.to_dict(),
            "preview": merged.text[:1500]}


# ---- 6. RE-CHECK ---------------------------------------------------------------
@app.post("/api/dossiers/{did}/recheck")
def recheck(did: str):
    d = _dossier(did)
    mode = "check" if (d.get("teaser") or "").strip() else "screen"
    return {"run_id": pipeline.start_run(did, mode, token())}


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    r = store.q("SELECT * FROM runs WHERE id=?", (rid,), one=True)
    if not r:
        raise HTTPException(404)
    r["progress"] = json.loads(r["progress"] or "[]")
    r["result"] = json.loads(r["result"]) if r["result"] else None
    return r


@app.get("/api/runs/{rid}/register")
def run_register(rid: str):
    r = store.q("SELECT * FROM runs WHERE id=?", (rid,), one=True)
    if not r:
        raise HTTPException(404)
    d = store.q("SELECT deck_meta FROM dossiers WHERE id=?", (r["dossier_id"],), one=True)
    return pipeline.register_json(r, None, json.loads(d["deck_meta"]) if d and d["deck_meta"] else None)


class Resolve(BaseModel):
    company_id: int


@app.post("/api/runs/{rid}/resolve")
def resolve_run(rid: str, body: Resolve):
    r = store.q("SELECT * FROM runs WHERE id=?", (rid,), one=True)
    if not r:
        raise HTTPException(404)
    store.x("UPDATE dossiers SET company_id=? WHERE id=?", (body.company_id, r["dossier_id"]))
    return {"run_id": pipeline.start_run(r["dossier_id"], r.get("mode") or "check", token())}


# ---- 5. REQUEST ------------------------------------------------------------------
class Draft(BaseModel):
    recipient: str
    sender_org: str = "our team"


@app.post("/api/runs/{rid}/draft")
def draft(rid: str, body: Draft):
    r = get_run(rid)
    if r["status"] != "done":
        raise HTTPException(400, "run not finished")
    if not outbox.valid_address(body.recipient):
        raise HTTPException(400, "recipient must be one email address you were given")
    subject, text, _usage = emailer.compose(r["result"], body.sender_org)
    return outbox.draft(r["dossier_id"], rid, body.recipient.strip(), subject, text, kind="request",
                        from_name=body.sender_org.strip() or None)


# ---- sends (steps 3 and 5): a person approves, delivered exactly once -------------
class Approve(BaseModel):
    approver: str


@app.post("/api/outbox/{key}/approve")
def approve(key: str, body: Approve):
    if not body.approver.strip():
        raise HTTPException(400, "a named person must approve")
    try:
        return outbox.approve_and_send(key, body.approver.strip())
    except KeyError:
        raise HTTPException(404)
    except PermissionError as e:
        raise HTTPException(409, str(e))


class Retry(BaseModel):
    approver: str
    confirm_not_sent: bool = False


@app.post("/api/outbox/{key}/retry")
def retry_send(key: str, body: Retry):
    """Failed: send again. Uncertain: only after a person confirms it isn't in the Sent folder."""
    if not body.approver.strip():
        raise HTTPException(400, "a named person must approve")
    try:
        return outbox.retry(key, body.approver.strip(), body.confirm_not_sent)
    except KeyError:
        raise HTTPException(404)
    except PermissionError as e:
        raise HTTPException(409, str(e))


@app.post("/api/outbox/{key}/mark-sent")
def mark_sent(key: str, body: Approve):
    if not body.approver.strip():
        raise HTTPException(400, "a named person must confirm")
    try:
        return outbox.mark_sent(key, body.approver.strip())
    except KeyError:
        raise HTTPException(404)
    except PermissionError as e:
        raise HTTPException(409, str(e))


class MailTest(BaseModel):
    to: str


@app.post("/api/mail/test")
def mail_test(body: MailTest):
    """Send one test message through the configured transport (not journaled)."""
    if not outbox.valid_address(body.to):
        raise HTTPException(400, "give one email address")
    try:
        return outbox.send_test(body.to.strip())
    except outbox.MailError as e:
        raise HTTPException(400, str(e))


@app.get("/api/outbox")
def list_outbox(dossier_id: str | None = None):
    rows = store.q("SELECT *, COALESCE(kind,'request') AS kind FROM outbox WHERE (? IS NULL OR dossier_id=?)"
                   " ORDER BY created_at DESC", (dossier_id, dossier_id))
    for row in rows:
        row["deliveries"] = outbox.transport.deliveries(row["idem_key"])
    return rows


# ---- kickoff-kit requests: JSON in, register JSON out (synchronous) ---------------
@app.post("/api/check")
async def check(request: Request):
    """Accepts the request as JSON (one object or a list / {"requests": [...]}), or a
    multipart upload with `file` (+ optional `company`, `domain`, `city`)."""
    ctype = request.headers.get("content-type", "")
    t = token()
    stop = _stop(request)
    if ctype.startswith("multipart/"):
        form = await request.form()
        f = form.get("file")
        req = ingest.parse_request({k: v for k, v in form.items() if isinstance(v, str)} or {})
        if f is not None and hasattr(f, "read"):
            import base64
            req.file_b64 = base64.b64encode(await f.read()).decode()
            req.file_name = f.filename
            req.warnings = [w for w in req.warnings if not w.startswith("No document")]
        return await _check_one(req, t, stop)
    raw = await request.body()
    try:
        obj = json.loads(raw)
    except ValueError:
        obj = raw.decode("utf-8", "replace")  # plain text body
    batch = isinstance(obj, list) or (isinstance(obj, dict) and any(
        isinstance(obj.get(k), list) for k in ("requests", "items", "cases", "tasks", "companies")))
    if not batch:
        return await _check_one(ingest.parse_request(obj), t, stop)
    out = []
    for r in ingest.parse_requests(obj):
        if stop is not None and stop.is_set():  # Stop pressed: skip the rest of the batch
            out.append({"request_id": r.id, "status": "cancelled", "error": "stopped by a person before it started"})
            continue
        out.append(await _check_one(r, t, stop))
    return out


async def _check_one(req, t: str, stop):
    from starlette.concurrency import run_in_threadpool
    try:
        return await run_in_threadpool(pipeline.check_request, req, t, None, stop)
    except cancel.Cancelled:  # stopped while reading the document, before the run started
        return {"request_id": req.id, "status": "cancelled", "error": "stopped by a person"}


# ---- person watch on leaders (recurring spend → preview, then explicit confirm) ----
class WatchCreate(BaseModel):
    preview_token: str | None = None
    refresh_days: int = 3


def _leaders(did: str) -> list[str]:
    r = store.q("SELECT result FROM runs WHERE dossier_id=? AND status='done' ORDER BY seq DESC LIMIT 1", (did,), one=True)
    if not r:
        raise HTTPException(400, "run the dossier first")
    return [p["profile_url"] for p in json.loads(r["result"]).get("leaders", [])]


@app.post("/api/dossiers/{did}/watch/preview")
def watch_preview(did: str, body: WatchCreate, request: Request):
    try:
        data, _ = Crust(token(), cancel=_stop(request)).watch_person(_leaders(did), preview=True,
                                                                   refresh_days=body.refresh_days)
    except CrustError as e:
        raise HTTPException(e.status, e.friendly)
    except cancel.Cancelled:
        raise _stopped()
    return data


@app.post("/api/dossiers/{did}/watch")
def watch_create(did: str, body: WatchCreate):
    urls = _leaders(did)
    try:
        data, _ = Crust(token()).watch_person(urls, preview=False, refresh_days=body.refresh_days,
                                              preview_token=body.preview_token)
    except CrustError as e:
        raise HTTPException(e.status, e.friendly)
    store.x("INSERT OR REPLACE INTO watches (dossier_id, watch_id, created_at, people) VALUES (?,?,?,?)",
            (did, data.get("id"), now_iso(), json.dumps(urls)))
    return data


@app.get("/api/dossiers/{did}/watch/runs")
def watch_runs(did: str):
    w = store.q("SELECT * FROM watches WHERE dossier_id=?", (did,), one=True)
    if not w:
        raise HTTPException(404, "no watch")
    data, _ = Crust(token()).watch_runs(w["watch_id"])
    return data
