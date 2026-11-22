"""A10 Market & Region Analyst (STANDARDS §4.3, §4.8). FP-01 per state (GST state code, or ≥ 2 weak signals),
FP-02/RG-02 target share, RG-03 network fit, RG-C; MK-C from a cited segment CAGR + growth vs competitor median.
Market-size figures appear only with a quote-locked source (else '[no cited range]')."""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..rubric.scoring import band, composite, metric_points
from .base import BaseAgent, cli

ZONES = {"Maharashtra": "West", "Gujarat": "West", "Goa": "West", "Delhi": "North", "Haryana": "North", "Uttar Pradesh": "North", "Punjab": "North",
         "Rajasthan": "North", "Karnataka": "South", "Tamil Nadu": "South", "Telangana": "South", "Kerala": "South", "Andhra Pradesh": "South",
         "West Bengal": "East", "Odisha": "East", "Bihar": "East", "Assam": "North-East", "Madhya Pradesh": "Central", "Chhattisgarh": "Central"}


class MarketInput(BaseModel):
    target_state: str | None = None
    states: dict[str, dict] = Field(default_factory=dict)   # state → {gst_active: bool, site: bool, staff: int, openings_90d: int}
    target_shares: dict[str, float] = Field(default_factory=dict)  # staff/openings/sites/fleet share in target (%)
    client_states: dict[str, str] = Field(default_factory=dict)    # state → present|weak|absent
    profile: str = "target"
    segment_cagr: float | None = None
    company_growth: float | None = None
    competitor_median_growth: float | None = None
    market_size: dict | None = None    # {min,max,sources:[evidence_id]}


class MarketRegionReport(BaseModel):
    regions: list[dict]
    fp02: float | None
    rg02: float | None
    rg03: float | None
    rg_c: float | None
    rg_points: dict
    mk_c: float | None
    market_size_range: dict | None
    concentration: str | None


class MarketRegion(BaseAgent[MarketInput, MarketRegionReport]):
    name, input_model, output_model = "a10_market_region", MarketInput, MarketRegionReport

    def run(self, inp: MarketInput, ctx) -> MarketRegionReport:
        mc = ctx.config["metrics"]
        regions = []
        for st, s in inp.states.items():
            weak = sum([bool(s.get("site")), (s.get("staff") or 0) >= 10, (s.get("openings_90d") or 0) >= 3])
            fp01 = "Yes" if s.get("gst_active") or weak >= 2 else ("Unknown" if weak == 1 else "No")
            regions.append({"state": st, "zone": ZONES.get(st, "—"), "fp01": fp01, "basis": "GST state code" if s.get("gst_active") else f"{weak} weak signals"})
        operating = [r["state"] for r in regions if r["fp01"] == "Yes"]
        shares = [v for v in inp.target_shares.values() if v is not None]
        fp02 = round(sum(shares) / len(shares), 1) if shares else None
        rg02_pts = metric_points("RG-02", fp02, mc)
        if inp.profile == "target":
            add = [s for s in operating if inp.client_states.get(s, "absent") in ("weak", "absent")]
            rg03 = round(100 * len(add) / len(operating), 1) if operating and inp.client_states else None
            rg03_pts = metric_points("RG-03-target", rg03, mc)
        else:
            req = [s for s, v in inp.client_states.items() if v == "required"]
            rg03 = round(100 * len([s for s in req if s in operating]) / len(req), 1) if req else None
            rg03_pts = metric_points("RG-03-vendor", rg03, mc)
        rgc = composite([p for p in (rg02_pts, rg03_pts) if p is not None])
        mk = None
        if inp.segment_cagr is not None and inp.company_growth is not None and inp.competitor_median_growth is not None:
            seg = 2 if inp.segment_cagr >= 15 else (1 if inp.segment_cagr >= 8 else 0)
            d = inp.company_growth - inp.competitor_median_growth
            rel = 2 if d >= 10 else (1 if d > -10 else 0)
            mk = float(seg + rel)
        conc = None
        if inp.target_shares and fp02 and fp02 > 85:
            conc = f"risk: {fp02}% of operations in {inp.target_state}"
        return MarketRegionReport(regions=regions, fp02=fp02, rg02=fp02, rg03=rg03, rg_c=rgc, rg_points={"RG-02": rg02_pts, "RG-03": rg03_pts},
                                  mk_c=mk, market_size_range=inp.market_size if (inp.market_size or {}).get("sources") else None, concentration=conc)


AGENT = MarketRegion()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
