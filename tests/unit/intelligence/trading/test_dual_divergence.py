"""Unit tests for trad_DualDivergence I7 shadow plugin."""

from __future__ import annotations

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv

# Gate-passing defaults for the dual gate
_GATE_FEATURES = {
    "hmm_prob_ranging": 0.65,
    "hmm_prob_trending_up": 0.20,
    "hmm_prob_trending_down": 0.15,
    "ctf_score": 0.40,
    "atr_14": 2.0,
}


def _make_frames(close_arr, features=None, symbol="ES", tf="1m"):
    df = make_ohlcv(np.array(close_arr, dtype=float))
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features or {},
        "__symbol__": symbol,
        "__timeframe__": tf,
    }


class TestDualDivergence:
    def _make_plugin(self):
        from src.intelligence.trading.dual_divergence import DualDivergencePlugin

        return DualDivergencePlugin()

    def test_fires_when_both_diverge(self):
        """ofi_divergence >= 1.5 AND cvd_divergence nonzero AND both persist N bars → fires."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        # Both OFI and CVD diverging (bullish pressure vs price neutral/falling)
        features = {
            **_GATE_FEATURES,
            "ofi_divergence": 1.8,
            "cvd_divergence": 1.2,
            "cvd_slope_5bar": 200.0,
        }
        # Build up N=3 confirmation bars
        for _ in range(2):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}: {result}"
        assert result.get("confidence", 0) > 0
        assert isinstance(
            result.get("stop_loss"), float
        ), f"stop_loss must be float, got {type(result.get('stop_loss'))}"
        assert (
            isinstance(result.get("targets"), list) and len(result["targets"]) > 0
        ), "targets must be non-empty list"
        assert all(isinstance(t, float) for t in result["targets"]), "all targets must be float"
        assert isinstance(
            result.get("regime_context"), str
        ), f"regime_context must be str, got {type(result.get('regime_context'))}"

    def test_fires_when_both_diverge_bearish(self):
        """Both OFI and CVD bearish divergence → fires short."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            **_GATE_FEATURES,
            "ofi_divergence": -1.8,
            "cvd_divergence": -1.2,
            "cvd_slope_5bar": -200.0,
        }
        for _ in range(2):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        assert (
            result.get("direction") == -1
        ), f"Expected -1, got {result.get('direction')}: {result}"

    def test_no_signal_only_ofi_diverges(self):
        """ofi_divergence high but cvd_divergence near 0 → no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            **_GATE_FEATURES,
            "ofi_divergence": 1.8,
            "cvd_divergence": 0.3,  # below 1.0 threshold
            "cvd_slope_5bar": 50.0,
        }
        for _ in range(3):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        assert result.get("direction") == 0, f"Expected 0, got {result.get('direction')}: {result}"

    def test_no_signal_only_cvd_diverges(self):
        """cvd_divergence high but ofi_divergence near 0 → no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            **_GATE_FEATURES,
            "ofi_divergence": 0.3,  # below 1.0 threshold
            "cvd_divergence": 1.5,
            "cvd_slope_5bar": 200.0,
        }
        for _ in range(3):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        assert result.get("direction") == 0, f"Expected 0, got {result.get('direction')}: {result}"

    def test_no_signal_insufficient_confirmation(self):
        """Only 1 bar of dual divergence → insufficient confirmation."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            **_GATE_FEATURES,
            "ofi_divergence": 1.8,
            "cvd_divergence": 1.2,
            "cvd_slope_5bar": 200.0,
        }
        result = plugin.compute_full(_make_frames(close, features))
        assert result.get("direction") == 0

    def test_no_signal_when_ranging_regime_below_threshold(self):
        """hmm_prob_ranging below 0.30 → HMM gate blocks (ranging gate for mean_reversion)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            "hmm_prob_ranging": 0.10,  # below 0.30
            "hmm_prob_trending_up": 0.50,
            "hmm_prob_trending_down": 0.40,
            "ctf_score": 0.40,
            "atr_14": 2.0,
            "ofi_divergence": 1.8,
            "cvd_divergence": 1.2,
            "cvd_slope_5bar": 200.0,
        }
        for _ in range(3):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        assert result.get("direction") == 0

    def test_ctf_below_old_threshold_still_fires(self):
        """Phase 123 ECL: abs(ctf_score) < 0.25 must NOT block — ctf_score is annotation."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            "hmm_prob_ranging": 0.65,
            "hmm_prob_trending_up": 0.20,
            "hmm_prob_trending_down": 0.15,
            "ctf_score": 0.10,  # below old 0.25 gate — no longer blocks
            "atr_14": 2.0,
            "ofi_divergence": 1.8,
            "cvd_divergence": 1.2,
            "cvd_slope_5bar": 200.0,
        }
        for _ in range(3):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        # Phase 126-06: signal fires; ctf_score initialized to None (pipeline annotates)
        assert (
            result.get("direction") != 0
        ), "Phase 126-06: ctf_score=0.10 must not block DualDivergence emission"
        assert (
            result.get("ctf_score") is None
        ), "ctf_score is None from plugin body; pipeline fills it"

    def test_regime_type_is_mean_reversion(self):
        """plugin.regime_type must be 'mean_reversion'."""
        plugin = self._make_plugin()
        assert plugin.regime_type == "mean_reversion"

    def test_shadow_only(self):
        """shadow_only=True ClassVar."""
        plugin = self._make_plugin()
        assert plugin.shadow_only is True

    def test_supporting_factors_include_both_divergences(self):
        """Signal output should include ofi_divergence and cvd_divergence in supporting factors."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            **_GATE_FEATURES,
            "ofi_divergence": 1.8,
            "cvd_divergence": 1.2,
            "cvd_slope_5bar": 200.0,
        }
        for _ in range(2):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        if result.get("direction") != 0:
            supporting = result.get("supporting_factors", [])
            assert any(
                "ofi" in str(s).lower() for s in supporting
            ), f"Expected ofi in supporting: {supporting}"
            assert any(
                "cvd" in str(s).lower() for s in supporting
            ), f"Expected cvd in supporting: {supporting}"

    def test_module_level_plugin_instance(self):
        from src.intelligence.trading.dual_divergence import plugin

        assert plugin.name == "trad_DualDivergence"

    def test_no_signal_uses_canonical_format(self):
        """no-signal output must have direction=0 and signal_type='none'."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        # Missing features → should return no-signal
        result = plugin.compute_full(_make_frames(close, {}))
        assert result.get("direction") == 0
        assert result.get("signal_type") == "none"
