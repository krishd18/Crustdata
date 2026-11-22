"""A11 Research Analyst (STANDARDS §2.3, §2.4, §6.8; plan §5.3A). FIND_LIST and RESEARCH_QA execution: every hard
criterion is a classed claim; a row is kept only if every hard criterion is ✅/🟢 on quote-locked evidence; never
padded. Classifiers (B2B, fintech) return a label + verbatim passage that must quote-lock, 'ambiguous' → excluded and
listed. Inferences use the Inference Strength rule and are always labelled."""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..core import normalize
from ..core.claude import load_prompt, wrap_untrusted
from ..core.errors import BudgetExhausted, ContractError, ParseFailed, SecretMissing, SourceUnavailable
from ..core.quote_lock import get_path, lock, lock_field


def lock_segments(passage: str, text: str) -> tuple[int | None, str]:
    """Lock a passage; if it contains '...'/'…' elisions every segment must lock verbatim. Returns (offset, locked passage)."""
    off = lock(passage, text)
    if off is not None:
        return off, passage
    segs = [s.strip() for s in re.split(r"\.\.\.|…", passage or "") if len(s.strip()) >= 12]
    if len(segs) >= 1 and all(lock(s, text) is not None for s in segs):
        best = max(segs, key=len)
        return lock(best, text), best
    return None, passage
from ..core.types import BADGE, Claim, Evidence, Inference
from ..rubric.research import inference_strength, r3
from .a01_query_reasoner import ResearchPlan
from .a02_scout import CandidateSet, growth
from .a07_verdict import VerdictEngine, VerdictInput
from .base import BaseAgent, cli

VE = VerdictEngine()


class Classification(BaseModel):
    label: str
    confidence: Literal["high", "medium", "low"]
    passage: str | None
    source: str | None


class ResearchInput(BaseModel):
    plan: ResearchPlan
    candidates: CandidateSet
    use_llm: bool = True


class ResearchAnswer(BaseModel):
    family: str
    status: str
    confidence: str
    answer: str
    rows: list[dict] = Field(default_factory=list)
    excluded_near_misses: list[dict] = Field(default_factory=list)
    inferences: list[Inference] = Field(default_factory=list)
    premise_checks: list[dict] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    r3: dict = Field(default_factory=dict)
    evidence: list[Evidence] = Field(default_factory=list)
    method: dict = Field(default_factory=dict)


def _v(verdict) -> dict:
    return {"cls": verdict.cls, "code": verdict.code, "badge": BADGE[verdict.cls], "evidence_ids": verdict.evidence_ids,
            "missing": verdict.missing, "note": verdict.note}


