"""Flush the pipeline: hide every target, stop their runs, never touch the send journal."""
import uuid

from app import outbox, pipeline, store
from app.crust import now_iso


def _setup():
    store.init()
    store.x("UPDATE dossiers SET flushed_at='0000' WHERE flushed_at IS NULL")  # isolate from other tests
    store.x("UPDATE searches SET flushed_at='0000' WHERE flushed_at IS NULL")
    a = pipeline.create_dossier("Alpha", "alpha.example", company_id=101)
    b = pipeline.create_dossier("Beta", "beta.example")
    rid = f"r_fl{uuid.uuid4().hex[:6]}"
    store.x("INSERT INTO runs (id,dossier_id,seq,status,started_at,progress,mode) VALUES (?,?,1,'running',?,'[]','screen')",
            (rid, a, now_iso()))
    store.x("INSERT INTO searches (id, thesis, created_at, result, credits) VALUES (?,'x',?,'{}',1)",
            (f"s_fl{uuid.uuid4().hex[:6]}", now_iso()))
    draft = outbox.draft(b, "intro", "deals@beta.example", "Hello", f"body {rid}", kind="intro")
    return a, b, draft, rid


def test_flush_hides_targets_stops_runs_and_keeps_the_journal():
    a, b, draft, rid = _setup()
    p = pipeline.flush_preview()
    assert (p["targets"], p["running"], p["drafts"], p["searches"]) == (2, 1, 1, 1)

    out = pipeline.flush(searches=False)
    assert out["targets"] == 2 and out["stopped_runs"] == 1 and out["searches"] == 0
    assert store.q("SELECT status FROM runs WHERE id=?", (rid,), one=True)["status"] == "cancelled"
    assert pipeline.flush_preview()["targets"] == 0
    assert pipeline.flush_preview()["searches"] == 1  # searches kept unless asked
    # nothing deleted: the send journal row is still there
    assert store.q("SELECT idem_key FROM outbox WHERE idem_key=?", (draft["idem_key"],), one=True)


def test_re_adding_a_flushed_company_starts_fresh_and_restore_brings_targets_back():
    a, b, _, _ = _setup()
    pipeline.flush(searches=True)
    assert pipeline.flush_preview()["searches"] == 0
    store.x("INSERT INTO searches (id, thesis, created_at, result, credits) VALUES ('s_fl2','x',?,?,1)",
            (now_iso(), '{"rows":[{"crustdata_company_id":101,"name":"Alpha","domain":"alpha.example"}],"thesis":"x"}'))
    [new] = pipeline.add_from_search("s_fl2", [101])
    assert new != a  # a fresh dossier, not the flushed one

    store.x("DELETE FROM dossiers WHERE id=?", (new,))
    r = pipeline.restore_last_flush()
    assert r == {"targets": 2, "searches": 1}
    live = {d["id"] for d in store.q("SELECT id FROM dossiers WHERE flushed_at IS NULL")}
    assert {a, b} <= live


def test_delete_one_target_stops_its_run_hides_it_and_undo_restores():
    a, b, draft, rid = _setup()
    out = pipeline.delete_target(a)
    assert out["stopped_runs"] == 1
    assert store.q("SELECT status FROM runs WHERE id=?", (rid,), one=True)["status"] == "cancelled"
    live = {d["id"] for d in store.q(f"SELECT id FROM dossiers WHERE {pipeline.LIVE}")}
    assert a not in live and b in live
    assert pipeline.flush_preview()["targets"] == 1  # a flush won't count or touch the deleted one
    pipeline.undelete_target(a)
    assert a in {d["id"] for d in store.q(f"SELECT id FROM dossiers WHERE {pipeline.LIVE}")}
