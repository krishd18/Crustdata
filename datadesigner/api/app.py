"""FastAPI app (plan §4.2B): REST + webhooks + a server-rendered console styled by theme.css (= ui/prototype/styles.css,
unchanged). The full designed prototype is served at /prototype. Runs execute in a background thread; every stage
is checkpointed, so a killed server resumes with POST /runs/{id}/resume (or automatically at startup)."""
from __future__ import annotations

import html
import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..core.config_loader import get_config
from ..core.context import get_stores, make_context
from ..core.settings import ROOT, get_settings, http_mode
from ..mail.executor import Executor
from ..mail.providers import make_provider
from ..orchestrator import runner

app = FastAPI(title="Data Designer", version="0.1.0")
STATIC = Path(__file__).resolve().parents[1] / "ui" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/prototype", StaticFiles(directory=str(ROOT / "ui" / "prototype"), html=True), name="prototype")
_threads: dict[str, threading.Thread] = {}


def executor() -> Executor:
    s, c = get_settings(), get_config()
    return Executor(get_stores(), make_provider(s, c["mail"]), s, c["mail"])


def start(rid: str) -> None:
    if rid in _threads and _threads[rid].is_alive():
        return
    def work():
        try:
            runner.execute(rid)
        except Exception as e:  # noqa: BLE001
            get_stores().x("UPDATE runs SET state=? WHERE run_id=?", (f"FAILED: {type(e).__name__}: {str(e)[:160]}", rid))
    t = threading.Thread(target=work, daemon=True)
    _threads[rid] = t
    t.start()


@app.on_event("startup")
def on_startup() -> None:
    get_config().watch()
    try:
        executor().reconcile_all()            # journal reconcile first (exactly once after a kill)
    except Exception:  # noqa: BLE001
        pass
    for r in get_stores().rows("SELECT run_id FROM runs WHERE state NOT LIKE 'DONE%' AND state NOT LIKE 'FAILED%'"):
        start(r["run_id"])                    # resume interrupted runs from their last checkpoint


# ---------------------------------------------------------------- REST
class RunReq(BaseModel):
    text: str | None = None
    family: str | None = None
    pack_id: str | None = None
    pack: dict | None = None
    limits: dict | None = None
    use_llm: bool = True
    nonce: str | None = None


@app.post("/queries")
def queries(body: RunReq):
    from ..agents.a01_query_reasoner import AGENT as A1
    ctx = make_context(run_id="query", stores=get_stores())
    return A1({"text": body.text or "", "use_llm": body.use_llm}, ctx).model_dump()


@app.post("/runs")
def create_run(body: RunReq):
    rid = runner.create(body.model_dump(exclude_none=True))
    start(rid)
    return {"run_id": rid}


@app.get("/runs")
def list_runs():
    return get_stores().rows("SELECT run_id, family, state, created_at, updated_at FROM runs ORDER BY created_at DESC LIMIT 50")


@app.get("/runs/{rid}")
def get_run(rid: str):
    st = get_stores()
    r = st.one("SELECT * FROM runs WHERE run_id=?", (rid,))
    if not r:
        raise HTTPException(404)
    stages = [x["stage"] for x in st.rows("SELECT stage FROM checkpoints WHERE run_id=? ORDER BY created_at", (rid,))]
    return {**{k: r[k] for k in ("run_id", "family", "state", "config_version", "rubric_version")}, "stages": stages, "cost": st.cost_summary(rid)}


@app.post("/runs/{rid}/resume")
def resume(rid: str):
    executor().reconcile_all()
    start(rid)
    return {"run_id": rid, "resumed": True}


@app.get("/runs/{rid}/memo")
def memo(rid: str, format: str = "md"):
    res = get_stores().checkpoint(rid, "RESULT")
    if not res:
        raise HTTPException(409, "run not finished")
    m = res["memo"]
    if format == "json":
        return {**m.get("json", {}), "md": m["md"]}
    return HTMLResponse(page(m.get("id", ""), f'<article class="card memo">{m["html"]}</article>')) if format == "html" else PlainTextResponse(m["md"])


