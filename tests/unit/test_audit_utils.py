"""Unit tests for src/core/audit_utils.py.

Tests cover:
- batch_bar_completeness returns BarCompletenessResult from mock DB
- batch_signal_coverage returns SignalCoverageResult with signal_count=0 for empty
- Both functions use asyncio pool.acquire() as async context manager
- Pure functions: no side effects on passed arguments
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool(fetch_rows: list) -> MagicMock:
    """Return a mock asyncpg pool whose conn.fetch() returns fetch_rows."""
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fetch_rows)

    mock_pool = MagicMock()
    mock_pool.acquire = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_pool


def _make_instrument(symbol: str = "BTC", session_id: str = "crypto_24_7"):
    """Return a minimal Instrument stub."""
    from src.core.models import AssetClass, Instrument

    return Instrument(symbol=symbol, asset_class=AssetClass.CRYPTO, session_id=session_id)


# ---------------------------------------------------------------------------
# Tests: batch_bar_completeness
# ---------------------------------------------------------------------------


class TestBatchBarCompleteness:
    @pytest.mark.asyncio
    async def test_returns_bar_completeness_result_from_mock_db(self):
        """batch_bar_completeness maps DB rows to BarCompletenessResult objects."""
        from src.core.audit_utils import BarCompletenessResult, batch_bar_completeness

        session_start = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)  # Tuesday UTC
        session_end = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)

        rows = [
            {
                "symbol": "BTC",
                "tf": "1m",
                "session_start": session_start,
                "session_end": session_end,
                "expected": 1440,
                "actual": 1430,
            }
        ]
        pool = _make_pool(rows)
        instrument = _make_instrument("BTC", "crypto_24_7")

        results = await batch_bar_completeness(pool, [instrument], lookback_days=1)

        assert len(results) >= 1
        result = next(r for r in results if r.symbol == "BTC" and r.tf == "1m")
        assert isinstance(result, BarCompletenessResult)
        assert result.symbol == "BTC"
        assert result.tf == "1m"
        assert result.actual == 1430
        assert result.expected == 1440

    @pytest.mark.asyncio
    async def test_returns_actual_zero_for_empty_session(self):
        """batch_bar_completeness returns actual=0 when no rows match (UNNEST LEFT JOIN)."""
        from src.core.audit_utils import BarCompletenessResult, batch_bar_completeness

        session_start = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
        session_end = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)

        rows = [
            {
                "symbol": "BTC",
                "tf": "1m",
                "session_start": session_start,
                "session_end": session_end,
                "expected": 1440,
                "actual": 0,
            }
        ]
        pool = _make_pool(rows)
        instrument = _make_instrument("BTC", "crypto_24_7")

        results = await batch_bar_completeness(pool, [instrument], lookback_days=1)

        assert any(r.actual == 0 for r in results)
        zero_result = next(r for r in results if r.actual == 0)
        assert isinstance(zero_result, BarCompletenessResult)

    @pytest.mark.asyncio
    async def test_uses_pool_acquire_as_async_context_manager(self):
        """batch_bar_completeness uses pool.acquire() as an async context manager."""
        from src.core.audit_utils import batch_bar_completeness

        pool = _make_pool([])
        instrument = _make_instrument("BTC", "crypto_24_7")

        await batch_bar_completeness(pool, [instrument], lookback_days=1)

        pool.acquire.assert_called()
        pool.acquire.return_value.__aenter__.assert_called()

    @pytest.mark.asyncio
    async def test_does_not_mutate_instruments_list(self):
        """batch_bar_completeness does not modify the passed instruments list."""
        from src.core.audit_utils import batch_bar_completeness

        pool = _make_pool([])
        instrument = _make_instrument("BTC", "crypto_24_7")
        original = [instrument]
        copy_before = list(original)

        await batch_bar_completeness(pool, original, lookback_days=1)

        assert original == copy_before


# ---------------------------------------------------------------------------
# Tests: batch_signal_coverage
# ---------------------------------------------------------------------------


class TestBatchSignalCoverage:
    @pytest.mark.asyncio
    async def test_returns_signal_count_zero_for_empty_session(self):
        """batch_signal_coverage returns SignalCoverageResult with signal_count=0 for zero rows."""
        from src.core.audit_utils import SignalCoverageResult, batch_signal_coverage

        session_start = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
        session_end = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)

        rows = [
            {
                "symbol": "BTC",
                "tf": "1m",
                "session_start": session_start,
                "session_end": session_end,
                "signal_count": 0,
                "p50": None,
                "p95": None,
            }
        ]
        pool = _make_pool(rows)
        instrument = _make_instrument("BTC", "crypto_24_7")

        results = await batch_signal_coverage(pool, [instrument], coverage_tfs=["1m"])

        assert len(results) >= 1
        result = next(r for r in results if r.symbol == "BTC" and r.tf == "1m")
        assert isinstance(result, SignalCoverageResult)
        assert result.signal_count == 0
        assert result.p50_lag_ms is None
        assert result.p95_lag_ms is None

    @pytest.mark.asyncio
    async def test_returns_signal_coverage_result_with_lag_data(self):
        """batch_signal_coverage maps p50/p95 from DB rows to SignalCoverageResult."""
        from src.core.audit_utils import SignalCoverageResult, batch_signal_coverage

        session_start = datetime(2026, 1, 6, 0, 0, tzinfo=UTC)
        session_end = datetime(2026, 1, 7, 0, 0, tzinfo=UTC)

        rows = [
            {
                "symbol": "BTC",
                "tf": "1m",
                "session_start": session_start,
                "session_end": session_end,
                "signal_count": 42,
                "p50": 150.5,
                "p95": 300.0,
            }
        ]
        pool = _make_pool(rows)
        instrument = _make_instrument("BTC", "crypto_24_7")

        results = await batch_signal_coverage(pool, [instrument], coverage_tfs=["1m"])

        result = next(r for r in results if r.symbol == "BTC" and r.tf == "1m")
        assert isinstance(result, SignalCoverageResult)
        assert result.signal_count == 42
        assert result.p50_lag_ms == 150.5
        assert result.p95_lag_ms == 300.0

    @pytest.mark.asyncio
    async def test_uses_pool_acquire_as_async_context_manager(self):
        """batch_signal_coverage uses pool.acquire() as an async context manager."""
        from src.core.audit_utils import batch_signal_coverage

        pool = _make_pool([])
        instrument = _make_instrument("BTC", "crypto_24_7")

        await batch_signal_coverage(pool, [instrument], coverage_tfs=["1m"])

        pool.acquire.assert_called()
        pool.acquire.return_value.__aenter__.assert_called()

    @pytest.mark.asyncio
    async def test_does_not_mutate_instruments_list(self):
        """batch_signal_coverage does not modify the passed instruments list."""
        from src.core.audit_utils import batch_signal_coverage

        pool = _make_pool([])
        instrument = _make_instrument("BTC", "crypto_24_7")
        original = [instrument]
        copy_before = list(original)

        await batch_signal_coverage(pool, original, coverage_tfs=["1m"])

        assert original == copy_before
