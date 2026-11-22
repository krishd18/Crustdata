"""A7 Verdict Engine (STANDARDS §2.2 first-match procedure; ARCHITECTURE §11 rules R-01…R-21; config/verdicts.yaml).
Safety: FALSE needs a resolved entity AND a quote-locked contradicting passage from a higher authority; never from
T2 counts, a single media report, or absence from a list."""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from ..core import normalize
from ..core.types import Claim, Evidence, Verdict
from .base import BaseAgent, cli

VOLATILE = {"headcount", "revenue", "ebitda", "profit", "locations", "footprint", "gst_status", "fleet_size",
            "warehouse_area", "certification", "growth_rate", "headcount_growth"}
NOT_CHECKED = {"projection": "X1", "opinion": "X2", "out_of_scope": "X3"}
FIN = {"revenue", "ebitda", "profit", "growth_rate"}
EVENT = {"funding", "customer", "contract_win", "facility", "award", "leadership_bio", "appointment", "tech", "premise"}


class VerdictInput(BaseModel):
    claims: list[Claim]
    evidence: list[Evidence] = Field(default_factory=list)
    by_claim: dict[str, list[str]] = Field(default_factory=dict)
    unavailable: list[dict] = Field(default_factory=list)   # [{claim_id, code: N2|N5|N6, source, reason}]
    entity_score: float = 1.0
    entity_status: str = "resolved"
    missing_docs: dict[str, str] = Field(default_factory=dict)  # claim type → document (asks.yaml)


class ClaimVerdicts(BaseModel):
    verdicts: list[Verdict]
    counts_by_class: dict[str, int]


def _num(v) -> float | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, dict):
        return _num(v.get("min", v.get("value")))
    val, _ = normalize.parse_amount(str(v))
    return val


def _cur(v) -> str | None:
    return normalize.parse_amount(str(v))[1] if isinstance(v, str) else None


