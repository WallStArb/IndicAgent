"""Unit tests for GapAnalysisSetup plugin.

Tests cover GAP-01 detection, GAP-02 classification, GAP-03 signal fields,
and the 0.8x ATR magnitude gate introduced in Phase 118-03.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.intelligence.archive.trading_i7.gap_analysis_setup import GapAnalysisSetupPlugin
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
    bars_since: float | None = None,
) -> tuple:
    """Build OHLCV + features dict with a controlled gap injected into the last bar.

    Gap = (1 if bullish else -1) * gap_atr_mult * atr inserted at open[-1].
    High-volume mode sets vol[-1] = mean(vol[:-1]) * 2.5 to reliably exceed 1.5x threshold.
    bars_since: optional bars_since_session_start injected into features dict.
    """
    close = np.linspace(5000, 5200, n)
    vol = np.full(n, 1000.0)
    if high_volume:
        vol[-1] = float(np.mean(vol[:-1])) * 2.5
    df = make_ohlcv(close, volume=vol)
    direction = 1 if bullish else -1
    df.at[df.index[-1], "open"] = float(df["close"].iloc[-2]) + direction * gap_atr_mult * atr
    features: dict = {"atr_14": atr}
    if bars_since is not None:
        features["bars_since_session_start"] = bars_since
    return df, features


def _make_frames(df, features):
    """Build a frames dict for compute_full with a given df and features."""
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
    }


# ---------------------------------------------------------------------------
# GAP-01 Detection
# ---------------------------------------------------------------------------


class TestGapDetection:
    """GAP-01: gap detection — direction from open vs prior close."""

    def test_bullish_gap_detected(self):
        """open > prior close by 0.9*ATR (above 0.8x gate): fade trade is SHORT (direction == -1)."""
        df, features = make_gap_df(gap_atr_mult=0.9, bullish=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["direction"] == -1  # upward gap fade = short trade

    def test_bearish_gap_detected(self):
        """open < prior close by 0.9*ATR (above 0.8x gate): fade trade is LONG (direction == 1)."""
        df, features = make_gap_df(gap_atr_mult=0.9, bullish=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["direction"] == 1  # downward gap fade = long trade

    def test_no_gap_no_signal(self):
        """open == prior close exactly produces signal_type == 'none', direction == 0."""
        close = np.linspace(5000, 5200, 100)
        df = make_ohlcv(close)
        # Inject zero gap: open[-1] == close[-2]
        df.at[df.index[-1], "open"] = float(df["close"].iloc[-2])
        features = {"atr_14": 10.0}
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] == "none"
        assert result["direction"] == 0

    def test_sub_threshold_gap_no_signal(self):
        """gap < 0.8*ATR threshold produces signal_type == 'none'."""
        df, features = make_gap_df(gap_atr_mult=0.5)  # 0.5 < 0.8 min threshold
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] == "none"


# ---------------------------------------------------------------------------
# GAP-02 Classification
# ---------------------------------------------------------------------------


class TestGapClassification:
    """GAP-02: bias (continuation vs fade) from gap size + volume."""

    def test_large_gap_high_volume_continuation(self):
        """gap_size_atr=1.2, vol_ratio=2.5 -> bias == 'continuation'."""
        df, features = make_gap_df(gap_atr_mult=1.2, high_volume=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["bias"] == "continuation"

    def test_medium_gap_normal_volume_fade(self):
        """gap_size_atr=0.9 (above gate), normal volume -> bias == 'fade'."""
        df, features = make_gap_df(gap_atr_mult=0.9, high_volume=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["bias"] == "fade"

    def test_bullish_fade_signal_type(self):
        """bullish (upward) gap fade -> trade is SHORT -> signal_type == 'gap_fade_short'."""
        df, features = make_gap_df(gap_atr_mult=0.9, bullish=True, high_volume=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] == "gap_fade_short"

    def test_bearish_fade_signal_type(self):
        """bearish (downward) gap fade -> trade is LONG -> signal_type == 'gap_fade_long'."""
        df, features = make_gap_df(gap_atr_mult=0.9, bullish=False, high_volume=False)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] == "gap_fade_long"

    def test_bullish_continuation_signal_type(self):
        """large bullish gap + high volume -> signal_type == 'gap_cont_long'."""
        df, features = make_gap_df(gap_atr_mult=1.2, bullish=True, high_volume=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] == "gap_cont_long"


# ---------------------------------------------------------------------------
# GAP-03 Signal Fields
# ---------------------------------------------------------------------------


class TestGapSignalFields:
    """GAP-03: signal field completeness and correctness."""

    def test_fade_entry_fields(self):
        """Fade signal: entry_price == current session open (frame_trade resolves gap to at_close)."""
        df, features = make_gap_df(gap_atr_mult=0.9)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        # frame_trade resolves gap signals to at_close — entry_price equals the open passed in
        assert result["entry_type"] == "at_close"
        assert result["entry_price"] == pytest.approx(float(df["open"].iloc[-1]))

    def test_continuation_entry_fields(self):
        """Continuation signal: entry_type resolved by frame_trade (at_close for gap signals)."""
        df, features = make_gap_df(gap_atr_mult=1.2, high_volume=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        # frame_trade resolves gap_cont_* to at_close (no special entry case in _resolve_entry)
        assert result["entry_type"] == "at_close"

    def test_all_fields_present_on_fired_signal(self):
        """Fired signal has confidence > 0.0, targets non-empty, stop_loss != entry_price."""
        df, features = make_gap_df(gap_atr_mult=0.9)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["confidence"] > 0.0
        assert len(result["targets"]) >= 1
        assert result["stop_loss"] != result["entry_price"]

    def test_fade_stop_above_entry_for_short(self):
        """Fade short signal (upward gap): stop_loss > entry_price (stop is above the entry open)."""
        df, features = make_gap_df(gap_atr_mult=0.9, bullish=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["stop_loss"] > result["entry_price"]  # short trade: stop above entry


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
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] == "none"
        assert result["direction"] == 0


# ---------------------------------------------------------------------------
# Phase 118-03: 0.8x ATR gate and 4-factor confidence formula
# ---------------------------------------------------------------------------


class TestGapMagnitudeGate:
    """118-03: minimum gap magnitude gate raised from 0.3x to 0.8x ATR."""

    def test_rejects_gap_below_0_8_atr(self):
        """gap_size_atr = 0.5 is rejected by the 0.8x gate (previously fired at 0.3x)."""
        df, features = make_gap_df(gap_atr_mult=0.5)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] == "none"

    def test_accepts_gap_at_0_8_atr(self):
        """gap_size_atr == 0.8 is at the boundary — signal should fire."""
        df, features = make_gap_df(gap_atr_mult=0.8, bullish=True)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        # 0.8 == threshold (gate is strict <), so exactly 0.8 fires
        assert result["signal_type"] != "none"

    def test_geo_score_scales_with_gap_size(self):
        """Larger gap -> higher geo_score -> higher confidence."""
        df_small, feat_small = make_gap_df(gap_atr_mult=0.8, bullish=True)
        df_large, feat_large = make_gap_df(gap_atr_mult=2.5, bullish=True)
        plugin = GapAnalysisSetupPlugin()
        result_small = plugin.compute_full(_make_frames(df_small, feat_small))
        result_large = plugin.compute_full(_make_frames(df_large, feat_large))
        assert result_small["signal_type"] != "none"
        assert result_large["signal_type"] != "none"
        assert result_large["confidence"] > result_small["confidence"]


class TestGapConfidenceFactors:
    """118-03: 4-factor intrinsic confidence formula verification."""

    def test_timing_score_better_at_session_open(self):
        """bars_since_session_start = 0 (open) -> higher timing_score -> higher confidence."""
        # Same gap size and volume, only bars_since differs
        df_early, feat_early = make_gap_df(gap_atr_mult=1.5, bullish=True, bars_since=0)
        df_late, feat_late = make_gap_df(gap_atr_mult=1.5, bullish=True, bars_since=30)
        plugin = GapAnalysisSetupPlugin()
        result_early = plugin.compute_full(_make_frames(df_early, feat_early))
        result_late = plugin.compute_full(_make_frames(df_late, feat_late))
        assert result_early["signal_type"] != "none"
        assert result_late["signal_type"] != "none"
        assert result_early["confidence"] > result_late["confidence"]

    def test_late_session_gap_still_fires(self):
        """bars_since_session_start = 45 (beyond 30-bar floor), strong geometry and volume.

        Proves timing_score floors at 0.2 — a valid late-session gap is down-weighted but
        never rejected (Codex MEDIUM concern).
        """
        df, features = make_gap_df(gap_atr_mult=2.0, high_volume=True, bullish=True, bars_since=45)
        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))
        assert result["signal_type"] != "none"
        assert result["confidence"] > 0.0

    def test_continuation_gap_higher_than_fade(self):
        """Same geometry/volume/timing; continuation bias -> higher confidence than fade."""
        # continuation: large gap + high volume
        df_cont, feat_cont = make_gap_df(
            gap_atr_mult=1.5, high_volume=True, bullish=True, bars_since=5
        )
        # fade: same gap size but no high volume
        df_fade, feat_fade = make_gap_df(
            gap_atr_mult=1.5, high_volume=False, bullish=True, bars_since=5
        )
        plugin = GapAnalysisSetupPlugin()
        result_cont = plugin.compute_full(_make_frames(df_cont, feat_cont))
        result_fade = plugin.compute_full(_make_frames(df_fade, feat_fade))
        assert result_cont["bias"] == "continuation"
        assert result_fade["bias"] == "fade"
        assert result_cont["confidence"] > result_fade["confidence"]

    def test_high_volume_boosts_confidence(self):
        """gap_size_atr=1.0, bars_since=5, continuation. Compare 1x vs 3x volume."""
        # 1x volume (normal) — same geometry/timing
        df_low, feat_low = make_gap_df(
            gap_atr_mult=1.0, high_volume=False, bullish=True, bars_since=5
        )
        # 3x volume (high) — triggers continuation + higher vol_score
        df_high, feat_high = make_gap_df(
            gap_atr_mult=1.0, high_volume=True, bullish=True, bars_since=5
        )
        plugin = GapAnalysisSetupPlugin()
        result_low = plugin.compute_full(_make_frames(df_low, feat_low))
        result_high = plugin.compute_full(_make_frames(df_high, feat_high))
        assert result_low["signal_type"] != "none"
        assert result_high["signal_type"] != "none"
        assert result_high["confidence"] > result_low["confidence"]

    def test_missing_session_start_uses_neutral(self):
        """No bars_since_session_start in features: timing_score = 0.5 (neutral, not penalized).

        Proves the is-None guard fires correctly: signal is returned and confidence is
        not at the near-minimum floor (timing_score=0.5 is neutral, not penalized).
        """
        # Build without bars_since — None path
        df, features = make_gap_df(gap_atr_mult=1.5, high_volume=True, bullish=True)
        # Confirm no bars_since_session_start in features
        assert "bars_since_session_start" not in features

        plugin = GapAnalysisSetupPlugin()
        result = plugin.compute_full(_make_frames(df, features))

        # No NoneType crash and a valid signal is returned
        assert result["signal_type"] != "none"
        assert 0.0 < result["confidence"] <= 0.95

        # Compare to bars_since=0 (best timing): neutral should be below best but not at floor
        df_open, feat_open = make_gap_df(
            gap_atr_mult=1.5, high_volume=True, bullish=True, bars_since=0
        )
        result_open = plugin.compute_full(_make_frames(df_open, feat_open))
        # Neutral timing (0.5) < peak timing (1.0) so neutral confidence <= open confidence
        # but neutral confidence must be clearly above floor (not at near-zero)
        assert result["confidence"] > 0.2  # not penalized to the floor
