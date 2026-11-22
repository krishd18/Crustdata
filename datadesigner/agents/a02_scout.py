"""A2 Scout (ARCHITECTURE §6; plan §5.3A): validates filter values with autocomplete, compiles filters (never
'>=', always '=>'), runs the search streams, paginates, dedups by id/domain with the lookalike guard, pre-scores
and enriches within budget (≤ 25 per call). Growth fields are filterable but not sortable → client-side sort."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from ..core import normalize
from ..core.errors import BudgetExhausted, SourceUnavailable
from .a01_query_reasoner import ResearchPlan
from .base import BaseAgent, cli

SEARCH_FIELDS = ["crustdata_company_id", "basic_info.name", "basic_info.primary_domain", "basic_info.year_founded",
                 "headcount.total", "headcount.growth_percent", "locations.headquarters", "locations.country",
                 ]
ENRICH = ["basic_info", "headcount", "people", "taxonomy", "locations"]


class ScoutInput(BaseModel):
    plan: ResearchPlan
    guard_confirmed: bool = True
    enrich_top: int = 25
    search_limit: int = 60


class Candidate(BaseModel):
    crustdata_company_id: int
    name: str
    domain: str | None = None
    fields: dict = Field(default_factory=dict)
    search_sha: str = ""
    enrich: dict | None = None
    enrich_sha: str = ""
    stream_ids: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class CandidateSet(BaseModel):
    candidates: list[Candidate] = Field(default_factory=list)
    funnel: dict[str, Any] = Field(default_factory=dict)
    excluded: list[dict] = Field(default_factory=list)
    requests: list[dict] = Field(default_factory=list)
    values: dict[str, list[str]] = Field(default_factory=dict)
    unavailable: list[dict] = Field(default_factory=list)
    total_count: int | None = None


def dedup(cands: list[Candidate]) -> tuple[list[Candidate], list[dict]]:
    """Dedup by id, then by domain; names ≥ 90 similar but different domains are kept apart and flagged."""
    out, seen_id, seen_dom, dropped = [], set(), {}, []
    for c in cands:
        d = (c.domain or "").lower().removeprefix("www.")
        if c.crustdata_company_id in seen_id:
            dropped.append({"id": c.crustdata_company_id, "reason": "duplicate id"})
            continue
        if d and d in seen_dom:
            dropped.append({"id": c.crustdata_company_id, "reason": f"duplicate domain {d} (same as {seen_dom[d]})"})
            continue
        for o in out:
            if fuzz.token_sort_ratio(normalize.company_name(o.name), normalize.company_name(c.name)) >= 90 and (o.domain or "") != (c.domain or ""):
                c.flags.append(f"lookalike of {o.name} — kept separate (different domain)")
        seen_id.add(c.crustdata_company_id)
        if d:
            seen_dom[d] = c.name
        out.append(c)
    return out, dropped


def growth(fields: dict, months: int) -> float | None:
    g = (fields.get("headcount") or {}).get("growth_percent") or {}
    key = {1: ("1m", "mom"), 3: ("3m", "qoq"), 6: ("6m", "six_months"), 12: ("12m", "yoy")}[months]
    for k in key:
        if g.get(k) is not None:
            return float(g[k])
    return None


class Scout(BaseAgent[ScoutInput, CandidateSet]):
    name, input_model, output_model = "a02_scout", ScoutInput, CandidateSet

    def industry_values(self, ctx, plan: ResearchPlan) -> list[str]:
        terms = ctx.config["terms"]["terms"]
        if plan.sector == "b2b_software":
            seeds = terms["b2b_software"]["industry_values_seed"]
            got = ctx.crustdata.company_autocomplete("taxonomy.professional_network_industry", "software", 20)
            vals = [v for v in seeds if v in got] or [v for v in got if v.lower() == "software development"]
            return vals
        if plan.sector == "logistic":
            got = []
            for q in ("logist", "transport", "warehous", "freight"):
                got += ctx.crustdata.company_autocomplete("taxonomy.professional_network_industry", q, 10)
            return sorted({v for v in got if any(k in v.lower() for k in ("logist", "transport", "warehous", "freight", "truck"))})
        return []

    def fintech_categories(self, ctx, plan: ResearchPlan) -> list[str]:
        f = ctx.config["terms"]["terms"]["fintech"]
        qs = [w[:5] for w in plan.sector_words] or f["category_queries"]
        out: list[str] = []
        for q in qs:
            for v in ctx.crustdata.company_autocomplete("taxonomy.categories", q, 50):
                lv = v.lower()
                if any(k in lv for k in ("fintech", "financial technology", "payment", "lending", "loan", "insurtech", "wealth", "banking", "credit", "finance")) and v not in out:
                    out.append(v)
        return out

    def run(self, inp: ScoutInput, ctx) -> CandidateSet:
        p = inp.plan
        cs = CandidateSet()
        conds: list[dict] = []
        if p.country:
            conds.append({"field": "locations.country", "type": "in", "value": [p.country]})
        if p.sector in ("b2b_software", "logistic"):
            vals = self.industry_values(ctx, p)
            cs.values["taxonomy.professional_network_industry"] = vals
            if vals:
                conds.append({"field": "taxonomy.professional_network_industry", "type": "in", "value": vals})
        elif p.sector == "fintech":
            cats = self.fintech_categories(ctx, p)
            cs.values["taxonomy.categories"] = cats
            seeds = ctx.config["terms"]["terms"]["fintech"]["industry_values_seed"]
            ors = [{"field": "taxonomy.professional_network_industry", "type": "in", "value": seeds}]
            if cats:
                ors.insert(0, {"field": "taxonomy.categories", "type": "in", "value": cats})
            conds.append({"op": "or", "conditions": ors})
        if p.year_founded_min:
            conds.append({"field": "basic_info.year_founded", "type": "=>", "value": p.year_founded_min})
        if p.growth_months and p.growth_pct is not None:
            conds.append({"field": f"headcount.growth_percent.{p.growth_months}m", "type": "=>", "value": p.growth_pct})
        filters = {"op": "and", "conditions": conds}
        limit = inp.search_limit if p.family == "FIND_LIST" else ctx.config["limits"].get("research_qa_search_limit", 300)
        fields = SEARCH_FIELDS if p.family == "FIND_LIST" else ["crustdata_company_id", "basic_info.name", "basic_info.primary_domain"]
        sorts = [{"field": "headcount.total", "order": "desc"}]
        cs.requests.append({"endpoint": "company/search", "filters": filters, "limit": limit})
        try:
            r = ctx.crustdata.company_search(filters, fields, sorts, limit)
        except SourceUnavailable as e:
            cs.unavailable.append({"source": "crustdata.company_search", "reason": e.reason, "code": "N2"})
            return cs
        except BudgetExhausted as e:
            cs.unavailable.append({"source": "crustdata.company_search", "reason": str(e), "code": "N5"})
            return cs
        rows = r.body.get("companies", []) if isinstance(r.body, dict) else []
        cs.total_count = r.body.get("total_count") if isinstance(r.body, dict) else None
        cands = [Candidate(crustdata_company_id=c["crustdata_company_id"], name=(c.get("basic_info") or {}).get("name", "?"),
                           domain=(c.get("basic_info") or {}).get("primary_domain"), fields=c, search_sha=r.sha, stream_ids=["A"])
                 for c in rows if c.get("crustdata_company_id")]
        cands, dropped = dedup(cands)
        cs.excluded += dropped
        cs.funnel = {"found": len(rows), "total_count": cs.total_count, "after_dedup": len(cands)}
        if p.family == "FIND_LIST" and p.growth_months:
            cands.sort(key=lambda c: (-(growth(c.fields, p.growth_months) or -1e9), c.name))
            if p.headcount_guard and inp.guard_confirmed:
                kept = []
                for c in cands:
                    tot = (c.fields.get("headcount") or {}).get("total")
                    if tot is not None and tot < p.headcount_guard:
                        cs.excluded.append({"id": c.crustdata_company_id, "name": c.name, "criterion": "headcount_guard",
                                            "reason": f"headcount {tot} < {p.headcount_guard} (guard you confirmed)",
                                            "growth": growth(c.fields, p.growth_months), "search_sha": c.search_sha})
                    else:
                        kept.append(c)
                cs.funnel["after_guard"] = len(kept)
                cands = kept
            top = cands[: inp.enrich_top]
            if top:
                try:
                    er = ctx.crustdata.company_enrich([c.crustdata_company_id for c in top], ENRICH)
                    by_id = {}
                    for item in er.body if isinstance(er.body, list) else []:
                        for m in item.get("matches", [])[:1]:
                            cd = m.get("company_data", {})
                            by_id[cd.get("crustdata_company_id")] = cd
                    for c in top:
                        c.enrich, c.enrich_sha = by_id.get(c.crustdata_company_id), er.sha
                    cs.funnel["enriched"] = sum(1 for c in top if c.enrich)
                except (SourceUnavailable, BudgetExhausted) as e:
                    cs.unavailable.append({"source": "crustdata.company_enrich", "reason": str(e), "code": "N5" if isinstance(e, BudgetExhausted) else "N2"})
            cs.candidates = top
        else:
            cs.candidates = cands
        return cs


AGENT = Scout()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
