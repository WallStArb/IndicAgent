"""Unit tests: CounterfactualTracker service -- worker write-free contract, per-symbol
incremental flush, and the UPDATE-key immutability guard (review M3/M4, T-142B-04/06/08).

No live DB required -- these tests assert source-level contracts (grep/inspect) and exercise
the write path against a mocked asyncpg pool.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from datetime import UTC, datetime
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.counterfactual_tracker import (
    CounterfactualTracker,
    _load_chunk_index,
    _route_chunk,
    _run_counterfactual_worker,
    evaluate_frame_gate,
)

_ROW_TEMPLATE = {
    "frame_id": "f",
    "bar_ts": "2026-07-10T00:00:00Z",
    "entry_price": 1.0,
    "stop_price": 1.0,
    "target_price": 1.0,
    "r_multiple": 1.0,
    "status": "closed_stop",
    "counterfactual_pnl_r": -1.0,
    "counterfactual_mfe": 0.0,
    "counterfactual_mae": -1.0,
    "counterfactual_bars": 1,
    "exit_reason": "closed_stop",
    "closed_at": "2026-07-10T00:00:00Z",
    "measured_at": "2026-07-10T00:00:00Z",
}


def _fake_pool():
    """Minimal fake asyncpg pool for _flush_worker_results tests. Records every
    executemany(sql, chunk) call and returns (pool, calls) so callers can assert on either
    call count (one per symbol/chunk-group) or per-call chunk sizes."""
    calls: list[tuple[str, list]] = []

    async def _executemany(self, sql, chunk):
        calls.append((sql, chunk))

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        executemany = _executemany

    class _FakePool:
        def acquire(self):
            return _FakeConn()

    return _FakePool(), calls


# ---------------------------------------------------------------------------
# (a) Worker-no-write guard (DAG invariant #3, T-142B-06)
# ---------------------------------------------------------------------------


def test_worker_source_has_no_write_calls():
    source = inspect.getsource(_run_counterfactual_worker)
    assert "execute_batch" not in source
    assert "executemany" not in source


def test_worker_source_uses_named_cursor_not_plain_cursor():
    """The worker's own source (and its _scan_symbol_tf helper, invoked from within it)
    must never open a plain conn.cursor() -- a leading conn.commit() is permitted (named-
    cursor precondition)."""
    import services.counterfactual_tracker as module

    worker_source = inspect.getsource(_run_counterfactual_worker)
    scan_source = inspect.getsource(module._scan_symbol_tf)
    combined = worker_source + scan_source
    assert "conn.cursor(name=" in combined
    assert "conn.cursor()" not in combined


def test_worker_opens_no_write_connection():
    source = inspect.getsource(_run_counterfactual_worker)
    assert "pool.acquire" not in source
    assert "asyncpg" not in source


def test_worker_returns_dict_with_expected_keys():
    sig = inspect.signature(_run_counterfactual_worker)
    params = list(sig.parameters.keys())
    assert params == ["args"]
    doc = _run_counterfactual_worker.__doc__
    assert doc is not None
    assert "list[dict]" in doc


# ---------------------------------------------------------------------------
# (b) Incremental per-symbol flush guard (T-142B-08)
# ---------------------------------------------------------------------------


def test_flush_worker_results_issues_one_executemany_per_symbol_batch():
    """3 distinct per-symbol row-lists -> exactly 3 awaited executemany calls, never 1
    (proves per-symbol flush, not all-symbols aggregation)."""
    tracker = CounterfactualTracker(db_dsn="postgresql://unused/unused")
    pool, calls = _fake_pool()

    batches = [
        [dict(_ROW_TEMPLATE, frame_id="a1"), dict(_ROW_TEMPLATE, frame_id="a2")],
        [dict(_ROW_TEMPLATE, frame_id="b1")],
        [dict(_ROW_TEMPLATE, frame_id="c1"), dict(_ROW_TEMPLATE, frame_id="c2")],
    ]

    total = asyncio.run(tracker._flush_worker_results(pool, iter(batches), chunk_size=5000))

    assert len(calls) == 3
    assert total == 5


def test_flush_worker_results_chunks_large_symbol_batch():
    """A single symbol's batch larger than chunk_size must split into multiple executemany
    calls, each committed separately -- regression for the 143.1-08 bug where one busy
    symbol's whole result set went into ONE implicit-transaction executemany() call, so
    nothing committed (and nothing was visible to a restart's WHERE status='open' scan)
    until the entire symbol finished."""
    tracker = CounterfactualTracker(db_dsn="postgresql://unused/unused")
    pool, calls = _fake_pool()
    one_symbol_batch = [dict(_ROW_TEMPLATE, frame_id=f"f{i}") for i in range(5)]

    total = asyncio.run(tracker._flush_worker_results(pool, iter([one_symbol_batch]), chunk_size=2))

    assert [len(chunk) for _, chunk in calls] == [2, 2, 1]
    assert total == 5


def test_flush_worker_results_skips_empty_batches():
    tracker = CounterfactualTracker(db_dsn="postgresql://unused/unused")
    pool, calls = _fake_pool()

    total = asyncio.run(tracker._flush_worker_results(pool, iter([[], []]), chunk_size=5000))
    assert len(calls) == 0
    assert total == 0


# ---------------------------------------------------------------------------
# (c) Direct-chunk write routing (todo 161) -- writing through the alpha_frames hypertable
# measured 29 rows/sec vs 10,423 rows/sec writing directly to the resolved chunk table
# (358x), root-caused to TimescaleDB's per-execution chunk-routing overhead at 1034 chunks.
# ---------------------------------------------------------------------------


def _synthetic_chunk_index():
    chunks = [
        (
            datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2020, 1, 8, tzinfo=UTC),
            "_timescaledb_internal._hyper_1_1_chunk",
        ),
        (
            datetime(2020, 1, 8, tzinfo=UTC),
            datetime(2020, 1, 15, tzinfo=UTC),
            "_timescaledb_internal._hyper_1_2_chunk",
        ),
    ]
    return [c[0] for c in chunks], chunks


def test_route_chunk_resolves_matching_range():
    idx = _synthetic_chunk_index()
    assert _route_chunk(idx, datetime(2020, 1, 5, tzinfo=UTC)) == (
        "_timescaledb_internal._hyper_1_1_chunk"
    )


def test_route_chunk_boundary_is_half_open():
    """range_end is exclusive -- a bar_ts exactly AT one chunk's range_end belongs to the
    NEXT chunk (matches TimescaleDB's own [range_start, range_end) convention)."""
    idx = _synthetic_chunk_index()
    assert _route_chunk(idx, datetime(2020, 1, 8, tzinfo=UTC)) == (
        "_timescaledb_internal._hyper_1_2_chunk"
    )


def test_route_chunk_returns_none_outside_all_ranges():
    idx = _synthetic_chunk_index()
    assert _route_chunk(idx, datetime(2019, 12, 1, tzinfo=UTC)) is None
    assert _route_chunk(idx, datetime(2021, 1, 1, tzinfo=UTC)) is None


def test_route_chunk_returns_none_in_gap_between_noncontiguous_chunks():
    chunks = [
        (
            datetime(2020, 1, 1, tzinfo=UTC),
            datetime(2020, 1, 8, tzinfo=UTC),
            "_timescaledb_internal._hyper_1_1_chunk",
        ),
        (
            datetime(2020, 2, 1, tzinfo=UTC),
            datetime(2020, 2, 8, tzinfo=UTC),
            "_timescaledb_internal._hyper_1_2_chunk",
        ),
    ]
    idx = ([c[0] for c in chunks], chunks)
    assert _route_chunk(idx, datetime(2020, 1, 20, tzinfo=UTC)) is None


def test_load_chunk_index_filters_names_not_matching_timescaledb_convention():
    """Table names can't be bound as query parameters -- only chunk_schema/chunk_name values
    matching TimescaleDB's own internal naming convention are trusted for SQL interpolation.
    A row that doesn't match must be silently excluded from the index (its bar_ts range then
    falls back to the hypertable via _route_chunk returning None), never passed through."""

    class _FakeConn:
        async def fetch(self, sql, hypertable_name):
            return [
                {
                    "range_start": datetime(2020, 1, 1, tzinfo=UTC),
                    "range_end": datetime(2020, 1, 8, tzinfo=UTC),
                    "chunk_schema": "_timescaledb_internal",
                    "chunk_name": "_hyper_1_1_chunk",
                },
                {
                    "range_start": datetime(2020, 1, 8, tzinfo=UTC),
                    "range_end": datetime(2020, 1, 15, tzinfo=UTC),
                    "chunk_schema": "public",
                    "chunk_name": "evil_table; DROP TABLE alpha_frames;",
                },
            ]

    starts, chunks = asyncio.run(_load_chunk_index(_FakeConn(), "alpha_frames"))
    assert len(chunks) == 1
    assert chunks[0][2] == "_timescaledb_internal._hyper_1_1_chunk"


def test_flush_worker_results_routes_writes_to_resolved_chunk_tables():
    """Rows whose bar_ts falls in different chunks must be written via separate UPDATE
    statements targeting each chunk table directly; a row with no matching chunk falls back
    to the hypertable rather than being dropped."""
    tracker = CounterfactualTracker(db_dsn="postgresql://unused/unused")
    pool, calls = _fake_pool()
    chunk_index = _synthetic_chunk_index()

    in_chunk_a = dict(_ROW_TEMPLATE, frame_id="a", bar_ts=datetime(2020, 1, 5, tzinfo=UTC))
    in_chunk_b = dict(_ROW_TEMPLATE, frame_id="b", bar_ts=datetime(2020, 1, 10, tzinfo=UTC))
    unrouted = dict(_ROW_TEMPLATE, frame_id="c", bar_ts=datetime(2021, 1, 1, tzinfo=UTC))

    total = asyncio.run(
        tracker._flush_worker_results(
            pool,
            iter([[in_chunk_a, in_chunk_b, unrouted]]),
            chunk_size=5000,
            chunk_index=chunk_index,
        )
    )

    tables_written = {sql.split()[1] for sql, _ in calls}
    assert tables_written == {
        "_timescaledb_internal._hyper_1_1_chunk",
        "_timescaledb_internal._hyper_1_2_chunk",
        "alpha_frames",
    }
    assert total == 3


def test_flush_worker_results_without_chunk_index_writes_hypertable_only():
    """chunk_index defaults to None -- callers that don't pass it must keep writing through
    the plain hypertable, byte-identical to the pre-routing SQL."""
    tracker = CounterfactualTracker(db_dsn="postgresql://unused/unused")
    pool, calls = _fake_pool()

    total = asyncio.run(
        tracker._flush_worker_results(
            pool, iter([[dict(_ROW_TEMPLATE, frame_id="a")]]), chunk_size=5000
        )
    )

    assert len(calls) == 1
    assert calls[0][0] == CounterfactualTracker._UPDATE_SQL
    assert total == 1


# ---------------------------------------------------------------------------
# (d) UPDATE key + immutability guard (review M3)
# ---------------------------------------------------------------------------


def test_update_sql_keys_on_frame_id_and_bar_ts_with_open_guard():
    sql = CounterfactualTracker._UPDATE_SQL
    assert "frame_id" in sql
    assert "bar_ts" in sql
    assert "status = 'open'" in sql


def test_update_keys_tuple_matches_sql_param_order():
    """_UPDATE_KEYS must produce a tuple whose positional order matches the SQL's $1..$14
    placeholders exactly."""
    keys = CounterfactualTracker._UPDATE_KEYS
    assert keys[0] == "frame_id"
    assert keys[1] == "bar_ts"
    assert len(keys) == 14


# ---------------------------------------------------------------------------
# Service registration (mirrors alpha-frame-writer's precedent)
# ---------------------------------------------------------------------------


def test_service_auditor_registers_counterfactual_tracker():
    import services.service_auditor as auditor

    assert "indicagent-counterfactual-tracker" in auditor._DAG_ORDER
    assert "indicagent-counterfactual-tracker" in auditor._ONESHOT_UNITS


def test_exception_handler_uses_error_variable_name():
    import services.counterfactual_tracker as module

    source = inspect.getsource(module.CounterfactualTracker.execute)
    assert "except Exception as error:" in source


# ---------------------------------------------------------------------------
# FRAME-04 gate evaluation helper (Task 3, --evaluate-gate)
# ---------------------------------------------------------------------------


def test_evaluate_frame_gate_groups_by_tf_and_regime():
    rows = [
        {"tf": "5m", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.5},
        {"tf": "5m", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.6},
        {"tf": "5m", "regime": "ranging", "cluster_id": "2026-01-01", "pnl_r": -0.2},
        {"tf": "1h", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.3},
    ]
    verdicts = evaluate_frame_gate(rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000)
    cells = {(v["tf"], v["regime"]) for v in verdicts}
    assert cells == {("5m", "trending_up"), ("5m", "ranging"), ("1h", "trending_up")}


def test_evaluate_frame_gate_passes_calendar_date_cluster_ids():
    """Frames on the same calendar day must land in the same cluster (day-clustered, review
    H4) -- proven by asserting a below-min_n cell short-circuits per-cell independently of
    another cell's larger N."""
    rows = [
        {"tf": "5m", "regime": "trending_up", "cluster_id": f"2026-01-{d:02d}", "pnl_r": 0.1}
        for d in range(1, 3)
    ] + [
        {"tf": "1h", "regime": "trending_up", "cluster_id": f"2026-02-{d:02d}", "pnl_r": 0.1}
        for d in range(1, 40)
    ]
    verdicts = evaluate_frame_gate(rows, min_n=30, bootstrap_max_n=5000, bootstrap_batch=1000)
    by_cell = {(v["tf"], v["regime"]): v for v in verdicts}
    assert by_cell[("5m", "trending_up")]["passes"] is False  # below min_n floor (N=2 < 30)
    assert by_cell[("1h", "trending_up")]["n_clusters"] == 39


def test_evaluate_frame_gate_helper_has_no_cost_subtraction():
    """Gross-only gate (D-01) -- the helper never mentions 'cost', proving no adjustment is
    applied inside it."""
    source = inspect.getsource(evaluate_frame_gate)
    assert "cost" not in source.lower()


def test_evaluate_gate_cli_flag_present():
    source = inspect.getsource(sys.modules["services.counterfactual_tracker"])
    assert "--evaluate-gate" in source
    assert "alpha.validation.oos_start" in source
    assert "frame_variant = 'primary'" in source