class VerdictEngine(BaseAgent[VerdictInput, ClaimVerdicts]):
    name, input_model, output_model = "a07_verdict", VerdictInput, ClaimVerdicts

    def run(self, inp: VerdictInput, ctx) -> ClaimVerdicts:
        cfg = ctx.config["verdicts"]
        today = ctx.clock.today()
        evmap = {e.evidence_id: e for e in inp.evidence}
        out = []
        for c in inp.claims:
            evs = [evmap[i] for i in inp.by_claim.get(c.claim_id, []) if i in evmap]
            una = [u for u in inp.unavailable if u.get("claim_id") == c.claim_id]
            out.append(self.classify(c, evs, una, inp, cfg, today))
        counts: dict[str, int] = {}
        for v in out:
            counts[v.cls] = counts.get(v.cls, 0) + 1
        return ClaimVerdicts(verdicts=out, counts_by_class=counts)

    # ------------------------------------------------------------------
    def relation(self, c: Claim, e: Evidence, tol: dict) -> str:
        """Deterministic comparison when both sides are comparable; else the collector's relation."""
        if e.kind in ("lower_bound", "band", "earliest", "profile", "self") or e.relation == "context":
            return e.relation
        cv, ev = _num(c.value), _num(e.value)
        if cv is None or ev is None:
            if isinstance(c.value, str) and isinstance(e.value, str) and c.type in ("identity", "registered_address", "gst_status"):
                return "supports" if normalize.company_name(c.value) == normalize.company_name(e.value) else "contradicts"
            return e.relation
        cc, ec = _cur(c.value), _cur(e.value)
        if cc and ec and cc != ec:
            return "context"          # H9b: never compare ₹ with USD
        pct = tol.get("money_pct", 2.0) if c.type in FIN else tol.get("count_pct", 5.0)
        if c.type in ("incorporation_date", "operating_since"):
            return "supports" if abs(cv - ev) <= tol.get("since_year", 1) else "contradicts"
        return "supports" if normalize.within(cv, ev, pct) else "contradicts"

    def classify(self, c: Claim, evs: list[Evidence], una: list[dict], inp: VerdictInput, cfg: dict, today: date) -> Verdict:
        cr = cfg["classes"]

        def V(cls: str, code: str, rule: str, ids: list[str] | None = None, missing: str | None = None, note: str = "") -> Verdict:
            fl, ce = (cr[cls]["credit"] or [None, None])
            return Verdict(claim_id=c.claim_id, cls=cls, code=code, evidence_ids=ids or [], missing=missing,
                           credit_floor=fl, credit_ceiling=ce, rule_id=rule, note=note)

        missing_doc = inp.missing_docs.get(c.type) or f"an independent record for '{c.type}'"
        # 1 · not checkable
        if c.type in NOT_CHECKED:
            return V("NOT_CHECKED", NOT_CHECKED[c.type], "R-15")
        # 2 · entity
        if inp.entity_status != "resolved" or inp.entity_score < 0.85:
            return V("NOT_VERIFIABLE", "N4", "R-14", missing="entity resolution (CIN/GSTIN or domain)")
        tol = cfg.get("tolerances", {})
        rel = {e.evidence_id: self.relation(c, e, tol) for e in evs}
        sup = [e for e in evs if rel[e.evidence_id] == "supports"]
        con = [e for e in evs if rel[e.evidence_id] == "contradicts"]
        # media tier D / press release is self-published wherever it appears (R-21)
        def is_selfpub(e: Evidence) -> bool:
            return e.tier == "T4" or e.media_tier == "D"
        media_own = lambda es, t: [e for e in es if e.tier == "T1-M" and e.media_tier == t and not e.attributed_to_company_quote and not is_selfpub(e)]
        # 3 · conflicts among independent reliable sources
        t1s, t1c = [e for e in sup if e.tier == "T1"], [e for e in con if e.tier == "T1"]
        if t1s and t1c:
            return V("NOT_VERIFIABLE", "N3", "R-13", [e.evidence_id for e in t1s + t1c], missing="reconciliation of conflicting public records")
        ma_s, ma_c = media_own(sup, "A"), media_own(con, "A")
        if ma_s and ma_c and not t1s and not t1c:
            return V("NOT_VERIFIABLE", "N3", "R-13", [e.evidence_id for e in ma_s + ma_c], missing="a primary record settling the conflicting reports")
        # 4 · contradicted by higher authority (premise → F3)
        if t1c and not c.kind == "premise":
            return V("FALSE", "F1", "R-02", [e.evidence_id for e in t1c])
        if t1c and c.kind == "premise":
            return V("FALSE", "F3", "R-16", [e.evidence_id for e in t1c])
        hi_t3 = [e for e in con if e.tier == "T3" and e.kind == "field" and "audited" in (e.source or "")]
        if hi_t3 and not sup:
            return V("FALSE", "F2", "R-10", [e.evidence_id for e in hi_t3])
        mc = media_own(con, "A") + media_own(con, "B")
        if len({e.url_or_endpoint for e in mc}) >= 2 or (media_own(con, "A") and t1s):
            return V("FALSE", "F3" if c.kind == "premise" else "F4", "R-20", [e.evidence_id for e in mc])
        if mc:   # single media contradiction → never FALSE
            return V("NOT_VERIFIABLE", "N3", "R-20", [e.evidence_id for e in mc], missing="a second independent report or a T1 record")
        # 5 · verified
        fresh = lambda e: self._fresh(e, c, cfg, today)
        if t1s:
            best = t1s[0]
            if not fresh(best):
                return V("OUTDATED", "O1", "R-11", [best.evidence_id], note=f"record date {best.record_date}")
            if best.kind == "lower_bound":
                return V("VERIFIED", "V4", "R-03", [e.evidence_id for e in t1s])
            if best.kind == "earliest":
                return V("VERIFIED", "V3", "R-08", [e.evidence_id for e in t1s])
            if best.source.startswith(("registry.aoc4", "exchange")):
                return V("VERIFIED", "V2", "R-09", [e.evidence_id for e in t1s])
            return V("VERIFIED", "V1", "R-01", [e.evidence_id for e in t1s])
        msa, msb = media_own(sup, "A"), media_own(sup, "B")
        indep_b = len({e.url_or_endpoint for e in msb})
        if (msa or indep_b >= 2) and (c.type not in FIN):
            best = (msa or msb)[0]
            if fresh(best):
                return V("VERIFIED", "V5", "R-17", [e.evidence_id for e in msa + msb])
            return V("OUTDATED", "O1", "R-11", [best.evidence_id], note=f"record date {best.record_date}")
        # 6 · partially verified
        comp = [e for e in sup if e.tier == "T1-M" and e.attributed_to_company_quote and e.media_tier in ("A", "B")]
        if comp:
            return V("PARTIALLY_VERIFIED", "P4", "R-18", [e.evidence_id for e in comp])
        t2 = [e for e in sup if e.tier == "T2"]
        if t2:
            best = t2[0]
            if not fresh(best):
                return V("OUTDATED", "O1", "R-11", [best.evidence_id], note=f"record date {best.record_date}")
            code, rule = {"profile": ("P5", "R-19"), "band": ("P2", "R-06")}.get(best.kind, ("P1", "R-04"))
            return V("PARTIALLY_VERIFIED", code, rule, [e.evidence_id for e in t2])
        if c.value and isinstance(c.value, dict) and c.value.get("parts_verified"):
            return V("PARTIALLY_VERIFIED", "P3", "R-07", [e.evidence_id for e in sup], note=f"{c.value['parts_verified']} verified")
        # lower bound below claim (T2/T1 counts) → U3, never FALSE
        lb = [e for e in evs if e.kind == "lower_bound" and rel[e.evidence_id] != "supports"]
        if lb or any(e.tier == "T2" for e in con):
            ids = [e.evidence_id for e in lb] + [e.evidence_id for e in con if e.tier == "T2"]
            return V("UNVERIFIED", "U3", "R-05", ids, missing=missing_doc, note="independent lower bound below the claim")
        # 7/8 · self-reported
        t3 = [e for e in sup if e.tier == "T3"]
        if t3:
            return V("UNVERIFIED", "U1", "R-12", [e.evidence_id for e in t3], missing=missing_doc)
        selfp = [e for e in sup if is_selfpub(e)]
        if not selfp and c.type in cfg.get("no_public_source_types", []):
            return V("NOT_VERIFIABLE", "N1", "R-14", missing=missing_doc)
        if selfp or c.kind in ("business", "bio", "tech") and not evs and not una:
            return V("UNVERIFIED", "U2", "R-21" if any(e.media_tier == "D" for e in selfp) else "R-12",
                     [e.evidence_id for e in selfp], missing=missing_doc)
        # 9 · nothing settles it
        if c.kind == "premise":
            return V("NOT_VERIFIABLE", "N7", "R-16", missing="any record of the premise")
        if una:
            u = una[0]
            return V("NOT_VERIFIABLE", u.get("code", "N2"), "R-14", missing=f"{u.get('source', 'source')} unavailable: {u.get('reason', '')}".strip())
        return V("NOT_VERIFIABLE", "N1", "R-14", missing=missing_doc)

    @staticmethod
    def _fresh(e: Evidence, c: Claim, cfg: dict, today: date) -> bool:
        if c.type not in VOLATILE or not e.record_date:
            return True
        f = cfg.get("freshness_days", {})
        days = {"T1": f.get("registry", 90) if "aoc4" not in e.source else f.get("financial_statements_after_fy_end", 548),
                "T1-M": f.get("media_event", 730), "T2": f.get("crustdata", 60)}.get(e.tier, 10_000)
        try:
            d = date.fromisoformat(str(e.record_date)[:10])
        except ValueError:
            return True
        return (today - d).days <= days


AGENT = VerdictEngine()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
