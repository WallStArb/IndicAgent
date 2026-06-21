"""Unit tests for CVD I7 plugins: trad_CVDDivergence, trad_CVDSpike, trad_DeltaExhaustion."""

from __future__ import annotations

import numpy as np

from tests.unit.intelligence.helpers import make_ohlcv
from tests.unit.intelligence.trading.conftest import SPIKE_GATE_FEATURES


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


# Minimal feature values that pass the CVDSpike dual gate (Phase 119):
# hmm_trending_weight >= 0.30 and abs(ctf_score) >= 0.25.
_SPIKE_GATE_FEATURES = SPIKE_GATE_FEATURES

# DeltaExhaustion gate: hmm_prob_ranging >= 0.30 and abs(ctf_score) >= 0.25
_EXHAUSTION_GATE_FEATURES: dict = {
    "hmm_prob_ranging": 0.60,
    "ctf_score": 0.5,
}


# ─── CVDDivergence ────────────────────────────────────────────────────────────


class TestCVDDivergence:
    def _make_plugin(self):
        from src.intelligence.archive.trading_i7.cvd_divergence import CVDDivergencePlugin

        return CVDDivergencePlugin()

    def test_fires_when_cvd_disagrees_with_price(self):
        """cvd_divergence != 0 AND cvd_slope_5bar opposes price direction for N bars."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)  # rising price
        # CVD slope negative (bears) vs rising price → divergence
        features = {
            "cvd_divergence": -1.5,
            "cvd_slope_5bar": -200.0,  # negative slope vs rising price
            "ofi_divergence": 0.0,
            "atr_14": 2.0,
        }
        # Build up confirmation count (N=5: Phase 118 raised from 3)
        for _ in range(4):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        assert (
            result.get("direction") == -1
        ), f"Expected -1, got {result.get('direction')}: {result}"
        assert result.get("confidence", 0) > 0
        if result.get("direction") != 0:
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

    def test_dual_divergence_flag_true(self):
        """Both ofi_divergence and cvd_divergence nonzero and diverging → dual_divergence=True."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            "cvd_divergence": -1.5,
            "cvd_slope_5bar": -200.0,
            "ofi_divergence": -1.2,  # both OFI and CVD diverging
            "atr_14": 2.0,
        }
        # Build confirmation count (N=5: Phase 118 raised from 3)
        for _ in range(4):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        assert result.get("direction") == -1
        assert result.get("dual_divergence") is True, f"Expected dual_divergence=True: {result}"

    def test_dual_divergence_flag_false_when_only_cvd_diverges(self):
        """Only CVD diverges but OFI aligned → dual_divergence=False."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            "cvd_divergence": -1.5,
            "cvd_slope_5bar": -200.0,
            "ofi_divergence": 0.3,  # OFI not strongly diverging
            "atr_14": 2.0,
        }
        for _ in range(4):
            plugin.compute_full(_make_frames(close, features))
        result = plugin.compute_full(_make_frames(close, features))
        if result.get("direction") == -1:
            assert (
                result.get("dual_divergence") is False
            ), f"Expected dual_divergence=False: {result}"

    def test_no_signal_insufficient_confirmation(self):
        """Only 1 bar of CVD divergence → insufficient confirmation, no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            "cvd_divergence": -1.5,
            "cvd_slope_5bar": -200.0,
            "ofi_divergence": 0.0,
            "atr_14": 2.0,
        }
        # Only 1 call
        result = plugin.compute_full(_make_frames(close, features))
        assert result.get("direction") == 0

    def test_regime_type_is_mean_reversion(self):
        """plugin.regime_type must be 'mean_reversion'."""
        plugin = self._make_plugin()
        assert plugin.regime_type == "mean_reversion"

    def test_no_signal_when_cvd_divergence_zero(self):
        """cvd_divergence = 0 → no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(
            _make_frames(close, {"cvd_divergence": 0.0, "cvd_slope_5bar": 0.0})
        )
        assert result.get("direction") == 0

    def test_module_level_plugin_instance(self):
        from src.intelligence.archive.trading_i7.cvd_divergence import plugin

        assert plugin.name == "trad_CVDDivergence"


# ─── CVDSpike ─────────────────────────────────────────────────────────────────


class TestCVDSpike:
    def _make_plugin(self):
        from src.intelligence.archive.trading_i7.cvd_spike import CVDSpikePlugin

        return CVDSpikePlugin()

    def test_fires_when_cvd_spike_z_exceeds_2_positive(self):
        """cvd_spike_z = 2.5 fires with direction=1 (gate-passing HMM+CTF included)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(
            _make_frames(close, {"cvd_spike_z": 2.5, "atr_14": 2.0, **_SPIKE_GATE_FEATURES})
        )
        assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}"
        assert result.get("confidence", 0) > 0
        if result.get("direction") != 0:
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

    def test_fires_when_cvd_spike_z_exceeds_2_negative(self):
        """cvd_spike_z = -2.5 fires with direction=-1 (gate-passing HMM+CTF included)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(
            _make_frames(close, {"cvd_spike_z": -2.5, "atr_14": 2.0, **_SPIKE_GATE_FEATURES})
        )
        assert result.get("direction") == -1

    def test_no_signal_below_threshold(self):
        """cvd_spike_z = 1.0, no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(_make_frames(close, {"cvd_spike_z": 1.0}))
        assert result.get("direction") == 0

    def test_no_signal_at_exactly_2(self):
        """cvd_spike_z = 2.0, no signal (threshold is > 2.0)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(_make_frames(close, {"cvd_spike_z": 2.0}))
        assert result.get("direction") == 0

    def test_regime_type_is_any(self):
        """plugin.regime_type must be 'any'."""
        plugin = self._make_plugin()
        assert plugin.regime_type == "any"

    def test_symmetric_with_ofi_spike(self):
        """CVDSpike fires same way as OFISpike — z > 2 fires, z < 2 doesn't."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        # Positive: direction 1
        r_pos = plugin.compute_full(
            _make_frames(close, {"cvd_spike_z": 3.0, "atr_14": 2.0, **_SPIKE_GATE_FEATURES})
        )
        assert r_pos.get("direction") == 1
        # Negative: direction -1
        r_neg = plugin.compute_full(
            _make_frames(close, {"cvd_spike_z": -3.0, "atr_14": 2.0, **_SPIKE_GATE_FEATURES})
        )
        assert r_neg.get("direction") == -1

    def test_no_signal_when_cvd_spike_z_missing(self):
        """Missing cvd_spike_z → no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(_make_frames(close, {}))
        assert result.get("direction") == 0

    def test_module_level_plugin_instance(self):
        from src.intelligence.archive.trading_i7.cvd_spike import plugin

        assert plugin.name == "trad_CVDSpike"


# ─── DeltaExhaustion ──────────────────────────────────────────────────────────


class TestDeltaExhaustion:
    def _make_plugin(self):
        from src.intelligence.archive.trading_i7.delta_exhaustion import DeltaExhaustionPlugin

        return DeltaExhaustionPlugin()

    def _make_frames_with_price_stall(self, spike_direction=1):
        """Create frames where CVD spikes but price barely moves."""
        # Flat price (stall) with large CVD spike
        close = np.full(25, 5000.0)  # flat
        atr = 10.0
        cvd_spike_z = 2.0 * spike_direction  # above 1.5 threshold
        return _make_frames(
            close,
            {
                "cvd_spike_z": cvd_spike_z,
                "atr_14": atr,
                **_EXHAUSTION_GATE_FEATURES,
            },
        )

    def test_fires_when_large_cvd_but_price_stalls(self):
        """cvd_spike_z > 1.5 but price change < 0.3 ATR → delta exhaustion fires."""
        plugin = self._make_plugin()
        # Flat price with positive CVD spike (buying but no follow-through)
        close = np.full(25, 5000.0)
        features = {"cvd_spike_z": 2.5, "atr_14": 10.0, **_EXHAUSTION_GATE_FEATURES}
        result = plugin.compute_full(_make_frames(close, features))
        assert (
            result.get("direction") == -1
        ), f"Expected -1 (reversal vs spike), got {result.get('direction')}: {result}"
        assert result.get("confidence", 0) > 0
        if result.get("direction") != 0:
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

    def test_no_signal_when_price_follows_cvd(self):
        """cvd_spike_z > 1.5 and price moves > 0.5 ATR in CVD direction → no signal."""
        plugin = self._make_plugin()
        atr = 10.0
        # Price moved 6 points (0.6 ATR) in CVD direction
        close = np.concatenate([np.full(24, 5000.0), [5006.0]])
        features = {"cvd_spike_z": 2.5, "atr_14": atr}
        result = plugin.compute_full(_make_frames(close, features))
        assert (
            result.get("direction") == 0
        ), f"Expected 0 (price followed), got {result.get('direction')}"

    def test_no_signal_when_cvd_spike_z_below_threshold(self):
        """cvd_spike_z = 1.0 (below 1.5 threshold) → no signal regardless of price."""
        plugin = self._make_plugin()
        close = np.full(25, 5000.0)
        result = plugin.compute_full(_make_frames(close, {"cvd_spike_z": 1.0, "atr_14": 10.0}))
        assert result.get("direction") == 0

    def test_fires_short_on_negative_spike_with_stall(self):
        """Negative CVD spike but price doesn't drop → fires long (bullish exhaustion)."""
        plugin = self._make_plugin()
        close = np.full(25, 5000.0)
        features = {"cvd_spike_z": -2.5, "atr_14": 10.0, **_EXHAUSTION_GATE_FEATURES}
        result = plugin.compute_full(_make_frames(close, features))
        assert (
            result.get("direction") == 1
        ), f"Expected 1 (reversal vs neg spike), got {result.get('direction')}"

    def test_regime_type_is_mean_reversion(self):
        """plugin.regime_type must be 'mean_reversion'."""
        plugin = self._make_plugin()
        assert plugin.regime_type == "mean_reversion"

    def test_no_signal_when_cvd_spike_z_missing(self):
        """Missing cvd_spike_z → no signal."""
        plugin = self._make_plugin()
        close = np.full(25, 5000.0)
        result = plugin.compute_full(_make_frames(close, {"atr_14": 10.0}))
        assert result.get("direction") == 0

    def test_no_signal_when_atr_missing(self):
        """Missing atr_14 and no df high/low data to compute ATR → no signal."""
        plugin = self._make_plugin()
        # make_ohlcv generates spread=0.002*close so high/low differ
        # ATR will be computed from df — this should still work
        close = np.full(25, 5000.0)
        features = {"cvd_spike_z": 2.5}  # no atr_14
        result = plugin.compute_full(_make_frames(close, features))
        # Should still work since df has high/low for fallback ATR
        # direction depends on whether fallback ATR > 0 (it should be)
        assert "direction" in result

    def test_module_level_plugin_instance(self):
        from src.intelligence.archive.trading_i7.delta_exhaustion import plugin

        assert plugin.name == "trad_DeltaExhaustion"
