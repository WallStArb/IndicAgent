import logging
from datetime import UTC, datetime

import pytest

from src.core.bar_accumulator import BarAccumulator
from src.core.schemas.bar_message import BarMessage, SessionType


# ---------------------------------------------------------------------------
# Forward-only timestamp guard tests (AGG-TIMESTAMP-GUARD)
# ---------------------------------------------------------------------------


def _make_bar(ts: datetime, symbol: str = "ES") -> BarMessage:
    return BarMessage(
        ts=ts,
        symbol=symbol,
        tf="1m",
        open=4000.0,
        high=4001.0,
        low=3999.0,
        close=4000.0,
        volume=100,
        source="ibkr",
        session_type=SessionType.RTH,
    )


def test_out_of_order_bar_returns_empty_list():
    """update() must return [] when bar_ts <= prev accumulator last_ts."""
    accumulator = BarAccumulator(timeframes=["5m"])

    t1 = datetime(2026, 4, 23, 13, 0, tzinfo=UTC)
    t2 = datetime(2026, 4, 23, 13, 1, tzinfo=UTC)

    # Feed first bar — establishes last_ts
    result1 = accumulator.update(_make_bar(t1))
    assert isinstance(result1, list)

    # Feed second bar so last_ts advances
    result2 = accumulator.update(_make_bar(t2))
    assert isinstance(result2, list)

    # Now feed a bar at exactly t1 (equal to first ts) — out of order
    result_dup = accumulator.update(_make_bar(t1))
    assert result_dup == [], f"Expected [] for duplicate ts, got {result_dup}"


def test_backwards_bar_returns_empty_list():
    """update() must return [] when bar_ts < prev accumulator last_ts."""
    accumulator = BarAccumulator(timeframes=["5m"])

    t1 = datetime(2026, 4, 23, 13, 5, tzinfo=UTC)
    t_before = datetime(2026, 4, 23, 13, 4, tzinfo=UTC)

    # Feed forward bar
    accumulator.update(_make_bar(t1))

    # Feed bar from the past
    result = accumulator.update(_make_bar(t_before))
    assert result == [], f"Expected [] for backward ts, got {result}"


def test_first_bar_for_symbol_tf_always_accepted():
    """First bar for a (symbol, tf) pair has no prior last_ts — must be accepted."""
    accumulator = BarAccumulator(timeframes=["5m"])
    t = datetime(2026, 4, 23, 13, 0, tzinfo=UTC)

    # No prior state — first bar must NOT be rejected
    result = accumulator.update(_make_bar(t, symbol="NQ"))
    # The bar is accumulated (accumulator created), not returned as HTF yet
    assert "NQ:5m" in accumulator._accumulators


def test_out_of_order_does_not_corrupt_accumulator():
    """Rejected out-of-order bars must not modify accumulator state."""
    accumulator = BarAccumulator(timeframes=["5m"])

    t1 = datetime(2026, 4, 23, 13, 0, tzinfo=UTC)
    t2 = datetime(2026, 4, 23, 13, 1, tzinfo=UTC)

    accumulator.update(_make_bar(t1))
    accumulator.update(_make_bar(t2))

    state_before = accumulator._accumulators["ES:5m"].copy()

    # Out-of-order bar — should be rejected
    accumulator.update(_make_bar(t1))

    state_after = accumulator._accumulators["ES:5m"]
    assert state_after["last_ts"] == state_before["last_ts"], (
        "last_ts must not change after rejecting out-of-order bar"
    )


# ---------------------------------------------------------------------------
# _validate_accumulator runs unconditionally (AUDIT-LOW-5)
# ---------------------------------------------------------------------------


def test_validate_accumulator_runs_without_debug_flag():
    """_is_accumulator_valid() must be callable without __debug__ guard.

    Confirms the method is reachable and validates correctly regardless of
    the Python optimization flag (python -O strips __debug__ blocks).
    """
    accumulator = BarAccumulator(timeframes=["5m"])
    # Valid accumulator
    valid_acc = {
        "period_ts": 1000, "open": 4000.0, "high": 4001.0,
        "low": 3999.0, "close": 4000.0, "volume": 100, "last_ts": 1060,
    }
    assert accumulator._is_accumulator_valid(valid_acc) is True

    # Invalid accumulator (high < low)
    invalid_acc = valid_acc.copy()
    invalid_acc["high"] = 3998.0
    assert accumulator._is_accumulator_valid(invalid_acc) is False