class ResearchAnalyst(BaseAgent[ResearchInput, ResearchAnswer]):
    name, input_model, output_model = "a11_research", ResearchInput, ResearchAnswer
    deterministic = False

    def run(self, inp: ResearchInput, ctx) -> ResearchAnswer:
        if inp.plan.family == "FIND_LIST":
            return self.find_list(inp, ctx)
        return self.research_qa(inp, ctx)

    # ------------------------------------------------------------------ helpers
    def field_ev(self, ctx, sha: str, path: str, value: Any, record_date: str | None, claim_id: str, source: str,
                 relation: str = "supports", kind: str = "field", tier: str = "T2") -> Evidence | None:
        blob = ctx.stores.blob(sha)
        if blob is None or not lock_field(path, value, blob):
            return None
        return ctx.evidence(source=source, url_or_endpoint=source, passage_or_field=path, value=value, record_date=record_date,
                            content_sha256=sha, tier=tier, relation=relation, kind=kind, claim_id=claim_id)

    def classify(self, ctx, claim: Claim, evs: list[Evidence]):
        return VE.classify(claim, evs, [], VerdictInput(claims=[claim]), ctx.config["verdicts"], ctx.clock.today())

    def classifier(self, ctx, kind: str, name: str, description: str, extra: dict) -> Classification | None:
        terms = ctx.config["terms"]["terms"]
        if kind == "b2b":
            definition = terms["b2b_software"]["intent"] + ": the company sells software or software-enabled services to businesses (B2B), not mainly to consumers."
            labels, excl = "b2b|b2c", "consumer apps, marketplaces for consumers, education/training sold to individuals"
        else:
            definition = terms["fintech"]["intent"]
            labels, excl = "fintech|not_fintech", terms["fintech"]["exclude"]
        ev = json.dumps([{"source": "crustdata.company_enrich.basic_info.description", "tier": "T2", "text": description},
                         {"source": "crustdata.taxonomy", "tier": "T2", "text": json.dumps(extra, ensure_ascii=False)}], ensure_ascii=False)
        user = (f"DEFINITION ({labels}): {definition}\nEXCLUSIONS: {excl}\nCOMPANY: {name}\n"
                f"EVIDENCE: {wrap_untrusted(ev, 'crustdata', ctx.config['llm'].get('untrusted_wrapper'))}\n"
                f"Return label as one of: {labels}|ambiguous.")
        try:
            out, _ = ctx.claude.generate_json("classify", load_prompt("classifier"), user, Classification, task=f"classifier:{kind}")
            return out
        except (ParseFailed, SecretMissing) as e:
            ctx.log.warning("a11.classifier_failed", company=name, error=str(e)[:120])
            return None

    def enrich_doc(self, ctx, sha: str, cid: int) -> tuple[str, dict] | tuple[None, None]:
        blob = ctx.stores.blob(sha)
        if not blob:
            return None, None
        body = json.loads(blob)
        for i, item in enumerate(body if isinstance(body, list) else []):
            for j, m in enumerate(item.get("matches", [])[:1]):
                if m.get("company_data", {}).get("crustdata_company_id") == cid:
                    return f"{i}.matches.{j}.company_data", m["company_data"]
        return None, None

    # ------------------------------------------------------------------ FIND_LIST
    def find_list(self, inp: ResearchInput, ctx) -> ResearchAnswer:
        p, cs = inp.plan, inp.candidates
        rows, near, evs, notes = [], [], [], []
        attrs_req = attrs_classed = attrs_supported = facts = facts_t1 = 0
        gkey = {1: "mom", 3: "qoq", 6: "six_months", 12: "yoy"}.get(p.growth_months or 6, "six_months")
        for x in cs.excluded:
            if x.get("criterion"):
                near.append({"name": x.get("name"), "criterion": x["criterion"], "reason": x["reason"]})
        unavailable = list(cs.unavailable)
        for c in cs.candidates:
            if p.n_requested and len(rows) >= p.n_requested:
                break
            if not c.enrich:
                near.append({"name": c.name, "criterion": "enrichment", "reason": "not enriched (budget/source) — not checked"})
                continue
            base, cd = self.enrich_doc(ctx, c.enrich_sha, c.crustdata_company_id)
            if not base:
                continue
            bi, hc = cd.get("basic_info", {}), cd.get("headcount", {})
            ts = hc.get("timeseries") or []
            rec = ts[-1]["date"] if ts else None
            crit: dict[str, dict] = {}
            row_evs: list[Evidence] = []

            def criterion(cid: str, path: str, value: Any, ok: bool, text: str):
                cl = Claim(claim_id=f"{c.crustdata_company_id}:{cid}", kind="criterion", type=cid, text=text)
                e = self.field_ev(ctx, c.enrich_sha, f"{base}.{path}", value, rec, cl.claim_id, "crustdata.company_enrich",
                                  relation="supports" if ok else "contradicts")
                if e:
                    row_evs.append(e)
                if not ok and e is not None:   # T2 says it fails → criterion fails (never FALSE: hard filter only)
                    crit[cid] = {"pass": "fail", "value": value, "cls": "UNVERIFIED", "badge": "🟡", "code": "U3", "evidence_ids": [e.evidence_id]}
                    return
                v = self.classify(ctx, cl, [e] if e else [])
                crit[cid] = {"pass": "pass" if v.cls in ("VERIFIED", "PARTIALLY_VERIFIED") else "unknown", "value": value, **_v(v)}

            country = (cd.get("locations") or {}).get("country")
            if p.country:
                criterion("country", "locations.country", country, country == p.country, f"HQ country {p.country}")
            yf = bi.get("year_founded")
            if p.year_founded_min:
                criterion("founded", "basic_info.year_founded", yf, yf is not None and yf >= p.year_founded_min, f"founded ≥ {p.year_founded_min}")
            gv = (hc.get("growth_percent") or {}).get(gkey)
            if p.growth_months:
                criterion("growth", f"headcount.growth_percent.{gkey}", gv, gv is not None and gv >= (p.growth_pct or 0),
                          f"{p.growth_months}-month headcount growth ≥ {p.growth_pct:g}%")
            tot = hc.get("total")
            if p.headcount_guard:
                criterion("headcount_guard", "headcount.total", tot, tot is not None and tot >= p.headcount_guard, f"headcount ≥ {p.headcount_guard}")
            ind = (cd.get("taxonomy") or {}).get("professional_network_industry")
            vals = cs.values.get("taxonomy.professional_network_industry") or []
            if vals:
                criterion("industry", "taxonomy.professional_network_industry", ind, ind in vals, f"industry in {vals}")
            # founded-year cross-check (Wayback first capture) — non-critical; unavailable is noted, never a silent pass
            if p.year_founded_min and c.domain and crit.get("founded", {}).get("pass") == "pass":
                wb = self.wayback_first(ctx, c.domain)
                if wb is None:
                    crit["founded"]["note"] = "cross-check unavailable (Wayback not reachable)"
                elif wb < p.year_founded_min - 1:
                    crit["founded"] = {**crit["founded"], "pass": "fail", "cls": "NOT_VERIFIABLE", "badge": "⚪", "code": "N3",
                                       "note": f"conflict: profile says {yf}, domain first captured {wb}"}
            failing = [k for k, v in crit.items() if v["pass"] != "pass"]
            if failing:
                k = failing[0]
                near.append({"name": c.name, "criterion": k, "reason": crit[k].get("note") or f"{k} = {crit[k]['value']}"})
                continue
            # B2B / sector classifier (hard)
            if p.sector == "b2b_software":
                desc = bi.get("description") or ""
                ok_desc = lock_field(f"{base}.basic_info.description", desc, ctx.stores.blob(c.enrich_sha)) if desc else False
                cls = self.classifier(ctx, "b2b", c.name, desc, {"industry": ind, "categories": (cd.get("taxonomy") or {}).get("categories", [])[:12]}) if (desc and inp.use_llm) else None
                if cls is None:
                    near.append({"name": c.name, "criterion": "b2b", "reason": "B2B classification could not be made (no description or classifier unavailable)"})
                    continue
                psha = ctx.stores.put_blob(desc, "text/plain")
                off, locked_p = lock_segments(cls.passage or "", desc) if ok_desc else (None, cls.passage)
                cls.passage = locked_p
                if cls.label != "b2b" or off is None:
                    why = "ambiguous" if cls.label == "ambiguous" else ("B2C" if cls.label == "b2c" else "passage did not quote-lock")
                    near.append({"name": c.name, "criterion": "b2b", "reason": f"{why}: \"{(cls.passage or '')[:120]}\""})
                    continue
                e = ctx.evidence(source="crustdata.company_enrich.basic_info.description", url_or_endpoint=f"crustdata:{c.crustdata_company_id}",
                                 passage_or_field=cls.passage, value="b2b", record_date=rec, content_sha256=psha, tier="T2", kind="field",
                                 claim_id=f"{c.crustdata_company_id}:b2b", offset=off)
                row_evs.append(e)
                crit["b2b"] = {"pass": "pass", "value": "B2B (self-described)", "cls": "PARTIALLY_VERIFIED", "badge": "🟢", "code": "P1",
                               "evidence_ids": [e.evidence_id], "passage": cls.passage, "confidence": cls.confidence}
            # attributes
            row: dict = {"entity": {"crustdata_company_id": c.crustdata_company_id, "name": c.name, "domain": c.domain,
                                    "hq": (cd.get("locations") or {}).get("headquarters")},
                         "criteria": crit, "attributes": {}, "record_date": rec, "flags": c.flags}
            ga = (hc.get("growth_absolute") or {}).get(gkey)
            row["attributes"]["headcount"] = {"now": tot, "before": (tot - ga) if (tot is not None and ga is not None) else None,
                                              "growth_pct": round(gv, 1) if gv is not None else None,
                                              "label": f"per Crustdata headcount (profiles), record date {rec}"}
            row["attributes"]["founded"] = {"value": yf, **{k: crit.get("founded", {}).get(k) for k in ("cls", "badge", "code", "evidence_ids", "note")}}
            if "founders" in p.attributes or "prior_roles" in p.attributes:
                founders = []
                fl = (cd.get("people") or {}).get("founders") or []
                attrs_req += 1
                if not fl:
                    cl = Claim(claim_id=f"{c.crustdata_company_id}:founders", kind="criterion", type="founders", text="founders")
                    v = VE.classify(cl, [], [], VerdictInput(claims=[cl]), {**ctx.config["verdicts"], "no_public_source_types": ["founders"]}, ctx.clock.today())
                    founders_v = {**_v(v), "missing": "founder record (Crustdata people / MCA directors)"}
                    attrs_classed += 1
                    row["attributes"]["founders"] = {"value": [], **founders_v}
                else:
                    attrs_classed += 1
                    attrs_supported += 1
                for fi, f in enumerate(fl[:4]):
                    fname = (f.get("basic_profile") or {}).get("name")
                    fp = f"{base}.people.founders.{fi}.basic_profile.name"
                    e = self.field_ev(ctx, c.enrich_sha, fp, fname, (f.get("updated_at") or "")[:10] or rec, f"{c.crustdata_company_id}:founder:{fi}", "crustdata.company_enrich.people")
                    fv = self.classify(ctx, Claim(claim_id=f"{c.crustdata_company_id}:founder:{fi}", kind="criterion", type="founders", text=f"founder {fname}"), [e] if e else [])
                    if e:
                        row_evs.append(e)
                    entry = {"name": fname, "title": (f.get("basic_profile") or {}).get("current_title"), **_v(fv), "prior_roles": []}
                    if "prior_roles" in p.attributes:
                        attrs_req += 1
                        past = ((f.get("experience") or {}).get("employment_details") or {}).get("past") or []
                        past = sorted(past, key=lambda r: r.get("employee_end_date") or "", reverse=True)
                        if not past:
                            attrs_classed += 1
                            entry["prior_roles_verdict"] = {"cls": "NOT_VERIFIABLE", "badge": "⚪", "code": "N1", "missing": "public profile with past roles"}
                        else:
                            attrs_classed += 1
                            attrs_supported += 1
                        for pi, pr in enumerate(past[:2]):
                            ppath = f"{base}.people.founders.{fi}.experience.employment_details.past"
                            idx = (((f.get("experience") or {}).get("employment_details") or {}).get("past") or []).index(pr)
                            e2 = self.field_ev(ctx, c.enrich_sha, f"{ppath}.{idx}.employee_title", pr.get("employee_title"),
                                               (f.get("updated_at") or "")[:10] or rec, f"{c.crustdata_company_id}:prior:{fi}:{pi}",
                                               "crustdata.company_enrich.people.experience", kind="profile")
                            pv = self.classify(ctx, Claim(claim_id=f"{c.crustdata_company_id}:prior:{fi}:{pi}", kind="bio", type="leadership_bio",
                                                          text=str(pr.get("employee_title"))), [e2] if e2 else [])
                            if e2:
                                row_evs.append(e2)
                            yrs = "–".join(x[:4] for x in (pr.get("employee_start_date") or "", pr.get("employee_end_date") or "") if x)
                            entry["prior_roles"].append({"text": f"{pr.get('employee_title')} at {pr.get('employer_name')}" + (f" ({yrs})" if yrs else ""), **_v(pv)})
                    founders.append(entry)
                if fl:
                    row["attributes"]["founders"] = {"value": founders}
            facts += len(row_evs)
            facts_t1 += sum(1 for e in row_evs if e.tier in ("T1", "T1-M"))
            evs += row_evs
            rows.append(row)
        rr = r3(rows_returned=len(rows), rows_requested=p.n_requested, rows_passing=len(rows), attrs_requested=attrs_req,
                attrs_classed=attrs_classed, attrs_supported=attrs_supported, facts=facts, facts_t1=facts_t1, inferences=0,
                inferences_labelled=0, premise_classes=[], required_source_unavailable=bool(unavailable) and not rows,
                cfg=ctx.config["rubric"]["R3"])
        n = len(rows)
        if n == 0:
            binding = max({x["criterion"] for x in near} or {"(search)"}, key=lambda k: sum(1 for x in near if x["criterion"] == k))
            ans = f"No company meets all criteria. The binding criterion is '{binding}'" + (f" ({cs.total_count or 0} matched the search filters)." if cs.total_count is not None else ".")
        else:
            lead = ", ".join(f"{r['entity']['name']} (+{r['attributes']['headcount']['growth_pct']}%)" for r in rows[:3])
            ans = (f"{'Only ' + str(n) + ' companies meet' if p.n_requested and n < p.n_requested else str(n) + ' companies meet'} all criteria"
                   f"{' (requested ' + str(p.n_requested) + ')' if p.n_requested and n < p.n_requested else ''}. Fastest growing: {lead}. "
                   f"Growth is per Crustdata headcount from public profiles (a lower bound), record dates in the table.")
        caveats = ["Headcount and growth come from public professional profiles (Crustdata, T2): a lower bound, never a filed figure.",
                   "Founders and prior roles are 'per public profile' (🟢 P5) unless a registry or reliable media record confirms them."]
        if any("unavailable" in (r["criteria"].get("founded", {}).get("note") or "") for r in rows):
            caveats.append("Founded-year cross-check against the domain's earliest Wayback capture was unavailable for some rows.")
        return ResearchAnswer(family="FIND_LIST", status=rr["status"], confidence=rr["confidence"], answer=ans, rows=rows,
                              excluded_near_misses=near[:12], caveats=caveats, r3=rr, evidence=evs,
                              method={"requests": cs.requests, "funnel": cs.funnel, "values": cs.values, "unavailable": unavailable})

    def wayback_first(self, ctx, domain: str) -> int | None:
        src = ctx.config["sources"].get("registries", {}).get("wayback_cdx", {})
        if not src.get("enabled", True):
            return None
        url = src.get("url", "https://web.archive.org/cdx/search/cdx")
        q = f"?url={domain}&output=json&limit=1&fl=timestamp"
        try:
            r = ctx.gateway.request("wayback", "wayback_cdx", "GET", url + q, "/cdx/search/cdx" + q, None, rpm=30,
                                    critical=False, ttl_s=604800, max_retries=1)
            rows = r.body if isinstance(r.body, list) else []
            return int(rows[1][0][:4]) if len(rows) > 1 else None
        except (SourceUnavailable, BudgetExhausted, ContractError, Exception):  # noqa: BLE001
            return None

    # ------------------------------------------------------------------ RESEARCH_QA
    def research_qa(self, inp: ResearchInput, ctx) -> ResearchAnswer:
        p, cs = inp.plan, inp.candidates
        cr = ctx.crustdata
        ids = [c.crustdata_company_id for c in cs.candidates][:1000]
        caveats = [ctx.config["rubric"]["IS"]["caveat"]]
        unavailable = list(cs.unavailable)
        premise_checks = [self.check_premise(ctx, x) for x in p.premises]
        if not ids:
            rr = r3(rows_returned=0, rows_requested=p.n_requested, rows_passing=0, attrs_requested=0, attrs_classed=0, attrs_supported=0,
                    facts=0, facts_t1=0, inferences=0, inferences_labelled=0, premise_classes=[x["cls"] for x in premise_checks],
                    required_source_unavailable=bool(unavailable), cfg=ctx.config["rubric"]["R3"])
            return ResearchAnswer(family="RESEARCH_QA", status="CANNOT ANSWER", confidence="LOW", answer="No candidate companies were found for the sector filter.",
                                  premise_checks=premise_checks, caveats=caveats, r3=rr, method={"requests": cs.requests, "unavailable": unavailable})
        win = [{"field": "metadata.date_added", "type": "=>", "value": p.window_start}]
        if p.job_category:
            win.append({"field": "job_details.category", "type": "=", "value": p.job_category})
        agg = [{"type": "group_by", "field": "company.basic_info.company_id", "agg": "count", "size": 50}]
        reqs = list(cs.requests)
        names: dict = {}
        raw_counts: dict = {}
        try:
            streams = [("ids", [{"field": "company.basic_info.company_id", "type": "in", "value": ids}])]
            if p.sector == "fintech":
                seeds = ctx.config["terms"]["terms"]["fintech"]["industry_values_seed"]
                streams.append(("industry", [{"field": "company.locations.country", "type": "=", "value": "IND"},
                                             {"field": "company.basic_info.industries", "type": "in", "value": seeds}]))
            for sname, sc in streams:
                ra = cr.job_search({"op": "and", "conditions": sc + win}, limit=0, aggregations=agg)
                reqs.append({"endpoint": f"job/search aggregation ({sname})", "window": [p.window_start, p.window_end], "category": p.job_category})
                for b in (ra.body.get("aggregations") or [{}])[0].get("buckets", []):
                    raw_counts[b["key"]] = max(raw_counts.get(b["key"], 0), b["count"])
                    names[b["key"]] = (b.get("metadata") or {}).get("company_name") or names.get(b["key"])
        except (SourceUnavailable, BudgetExhausted, ContractError) as e:
            unavailable.append({"source": "crustdata.job_search", "reason": str(e)[:160], "code": "N5" if isinstance(e, BudgetExhausted) else "N2"})
            rr = r3(rows_returned=0, rows_requested=p.n_requested, rows_passing=0, attrs_requested=0, attrs_classed=0, attrs_supported=0, facts=0,
                    facts_t1=0, inferences=0, inferences_labelled=0, premise_classes=[], required_source_unavailable=True, cfg=ctx.config["rubric"]["R3"])
            return ResearchAnswer(family="RESEARCH_QA", status="CANNOT ANSWER", confidence="LOW", answer="Job data was unavailable, so the ranking cannot be computed.",
                                  premise_checks=premise_checks, caveats=caveats, r3=rr, method={"requests": reqs, "unavailable": unavailable})
        by_raw = sorted(raw_counts, key=lambda k: (-raw_counts[k], names.get(k) or ""))[: int(ctx.config["limits"].get("research_qa_classify_top", 25))]
        enr: dict[int, tuple[str, dict, str]] = {}
        try:
            er = cr.company_enrich(by_raw, ["basic_info", "taxonomy"])
            for i, item in enumerate(er.body if isinstance(er.body, list) else []):
                for m in item.get("matches", [])[:1]:
                    cd = m.get("company_data", {})
                    enr[cd.get("crustdata_company_id")] = (f"{i}.matches.0.company_data", cd, er.sha)
        except (SourceUnavailable, BudgetExhausted, ContractError) as e:
            unavailable.append({"source": "crustdata.company_enrich", "reason": str(e)[:120], "code": "N2"})
        n_target = p.n_requested or 10
        accepted: list[int] = []
        sector_by: dict[int, dict] = {}
        excluded, evs = [], []
        for cid in by_raw:
            if len(accepted) >= n_target + 3:   # a little headroom: dedup can reorder
                break
            name = names.get(cid) or str(cid)
            base, cd, esha = enr.get(cid, (None, {}, ""))
            desc = ((cd or {}).get("basic_info") or {}).get("description") or ""
            if p.sector == "fintech":
                if not desc or not inp.use_llm:
                    excluded.append({"name": name, "criterion": "fintech", "reason": "no description to classify — not checked", "postings": raw_counts[cid]})
                    continue
                extra = {"industry": (cd.get("taxonomy") or {}).get("professional_network_industry"),
                         "categories": (cd.get("taxonomy") or {}).get("categories", [])[:12]}
                cls = self.classifier(ctx, "fintech", name, desc, extra)
                text = desc + "\n" + json.dumps(extra, ensure_ascii=False)
                psha = ctx.stores.put_blob(text, "text/plain")
                off, lp = lock_segments(cls.passage or "", text) if cls else (None, None)
                if cls is None or cls.label != "fintech" or off is None:
                    lab = "classifier unavailable" if cls is None else ("ambiguous" if cls.label == "ambiguous" else ("not tech-first (incumbent/other)" if cls.label == "not_fintech" else "passage did not quote-lock"))
                    excluded.append({"name": name, "criterion": "fintech", "reason": lab + (f': "{(lp or cls.passage)[:140]}"' if cls and cls.passage else ""),
                                     "postings": raw_counts[cid]})
                    continue
                e = ctx.evidence(source="crustdata.company_enrich.basic_info.description", url_or_endpoint=f"crustdata:{cid}", passage_or_field=lp,
                                 value="fintech", record_date=None, content_sha256=psha, tier="T2", claim_id=f"{cid}:fintech", offset=off)
                evs.append(e)
                sector_by[cid] = {"label": "fintech (self-described, classified)", "passage": lp, "badge": "🟢", "cls": "PARTIALLY_VERIFIED", "code": "P1", "evidence_ids": [e.evidence_id]}
            else:
                sector_by[cid] = {"label": p.sector or "-", "badge": "🟢", "cls": "PARTIALLY_VERIFIED", "code": "P1", "evidence_ids": []}
            accepted.append(cid)
        listings, all_counts, rl = [], {}, None
        if accepted:
            try:
                rl = cr.job_search({"op": "and", "conditions": [{"field": "company.basic_info.company_id", "type": "in", "value": accepted}] + win},
                                   limit=int(ctx.config["limits"].get("research_qa_listing_limit", 500)), sorts=[{"field": "metadata.date_added", "order": "desc"}])
                reqs.append({"endpoint": "job/search listings (accepted companies)", "companies": len(accepted)})
                listings = rl.body.get("job_listings", [])
                allc = cr.job_search({"op": "and", "conditions": [{"field": "company.basic_info.company_id", "type": "in", "value": accepted},
                                                                   {"field": "metadata.date_added", "type": "=>", "value": p.window_start}]}, limit=0, aggregations=agg)
                all_counts = {b["key"]: b["count"] for b in (allc.body.get("aggregations") or [{}])[0].get("buckets", [])}
            except (SourceUnavailable, BudgetExhausted, ContractError) as e:
                unavailable.append({"source": "crustdata.job_search", "reason": str(e)[:120], "code": "N2"})
        tf = (p.title_filter or "").lower()
        by_c: dict[int, list[dict]] = {}
        for j in listings:
            cid = ((j.get("company") or {}).get("basic_info") or {}).get("crustdata_company_id")
            if cid is None:
                continue
            if tf and tf.split()[0] not in normalize.loose(j["job_details"].get("title", "")):
                continue
            by_c.setdefault(cid, []).append(j)
        dedup_counts, kept_by_c = {}, {}
        for cid in accepted:
            kept = self.dedup_postings(by_c.get(cid, []))
            kept_by_c[cid], dedup_counts[cid] = kept, len(kept)
        ranking = sorted([c for c in accepted if dedup_counts[c] > 0],
                         key=lambda k: (-dedup_counts[k], -(dedup_counts[k] / max(all_counts.get(k, 1), 1)), names.get(k) or ""))
        rows = []
        listing_sha = rl.sha if rl else ""
        themes_cfg = ctx.config["themes"]
        tax = themes_cfg.get("fintech" if p.sector == "fintech" else "logistics", {})
        generic = [g.lower() for g in themes_cfg.get("generic_titles_excluded", [])]
        for cid in ranking:
            if len(rows) >= n_target:
                break
            name = names.get(cid) or str(cid)
            sector_ev = sector_by[cid]
            kept = kept_by_c[cid]
            cnt_ev = ctx.evidence(source="crustdata.job_search", url_or_endpoint="/job/search", passage_or_field="job_listings[company].count (deduped)",
                                  value=dedup_counts[cid], record_date=p.window_end, content_sha256=listing_sha, tier="T2", kind="lower_bound",
                                  claim_id=f"{cid}:postings")
            evs.append(cnt_ev)
            row = {"entity": {"crustdata_company_id": cid, "name": name}, "postings_deduped": dedup_counts[cid], "postings_raw": raw_counts.get(cid),
                   "all_postings_window": all_counts.get(cid), "share": round(dedup_counts[cid] / all_counts[cid] * 100, 1) if all_counts.get(cid) else None,
                   "sector": sector_ev, "evidence_ids": [cnt_ev.evidence_id], "themes": []}
            if p.inference:
                row["themes"] = self.themes(kept, tax, generic, themes_cfg.get("description_rules"))
            rows.append(row)
        infs = self.inferences(ctx, rows, p, tax) if p.inference else []
        # premise: any FALSE/N7 premise blocks the answer (no fabricated list)
        pcls = [x["cls"] for x in premise_checks]
        blocked = any(c in ("FALSE", "NOT_VERIFIABLE") for c in pcls)
        near = excluded
        if blocked:
            near = [{"name": r["entity"]["name"], "criterion": "premise", "reason": "premise could not be verified for this company", "postings": r["postings_deduped"]} for r in rows] + excluded
            rows = []
        rr = r3(rows_returned=len(rows), rows_requested=n_target, rows_passing=len(rows), attrs_requested=len(rows), attrs_classed=len(rows),
                attrs_supported=len(rows), facts=len(evs), facts_t1=sum(1 for e in evs if e.tier in ("T1", "T1-M")), inferences=len(infs),
                inferences_labelled=sum(1 for i in infs if i.label), premise_classes=pcls,
                required_source_unavailable=False, cfg=ctx.config["rubric"]["R3"])
        if blocked:
            ans = (f"Cannot answer as asked: the premise \"{p.premises[0]}\" is {'contradicted' if 'FALSE' in pcls else 'not supported by any record found'}. "
                   "No list is given rather than a guessed one; the hiring ranking without the premise is listed under near-misses.")
        elif rows:
            top3 = "; ".join(f"{r['entity']['name']} ({r['postings_deduped']} deduped postings)" for r in rows[:3])
            ans = f"Ranked by deduped {'engineering ' if p.job_category else ''}job postings {p.window_start} → {p.window_end}: {top3}."
            if infs:
                ans += " " + " ".join(f"{i.company}: {i.theme_label} ({i.strength})." for i in infs[:3] if i.strength != "WEAK")
        else:
            ans = "No company passed every criterion; see near-misses."
        caveats += ["Counts are postings indexed by Crustdata (T2), deduplicated by company, normalised title, city and a 14-day window.",
                    f"Window: {p.window_start} → {p.window_end} ({p.window_label or ''}); a partly elapsed quarter."]
        return ResearchAnswer(family="RESEARCH_QA", status=rr["status"], confidence=rr["confidence"], answer=ans, rows=rows,
                              excluded_near_misses=near[:15], inferences=infs, premise_checks=premise_checks, caveats=caveats, r3=rr, evidence=evs,
                              method={"requests": reqs, "unavailable": unavailable, "listings_fetched": len(listings), "dedup": "company+title+city+14d"})

    @staticmethod
    def dedup_postings(js: list[dict]) -> list[dict]:
        kept, last = [], {}
        for j in sorted(js, key=lambda j: (j.get("metadata") or {}).get("date_added") or ""):
            t = re.sub(r"[^a-z0-9 ]", " ", normalize.loose((j.get("job_details") or {}).get("title", "")))
            t = re.sub(r"\s+", " ", t).strip()
            city = normalize.loose(((j.get("location") or {}).get("city")) or "")
            d = (j.get("metadata") or {}).get("date_added") or ""
            try:
                dd = datetime.fromisoformat(d[:19])
            except ValueError:
                dd = None
            k = (t, city)
            if k in last and dd and last[k] and (dd - last[k]) <= timedelta(days=14):
                continue
            last[k] = dd
            kept.append(j)
        return kept

    @staticmethod
    def themes(kept: list[dict], tax: dict, generic: list[str], rules: dict | None = None) -> list[dict]:
        rules = rules or {}
        req, exc, win = rules.get("require_any", []), rules.get("exclude_any", []), int(rules.get("context_window", 120))
        out = []
        for tid, th in tax.items():
            hits = []
            for j in kept:
                title = (j.get("job_details") or {}).get("title", "")
                lt = normalize.loose(title)
                kw = next((k for k in th["keywords"] if re.search(rf"\b{re.escape(k)}\b", lt)), None)
                quote, src = (title.strip(), "title") if kw else (None, None)
                if not kw:
                    desc = (j.get("content") or {}).get("description") or ""
                    for k in th["keywords"]:
                        for m in re.finditer(rf"\b{re.escape(k)}\b", desc, re.I):
                            ctxt = desc[max(0, m.start() - win): m.end() + win]
                            lc = normalize.loose(ctxt)
                            if any(r in lc for r in req) and not any(x in lc for x in exc):
                                s = desc.rfind(".", 0, m.start()) + 1
                                e = desc.find(".", m.end())
                                quote = desc[s: e if e > 0 else m.end() + 100].strip()[:200]
                                kw, src = k, "description"
                                break
                        if kw:
                            break
                if kw and not (src == "title" and lt.strip() in generic):
                    hits.append({"job_id": str(j.get("crustdata_job_id")), "quote": quote, "quote_source": src, "keyword": kw})
            if hits:
                out.append({"theme_id": tid, "label": th["label"], "n": len(hits), "postings": sorted(hits, key=lambda h: h["quote_source"] != "title")[:5]})
        return sorted(out, key=lambda x: -x["n"])

    def inferences(self, ctx, rows: list[dict], p: ResearchPlan, tax: dict) -> list[Inference]:
        is_cfg = ctx.config["rubric"]["IS"]
        out: list[Inference] = []
        for i, r in enumerate(rows):
            total = r["postings_deduped"] or 0
            cands = []
            for th in r["themes"][:2]:
                share = th["n"] / total if total else 0
                corr: list[str] = []
                if th["n"] >= is_cfg["STRONG"]["n_ge"] and share >= is_cfg["STRONG"]["share_ge"] and i < 5:
                    corr = self.corroborate(ctx, r["entity"]["name"], th, tax)
                s = inference_strength(th["n"], share, bool(corr), is_cfg)
                if s:
                    cands.append((s, th, share, corr))
            strong = [x for x in cands if x[0] in ("STRONG", "MODERATE")]
            chosen = strong if strong else cands[:1]
            for s, th, share, corr in chosen:
                q = th["postings"][0]["quote"]
                corr_txt = "corroborated by reliable-media own reporting" if corr else "no independent corroboration"
                stmt = (f"Hiring suggests {r['entity']['name']} is building {th['label']} — INFERENCE ({s}): {th['n']} of {total} "
                        f"{'engineering ' if p.job_category else ''}postings since {p.window_start}, e.g. '{q[:90]}'; {corr_txt}.")
                out.append(Inference(company=r["entity"]["name"], statement=stmt, theme=th["theme_id"], theme_label=th["label"], strength=s,
                                     n_supporting=th["n"], total=total, share=round(share, 3), corroboration_ids=corr,
                                     quotes=[x["quote"][:160] for x in th["postings"][:3]], label=is_cfg["label"]))
        return out

    def corroborate(self, ctx, company: str, th: dict, tax: dict) -> list[str]:
        """Tier-A own reporting within 12 months (STANDARDS §2.4/§3.2). Non-critical; failures → no corroboration."""
        media = ctx.config["media"]
        outlets = [d for o in media["tiers"]["A"] for d in o["domains"]][:2]
        start = int((datetime.combine(ctx.clock.today() - timedelta(days=365), datetime.min.time())).timestamp())
        for site in outlets:
            try:
                r = ctx.crustdata.web_search(f"{company} {th['label']}", ["news"], site=site, start_date=start, critical=False)
            except (SourceUnavailable, BudgetExhausted, ContractError):
                return []
            for res in (r.body.get("results") or [])[:3]:
                snip = res.get("snippet") or ""
                title = res.get("title") or ""
                text = f"{title} {snip}"
                lt = normalize.loose(text)
                if normalize.loose(company.split()[0]) in lt and any(k in lt for k in tax.get(th["theme_id"], {}).get("keywords", [])):
                    if any(lbl in lt for lbl in media["own_reporting_test"]["reject_labels"]):
                        continue
                    # own-reporting needs the article (byline, labels); the snippet alone is not enough → fetch
                    try:
                        f = ctx.crustdata.web_fetch([res["url"]], critical=False)
                        page = json.dumps(f.body, ensure_ascii=False)
                    except (SourceUnavailable, BudgetExhausted, ContractError):
                        return []
                    lp = normalize.loose(page)
                    if any(lbl in lp for lbl in media["own_reporting_test"]["reject_labels"]) or not re.search(r"(?i)\bby\s+[A-Z]|\"author\"|byline|staff", page):
                        continue
                    off = lock(snip[:120], page) if snip else None
                    if off is None:
                        continue
                    tier = "A"
                    e = ctx.evidence(source=f"media:{site}", url_or_endpoint=res["url"], passage_or_field=snip[:120], value=th["label"],
                                     record_date=None, content_sha256=ctx.stores.put_blob(page, "text/html"), tier="T1-M", media_tier=tier,
                                     claim_id=f"corr:{company}:{th['theme_id']}", offset=off)
                    return [e.evidence_id]
        return []

    def check_premise(self, ctx, premise: str) -> dict:
        """Premise → ✅ / ❌ F3 / ⚪ N7. Only a quote-locked T1/T1-M record can settle it; absence ⇒ N7, never FALSE."""
        try:
            r = ctx.crustdata.web_search(premise + " India", ["news"], critical=False)
            sha = r.sha
            n = len(r.body.get("results") or [])
        except (SourceUnavailable, BudgetExhausted, ContractError) as e:
            return {"premise": premise, "cls": "NOT_VERIFIABLE", "code": "N2" if isinstance(e, SourceUnavailable) else "N5", "badge": "⚪",
                    "missing": "news search unavailable"}
        return {"premise": premise, "cls": "NOT_VERIFIABLE", "code": "N7", "badge": "⚪", "search_results": n, "search_sha": sha,
                "missing": "an exchange filing or tier-A own report listing the companies that satisfy the premise"}


AGENT = ResearchAnalyst()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
