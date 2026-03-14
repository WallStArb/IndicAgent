"""Tests for I6 CrossTimeframeConfluence plugin."""

import pytest

from src.intelligence.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@pytest.fixture
def plugin():
    return CrossTimeframeConfluencePlugin()


def _bullish_intel() -> dict:
    return {
        "trend_direction": 1.0,
        "swing_pattern": 1.0,
        "momentum_bias": 0.6,
        "vol_expansion": 1.0,
        "bos_direction": 1.0,
    }


def _bearish_intel() -> dict:
    return {
        "trend_direction": -1.0,
        "swing_pattern": -1.0,
        "momentum_bias": -0.5,
        "vol_expansion": 0.0,
        "bos_direction": -1.0,
    }


def _neutral_intel() -> dict:
    return {
        "trend_direction": 0.0,
        "swing_pattern": 0.0,
        "momentum_bias": 0.0,
        "vol_expansion": 0.0,
    }


class TestCrossTimeframeConfluence:
    def test_all_timeframes_bullish(self, plugin):
        """All cached intel agrees bullish → high positive ctf_score."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),
            "intel_15m": _bullish_intel(),
            "intel_1h": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["ctf_score"] > 0.5
        assert result["ctf_trend_alignment"] > 0
        assert result["ctf_timeframes_aligned"] == 3.0
        assert result["ctf_highest_aligned_tf"] == 60.0  # 1h

    def test_all_timeframes_bearish(self, plugin):
        """All cached intel agrees bearish → negative ctf_score."""
        frames = {
            "main": None,
            "features": _bearish_intel(),
            "intel_5m": _bearish_intel(),
            "intel_15m": _bearish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["ctf_score"] < -0.5
        assert result["ctf_trend_alignment"] < 0
        assert result["ctf_timeframes_aligned"] == 2.0

    def test_mixed_timeframes(self, plugin):
        """1m bullish but 5m bearish → low/mixed ctf_score."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bearish_intel(),
            "intel_15m": _bearish_intel(),
        }
        result = plugin.compute_full(frames)
        # Most other TFs disagree → score should be low magnitude
        assert result["ctf_score"] < 0.3
        assert result["ctf_timeframes_aligned"] == 0.0

    def test_no_cached_intel(self, plugin):
        """No other TF data available → empty dict."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result == {}

    def test_trend_alignment_scoring(self, plugin):
        """Verify trend alignment weight contributes to score direction."""
        # All bullish
        frames_bull = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),
        }
        # All bearish
        frames_bear = {
            "main": None,
            "features": _bearish_intel(),
            "intel_5m": _bearish_intel(),
        }
        r_bull = plugin.compute_full(frames_bull)
        r_bear = plugin.compute_full(frames_bear)
        assert r_bull["ctf_trend_alignment"] > 0
        assert r_bear["ctf_trend_alignment"] < 0

    def test_structure_alignment_with_sr(self, plugin):
        """Matching swing patterns boost structure alignment."""
        frames = {
            "main": None,
            "features": {"swing_pattern": 1.0, "trend_direction": 1.0},
            "intel_5m": {"swing_pattern": 1.0, "trend_direction": 1.0},
            "intel_15m": {"swing_pattern": -1.0, "trend_direction": -1.0},
        }
        result = plugin.compute_full(frames)
        # One agrees, one disagrees on structure → partial
        assert 0 < result["ctf_structure_alignment"] < 1.0

    def test_regime_agreement(self, plugin):
        """Matching momentum regimes boost regime score."""
        frames = {
            "main": None,
            "features": {"momentum_bias": 0.7, "trend_direction": 1.0},
            "intel_5m": {"momentum_bias": 0.5, "trend_direction": 1.0},
            "intel_15m": {"momentum_bias": 0.3, "trend_direction": 1.0},
        }
        result = plugin.compute_full(frames)
        # All positive momentum → agreement should be positive
        assert result["ctf_regime_agreement"] > 0

    def test_single_higher_tf_available(self, plugin):
        """Only 5m cached, no 15m/1h → partial score based on 1 TF."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["ctf_score"] > 0
        assert result["ctf_timeframes_aligned"] == 1.0
        assert result["ctf_highest_aligned_tf"] == 5.0  # 5m

    def test_empty_features(self, plugin):
        """Empty features dict with intel → still produces output from other TF data."""
        frames = {
            "main": None,
            "features": {},
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        # Current trend is 0 (unknown) → trend alignment should be 0
        assert result["ctf_trend_alignment"] == 0.0
        assert result["ctf_timeframes_aligned"] == 0.0

    def test_compute_next_delegates(self, plugin):
        """compute_next should delegate to compute_full."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),
        }
        full = plugin.compute_full(frames)
        incremental = plugin.compute_next(frames)
        assert full == incremental

    def test_output_keys_present(self, plugin):
        """All declared output keys should be present in result."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        for key in plugin.outputs:
            assert key in result, f"Missing output key: {key}"

    def test_score_clamped_to_range(self, plugin):
        """ctf_score should always be in [-1, +1]."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),
            "intel_15m": _bullish_intel(),
            "intel_1h": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert -1.0 <= result["ctf_score"] <= 1.0

    def test_stale_intel_has_less_weight(self, plugin):
        """Fresh 5m bullish intel should outweigh stale 1h bearish intel."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),  # fresh: bars_since=0 → weight=1.0
            "intel_1h": _bearish_intel(),  # stale: bars_since=10 → weight≈0.09
            "intel_5m_bars_since": 0,
            "intel_1h_bars_since": 10,
        }
        result = plugin.compute_full(frames)
        # Fresh bullish 5m dominates stale bearish 1h → positive score
        assert result["ctf_score"] > 0
        assert result["ctf_trend_alignment"] > 0

    def test_smc_bos_alignment_present_in_output(self, plugin):
        """i6_smc_bos_alignment and placeholder SMC fields appear in output."""
        frames = {
            "main": None,
            "features": _bullish_intel(),
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert "i6_smc_bos_alignment" in result
        assert "i6_fvg_tf_alignment" in result
        assert "i6_ob_tf_alignment" in result
        assert result["i6_fvg_tf_alignment"] == 0.0
        assert result["i6_ob_tf_alignment"] == 0.0

    def test_i2_events_boost_bullish_confluence(self, plugin):
        """Bullish I2 events in uptrend should yield positive i2_event_score and boost ctf_score."""
        features = dict(_bullish_intel())
        features["macd_cross_bullish"] = 1.0
        features["rsi_crossed_30_up"] = 1.0
        features["stoch_cross_bullish"] = 1.0
        frames = {
            "main": None,
            "features": features,
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["i6_i2_event_score"] > 0
        assert result["ctf_score"] > 0

    def test_i2_events_no_effect_when_absent(self, plugin):
        """No I2 events → i2_event_score == 0.0."""
        frames = {
            "main": None,
            "features": _bullish_intel(),  # no I2 event keys
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["i6_i2_event_score"] == 0.0
