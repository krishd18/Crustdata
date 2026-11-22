"""SecondLook API + static UI.  Run:  uvicorn app.main:app --reload"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

from . import emailer, engine, outbox, store  # noqa: E402
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


def token() -> str:
    t = os.getenv("CRUSTDATA_API_TOKEN")
    if not t:
        raise HTTPException(500, "CRUSTDATA_API_TOKEN is not set (see .env.example)")
    return t


@app.on_event("startup")
def _startup():
    store.init()
    rec = outbox.recover()
    if rec:
        log.warning("startup recovery finished %d send(s)", len(rec))


def _start_run(dossier_id: str) -> str:
    seq = (store.q("SELECT COALESCE(MAX(seq),0) AS s FROM runs WHERE dossier_id=?", (dossier_id,), one=True) or {}).get("s", 0) + 1
    run_id = f"r_{uuid.uuid4().hex[:10]}"
    store.x("INSERT INTO runs (id, dossier_id, seq, status, started_at, progress) VALUES (?,?,?,?,?,?)",
            (run_id, dossier_id, seq, "running", now_iso(), "[]"))
    threading.Thread(target=engine.run, args=(run_id, token()), daemon=True).start()
    return run_id


# ---- pages ----------------------------------------------------------------
@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/config")
def config():
    from . import extract
    return {"crustdata": bool(os.getenv("CRUSTDATA_API_TOKEN")), "llm": extract.llm_available(),
            "model": extract.MODEL}


@app.get("/api/samples")
def samples():
    out = []
    for p in sorted((ROOT / "samples").glob("*.json")):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    return out


# ---- dossiers & runs -------------------------------------------------------
class NewDossier(BaseModel):
    name: str
    domain: str | None = None
    city: str | None = None
    teaser: str


@app.post("/api/dossiers")
def create_dossier(body: NewDossier):
    token()
    did = f"d_{uuid.uuid4().hex[:10]}"
    domain = (body.domain or "").strip().lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").strip("/") or None
    store.x("INSERT INTO dossiers (id, name, domain, city, teaser, created_at) VALUES (?,?,?,?,?,?)",
            (did, body.name.strip(), domain, (body.city or "").strip() or None, body.teaser, now_iso()))
    return {"dossier_id": did, "run_id": _start_run(did)}


@app.get("/api/dossiers")
def list_dossiers():
    return store.q("""SELECT d.id, d.name, d.domain, d.created_at,
                      (SELECT COUNT(*) FROM runs r WHERE r.dossier_id=d.id) AS runs,
                      (SELECT id FROM runs r WHERE r.dossier_id=d.id ORDER BY seq DESC LIMIT 1) AS last_run
                      FROM dossiers d ORDER BY created_at DESC""")


@app.get("/api/dossiers/{did}")
def get_dossier(did: str):
    d = store.q("SELECT * FROM dossiers WHERE id=?", (did,), one=True)
    if not d:
        raise HTTPException(404)
    d["runs"] = store.q("SELECT id, seq, status, started_at, finished_at FROM runs WHERE dossier_id=? ORDER BY seq", (did,))
    d["watch"] = store.q("SELECT * FROM watches WHERE dossier_id=?", (did,), one=True)
    return d


@app.post("/api/dossiers/{did}/recheck")
def recheck(did: str):
    if not store.q("SELECT id FROM dossiers WHERE id=?", (did,), one=True):
        raise HTTPException(404)
    return {"run_id": _start_run(did)}


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    r = store.q("SELECT * FROM runs WHERE id=?", (rid,), one=True)
    if not r:
        raise HTTPException(404)
    r["progress"] = json.loads(r["progress"] or "[]")
    r["result"] = json.loads(r["result"]) if r["result"] else None
    return r


class Resolve(BaseModel):
    company_id: int


@app.post("/api/runs/{rid}/resolve")
def resolve_run(rid: str, body: Resolve):
    r = store.q("SELECT * FROM runs WHERE id=?", (rid,), one=True)
    if not r:
        raise HTTPException(404)
    store.x("UPDATE dossiers SET company_id=? WHERE id=?", (body.company_id, r["dossier_id"]))
    return {"run_id": _start_run(r["dossier_id"])}


# ---- the irreversible step: sending to the counterparty --------------------
class Draft(BaseModel):
    recipient: str
    sender_org: str = "our team"


@app.post("/api/runs/{rid}/draft")
def draft(rid: str, body: Draft):
    r = get_run(rid)
    if r["status"] != "done":
        raise HTTPException(400, "run not finished")
    subject, text, _usage = emailer.compose(r["result"], body.sender_org)
    return outbox.draft(r["dossier_id"], rid, body.recipient.strip(), subject, text)


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


@app.get("/api/outbox")
def list_outbox(dossier_id: str | None = None):
    rows = store.q("SELECT * FROM outbox WHERE (? IS NULL OR dossier_id=?) ORDER BY created_at DESC", (dossier_id, dossier_id))
    for row in rows:
        row["deliveries"] = outbox.transport.deliveries(row["idem_key"])
    return rows


# ---- person watch on leaders (recurring spend → preview, then explicit confirm)
class WatchCreate(BaseModel):
    preview_token: str | None = None
    refresh_days: int = 3


def _leaders(did: str) -> list[str]:
    r = store.q("SELECT result FROM runs WHERE dossier_id=? AND status='done' ORDER BY seq DESC LIMIT 1", (did,), one=True)
    if not r:
        raise HTTPException(400, "run the dossier first")
    return [p["profile_url"] for p in json.loads(r["result"]).get("leaders", [])]


@app.post("/api/dossiers/{did}/watch/preview")
def watch_preview(did: str, body: WatchCreate):
    c = Crust(token())
    try:
        data, _ = c.watch_person(_leaders(did), preview=True, refresh_days=body.refresh_days)
    except CrustError as e:
        raise HTTPException(e.status, e.body)
    return data


@app.post("/api/dossiers/{did}/watch")
def watch_create(did: str, body: WatchCreate):
    c = Crust(token())
    urls = _leaders(did)
    try:
        data, _ = c.watch_person(urls, preview=False, refresh_days=body.refresh_days, preview_token=body.preview_token)
    except CrustError as e:
        raise HTTPException(e.status, e.body)
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
