"""Tests for atomic signal_features write path in SignalGeneratorService.

FEAT-02: signal_ledger + signal_features written atomically in one transaction.
No orphaned feature rows — both succeed or both fail.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.signal_generator_service import SignalGeneratorService
from src.intelligence.trading.signal_ledger import (
    LedgerEntry,
    _INSERT_FEATURES_SQL,
    _INSERT_SQL,
)


def _make_entry(**overrides) -> LedgerEntry:
    defaults = dict(
        signal_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        timestamp=datetime(2026, 3, 16, 14, 30, 0, tzinfo=UTC),
        symbol="ES",
        timeframe="1m",
        setup_plugin="trad_TrendFollowing",
        signal_type="trend_long",
        direction=1,
        entry_price=5100.0,
        stop_loss=5090.0,
        targets=[5110.0],
        confidence=0.75,
        confluence_score=0.82,
        regime_context="bullish",
        supporting_factors=["ema_alignment"],
        was_selected=True,
        num_signals_bar=1,
        num_agreeing=1,
        num_conflicting=0,
        resolution_method="rank",
        composite_rank=1,
        signal_computed_at=datetime(2026, 3, 16, 14, 30, 1, tzinfo=UTC),
    )
    defaults.update(overrides)
    return LedgerEntry(**defaults)


def _make_service() -> SignalGeneratorService:
    """Build a SignalGeneratorService instance bypassing __init__."""
    svc = SignalGeneratorService.__new__(SignalGeneratorService)
    # Required attrs
    svc.logger = MagicMock()
    svc.logger.info = MagicMock()
    svc.db_manager = MagicMock()
    return svc


@pytest.mark.unit
class TestWriteSignalWithFeaturesAtomic:
    @pytest.mark.asyncio
    async def test_noop_when_entries_empty(self):
        """No DB calls when entries list is empty."""
        svc = _make_service()
        svc.db_manager = MagicMock()
        pool_mock = MagicMock()
        svc.db_manager.pool = pool_mock

        await svc._write_signal_with_features([], [{}], [None])
        pool_mock.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_db_manager_none(self):
        """No crash when db_manager is None."""
        svc = _make_service()
        svc.db_manager = None

        await svc._write_signal_with_features([_make_entry()], [{}], [None])
        # Should not raise

    @pytest.mark.asyncio
    async def test_noop_when_pool_none(self):
        """No crash when db_manager.pool is None."""
        svc = _make_service()
        svc.db_manager = MagicMock()
        svc.db_manager.pool = None

        await svc._write_signal_with_features([_make_entry()], [{}], [None])
        # Should not raise

    def _make_conn_mock(self):
        """Build a properly-typed connection mock for asyncpg pool.acquire context."""
        # asyncpg conn.transaction() returns a Transaction object (sync, not awaitable)
        # that supports async context manager protocol via __aenter__/__aexit__.
        txn_mock = MagicMock()
        txn_mock.__aenter__ = AsyncMock(return_value=txn_mock)
        txn_mock.__aexit__ = AsyncMock(return_value=False)

        conn_mock = AsyncMock()
        # transaction() must return the txn_mock synchronously (not as a coroutine)
        conn_mock.transaction = MagicMock(return_value=txn_mock)

        acquire_ctx = MagicMock()
        acquire_ctx.__aenter__ = AsyncMock(return_value=conn_mock)
        acquire_ctx.__aexit__ = AsyncMock(return_value=False)

        pool_mock = MagicMock()
        pool_mock.acquire = MagicMock(return_value=acquire_ctx)

        return conn_mock, txn_mock, pool_mock

    @pytest.mark.asyncio
    async def test_uses_transaction_context_manager(self):
        """Uses conn.transaction() wrapping the inserts."""
        svc = _make_service()
        conn_mock, txn_mock, pool_mock = self._make_conn_mock()
        svc.db_manager = MagicMock()
        svc.db_manager.pool = pool_mock

        entry = _make_entry()
        features = {"rsi_14": 55.0, "adx_14": 30.0}

        await svc._write_signal_with_features([entry], [features], [None])

        # conn.transaction() was called
        conn_mock.transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_executes_insert_sql_for_signal_ledger(self):
        """conn.execute is called with _INSERT_SQL for each entry."""
        svc = _make_service()
        conn_mock, txn_mock, pool_mock = self._make_conn_mock()
        svc.db_manager = MagicMock()
        svc.db_manager.pool = pool_mock

        entry = _make_entry()
        await svc._write_signal_with_features([entry], [{}], [None])

        # conn.execute was called with _INSERT_SQL as first arg
        assert conn_mock.execute.called
        call_args = conn_mock.execute.call_args_list[0]
        assert call_args[0][0] == _INSERT_SQL

    @pytest.mark.asyncio
    async def test_executemany_called_for_feature_rows(self):
        """conn.executemany is called with _INSERT_FEATURES_SQL when features present."""
        svc = _make_service()
        conn_mock, txn_mock, pool_mock = self._make_conn_mock()
        svc.db_manager = MagicMock()
        svc.db_manager.pool = pool_mock

        entry = _make_entry()
        features = {"rsi_14": 55.0, "adx_14": 30.0}  # 2 numeric features

        await svc._write_signal_with_features([entry], [features], [None])

        # conn.executemany was called with _INSERT_FEATURES_SQL
        assert conn_mock.executemany.called
        call_args = conn_mock.executemany.call_args_list[0]
        assert call_args[0][0] == _INSERT_FEATURES_SQL

    @pytest.mark.asyncio
    async def test_no_executemany_when_no_numeric_features(self):
        """conn.executemany is NOT called when no numeric features found."""
        svc = _make_service()
        conn_mock, txn_mock, pool_mock = self._make_conn_mock()
        svc.db_manager = MagicMock()
        svc.db_manager.pool = pool_mock

        entry = _make_entry()
        features: dict = {}  # No features

        await svc._write_signal_with_features([entry], [features], [None])

        conn_mock.executemany.assert_not_called()
