"""Unit tests for indicator_service buffer management optimization.

Tests verify that _df_cache is only invalidated when buffer capacity is
exceeded (oldest bar evicted), not on every bar append.

Uses __new__ pattern to bypass __init__ — avoids full service initialization.
"""

from collections import OrderedDict, defaultdict

import pandas as pd


def _make_service():
    """Create a minimal IndicatorComputeAgent instance for buffer tests."""
    import asyncio
    from unittest.mock import MagicMock

    from services.indicator_compute_agent import IndicatorComputeAgent

    svc = IndicatorComputeAgent.__new__(IndicatorComputeAgent)
    # BaseAgent attributes required by __new__ pattern (see CLAUDE.md)
    svc._stop_event = asyncio.Event()
    svc.name = "test"
    svc.logger = MagicMock()
    svc.bar_history = defaultdict(OrderedDict)
    svc._bar_history_max = 5  # small max for tests
    svc._df_cache = {}
    return svc


def _make_bar(ts: str, close: float = 100.0) -> dict:
    return {
        "timestamp": ts,
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 1000,
    }


class TestCacheNotInvalidatedWhenBufferHasRoom:
    """Cache must remain intact when buffer has room (len < _bar_history_max)."""

    def test_cache_retained_on_first_bar(self):
        svc = _make_service()
        key = "ES:1m"
        # Manually pre-populate cache with a sentinel
        sentinel = pd.DataFrame([{"close": 99.0}])
        svc._df_cache[key] = sentinel

        # Add first bar — buffer well under max (1 < 5)
        history = svc.bar_history[key]
        history["2026-01-01T10:00:00"] = _make_bar("2026-01-01T10:00:00", 100.0)

        cache_invalidated = False
        while len(history) > svc._bar_history_max:
            history.popitem(last=False)
            cache_invalidated = True

        if cache_invalidated:
            svc._df_cache[key] = None

        # Cache should NOT have been invalidated
        assert svc._df_cache[key] is sentinel, "Cache must not be invalidated when buffer has room"

    def test_cache_retained_when_filling_to_capacity(self):
        svc = _make_service()
        key = "ES:1m"
        sentinel = pd.DataFrame([{"close": 99.0}])
        svc._df_cache[key] = sentinel

        # Fill buffer exactly to max (5 bars) — no eviction needed
        for i in range(5):
            ts = f"2026-01-01T10:0{i}:00"
            history = svc.bar_history[key]
            history[ts] = _make_bar(ts, 100.0 + i)

            cache_invalidated = False
            while len(history) > svc._bar_history_max:
                history.popitem(last=False)
                cache_invalidated = True

            if cache_invalidated:
                svc._df_cache[key] = None

        # 5 bars, max=5 — no eviction occurred
        assert len(svc.bar_history[key]) == 5
        assert (
            svc._df_cache[key] is sentinel
        ), "Cache must not be invalidated when buffer exactly at max"


class TestCacheInvalidatedWhenCapacityExceeded:
    """Cache must be invalidated when buffer capacity is exceeded."""

    def test_cache_invalidated_on_capacity_exceeded(self):
        svc = _make_service()
        key = "ES:1m"

        # Fill to exactly max first
        for i in range(5):
            ts = f"2026-01-01T10:0{i}:00"
            svc.bar_history[key][ts] = _make_bar(ts, 100.0 + i)

        # Set sentinel after fill (simulating a pre-existing cache)
        sentinel = pd.DataFrame([{"close": 99.0}])
        svc._df_cache[key] = sentinel

        # Add one more bar — this EXCEEDS max and forces eviction
        ts_new = "2026-01-01T10:05:00"
        history = svc.bar_history[key]
        history[ts_new] = _make_bar(ts_new, 105.0)

        cache_invalidated = False
        while len(history) > svc._bar_history_max:
            history.popitem(last=False)
            cache_invalidated = True

        if cache_invalidated:
            svc._df_cache[key] = None

        assert cache_invalidated, "cache_invalidated flag must be True when capacity exceeded"
        assert svc._df_cache[key] is None, "Cache must be invalidated when oldest bar is evicted"
        assert len(svc.bar_history[key]) == 5, "Buffer must be trimmed to max"

    def test_only_oldest_bar_evicted(self):
        svc = _make_service()
        key = "ES:1m"
        timestamps = [f"2026-01-01T10:0{i}:00" for i in range(5)]

        for ts in timestamps:
            svc.bar_history[key][ts] = _make_bar(ts)

        # Add one beyond max — oldest should be evicted
        ts_new = "2026-01-01T10:05:00"
        history = svc.bar_history[key]
        history[ts_new] = _make_bar(ts_new)

        while len(history) > svc._bar_history_max:
            history.popitem(last=False)

        # Oldest timestamp (10:00) must be gone; newest (10:05) must remain
        assert timestamps[0] not in svc.bar_history[key], "Oldest bar must be evicted"
        assert ts_new in svc.bar_history[key], "Newest bar must be retained"


class TestGetDfCacheBehavior:
    """Tests for _get_df() lazy cache rebuild behavior."""

    def test_get_df_returns_cached_dataframe(self):
        svc = _make_service()
        key = "ES:1m"

        # Pre-populate history and cache
        for i in range(3):
            ts = f"2026-01-01T10:0{i}:00"
            svc.bar_history[key][ts] = _make_bar(ts, 100.0 + i)

        # Build cache via _get_df
        df1 = svc._get_df(key)
        df2 = svc._get_df(key)

        # Second call must return same object (cache hit, no rebuild)
        assert df1 is df2, "_get_df() must return cached DataFrame on repeated call"

    def test_get_df_rebuilds_after_cache_invalidation(self):
        svc = _make_service()
        key = "ES:1m"

        # Populate history
        for i in range(3):
            ts = f"2026-01-01T10:0{i}:00"
            svc.bar_history[key][ts] = _make_bar(ts, 100.0 + i)

        # Build initial cache
        df1 = svc._get_df(key)
        assert df1 is not None
        assert len(df1) == 3

        # Simulate cache invalidation (capacity exceeded)
        svc._df_cache[key] = None

        # Add a new bar and rebuild
        ts_new = "2026-01-01T10:03:00"
        svc.bar_history[key][ts_new] = _make_bar(ts_new, 103.0)

        df2 = svc._get_df(key)

        # Must be a new object (cache was rebuilt after invalidation)
        assert df2 is not df1, "_get_df() must rebuild DataFrame after cache invalidation"
        assert len(df2) == 4, "Rebuilt DataFrame must include all bars"

    def test_get_df_initializes_cache_for_new_key(self):
        svc = _make_service()
        key = "NQ:5m"

        # Populate history (no cache set yet)
        for i in range(3):
            ts = f"2026-01-01T10:0{i}:00"
            svc.bar_history[key][ts] = _make_bar(ts, 200.0 + i)

        df = svc._get_df(key)

        assert df is not None
        assert len(df) == 3
        assert svc._df_cache[key] is not None, "Cache must be populated after first _get_df call"
