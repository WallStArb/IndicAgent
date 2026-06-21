"""Tests for MultiTimeframeAlignment I7 trading setup plugin."""

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv


class TestMultiTimeframeAlignment:
    def test_strong_bullish_alignment(self):
        """CTF score > 0.7 + multiple TFs → long signal."""
        from src.intelligence.archive.trading_i7.mtf_alignment import MTFAlignmentPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.85,
            "ctf_trend_alignment": 0.9,
            "ctf_structure_alignment": 0.8,
            "ctf_regime_agreement": 0.7,
            "ctf_timeframes_aligned": 3.0,
            "ctf_highest_aligned_tf": 60.0,
            "trend_regime": 0.6,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
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

        assert result.get("signal_type") == "mtf_alignment_long"
        assert result.get("direction") == 1
        assert result.get("confidence", 0) >= 0.7

    def test_weak_alignment_no_signal(self):
        """CTF score < threshold → no signal."""
        from src.intelligence.archive.trading_i7.mtf_alignment import MTFAlignmentPlugin

        close = np.full(100, 5050.0)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.3,
            "ctf_timeframes_aligned": 1.0,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
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

        assert result.get("signal_type", "none") == "none"

    def test_minimum_timeframes_required(self):
        """High CTF score but only 1 TF aligned → no signal."""
        from src.intelligence.archive.trading_i7.mtf_alignment import MTFAlignmentPlugin

        close = np.linspace(5000, 5100, 100)
        df = make_ohlcv(close)
        features = {
            "ctf_score": 0.8,
            "ctf_timeframes_aligned": 1.0,
            "atr_14": 10.0,
        }
        plugin = MTFAlignmentPlugin()
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

        assert result.get("signal_type", "none") == "none"
