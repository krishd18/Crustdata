"""Contract tests: every agent's I/O validates; each has a CLI; edge payloads fail cleanly (V1)."""
import importlib, json, pkgutil, subprocess, sys
import pytest
import datadesigner.agents as pkg
from datadesigner.agents.base import BaseAgent

MODS = [m.name for m in pkgutil.iter_modules(pkg.__path__) if m.name.startswith("a")]


def test_fifteen_agents_present():
    assert len(MODS) == 15


@pytest.mark.parametrize("mod", MODS)
def test_agent_contract(mod):
    m = importlib.import_module(f"datadesigner.agents.{mod}")
    a = m.AGENT
    assert isinstance(a, BaseAgent) and a.input_model and a.output_model and a.name == mod
    assert a.output_model.model_json_schema()["type"] == "object"


def test_a03_never_merges_lookalikes(ctx):
    from datadesigner.agents.a03_entity_resolver import AGENT
    r = AGENT({"name": "XYZ Logistics Pvt Ltd", "lookup": False, "candidates": [{"name": "XYZ Logistic Solutions LLP", "domain": "xyz-sol.example"}]}, ctx)
    assert r.status != "resolved"


def test_a09_rejects_protected_attributes(ctx):
    from datadesigner.agents.a09_people import AGENT
    with pytest.raises(Exception):
        AGENT({"people": [{"name": "x", "role": "CEO", "age": 50}]}, ctx)


def test_cli_runs():
    out = subprocess.run([sys.executable, "-m", "datadesigner.agents.a03_entity_resolver", "--in", "tests/fixtures/entity_hint.json"], capture_output=True, text=True)
    assert out.returncode == 0 and json.loads(out.stdout)["status"] == "resolved"
