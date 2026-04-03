"""Test session boundary handling in BarAccumulator."""
from datetime import UTC, datetime, timedelta

from src.core.bar_accumulator import BarAccumulator
from src.core.bar_normalizer import SOURCE_IBKR_GENERIC
from src.core.schemas.bar_message import BarMessage, SessionType


def _create_bars(symbol: str, start_time: datetime, count: int) -> list[BarMessage]:
    """Helper to create test bars."""
    bars = []
    for i in range(count):
        bar = BarMessage(
            ts=start_time + timedelta(minutes=i),
            symbol=symbol,
            tf="1m",
            open=4000.0 + i,
            high=4001.0 + i,
            low=3999.0 + i,
            close=4000.5 + i,
            volume=100,
            source=SOURCE_IBKR_GENERIC,
            session_type=SessionType.RTH
        )
        bars.append(bar)
    return bars

def test_session_boundary_emits_partial_bar():
    """Test that RTH close triggers partial bar emission."""
    accumulator = BarAccumulator(timeframes=["5m"])

    # Add bars just before RTH close (15:55-15:59 ET = 19:55-19:59 UTC)
    bars = _create_bars("ES", datetime(2026, 3, 29, 19, 55, tzinfo=UTC), 5)
    for bar in bars:
        accumulator.update(bar)

    # RTH close at 16:00 ET (20:00 UTC) - triggers session boundary
    rth_close_bar = BarMessage(
        ts=datetime(2026, 3, 29, 20, 0, tzinfo=UTC),
        symbol="ES",
        tf="1m",
        open=4005.0,
        high=4006.0,
        low=4004.0,
        close=4005.5,
        volume=100,
        source=SOURCE_IBKR_GENERIC,
        session_type=SessionType.RTH
    )

    completed = accumulator.update(rth_close_bar)

    # Should emit partial 5m bar
    assert len(completed) == 1
    assert completed[0].tf == "5m"
    assert completed[0].source == "htf_derived"

    # Verify partial bar contains data from bars before boundary
    assert completed[0].open == 4000.0  # First bar's open
    assert completed[0].close == 4004.5  # Last complete bar's close before boundary

def test_session_boundary_starts_new_accumulator():
    """Test that session boundary starts fresh accumulator."""
    accumulator = BarAccumulator(timeframes=["5m"])

    # Add bars before RTH close (15:55-15:59 ET = 19:55-19:59 UTC)
    bars = _create_bars("ES", datetime(2026, 3, 29, 19, 55, tzinfo=UTC), 5)
    for bar in bars:
        accumulator.update(bar)

    # Cross session boundary at RTH close (16:00 ET = 20:00 UTC)
    rth_close_bar = BarMessage(
        ts=datetime(2026, 3, 29, 20, 0, tzinfo=UTC),
        symbol="ES",
        tf="1m",
        open=4005.0,
        high=4006.0,
        low=4004.0,
        close=4005.5,
        volume=100,
        source=SOURCE_IBKR_GENERIC,
        session_type=SessionType.RTH
    )
    completed_before = accumulator.update(rth_close_bar)

    # Add first bar after boundary (16:01 ET = 20:01 UTC, ETH session)
    next_bar = BarMessage(
        ts=datetime(2026, 3, 29, 20, 1, tzinfo=UTC),
        symbol="ES",
        tf="1m",
        open=4006.0,
        high=4007.0,
        low=4005.0,
        close=4006.5,
        volume=100,
        source=SOURCE_IBKR_GENERIC,
        session_type=SessionType.ETH  # After hours session
    )
    completed_after = accumulator.update(next_bar)

    # Verify partial bar was emitted at boundary
    assert len(completed_before) == 1

    # Verify new bar started fresh accumulation (needs 5 bars for 5m)
    assert len(completed_after) == 0

    # Check accumulator state is fresh with boundary bar's open value
    # (The boundary bar itself starts the new accumulator, not the next bar)
    acc = accumulator._accumulators.get("ES:5m")
    assert acc is not None
    assert acc["open"] == 4005.0  # Boundary bar's open (starts new accumulator)
