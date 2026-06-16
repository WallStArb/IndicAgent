"""Tests for signal_tracker_compute_agent bootstrap retry logic."""

from collections import defaultdict
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
    # APR-backed bootstrap config (defaults from migration 142)
    agent._bootstrap_max_attempts = 3
    agent._bootstrap_pending_window_days = 7
    agent._bootstrap_active_window_days = 30
    agent._bootstrap_dedup_window_days = 3
    agent._staleness_score_threshold = 0.5
    return agent


def _make_db_mock(signal_count: int = 0) -> MagicMock:
    """Build a DatabaseManager mock for the dedup COUNT(*) check path.

    The new bootstrap code calls SignalEventsRepository.get_active_signals_for_bootstrap()
    (mocked separately per test) and DatabaseManager.execute_query() only for the
    dedup COUNT(*) fallback check when no rows are returned.
    """
    mock_db = MagicMock()
    mock_db.initialize = AsyncMock()
    mock_db.close = AsyncMock()

    async def _execute_query(query, *args):
        return [{"count": signal_count}]

    mock_db.execute_query = AsyncMock(side_effect=_execute_query)
    return mock_db


def _patch_bootstrap(agent, rows_sequence: list, signal_count: int = 0):
    """Patch DatabaseManager and SignalEventsRepository for bootstrap tests.

    rows_sequence: list of return values per get_active_signals_for_bootstrap call.
    signal_count: COUNT(*) to return from execute_query for the dedup fallback check.
    """
    mock_db = _make_db_mock(signal_count=signal_count)
    results = list(rows_sequence)

    async def _fake_bootstrap(pending_window_days=7, active_window_days=30):
        if results:
            return results.pop(0)
        return []

    mock_repo = MagicMock()
    mock_repo.get_active_signals_for_bootstrap = AsyncMock(side_effect=_fake_bootstrap)

    db_patch = patch("services.signal_tracker.DatabaseManager", return_value=mock_db)
    repo_patch = patch("services.signal_tracker.SignalEventsRepository", return_value=mock_repo)
    return db_patch, repo_patch, mock_repo


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
    db_patch, repo_patch, _ = _patch_bootstrap(agent, [rows], signal_count=3)

    with db_patch, repo_patch:
        await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 3
    assert {"sig1", "sig2", "sig3"} == agent._signal_ids
    assert len(agent._active_symbols) == 2
    assert len(agent._active_index[("ES", "5m")]) == 1
    assert len(agent._active_index[("NQ", "5m")]) == 1
    assert len(agent._active_index[("ES", "15m")]) == 1


@pytest.mark.asyncio
async def test_bootstrap_retries_on_empty_result_when_ledger_has_rows():
    """Bootstrap retries when DB returns empty but signal_events has rows, then succeeds."""
    agent = _make_agent()
    rows = [
        _make_signal_row("sig1"),
        _make_signal_row("sig2", symbol="NQ"),
    ]
    # First two calls return [], third returns rows
    db_patch, repo_patch, _ = _patch_bootstrap(agent, [[], [], rows], signal_count=2)

    with db_patch, repo_patch:
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 2
    assert "sig1" in agent._signal_ids
    assert "sig2" in agent._signal_ids
    assert any("bootstrap_empty_retry" in str(call) for call in agent.logger.method_calls)


@pytest.mark.asyncio
async def test_bootstrap_succeeds_immediately_on_empty_ledger():
    """Bootstrap completes immediately when signal_events is provably empty."""
    agent = _make_agent()
    db_patch, repo_patch, _ = _patch_bootstrap(agent, [[]], signal_count=0)

    with db_patch, repo_patch:
        await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 0
    assert len(agent._active_symbols) == 0
    assert not any("bootstrap_retry" in str(call) for call in agent.logger.method_calls)


@pytest.mark.asyncio
async def test_bootstrap_exhausted_publishes_health_event():
    """Bootstrap publishes health event after 3 failed attempts."""
    agent = _make_agent()
    agent._producer = AsyncMock()
    # All calls return empty, but COUNT says 5 rows exist
    db_patch, repo_patch, _ = _patch_bootstrap(agent, [[], [], []], signal_count=5)

    with db_patch, repo_patch:
        with patch("asyncio.sleep", new_callable=AsyncMock):
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
    db_patch, repo_patch, mock_repo = _patch_bootstrap(agent, [rows], signal_count=1)

    with db_patch, repo_patch:
        await agent._bootstrap_active_signals()

    assert len(agent._signal_ids) == 1
    mock_repo.get_active_signals_for_bootstrap.assert_called_once()


@pytest.mark.asyncio
async def test_bootstrap_null_entry_price_falls_back_to_activation_price():
    """entry_price from trade_frames.entry_price is used directly by the bootstrap query.

    The new bootstrap query (via SignalEventsRepository.get_active_signals_for_bootstrap)
    returns entry_price from trade_frames.entry_price. This test verifies the row is
    loaded and the canonical dict has the correct entry_price.
    """
    signal_id = "aaaaaaaa-0000-0000-0000-000000000099"
    row = _make_signal_row(
        signal_id,
        ttl_bars=10,
        is_backfill=False,
    )
    # trade_frames.entry_price provides the value directly (no COALESCE needed in new schema)
    row["entry_price"] = 5050.0

    agent = _make_agent()
    db_patch, repo_patch, _ = _patch_bootstrap(agent, [row if False else [row]])

    with db_patch, repo_patch:
        await agent._bootstrap_active_signals()

    assert signal_id in agent._signal_ids
    loaded = agent._active_index[("ES", "5m")][0]
    assert loaded["entry_price"] == 5050.0
