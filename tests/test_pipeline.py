"""Six-step stage tracking and the outbox kinds."""
from app import outbox, pipeline, store
from app.crust import now_iso


def _run(did, mode, seq, status="done"):
    store.x("INSERT INTO runs (id, dossier_id, seq, status, started_at, progress, mode) VALUES (?,?,?,?,?,?,?)",
            (f"r_{did}_{seq}", did, seq, status, now_iso(), "[]", mode))


def test_stages_advance_and_can_skip(tmp_path, monkeypatch):
    store.init()
    did = pipeline.create_dossier("Acme", "https://www.acme.in/about")
    assert store.q("SELECT domain FROM dossiers WHERE id=?", (did,), one=True)["domain"] == "acme.in"
    steps = pipeline.stage(did)
    assert [s["done"] for s in steps] == [True, False, False, False, False, False]
    assert pipeline.current_step(steps) == "screen"

    # a deck that arrives unasked: CHECK without SCREEN / REACH OUT
    _run(did, "check", 1)
    assert pipeline.current_step(pipeline.stage(did)) == "request"

    row = outbox.draft(did, "intro", "bd@acme.example", "hi", "body", kind="intro")
    outbox.approve_and_send(row["idem_key"], "tester")
    _run(did, "screen", 2)
    _run(did, "check", 3)
    done = {s["key"]: s["done"] for s in pipeline.stage(did)}
    assert done == {"find": True, "screen": True, "reach_out": True, "check": True, "request": False, "recheck": True}

    # the intro and the request list are separate sends with separate keys
    req = outbox.draft(did, f"r_{did}_3", "bd@acme.example", "docs", "body", kind="request")
    assert req["idem_key"] != row["idem_key"] and req["kind"] == "request"
