"""The runner's store on the real schema (186-31, migration 578, indicagent_test).

The data gate's persistence is one transaction: the data_gate column, the caveat (appended only
when no caveat carries its code) and the step's completion; a failure injected after the caveat
append leaves none of them. The adoption query reads only completed steps.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

import services.corpus_rerun as cr
from tests.integration.conftest import TEST_DB_URL

pytestmark = pytest.mark.integration

CAVEAT = {"code": "survivorship_pre_alpaca_era_5m", "text": "biased", "counts": {"names": 3}}


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
    assert store_.try_lock()
    with psycopg.connect(TEST_DB_URL, autocommit=True) as other:
        assert not cr.RunStore(other).try_lock()  # one corpus rerun at a time, any run id


def test_loaded_rows_and_pooled_lookaheads_read_the_real_schema(store):
    store_, run_id = store
    lo, hi = datetime(2010, 1, 1, tzinfo=UTC), datetime(2013, 1, 1, tzinfo=UTC)
    assert store_.loaded_rows(run_id, "5m", lo, hi) == 0
    assert isinstance(store_.pooled_lookaheads(), dict)


def test_the_compression_ratio_is_measured_on_a_scratch_copy(store):
    """Rows of a test symbol are copied into a scratch hypertable with feature_vectors' own
    compression settings, compressed and measured; feature_vectors' chunks stay as they were
    and the scratch table is gone."""
    from src.intelligence.features.feature_vector_persistence import (
        feature_vector_row_values,
        feature_vectors_columns,
        feature_vectors_numeric_columns,
    )

    store_, _run_id = store
    conn = store_.conn
    symbol = f"ZZ31{uuid.uuid4().hex[:6].upper()}"
    columns = feature_vectors_columns()
    width = len(feature_vectors_numeric_columns())
    base = datetime(2001, 1, 2, tzinfo=UTC)
    rows = [
        feature_vector_row_values(
            symbol, "1d", base + timedelta(days=i), None, None, [float(i % 7)] * width
        )
        for i in range(400)
    ]
    chunks_before = conn.execute(
        "SELECT count(*) FILTER (WHERE is_compressed) FROM timescaledb_information.chunks "
        "WHERE hypertable_name = 'feature_vectors'"
    ).fetchone()[0]
    with (
        conn.cursor() as cur,
        cur.copy(f"COPY feature_vectors ({', '.join(columns)}) FROM STDIN") as copy,
    ):
        for row in rows:
            copy.write_row(row)
    try:
        measured = cr.measure_compression(conn, [symbol], "1d")
    finally:
        conn.execute("DELETE FROM feature_vectors WHERE symbol = %s", (symbol,))
    assert measured["rows"] == 400
    assert measured["ratio"] and measured["ratio"] > 1
    assert measured["compressed_bytes"] < measured["uncompressed_bytes"]
    left = conn.execute(
        "SELECT count(*) FROM pg_tables WHERE schemaname = 'corpus_rerun_scratch'"
    ).fetchone()[0]
    assert left == 0
    chunks_after = conn.execute(
        "SELECT count(*) FILTER (WHERE is_compressed) FROM timescaledb_information.chunks "
        "WHERE hypertable_name = 'feature_vectors'"
    ).fetchone()[0]
    assert chunks_after == chunks_before


def _provenance_row(conn) -> str:
    key = uuid.uuid4().hex + uuid.uuid4().hex
    conn.execute(
        "INSERT INTO provenance_batch (batch_key, writer, target_table, time_column, tf, "
        "range_start, range_end, symbols, symbols_hash, code_key, apr_hash, apr_snapshot, "
        "input_digest, unit_key) VALUES (%s, 'test-583', 'feature_vectors', 'bar_ts', '1d', "
        "'2020-01-01', '2021-01-01', ARRAY['ZZ583'], %s, %s, %s, '{}'::jsonb, %s, %s)",
        (key, "a" * 64, "c" * 64, "d" * 64, "e" * 64, key),
    )
    return key


class _RollBack(Exception):
    """Ends the test's transaction: provenance_batch is append only, so nothing is deleted."""


def test_unit_stats_are_set_with_the_completion_and_frozen_after(store):
    """Migration 583: unit_stats moves only on started -> completed; a completed row's
    unit_stats cannot change, including on the completed -> superseded flip. All inside one
    rolled-back transaction, each refusal in its own savepoint."""
    store_, _run_id = store
    conn = store_.conn
    stats = '{"swing_high_dist_atr": {"present": 10, "nan_present": 1}}'

    def refused(sql: str, params: tuple, match: str = "") -> None:
        with pytest.raises(psycopg.errors.CheckViolation, match=match), conn.transaction():
            conn.execute(sql, params)

    with contextlib.suppress(_RollBack), conn.transaction():
        key = _provenance_row(conn)
        refused(
            "UPDATE provenance_batch SET status = 'failed', unit_stats = %s::jsonb "
            "WHERE batch_key = %s",
            (stats, key),
            "unit_stats is set only",
        )
        conn.execute(
            "UPDATE provenance_batch SET status = 'completed', row_count = 3, finished_at = now(), "
            "unit_stats = %s::jsonb WHERE batch_key = %s",
            (stats, key),
        )
        assert store_.unit_stats([key])[0][2]["swing_high_dist_atr"]["nan_present"] == 1
        refused("UPDATE provenance_batch SET unit_stats = '{}'::jsonb WHERE batch_key = %s", (key,))
        refused(
            "UPDATE provenance_batch SET status = 'superseded', unit_stats = NULL "
            "WHERE batch_key = %s",
            (key,),
        )
        conn.execute(
            "UPDATE provenance_batch SET status = 'superseded' WHERE batch_key = %s", (key,)
        )
        raise _RollBack