def test_corrupted_accumulator_detected():
    """Test that corrupted accumulator state is detected."""
    accumulator = BarAccumulator(timeframes=["5m"])

    # Add a normal bar
    bar = BarMessage(
        ts=datetime(2026, 3, 29, 13, 0, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4001.0, low=3999.0, close=4000.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )
    accumulator.update(bar)

    # Corrupt the accumulator state
    key = "ES:5m"
    accumulator._accumulators[key]["high"] = 3998.0  # high < low!

    # Add another bar - corruption should be detected
    bar2 = BarMessage(
        ts=datetime(2026, 3, 29, 13, 1, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4002.0, low=3999.0, close=4001.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )

    # Should detect corruption and log warning
    result = accumulator.update(bar2)

    # Verify accumulator was reset
    acc = accumulator._accumulators.get("ES:5m")
    assert acc is not None
    assert acc["high"] == 4002.0  # Should have new bar's high
    assert acc["low"] == 3999.0   # Should have new bar's low


def test_missing_key_accumulator_detected():
    """Test that accumulator with missing keys is detected."""
    accumulator = BarAccumulator(timeframes=["5m"])

    # Add a normal bar
    bar = BarMessage(
        ts=datetime(2026, 3, 29, 13, 0, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4001.0, low=3999.0, close=4000.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )
    accumulator.update(bar)

    # Remove a required key from accumulator
    key = "ES:5m"
    del accumulator._accumulators[key]["low"]

    # Add another bar - corruption should be detected
    bar2 = BarMessage(
        ts=datetime(2026, 3, 29, 13, 1, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4002.0, low=3999.0, close=4001.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )

    # Should detect corruption and reset
    result = accumulator.update(bar2)

    # Verify accumulator was reset with new bar data
    acc = accumulator._accumulators.get("ES:5m")
    assert acc is not None
    assert acc["high"] == 4002.0


def test_invalid_type_accumulator_detected():
    """Test that accumulator with invalid data types is detected."""
    accumulator = BarAccumulator(timeframes=["5m"])

    # Add a normal bar
    bar = BarMessage(
        ts=datetime(2026, 3, 29, 13, 0, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4001.0, low=3999.0, close=4000.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )
    accumulator.update(bar)

    # Corrupt the accumulator state by making high a string
    key = "ES:5m"
    accumulator._accumulators[key]["high"] = "invalid_string"

    # Add another bar - corruption should be detected
    bar2 = BarMessage(
        ts=datetime(2026, 3, 29, 13, 1, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4002.0, low=3999.0, close=4001.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )

    # Should detect corruption and reset
    result = accumulator.update(bar2)

    # Verify accumulator was reset
    acc = accumulator._accumulators.get("ES:5m")
    assert acc is not None
    assert acc["high"] == 4002.0
    assert isinstance(acc["high"], (int, float))


def test_valid_accumulator_not_reset():
    """Test that valid accumulator state is not reset."""
    accumulator = BarAccumulator(timeframes=["5m"])

    # Add a normal bar
    bar = BarMessage(
        ts=datetime(2026, 3, 29, 13, 0, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4001.0, low=3999.0, close=4000.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )
    accumulator.update(bar)

    # Get accumulator state before update
    key = "ES:5m"
    original_acc = accumulator._accumulators[key].copy()

    # Add another valid bar
    bar2 = BarMessage(
        ts=datetime(2026, 3, 29, 13, 1, tzinfo=UTC),
        symbol="ES", tf="1m",
        open=4000.0, high=4002.0, low=3998.0, close=4001.0,
        volume=100, source="ibkr", session_type=SessionType.RTH
    )

    # Should not detect corruption, should update normally
    result = accumulator.update(bar2)

    # Verify accumulator was updated, not reset
    acc = accumulator._accumulators.get("ES:5m")
    assert acc is not None
    assert acc["high"] == 4002.0  # Updated to max of original and new
    assert acc["low"] == 3998.0   # Updated to min of original and new
    assert acc["volume"] == 200    # Sum of both volumes
    assert acc["close"] == 4001.0  # Latest close price
