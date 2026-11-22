"""A15 Monitor / Re-check (ARCHITECTURE §18): diff two snapshots of a run (verdicts, metrics, score, label).
Triggers (schedule, watcher webhook, new documents) re-run the CHECK flow with the same rubric version."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .base import BaseAgent, cli


class Snapshots(BaseModel):
    before: dict
    after: dict


class Diff(BaseModel):
    claims_changed: list[dict] = Field(default_factory=list)
    metrics_moved: list[dict] = Field(default_factory=list)
    score_before: list[float] | None = None
    score_after: list[float] | None = None
    label_before: str | None = None
    label_after: str | None = None
    decision_changed: bool = False


class Monitor(BaseAgent[Snapshots, Diff]):
    name, input_model, output_model = "a15_monitor", Snapshots, Diff

    def run(self, inp: Snapshots, ctx) -> Diff:
        b, a = inp.before, inp.after
        vb = {v["claim_id"]: v for v in (b.get("verdicts") or {}).get("verdicts", [])}
        va = {v["claim_id"]: v for v in (a.get("verdicts") or {}).get("verdicts", [])}
        ch = [{"claim_id": k, "before": f"{vb[k]['cls']}/{vb[k]['code']}", "after": f"{va[k]['cls']}/{va[k]['code']}"}
              for k in va if k in vb and (vb[k]["cls"], vb[k]["code"]) != (va[k]["cls"], va[k]["code"])]
        mb = {m["id"]: m for m in (b.get("financial") or {}).get("metrics", [])}
        mm = [{"id": m["id"], "before": mb[m["id"]]["points"], "after": m["points"]} for m in (a.get("financial") or {}).get("metrics", [])
              if m["id"] in mb and mb[m["id"]]["points"] != m["points"]]
        db, da = b.get("decision") or {}, a.get("decision") or {}
        return Diff(claims_changed=ch, metrics_moved=mm, score_before=[db.get("floor"), db.get("ceiling")] if db else None,
                    score_after=[da.get("floor"), da.get("ceiling")] if da else None, label_before=db.get("label"), label_after=da.get("label"),
                    decision_changed=db.get("label") != da.get("label"))


AGENT = Monitor()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
