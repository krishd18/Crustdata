"""Family flows (plan §4.2B). Every stage output is checkpointed; resume skips finished stages.
FIND_LIST / RESEARCH_QA: A1 → A2 → A11 → R3 → A13 Research Memo.
CHECK (DECK_CHECK / VENDOR_CHECK / ACQUIRE·CHECK): A3 → A4 → A5 → A6 → A7 → A8 → A9 → A10 → A12 (R2) → A13 Company IM → A14 asks.
ACQUIRE (Step 1): A1 → A2 (streams) → gate → R1 → A13 Market IM."""
from __future__ import annotations

from typing import Any, Callable

from ..agents.a01_query_reasoner import AGENT as A1
from ..agents.a02_scout import AGENT as A2
from ..agents.a03_entity_resolver import AGENT as A3
from ..agents.a04_deck_intake import AGENT as A4
from ..agents.a05_evidence import AGENT as A5
from ..agents.a06_quote_lock import AGENT as A6
from ..agents.a07_verdict import AGENT as A7
from ..agents.a08_financial import AGENT as A8
from ..agents.a09_people import AGENT as A9
from ..agents.a10_market_region import AGENT as A10
from ..agents.a11_research import AGENT as A11
from ..agents.a12_decision import AGENT as A12


class Stages:
    """Checkpoint helper: run(stage, fn) returns the stored output if the stage already finished (resume)."""

    def __init__(self, ctx, on_stage: Callable[[str, str], None] | None = None):
        self.ctx, self.on_stage = ctx, on_stage or (lambda s, st: None)
        self.done: list[str] = []

    def run(self, stage: str, fn: Callable[[], Any]) -> Any:
        hit = self.ctx.stores.checkpoint(self.ctx.run_id, stage)
        if hit is not None:
            self.done.append(stage)
            self.on_stage(stage, "resumed")
            return hit
        self.on_stage(stage, "running")
        out = fn()
        data = out.model_dump(mode="json") if hasattr(out, "model_dump") else out
        self.ctx.stores.put_checkpoint(self.ctx.run_id, stage, data)
        self.done.append(stage)
        self.on_stage(stage, "done")
        return data


def research(ctx, text: str, st: Stages, use_llm: bool = True, card: dict | None = None) -> dict:
    card = card or st.run("A1_reasoning", lambda: A1({"text": text, "use_llm": use_llm, "client_profile": ctx.config.get("client", {})}, ctx))
    plan = card["plan"]
    cs = st.run("A2_scout", lambda: A2({"plan": plan}, ctx))
    ans = st.run("A11_research", lambda: A11({"plan": plan, "candidates": cs, "use_llm": use_llm}, ctx))
    return {"card": card, "candidates": cs, "answer": ans}


def check(ctx, pack: dict, st: Stages, use_llm: bool = True) -> dict:
    co = pack.get("company", {})
    ent = st.run("A3_entity", lambda: A3({"name": co.get("name", ""), "domain": co.get("domain"), "cin": co.get("cin"),
                                          "candidates": pack.get("entity_candidates") or [{"name": co.get("name"), "domain": co.get("domain"), "cin": co.get("cin")}],
                                          "lookup": False}, ctx))
    cset = st.run("A4_claims", lambda: A4({"pages": pack.get("pages", []), "claims": pack.get("claims", []), "files": pack.get("files", []),
                                           "use_llm": use_llm}, ctx))
    bundle = st.run("A5_evidence", lambda: A5({"claims": cset["claims"], "extracts": pack.get("extracts", []),
                                               "crustdata_company_id": co.get("crustdata_company_id"), "live_sources": bool(co.get("crustdata_company_id"))}, ctx))
    locked = st.run("A6_quote_lock", lambda: A6(bundle, ctx))
    asks = ctx.config["asks"]
    missing = {t: asks["asks"][k] for t, k in asks.get("type_to_ask", {}).items() if k in asks["asks"]}
    verdicts = st.run("A7_verdicts", lambda: A7({"claims": cset["claims"], "evidence": locked["accepted"], "by_claim": locked["by_claim"],
                                                 "unavailable": locked["unavailable"], "entity_score": ent["score"], "entity_status": ent["status"],
                                                 "missing_docs": missing}, ctx))
    fin = st.run("A8_financial", lambda: A8(pack.get("financial", {}), ctx))
    vmap = {v["claim_id"]: v for v in verdicts["verdicts"]}
    bio = [c for c in cset["claims"] if c["kind"] == "bio"]
    ppl_in = dict(pack.get("people", {}))
    ppl_in["bio_verdict_credits"] = [vmap[c["claim_id"]]["credit_floor"] or 0 for c in bio if vmap[c["claim_id"]]["cls"] != "NOT_CHECKED"]
    ppl_in["bio_false"] = any(vmap[c["claim_id"]]["cls"] == "FALSE" for c in bio)
    ppl = st.run("A9_people", lambda: A9(ppl_in, ctx))
    mkt = st.run("A10_market", lambda: A10({"profile": pack.get("profile", "target"), **pack.get("market", {})}, ctx))
    dec_in = {"profile": pack.get("profile", "target"), "claims": cset["claims"], "verdicts": verdicts["verdicts"], "financial": fin,
              "people": ppl, "market": mkt, "entity_score": ent["score"], **pack.get("decision", {})}
    sc = [s for s in ppl.get("screening", [])]
    if any(s["status"].startswith("possible") for s in sc):
        dec_in["sanctions"] = "possible"
    dec = st.run("A12_decision", lambda: A12(dec_in, ctx))
    return {"entity": ent, "claims": cset, "evidence": locked, "verdicts": verdicts, "financial": fin, "people": ppl, "market": mkt, "decision": dec}
