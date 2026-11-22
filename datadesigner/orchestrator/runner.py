"""A0 Orchestrator (plan §4.2B). Creates runs, routes families, checkpoints every stage (resume skips finished
stages), reconciles the mail journal first on restart, and composes the memo. Same request → same run_id, so a
duplicate request joins the in-flight run."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ..agents.a01_query_reasoner import AGENT as A1
from ..agents.a12_decision import r1_score
from ..agents.a13_memo import AGENT as A13, NAMES
from ..agents.a14_outreach import AGENT as A14
from ..core.context import get_stores, make_context
from ..core.ids import canon, short
from ..core.settings import ROOT
from .flows import Stages, check, research

FIXTURE_PACKS = {"A2": "company_c", "V1": "acme_vendor", "R4": "acme_vendor", "H3": "company_c", "H8": "company_c"}


def run_id_for(request: dict) -> str:
    return short("R", canon({k: request.get(k) for k in ("text", "family", "pack_id", "nonce")}), n=10)


def create(request: dict, stores=None) -> str:
    st = stores or get_stores()
    rid = request.get("run_id") or run_id_for(request)
    if not st.one("SELECT run_id FROM runs WHERE run_id=?", (rid,)):
        from ..core.config_loader import get_config
        cfg = get_config()
        st.x("INSERT INTO runs(run_id,family,mandate_json,state,config_version,rubric_version,created_at,updated_at,request_json,limits_json) VALUES(?,?,?,?,?,?,?,?,?,?)",
             (rid, request.get("family") or "", "{}", "CREATED", cfg.version, cfg.rubric_version, time.time(), time.time(), canon(request),
              canon(request.get("limits") or {})))
    return rid


def set_state(st, rid: str, state: str) -> None:
    st.x("UPDATE runs SET state=?, updated_at=? WHERE run_id=?", (state, time.time(), rid))


def execute(rid: str, stores=None, mode: str | None = None, frozen_now: str | None = None, sdk_client=None, transport=None) -> dict:
    """Run (or resume) a run to completion. Safe to call repeatedly: finished stages come from checkpoints."""
    st = stores or get_stores()
    row = st.one("SELECT * FROM runs WHERE run_id=?", (rid,))
    req = json.loads(row["request_json"])
    limits = json.loads(row["limits_json"] or "{}")
    family = req.get("family") or ""
    ctx = make_context(run_id=rid, family=family or "FIND_LIST", mode=mode, frozen_now=frozen_now or req.get("frozen_now"), limits=limits,
                       stores=st, sdk_client=sdk_client, transport=transport, cassette=req.get("cassette"))
    stages = Stages(ctx, on_stage=lambda s, how: (set_state(st, rid, f"{s}:{how}"), ctx.log.info("stage", stage=s, how=how)))
    use_llm = req.get("use_llm", True)
    pack = req.get("pack")
    if not pack and req.get("pack_id"):
        pack = json.loads((ROOT / "tests" / "fixtures" / f"{req['pack_id']}.json").read_text())
    if pack or family in ("DECK_CHECK", "VENDOR_CHECK"):
        if not pack:
            raise ValueError("CHECK needs a pack (pack or pack_id)")
        family = family or ("VENDOR_CHECK" if pack.get("profile") == "vendor" else "DECK_CHECK")
        out = check(ctx, pack, stages, use_llm=use_llm)
        data = {**out, "company": pack.get("company", {}), "profile": pack.get("profile", "target")}
        memo = stages.run("A13_memo", lambda: A13({"kind": "COMPANY_IM", "run_id": rid, "data": data, "cost": st.cost_summary(rid)}, ctx))
        conds = [c for c in out["decision"]["conditions"] if not c.get("mitigation")]
        if conds and pack.get("recipient"):
            stages.run("A14_outreach", lambda: A14({"template": "doc_request", "company": pack.get("company", {}), "recipient": pack["recipient"],
                                                    "asks": [{"document": c["ask"], "claim_text": NAMES.get(c.get("criterion", ""), c.get("criterion", ""))} for c in conds[:4]],
                                                    "decision_label": out["decision"]["label"]}, ctx))
        result = {"family": family, **data, "memo": memo}
    else:
        card = stages.run("A1_reasoning", lambda: A1({"text": req["text"], "use_llm": use_llm}, ctx))
        family = card["family"]
        if family == "ACQUIRE":
            result = acquire(ctx, card, stages, rid)
        else:
            out = research(ctx, req["text"], stages, use_llm=use_llm, card=card)
            memo = stages.run("A13_memo", lambda: A13({"kind": "RESEARCH_MEMO", "run_id": rid, "data": out, "title": req["text"],
                                                       "cost": st.cost_summary(rid)}, ctx))
            result = {"family": family, **out, "memo": memo}
    st.x("UPDATE runs SET family=?, mandate_json=? WHERE run_id=?", (family, canon((result.get("card") or {}).get("plan", {})), rid))
    st.put_checkpoint(rid, "RESULT", result)
    set_state(st, rid, "DONE")
    return result


def acquire(ctx, card: dict, stages: Stages, rid: str) -> dict:
    """Step 1 (Market IM): logistics companies, location basis 'operates', gate, R1 with floor–ceiling (unknowns widen it)."""
    from ..agents.a02_scout import AGENT as A2
    plan = dict(card["plan"])
    plan["family"] = "FIND_LIST"
    cs = stages.run("A2_scout", lambda: A2({"plan": {**plan, "growth_months": None}, "search_limit": 60, "enrich_top": 25}, ctx))
    st_name = plan.get("state") or ""
    w = ctx.config["rubric"]["R1"]["criteria"]
    rows = []
    for c in cs["candidates"]:
        f = c.get("fields") or {}
        hq = (f.get("locations") or {}).get("headquarters") or ""
        hc = f.get("headcount") or {}
        gr = (hc.get("growth_percent") or {}).get("12m")
        from ..rubric.scoring import metric_points
        s2 = metric_points("GR-02", gr, ctx.config["metrics"]) if gr is not None else None
        in_state = st_name.lower() in hq.lower()
        s = {"S2": (s2, s2), "S8": ((3, 4) if in_state else (None, None))}
        r = r1_score(s, w, False, [])
        rows.append({"name": c["name"], "domain": c.get("domain"), "hq": hq, "operates_signal": "HQ in state" if in_state else "unknown (people/jobs streams needed)",
                     "headcount": hc.get("total"), "growth_12m": gr, **r})
    rows.sort(key=lambda r: (-r["floor"], -r["ceiling"], r["name"]))
    lines = [f"# MARKET IM · {short('MIM', rid, n=8)}", f"**{card['plan'].get('family')} · location basis = operates · as of {ctx.clock.now():%d %b %Y}**", "",
             "| # | Company | HQ | Operates signal | Staff | 12-m growth | R1 floor–ceiling | Label |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rows[:25], 1):
        lines.append(f"| {i} | {r['name']} | {r['hq']} | {r['operates_signal']} | {r['headcount']} | {r['growth_12m']} | {r['floor']:.2f}–{r['ceiling']:.2f} | {r['label']} |")
    lines += ["", "Financial-ratio, governance and tech requirements from 'acquirable' are **open** at Step 1 (private financials are not public) and are tested at CHECK."]
    md = "\n".join(lines)
    import markdown
    return {"family": "ACQUIRE", "card": card, "candidates": cs, "shortlist": rows, "memo": {"type": "MARKET_IM", "id": short("MIM", rid, n=8), "md": md,
            "html": markdown.markdown(md, extensions=["tables"]), "status": "DRAFT — awaiting selection"}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m datadesigner.orchestrator.runner")
    ap.add_argument("--case")
    ap.add_argument("--text")
    ap.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    req: dict = {}
    if a.case:
        for line in (ROOT / "tests" / "cases.jsonl").read_text().splitlines():
            d = json.loads(line)
            if d["id"] == a.case:
                req = {"text": d["input"], "family": d["family"] if d["family"] in ("DECK_CHECK", "VENDOR_CHECK") else None,
                       "frozen_now": d.get("frozen_now"), "cassette": d["id"], "pack_id": FIXTURE_PACKS.get(d["id"])}
    else:
        req = {"text": a.text}
    rid = create(req)
    res = execute(rid, mode="record" if a.record else None)
    sys.stdout.write(json.dumps({"run_id": rid, "family": res["family"], "memo_id": res["memo"]["id"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
