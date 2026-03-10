import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))


def test_aggregate_bars_from_1m_5m_groups_correctly():
    """Five 1m bars in the same 5m window produce one aggregated bar."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    base = datetime(2026, 3, 7, 9, 30, 0, tzinfo=timezone.utc)
    bars = [
        {"timestamp": base.replace(minute=30 + i), "open": 100 + i, "high": 105 + i,
         "low": 99 + i, "close": 101 + i, "volume": 10}
        for i in range(5)
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert len(result) == 1
    agg = result[0]
    assert agg["timestamp"] == base.replace(minute=30)
    assert agg["open"] == bars[0]["open"]
    assert agg["close"] == bars[-1]["close"]
    assert agg["high"] == max(b["high"] for b in bars)
    assert agg["low"] == min(b["low"] for b in bars)
    assert agg["volume"] == 50
    assert agg["source"] == "derived_1m"


def test_aggregate_bars_from_1m_splits_across_windows():
    """Bars spanning two 5m windows produce two aggregated bars."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    base = datetime(2026, 3, 7, 9, 33, 0, tzinfo=timezone.utc)
    bars = [
        {"timestamp": base.replace(minute=33), "open": 100, "high": 102, "low": 99, "close": 101, "volume": 5},
        {"timestamp": base.replace(minute=34), "open": 101, "high": 103, "low": 100, "close": 102, "volume": 5},
        {"timestamp": base.replace(minute=35), "open": 102, "high": 104, "low": 101, "close": 103, "volume": 5},
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert len(result) == 2
    assert result[0]["timestamp"] == base.replace(minute=30)
    assert result[1]["timestamp"] == base.replace(minute=35)


def test_aggregate_bars_from_1m_daily_floors_to_midnight():
    """1d aggregation floors timestamps to midnight."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    bars = [
        {"timestamp": datetime(2026, 3, 7, 9, 30, tzinfo=timezone.utc), "open": 100, "high": 105,
         "low": 99, "close": 104, "volume": 100},
        {"timestamp": datetime(2026, 3, 7, 15, 0, tzinfo=timezone.utc), "open": 104, "high": 106,
         "low": 103, "close": 105, "volume": 200},
    ]
    result = aggregate_bars_from_1m(bars, "1d")
    assert len(result) == 1
    assert result[0]["timestamp"] == datetime(2026, 3, 7, 0, 0, tzinfo=timezone.utc)
    assert result[0]["volume"] == 300


def test_aggregate_bars_from_1m_none_volume_treated_as_zero():
    """None volume values (FX has no volume) are treated as 0."""
    from production.scripts.historical_backfill import aggregate_bars_from_1m

    base = datetime(2026, 3, 7, 9, 30, tzinfo=timezone.utc)
    bars = [
        {"timestamp": base, "open": 1.10, "high": 1.11, "low": 1.09, "close": 1.105, "volume": None},
        {"timestamp": base.replace(minute=31), "open": 1.105, "high": 1.112, "low": 1.104, "close": 1.11, "volume": None},
    ]
    result = aggregate_bars_from_1m(bars, "5m")
    assert result[0]["volume"] == 0
