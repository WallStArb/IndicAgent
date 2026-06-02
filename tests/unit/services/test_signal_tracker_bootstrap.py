"""Tests for signal_tracker_compute_agent bootstrap retry logic."""

from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.signal_tracker import SignalTracker


def _make_signal_row(signal_id, symbol="ES", timeframe="5m", status="pending", **kwargs):
    return {
        "signal_id": signal_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "status": status,
        "timestamp": datetime.now(UTC),
        "direction": 1,
        "entry_price": 5000.0,
        "stop_loss": 4980.0,
        "targets": [],
        "confidence": 0.8,
        "entry_zone_low": 4995.0,
        "entry_zone_high": 5005.0,
        "activated_at": None,
        "market_entry_price": None,
        "point_value": 50.0,
        **kwargs,
    }


def _make_db_mock(main_query_results, count=None):
    """Build a DatabaseManager mock that supports the get_connection() interface.

    Each call to get_connection() yields a fresh mock connection. The connection's
    fetch() returns the next item from main_query_results (popped from the front);
    execute() is a no-op (used for SET commands).

    count: if provided, overrides COUNT(*) queries with this value. If None,
    falls back to len(main_query_results) as a rough estimate.
    """
    results = list(main_query_results)  # mutable copy

    @asynccontextmanager
    async def _fake_get_connection():
        conn = AsyncMock()

        async def _fetch(query):
            if results:
                return results.pop(0)
            return []

        async def _execute(query):
            return None

        conn.fetch.side_effect = _fetch
        conn.execute.side_effect = _execute
        yield conn

    mock_db = MagicMock()
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()
    # get_connection must be a plain MagicMock (not AsyncMock) because it returns
    # an async context manager, not a coroutine.
    mock_db.get_connection = MagicMock(side_effect=_fake_get_connection)
    # execute_query is still used for the COUNT(*) check
    _count = count if count is not None else 0

    async def _execute_query(query, *args):
        if "COUNT" in query:
            return [{"count": _count}]
        return []

    mock_db.execute_query = AsyncMock(side_effect=_execute_query)
    return mock_db


def _make_agent():
    agent = SignalTracker.__new__(SignalTracker)
    agent.settings = MagicMock(env_name="dev")
    agent.settings.database_url = "postgresql://test"
    agent._signal_ids = set()
    agent._active_index = defaultdict(list)
    agent._active_symbols = set()
    agent._signal_states = {}
    agent._point_values = {}
    agent._regime_cache = {}
    agent.logger = MagicMock()
    return agent


@pytest.mark.asyncio
async def test_bootstrap_succeeds_on_first_attempt():
    """Bootstrap loads 3 signals on first DB attempt."""
    agent = _make_agent()
    rows = [
        _make_signal_row("sig1", symbol="ES", timeframe="5m"),
        _make_signal_row(
            "sig2",
            symbol="NQ",
            timeframe="5m",
            direction=-1,
            status="active",
            activated_at=datetime.now(UTC),
            market_entry_price=18000.0,
        ),
        _make_signal_row("sig3", symbol="ES", timeframe="15m"),
    ]
    mock_db = _make_db_mock([rows], count=3)

    with patch("services.signal_tracker.DatabaseManager") as mock_db_cls:
        mock_db_cls.return_value = mock_db
        await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 3
    assert {"sig1", "sig2", "sig3"} == agent._signal_ids
    assert len(agent._active_symbols) == 2
    assert len(agent._active_index[("ES", "5m")]) == 1
    assert len(agent._active_index[("NQ", "5m")]) == 1
    assert len(agent._active_index[("ES", "15m")]) == 1


