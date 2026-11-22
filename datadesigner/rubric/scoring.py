"""Scoring math (STANDARDS §4.1, §6.2; RUBRIC card 1). Must equal tools/rubric_check.py (V7)."""
from __future__ import annotations

import math
from statistics import median


def band(v: float | None, edges: list[float], higher: bool = True) -> int | None:
    """Points 4..0 from four edges (for 4,3,2,1). Edge value → better band. None stays None (missing)."""
    if v is None:
        return None
    for p, e in zip((4, 3, 2, 1), edges):
        if (v >= e if higher else v <= e):
            return p
    return 0


def band_strict_down(v: float | None, edges: list[float]) -> int | None:
    """For 'down_strict' metrics (LF-06): < e1 → 4, < e2 → 3 … ≥ last → 0."""
    if v is None:
        return None
    for p, e in zip((4, 3, 2, 1), edges):
        if v < e:
            return p
    return 0


def metric_points(metric_id: str, v: float | None, metrics_cfg: dict) -> float | None:
    m = metrics_cfg["metrics"][metric_id]
    if v is None:
        return None
    if "points_map" in m:
        for rule in m["points_map"]:
            if "gt" in rule and v > rule["gt"]:
                return rule["points"]
            if "ge" in rule and v >= rule["ge"]:
                return rule["points"]
            if "le" in rule and v <= rule["le"]:
                return rule["points"]
            if "else" in rule:
                return rule["else"]
        return 0
    if m.get("dir") == "down_strict":
        return band_strict_down(v, m["bands"])
    return band(v, m["bands"], higher=m.get("dir", "up") == "up")


def rdown(x: float) -> float:
    """Composites: mean rounded DOWN to the nearest 0.5."""
    return math.floor(x * 2 + 1e-9) / 2


def composite(points: list[float | None], missing_as: float | None = None) -> float | None:
    vals = [p if p is not None else missing_as for p in points]
    vals = [v for v in vals if v is not None]
    return rdown(sum(vals) / len(vals)) if vals else None


def vi01(credits_floor: float, credits_ceil: float, n: int, penalty: int = 0, bands: list[float] | None = None):
    """Claim integrity → (pts_floor, pts_ceil, pct_floor, pct_ceil); −1 point per non-critical FALSE (min 0)."""
    b = bands or [90, 75, 60, 40]
    if n == 0:
        return None, None, None, None
    pf, pc = 100 * credits_floor / n, 100 * credits_ceil / n
    return max(band(pf, b) - penalty, 0), max(band(pc, b) - penalty, 0), pf, pc


def score(crit: dict[str, tuple[float, float, float]]) -> tuple[float, float]:
    """crit: id → (weight, pts_floor, pts_ceil). contribution = weight × points ÷ 4."""
    F = sum(w * pf / 4 for w, pf, pc in crit.values())
    C = sum(w * pc / 4 for w, pf, pc in crit.values())
    return round(F, 2), round(C, 2)


def rule(F: float, C: float) -> str:
    """Decision rule 2–5 (gates handled by the caller)."""
    if C < 50:
        return "negative"
    if F >= 75:
        return "positive"
    if F >= 50:
        return "positive_with_conditions"
    return "hold"


def requirement_status(floor_pts: float | None, ceil_pts: float | None, minimum: float) -> str:
    """met if floor ≥ min · unmet if ceiling < min · open otherwise (STANDARDS §5.1)."""
    if floor_pts is not None and floor_pts >= minimum:
        return "met"
    if ceil_pts is not None and ceil_pts < minimum:
        return "unmet"
    return "open"


CAP = {"positive": "positive_with_conditions", "positive_with_conditions": "hold", "hold": "negative", "negative": "negative",
       "RECOMMEND": "CONSIDER", "CONSIDER": "NOT RECOMMENDED", "NOT RECOMMENDED": "NOT RECOMMENDED"}


def health_grade(metric_points_by_pillar: dict[str, list[float | None]], cfg: dict, distress: bool = False) -> tuple[str | None, float | None, dict]:
    """Pillar = median of metric points (a 0 caps the pillar at 1); grade = mean of pillars (STANDARDS §4.5)."""
    hg = cfg["health_grade"]
    pillars: dict[str, float] = {}
    for name, pts in metric_points_by_pillar.items():
        vals = [p for p in pts if p is not None]
        if not vals:
            continue
        p = float(median(vals))
        if 0 in vals:
            p = min(p, float(hg.get("zero_caps_pillar_at", 1)))
        pillars[name] = p
    if not pillars:
        return None, None, {}
    mean = sum(pillars.values()) / len(pillars)
    grade = next((g["grade"] for g in hg["grade"] if "ge" in g and mean >= g["ge"]), "E")
    if distress and grade in ("A", "B"):
        grade = hg.get("distress_cap", "C")
    return grade, round(mean, 3), pillars


def lf_verdict(lfc: float | None, measurable: int, cfg: dict) -> str:
    c = cfg["composites"]["LF-C"]
    if lfc is None or measurable < c.get("min_measurable", 4):
        return "NOT ASSESSABLE"
    for v in c["verdicts"]:
        if "ge" in v and lfc >= v["ge"]:
            return v["label"]
    return "NOT FIT"
