"""A8 Financial Analyst (ARCHITECTURE §12–13; STANDARDS §4.5). Statements → FSV-01…03 footing checks (a parse is
accepted only if they pass) → metric dictionary (config/metrics.yaml) → pillars → health grade (A–E)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..core.types import Metric
from ..rubric.scoring import health_grade, metric_points
from .base import BaseAgent, cli

FORMULAS = {
    "GR-01": ("(Rev0/Rev-3)^(1/3)-1", lambda s, p: ((s[-1]["revenue"] / s[0]["revenue"]) ** (1 / (len(s) - 1)) - 1) * 100 if len(s) >= 2 and s[0]["revenue"] else None),
    "PR-01": ("EBITDA/revenue", lambda s, p: s[-1]["ebitda"] / s[-1]["revenue"] * 100),
    "PR-02": ("PAT/revenue", lambda s, p: s[-1]["pat"] / s[-1]["revenue"] * 100),
    "PR-03": ("EBIT/(TA-CL)", lambda s, p: s[-1]["ebit"] / (s[-1]["total_assets"] - s[-1]["current_liabilities"]) * 100),
    "PR-04": ("PAT/avg equity", lambda s, p: s[-1]["pat"] / ((s[-1]["equity"] + s[-2]["equity"]) / 2) * 100 if len(s) > 1 else None),
    "LQ-01": ("CA/CL", lambda s, p: s[-1]["current_assets"] / s[-1]["current_liabilities"]),
    "LQ-02": ("(CA-inventory)/CL", lambda s, p: (s[-1]["current_assets"] - s[-1].get("inventory", 0)) / s[-1]["current_liabilities"]),
    "SV-01": ("borrowings/equity", lambda s, p: s[-1]["borrowings"] / s[-1]["equity"]),
    "SV-02": ("(borrowings-cash)/EBITDA", lambda s, p: (s[-1]["borrowings"] - s[-1]["cash"]) / s[-1]["ebitda"]),
    "SV-03": ("EBIT/interest", lambda s, p: s[-1]["ebit"] / s[-1]["interest"]),
    "SV-04": ("(PAT+D&A+interest)/(interest+principal)", lambda s, p: (s[-1]["pat"] + s[-1]["da"] + s[-1]["interest"]) / (s[-1]["interest"] + s[-1]["principal_due"])),
    "WC-01": ("receivables/revenue×365", lambda s, p: s[-1]["receivables"] / s[-1]["revenue"] * 365),
    "CQ-01": ("CFO/EBITDA", lambda s, p: s[-1]["cfo"] / s[-1]["ebitda"] * 100),
    "CQ-02": ("(CFO-capex)/revenue", lambda s, p: (s[-1]["cfo"] - s[-1]["capex"]) / s[-1]["revenue"] * 100),
}


class FinInput(BaseModel):
    statements: list[dict] = Field(default_factory=list)   # oldest → newest, ₹ lakh line items
    metric_values: dict[str, float] = Field(default_factory=dict)   # pre-computed values (fixtures / provided analyses)
    quality_tag: str = "audited-provided"
    filed: bool = False


class FinancialReport(BaseModel):
    fsv: list[dict] = Field(default_factory=list)
    metrics: list[Metric] = Field(default_factory=list)
    pillars: dict[str, float] = Field(default_factory=dict)
    pillar_mean: float | None = None
    grade: str | None = None
    flags: list[str] = Field(default_factory=list)
    accepted: bool = True


def fsv(stmts: list[dict]) -> list[dict]:
    out = []
    for i, s in enumerate(stmts):
        if {"total_assets", "total_liabilities", "equity"} <= s.keys():
            ok = abs(s["total_assets"] - (s["total_liabilities"] + s["equity"])) <= 0.005 * s["total_assets"]
            out.append({"id": "FSV-01", "period": s.get("period", i), "status": "pass" if ok else "fail", "detail": "assets = liabilities + equity (±0.5%)"})
        if {"current_assets", "ca_items"} <= s.keys():
            ok = abs(sum(s["ca_items"].values()) - s["current_assets"]) <= 0.005 * s["current_assets"]
            out.append({"id": "FSV-02", "period": s.get("period", i), "status": "pass" if ok else "fail", "detail": "current-asset sub-totals foot"})
        if {"cash_open", "net_cash_flow", "cash"} <= s.keys():
            ok = abs(s["cash_open"] + s["net_cash_flow"] - s["cash"]) <= max(1, 0.005 * abs(s["cash"]))
            out.append({"id": "FSV-03", "period": s.get("period", i), "status": "pass" if ok else "fail", "detail": "cash roll-forward"})
    return out


class FinancialAnalyst(BaseAgent[FinInput, FinancialReport]):
    name, input_model, output_model = "a08_financial", FinInput, FinancialReport

    def run(self, inp: FinInput, ctx) -> FinancialReport:
        mcfg = ctx.config["metrics"]
        rep = FinancialReport(fsv=fsv(inp.statements))
        if any(x["status"] == "fail" and x["id"] in ("FSV-01", "FSV-02", "FSV-03") for x in rep.fsv):
            rep.accepted = False
            rep.flags.append("statements internally inconsistent (FSV-01…03) → gate G6 Hold")
            return rep
        vals = dict(inp.metric_values)
        if inp.statements:
            for mid, (formula, fn) in FORMULAS.items():
                if mid in vals:
                    continue
                try:
                    v = fn(inp.statements, None)
                except (KeyError, ZeroDivisionError, IndexError, TypeError):
                    v = None
                if v is not None:
                    vals[mid] = round(v, 4)
        tag = "audited-filed" if inp.filed else inp.quality_tag
        for mid, v in vals.items():
            if mid not in mcfg["metrics"]:
                continue
            pts = 4 if (mid == "SV-02" and v is not None and v <= 0) else metric_points(mid, v, mcfg)
            rep.metrics.append(Metric(id=mid, value=v, unit=mcfg["metrics"][mid].get("unit", ""), points=pts, quality_tag=tag,
                                      formula=FORMULAS.get(mid, ("provided", None))[0]))
        pts = {m.id: m.points for m in rep.metrics}
        by_pillar = {name: [pts.get(m) for m in ids if m in pts] for name, ids in mcfg["health_grade"]["pillars"].items()}
        by_pillar = {k: v for k, v in by_pillar.items() if v}
        distress = (vals.get("EQ-01") is not None and vals["EQ-01"] < 1.1) or (vals.get("EQ-02") is not None and vals["EQ-02"] > -1.78)
        if distress:
            rep.flags.append("earnings-quality flag (Z'' distress or M-score) → grade capped at C")
        rep.grade, rep.pillar_mean, rep.pillars = health_grade(by_pillar, mcfg, distress)
        return rep


AGENT = FinancialAnalyst()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
