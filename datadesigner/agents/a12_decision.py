"""A12 Decision Engine (STANDARDS §6.3–6.5). Assembles C1…C11 from the reports, runs gates G1–G8, R2 floor–ceiling,
the fixed rule, query requirements (min-band), conditions and 'what would change it'. Deterministic; must equal
tools/rubric_check.py (V7). R1 (Step 1) labels for the Market IM are computed here too."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.types import Claim, Verdict
from ..rubric.decision import CriterionIn, Decision, Gate, decide
from ..rubric.research import r1
from ..rubric.scoring import band, composite, metric_points, rdown, vi01
from .base import BaseAgent, cli


class DecisionInput(BaseModel):
    profile: str = "target"
    claims: list[Claim]
    verdicts: list[Verdict]
    financial: dict = Field(default_factory=dict)     # FinancialReport
    people: dict = Field(default_factory=dict)        # PeopleReport
    market: dict = Field(default_factory=dict)        # MarketRegionReport
    entity_score: float = 1.0
    legal_status: str = "active"
    sanctions: str = "none"
    in_mandate: bool = True
    mandate_fit_pct: float | None = None
    governance_flags: list[str] = Field(default_factory=list)
    reputation_points: float | None = 4
    growth_metric: dict = Field(default_factory=dict)  # {"GR-01": 21} or {"GR-02": ...}
    tech_led: bool = False
    engineering_share_pct: float | None = None
    requirements: dict[str, float | str] = Field(default_factory=dict)
    extra_requirements: list[dict] = Field(default_factory=list)


def credits(vs: list[Verdict]) -> tuple[float, float, int]:
    vs = [v for v in vs if v.cls != "NOT_CHECKED"]
    return sum(v.credit_floor or 0 for v in vs), sum(v.credit_ceiling or 0 for v in vs), len(vs)


class DecisionEngine(BaseAgent[DecisionInput, Decision]):
    name, input_model, output_model = "a12_decision", DecisionInput, Decision

    def run(self, inp: DecisionInput, ctx) -> Decision:
        cfg, mc = ctx.config["rubric"], ctx.config["metrics"]
        asks_cfg = ctx.config["asks"]
        vmap = {v.claim_id: v for v in inp.verdicts}
        cl = [c for c in inp.claims if c.claim_id in vmap]
        crit_vs = [vmap[c.claim_id] for c in cl if c.critical]
        noncrit_false = sum(1 for c in cl if not c.critical and vmap[c.claim_id].cls == "FALSE")
        crits: list[CriterionIn] = []

        def vi_crit(cid: str, group: list[Claim], penalty: int = 0) -> CriterionIn:
            vs = [vmap[c.claim_id] for c in group]
            f, c, n = credits(vs)
            if not n:
                return CriterionIn(id=cid, coverage=0)
            pf, pc, pctf, pctc = vi01(f, c, n, penalty)
            cov = sum(1 for v in vs if v.cls not in ("NOT_VERIFIABLE", "NOT_CHECKED")) / n
            ci = CriterionIn(id=cid, value=f"{pctf:.1f}%; ceiling {pctc:.1f}%", pf=pf, pc=pc, coverage=round(cov, 4))
            # asks: settling the claims behind one document
            by_ask: dict[str, list[str]] = {}
            for g in group:
                v = vmap[g.claim_id]
                key = asks_cfg.get("type_to_ask", {}).get(g.type)
                if key and v.cls in ("NOT_VERIFIABLE", "UNVERIFIED", "OUTDATED", "PARTIALLY_VERIFIED"):
                    by_ask.setdefault(key, []).append(g.claim_id)
            for key, ids in by_ask.items():
                f2 = f + sum(1 - (vmap[i].credit_floor or 0) for i in ids)
                new_pf = vi01(f2, c, n, penalty)[0]
                if new_pf > pf:
                    ci.asks.append({"ask": asks_cfg["asks"][key], "new_pf": new_pf})
            return ci

        crits.append(vi_crit("C1", [c for c in cl if c.critical], noncrit_false))
        g = inp.financial.get("grade")
        gp = {"A": 4, "B": 3, "C": 2, "D": 1, "E": 0}.get(g) if g else None
        crits.append(CriterionIn(id="C2", value=f"grade {g}" if g else "no statements", pf=gp, pc=gp if gp is not None else None, coverage=1.0 if g else 0))
        gm = inp.growth_metric or {}
        mid, gv = next(iter(gm.items()), (None, None))
        gpts = metric_points(mid, gv, mc) if mid else None
        crits.append(CriterionIn(id="C3", value=f"{mid} {gv}%" if mid else "—", pf=gpts, pc=gpts, coverage=1.0 if gpts is not None else 0))
        mk = inp.market.get("mk_c")
        crits.append(CriterionIn(id="C4", value=f"MK-C {mk}" if mk is not None else "—", pf=mk, pc=mk, coverage=1.0 if mk is not None else 0))
        c5 = max(4 - len(inp.governance_flags), 0)
        crits.append(CriterionIn(id="C5", value=f"{len(inp.governance_flags)} flag(s)" + (f": {', '.join(inp.governance_flags)}" if inp.governance_flags else ""), pf=c5, pc=c5))
        crits.append(CriterionIn(id="C6", value="none confirmed" if inp.reputation_points == 4 else f"RP-01 {inp.reputation_points}", pf=inp.reputation_points, pc=inp.reputation_points))
        if inp.mandate_fit_pct is not None:
            c7f = band(inp.mandate_fit_pct, mc["metrics"]["VI-04"]["bands"])
            crits.append(CriterionIn(id="C7", value=f"{inp.mandate_fit_pct:g}%; ceiling 100%", pf=c7f, pc=4, coverage=inp.mandate_fit_pct / 100))
        else:
            crits.append(CriterionIn(id="C7", coverage=0))
        crits.append(vi_crit("C8", [c for c in cl if c.operational]))
        lfc = inp.people.get("composite")
        crits.append(CriterionIn(id="C9", value=inp.people.get("verdict", "—"), pf=lfc, pc=lfc, coverage=1.0 if lfc is not None else 0))
        rg = inp.market.get("rg_c")
        crits.append(CriterionIn(id="C10", value=f"RG-02 {inp.market.get('rg02')}% · RG-03 {inp.market.get('rg03')}%", pf=rg, pc=rg, coverage=1.0 if rg is not None else 0))
        tech = [c for c in cl if c.kind == "tech"]
        t = vi_crit("C11", tech)
        if tech and t.pf is not None:
            tc01f, tc01c = t.pf, t.pc
            if inp.tech_led:
                tc02 = metric_points("TC-02", inp.engineering_share_pct, mc)
                t.pf, t.pc = rdown((tc01f + (tc02 or 0)) / 2), rdown((tc01c + (tc02 if tc02 is not None else 4)) / 2)
                t.asks = [{**a, "new_pf": rdown((a["new_pf"] + (tc02 or 0)) / 2), "closes": "C11"} for a in t.asks]
                t.coverage = round((t.coverage * len(tech) + (1 if tc02 is not None else 0)) / (len(tech) + 1), 4)
                t.value = f"TC-01 {tc01f}/{tc01c} · TC-02 {inp.engineering_share_pct}% → {tc02}"
        crits.append(t)
        # gates
        critical_false = [c for c in cl if c.critical and vmap[c.claim_id].cls == "FALSE" and vmap[c.claim_id].code in ("F1", "F4")]
        kmp_false = [c for c in cl if c.kind == "bio" and vmap[c.claim_id].cls == "FALSE"]
        sev = {"possible": "HOLD", "confirmed": "REJECT"}
        gates = [Gate(id="G1", passed=inp.entity_score >= 0.85, outcome="HOLD", detail=f"entity match {inp.entity_score:.2f}"),
                 Gate(id="G2", passed=inp.legal_status == "active", outcome="HOLD" if inp.legal_status == "source_down" else "REJECT", detail=inp.legal_status),
                 Gate(id="G3", passed=inp.sanctions == "none", outcome=sev.get(inp.sanctions, "HOLD"), detail=f"sanctions: {inp.sanctions}"),
                 Gate(id="G4", passed=not critical_false, outcome="REJECT", detail="no critical FALSE" if not critical_false else f"critical FALSE: {critical_false[0].text}"),
                 Gate(id="G5", passed=inp.in_mandate, outcome="REJECT", detail="in mandate" if inp.in_mandate else "out of mandate"),
                 Gate(id="G6", passed=inp.financial.get("accepted", True), outcome="HOLD", detail="statements consistent" if inp.financial.get("accepted", True) else "FSV-01…03 failed")]
        d0 = decide(inp.profile, crits, gates, inp.requirements, cfg, ctx.config["mitigants"]["mitigants"], ctx.config.shas.get("rubric", ""))
        gates.append(Gate(id="G7", passed=d0.coverage >= 60, outcome="HOLD", detail=f"coverage {d0.coverage}%"))
        gates.append(Gate(id="G8", passed=not kmp_false, outcome="HOLD", detail="no false credential" if not kmp_false else f"false credential: {kmp_false[0].text}"))
        reqs = dict(inp.requirements)
        extra = list(inp.extra_requirements)
        pillars = inp.financial.get("pillars", {})
        for name, key in (("solvency_pillar", "solvency"), ("cash_quality_pillar", "cash_quality")):
            if name in reqs:
                v = pillars.get(key)
                extra.append({"name": name, "min": reqs.pop(name), "status": "open" if v is None else ("met" if v >= inp.requirements[name] else "unmet"), "value": v})
        if "earnings_quality_flag" in reqs:
            reqs.pop("earnings_quality_flag")
            fl = any("earnings-quality" in f for f in inp.financial.get("flags", []))
            extra.append({"name": "no earnings-quality flag", "min": "none", "status": "unmet" if fl else ("met" if inp.financial.get("grade") else "open"), "value": "flag" if fl else "none"})
        reqs = {k: v for k, v in reqs.items() if isinstance(v, (int, float))}
        return decide(inp.profile, crits, gates, reqs, cfg, ctx.config["mitigants"]["mitigants"], ctx.config.shas.get("rubric", ""), extra)


def r1_score(s: dict[str, tuple[float | None, float | None]], weights: dict, risk_flag: bool, req_statuses: list[str]) -> dict:
    """R1 from S1…S9 (pf, pc); None floor → 0, None ceiling → 4."""
    table = {k: (weights[k]["weight"], 0 if v[0] is None else v[0], 4 if v[1] is None else v[1]) for k, v in s.items()}
    for k in weights:
        table.setdefault(k, (weights[k]["weight"], 0, 4))
    return {**r1(table, risk_flag, req_statuses), "criteria": {k: {"weight": w, "pf": pf, "pc": pc} for k, (w, pf, pc) in table.items()}}


AGENT = DecisionEngine()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
