"""Unit tests for FeaturePipelineExecutor._seed_last_events_from_db() (A7 fix).

Verifies that the seed method:
- Populates _last_events with I3 trend fields from a DB row (happy path)
- Handles cold-start gracefully when intelligence_features is empty (no exception)
- Uses a single batched fetch() call (not per-pair fetchrow)
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


def _make_dict_row(data: dict) -> MagicMock:
    """Return a MagicMock that supports asyncpg-style row["key"] access."""
    row = MagicMock()
    row.__getitem__ = lambda self, key: data.get(key)
    row.get = lambda key, default=None: data.get(key, default)
    return row


def _make_mock_db(rows: list[dict] | None) -> MagicMock:
    """Return a mock DatabaseManager whose pool.acquire() returns a fake asyncpg conn."""
    mock_conn = AsyncMock()
    if rows is None or rows == []:
        mock_conn.fetch = AsyncMock(return_value=[])
    else:
        mock_rows = []
        for row_data in rows:
            mock_row = MagicMock()
            mock_row.__getitem__ = lambda self, key, d=row_data: d.get(key)
            mock_rows.append(mock_row)
        mock_conn.fetch = AsyncMock(return_value=mock_rows)

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
        "symbol": "ESM6",
        "tf": "1m",
        "trend_direction": "1.0",
        "trend_strength": "0.8",
        "trend_bars_elapsed": "5",
        "trend_confirmed": "True",
    }
    mock_db = _make_mock_db([fake_row])

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
    """Cold-start path: intelligence_features is empty (DB returns []); no exception raised."""
    executor = _make_executor()
    mock_db = _make_mock_db(rows=None)

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
    """Verify batch fetch handles multiple (symbol, tf) pairs correctly."""
    executor = _make_executor()

    # Only ESM6:1m has a row; all other pairs return nothing (simulated by DISTINCT ON)
    fake_rows = [
        {
            "symbol": "ESM6",
            "tf": "1m",
            "trend_direction": "-1.0",
            "trend_strength": "0.6",
            "trend_bars_elapsed": "3",
            "trend_confirmed": "False",
        },
    ]
    mock_db = _make_mock_db(fake_rows)

    await executor._seed_last_events_from_db(
        symbols=["ESM6", "NQM6"],
        timeframes=["1m", "5m"],
        db=mock_db,
    )

    # fetch() called once (batched) — not per-pair
    mock_conn = mock_db.pool.acquire.return_value.__aenter__.return_value
    mock_conn.fetch.assert_called_once()

    # Only ESM6:1m had a row
    assert "ESM6:1m" in executor._last_events
    assert "ESM6:5m" not in executor._last_events
    assert "NQM6:1m" not in executor._last_events

    event = executor._last_events["ESM6:1m"]
    assert event.i3.trend_direction == pytest.approx(-1.0)


@pytest.mark.asyncio
async def test_seed_uses_single_batch_query() -> None:
    """_seed_last_events_from_db must call fetch() once (batch), not fetchrow() per pair."""
    executor = _make_executor()

    fake_rows = [
        _make_dict_row(
            {
                "symbol": "ESM6",
                "tf": "1m",
                "trend_direction": "1.0",
                "trend_strength": "0.8",
                "trend_bars_elapsed": "5.0",
                "trend_confirmed": "true",
            }
        ),
    ]

    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=fake_rows)
    mock_pool_ctx = AsyncMock()
    mock_pool_ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool_ctx.__aexit__ = AsyncMock(return_value=None)
    mock_db = MagicMock()
    mock_db.pool.acquire.return_value = mock_pool_ctx

    await executor._seed_last_events_from_db(["ESM6"], ["1m", "5m"], mock_db)

    # Must call fetch once (batched), never fetchrow (per-pair old pattern)
    mock_conn.fetch.assert_called_once()
    mock_conn.fetchrow.assert_not_called()
    assert "ESM6:1m" in executor._last_events