@app.get("/runs/{rid}/rubric")
def rubric(rid: str):
    res = get_stores().checkpoint(rid, "RESULT") or {}
    return res.get("decision") or (res.get("answer") or {}).get("r3") or {}


@app.patch("/runs/{rid}/limits")
def limits(rid: str, body: dict):
    st = get_stores()
    r = st.one("SELECT limits_json FROM runs WHERE run_id=?", (rid,))
    lim = {**json.loads(r["limits_json"] or "{}"), **body}
    st.x("UPDATE runs SET limits_json=? WHERE run_id=?", (json.dumps(lim), rid))
    return lim


class DecisionReq(BaseModel):
    final: str
    reason: str = ""
    by: str = "reviewer"


@app.post("/runs/{rid}/decision")
def decide(rid: str, body: DecisionReq):
    st = get_stores()
    res = st.checkpoint(rid, "RESULT") or {}
    sug = (res.get("decision") or {}).get("label", "")
    if body.final != sug and not body.reason.strip():
        raise HTTPException(422, "an override needs a reason")
    st.x("INSERT INTO decisions(run_id,suggested,final,decided_by,reason,at) VALUES(?,?,?,?,?,?)", (rid, sug, body.final, body.by, body.reason, time.time()))
    st.journal(f"decision:{rid}:{int(time.time())}", "decision.accepted" if body.final == sug else "decision.overridden",
               {"suggested": sug, "final": body.final, "by": body.by, "reason": body.reason})
    return {"suggested": sug, "final": body.final}


class AskReq(BaseModel):
    question: str


@app.post("/runs/{rid}/ask")
def ask(rid: str, body: AskReq):
    """Ask the analyst: Claude (reason) over this run's memo + evidence; cites ids; never changes a score."""
    from ..core.claude import load_prompt, wrap_untrusted
    from ..core.errors import ParseFailed, SecretMissing

    class AnalystAnswer(BaseModel):
        answer: str
        citations: list[str]
        missing: list[str]
        refers_to_rule: str | None

    st = get_stores()
    res = st.checkpoint(rid, "RESULT")
    if not res:
        raise HTTPException(409, "run not finished")
    ev = st.rows("SELECT evidence_id, source, passage_or_field, value, record_date, tier FROM evidence WHERE run_id=? LIMIT 80", (rid,))
    ctx = make_context(run_id=rid, stores=st, mode="live" if http_mode() != "replay" else "replay")
    user = (f"Question: {body.question}\nMemo: {wrap_untrusted(res['memo']['md'][:12000], 'memo')}\n"
            f"Evidence: {wrap_untrusted(json.dumps(ev, ensure_ascii=False)[:12000], 'ledger')}")
    try:
        out, _ = ctx.claude.generate_json("reason", load_prompt("analyst_qa"), user, AnalystAnswer, task="analyst_qa")
        return out.model_dump()
    except (ParseFailed, SecretMissing) as e:
        return {"answer": f"The analyst is unavailable ({type(e).__name__}); the memo and its evidence remain authoritative.", "citations": [], "missing": [], "refers_to_rule": None}


@app.get("/approvals")
def approvals():
    return [{**json.loads(r["draft_json"]), "status": r["status"], "states": get_stores().journal_states(r["action_id"])}
            for r in get_stores().rows("SELECT * FROM approvals ORDER BY at DESC")]


class EditReq(BaseModel):
    subject: str
    body: str
    by: str = "reviewer"


