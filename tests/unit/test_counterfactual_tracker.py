"""Unit tests: CounterfactualTracker service -- worker write-free contract, per-symbol
incremental flush, and the UPDATE-key immutability guard (review M3/M4, T-142B-04/06/08).

No live DB required -- these tests assert source-level contracts (grep/inspect) and exercise
the write path against a mocked asyncpg pool.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from unittest.mock import AsyncMock

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.counterfactual_tracker import (
    CounterfactualTracker,
    _run_counterfactual_worker,
    evaluate_frame_gate,
)

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

    executemany_mock = AsyncMock()

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        executemany = executemany_mock

    class _FakePool:
        def acquire(self):
            return _FakeConn()

    now = "2026-07-10T00:00:00Z"
    row_template = {
        "frame_id": "f",
        "bar_ts": now,
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
        "closed_at": now,
        "measured_at": now,
    }

    batches = [
        [dict(row_template, frame_id="a1"), dict(row_template, frame_id="a2")],
        [dict(row_template, frame_id="b1")],
        [dict(row_template, frame_id="c1"), dict(row_template, frame_id="c2")],
    ]

    total = asyncio.run(tracker._flush_worker_results(_FakePool(), iter(batches)))

    assert executemany_mock.await_count == 3
    assert total == 5


def test_flush_worker_results_skips_empty_batches():
    tracker = CounterfactualTracker(db_dsn="postgresql://unused/unused")
    executemany_mock = AsyncMock()

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return False

        executemany = executemany_mock

    class _FakePool:
        def acquire(self):
            return _FakeConn()

    total = asyncio.run(tracker._flush_worker_results(_FakePool(), iter([[], []])))
    assert executemany_mock.await_count == 0
    assert total == 0


# ---------------------------------------------------------------------------
# (c) UPDATE key + immutability guard (review M3)
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


# ---------------------------------------------------------------------------
# SQL query table references (Task 3: tradeable view boundary)
# ---------------------------------------------------------------------------


def test_atr_seed_and_bar_scan_sql_query_tradeable_view_not_raw_table():
    """_ATR_SEED_SQL / _BAR_SCAN_SQL must read market_data_ohlcv_tradeable, not the raw
    table (todo 035 / 2026-07-16 audit: a synthetic-fill or IBKR flat-carry-forward bar
    here means zero true range and a fabricated flat price feeding stop/target exit
    logic in determine_exit)."""
    import services.counterfactual_tracker as module

    assert "market_data_ohlcv_tradeable" in module._ATR_SEED_SQL
    assert "market_data_ohlcv_tradeable" in module._BAR_SCAN_SQL
    assert "FROM market_data_ohlcv\n" not in module._ATR_SEED_SQL
    assert "FROM market_data_ohlcv\n" not in module._BAR_SCAN_SQL
