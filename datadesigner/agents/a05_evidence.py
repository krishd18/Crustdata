"""A5 Evidence Collector (ARCHITECTURE §9; config/collectors.yaml). Per claim, the ordered collectors are tried
(critical claims first; budget checked before each call). Registries are captcha-gated: no bypass — operator-uploaded
extracts in the pack are T1 (operator) with hash + date; missing extract → ⚪ N6. Crustdata fields become T2
candidates (headcount is a lower bound). Output candidates go to A6 for quote lock."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.errors import BudgetExhausted, SourceUnavailable
from ..core.types import Claim
from .a06_quote_lock import Candidate, EvidenceBundle
from .base import BaseAgent, cli


class CollectInput(BaseModel):
    claims: list[Claim]
    extracts: list[dict] = Field(default_factory=list)   # [{claim_id|type, source, tier, raw, passage|field_path, value, record_date, relation, kind, media_tier}]
    crustdata_company_id: int | None = None
    live_sources: bool = True


class EvidenceCollector(BaseAgent[CollectInput, EvidenceBundle]):
    name, input_model, output_model = "a05_evidence", CollectInput, EvidenceBundle

    def run(self, inp: CollectInput, ctx) -> EvidenceBundle:
        plan = ctx.config["collectors"].get("by_claim_type", {})
        out = EvidenceBundle()
        enrich = None
        for c in sorted(inp.claims, key=lambda c: (not c.critical, c.claim_id)):
            if c.type in ("projection", "opinion"):
                continue
            got = False
            for x in inp.extracts:
                if x.get("claim_id") == c.claim_id or (not x.get("claim_id") and x.get("type") == c.type):
                    out.candidates.append(Candidate(claim_id=c.claim_id, source=x["source"], url_or_endpoint=x.get("url", x["source"]),
                                                    blob_sha="", raw=x["raw"], passage=x.get("passage"), field_path=x.get("field_path"),
                                                    value=x.get("value"), record_date=x.get("record_date"), tier=x["tier"],
                                                    media_tier=x.get("media_tier"), relation=x.get("relation", "supports"),
                                                    kind=x.get("kind", "field"), attributed_to_company_quote=x.get("company_quote", False)))
                    got = True
            collectors = plan.get(c.type, [])
            if not got and any(s.startswith(("registry", "issuer_register")) for s in collectors[:1]):
                out.unavailable.append({"claim_id": c.claim_id, "source": collectors[0], "code": "N6",
                                        "reason": "captcha-gated registry; no operator extract uploaded"})
            if inp.live_sources and inp.crustdata_company_id and c.type in ("headcount", "incorporation_date", "operating_since") and not got:
                try:
                    critical = c.critical
                    if enrich is None:
                        r = ctx.crustdata.company_enrich([inp.crustdata_company_id], ["basic_info", "headcount"], critical=critical)
                        enrich = r
                    cd = (enrich.body[0]["matches"][0]["company_data"]) if enrich.body else {}
                    base = "0.matches.0.company_data"
                    if c.type == "headcount" and (cd.get("headcount") or {}).get("total") is not None:
                        v = cd["headcount"]["total"]
                        claimed = c.value if isinstance(c.value, (int, float)) else None
                        rel = "supports" if claimed is None or v >= float(claimed) else "contradicts"
                        out.candidates.append(Candidate(claim_id=c.claim_id, source="crustdata.company_enrich", url_or_endpoint="/company/enrich",
                                                        blob_sha=enrich.sha, field_path=f"{base}.headcount.total", value=v, tier="T2", kind="lower_bound",
                                                        relation=rel, record_date=((cd["headcount"].get("timeseries") or [{}])[-1]).get("date")))
                    if c.type in ("incorporation_date", "operating_since") and (cd.get("basic_info") or {}).get("year_founded"):
                        out.candidates.append(Candidate(claim_id=c.claim_id, source="crustdata.company_enrich", url_or_endpoint="/company/enrich",
                                                        blob_sha=enrich.sha, field_path=f"{base}.basic_info.year_founded", value=cd["basic_info"]["year_founded"], tier="T2"))
                except (SourceUnavailable, BudgetExhausted) as e:
                    out.unavailable.append({"claim_id": c.claim_id, "source": "crustdata.company_enrich",
                                            "code": "N5" if isinstance(e, BudgetExhausted) else "N2", "reason": str(e)[:100]})
                except (KeyError, IndexError, TypeError):
                    pass
        return out


AGENT = EvidenceCollector()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
