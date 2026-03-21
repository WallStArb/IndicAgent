"""Failing test suite for GapAnalysisSetup — RED phase before Plan 02.

All tests fail with ImportError because the plugin does not exist yet.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.trading.gap_analysis_setup import GapAnalysisSetupPlugin
from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Module-level helper
# ---------------------------------------------------------------------------


def make_gap_df(
    gap_atr_mult: float,
    atr: float = 10.0,
    n: int = 100,
    bullish: bool = True,
    high_volume: bool = False,
) -> tuple:
    """Build OHLCV + features dict with a controlled gap injected into the last bar.

    Gap = (1 if bullish else -1) * gap_atr_mult * atr inserted at open[-1].
    High-volume mode sets vol[-1] = mean(vol[:-1]) * 2.5 to reliably exceed 1.5x threshold.
    """
    close = np.linspace(5000, 5200, n)
    vol = np.full(n, 1000.0)
    if high_volume:
        vol[-1] = float(np.mean(vol[:-1])) * 2.5
    df = make_ohlcv(close, volume=vol)
    direction = 1 if bullish else -1
    df.at[df.index[-1], "open"] = float(df["close"].iloc[-2]) + direction * gap_atr_mult * atr
    features = {"atr_14": atr}
    return df, features


# ---------------------------------------------------------------------------
# GAP-01 Detection
# ---------------------------------------------------------------------------


class TestGapDetection:
    """GAP-01: gap detection — direction from open vs prior close."""

    def test_bullish_gap_detected(self):
        """open > prior close by 0.5*ATR produces direction == 1."""
        df, features = make_gap_df(gap_atr_mult=0.5, bullish=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["direction"] == 1

    def test_bearish_gap_detected(self):
        """open < prior close by 0.5*ATR produces direction == -1."""
        df, features = make_gap_df(gap_atr_mult=0.5, bullish=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["direction"] == -1

    def test_no_gap_no_signal(self):
        """open == prior close exactly produces signal_type == 'none', direction == 0."""
        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        # Inject zero gap: open[-1] == close[-2]
        df.at[df.index[-1], "open"] = float(df["close"].iloc[-2])
        features = {"atr_14": 10.0}
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["signal_type"] == "none"
        assert result["direction"] == 0

    def test_sub_threshold_gap_no_signal(self):
        """gap < 0.3*ATR threshold produces signal_type == 'none'."""
        df, features = make_gap_df(gap_atr_mult=0.2)  # 0.2 < 0.3 min threshold
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["signal_type"] == "none"


# ---------------------------------------------------------------------------
# GAP-02 Classification
# ---------------------------------------------------------------------------


class TestGapClassification:
    """GAP-02: bias (continuation vs fade) from gap size + volume."""

    def test_large_gap_high_volume_continuation(self):
        """gap_size_atr=1.2, vol_ratio=2.5 → bias == 'continuation'."""
        df, features = make_gap_df(gap_atr_mult=1.2, high_volume=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["bias"] == "continuation"

    def test_medium_gap_normal_volume_fade(self):
        """gap_size_atr=0.5, normal volume → bias == 'fade'."""
        df, features = make_gap_df(gap_atr_mult=0.5, high_volume=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["bias"] == "fade"

    def test_bullish_fade_signal_type(self):
        """bullish fade gap → signal_type == 'gap_fade_long'."""
        df, features = make_gap_df(gap_atr_mult=0.5, bullish=True, high_volume=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["signal_type"] == "gap_fade_long"

    def test_bearish_fade_signal_type(self):
        """bearish fade gap → signal_type == 'gap_fade_short'."""
        df, features = make_gap_df(gap_atr_mult=0.5, bullish=False, high_volume=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["signal_type"] == "gap_fade_short"

    def test_bullish_continuation_signal_type(self):
        """large bullish gap + high volume → signal_type == 'gap_cont_long'."""
        df, features = make_gap_df(gap_atr_mult=1.2, bullish=True, high_volume=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["signal_type"] == "gap_cont_long"


# ---------------------------------------------------------------------------
# GAP-03 Signal Fields
# ---------------------------------------------------------------------------


class TestGapSignalFields:
    """GAP-03: signal field completeness and correctness."""

    def test_fade_entry_at_limit(self):
        """Fade signal: entry_type == 'at_limit', entry_price == current session open."""
        df, features = make_gap_df(gap_atr_mult=0.5)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["entry_type"] == "at_limit"
        assert result["entry_price"] == pytest.approx(float(df["open"].iloc[-1]))

    def test_continuation_entry_at_pullback(self):
        """Continuation signal: entry_type == 'at_pullback'."""
        df, features = make_gap_df(gap_atr_mult=1.2, high_volume=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["entry_type"] == "at_pullback"

    def test_all_fields_present_on_fired_signal(self):
        """Fired signal has confidence > 0.0, targets non-empty, stop_loss != entry_price."""
        df, features = make_gap_df(gap_atr_mult=0.5)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["confidence"] > 0.0
        assert len(result["targets"]) >= 1
        assert result["stop_loss"] != result["entry_price"]

    def test_fade_stop_below_entry_for_long(self):
        """Fade long signal: stop_loss < entry_price (stop is below the entry open)."""
        df, features = make_gap_df(gap_atr_mult=0.5, bullish=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["stop_loss"] < result["entry_price"]


# ---------------------------------------------------------------------------
# No-signal edge cases
# ---------------------------------------------------------------------------


class TestGapNoSignal:
    """Edge cases that must return empty dict."""

    def test_insufficient_data_returns_empty(self):
        """DataFrame with only 30 rows (< min_lookback=50) returns no_signal dict."""
        close = np.linspace(5000, 5100, 30)
        df = make_ohlcv(close)
        features = {"atr_14": 10.0}
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full({"main": df, "features": features})
        assert result["signal_type"] == "none"
        assert result["direction"] == 0
