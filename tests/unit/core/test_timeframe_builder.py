"""
Unit tests for TimeframeBuilder — 1m bar aggregation into higher timeframes.

Tests are pure logic tests — no live Redis connection required.
Uses MagicMock for streams_manager.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bar(
    ts_seconds: int, open_: float, high: float, low: float, close: float, volume: int
) -> dict:
    """Build a minimal OHLCV bar dict as the TimeframeBuilder expects."""
    return {
        "timestamp": str(ts_seconds),
        "open": str(open_),
        "high": str(high),
        "low": str(low),
        "close": str(close),
        "volume": str(volume),
        "symbol": "ESH6",
        "timeframe": "1m",
    }


def _make_stream_message(
    ts_seconds: int, open_: float, high: float, low: float, close: float, volume: int
):
    """Build a (msg_id, fields_bytes) Redis stream message tuple."""
    bar = _make_bar(ts_seconds, open_, high, low, close, volume)
    # Redis returns bytes; fields are byte-encoded
    fields = {k.encode(): v.encode() for k, v in bar.items()}
    return (b"fake_id", fields)


# ---------------------------------------------------------------------------
# Test imports
# ---------------------------------------------------------------------------


def test_import_timeframe_builder():
    """TimeframeBuilder must import from src.core without error."""
    from src.core.timeframe_builder import TimeframeBuilder  # noqa: F401

    assert TimeframeBuilder is not None


# ---------------------------------------------------------------------------
# Test period boundary math
# ---------------------------------------------------------------------------


def test_period_boundary_5m():
    """Floor to 5m boundary: ts=300 → period_ts=300 (start of 5-9 period)."""
    from src.core.timeframe_builder import _floor_to_period

    assert _floor_to_period(0, 5) == 0  # minute 0: start of first period
    assert _floor_to_period(299, 5) == 0  # minute 4:59: still first period (0-4)
    assert _floor_to_period(300, 5) == 300  # minute 5: start of second period (5-9)
    assert _floor_to_period(301, 5) == 300  # minute 5:01: same period
    assert _floor_to_period(599, 5) == 300  # minute 9:59: still 5-9 period
    assert _floor_to_period(600, 5) == 600  # minute 10: start of third period (10-14)
    assert _floor_to_period(3600, 5) == 3600  # top of hour: exact period start


def test_period_boundary_15m():
    """Floor to 15m boundary."""
    from src.core.timeframe_builder import _floor_to_period

    assert _floor_to_period(900, 15) == 900  # minute 15
    assert _floor_to_period(1799, 15) == 900  # minute 29:59
    assert _floor_to_period(1800, 15) == 1800  # minute 30


def test_period_boundary_1h():
    """Floor to 1h boundary."""
    from src.core.timeframe_builder import _floor_to_period

    assert _floor_to_period(3600, 60) == 3600  # hour 1
    assert _floor_to_period(3659, 60) == 3600  # hour 1:59
    assert _floor_to_period(7200, 60) == 7200  # hour 2


# ---------------------------------------------------------------------------
# Test OHLCV accumulation logic
# ---------------------------------------------------------------------------


def test_accumulator_first_bar():
    """First bar in period sets open/high/low/close/volume directly."""
    from src.core.timeframe_builder import _update_accumulator

    acc = None
    bar = {
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 100,
        "period_ts": 300,
    }
    result = _update_accumulator(acc, bar, period_ts=300)

    assert result["open"] == 100.0
    assert result["high"] == 102.0
    assert result["low"] == 99.0
    assert result["close"] == 101.0
    assert result["volume"] == 100
    assert result["period_ts"] == 300


def test_accumulator_subsequent_bars():
    """Subsequent bars update high/low/close/volume correctly."""
    from src.core.timeframe_builder import _update_accumulator

    # First bar
    bar1 = {
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 100,
        "period_ts": 300,
    }
    acc = _update_accumulator(None, bar1, period_ts=300)

    # Second bar — higher high, lower low
    bar2 = {
        "open": 101.0,
        "high": 103.0,
        "low": 98.0,
        "close": 102.0,
        "volume": 150,
        "period_ts": 300,
    }
    acc = _update_accumulator(acc, bar2, period_ts=300)

    assert acc["open"] == 100.0  # unchanged from first bar
    assert acc["high"] == 103.0  # max(102, 103)
    assert acc["low"] == 98.0  # min(99, 98)
    assert acc["close"] == 102.0  # last bar close
    assert acc["volume"] == 250  # 100 + 150
    assert acc["period_ts"] == 300


def test_accumulates_1m_into_5m():
    """5 consecutive 1m bars within the same 5m period produce correct OHLCV accumulation."""
    from src.core.timeframe_builder import _update_accumulator

    # Bars at minutes 0,1,2,3,4 (all in period starting at 0)
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100},
        {"open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 120},
        {"open": 101.0, "high": 101.5, "low": 100.5, "close": 101.2, "volume": 80},
        {"open": 101.2, "high": 103.0, "low": 100.8, "close": 102.0, "volume": 200},
        {"open": 102.0, "high": 102.5, "low": 101.5, "close": 102.3, "volume": 90},
    ]

    acc = None
    for bar in bars:
        bar["period_ts"] = 0
        acc = _update_accumulator(acc, bar, period_ts=0)

    assert acc["open"] == 100.0  # first bar open
    assert acc["high"] == 103.0  # max of all highs
    assert acc["low"] == 99.0  # min of all lows
    assert acc["close"] == 102.3  # last bar close
    assert acc["volume"] == 590  # sum: 100+120+80+200+90


def test_period_boundary_emits_bar():
    """New period bar triggers emit of previous accumulated bar."""
    from src.core.timeframe_builder import _floor_to_period, _update_accumulator

    # First 5m period bars (ts 0..299)
    acc_5m = None
    for ts in [0, 60, 120, 180, 240]:  # minutes 0-4
        period_ts = _floor_to_period(ts, 5)
        bar = {
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 100,
            "period_ts": period_ts,
        }
        acc_5m = _update_accumulator(acc_5m, bar, period_ts=period_ts)

    # Bar at ts=300 (minute 5) — new 5m period
    new_period_ts = _floor_to_period(300, 5)
    assert new_period_ts == 300

    # The old period_ts (0) differs from new period_ts (300) → should emit acc_5m
    assert acc_5m is not None
    assert acc_5m["period_ts"] == 0  # previously accumulated period

    # New accumulator starts fresh
    new_bar = {
        "open": 101.0,
        "high": 102.0,
        "low": 100.5,
        "close": 101.5,
        "volume": 150,
        "period_ts": 300,
    }
    new_acc = _update_accumulator(None, new_bar, period_ts=300)
    assert new_acc["open"] == 101.0
    assert new_acc["period_ts"] == 300


# ---------------------------------------------------------------------------
# Test TimeframeBuilder API (async — mock Redis)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeframe_builder_get_metrics():
    """get_metrics() returns expected keys after construction."""
    from src.core.timeframe_builder import TimeframeBuilder

    mock_streams = MagicMock()
    builder = TimeframeBuilder(mock_streams)

    metrics = builder.get_metrics()
    expected_keys = {
        "bars_1m_processed",
        "bars_5m_built",
        "bars_15m_built",
        "bars_1h_built",
        "bars_4h_built",
        "bars_1d_built",
        "symbols_active",
    }
    assert set(metrics.keys()) == expected_keys
    assert metrics["bars_1m_processed"] == 0
    assert metrics["symbols_active"] == set()


@pytest.mark.asyncio
async def test_timeframe_builder_subscribe_adds_symbols():
    """subscribe_to_symbols() adds to the active symbols set."""
    from src.core.timeframe_builder import TimeframeBuilder

    mock_streams = MagicMock()
    builder = TimeframeBuilder(mock_streams)

    await builder.subscribe_to_symbols(["ESH6", "NQH6"])

    metrics = builder.get_metrics()
    assert metrics["symbols_active"] == {"ESH6", "NQH6"}


@pytest.mark.asyncio
async def test_timeframe_builder_start_stop():
    """start() and stop() complete without error (no live Redis needed)."""
    from src.core.timeframe_builder import TimeframeBuilder

    mock_redis = AsyncMock()
    mock_redis.xread = AsyncMock(return_value=[])
    mock_streams = MagicMock()
    mock_streams.redis_client = mock_redis

    builder = TimeframeBuilder(mock_streams)

    # Start creates the processing task
    await builder.start()
    assert builder._running is True

    # Stop cancels it
    await builder.stop()
    assert builder._running is False


@pytest.mark.asyncio
async def test_bar_accumulation_emits_on_new_period():
    """
    Process 6 x 1m bars: first 5 belong to period 0, 6th to period 300.
    Expect exactly 1 xadd call for the 5m bar when period boundary detected.
    """
    from src.core.timeframe_builder import TimeframeBuilder

    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_streams = MagicMock()
    mock_streams.redis_client = mock_redis

    # Patch Settings to avoid env dep
    with patch("src.core.timeframe_builder.Settings") as MockSettings:
        MockSettings.return_value.env_name = "development"
        builder = TimeframeBuilder(mock_streams)
        await builder.subscribe_to_symbols(["ESH6"])

        # Process 5 bars in period 0 (ts=0..240, period_ts=0)
        for i in range(5):
            ts = i * 60  # 0, 60, 120, 180, 240
            await builder._process_bar(
                "ESH6",
                {
                    "timestamp": str(ts),
                    "open": "100.0",
                    "high": "101.0",
                    "low": "99.0",
                    "close": "100.5",
                    "volume": "100",
                },
            )

        # No emit yet — still in same 5m period
        assert mock_redis.xadd.call_count == 0

        # 6th bar at ts=300 — new 5m period triggers emit of the previous 5m bar
        await builder._process_bar(
            "ESH6",
            {
                "timestamp": "300",
                "open": "101.0",
                "high": "102.0",
                "low": "100.5",
                "close": "101.5",
                "volume": "120",
            },
        )

        # At least 1 xadd call for the completed 5m bar
        assert mock_redis.xadd.call_count >= 1


@pytest.mark.asyncio
async def test_zero_volume_real_price_bar_accumulates():
    """Bar with volume=0 but close>0 (crypto paper trading) must accumulate.
    Verify a 5m bar is eventually emitted after 5 such bars.
    """
    from src.core.timeframe_builder import TimeframeBuilder

    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_streams = MagicMock()
    mock_streams.redis_client = mock_redis

    # Patch Settings to avoid env dep
    with patch("src.core.timeframe_builder.Settings") as MockSettings:
        MockSettings.return_value.env_name = "development"
        builder = TimeframeBuilder(mock_streams)
        await builder.subscribe_to_symbols(["BTCUSD"])

    # Process 5 bars with volume=0 but real price (crypto paper trading behavior)
    # All in same 5m period (ts=0..240, period_ts=0)
    for i in range(5):
        ts = i * 60  # 0, 60, 120, 180, 240
        await builder._process_bar(
            "BTCUSD",
            {
                "timestamp": str(ts),
                "open": "66900.0",
                "high": str(66900.0 + i * 10),
                "low": str(66890.0 - i * 5),
                "close": str(66950.0 + i * 5),
                "volume": "0",  # Paper trading returns volume=0 for crypto
            },
        )

    # No emit yet — still in same 5m period
    assert mock_redis.xadd.call_count == 0

    # 6th bar at ts=300 — new 5m period triggers emit of previous 5m bar
    await builder._process_bar(
        "BTCUSD",
        {
            "timestamp": "300",
            "open": "67000.0",
            "high": "67100.0",
            "low": "66900.0",
            "close": "67050.0",
            "volume": "100",  # Now has volume (not required for emit)
        },
    )

    # At least 1 xadd call for the completed 5m bar
    # This test FAILS with current implementation (volume==0 skips all bars)
    assert mock_redis.xadd.call_count >= 1


@pytest.mark.asyncio
async def test_zero_volume_zero_price_bar_skipped():
    """Bar with volume=0 AND close=0 (genuine empty bar) must be skipped."""
    from src.core.timeframe_builder import TimeframeBuilder

    mock_redis = AsyncMock()
    mock_redis.xadd = AsyncMock()
    mock_streams = MagicMock()
    mock_streams.redis_client = mock_redis

    # Patch Settings to avoid env dep
    with patch("src.core.timeframe_builder.Settings") as MockSettings:
        MockSettings.return_value.env_name = "development"
        builder = TimeframeBuilder(mock_streams)
        await builder.subscribe_to_symbols(["ESH6"])

    # Process 5 bars with volume=0 and close=0.0 (genuine empty bars)
    for i in range(5):
        ts = i * 60
        await builder._process_bar(
            "ESH6",
            {
                "timestamp": str(ts),
                "open": "0.0",
                "high": "0.0",
                "low": "0.0",
                "close": "0.0",
                "volume": "0",
            },
        )

    # 6th bar to trigger potential emit
    await builder._process_bar(
        "ESH6",
        {
            "timestamp": "300",
            "open": "100.0",
            "high": "101.0",
            "low": "99.0",
            "close": "100.5",
            "volume": "100",
        },
    )

    # No xadd calls — bars were all skipped (volume==0 and close==0.0)
    assert mock_redis.xadd.call_count == 0
