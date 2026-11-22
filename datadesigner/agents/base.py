"""BaseAgent contract + shared CLI (docs/AGENTS.md §1): `python -m datadesigner.agents.aNN --in fixture.json --mode replay`."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Generic, TypeVar

from pydantic import BaseModel

I = TypeVar("I", bound=BaseModel)
O = TypeVar("O", bound=BaseModel)


class BaseAgent(Generic[I, O]):
    name: str = "agent"
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    deterministic: bool = True

    def run(self, inp: I, ctx) -> O:  # pragma: no cover - interface
        raise NotImplementedError

    def __call__(self, inp, ctx):
        if isinstance(inp, dict):
            inp = self.input_model.model_validate(inp)
        out = self.run(inp, ctx)
        return self.output_model.model_validate(out) if isinstance(out, dict) else out


def cli(agent: BaseAgent, argv: list[str] | None = None) -> int:
    from ..core.context import make_context
    from ..core.stores import Stores
    ap = argparse.ArgumentParser(prog=f"python -m datadesigner.agents.{agent.name}")
    ap.add_argument("--in", dest="inp", required=True, help="input fixture JSON")
    ap.add_argument("--mode", default="replay", choices=["live", "record", "replay"])
    ap.add_argument("--family", default="FIND_LIST")
    ap.add_argument("--now", default="2026-11-22T16:30:00+05:30")
    ap.add_argument("--db", default=":memory:")
    a = ap.parse_args(argv)
    data = json.loads(open(a.inp).read())
    ctx = make_context(run_id=f"cli-{agent.name}", family=a.family, mode=a.mode, frozen_now=a.now, stores=Stores(a.db))
    out = agent(data, ctx)
    sys.stdout.write(out.model_dump_json(indent=1) + "\n")
    return 0
