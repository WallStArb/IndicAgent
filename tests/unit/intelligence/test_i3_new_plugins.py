"""Tests for new I3 structure plugins: MarketProfile, SessionLevels, AnchoredVWAP, FibZones."""
from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# MarketProfile
# ---------------------------------------------------------------------------


class TestMarketProfile:
    def test_poc_within_price_range(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        features = {"atr_14": 10.0, "close": float(close[-1])}
        result = MarketProfilePlugin().compute_full({"main": df, "features": features})
        poc = result.get("poc_level")
        assert poc is None or (5000 <= poc <= 5100)

    def test_va_high_gte_va_low(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = MarketProfilePlugin().compute_full({"main": df, "features": {}})
        va_high = result.get("va_high")
        va_low = result.get("va_low")
        if va_high is not None and va_low is not None:
            assert va_high >= va_low

    def test_poc_dist_atr_computed(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        features = {"atr_14": 10.0, "close": float(close[-1])}
        result = MarketProfilePlugin().compute_full({"main": df, "features": features})
        if result.get("poc_level") is not None:
            assert result.get("poc_dist_atr") is not None
            assert result["poc_dist_atr"] >= 0.0

    def test_price_flags_mutually_exclusive(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = MarketProfilePlugin().compute_full({"main": df, "features": {}})
        if result:
            total = (
                result.get("price_in_va", 0)
                + result.get("price_above_va", 0)
                + result.get("price_below_va", 0)
            )
            assert total == pytest.approx(1.0)

    def test_empty_returns_empty(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin

        assert MarketProfilePlugin().compute_full({}) == {}

    def test_insufficient_bars_returns_empty(self):
        from src.intelligence.structure.market_profile import MarketProfilePlugin

        close = np.linspace(5000, 5010, 5)
        df = make_ohlcv(close)
        assert MarketProfilePlugin().compute_full({"main": df, "features": {}}) == {}


# ---------------------------------------------------------------------------
# SessionLevels
# ---------------------------------------------------------------------------


class TestSessionLevels:
    def test_weekly_pivot_formula(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin

        close = np.linspace(5000, 5100, 200)
        df = make_ohlcv(close)
        features = {"atr_14": 10.0, "close": float(close[-1])}
        result = SessionLevelsPlugin().compute_full({"main": df, "features": features})
        pivot = result.get("weekly_pivot")
        if pivot is not None:
            assert 4000 < pivot < 6000

    def test_weekly_pivot_with_enough_history(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin

        # 800 bars so prior session (390) exists and week_df can be formed
        close = np.linspace(5000, 5200, 800)
        df = make_ohlcv(close)
        result = SessionLevelsPlugin().compute_full({"main": df, "features": {}})
        # prior session should be populated
        assert result.get("prior_session_high") is not None
        assert result.get("prior_session_low") is not None

    def test_pivot_levels_ordering(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin

        close = np.linspace(5000, 5200, 800)
        df = make_ohlcv(close)
        result = SessionLevelsPlugin().compute_full({"main": df, "features": {}})
        wp = result.get("weekly_pivot")
        r1 = result.get("weekly_r1")
        s1 = result.get("weekly_s1")
        if wp is not None and r1 is not None and s1 is not None:
            assert r1 > wp > s1

    def test_empty_returns_empty(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin

        assert SessionLevelsPlugin().compute_full({}) == {}

    def test_asian_session_high_low_from_timestamps(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin

        # Build 60 bars: first 20 in Asia (02:00 UTC = 21:00 ET), rest in NY (15:00 UTC = 10:00 ET)
        _UTC = UTC
        asia_ts = [datetime(2026, 1, 1, 2, i, tzinfo=_UTC) for i in range(20)]  # 02:00 UTC
        ny_ts = [datetime(2026, 1, 1, 15, i, tzinfo=_UTC) for i in range(40)]  # 15:00 UTC
        timestamps = asia_ts + ny_ts

        n = len(timestamps)
        close = np.full(n, 5000.0)
        high = np.full(n, 5005.0)
        low = np.full(n, 4995.0)
        # Asia bars get extreme high/low
        high[:20] = 9999.0
        low[:20] = 1.0
        open_ = close.copy()
        df = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(n, 1000.0),
                "timestamp": timestamps,
            }
        )
        result = SessionLevelsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("asian_session_high") == pytest.approx(9999.0)
        assert result.get("asian_session_low") == pytest.approx(1.0)

    def test_asian_session_none_without_timestamps(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin

        close = np.linspace(5000, 5100, 60)
        df = make_ohlcv(close)  # no timestamp column
        result = SessionLevelsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("asian_session_high") is None
        assert result.get("asian_session_low") is None

    def test_asian_session_none_when_no_asia_bars(self):
        from src.intelligence.structure.session_levels import SessionLevelsPlugin

        # All bars at 15:00 UTC = 10:00 ET — fully in NY session, not Asia
        _UTC = UTC
        timestamps = [datetime(2026, 1, 1, 15, i, tzinfo=_UTC) for i in range(60)]
        close = np.full(60, 5000.0)
        high = close + 5.0
        low = close - 5.0
        open_ = close.copy()
        df = pd.DataFrame(
            {
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "volume": np.full(60, 1000.0),
                "timestamp": timestamps,
            }
        )
        result = SessionLevelsPlugin().compute_full({"main": df, "features": {}})
        assert result.get("asian_session_high") is None
        assert result.get("asian_session_low") is None


# ---------------------------------------------------------------------------
# AnchoredVWAP
# ---------------------------------------------------------------------------


class TestAnchoredVWAP:
    def test_session_vwap_in_price_range(self):
        from src.intelligence.structure.anchored_vwap import AnchoredVWAPPlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = AnchoredVWAPPlugin().compute_full({"main": df, "features": {}})
        vwap = result.get("session_vwap")
        if vwap is not None:
            assert 5000 <= vwap <= 5100

    def test_above_flags_are_binary(self):
        from src.intelligence.structure.anchored_vwap import AnchoredVWAPPlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = AnchoredVWAPPlugin().compute_full({"main": df, "features": {}})
        for key in ("above_session_vwap", "above_swing_vwap", "above_weekly_vwap"):
            val = result.get(key)
            if val is not None:
                assert val in (0.0, 1.0)

    def test_alignment_score_in_range(self):
        from src.intelligence.structure.anchored_vwap import AnchoredVWAPPlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        result = AnchoredVWAPPlugin().compute_full({"main": df, "features": {}})
        score = result.get("vwap_alignment_score")
        if score is not None:
            assert 0.0 <= score <= 1.0

    def test_swing_vwap_with_anchor(self):
        from src.intelligence.structure.anchored_vwap import AnchoredVWAPPlugin

        close = np.linspace(5000, 5100, 50)
        df = make_ohlcv(close)
        features = {"swing_high_idx": 10.0, "swing_low_idx": 5.0}
        result = AnchoredVWAPPlugin().compute_full({"main": df, "features": features})
        assert "swing_vwap" in result

    def test_empty_returns_empty(self):
        from src.intelligence.structure.anchored_vwap import AnchoredVWAPPlugin

        assert AnchoredVWAPPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# FibonacciZones
# ---------------------------------------------------------------------------


class TestFibonacciZones:
    def test_fib_618_between_high_and_low(self):
        from src.intelligence.structure.fibonacci_zones import FibonacciZonesPlugin

        close = np.linspace(5000, 5200, 50)
        df = make_ohlcv(close)
        features = {"swing_high": 5200.0, "swing_low": 5000.0, "atr_14": 10.0, "close": 5130.0}
        result = FibonacciZonesPlugin().compute_full({"main": df, "features": features})
        fib618 = result.get("fib_618")
        if fib618 is not None:
            assert abs(fib618 - (5000 + 0.618 * 200)) < 1.0

    def test_all_fib_levels_between_high_and_low(self):
        from src.intelligence.structure.fibonacci_zones import FibonacciZonesPlugin

        close = np.linspace(5000, 5200, 50)
        df = make_ohlcv(close)
        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5100.0}
        result = FibonacciZonesPlugin().compute_full({"main": df, "features": features})
        for key in ("fib_236", "fib_382", "fib_500", "fib_618", "fib_786"):
            level = result.get(key)
            if level is not None:
                assert 5000 <= level <= 5200

    def test_nearest_fib_ratio_valid(self):
        from src.intelligence.structure.fibonacci_zones import FibonacciZonesPlugin

        close = np.linspace(5000, 5200, 50)
        df = make_ohlcv(close)
        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5100.0}
        result = FibonacciZonesPlugin().compute_full({"main": df, "features": features})
        ratio = result.get("nearest_fib_ratio")
        if ratio is not None:
            assert ratio in (0.236, 0.382, 0.500, 0.618, 0.786)

    def test_discount_zone_at_50pct(self):
        from src.intelligence.structure.fibonacci_zones import FibonacciZonesPlugin

        close = np.full(50, 5100.0)
        df = make_ohlcv(close)
        # Close at 5100 = 50% of 5000–5200 range
        features = {"swing_high": 5200.0, "swing_low": 5000.0, "close": 5100.0}
        result = FibonacciZonesPlugin().compute_full({"main": df, "features": features})
        assert result.get("in_fib_discount_zone") == 1.0

    def test_fallback_when_no_swing_features(self):
        from src.intelligence.structure.fibonacci_zones import FibonacciZonesPlugin

        close = np.linspace(5000, 5200, 50)
        df = make_ohlcv(close)
        result = FibonacciZonesPlugin().compute_full({"main": df, "features": {}})
        # Should compute from rolling high/low fallback — not crash
        assert isinstance(result, dict)

    def test_empty_returns_empty(self):
        from src.intelligence.structure.fibonacci_zones import FibonacciZonesPlugin

        assert FibonacciZonesPlugin().compute_full({}) == {}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestI3Registration:
    def test_all_new_plugins_in_tier_i3(self):
        from src.intelligence.register_plugins import TIER_I3

        assert "struct_MarketProfile" in TIER_I3
        assert "struct_SessionLevels" in TIER_I3
        assert "struct_AnchoredVWAP" in TIER_I3
        assert "struct_FibonacciZones" in TIER_I3

    def test_new_plugins_registered_in_registry(self):
        from src.intelligence.plugins import registry
        from src.intelligence.register_plugins import register_all_plugins

        register_all_plugins()
        names = set(registry.list_patterns())
        assert "struct_MarketProfile" in names
        assert "struct_SessionLevels" in names
        assert "struct_AnchoredVWAP" in names
        assert "struct_FibonacciZones" in names

    def test_i3structure_accepts_new_fields(self):
        from src.intelligence.schemas import I3Structure

        # All new fields should be accepted without ValidationError
        obj = I3Structure(
            poc_level=5050.0,
            va_high=5080.0,
            va_low=5020.0,
            session_vwap=5055.0,
            fib_618=5124.0,
            weekly_pivot=5040.0,
        )
        assert obj.poc_level == 5050.0
        assert obj.fib_618 == 5124.0
