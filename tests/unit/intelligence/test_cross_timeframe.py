"""Tests for I6 CrossTimeframeConfluence plugin."""

import pytest

from src.intelligence.archive.confluence.cross_timeframe import CrossTimeframeConfluencePlugin


@pytest.fixture
def plugin():
    return CrossTimeframeConfluencePlugin()


def _bullish_intel() -> dict:
    """Intel dict for use both as cross-TF cached intel and as tier dicts."""
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


def _make_frames(current_intel: dict, **intel_tfs: dict) -> dict:
    """Build frames dict distributing current_intel across all tier keys.

    cross_timeframe.py now merges i1+i2+i3+i4+i5+smc into local features.
    Pass the same intel into all tiers so helper functions can find fields
    regardless of their producing tier.
    """
    frames = {
        "main": None,
        "i1": current_intel,
        "i2": current_intel,
        "i3": current_intel,
        "i4": current_intel,
        "i5": current_intel,
        "smc": current_intel,
    }
    frames.update(intel_tfs)
    return frames


class TestCrossTimeframeConfluence:
    def test_all_timeframes_bullish(self, plugin):
        """All cached intel agrees bullish → high positive ctf_score."""
        frames = {
            **_make_frames(_bullish_intel()),
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
            **_make_frames(_bearish_intel()),
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
            **_make_frames({}),
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
        }
        result = plugin.compute_full(frames)
        assert result == {}

    def test_trend_alignment_scoring(self, plugin):
        """Verify trend alignment weight contributes to score direction."""
        # All bullish
        frames_bull = {
            **_make_frames(_bullish_intel()),
            "intel_5m": _bullish_intel(),
        }
        # All bearish
        frames_bear = {
            **_make_frames(_bearish_intel()),
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
            "i3": {"swing_pattern": 1.0, "trend_direction": 1.0},
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
            "i3": {"trend_direction": 1.0},
            "i4": {"momentum_bias": 0.7},
            "intel_5m": {"momentum_bias": 0.5, "trend_direction": 1.0},
            "intel_15m": {"momentum_bias": 0.3, "trend_direction": 1.0},
        }
        result = plugin.compute_full(frames)
        # All positive momentum → agreement should be positive
        assert result["ctf_regime_agreement"] > 0

    def test_single_higher_tf_available(self, plugin):
        """Only 5m cached, no 15m/1h → partial score based on 1 TF."""
        frames = {
            **_make_frames(_bullish_intel()),
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["ctf_score"] > 0
        assert result["ctf_timeframes_aligned"] == 1.0
        assert result["ctf_highest_aligned_tf"] == 5.0  # 5m

    def test_empty_features(self, plugin):
        """Empty features dict with intel → still produces output from other TF data."""
        frames = {
            **_make_frames({}),
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        # Current trend is 0 (unknown) → trend alignment should be 0
        assert result["ctf_trend_alignment"] == 0.0
        assert result["ctf_timeframes_aligned"] == 0.0

    def test_compute_next_delegates(self, plugin):
        """compute_next should delegate to compute_full."""
        frames = {
            **_make_frames({}),
            "intel_5m": _bullish_intel(),
        }
        full = plugin.compute_full(frames)
        incremental = plugin.compute_next(frames)
        assert full == incremental

    def test_output_keys_present(self, plugin):
        """All declared output keys should be present in result."""
        frames = {
            **_make_frames({}),
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        for key in plugin.outputs:
            assert key in result, f"Missing output key: {key}"

    def test_score_clamped_to_range(self, plugin):
        """ctf_score should always be in [-1, +1]."""
        frames = {
            **_make_frames(_bullish_intel()),
            "intel_5m": _bullish_intel(),
            "intel_15m": _bullish_intel(),
            "intel_1h": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert -1.0 <= result["ctf_score"] <= 1.0

    def test_stale_intel_has_less_weight(self, plugin):
        """Fresh 5m bullish intel should outweigh stale 1h bearish intel."""
        frames = {
            **_make_frames(_bullish_intel()),
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
        """i6_smc_bos_alignment and SMC alignment fields appear in output."""
        frames = {
            **_make_frames({}),
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert "i6_smc_bos_alignment" in result
        assert "i6_fvg_tf_alignment" in result
        assert "i6_ob_tf_alignment" in result
        # Values are real scores now (not stubs); FVG/OB fields are absent in _bullish_intel()
        # so alignment defaults to 0.0 when no FVG/OB data is present in other_intel
        assert isinstance(result["i6_fvg_tf_alignment"], float)
        assert isinstance(result["i6_ob_tf_alignment"], float)

    def test_i2_events_boost_bullish_confluence(self, plugin):
        """Bullish I2 events in uptrend should yield positive i2_event_score and boost ctf_score."""
        features = dict(_bullish_intel())
        features["macd_cross_bullish"] = 1.0
        features["rsi_crossed_30_up"] = 1.0
        features["stoch_cross_bullish"] = 1.0
        frames = {
            "main": None,
            "i2": {
                k: v
                for k, v in features.items()
                if k in ("macd_cross_bullish", "rsi_crossed_30_up", "stoch_cross_bullish")
            },
            "i3": {k: v for k, v in features.items() if k in ("trend_direction", "swing_pattern")},
            "i4": {k: v for k, v in features.items() if k in ("momentum_bias", "vol_expansion")},
            "smc": {k: v for k, v in features.items() if k in ("bos_direction",)},
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["i6_i2_event_score"] > 0
        assert result["ctf_score"] > 0

    def test_i2_events_no_effect_when_absent(self, plugin):
        """No I2 events → i2_event_score == 0.0."""
        frames = {
            "main": None,
            # no I2 event keys
            "intel_5m": _bullish_intel(),
        }
        result = plugin.compute_full(frames)
        assert result["i6_i2_event_score"] == 0.0

    def test_fvg_alignment_nonzero_when_fvg_present(self, plugin):
        """FVG on higher TF matching current bar direction → non-zero positive alignment."""
        import pandas as pd

        close_price = 101.0
        main_df = pd.DataFrame(
            {
                "close": [close_price],
                "high": [close_price + 1],
                "low": [close_price - 1],
                "volume": [1000],
            }
        )
        frames = {
            "main": main_df,
            "timeframe": "1m",
            "i1": {"atr_14": 2.0},
            "i3": {"trend_direction": 1.0},
            "intel_5m": {
                "fvg_type": 1.0,
                "fvg_top": 105.0,
                "fvg_bottom": 103.0,
                "trend_direction": 1.0,
            },
        }
        result = plugin.compute_full(frames)
        assert result["i6_fvg_tf_alignment"] != 0.0
        assert result["i6_fvg_tf_alignment"] > 0.0

    def test_fvg_alignment_zero_no_fvg(self, plugin):
        """No FVG on higher TF (fvg_type=0.0) → alignment score is 0.0."""
        frames = {
            "timeframe": "1m",
            "i1": {"atr_14": 2.0},
            "i3": {"trend_direction": 1.0},
            "intel_5m": {
                "fvg_type": 0.0,
                "trend_direction": 1.0,
            },
        }
        result = plugin.compute_full(frames)
        assert result["i6_fvg_tf_alignment"] == 0.0

    def test_ob_alignment_nonzero_when_ob_present(self, plugin):
        """OB on higher TF matching current bar direction → non-zero positive alignment."""
        import pandas as pd

        close_price = 101.0
        main_df = pd.DataFrame(
            {
                "close": [close_price],
                "high": [close_price + 1],
                "low": [close_price - 1],
                "volume": [1000],
            }
        )
        frames = {
            "main": main_df,
            "timeframe": "1m",
            "i1": {"atr_14": 2.0},
            "i3": {"trend_direction": 1.0},
            "intel_5m": {
                "ob_type": 1.0,
                "ob_top": 105.0,
                "ob_bottom": 103.0,
                "trend_direction": 1.0,
            },
        }
        result = plugin.compute_full(frames)
        assert result["i6_ob_tf_alignment"] != 0.0
        assert result["i6_ob_tf_alignment"] > 0.0

    def test_fvg_alignment_direction_mismatch_reduces_score(self, plugin):
        """Bearish FVG on higher TF but bullish current bar → negative or zero score."""
        frames = {
            "timeframe": "1m",
            "i1": {"atr_14": 2.0},
            "i3": {"trend_direction": 1.0},
            "intel_5m": {
                "fvg_type": -1.0,
                "fvg_top": 105.0,
                "fvg_bottom": 103.0,
                "trend_direction": -1.0,
            },
        }
        result = plugin.compute_full(frames)
        assert result["i6_fvg_tf_alignment"] <= 0.0
