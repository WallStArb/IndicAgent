"""Failing test suite for CandlestickPatternSetup — RED phase before Plan 02.

All tests fail with ImportError because the plugin does not exist yet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.intelligence.archive.trading_i7.candlestick_pattern_setup import (
    CandlestickPatternSetupPlugin,
)
from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def make_candlestick_df(n: int = 50) -> pd.DataFrame:
    """Build a neutral OHLCV DataFrame — no synthetic patterns injected."""
    close = np.linspace(5000, 5100, n)
    return make_ohlcv(close)


def base_features(
    trend_regime: float = 0.7,
    engulfing_bull: float = 0.0,
    engulfing_bear: float = 0.0,
    pin_bar_bull: float = 0.0,
    pin_bar_bear: float = 0.0,
    hammer_detected: float = 0.0,
    shooting_star_detected: float = 0.0,
    has_sr_proximity: bool = False,
    atr: float = 10.0,
) -> tuple[pd.DataFrame, dict]:
    """Build (df, features) with all required I5/I4/I1/I3 fields.

    Returns a tuple so callers can manipulate df (e.g. inject high volume)
    before passing to compute_full.

    volume_sma_20 is always computed from df BEFORE any volume overwrite
    so that volume-confirm tests can reliably exceed the 1.3x threshold.
    """
    df = make_candlestick_df()
    vol_sma = float(np.mean(df["volume"].to_numpy()[-20:]))
    features: dict = {
        "trend_regime": trend_regime,
        "engulfing_bull": engulfing_bull,
        "engulfing_bear": engulfing_bear,
        "pin_bar_bull": pin_bar_bull,
        "pin_bar_bear": pin_bar_bear,
        "hammer_detected": hammer_detected,
        "shooting_star_detected": shooting_star_detected,
        "atr_14": atr,
        "volume_sma_20": vol_sma,
        # Phase 119: gate-passing values for dual gate
        "ctf_score": 0.5,
        "hmm_prob_trending_up": 0.6,
        "hmm_prob_trending_down": 0.3,
    }
    if has_sr_proximity:
        close = df["close"].iloc[-1]
        features["nearest_support"] = close - 0.1 * atr  # within 0.3 * atr
    return df, features


def inject_high_volume(df: pd.DataFrame, features: dict) -> pd.DataFrame:
    """Return a copy of df with the last bar's volume set to volume_sma_20 * 2.0.

    Invariant: df["volume"].iloc[-1] > features["volume_sma_20"] * 1.3 is guaranteed.
    """
    df = df.copy()
    df.iloc[-1, df.columns.get_loc("volume")] = features["volume_sma_20"] * 2.0
    return df


# ---------------------------------------------------------------------------
# CNDL-01 — Pattern detection reads I5 features (no OHLCV re-detection)
# ---------------------------------------------------------------------------


class TestCandlestickPatternDetection:
    """CNDL-01: plugin reads I5 feature flags, not raw OHLCV, for pattern detection."""

    def test_engulfing_bull_fires_long(self):
        """engulfing_bull + bullish trend + high volume -> direction==1, 'long' in signal_type."""
        df, features = base_features(engulfing_bull=1.0, trend_regime=0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["direction"] == 1
        assert "long" in result["signal_type"]

    def test_engulfing_bear_fires_short(self):
        """engulfing_bear + bearish trend + high volume -> direction==-1, 'short' in signal_type."""
        df, features = base_features(engulfing_bear=1.0, trend_regime=-0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["direction"] == -1
        assert "short" in result["signal_type"]

    def test_hammer_fires_without_extra_confirm(self):
        """hammer_detected=1.0, trend_regime=0.7, no volume boost, no S/R -> signal fires.

        Hammer satisfies S/R factor automatically — it does not need an additional confirm.
        """
        df, features = base_features(hammer_detected=1.0, trend_regime=0.7)
        # NOTE: no volume injection, no has_sr_proximity — hammer self-confirms S/R
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["direction"] == 1

    def test_shooting_star_fires_without_extra_confirm(self):
        """shooting_star + bearish trend, no volume boost, no S/R -> signal fires."""
        df, features = base_features(shooting_star_detected=1.0, trend_regime=-0.7)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["direction"] == -1


# ---------------------------------------------------------------------------
# CNDL-02 — Confluence gating
# ---------------------------------------------------------------------------


class TestCandlestickConfluenceGating:
    """CNDL-02: regime gate and direction-agreement gate block signals when not met."""

    def test_flat_regime_blocks_signal(self):
        """trend_regime=0.3 (< 0.5 threshold), any pattern, high volume -> signal_type == 'none'."""
        df, features = base_features(engulfing_bull=1.0, trend_regime=0.3)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["signal_type"] == "none"

    def test_bullish_pattern_in_bearish_trend(self):
        """engulfing_bull in bearish trend + high volume -> signal_type=='none' (mismatch)."""
        df, features = base_features(engulfing_bull=1.0, trend_regime=-0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["signal_type"] == "none"

    def test_bearish_pattern_in_bullish_trend(self):
        """engulfing_bear in bullish trend + high volume -> signal_type=='none' (mismatch)."""
        df, features = base_features(engulfing_bear=1.0, trend_regime=0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["signal_type"] == "none"

    def test_pin_bar_no_volume_no_sr_blocked(self):
        """pin_bar_bull=1.0, trend_regime=0.7, no volume boost, no S/R -> signal_type == 'none'.

        pin_bar does NOT self-confirm S/R — it needs at least one additional factor.
        """
        df, features = base_features(pin_bar_bull=1.0, trend_regime=0.7)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["signal_type"] == "none"

    def test_pin_bar_with_volume_fires(self):
        """pin_bar_bull=1.0, trend_regime=0.7, high volume -> signal fires, direction == 1."""
        df, features = base_features(pin_bar_bull=1.0, trend_regime=0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["direction"] == 1

    def test_priority_hammer_over_engulfing(self):
        """hammer_detected=1.0 AND engulfing_bull=1.0, trend_regime=0.7, no volume -> hammer wins.

        Priority: hammer/shooting_star (rank 0) beats engulfing (rank 1).
        Expected signal_type == 'candlestick_hammer_long'.
        """
        df, features = base_features(
            hammer_detected=1.0,
            engulfing_bull=1.0,
            trend_regime=0.7,
        )
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["signal_type"] == "candlestick_hammer_long"


# ---------------------------------------------------------------------------
# CNDL-03 — Signal field completeness and correctness
# ---------------------------------------------------------------------------


class TestCandlestickSignalFields:
    """CNDL-03: all required output fields present and mathematically correct."""

    def test_signal_has_all_required_fields(self):
        """Fired signal contains all 9 required output fields."""
        df, features = base_features(engulfing_bull=1.0, trend_regime=0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        required_fields = {
            "signal_type",
            "direction",
            "entry_price",
            "stop_loss",
            "targets",
            "confidence",
            "confluence_score",
            "regime_context",
            "supporting_factors",
        }
        assert required_fields.issubset(result.keys())

    def test_long_stop_below_entry(self):
        """Bullish signal: stop_loss < entry_price (stop placed below entry)."""
        df, features = base_features(engulfing_bull=1.0, trend_regime=0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["stop_loss"] < result["entry_price"]

    def test_short_stop_above_entry(self):
        """Bearish signal: stop_loss > entry_price (stop placed above entry)."""
        df, features = base_features(engulfing_bear=1.0, trend_regime=-0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["stop_loss"] > result["entry_price"]

    def test_confidence_clamped_in_range(self):
        """Any fired signal: confidence in [0.10, 0.90]."""
        df, features = base_features(engulfing_bull=1.0, trend_regime=0.7)
        df = inject_high_volume(df, features)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert 0.10 <= result["confidence"] <= 0.90


# ---------------------------------------------------------------------------
# TestCandlestickNoSignal — edge case: insufficient data
# ---------------------------------------------------------------------------


class TestCandlestickNoSignal:
    """Edge cases: insufficient data returns {}, gated no-signal returns signal_type='none'."""

    def test_insufficient_data_returns_empty(self):
        """DataFrame with only 10 rows (< min_lookback=20) returns no_signal dict."""
        df = make_candlestick_df(n=10)
        _, features = base_features(engulfing_bull=1.0, trend_regime=0.7)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["signal_type"] == "none"
        assert result["direction"] == 0

    def test_gated_no_signal_returns_signal_type_none(self):
        """Regime gate returns {'signal_type': 'none', ...}, not {}."""
        df, features = base_features(engulfing_bull=1.0, trend_regime=0.3)
        plugin = CandlestickPatternSetupPlugin()
        result = plugin.compute_full(
            {
                "main": df,
                "i1": features,
                "i2": features,
                "i3": features,
                "i4": features,
                "i5": features,
                "smc": features,
                "i6": features,
            }
        )
        assert result["signal_type"] == "none"
        assert result["direction"] == 0
        assert "confidence" in result
