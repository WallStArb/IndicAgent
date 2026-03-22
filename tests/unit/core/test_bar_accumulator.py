"""Test stubs for BarAccumulator window logic.

All tests are marked xfail (Wave 0). Implementation is in Wave 1 (44.1-02).
These stubs define the behavioral contract that the implementation must satisfy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from src.core.schemas.bar_message import BarMessage

UTC = timezone.utc

# Base timestamp: 2026-03-21 14:00:00 UTC (09:00 ET — during RTH pre-open)
BASE_TS = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)


def _make_1m_bar(
    symbol: str = "ES",
    minute_offset: int = 0,
    open: float = 5250.0,
    high: float = 5252.0,
    low: float = 5248.0,
    close: float = 5251.0,
    volume: int = 1000,
    session_type=None,
) -> "BarMessage":
    from src.core.schemas.bar_message import BarMessage, SessionType

    return BarMessage(
        ts=BASE_TS + timedelta(minutes=minute_offset),
        symbol=symbol,
        tf="1m",
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        source="ibkr_named",
        session_type=session_type or SessionType.RTH,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_5m_boundaries():
    """Feed 5 sequential 1m bars at :00,:01,:02,:03,:04 then :05 — first 5m bar emitted at :05 boundary cross."""
    from src.core.bar_accumulator import BarAccumulator

    acc = BarAccumulator(timeframes=["5m"])
    emitted = []
    for minute in range(6):  # 0,1,2,3,4,5
        result = acc.update(_make_1m_bar(minute_offset=minute))
        emitted.extend(result)

    # Only one 5m bar should have been emitted (at the :05 boundary cross)
    five_m_bars = [b for b in emitted if b.tf == "5m"]
    assert len(five_m_bars) == 1


def test_15m_boundaries():
    """Feed 15 sequential 1m bars — 15m bar emitted at :15 boundary cross."""
    from src.core.bar_accumulator import BarAccumulator

    acc = BarAccumulator(timeframes=["15m"])
    emitted = []
    for minute in range(16):  # 0..15
        result = acc.update(_make_1m_bar(minute_offset=minute))
        emitted.extend(result)

    fifteen_m_bars = [b for b in emitted if b.tf == "15m"]
    assert len(fifteen_m_bars) == 1


def test_1h_boundaries():
    """Feed 60 sequential 1m bars — 1h bar emitted at :00 boundary cross."""
    from src.core.bar_accumulator import BarAccumulator

    acc = BarAccumulator(timeframes=["1h"])
    emitted = []
    for minute in range(61):  # 0..60
        result = acc.update(_make_1m_bar(minute_offset=minute))
        emitted.extend(result)

    one_h_bars = [b for b in emitted if b.tf == "1h"]
    assert len(one_h_bars) == 1


def test_gap_no_emission():
    """Skip 3 bars in a 5m window, feed bar at :05 — only the partial 5m bar from the window with data emitted."""
    from src.core.bar_accumulator import BarAccumulator

    # Feed bar at :00, skip :01,:02,:03, feed :04, then :05 (boundary)
    acc = BarAccumulator(timeframes=["5m"])
    emitted = []

    for minute in (0, 4, 5):  # gap between :00 and :04
        result = acc.update(_make_1m_bar(minute_offset=minute))
        emitted.extend(result)

    five_m_bars = [b for b in emitted if b.tf == "5m"]
    # One 5m bar emitted (for the window containing bars at :00 and :04)
    # No synthetic bar for the gap — only real data
    assert len(five_m_bars) == 1


def test_current_partial():
    """After 3 of 5 bars in a 5m window, current_partial returns in-progress bar with OHLCV from those 3 bars."""
    from src.core.bar_accumulator import BarAccumulator

    acc = BarAccumulator(timeframes=["5m"])
    for minute in range(3):  # :00, :01, :02
        acc.update(_make_1m_bar(minute_offset=minute))

    partial = acc.current_partial("ES", "5m")
    assert partial is not None
    assert partial.tf == "5m"
    assert partial.symbol == "ES"


def test_ohlcv_aggregation():
    """5m bar has correct open (first bar), high (max), low (min), close (last bar), volume (sum)."""
    from src.core.bar_accumulator import BarAccumulator

    acc = BarAccumulator(timeframes=["5m"])

    # Feed 5 bars with known OHLCV values, then bar at :05 to close the window
    bars_data = [
        # (minute, open, high, low, close, volume)
        (0, 5200.0, 5210.0, 5195.0, 5205.0, 1000),
        (1, 5205.0, 5215.0, 5200.0, 5210.0, 1100),
        (2, 5210.0, 5220.0, 5205.0, 5215.0, 900),
        (3, 5215.0, 5225.0, 5210.0, 5220.0, 800),
        (4, 5220.0, 5230.0, 5215.0, 5225.0, 1200),
    ]

    emitted = []
    for minute, o, h, low, c, v in bars_data:
        from src.core.schemas.bar_message import BarMessage, SessionType

        bar = BarMessage(
            ts=BASE_TS + timedelta(minutes=minute),
            symbol="ES",
            tf="1m",
            open=o,
            high=h,
            low=low,
            close=c,
            volume=v,
            source="ibkr_named",
            session_type=SessionType.RTH,
        )
        result = acc.update(bar)
        emitted.extend(result)

    # Feed boundary bar to close the 5m window
    result = acc.update(_make_1m_bar(minute_offset=5))
    emitted.extend(result)

    five_m = next((b for b in emitted if b.tf == "5m"), None)
    assert five_m is not None
    assert five_m.open == pytest.approx(5200.0)  # first bar's open
    assert five_m.high == pytest.approx(5230.0)  # max high
    assert five_m.low == pytest.approx(5195.0)  # min low
    assert five_m.close == pytest.approx(5225.0)  # last bar's close
    assert five_m.volume == 5000  # sum of volumes


def test_htf_derived_source():
    """Emitted HTF bars have source='htf_derived'."""
    from src.core.bar_accumulator import BarAccumulator

    acc = BarAccumulator(timeframes=["5m"])
    emitted = []
    for minute in range(6):
        result = acc.update(_make_1m_bar(minute_offset=minute))
        emitted.extend(result)

    five_m_bars = [b for b in emitted if b.tf == "5m"]
    assert len(five_m_bars) == 1
    assert five_m_bars[0].source == "htf_derived"


def test_no_1m_no_output():
    """update with a 5m bar (not 1m) returns empty list."""
    from src.core.bar_accumulator import BarAccumulator
    from src.core.schemas.bar_message import BarMessage, SessionType

    acc = BarAccumulator(timeframes=["5m", "15m"])
    bar_5m = BarMessage(
        ts=BASE_TS,
        symbol="ES",
        tf="5m",  # NOT 1m — should be ignored
        open=5250.0,
        high=5252.0,
        low=5248.0,
        close=5251.0,
        volume=5000,
        source="htf_derived",
        session_type=SessionType.RTH,
    )
    result = acc.update(bar_5m)
    assert result == []


def test_session_break_closes_partial():
    """Feed bars across a session boundary (per D-14) — partial bar is closed and emitted at session break."""
    from src.core.bar_accumulator import BarAccumulator, TradingSession
    from src.core.schemas.bar_message import SessionType

    # Use a custom TradingSession that considers every boundary between two
    # consecutive minutes a "session break" for testing purposes.
    # (Real implementation uses ET 09:30 / 16:00 boundaries for RTH.)
    # We simulate by constructing two bars far apart in time.

    # Bar at 08:00 ET (pre-RTH)
    pre_rth_ts = datetime(2026, 3, 21, 13, 0, 0, tzinfo=UTC)  # 08:00 ET
    # Bar at 09:30 ET (RTH open) — crosses session boundary
    rth_ts = datetime(2026, 3, 21, 14, 30, 0, tzinfo=UTC)  # 09:30 ET

    from src.core.schemas.bar_message import BarMessage

    bar_eth = BarMessage(
        ts=pre_rth_ts,
        symbol="ES",
        tf="1m",
        open=5240.0,
        high=5242.0,
        low=5238.0,
        close=5241.0,
        volume=300,
        source="ibkr_named",
        session_type=SessionType.ETH,
    )
    bar_rth = BarMessage(
        ts=rth_ts,
        symbol="ES",
        tf="1m",
        open=5250.0,
        high=5252.0,
        low=5248.0,
        close=5251.0,
        volume=1500,
        source="ibkr_named",
        session_type=SessionType.RTH,
    )

    session = TradingSession(SessionType.RTH)
    acc = BarAccumulator(timeframes=["5m"], session=session)

    emitted = []
    emitted.extend(acc.update(bar_eth))

    # The RTH bar is in a different session — partial ETH partial bar should be closed
    emitted.extend(acc.update(bar_rth))

    # The partial ETH 5m bar should have been emitted at session break
    # (even though it contains only 1 bar, not 5)
    five_m_bars = [b for b in emitted if b.tf == "5m"]
    assert len(five_m_bars) >= 1
    # The emitted bar should contain only the pre-RTH data (not mixed)
    eth_partial = five_m_bars[0]
    assert eth_partial.close == pytest.approx(5241.0)  # last ETH bar's close
