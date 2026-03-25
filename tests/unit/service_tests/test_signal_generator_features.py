"""Tests for atomic signal_features write path.

FEAT-02: signal_ledger + signal_features written atomically in one transaction.
No orphaned feature rows — both succeed or both fail.

Tests the public insert_signals_with_features() function in signal_ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.persistence.repository.signal_ledger_repository import (
    _INSERT_FEATURES_SQL,
    _INSERT_SQL,
    LedgerEntry,
    SignalLedgerRepository,
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


def _make_pool_mock():
    """Build a properly-typed connection mock for asyncpg pool.acquire context."""
    txn_mock = MagicMock()
    txn_mock.__aenter__ = AsyncMock(return_value=txn_mock)
    txn_mock.__aexit__ = AsyncMock(return_value=False)

    conn_mock = AsyncMock()
    conn_mock.transaction = MagicMock(return_value=txn_mock)

    acquire_ctx = MagicMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn_mock)
    acquire_ctx.__aexit__ = AsyncMock(return_value=False)

    pool_mock = MagicMock()
    pool_mock.acquire = MagicMock(return_value=acquire_ctx)

    db_manager = MagicMock()
    db_manager.pool = pool_mock

    return conn_mock, txn_mock, pool_mock, db_manager


@pytest.mark.unit
class TestInsertSignalsWithFeatures:
    @pytest.mark.asyncio
    async def test_noop_when_entries_empty(self):
        """No DB calls when entries list is empty."""
        conn_mock, txn_mock, pool_mock, db_manager = _make_pool_mock()
        await SignalLedgerRepository(db_manager).insert_signals_with_features([], {})
        pool_mock.acquire.assert_not_called()

    @pytest.mark.asyncio
    async def test_noop_when_pool_none(self):
        """No crash when pool is None."""
        db_mock = MagicMock()
        db_mock.pool = None
        await SignalLedgerRepository(db_mock).insert_signals_with_features([_make_entry()], {})
        # Should not raise

    @pytest.mark.asyncio
    async def test_uses_transaction_context_manager(self):
        """Uses conn.transaction() wrapping the inserts."""
        conn_mock, txn_mock, pool_mock, db_manager = _make_pool_mock()
        entry = _make_entry()
        features = {"rsi_14": 55.0, "adx_14": 30.0}

        await SignalLedgerRepository(db_manager).insert_signals_with_features([entry], features)

        conn_mock.transaction.assert_called_once()

    @pytest.mark.asyncio
    async def test_executes_insert_sql_for_signal_ledger(self):
        """conn.execute is called with _INSERT_SQL for each entry."""
        conn_mock, txn_mock, pool_mock, db_manager = _make_pool_mock()
        entry = _make_entry()

        await SignalLedgerRepository(db_manager).insert_signals_with_features([entry], {})

        assert conn_mock.execute.called
        call_args = conn_mock.execute.call_args_list[0]
        assert call_args[0][0] == _INSERT_SQL

    @pytest.mark.asyncio
    async def test_executemany_called_for_feature_rows(self):
        """conn.executemany is called with _INSERT_FEATURES_SQL when features present."""
        conn_mock, txn_mock, pool_mock, db_manager = _make_pool_mock()
        entry = _make_entry()
        features = {"rsi_14": 55.0, "adx_14": 30.0}  # 2 numeric features

        await SignalLedgerRepository(db_manager).insert_signals_with_features([entry], features)

        assert conn_mock.executemany.called
        call_args = conn_mock.executemany.call_args_list[0]
        assert call_args[0][0] == _INSERT_FEATURES_SQL

    @pytest.mark.asyncio
    async def test_no_executemany_when_no_numeric_features(self):
        """conn.executemany is NOT called when no numeric features found."""
        conn_mock, txn_mock, pool_mock, db_manager = _make_pool_mock()
        entry = _make_entry()

        await SignalLedgerRepository(db_manager).insert_signals_with_features([entry], {})

        conn_mock.executemany.assert_not_called()
