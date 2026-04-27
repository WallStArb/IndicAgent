"""Unit tests for backtest_i6_plugin.py tool."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.backtest_i6_plugin import backtest_i6_plugin


@pytest.fixture
def mock_plugin():
    """Create a mock I6 plugin for testing."""

    class MockI6Plugin:
        name = "mock_i6_plugin"
        outputs = frozenset({"test_score", "test_signal"})
        min_lookback = 1
        supports_incremental = False
        capability_tags = frozenset({"confluence"})
        inputs = []

        def __init__(self):
            self._state = {}
            self.compute_full_calls = []

        def compute_full(self, frames: dict) -> dict:
            """Mock compute_full that tracks calls and returns test data."""
            self.compute_full_calls.append(frames)
            return {
                "test_score": 0.75,
                "test_signal": 1.0,
            }

    return MockI6Plugin  # Return class, not instance


@pytest.fixture
def mock_db_connection():
    """Create a mock asyncpg connection."""
    conn = AsyncMock()
    conn.fetch = AsyncMock()
    conn.close = AsyncMock()
    return conn


@pytest.mark.asyncio
async def test_backtest_mock_plugin(mock_plugin, mock_db_connection):
    """Test that backtest calls plugin.compute_full() for each bar."""
    # Mock database queries
    mock_db_connection.fetch.side_effect = [
        # First call: intelligence_features
        [
            {
                "ts": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "symbol": "ES",
                "tf": "5m",
                "i2_events": {},
                "i3_patterns": {},
                "i4_context": {},
                "i5_patterns": {},
                "hmm_regime": 1,  # From intelligence_features
            }
        ],
        # Second call: signal_ledger
        [
            {
                "feature_ts": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "feature_tf": "5m",
                "symbol": "ES",
                "pnl_r": 0.025,
            }
        ],
    ]

    with patch("asyncpg.connect", return_value=mock_db_connection):
        result = await backtest_i6_plugin(
            plugin_class=mock_plugin,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 2, tzinfo=UTC),
            symbols=["ES"],
            timeframes=["5m"],
        )

    # Verify DataFrame structure
    assert len(result) == 1
    assert "ts" in result.columns
    assert "symbol" in result.columns
    assert "tf" in result.columns
    assert "test_score" in result.columns
    assert "test_signal" in result.columns
    assert "pnl_r" in result.columns
    assert "hmm_regime" in result.columns

    # Verify values
    row = result.iloc[0]
    assert row["symbol"] == "ES"
    assert row["tf"] == "5m"
    assert row["test_score"] == 0.75
    assert row["test_signal"] == 1.0
    assert row["pnl_r"] == 0.025
    assert row["hmm_regime"] == 1


@pytest.mark.asyncio
async def test_backtest_missing_outcomes(mock_plugin, mock_db_connection):
    """Test that backtest handles missing pnl_r gracefully (sets None)."""
    # Mock database queries with empty signal_ledger result
    mock_db_connection.fetch.side_effect = [
        [
            {
                "ts": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "symbol": "ES",
                "tf": "5m",
                "i2_events": {},
                "i3_patterns": {},
                "i4_context": {},
                "i5_patterns": {},
                "hmm_regime": 1,
            }
        ],
        [],  # Empty signal_ledger result
    ]

    with patch("asyncpg.connect", return_value=mock_db_connection):
        result = await backtest_i6_plugin(
            plugin_class=mock_plugin,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 2, tzinfo=UTC),
            symbols=["ES"],
            timeframes=["5m"],
        )

    # Verify pnl_r is None (but hmm_regime is from intelligence_features)
    row = result.iloc[0]
    assert row["pnl_r"] is None
    assert row["hmm_regime"] == 1  # From intelligence_features


def test_backtest_cli_interface():
    """Test that CLI args parse correctly."""
    # This is a basic smoke test - full CLI testing would require more setup
    # For now, just verify the module has the expected structure
    assert hasattr(backtest_i6_plugin, "__call__")


@pytest.mark.asyncio
async def test_backtest_plugin_raises_error(mock_plugin, mock_db_connection):
    """Test that backtest handles plugin.compute_full() errors gracefully."""
    # Make plugin raise an error
    original_compute = mock_plugin.compute_full
    mock_plugin.compute_full = MagicMock(side_effect=ValueError("Test error"))

    mock_db_connection.fetch.side_effect = [
        [  # First call: intelligence_features
            {
                "ts": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
                "symbol": "ES",
                "tf": "5m",
                "i2_events": {},
                "i3_patterns": {},
                "i4_context": {},
                "i5_patterns": {},
                "hmm_regime": 1,
            }
        ],
        [],  # Second call: signal_ledger (empty)
    ]

    with patch("asyncpg.connect", return_value=mock_db_connection):
        result = await backtest_i6_plugin(
            plugin_class=mock_plugin,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
            end_date=datetime(2026, 1, 2, tzinfo=UTC),
            symbols=["ES"],
            timeframes=["5m"],
        )

    # Verify error was handled gracefully (empty result or skipped bar)
    assert len(result) == 0  # No results due to error

    # Restore original compute_full
    mock_plugin.compute_full = original_compute
