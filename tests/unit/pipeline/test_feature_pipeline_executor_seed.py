"""Unit tests for FeaturePipelineExecutor._seed_last_events_from_db() (A7 fix).

Verifies that the seed method:
- Populates _last_events with I3 trend fields from a DB row (happy path)
- Handles cold-start gracefully when intelligence_features is empty (no exception)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.intelligence.pipeline.feature_pipeline_executor import FeaturePipelineExecutor


def _make_executor() -> FeaturePipelineExecutor:
    """Return a minimal FeaturePipelineExecutor with mocked injected dependencies."""
    bar_history = MagicMock()
    executor = MagicMock()
    state_mgr = MagicMock()
    state_mgr.get_all_states_for.return_value = {}
    state_mgr.get_lock.return_value = MagicMock()
    instrument_map = {}
    return FeaturePipelineExecutor(
        bar_history=bar_history,
        executor=executor,
        state_mgr=state_mgr,
        instrument_map=instrument_map,
        vix_symbol=None,
        settings=None,
    )


def _make_mock_db(row: dict | None) -> MagicMock:
    """Return a mock DatabaseManager whose pool.acquire() returns a fake asyncpg conn."""
    mock_conn = AsyncMock()
    if row is None:
        mock_conn.fetchrow = AsyncMock(return_value=None)
    else:
        mock_row = MagicMock()
        mock_row.__getitem__ = lambda self, key: row.get(key)
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool.acquire.return_value = mock_pool_ctx
    return mock_db


@pytest.mark.asyncio
async def test_seed_populates_last_events_with_trend_fields() -> None:
    """Happy path: DB returns a row with trend data; _last_events is seeded correctly."""
    executor = _make_executor()

    fake_row = {
        "trend_direction": "1.0",
        "trend_strength": "0.8",
        "trend_bars_elapsed": "5",
        "trend_confirmed": "True",
    }
    mock_db = _make_mock_db(fake_row)

    await executor._seed_last_events_from_db(
        symbols=["ESM6"],
        timeframes=["1m"],
        db=mock_db,
    )

    # _last_events must be populated for the (symbol, tf) pair
    assert "ESM6:1m" in executor._last_events, "_last_events must have ESM6:1m key after seed"

    event = executor._last_events["ESM6:1m"]
    # The seeded event's i3 tier must carry trend_direction=1.0
    assert event.i3.trend_direction == pytest.approx(
        1.0
    ), f"Expected trend_direction=1.0, got {event.i3.trend_direction}"
    assert event.i3.trend_strength == pytest.approx(
        0.8
    ), f"Expected trend_strength=0.8, got {event.i3.trend_strength}"


@pytest.mark.asyncio
async def test_seed_cold_start_no_exception() -> None:
    """Cold-start path: intelligence_features is empty (DB returns None); no exception raised."""
    executor = _make_executor()
    mock_db = _make_mock_db(row=None)

    # Must not raise even when table is empty
    await executor._seed_last_events_from_db(
        symbols=["ESM6"],
        timeframes=["1m"],
        db=mock_db,
    )

    # _last_events must remain empty — no spurious seed entry
    assert (
        "ESM6:1m" not in executor._last_events
    ), "_last_events must not have ESM6:1m key when DB returned no rows"


@pytest.mark.asyncio
async def test_seed_multiple_symbol_tf_pairs() -> None:
    """Verify parallel gather across multiple (symbol, tf) pairs."""
    executor = _make_executor()

    call_count = 0

    async def _fake_fetchrow(query: str, symbol: str, tf: str) -> MagicMock | None:
        nonlocal call_count
        call_count += 1
        if symbol == "ESM6" and tf == "1m":
            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key: {
                "trend_direction": "-1.0",
                "trend_strength": "0.6",
                "trend_bars_elapsed": "3",
                "trend_confirmed": "False",
            }.get(key)
            return mock_row
        return None  # all other pairs: cold-start

    mock_conn = AsyncMock()
    mock_conn.fetchrow = _fake_fetchrow  # type: ignore[assignment]

    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool.acquire.return_value = mock_pool_ctx

    await executor._seed_last_events_from_db(
        symbols=["ESM6", "NQM6"],
        timeframes=["1m", "5m"],
        db=mock_db,
    )

    # 4 pairs queried (2 symbols * 2 tfs)
    assert call_count == 4, f"Expected 4 DB queries, got {call_count}"

    # Only ESM6:1m had a row
    assert "ESM6:1m" in executor._last_events
    assert "ESM6:5m" not in executor._last_events
    assert "NQM6:1m" not in executor._last_events

    event = executor._last_events["ESM6:1m"]
    assert event.i3.trend_direction == pytest.approx(-1.0)
