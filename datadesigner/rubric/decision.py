"""R2 decision (STANDARDS §6.4–6.5): gates → floor–ceiling → fixed rule → requirement cap → wording,
conditions and 'what would change it'. Deterministic; reads config/rubric.yaml and mitigants.yaml."""
from __future__ import annotations

from itertools import combinations
from typing import Any

from pydantic import BaseModel, Field

from .scoring import CAP, requirement_status, rule, score


class CriterionIn(BaseModel):
    id: str
    value: str = ""
    pf: float | None = None   # points floor (None = missing → 0)
    pc: float | None = None   # points ceiling (None = missing → 4)
    coverage: float = 1.0      # share of inputs with evidence
    asks: list[dict] = Field(default_factory=list)   # [{ask, new_pf, closes?}]


class Gate(BaseModel):
    id: str
    passed: bool
    outcome: str | None = None   # HOLD | REJECT when failed
    detail: str = ""


class Decision(BaseModel):
    rubric_id: str
    version: str
    sha256: str
    profile: str
    gates: list[Gate]
    criteria: list[dict]
    floor: float
    ceiling: float
    coverage: float
    rule_applied: str
    outcome: str
    label: str
    requirements: list[dict]
    conditions: list[dict]
    what_would_change: dict | None
    drivers: dict


def decide(profile: str, crits: list[CriterionIn], gates: list[Gate], requirements: dict[str, float],
           rubric_cfg: dict, mitigants: dict, rubric_sha: str = "", extra_requirements: list[dict] | None = None) -> Decision:
    r2 = rubric_cfg["R2"]
    weights = r2["weights"][profile]
    table, cmap = {}, {c.id: c for c in crits}
    rows = []
    for cid, w in weights.items():
        c = cmap.get(cid, CriterionIn(id=cid))
        pf = 0.0 if c.pf is None else c.pf
        pc = 4.0 if c.pc is None else c.pc
        table[cid] = (w, pf, pc)
        rows.append({"id": cid, "value": c.value, "points_floor": pf, "points_ceiling": pc, "weight": w,
                     "floor": round(w * pf / 4, 2), "ceiling": round(w * pc / 4, 2), "coverage": c.coverage})
    F, C = score(table)
    coverage = round(sum(weights[c] * cmap.get(c, CriterionIn(id=c, coverage=0)).coverage for c in weights), 2)

    fired = next((g for g in gates if not g.passed), None)
    reqs = []
    for name, minimum in requirements.items():
        if name in table:
            _, pf, pc = table[name]
            st = requirement_status(cmap[name].pf if name in cmap else None, cmap[name].pc if name in cmap else None, minimum)
            reqs.append({"name": name, "min": minimum, "status": st, "value": f"floor {pf:g}, ceiling {pc:g}"})
    reqs += extra_requirements or []
    if fired:
        outcome, rule_txt = ("negative" if fired.outcome == "REJECT" else "hold"), f"gate {fired.id} → {fired.outcome}"
    else:
        outcome = rule(F, C)
        rule_txt = {"negative": "rule 2: ceiling < 50", "positive": "rule 3: floor ≥ 75",
                    "positive_with_conditions": "rule 4: floor ≥ 50 and < 75", "hold": "rule 5: otherwise"}[outcome]
        if any(r["status"] == "unmet" for r in reqs):
            outcome, rule_txt = CAP[outcome], rule_txt + " · capped one level (requirement unmet)"
    label = rubric_cfg["wording"][profile][outcome]

    # conditions: asks ordered by points each adds + open requirements + mitigation per criterion ≤ 1
    conds: list[dict] = []
    for c in crits:
        for a in c.asks:
            w, pf, _ = table[c.id]
            gain = round(w * (a["new_pf"] - pf) / 4, 2)
            conds.append({"ask": a["ask"], "criterion": c.id, "adds": gain, "closes": a.get("closes")})
    conds.sort(key=lambda x: -x["adds"])
    for r in reqs:
        if r["status"] == "open" and not any(x.get("closes") == r["name"] for x in conds):
            conds.append({"ask": f"Evidence to settle requirement {r['name']} ≥ {r['min']}", "criterion": r["name"], "adds": 0.0})
    for cid, (w, pf, pc) in table.items():
        if w and pf <= 1 and cid in mitigants:
            conds.append({"ask": mitigants[cid], "criterion": cid, "adds": 0.0, "mitigation": True})

    wwc = _what_would_change(crits, table, F, outcome, reqs, rubric_cfg, profile) if not fired else None
    ranked = sorted(rows, key=lambda r: r["floor"] - r["weight"] * 3 / 4)
    drivers = {"for": [r["id"] for r in sorted(rows, key=lambda r: -r["points_floor"] * (r["weight"] > 0)) if r["weight"]][:3],
               "against": [r["id"] for r in ranked if r["weight"] and r["points_floor"] <= 2][:3]}
    return Decision(rubric_id="R2", version=rubric_cfg.get("version", ""), sha256=rubric_sha, profile=profile, gates=gates,
                    criteria=rows, floor=F, ceiling=C, coverage=coverage, rule_applied=rule_txt, outcome=outcome, label=label,
                    requirements=reqs, conditions=conds, what_would_change=wwc, drivers=drivers)


def _what_would_change(crits, table, F, outcome, reqs, rubric_cfg, profile) -> dict | None:
    """Smallest set of asks moving the floor across the next threshold; ties → set closing an open requirement."""
    nxt = {"hold": 50.0, "positive_with_conditions": 75.0}.get(outcome)
    if nxt is None:
        return None
    asks = [(c.id, a) for c in crits for a in c.asks]
    for k in range(1, len(asks) + 1):
        best = None
        for combo in combinations(asks, k):
            t = dict(table)
            per: dict[str, float] = {}
            for cid, a in combo:
                per[cid] = max(per.get(cid, -1), a["new_pf"])
            for cid, v in per.items():
                w, _, pc = t[cid]
                t[cid] = (w, v, pc)
            f2 = round(sum(w * pf / 4 for w, pf, _ in t.values()), 2)
            if f2 >= nxt:
                closes = sum(1 for _, a in combo if a.get("closes"))
                cand = (closes, f2, combo)
                if best is None or cand[:2] > best[:2]:
                    best = cand
        if best:
            new_out = rule(best[1], 100)
            return {"asks": [a["ask"] for _, a in best[2]], "floor": best[1],
                    "label": rubric_cfg["wording"][profile][new_out], "closes": [a.get("closes") for _, a in best[2] if a.get("closes")]}
    return None
