"""A3 Entity Resolver (ARCHITECTURE §7): weighted agreement — domain 0.35 · CIN/GSTIN 0.35 · name fuzz 0.15 ·
city 0.10 · year 0.05. ≥ 0.85 resolved · 0.60–0.85 ambiguous (HOLD) · < 0.60 unresolved (N4).
Lookalikes are never merged on name alone (a name match can contribute at most 0.15)."""
from __future__ import annotations

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from ..core import normalize
from .base import BaseAgent, cli

W = {"domain": 0.35, "id": 0.35, "name": 0.15, "city": 0.10, "year": 0.05}


class EntityHints(BaseModel):
    name: str
    domain: str | None = None
    cin: str | None = None
    gstin: str | None = None
    city: str | None = None
    year: int | None = None
    profile_url: str | None = None
    candidates: list[dict] = Field(default_factory=list)   # pre-fetched [{crustdata_company_id,name,domain,cin,gstin,city,year}]
    lookup: bool = True


class ResolvedEntity(BaseModel):
    crustdata_company_id: int | None = None
    name: str | None = None
    domain: str | None = None
    cin: str | None = None
    gstin: str | None = None
    score: float
    status: str
    candidates: list[dict] = Field(default_factory=list)


def _dom(d: str | None) -> str:
    d = (d or "").lower().strip()
    for p in ("https://", "http://", "www."):
        d = d.removeprefix(p)
    return d.split("/")[0]


def match_score(h: EntityHints, c: dict) -> tuple[float, dict]:
    parts = {}
    if h.domain and c.get("domain"):
        parts["domain"] = W["domain"] if _dom(h.domain) == _dom(c["domain"]) else 0.0
    hid, cid = (h.cin or h.gstin or ""), (c.get("cin") or c.get("gstin") or "")
    if hid and cid:
        same = hid.upper() == cid.upper() or (len(hid) == 15 and len(cid) == 15 and hid[2:12].upper() == cid[2:12].upper())
        parts["id"] = W["id"] if same else 0.0
    if h.name and c.get("name"):
        r = fuzz.token_sort_ratio(normalize.company_name(h.name), normalize.company_name(c["name"])) / 100
        parts["name"] = W["name"] * (r if r >= 0.9 else r * 0.5)
    if h.city and c.get("city"):
        parts["city"] = W["city"] if normalize.loose(h.city) in normalize.loose(c["city"]) or normalize.loose(c["city"]) in normalize.loose(h.city) else 0.0
    if h.year and c.get("year"):
        parts["year"] = W["year"] if abs(int(h.year) - int(c["year"])) <= 1 else 0.0
    # Missing attributes neither add nor subtract: score is normalised over attributes BOTH sides have,
    # but a name-only comparison is capped below 'resolved' (lookalike guard).
    have = sum(W[k] for k in parts)
    s = sum(parts.values()) / have if have else 0.0
    if set(parts) <= {"name", "city", "year"}:
        s = min(s, 0.84)
    return round(s, 3), parts


class EntityResolver(BaseAgent[EntityHints, ResolvedEntity]):
    name, input_model, output_model = "a03_entity_resolver", EntityHints, ResolvedEntity

    def run(self, inp: EntityHints, ctx) -> ResolvedEntity:
        cands = list(inp.candidates)
        if not cands and inp.lookup and ctx is not None:
            try:
                r = ctx.crustdata.company_identify(domains=[inp.domain]) if inp.domain else ctx.crustdata.company_identify(names=[inp.name])
                for m in (r.body[0].get("matches", []) if isinstance(r.body, list) and r.body else []):
                    cd = m.get("company_data", {})
                    bi = cd.get("basic_info", {})
                    cands.append({"crustdata_company_id": cd.get("crustdata_company_id"), "name": bi.get("name"),
                                  "domain": bi.get("primary_domain"), "year": bi.get("year_founded"),
                                  "city": (cd.get("locations") or {}).get("city")})
            except Exception as e:  # noqa: BLE001 — resolver degrades to unresolved, never guesses
                ctx.log.warning("a03.lookup_failed", error=str(e)[:120])
        scored = sorted(({**c, "score": match_score(inp, c)[0]} for c in cands), key=lambda c: -c["score"])
        if not scored:
            return ResolvedEntity(score=0.0, status="unresolved", candidates=[])
        top = scored[0]
        # two candidates both above 0.6 with different domains → ambiguous (never merge lookalikes)
        if len(scored) > 1 and scored[1]["score"] >= 0.6 and _dom(scored[1].get("domain")) != _dom(top.get("domain")) and top["score"] - scored[1]["score"] < 0.1:
            status = "ambiguous"
        else:
            status = "resolved" if top["score"] >= 0.85 else ("ambiguous" if top["score"] >= 0.60 else "unresolved")
        res = ResolvedEntity(score=top["score"], status=status, candidates=scored[:5])
        if status == "resolved":
            res.crustdata_company_id, res.name, res.domain = top.get("crustdata_company_id"), top.get("name"), top.get("domain")
            res.cin, res.gstin = top.get("cin") or inp.cin, top.get("gstin") or inp.gstin
        return res


AGENT = EntityResolver()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
