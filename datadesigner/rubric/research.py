"""R1 labels (STANDARDS §6.3), R3 research-answer status/confidence (§6.8) and Inference Strength (§2.4)."""
from __future__ import annotations

from .scoring import CAP, score


def r1(table: dict[str, tuple[float, float, float]], risk_flag: bool, requirement_statuses: list[str]) -> dict:
    F, C = score(table)
    if F >= 60 and not risk_flag:
        label = "RECOMMEND"
    elif C >= 60:
        label = "CONSIDER"
    else:
        label = "NOT RECOMMENDED"
    if "unmet" in requirement_statuses:
        label = CAP[label]
    return {"floor": F, "ceiling": C, "label": label}


def r3(*, rows_returned: int, rows_requested: int | None, rows_passing: int, attrs_requested: int, attrs_classed: int,
       attrs_supported: int, facts: int, facts_t1: int, inferences: int, inferences_labelled: int,
       premise_classes: list[str], required_source_unavailable: bool, cfg: dict) -> dict:
    q1 = rows_passing / rows_returned if rows_returned else 1.0
    q2a = attrs_classed / attrs_requested if attrs_requested else 1.0
    q2b = attrs_supported / attrs_requested if attrs_requested else 1.0
    q3 = rows_returned / rows_requested if rows_requested else (1.0 if rows_returned else 0.0)
    q4 = facts_t1 / facts if facts else 0.0
    q5 = inferences_labelled / inferences if inferences else 1.0
    false_premise = "FALSE" in premise_classes
    if false_premise or rows_returned == 0 or required_source_unavailable:
        status = "CANNOT ANSWER"
    elif q1 == 1 and q2a == 1 and q3 >= 1 and q5 == 1:
        status = "COMPLETE"
    else:
        status = "PARTIAL"
    conf = "HIGH" if (q2b >= 0.90 and q4 >= 0.30) else ("MEDIUM" if q2b >= 0.75 else "LOW")
    return {"Q1": round(q1, 3), "Q2a": round(q2a, 3), "Q2b": round(q2b, 3), "Q3": round(q3, 3), "Q4": round(q4, 3),
            "Q5": round(q5, 3), "Q6": premise_classes, "status": status, "confidence": conf,
            "q3_text": f"{rows_returned}/{rows_requested}" if rows_requested else f"{rows_returned}"}


def inference_strength(n: int, share: float, corroborated: bool, cfg: dict) -> str | None:
    s, m = cfg["STRONG"], cfg["MODERATE"]
    if n >= s["n_ge"] and share >= s["share_ge"] and corroborated:
        return "STRONG"
    for alt in m["any_of"]:
        if n >= alt["n_ge"] and share >= alt["share_ge"]:
            return "MODERATE"
    if n >= cfg["WEAK"]["n_ge"]:
        return "WEAK"
    return None
