"""Integration tests for per-entry_type and per-symbol signal_metrics persistence.

Verifies end-to-end behaviour from event dict through to SQL INSERT/UPSERT,
using AsyncMock to inspect the SQL statements without requiring a live DB.

Tests:
  - _ensure_schema() can be called twice without exception (idempotency)
  - Writer persists per-entry_type rows (entry_type='at_pullback') with correct SQL
  - Writer persists per-symbol rows (symbol='ES', entry_type='*') with correct SQL
  - Events missing entry_type key default to '*' via writer's event.get() fallback

All tests in this module run without a live DB by using AsyncMock fixtures.
Live-DB tests that need a running TimescaleDB should use pytestmark.integration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.signal_metrics_writer_agent import _ensure_schema, _handle_metrics_computed


def _make_conn_with_transaction():
    conn = AsyncMock()
    tx_ctx = MagicMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    return conn


class TestEnsureSchemaIdempotent:
    """_ensure_schema() must be safe to call repeatedly (startup idempotency)."""

    @pytest.mark.asyncio
    async def test_ensure_schema_idempotent(self):
        """Call _ensure_schema(mock_conn) twice; no exception raised, DDL attempted each time."""
        conn = _make_conn_with_transaction()

        await _ensure_schema(conn)
        await _ensure_schema(conn)

        # At least 7 execute calls per run: 6 ADD COLUMN + 1 DO block within transaction
        # Two runs = at least 14 calls total
        assert conn.execute.call_count >= 14

    @pytest.mark.asyncio
    async def test_ensure_schema_calls_add_column_for_entry_type(self):
        """_ensure_schema emits an ALTER TABLE ... ADD COLUMN ... entry_type statement."""
        conn = _make_conn_with_transaction()

        await _ensure_schema(conn)

        all_sqls = [c[0][0] for c in conn.execute.call_args_list if c[0]]
        entry_type_ddl = [s for s in all_sqls if "entry_type" in s]
        assert len(entry_type_ddl) >= 1

    @pytest.mark.asyncio
    async def test_ensure_schema_calls_add_column_for_six_distribution_fields(self):
        """_ensure_schema adds all six distribution shape columns."""
        conn = _make_conn_with_transaction()

        await _ensure_schema(conn)

        all_sqls = [c[0][0] for c in conn.execute.call_args_list if c[0]]
        for col in ("skewness", "kurtosis", "min_r", "p5_r", "recovery_factor", "cvar_5"):
            matching = [s for s in all_sqls if col in s]
            assert len(matching) >= 1, f"No DDL statement found for column '{col}'"


class TestWriterPersistsPerEntryTypeRow:
    """Writer correctly persists per-entry_type rows (symbol='*', entry_type=actual)."""

    @pytest.mark.asyncio
    async def test_writer_persists_per_entry_type_row(self):
        """_handle_metrics_computed with entry_type='at_pullback' inserts with entry_type column."""
        conn = AsyncMock()
        event = {
            "track": "zone",
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "trend",
            "window_days": 30,
            "symbol": "*",
            "entry_type": "at_pullback",
            "n": 50,
            "n_outliers": 0,
            "never_activated_pct": 0.0,
            "win_rate": 0.62,
            "avg_r": 0.45,
            "std_r": 0.90,
            "sharpe": 0.50,
            "p_value": 0.02,
            "avg_mae": -0.35,
            "avg_mfe": 1.10,
            "skewness": -0.8,
            "kurtosis": 1.2,
            "min_r": -2.1,
            "p5_r": -1.5,
            "recovery_factor": 0.73,
            "cvar_5": -1.9,
            "computed_at": "2026-05-20T12:00:00+00:00",
        }

        await _handle_metrics_computed(conn, event)

        conn.execute.assert_called_once()
        sql = conn.execute.call_args_list[0][0][0]
        params = conn.execute.call_args_list[0][0][1:]

        # SQL must mention entry_type as a column
        assert "entry_type" in sql

        # ON CONFLICT must include entry_type in the conflict target
        assert (
            "ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol, entry_type)"
            in sql
        )

        # The positional parameter for entry_type should be 'at_pullback'
        assert "at_pullback" in params

    @pytest.mark.asyncio
    async def test_writer_insert_includes_all_distribution_columns(self):
        """INSERT SQL for a per-entry_type event contains all six distribution columns."""
        conn = AsyncMock()
        event = {
            "track": "zone",
            "setup_plugin": "trad_MomentumBreakout",
            "tf": "15m",
            "regime_type": "trend",
            "window_days": 30,
            "symbol": "*",
            "entry_type": "at_limit",
            "n": 35,
            "n_outliers": 1,
            "never_activated_pct": 0.05,
            "win_rate": 0.55,
            "avg_r": 0.30,
            "std_r": 0.80,
            "sharpe": 0.37,
            "p_value": 0.05,
            "avg_mae": -0.30,
            "avg_mfe": 0.95,
            "skewness": -0.5,
            "kurtosis": 0.8,
            "min_r": -1.8,
            "p5_r": -1.4,
            "recovery_factor": 0.68,
            "cvar_5": -1.7,
            "computed_at": "2026-05-20T12:00:00+00:00",
        }

        await _handle_metrics_computed(conn, event)

        sql = conn.execute.call_args_list[0][0][0]
        for col in ("skewness", "kurtosis", "min_r", "p5_r", "recovery_factor", "cvar_5"):
            assert col in sql, f"Column '{col}' missing from INSERT SQL"


class TestWriterPersistsPerSymbolRow:
    """Writer correctly persists per-symbol rows (symbol=actual, entry_type='*')."""

    @pytest.mark.asyncio
    async def test_writer_persists_per_symbol_row(self):
        """_handle_metrics_computed with symbol='ES', entry_type='*' inserts with both columns."""
        conn = AsyncMock()
        event = {
            "track": "market",
            "setup_plugin": "trad_CVDDivergence",
            "tf": "1m",
            "regime_type": "mean_reversion",
            "window_days": 7,
            "symbol": "ES",
            "entry_type": "*",
            "n": 45,
            "n_outliers": 2,
            "never_activated_pct": 0.10,
            "win_rate": 0.51,
            "avg_r": 0.25,
            "std_r": 0.75,
            "sharpe": 0.33,
            "p_value": 0.08,
            "avg_mae": -0.28,
            "avg_mfe": 0.88,
            "skewness": None,
            "kurtosis": None,
            "min_r": -1.5,
            "p5_r": -1.2,
            "recovery_factor": 0.73,
            "cvar_5": -1.4,
            "computed_at": "2026-05-20T12:00:00+00:00",
        }

        await _handle_metrics_computed(conn, event)

        # market track + regime_type='mean_reversion' does NOT trigger shim; one execute call
        conn.execute.assert_called_once()
        sql = conn.execute.call_args_list[0][0][0]
        params = conn.execute.call_args_list[0][0][1:]

        assert "symbol" in sql
        assert "entry_type" in sql
        assert (
            "ON CONFLICT (track, setup_plugin, tf, regime_type, window_days, symbol, entry_type)"
            in sql
        )
        assert "ES" in params
        assert "*" in params


class TestWriterDefaultsEntryTypeToStar:
    """Events missing entry_type key default to '*' via event.get() fallback."""

    @pytest.mark.asyncio
    async def test_writer_rejects_invalid_event_missing_required_fields_defaults_entry_type(self):
        """Event without entry_type key uses '*' default — NOT routed to DLQ.

        The writer uses event.get('entry_type', '*') so missing key maps to global sentinel.
        """
        conn = AsyncMock()
        event = {
            "track": "zone",
            "setup_plugin": "trad_TrendFollowing",
            "tf": "5m",
            "regime_type": "trend",
            "window_days": 30,
            # entry_type intentionally absent
            "n": 40,
            "n_outliers": 0,
            "never_activated_pct": 0.0,
            "win_rate": 0.55,
            "avg_r": 0.30,
            "std_r": 0.85,
            "sharpe": 0.35,
            "p_value": 0.04,
            "avg_mae": -0.38,
            "avg_mfe": 0.92,
            "computed_at": "2026-05-20T12:00:00+00:00",
        }

        # No exception: missing entry_type defaults gracefully
        await _handle_metrics_computed(conn, event)

        conn.execute.assert_called_once()
        params = conn.execute.call_args_list[0][0][1:]
        # The '*' default should appear in the params
        assert "*" in params
