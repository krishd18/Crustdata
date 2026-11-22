"""A13 Memo Composer (STANDARDS §7): Jinja templates → Markdown → HTML (themed). Every number in the prose must
trace to the run's data (number lock); violations are reported and the offending lines dropped. Claude smoothing is
optional (config memo.smooth) and its output is re-checked by the same lock."""
from __future__ import annotations

from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel, Field

from ..core.ids import short
from ..core.types import BADGE
from ..memo.number_lock import allowed_from, lock_text
from .base import BaseAgent, cli

TPL = Path(__file__).resolve().parents[1] / "memo" / "templates"
NAMES = {"C1": "Claim integrity", "C2": "Financial health", "C3": "Growth", "C4": "Market position", "C5": "Governance", "C6": "Reputation & legal",
         "C7": "Mandate fit, verified", "C8": "Operational capacity", "C9": "Leadership fit", "C10": "Regional fit", "C11": "Tech soundness"}


class MemoInput(BaseModel):
    kind: str            # RESEARCH_MEMO | COMPANY_IM | MARKET_IM
    run_id: str
    data: dict
    title: str = ""
    cost: dict = Field(default_factory=dict)


class Memo(BaseModel):
    type: str
    id: str
    status: str
    md: str
    html: str
    json_: dict = Field(alias="json")
    number_lock_dropped: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class MemoComposer(BaseAgent[MemoInput, Memo]):
    name, input_model, output_model = "a13_memo", MemoInput, Memo

    def run(self, inp: MemoInput, ctx) -> Memo:
        env = Environment(loader=FileSystemLoader(str(TPL)), autoescape=False, trim_blocks=False)
        as_of = ctx.clock.now().strftime("%d %b %Y, %H:%M IST")
        mid = short({"RESEARCH_MEMO": "RM", "COMPANY_IM": "IM", "MARKET_IM": "MIM"}[inp.kind], inp.run_id, n=8)
        base = {"memo_id": mid, "as_of": as_of, "cost": inp.cost, "config_version": ctx.config.version, "rubric_version": ctx.config.rubric_version}
        if inp.kind == "RESEARCH_MEMO":
            d = inp.data
            md = env.get_template("research.md.j2").render(**base, title=inp.title, a=d["answer"], card=d["card"], windows=d["card"].get("time_windows", []))
            status = d["answer"]["status"]
        else:
            d = inp.data
            vmap = {v["claim_id"]: {**v, "badge": BADGE[v["cls"]]} for v in d["verdicts"]["verdicts"]}
            md = env.get_template("company.md.j2").render(**base, company=d.get("company", {}), profile=d.get("profile", "target"), d=d["decision"],
                                                           people=d["people"], market=d["market"], fin=d["financial"], claims=d["claims"]["claims"],
                                                           vmap=vmap, counts=d["verdicts"]["counts_by_class"], evidence=d["evidence"]["accepted"],
                                                           names=NAMES, status="DRAFT — awaiting decision" if not d.get("human_decision") else "DECIDED",
                                                           decision=d.get("human_decision"), decider=d.get("decider", "Head of Corporate Development"))
            status = "DRAFT" if not d.get("human_decision") else "DECIDED"
        allowed = allowed_from({**inp.data, **base}) | {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "100", "50", "75", "60"}
        locked, dropped = lock_text(md, allowed)
        if dropped:
            ctx.log.warning("a13.number_lock_dropped", n=len(dropped))
        html = markdown.markdown(locked, extensions=["tables"])
        return Memo(type=inp.kind, id=mid, status=status, md=locked, html=html, json={"memo_id": mid, "type": inp.kind, "status": status, "as_of": as_of,
                    "config_version": ctx.config.version, "rubric_version": ctx.config.rubric_version, "cost": inp.cost},
                    number_lock_dropped=dropped)


AGENT = MemoComposer()
if __name__ == "__main__":
    raise SystemExit(cli(AGENT))
