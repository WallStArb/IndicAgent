"""Unit tests: src/core/integrity_monitor.py -- the shared emit_integrity_fact
helper (todo 150).

Before this extraction, the exact `INSERT INTO integrity_monitor ... ON CONFLICT
(monitor_type, training_window_end, metric_name, COALESCE(subject, ''), evaluated_at)
DO NOTHING` statement shape was hand-copied at 4 independent call sites
(services/ic_engine.py x2, src/config/vocabulary_drift.py, services/
forward_return_writer.py). These tests exercise the sync (psycopg2-style) and async
(asyncpg-style) helpers directly against fake/mock connections -- no real DB.
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
    emit_integrity_fact_sync,
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
# Sync helper (psycopg2-style conn/cursor)
# ---------------------------------------------------------------------------


def _mock_sync_conn(precheck_hit: bool = False) -> MagicMock:
    cur = MagicMock()
    cur.fetchone.return_value = (1,) if precheck_hit else None
    cur.__enter__.return_value = cur
    cur.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def test_emit_sync_inserts_with_all_fields_bound():
    conn = _mock_sync_conn()

    emit_integrity_fact_sync(
        conn,
        "ic_lifecycle",
        None,
        "decay_cells_flagged",
        3.0,
        0.005,
        True,
        "2026-01-01T00:00:00+00:00",
    )

    cur = conn.cursor.return_value
    cur.execute.assert_called_once_with(
        INTEGRITY_MONITOR_INSERT_SQL,
        (
            "ic_lifecycle",
            None,
            "decay_cells_flagged",
            3.0,
            0.005,
            True,
            "2026-01-01T00:00:00+00:00",
        ),
    )


def test_emit_sync_does_not_commit_by_default():
    conn = _mock_sync_conn()

    emit_integrity_fact_sync(
        conn, "ic_lifecycle", None, "decay_cells_flagged", 3.0, 0.005, True, "2026-01-01"
    )

    conn.commit.assert_not_called()


def test_emit_sync_commits_when_requested():
    conn = _mock_sync_conn()

    emit_integrity_fact_sync(
        conn,
        "price_sanity",
        None,
        "rows_flagged_suspect",
        5.0,
        None,
        True,
        "2026-01-01",
        commit=True,
    )

    conn.commit.assert_called_once()


def test_emit_sync_no_idempotency_check_by_default_single_cursor_use():
    conn = _mock_sync_conn()

    emit_integrity_fact_sync(
        conn, "ic_lifecycle", None, "decay_cells_flagged", 3.0, 0.005, True, "2026-01-01"
    )

    assert conn.cursor.call_count == 1


def test_emit_sync_idempotency_check_skips_insert_when_already_ran():
    conn = _mock_sync_conn(precheck_hit=True)

    emit_integrity_fact_sync(
        conn,
        "price_sanity",
        None,
        "rows_flagged_suspect",
        5.0,
        None,
        True,
        "2026-01-01",
        idempotency_check=True,
        commit=True,
    )

    # Only the pre-check SELECT ran -- no INSERT, no commit.
    assert conn.cursor.call_count == 1
    conn.commit.assert_not_called()


def test_emit_sync_idempotency_check_inserts_when_not_already_ran():
    conn = _mock_sync_conn(precheck_hit=False)

    emit_integrity_fact_sync(
        conn,
        "price_sanity",
        None,
        "rows_flagged_suspect",
        5.0,
        None,
        True,
        "2026-01-01",
        idempotency_check=True,
        commit=True,
    )

    # Pre-check SELECT + INSERT -- two separate cursor uses.
    assert conn.cursor.call_count == 2
    conn.commit.assert_called_once()


def test_emit_sync_guards_insert_failure_log_and_continue():
    conn = _mock_sync_conn()
    conn.cursor.return_value.execute.side_effect = Exception("boom")

    # Must not raise -- guard behavior lives in the helper.
    emit_integrity_fact_sync(
        conn, "ic_lifecycle", None, "decay_cells_flagged", 3.0, 0.005, True, "2026-01-01"
    )


def test_emit_sync_guard_does_not_commit_on_failure():
    conn = _mock_sync_conn()
    conn.cursor.return_value.execute.side_effect = Exception("boom")

    emit_integrity_fact_sync(
        conn,
        "ic_lifecycle",
        None,
        "decay_cells_flagged",
        3.0,
        0.005,
        True,
        "2026-01-01",
        commit=True,
    )

    conn.commit.assert_not_called()


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
