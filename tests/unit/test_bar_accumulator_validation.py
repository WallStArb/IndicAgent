from datetime import UTC, datetime

from src.core.bar_accumulator import BarAccumulator
from src.core.schemas.bar_message import BarMessage, SessionType


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