@app.post("/approvals/{aid}/{action}")
async def approval_action(aid: str, action: str, request: Request):
    ex = executor()
    form = await request.form() if "form" in request.headers.get("content-type", "") else {}
    by = form.get("by", "reviewer") if form else "reviewer"
    if action == "approve":
        ex.approve(aid, by)
        state = ex.execute(aid)
        msg = {"reconciled": "Sent once · reconciled against the Sent folder", "unconfirmed": "Sent state unconfirmed — held, never resent blindly"}.get(state, state)
    elif action == "reject":
        ex.reject(aid, by, form.get("reason", "") if form else "")
        msg = "Rejected · nothing sent · journaled"
    elif action == "edit":
        data = form or await request.json()
        aid = ex.edit(aid, by, data["subject"], data["body"])
        msg = f"Edited · new draft {aid[:8]} awaiting approval"
    else:
        raise HTTPException(404)
    if form:
        return RedirectResponse(f"/ui/approvals?msg={msg}", status_code=303)
    return {"action_id": aid, "message": msg}


@app.get("/journal")
def journal(verify: int = 0):
    st = get_stores()
    rows = st.rows("SELECT seq, action_id, state, payload_json, provider_id, at, hash FROM journal ORDER BY seq")
    out: dict = {"entries": rows}
    if verify:
        ok, n = st.verify_chain()
        out["chain"] = {"intact": ok, "entries": n}
    return out


@app.get("/cost")
def cost(run: str | None = None):
    return get_stores().cost_summary(run)


@app.get("/setup/status")
def setup_status():
    s = get_settings()
    return {"present": s.present(), "http_mode": http_mode(), "mail_provider": s.mail_provider, "mail_mode": s.mail_mode,
            "config_version": get_config().version}


@app.post("/admin/reload")
def reload():
    get_config().reload()
    return {"config_version": get_config().version}


@app.post("/webhooks/crustdata")
async def webhook(request: Request):
    body = await request.body()
    sha = get_stores().put_blob(body)
    get_stores().journal(f"webhook:{sha[:16]}", "received", {"bytes": len(body)})
    return {"ok": True}


