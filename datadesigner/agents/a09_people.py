"""A9 People & Leadership (ARCHITECTURE §14; STANDARDS §4.7). LF-01…07 from role-relevant professional facts only —
fairness exclusions are enforced in code (config/roles.yaml fairness_excluded_inputs are rejected as inputs).
Namesake/sanctions hits are 'possible match — not confirmed' (HOLD), never auto-confirmed."""
from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from ..rubric.scoring import composite, lf_verdict, metric_points
from .base import BaseAgent, cli


class PeopleInput(BaseModel):
    people: list[dict] = Field(default_factory=list)          # [{name, role, domain_years, senior_at_larger, clean, din?, city?}]
    bio_verdict_credits: list[float] = Field(default_factory=list)   # credit floor per bio claim (A7 output)
    bio_false: bool = False
    required_roles: list[str] = Field(default_factory=list)
    churn_pct: float | None = None
    pillars_with_leader: tuple[int, int] | None = None          # (covered, total)
    screening: list[dict] = Field(default_factory=list)        # [{name, list, matched_attrs:[...], same_person?}]

    @model_validator(mode="before")
    @classmethod
    def no_protected(cls, v):
        banned = {"age", "gender", "religion", "caste", "region_of_origin", "family", "institution_prestige", "career_breaks"}
        for p in (v or {}).get("people", []):
            bad = banned & set(p)
            if bad:
                raise ValueError(f"fairness: inputs {sorted(bad)} are excluded from leadership fit")
        return v


class PeopleReport(BaseModel):
    lf: dict[str, dict]
    composite: float | None
    verdict: str
    gaps: list[str]
    screening: list[dict]


def _roles_covered(people: list[dict], required: list[str], syn: dict) -> tuple[float, list[str]]:
    used, missing = set(), []
    for r in required:
        who = next((p["name"] for p in people if p["name"] not in used and any(s in p.get("role", "").lower() for s in syn.get(r, [r]))), None)
        if who:
            used.add(who)
        else:
            missing.append(r)
    return (100 * (len(required) - len(missing)) / len(required) if required else 100.0), missing


class PeopleLeadership(BaseAgent[PeopleInput, PeopleReport]):
    name, input_model, output_model = "a09_people", PeopleInput, PeopleReport

    def run(self, inp: PeopleInput, ctx) -> PeopleReport:
        mc, roles = ctx.config["metrics"], ctx.config["roles"]
        req = inp.required_roles or roles.get("base_required", [])
        lf01, missing = _roles_covered(inp.people, req, roles.get("title_synonyms", {}))
        cx = [p for p in inp.people]
        dy = sorted(p["domain_years"] for p in cx if p.get("domain_years") is not None)
        lf02 = (dy[len(dy) // 2] if len(dy) % 2 else (dy[len(dy) // 2 - 1] + dy[len(dy) // 2]) / 2) if dy else None
        sl = [p["senior_at_larger"] for p in cx if p.get("senior_at_larger") is not None]
        lf03 = 100 * sum(sl) / len(sl) if sl else None
        cl = [p["clean"] for p in cx if p.get("clean") is not None]
        lf04 = 100 * sum(cl) / len(cl) if cl else None
        lf05 = 100 * sum(inp.bio_verdict_credits) / len(inp.bio_verdict_credits) if inp.bio_verdict_credits else None
        lf07 = 100 * inp.pillars_with_leader[0] / inp.pillars_with_leader[1] if inp.pillars_with_leader else None
        vals = {"LF-01": lf01, "LF-02": lf02, "LF-03": lf03, "LF-04": lf04, "LF-05": lf05, "LF-06": inp.churn_pct, "LF-07": lf07}
        lf = {}
        for k, v in vals.items():
            pts = metric_points(k, v, mc)
            if k == "LF-05" and inp.bio_false:
                pts = 0
            lf[k] = {"value": None if v is None else round(v, 1), "points": pts}
        measurable = sum(1 for x in lf.values() if x["points"] is not None)
        comp = composite([x["points"] for x in lf.values() if x["points"] is not None])
        gaps = [f"no {r.replace('_', ' ')}" for r in missing]
        scr = []
        for s in inp.screening:
            matched = len(s.get("matched_attrs", []))
            status = "confirmed" if (s.get("same_person") and matched >= 2) else "possible match — not confirmed"
            scr.append({**s, "status": status})
        return PeopleReport(lf=lf, composite=comp, verdict=lf_verdict(comp, measurable, mc), gaps=gaps, screening=scr)


AGENT = PeopleLeadership()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
