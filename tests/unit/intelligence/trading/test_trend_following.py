"""Tests for TrendFollowing I7 trading setup plugin."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tests.unit.intelligence.helpers import make_ohlcv


def _make_frames(
    close_arr: np.ndarray,
    features: dict,
    *,
    symbol: str = "ES",
    tf: str = "1m",
) -> dict:
    """Build frames dict for TrendFollowingPlugin.compute_full()."""
    df = make_ohlcv(close_arr)
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
        "__symbol__": symbol,
        "__timeframe__": tf,
    }


def _bullish_features(sma: float = 5000.0) -> dict:
    """Standard bullish trend features."""
    return {
        "trend_regime": 0.8,
        "trend_confidence": 0.75,
        "swing_pattern": 1.0,
        "trend_strength": 0.7,
        "ctf_score": 0.6,
        "atr_14": 10.0,
        "sma_20": sma,
    }


class TestTrendFollowing:
    def test_broad_trend_state_no_signal(self):
        """Continuous bullish trend_regime with no structural entry -> no signal.

        This is the key Phase 124 invariant: 'is trending' state alone does NOT fire.
        Price is flat relative to SMA (no pullback, no consolidation breakout).
        """
        from src.intelligence.archive.trading_i7.trend_following import TrendFollowingPlugin

        plugin = TrendFollowingPlugin()
        close = np.full(100, 5000.0)
        # SMA == price throughout: no pullback (SMA never above price), no consolidation
        # (range spread from make_ohlcv is ~0.4% of price, just under 0.5% threshold,
        # but no breakout because consolidation_high would equal current close).
        # We set a wide-range bar by using high spread to ensure range > 0.5%.
        wide_close = np.linspace(5000.0, 5020.0, 100)  # gradual trend, wide range bars
        features = {
            "trend_regime": 0.8,
            "trend_confidence": 0.75,
            "swing_pattern": 1.0,
            "trend_strength": 0.7,
            "ctf_score": 0.6,
            "atr_14": 10.0,
            "sma_20": 5010.0,  # SMA roughly at midpoint - no pullback pattern
        }
        for _ in range(50):
            frames = _make_frames(wide_close, features, symbol="ES", tf="1m")
            result = plugin.compute_full(frames)
            # Strong trend state but no structural event -> no signal
            assert (
                result.get("signal_type", "none") == "none"
            ), f"Expected no signal on bar {_} (broad trend state only), got {result.get('signal_type')}"

    def test_pullback_reversal_fires_once(self):
        """Pullback-to-MA reversal fires once; does not fire on steady trend bars.

        Setup:
        - Pre-populate MA history with SMA values > current price (price was below SMA)
        - Feed a reversal bar: price crosses back above SMA
        - Verify: fires on reversal bar, deduplicate_event prevents immediate re-fire
        """
        from src.intelligence.archive.trading_i7.trend_following import (
            TrendFollowingPlugin,
        )

        plugin = TrendFollowingPlugin()
        symbol, tf = "ES", "1m"

        # Pre-populate MA history: 5 SMA values all > 5100 (price during pullback was ~5050)
        # This simulates price having been below SMA for 5 bars
        state = plugin._get_state(symbol, tf)
        for sma_val in [5110.0, 5115.0, 5120.0, 5125.0, 5130.0]:
            state.below_sma_history.append(True)

        # Now feed reversal bar: price = 5200 (above all previous SMAs), current SMA = 5100 (< price)
        # bars_below_sma = count(history[-4:] > 5200) -> all previous SMAs (5115-5130) < 5200 -> 0
        # That won't work. Need price to be just above current SMA but previous SMAs to be above price.
        # Trick: previous SMAs = 5200 (above current price 5150), current SMA = 5140 (just below price 5150)

        state.below_sma_history.clear()
        for sma_val in [5200.0, 5205.0, 5210.0, 5215.0, 5220.0]:
            state.below_sma_history.append(True)

        # Reversal bar: close = 5150, current_sma = 5140 (< 5150, price now above SMA)
        # bars_below_sma: history[-4:] = [5205, 5210, 5215, 5220], all > 5150 -> count = 4
        # 4 >= _PULLBACK_MIN_BARS - 1 (4) AND price (5150) > current_sma (5140) -> pullback_reversal!
        reversal_close = np.full(100, 5150.0)
        features_reversal = {
            "trend_regime": 0.8,
            "trend_confidence": 0.75,
            "swing_pattern": 1.0,
            "trend_strength": 0.7,
            "ctf_score": 0.6,
            "atr_14": 10.0,
            "sma_20": 5140.0,  # current SMA < close (5150) -> price crossed above SMA
        }

        frames = _make_frames(reversal_close, features_reversal, symbol=symbol, tf=tf)
        result = plugin.compute_full(frames)

        assert (
            result.get("signal_type") == "trend_long"
        ), f"Expected trend_long on pullback reversal bar, got {result.get('signal_type')}"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0

        # Second call with same structural_type -> deduplicate_event blocks re-fire
        result2 = plugin.compute_full(frames)
        assert (
            result2.get("signal_type", "none") == "none"
        ), "Expected no signal on re-fire (deduplicate_event should block same structural event)"

    def test_consolidation_breakout_fires_once(self):
        """Consolidation breakout fires on bar that exceeds consolidation_high.

        Setup:
        - Feed 5+ tight-range bars to build consolidation state (range < 0.5%)
        - Feed a breakout bar with close > consolidation_high
        - Verify: fires on breakout bar only
        """
        from src.intelligence.archive.trading_i7.trend_following import TrendFollowingPlugin

        plugin = TrendFollowingPlugin()
        symbol, tf = "ES", "1m"

        # Build consolidation: range < 0.5% of price 4200
        # 0.5% of 4200 = 21 points; make range = 5 points (< 21 -> consolidation)
        n_bars = 100
        consolidation_close = np.full(n_bars, 4200.0)

        # Build tight range DataFrame manually (spread = 5 pts, range_pct ~0.12%)
        consolidation_high_arr = np.full(n_bars, 4202.5)
        consolidation_low_arr = np.full(n_bars, 4197.5)
        open_arr = np.full(n_bars, 4200.0)
        volume_arr = np.full(n_bars, 1000.0)
        tight_df = pd.DataFrame(
            {
                "open": open_arr,
                "high": consolidation_high_arr,
                "low": consolidation_low_arr,
                "close": consolidation_close,
                "volume": volume_arr,
            }
        )

        features_consol = {
            "trend_regime": 0.8,
            "trend_confidence": 0.75,
            "swing_pattern": 1.0,
            "trend_strength": 0.7,
            "ctf_score": 0.6,
            "atr_14": 10.0,
            "sma_20": 4195.0,  # SMA below price (bullish)
        }
        consolidation_frames = {
            "main": tight_df,
            "i1": features_consol,
            "i2": features_consol,
            "i3": features_consol,
            "i4": features_consol,
            "i5": features_consol,
            "smc": features_consol,
            "i6": features_consol,
            "__symbol__": symbol,
            "__timeframe__": tf,
        }

        # Feed 6 consolidation bars (> _CONSOLIDATION_MIN_BARS = 5)
        for _ in range(6):
            result = plugin.compute_full(consolidation_frames)
            assert (
                result.get("signal_type", "none") == "none"
            ), f"Expected no signal during consolidation bar {_}"

        # State should now have consolidation_bars = 6, consolidation_high = 4202.5
        state = plugin._get_state(symbol, tf)
        assert state.consolidation_bars >= 5
        assert state.consolidation_high is not None

        consol_high = state.consolidation_high

        # Breakout bar: close > consolidation_high, range > 0.5% (expansion)
        breakout_close = np.full(n_bars, consol_high + 10.0)
        breakout_high_arr = np.full(n_bars, consol_high + 30.0)
        breakout_low_arr = np.full(n_bars, consol_high - 10.0)
        breakout_df = pd.DataFrame(
            {
                "open": np.full(n_bars, consol_high + 5.0),
                "high": breakout_high_arr,
                "low": breakout_low_arr,
                "close": breakout_close,
                "volume": volume_arr,
            }
        )

        features_breakout = {
            **features_consol,
            "sma_20": 4195.0,
        }
        breakout_frames = {
            "main": breakout_df,
            "i1": features_breakout,
            "i2": features_breakout,
            "i3": features_breakout,
            "i4": features_breakout,
            "i5": features_breakout,
            "smc": features_breakout,
            "i6": features_breakout,
            "__symbol__": symbol,
            "__timeframe__": tf,
        }

        result = plugin.compute_full(breakout_frames)
        assert (
            result.get("signal_type") == "trend_long"
        ), f"Expected trend_long on consolidation breakout, got {result.get('signal_type')}"
        assert result.get("direction") == 1
        assert 0.0 < result.get("confidence", 0) <= 1.0

        # deduplicate_event blocks immediate re-fire on same structural event
        result2 = plugin.compute_full(breakout_frames)
        assert (
            result2.get("signal_type", "none") == "none"
        ), "Expected no re-fire (deduplicate_event should block same consolidation_breakout_bull)"

    def test_no_signal_in_weak_regime(self):
        """Weak/neutral regime -> no signal generated (context filter blocks even with structural event)."""
        from src.intelligence.archive.trading_i7.trend_following import (
            TrendFollowingPlugin,
        )

        plugin = TrendFollowingPlugin()
        symbol, tf = "ES", "1m"

        # Pre-populate MA history to enable pullback detection
        state = plugin._get_state(symbol, tf)
        for sma_val in [5200.0, 5205.0, 5210.0, 5215.0, 5220.0]:
            state.below_sma_history.append(True)

        # Structural trigger would fire (pullback reversal), but regime too weak
        close = np.full(100, 5150.0)
        features = {
            "trend_regime": 0.2,  # below regime_min (0.5) -> context filter blocks
            "trend_confidence": 0.3,
            "swing_pattern": 0.0,
            "trend_strength": 0.1,
            "ctf_score": 0.1,
            "atr_14": 10.0,
            "sma_20": 5140.0,
        }
        result = plugin.compute_full(_make_frames(close, features, symbol=symbol, tf=tf))
        assert result.get("signal_type", "none") == "none"
        assert result.get("direction", 0) == 0

    def test_insufficient_data_returns_empty(self):
        """Too few bars -> empty result."""
        from src.intelligence.archive.trading_i7.trend_following import TrendFollowingPlugin

        close = np.array([5000.0, 5001.0, 5002.0])
        df = make_ohlcv(close)
        plugin = TrendFollowingPlugin()
        result = plugin.compute_full(
            {"main": df, "i1": {}, "i2": {}, "i3": {}, "i4": {}, "i5": {}, "smc": {}, "i6": {}}
        )
        assert result == {} or result.get("signal_type", "none") == "none"