# ---------------------------------------------------------------- console (server-rendered, theme.css)
def page(title: str, body: str) -> str:
    s = get_settings()
    cost = get_stores().cost_summary()
    pending = get_stores().one("SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Data Designer</title><link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="/static/theme.css"><link rel="stylesheet" href="/static/console.css"><script src="https://unpkg.com/htmx.org@1.9.12"></script></head>
<body><a class="sr" href="#main">Skip to content</a><header class="nav"><div class="nav-inner dd-nav"><a class="brand" href="/"><b>Data Designer</b></a>
<a href="/">Ask</a><a href="/ui/runs">Runs</a><a href="/ui/approvals">Approvals ({pending})</a><a href="/ui/audit">Audit</a><a href="/ui/setup">Setup</a><a href="/prototype/">Prototype</a>
<span class="meter-mini">credits <b class="num">{cost['credits']}</b> · ₹{cost['inr']}</span><span class="env {'live' if http_mode() == 'live' else ''}"><i></i>{http_mode()}</span></div></header>
<main id="main" class="dd-main">{body}</main><footer class="dd-foot">Data by Crustdata · reasoning by Claude · suggestions only — a person decides{' · TEST MODE: mail goes to the test inbox' if s.mail_mode != 'live' else ''}</footer></body></html>"""


SAMPLES = ["Find ten Indian B2B software companies founded since 2023 whose team grew by half in the last six months, and tell me who founded each and what they did before.",
           "Which Indian fintech companies are hiring the most engineers this quarter, and what does their hiring say about what each will launch next?",
           "acquirable logistic companies in maharashtra"]


@app.get("/", response_class=HTMLResponse)
def home():
    chips = "".join(f'<button type="button" class="chip" onclick="document.getElementById(\'q\').value=this.textContent">{html.escape(s)}</button>' for s in SAMPLES)
    packs = "".join(f'<form method="post" action="/ui/run" style="display:inline"><input type="hidden" name="pack_id" value="{p}"><button class="chip">{lbl}</button></form>'
                    for p, lbl in (("company_c", "Fact-check deck: Company C (sample)"), ("acme_vendor", "Vendor pack: ACME Freight (sample)")))
    return page("Ask", f"""<section class="hero dd-hero"><h1>Every claim, <span class="hl">checked</span> before you sign.</h1>
<p class="muted">Type a request. Data Designer reasons over each word, shows you how it read it, then finds, checks, scores and writes the memo.</p>
<form method="post" action="/ui/run" class="dd-ask"><textarea id="q" name="text" rows="3" placeholder="e.g. Which Indian fintech companies are hiring the most engineers this quarter?" required></textarea>
<button class="btn primary" type="submit">Reason about it →</button></form><div class="chips">{chips}</div><div class="chips">{packs}</div></section>{runs_table()}""")


def runs_table() -> str:
    rows = get_stores().rows("SELECT run_id, family, state, request_json FROM runs ORDER BY created_at DESC LIMIT 20")
    tr = "".join(f'<tr><td class="mono"><a href="/ui/runs/{r["run_id"]}">{r["run_id"]}</a></td><td><span class="tag">{r["family"] or "…"}</span></td>'
                 f'<td>{html.escape((json.loads(r["request_json"]).get("text") or json.loads(r["request_json"]).get("pack_id") or "")[:110])}</td><td>{html.escape(r["state"])}</td></tr>' for r in rows)
    return f'<section class="card"><div class="label">Runs</div><table class="tbl"><tr><th>Run</th><th>Family</th><th>Request</th><th>State</th></tr>{tr}</table></section>'


@app.post("/ui/run")
async def ui_run(request: Request):
    f = await request.form()
    req = {"text": f.get("text"), "pack_id": f.get("pack_id") or None}
    if req["pack_id"]:
        req["family"] = "VENDOR_CHECK" if "vendor" in req["pack_id"] else "DECK_CHECK"
        req["use_llm"] = False
        req["text"] = req["pack_id"]
    rid = runner.create({k: v for k, v in req.items() if v is not None})
    start(rid)
    return RedirectResponse(f"/ui/runs/{rid}", status_code=303)


@app.get("/ui/runs", response_class=HTMLResponse)
def ui_runs():
    return page("Runs", runs_table())


@app.get("/ui/runs/{rid}", response_class=HTMLResponse)
def ui_run_view(rid: str):
    st = get_stores()
    r = st.one("SELECT * FROM runs WHERE run_id=?", (rid,))
    if not r:
        raise HTTPException(404)
    res = st.checkpoint(rid, "RESULT")
    stages = st.rows("SELECT stage FROM checkpoints WHERE run_id=? ORDER BY created_at", (rid,))
    c = st.cost_summary(rid)
    tl = "".join(f'<li class="done">✓ {s["stage"]}</li>' for s in stages)
    head = f"""<div class="title-row"><div><div class="label">Run · {rid}</div><h1>{html.escape(r['family'] or 'Run')}</h1>
<div class="meta">state {html.escape(r['state'])} · config {r['config_version']} · rubric {html.escape(r['rubric_version'] or '')} · {c['credits']} credits · {c['llm_tokens_in']}+{c['llm_tokens_out']} Claude tokens · ₹{c['inr']}</div></div>
<div><form method="post" action="/runs/{rid}/resume" hx-post="/runs/{rid}/resume" hx-swap="none"><button class="btn">Resume</button></form>
<a class="btn" href="/runs/{rid}/memo?format=md">Markdown</a></div></div><ol class="dd-stages">{tl}</ol>"""
    if not res:
        return page(rid, head + '<p class="muted" hx-get="/ui/runs/' + rid + '" hx-trigger="every 3s" hx-select="main" hx-target="main">Working… stages tick as they finish.</p>')
    dec = ""
    if res.get("decision"):
        lab = res["decision"]["label"]
        dec = f"""<section class="card"><div class="label">5 · Your decision</div><p class="muted">Suggestion only. Accept it, or override with a reason; both are journaled.</p>
<form hx-post="/runs/{rid}/decision" hx-ext="json-enc" hx-swap="none" onsubmit="event.preventDefault();fetch('/runs/{rid}/decision',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{final:this.final.value,reason:this.reason.value}})}}).then(r=>r.json()).then(j=>alert(JSON.stringify(j)))">
<select name="final"><option>{lab}</option><option>PURSUE</option><option>PURSUE WITH CONDITIONS</option><option>HOLD — MORE EVIDENCE NEEDED</option><option>PASS</option><option>CLEAR</option><option>CLEAR WITH CONDITIONS</option><option>HOLD FOR A PERSON</option><option>REJECT</option></select>
<input name="reason" placeholder="reason (required to override)"><button class="btn primary">Record decision</button></form></section>"""
    ask = f"""<section class="card"><div class="label">Ask the analyst</div><form onsubmit="event.preventDefault();const o=document.getElementById('ans');o.textContent='…';fetch('/runs/{rid}/ask',{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{question:this.q.value}})}}).then(r=>r.json()).then(j=>o.textContent=j.answer+(j.citations.length?' ['+j.citations.join(', ')+']':''))">
<input name="q" placeholder="Why is C11 only 1 point?" style="width:70%"><button class="btn">Ask</button></form><p id="ans" class="muted"></p></section>"""
    return page(rid, head + f'<article class="card memo">{res["memo"]["html"]}</article>' + dec + ask)


@app.get("/ui/approvals", response_class=HTMLResponse)
def ui_approvals(msg: str = ""):
    s = get_settings()
    cards = []
    for a in approvals():
        dots = " ".join(f'<span class="tag">{x}</span>' for x in a["states"])
        btn = "" if a["status"] != "pending" else f"""<form method="post" action="/approvals/{a['action_id']}/approve" style="display:inline"><input type="hidden" name="by" value="reviewer"><button class="btn primary">Approve &amp; send</button></form>
<form method="post" action="/approvals/{a['action_id']}/reject" style="display:inline"><input name="reason" placeholder="reason"><button class="btn">Reject</button></form>"""
        cards.append(f"""<section class="card"><div class="label">{a['template']} · {a['status']} · {a['action_id'][:12]}</div><div class="mono sub">To: {html.escape(a['to'])}{' → TEST INBOX' if s.mail_mode != 'live' else ''}</div>
<h3>{html.escape(a['subject'])}</h3><pre class="dd-mail">{html.escape(a['body'])}</pre><div>{dots}</div>{btn}</section>""")
    banner = '<div class="card dd-test">TEST MODE · every approved email is redirected to the test inbox</div>' if s.mail_mode != "live" else ""
    note = f'<div class="toast show">{html.escape(msg)}</div>' if msg else ""
    return page("Approvals", banner + note + ("".join(cards) or '<p class="muted">No drafts yet — run a deck or vendor check.</p>'))


@app.get("/ui/audit", response_class=HTMLResponse)
def ui_audit():
    j = journal(verify=1)
    rows = "".join(f'<div class="jrow"><span class="num sub">{time.strftime("%H:%M:%S", time.localtime(e["at"]))}</span><span class="ev">{e["state"]}</span><span class="mono">{e["action_id"][:28]}</span><span class="mono sub">{e["hash"][:8]}…</span></div>' for e in j["entries"][-200:])
    return page("Audit", f'<section class="card"><div class="label">Journal · hash chain {"intact ✓" if j["chain"]["intact"] else "BROKEN ✗"} · {j["chain"]["entries"]} entries</div>{rows}</section>')


@app.get("/ui/setup", response_class=HTMLResponse)
def ui_setup():
    st = setup_status()
    rows = "".join(f'<div class="card"><b>{k}</b> <span class="state {"ok" if v else ""}">{"present" if v else "missing — run make setup-secrets"}</span></div>' for k, v in st["present"].items())
    return page("Setup", f'<section><div class="label">Connections (booleans only — values are never shown)</div>{rows}<p class="muted">HTTP mode {st["http_mode"]} · mail {st["mail_provider"]} ({st["mail_mode"]}) · config {st["config_version"]}</p></section>')
