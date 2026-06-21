"""Unit tests for CrossTFMomentumDivergence plugin.

Tests cover:
- Plugin instantiation and output field declaration
- All 5 regime classifications (D-06: 5 categorical labels)
- Gradient output range via np.tanh() (not binary step)
- Missing data fallback to mixed/0.0
- Divergence direction (positive = pullback, negative = bounce)
"""

import pytest

from src.intelligence.archive.confluence.cross_tf_momentum_divergence import (
    CrossTFMomentumDivergencePlugin,
    plugin,
)


class TestCrossTFMomentumDivergencePlugin:
    """Test cross-TF momentum divergence plugin implementation."""

    @pytest.fixture
    def p(self) -> CrossTFMomentumDivergencePlugin:
        return CrossTFMomentumDivergencePlugin()

    def _frames(
        self,
        ltf_rsi: float,
        htf_rsi: float,
        ltf_macd: float,
        htf_macd: float,
    ) -> dict:
        """Build a frames dict with controlled I1 values per TF.

        Injects intel_{tf} flat dicts matching the actual pipeline frame format.
        Uses rsi_14 (I1) and macd_histogram_12_26_9 (I1) for momentum bias.
        """
        return {
            "intel_5m": {"rsi_14": ltf_rsi, "macd_histogram_12_26_9": ltf_macd},
            "intel_15m": {"rsi_14": ltf_rsi - 2, "macd_histogram_12_26_9": ltf_macd * 0.9},
            "intel_1h": {"rsi_14": htf_rsi, "macd_histogram_12_26_9": htf_macd},
            "intel_4h": {"rsi_14": htf_rsi + 2, "macd_histogram_12_26_9": htf_macd * 0.9},
        }

    def test_plugin_module_instance_exists(self) -> None:
        """Module-level plugin instance is created."""
        assert isinstance(plugin, CrossTFMomentumDivergencePlugin)

    def test_plugin_name(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Plugin name matches expected convention."""
        assert p.name == "i6_CrossTFMomentumDivergence"

    def test_plugin_outputs_declared(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Plugin declares both output fields."""
        assert "ctf_momentum_divergence" in p.outputs
        assert "ctf_momentum_regime" in p.outputs

    def test_aligned_htf_bull_regime(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Both HTF and LTF strongly bullish -> aligned_htf_bull regime."""
        frames = self._frames(ltf_rsi=68.0, htf_rsi=70.0, ltf_macd=0.8, htf_macd=1.0)
        result = p.compute_full(frames)

        assert result["ctf_momentum_regime"] == "aligned_htf_bull"
        # Divergence near 0 when aligned (HTF_bias - LTF_bias both positive)
        assert -0.6 <= result["ctf_momentum_divergence"] <= 0.6

    def test_aligned_htf_bear_regime(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Both HTF and LTF strongly bearish -> aligned_htf_bear regime."""
        frames = self._frames(ltf_rsi=32.0, htf_rsi=30.0, ltf_macd=-0.8, htf_macd=-1.0)
        result = p.compute_full(frames)

        assert result["ctf_momentum_regime"] == "aligned_htf_bear"

    def test_pullback_regime(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """HTF bullish, LTF bearish -> pullback regime with positive divergence."""
        frames = self._frames(ltf_rsi=35.0, htf_rsi=68.0, ltf_macd=-0.8, htf_macd=0.8)
        result = p.compute_full(frames)

        assert result["ctf_momentum_regime"] == "pullback"
        # Positive divergence: HTF_bias > 0, LTF_bias < 0
        assert (
            result["ctf_momentum_divergence"] > 0.0
        ), f"Expected positive divergence for pullback, got {result['ctf_momentum_divergence']}"

    def test_bounce_regime(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """HTF bearish, LTF bullish -> bounce regime with negative divergence."""
        frames = self._frames(ltf_rsi=65.0, htf_rsi=32.0, ltf_macd=0.8, htf_macd=-0.8)
        result = p.compute_full(frames)

        assert result["ctf_momentum_regime"] == "bounce"
        # Negative divergence: HTF_bias < 0, LTF_bias > 0
        assert (
            result["ctf_momentum_divergence"] < 0.0
        ), f"Expected negative divergence for bounce, got {result['ctf_momentum_divergence']}"

    def test_mixed_regime(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Weak directional bias on both HTF and LTF -> mixed regime."""
        frames = self._frames(ltf_rsi=49.0, htf_rsi=51.0, ltf_macd=0.01, htf_macd=-0.01)
        result = p.compute_full(frames)

        assert result["ctf_momentum_regime"] == "mixed"

    def test_missing_data_returns_zero_mixed(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Empty frames -> 0.0 divergence and mixed regime."""
        result = p.compute_full({})

        assert result["ctf_momentum_divergence"] == 0.0
        assert result["ctf_momentum_regime"] == "mixed"

    def test_missing_frames_key(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Completely missing intel keys -> graceful fallback."""
        result = p.compute_full({"other_key": {"5m": {}}})

        assert result["ctf_momentum_divergence"] == 0.0
        assert result["ctf_momentum_regime"] == "mixed"

    def test_missing_htf_data(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Only LTF data present (no HTF intel_1h/intel_4h) -> insufficient -> mixed."""
        frames = {
            "intel_5m": {"rsi_14": 65.0, "macd_histogram_12_26_9": 0.5},
            "intel_15m": {"rsi_14": 63.0, "macd_histogram_12_26_9": 0.4},
        }
        result = p.compute_full(frames)

        assert result["ctf_momentum_divergence"] == 0.0
        assert result["ctf_momentum_regime"] == "mixed"

    def test_gradient_not_binary(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """Output is continuous gradient via np.tanh(), not a binary step function.

        Per D-06/D-17: ctf_momentum_divergence must be a continuous gradient [-1, +1]
        not a binary step (-1, 0, +1).
        """
        frames = self._frames(ltf_rsi=38.0, htf_rsi=63.0, ltf_macd=-0.4, htf_macd=0.4)
        result = p.compute_full(frames)

        val = result["ctf_momentum_divergence"]
        # Must be in valid range
        assert -1.0 <= val <= 1.0
        # Must NOT be exactly -1, 0, or 1 (binary step pattern)
        assert val not in (
            -1.0,
            0.0,
            1.0,
        ), f"Expected fractional gradient value, got exact binary value {val}"

    def test_output_range_bounded(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """ctf_momentum_divergence is always in [-1.0, +1.0] due to np.tanh()."""
        test_cases = [
            # Strong pullback: LTF bearish, HTF bullish
            self._frames(20.0, 80.0, -2.0, 2.0),
            # Strong bounce: LTF bullish, HTF bearish
            self._frames(80.0, 20.0, 2.0, -2.0),
            # Strong bull alignment
            self._frames(80.0, 80.0, 2.0, 2.0),
            # Strong bear alignment
            self._frames(20.0, 20.0, -2.0, -2.0),
        ]

        for frames in test_cases:
            result = p.compute_full(frames)
            val = result["ctf_momentum_divergence"]
            assert -1.0 <= val <= 1.0, f"Out of range: {val}"

    def test_compute_next_delegates_to_compute_full(
        self, p: CrossTFMomentumDivergencePlugin
    ) -> None:
        """compute_next() delegates to compute_full() (incremental = same output)."""
        frames = self._frames(ltf_rsi=35.0, htf_rsi=68.0, ltf_macd=-0.8, htf_macd=0.8)
        full_result = p.compute_full(frames)
        next_result = p.compute_next(frames)

        assert full_result == next_result

    def test_all_five_regimes_reachable(self, p: CrossTFMomentumDivergencePlugin) -> None:
        """All 5 D-06 categorical regimes are reachable.

        Tests the full regime coverage requirement from D-06:
        aligned_htf_bull, aligned_htf_bear, pullback, bounce, mixed
        """
        # aligned_htf_bull: both HTF+LTF strongly bullish
        r = p.compute_full(self._frames(70.0, 72.0, 1.0, 1.2))
        assert r["ctf_momentum_regime"] == "aligned_htf_bull"

        # aligned_htf_bear: both HTF+LTF strongly bearish
        r = p.compute_full(self._frames(30.0, 28.0, -1.0, -1.2))
        assert r["ctf_momentum_regime"] == "aligned_htf_bear"

        # pullback: HTF bullish, LTF bearish
        r = p.compute_full(self._frames(32.0, 68.0, -0.9, 0.9))
        assert r["ctf_momentum_regime"] == "pullback"

        # bounce: HTF bearish, LTF bullish
        r = p.compute_full(self._frames(68.0, 32.0, 0.9, -0.9))
        assert r["ctf_momentum_regime"] == "bounce"

        # mixed: weak bias on both sides
        r = p.compute_full(self._frames(50.5, 49.5, 0.005, -0.005))
        assert r["ctf_momentum_regime"] == "mixed"
