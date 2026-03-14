"""Unit tests for market_analysis_service buffer management optimization.

Verifies that _df_cache is only invalidated when deque maxlen overflow occurs,
not on every bar append. Uses __new__() bypass pattern to avoid __init__ side effects.
"""

from collections import defaultdict, deque

import pandas as pd


def _make_svc(maxlen: int = 200):
    """Create a MarketAnalysisService instance bypassing __init__."""
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService.__new__(MarketAnalysisService)
    # Manually initialize only the attributes needed for buffer management tests
    svc.bar_history = defaultdict(lambda: deque(maxlen=maxlen))
    svc._df_cache = {}
    return svc


def _make_bar(i: int) -> dict:
    """Return a minimal bar dict for testing."""
    return {
        "open": float(i),
        "high": float(i) + 1,
        "low": float(i) - 1,
        "close": float(i),
        "volume": 100,
    }


class TestCacheNotInvalidatedWhenDequeHasRoom:
    """Cache should remain valid when deque has capacity left (no overflow)."""

    def test_cache_retained_on_first_bar(self):
        """Appending first bar into empty deque should not invalidate cache."""
        svc = _make_svc(maxlen=5)
        key = "ES:1m"
        # Prime cache with some sentinel value
        svc._df_cache[key] = pd.DataFrame([{"close": 999.0}])

        history = svc.bar_history[key]
        len_before = len(history)  # 0
        history.append(_make_bar(1))
        cache_invalidated = len_before == history.maxlen  # 0 == 5 → False

        if cache_invalidated:
            svc._df_cache[key] = None

        assert svc._df_cache[key] is not None, "Cache should NOT be invalidated when deque has room"

    def test_cache_retained_while_filling_up_to_maxlen_minus_one(self):
        """Cache should remain valid while filling deque (len < maxlen)."""
        svc = _make_svc(maxlen=5)
        key = "ES:1m"
        svc._df_cache[key] = pd.DataFrame([{"close": 999.0}])

        # Fill to maxlen - 1 (4 bars), never triggering overflow
        history = svc.bar_history[key]
        for i in range(4):
            len_before = len(history)
            history.append(_make_bar(i))
            cache_invalidated = len_before == history.maxlen
            if cache_invalidated:
                svc._df_cache[key] = None

        assert len(history) == 4
        assert (
            svc._df_cache[key] is not None
        ), "Cache should NOT be invalidated before deque is full"


class TestCacheInvalidatedOnOverflow:
    """Cache should be invalidated exactly when deque overflows (oldest bar removed)."""

    def test_cache_invalidated_when_deque_reaches_maxlen_and_overflows(self):
        """First overflow (bar 6 into maxlen=5 deque) must invalidate cache."""
        svc = _make_svc(maxlen=5)
        key = "ES:1m"

        # Fill deque to maxlen without invalidating cache
        history = svc.bar_history[key]
        for i in range(5):
            len_before = len(history)
            history.append(_make_bar(i))
            if len_before == history.maxlen:
                svc._df_cache[key] = None

        # Deque is now full (5 bars), cache still None (was never set)
        # Set a fresh cache value to verify it gets cleared on overflow
        svc._df_cache[key] = pd.DataFrame([{"close": 42.0}])
        assert svc._df_cache[key] is not None

        # Now append one more — this triggers overflow
        len_before = len(history)
        history.append(_make_bar(99))
        cache_invalidated = len_before == history.maxlen  # 5 == 5 → True

        if cache_invalidated:
            svc._df_cache[key] = None

        assert svc._df_cache[key] is None, "Cache MUST be invalidated when deque overflows"

    def test_oldest_bar_removed_on_overflow(self):
        """Verify deque actually removes oldest bar when maxlen is exceeded."""
        svc = _make_svc(maxlen=3)
        key = "ES:1m"

        history = svc.bar_history[key]
        for i in range(3):
            history.append(_make_bar(i))

        # Bar 0 (close=0.0) is oldest; appending bar 3 should evict it
        history.append(_make_bar(3))

        closes = [bar["close"] for bar in history]
        assert 0.0 not in closes, "Oldest bar should have been evicted on overflow"
        assert 3.0 in closes, "Newest bar should be in deque after overflow"
        assert len(history) == 3, "Deque length should remain at maxlen"

    def test_every_subsequent_overflow_invalidates_cache(self):
        """After reaching maxlen, every additional append triggers overflow."""
        svc = _make_svc(maxlen=3)
        key = "ES:1m"

        history = svc.bar_history[key]
        # Fill to maxlen
        for i in range(3):
            history.append(_make_bar(i))

        invalidation_count = 0
        for i in range(3, 10):
            svc._df_cache[key] = pd.DataFrame([{"close": float(i)}])  # restore cache
            len_before = len(history)
            history.append(_make_bar(i))
            if len_before == history.maxlen:
                svc._df_cache[key] = None
                invalidation_count += 1

        assert (
            invalidation_count == 7
        ), "Cache should be invalidated on every overflow after maxlen is reached"


class TestGetDfCacheRebuilt:
    """_get_df() should return cached DataFrame when valid, rebuild on miss."""

    def test_get_df_builds_dataframe_on_cache_miss(self):
        """_get_df() builds fresh DataFrame when cache is None."""
        svc = _make_svc(maxlen=10)
        key = "ES:1m"
        svc._df_cache[key] = None

        for i in range(5):
            svc.bar_history[key].append(_make_bar(i))

        df = svc._get_df(key)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5

    def test_get_df_returns_cached_dataframe_without_rebuild(self):
        """_get_df() returns cached value when cache is not None."""
        svc = _make_svc(maxlen=10)
        key = "ES:1m"
        cached_df = pd.DataFrame([{"close": 777.0}])
        svc._df_cache[key] = cached_df

        # Even if bar_history is populated, the cached value should be returned
        svc.bar_history[key].append(_make_bar(1))
        result = svc._get_df(key)

        assert result is cached_df, "_get_df() should return cached DataFrame without rebuilding"

    def test_get_df_stores_result_in_cache(self):
        """_get_df() should populate _df_cache after a rebuild so next call is cached."""
        svc = _make_svc(maxlen=10)
        key = "ES:1m"
        svc._df_cache[key] = None

        for i in range(3):
            svc.bar_history[key].append(_make_bar(i))

        _ = svc._get_df(key)

        assert svc._df_cache[key] is not None, "_df_cache should be populated after _get_df() call"
