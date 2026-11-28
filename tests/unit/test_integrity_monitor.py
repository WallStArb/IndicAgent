"""Unit tests: src/core/integrity_monitor.py -- the shared emit_integrity_fact
helper (todo 150).

Before this extraction, the exact `INSERT INTO integrity_monitor ... ON CONFLICT
(monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at)
DO NOTHING` statement shape was hand-copied at 4 independent call sites
(services/ic_engine.py x2, src/config/vocabulary_drift.py, services/
forward_return_writer.py). These tests exercise the asyncpg helpers directly against mock connections, no real DB.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.core.integrity_monitor import (
    INTEGRITY_MONITOR_INSERT_SQL,
    emit_integrity_fact_async,
    emit_integrity_facts_async,
)

# ---------------------------------------------------------------------------
# SQL shape sanity (mirrors test_ic_engine_idempotency.py's pattern of asserting
# directly on the SQL text -- the exact ON CONFLICT clause is the correctness-
# critical part the todo calls out as a drift risk).
# ---------------------------------------------------------------------------


def test_insert_sql_has_idempotent_on_conflict_do_nothing():
    assert "ON CONFLICT" in INTEGRITY_MONITOR_INSERT_SQL
    assert "DO NOTHING" in INTEGRITY_MONITOR_INSERT_SQL


def test_insert_sql_on_conflict_key_matches_migration_211_unique_index():
    # production/migrations/211_integrity_monitor.sql's unique index is keyed on
    # (monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at).
    assert (
        "monitor_type, training_window_end, metric_name, COALESCE(subject, '')"
        in INTEGRITY_MONITOR_INSERT_SQL
    )


def test_insert_sql_targets_integrity_monitor_table():
    assert "INSERT INTO integrity_monitor" in INTEGRITY_MONITOR_INSERT_SQL


# ---------------------------------------------------------------------------
# Async helper (asyncpg-style conn)
# ---------------------------------------------------------------------------


def _mock_async_conn(precheck_hit: bool = False) -> MagicMock:
    conn = MagicMock()
    conn.execute = AsyncMock()
    conn.fetchval = AsyncMock(return_value=1 if precheck_hit else None)
    return conn


@pytest.mark.asyncio
async def test_emit_async_inserts_with_all_fields_bound():
    conn = _mock_async_conn()

    await emit_integrity_fact_async(
        conn,
        "vocabulary_drift",
        "regime_hmm",
        "unregistered_code_count",
        2.0,
        0.0,
        False,
        None,
    )

    conn.execute.assert_awaited_once()
    args = conn.execute.call_args.args
    assert "INSERT INTO integrity_monitor" in args[0]
    assert args[1:] == (
        "vocabulary_drift",
        "regime_hmm",
        "unregistered_code_count",
        2.0,
        0.0,
        False,
        None,
    )


@pytest.mark.asyncio
async def test_emit_async_no_idempotency_check_by_default():
    conn = _mock_async_conn()

    await emit_integrity_fact_async(
        conn, "vocabulary_drift", "regime_hmm", "unregistered_code_count", 2.0, 0.0, False, None
    )

    conn.fetchval.assert_not_awaited()
    conn.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_emit_async_idempotency_check_skips_insert_when_already_ran():
    conn = _mock_async_conn(precheck_hit=True)

    await emit_integrity_fact_async(
        conn,
        "price_sanity",
        None,
        "rows_flagged_suspect",
        5.0,
        None,
        True,
        "2026-01-01",
        idempotency_check=True,
    )

    conn.fetchval.assert_awaited_once()
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_async_guards_insert_failure_log_and_continue():
    conn = _mock_async_conn()
    conn.execute.side_effect = Exception("boom")

    # Must not raise.
    await emit_integrity_fact_async(
        conn, "vocabulary_drift", "regime_hmm", "unregistered_code_count", 2.0, 0.0, False, None
    )
    conn.execute.assert_awaited_once()  # the insert was attempted, and its failure swallowed


# ---------------------------------------------------------------------------
# Async batch helper
# ---------------------------------------------------------------------------

_FACTS = [
    ("m", "a|tf=1d", "symbol_coverage", 0.1, 0.95, False, "w"),
    ("m", None, "n_failed", 1.0, 0.0, False, "w"),
]


@pytest.mark.asyncio
async def test_emit_facts_async_writes_one_executemany_with_the_single_fact_insert():
    conn = MagicMock()
    conn.executemany = AsyncMock()
    conn.execute = AsyncMock()
    await emit_integrity_facts_async(conn, _FACTS)
    conn.executemany.assert_awaited_once()
    sql, rows = conn.executemany.call_args.args
    assert "INSERT INTO integrity_monitor" in sql and "ON CONFLICT" in sql
    assert rows == _FACTS
    conn.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_facts_async_no_facts_is_no_round_trip():
    conn = MagicMock()
    conn.executemany = AsyncMock()
    await emit_integrity_facts_async(conn, [])
    conn.executemany.assert_not_awaited()


@pytest.mark.asyncio
async def test_emit_facts_async_batch_failure_falls_back_to_per_fact_and_never_raises():
    conn = MagicMock()
    conn.executemany = AsyncMock(side_effect=RuntimeError("bad row"))
    written = []

    async def execute(sql, *args):
        if args[1] is None:
            raise RuntimeError("still bad")  # one fact fails on its own; the other still lands
        written.append(args)

    conn.execute = execute
    await emit_integrity_facts_async(conn, _FACTS)
    assert written == [_FACTS[0]]
