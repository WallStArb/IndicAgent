"""Test stubs for BarHistory contract.

All tests are marked xfail (Wave 0). Implementation is in Wave 1 (44.1-02).
These stubs define the behavioral contract that the implementation must satisfy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.core.bar_normalizer import SOURCE_IBKR_NAMED

UTC = UTC

if TYPE_CHECKING:
    from src.core.schemas.bar_message import BarMessage


def _make_bar(
    symbol: str = "ES",
    tf: str = "1m",
    ts: datetime | None = None,
    close: float = 5250.0,
    volume: int = 1000,
) -> BarMessage:
    from src.core.schemas.bar_message import BarMessage, SessionType

    return BarMessage(
        ts=ts or datetime(2026, 3, 21, 14, 30, 0, tzinfo=UTC),
        symbol=symbol,
        tf=tf,
        open=close - 1.0,
        high=close + 1.0,
        low=close - 2.0,
        close=close,
        volume=volume,
        source=SOURCE_IBKR_NAMED,
        session_type=SessionType.RTH,
    )


def _make_bars_sequence(
    symbol: str = "ES",
    tf: str = "1m",
    count: int = 5,
    start_minute: int = 0,
) -> list:
    """Return `count` bars for (symbol, tf) at consecutive minute offsets."""
    from datetime import timedelta

    from src.core.schemas.bar_message import BarMessage, SessionType

    bars = []
    base_ts = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)
    for i in range(count):
        ts = base_ts + timedelta(minutes=start_minute + i)
        bars.append(
            BarMessage(
                ts=ts,
                symbol=symbol,
                tf=tf,
                open=5250.0 + i,
                high=5252.0 + i,
                low=5248.0 + i,
                close=5251.0 + i,
                volume=1000 + i * 100,
                source=SOURCE_IBKR_NAMED,
                session_type=SessionType.RTH,
            )
        )
    return bars


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_append_and_get():
    """append a BarMessage, get returns deque with that bar."""
    from src.core.bar_history import BarHistory

    bh = BarHistory()
    bar = _make_bar()
    bh.append(bar)
    result = bh.get("ES", "1m")
    assert len(result) == 1
    assert result[0] is bar


def test_maxlen_eviction():
    """append maxlen+1 bars, oldest evicted."""
    from src.core.bar_history import BarHistory

    bh = BarHistory(maxlen=3)
    bars = _make_bars_sequence(count=4)
    for bar in bars:
        bh.append(bar)
    result = bh.get("ES", "1m")
    assert len(result) == 3
    # The oldest bar should no longer be in the deque
    assert bars[0] not in result


def test_to_dataframe():
    """to_dataframe returns DataFrame with columns [timestamp, open, high, low, close, volume]."""
    import pandas as pd

    from src.core.bar_history import BarHistory

    bh = BarHistory()
    bars = _make_bars_sequence(count=3)
    for bar in bars:
        bh.append(bar)
    df = bh.to_dataframe("ES", "1m")
    assert isinstance(df, pd.DataFrame)
    for col in ("timestamp", "open", "high", "low", "close", "volume"):
        assert col in df.columns, f"Missing column: {col}"
    assert len(df) == 3


def test_to_dataframe_empty():
    """to_dataframe returns empty DataFrame for unknown (symbol, tf)."""
    import pandas as pd

    from src.core.bar_history import BarHistory

    bh = BarHistory()
    df = bh.to_dataframe("ZZ", "15m")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 0


def test_is_warm_true():
    """is_warm returns True when len >= min_bars."""
    from src.core.bar_history import BarHistory

    bh = BarHistory()
    bars = _make_bars_sequence(count=5)
    for bar in bars:
        bh.append(bar)
    assert bh.is_warm("ES", "1m", min_bars=5) is True
    assert bh.is_warm("ES", "1m", min_bars=3) is True


def test_is_warm_false():
    """is_warm returns False when len < min_bars."""
    from src.core.bar_history import BarHistory

    bh = BarHistory()
    bars = _make_bars_sequence(count=3)
    for bar in bars:
        bh.append(bar)
    assert bh.is_warm("ES", "1m", min_bars=5) is False
    assert bh.is_warm("ZZ", "1m", min_bars=1) is False  # unknown key


def test_seed():
    """seed with 250 bars, only last 200 kept (maxlen honored)."""
    from src.core.bar_history import BarHistory

    bh = BarHistory(maxlen=200)
    bars = _make_bars_sequence(count=250)
    bh.seed("ES", "1m", bars)
    result = bh.get("ES", "1m")
    assert len(result) == 200
    # Only the most recent 200 bars should be kept
    assert result[-1] is bars[-1]  # last bar is the most recent


def test_seed_chronological_order():
    """seed bars are in ts ascending order after seed (oldest first)."""
    from src.core.bar_history import BarHistory

    bh = BarHistory(maxlen=200)
    bars = _make_bars_sequence(count=10)
    bh.seed("ES", "1m", bars)
    result = bh.get("ES", "1m")
    timestamps = [b.ts for b in result]
    assert timestamps == sorted(timestamps)


def test_migrate_symbol():
    """bars move from old to new key for all TFs."""

    from src.core.bar_history import BarHistory
    from src.core.schemas.bar_message import BarMessage, SessionType

    bh = BarHistory()
    base_ts = datetime(2026, 3, 21, 14, 0, 0, tzinfo=UTC)
    for tf in ("1m", "5m"):
        bar = BarMessage(
            ts=base_ts,
            symbol="ESH6",
            tf=tf,
            open=5250.0,
            high=5252.0,
            low=5248.0,
            close=5251.0,
            volume=1000,
            source=SOURCE_IBKR_NAMED,
            session_type=SessionType.RTH,
        )
        bh.append(bar)

    bh.migrate_symbol("ESH6", "ESM6")

    # Old key should be empty; new key should have the bars
    assert len(bh.get("ESH6", "1m")) == 0
    assert len(bh.get("ESH6", "5m")) == 0
    assert len(bh.get("ESM6", "1m")) == 1
    assert len(bh.get("ESM6", "5m")) == 1


def test_migrate_symbol_no_data():
    """migrate on unknown symbol does not error."""
    from src.core.bar_history import BarHistory

    bh = BarHistory()
    # Should not raise
    bh.migrate_symbol("UNKNOWN", "ALSO_UNKNOWN")
    assert len(bh.get("ALSO_UNKNOWN", "1m")) == 0
