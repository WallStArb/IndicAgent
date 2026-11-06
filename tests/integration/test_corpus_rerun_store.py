"""The runner's store on the real schema (186-31, migration 578, indicagent_test).

The data gate's persistence is one transaction: the data_gate column, the caveat (appended only
when no caveat carries its code) and the step's completion; a failure injected after the caveat
append leaves none of them. The adoption query reads only completed steps.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import psycopg
import pytest

import services.corpus_rerun as cr
from tests.integration.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration

CAVEAT = {"code": "survivorship_pre2016_ibkr_5m", "text": "biased", "counts": {"names": 3}}


@pytest.fixture()
def store():
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    assert conn.execute("SELECT current_database()").fetchone()[0] == "indicagent_test"
    run_id = str(uuid.uuid4())
    run = cr.CorpusRun(
        run_id=run_id,
        code_commit="a" * 40,
        code_key="c" * 64,
        horizon=datetime(2026, 11, 1, tzinfo=UTC),
        apr_hash="d" * 64,
        spans=((datetime(2010, 1, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)),),
        free_bytes_at_launch=700 * 10**9,
        caveats=(),
        measured={"row_counts": []},
    )
    store = cr.RunStore(conn)
    store.create_run(run)
    try:
        yield store, run_id
    finally:
        conn.execute("DELETE FROM corpus_run_step WHERE run_id = %s", (run_id,))
        # corpus_run's guard forbids identity changes, not deletes
        conn.execute("DELETE FROM corpus_run WHERE run_id = %s", (run_id,))
        conn.close()


def _state(store, run_id):
    row = store.conn.execute(
        "SELECT data_gate, caveats FROM corpus_run WHERE run_id = %s", (run_id,)
    ).fetchone()
    return row[0], row[1], store.step(run_id, "data_gate")


def test_the_run_round_trips(store):
    store_, run_id = store
    run = store_.load_run(run_id)
    assert run.spans[0][0] == datetime(2010, 1, 1, tzinfo=UTC) and run.caveats == ()


def test_the_data_gate_writes_result_caveat_and_completion_and_never_duplicates(store):
    store_, run_id = store
    store_.begin(run_id, "data_gate")
    store_.complete_data_gate(run_id, "data_gate", {"ok": True}, CAVEAT, {"ok": True})
    data_gate, caveats, step = _state(store_, run_id)
    assert data_gate == {"ok": True} and caveats == [CAVEAT] and step.status == "completed"
    # a retry (the step reset to started) re-records the result and keeps one caveat
    store_.conn.execute("UPDATE corpus_run_step SET status = 'failed' WHERE run_id = %s", (run_id,))
    store_.begin(run_id, "data_gate")
    store_.complete_data_gate(run_id, "data_gate", {"ok": True, "n": 2}, CAVEAT, {"ok": True})
    data_gate, caveats, step = _state(store_, run_id)
    assert data_gate == {"ok": True, "n": 2} and caveats == [CAVEAT]


def test_a_failure_after_the_caveat_append_leaves_nothing(store, monkeypatch):
    store_, run_id = store
    store_.begin(run_id, "data_gate")
    monkeypatch.setattr(
        cr,
        "FINISH_STEP_SQL",
        "UPDATE corpus_run_step SET status = %s, summary = %s "
        "WHERE run_id = %s AND step = %s AND 1 / 0 = 1",
    )
    with pytest.raises(psycopg.errors.DivisionByZero):
        store_.complete_data_gate(run_id, "data_gate", {"ok": True}, CAVEAT, {"ok": True})
    data_gate, caveats, step = _state(store_, run_id)
    assert data_gate is None and caveats == [] and step.status == "started"


def test_the_data_gate_completes_only_a_started_step(store):
    store_, run_id = store
    with pytest.raises(RuntimeError, match="is not started"):
        store_.complete_data_gate(run_id, "data_gate", {"ok": True}, CAVEAT, {"ok": True})
    data_gate, caveats, _ = _state(store_, run_id)
    assert data_gate is None and caveats == []


def test_a_completed_step_is_not_restarted_and_adoptions_come_from_completed_steps(store):
    store_, run_id = store
    other = str(uuid.uuid4())
    adopted = [{"unit_key": "u", "batch_key": "k1", "adopted_from_run_id": other}]
    store_.begin(run_id, "s1.1h")
    store_.finish(run_id, "s1.1h", "completed", {"adopted": adopted})
    store_.begin(run_id, "s1.1h")  # no-op on a completed row
    assert store_.step(run_id, "s1.1h").status == "completed"
    store_.begin(run_id, "s1.15m")
    store_.finish(run_id, "s1.15m", "failed", {"adopted": [{**adopted[0], "batch_key": "k2"}]})
    assert store_.adoptions(run_id) == {"k1": other}


def test_measured_merges_and_the_lock_is_exclusive(store):
    store_, run_id = store
    store_.merge_measured(run_id, {"bytes_per_row_max": 1400.0})
    assert store_.load_run(run_id).measured == {"row_counts": [], "bytes_per_row_max": 1400.0}
    assert store_.try_lock(run_id)
    with psycopg.connect(TEST_DB_URL, autocommit=True) as other:
        assert not cr.RunStore(other).try_lock(run_id)