@pytest.mark.asyncio
async def test_bootstrap_retries_on_empty_result_when_ledger_has_rows():
    """Bootstrap retries when DB returns empty but ledger has rows, then succeeds."""
    agent = _make_agent()
    rows = [
        _make_signal_row("sig1"),
        _make_signal_row("sig2", symbol="NQ"),
    ]
    # First two connection fetches return [], third returns rows
    mock_db = _make_db_mock([[], [], rows], count=2)

    with patch("services.signal_tracker.DatabaseManager") as mock_db_cls:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            mock_db_cls.return_value = mock_db
            await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 2
    assert "sig1" in agent._signal_ids
    assert "sig2" in agent._signal_ids
    assert any("bootstrap_empty_retry" in str(call) for call in agent.logger.method_calls)


@pytest.mark.asyncio
async def test_bootstrap_succeeds_immediately_on_empty_ledger():
    """Bootstrap completes immediately when ledger is provably empty."""
    agent = _make_agent()
    mock_db = _make_db_mock([[]], count=0)

    with patch("services.signal_tracker.DatabaseManager") as mock_db_cls:
        mock_db_cls.return_value = mock_db
        await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 0
    assert len(agent._active_symbols) == 0
    assert not any("bootstrap_retry" in str(call) for call in agent.logger.method_calls)


@pytest.mark.asyncio
async def test_bootstrap_exhausted_publishes_health_event():
    """Bootstrap publishes health event after 3 failed attempts."""
    agent = _make_agent()
    agent._producer = AsyncMock()
    # All fetches return empty, but COUNT says 5 rows exist
    mock_db = _make_db_mock([[], [], []], count=5)

    with patch("services.signal_tracker.DatabaseManager") as mock_db_cls:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            mock_db_cls.return_value = mock_db
            await agent._bootstrap_active_signals()

    assert any(
        "bootstrap_failed_exhausted" in str(call) for call in agent.logger.method_calls
    ), "bootstrap_failed_exhausted should be logged"

    agent._producer.publish.assert_called_once()
    call_args = agent._producer.publish.call_args
    assert call_args[0][0] == "dev.system.health.events"
    payload = call_args[1]["msg"]
    assert payload["event_type"] == "bootstrap_failed"
    assert "signal_tracker_compute" in payload.get("service", "")


@pytest.mark.asyncio
async def test_sd_notify_called_after_bootstrap_not_before():
    """Bootstrap completes and loads signals correctly (sd_notify timing verified via _setup)."""
    agent = _make_agent()
    rows = [_make_signal_row("sig1")]
    mock_db = _make_db_mock([rows], count=1)

    call_order = []
    original_side_effect = mock_db.get_connection.side_effect

    @asynccontextmanager
    async def _tracked_get_connection():
        async with original_side_effect() as conn:
            call_order.append("db_query")
            yield conn

    mock_db.get_connection = MagicMock(side_effect=_tracked_get_connection)

    with patch("services.signal_tracker.DatabaseManager") as mock_db_cls:
        mock_db_cls.return_value = mock_db
        await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 1
    assert "db_query" in call_order


@pytest.mark.asyncio
async def test_bootstrap_null_entry_price_falls_back_to_activation_price():
    """entry_price=NULL (pre-095 signal) uses COALESCE result from SQL.

    The bootstrap query does COALESCE(sl.entry_price, sl.activation_price).
    This test simulates what the DB returns after COALESCE resolves.
    """
    signal_id = "aaaaaaaa-0000-0000-0000-000000000099"
    row = _make_signal_row(
        signal_id,
        activation_price=5050.0,
        ttl_bars=10,
        signal_schema_version="1",
        is_backfill=False,
    )
    # SQL COALESCE(sl.entry_price=NULL, sl.activation_price=5050) → 5050
    row["entry_price"] = 5050.0

    agent = _make_agent()
    mock_db = _make_db_mock([[row]])

    with patch("services.signal_tracker.DatabaseManager") as mock_db_cls:
        mock_db_cls.return_value = mock_db
        await agent._bootstrap_active_signals()

    assert signal_id in agent._signal_ids
    loaded = agent._active_index[("ES", "5m")][0]
    assert loaded["entry_price"] == 5050.0
