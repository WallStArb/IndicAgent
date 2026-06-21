"""Unit tests for OFI I7 plugins: trad_OFIContinuation, trad_OFIDivergence, trad_OFISpike."""

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


# Minimal feature values that pass the OFISpike dual gate (Phase 119):
# hmm_trending_weight >= 0.30 requires hmm_prob_trending_up or hmm_prob_trending_down >= 0.30;
# abs(ctf_score) >= 0.25.
_SPIKE_GATE_FEATURES = SPIKE_GATE_FEATURES


# ─── OFIContinuation ──────────────────────────────────────────────────────────


class TestOFIContinuation:
    def _make_plugin(self):
        from src.intelligence.archive.trading_i7.ofi_continuation import OFIContinuationPlugin

        return OFIContinuationPlugin()

    def test_fires_on_sustained_directional_ofi(self):
        """After sustained OFI with a volume spike structural trigger, plugin fires direction=1."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        # Phase 124: requires structural trigger (acceleration OR volume spike) on top of sustained flow.
        # Use a 2.5x volume spike as the structural trigger (simplest path to firing).
        base_features = {
            "ofi_ewma_20": 600.0,
            "ofi_ewma_5": 600.0,
            "atr_14": 2.0,
            "volume_sma_20": 400.0,
        }
        for _ in range(9):
            frames = _make_frames(close, base_features)
            plugin.compute_full(frames)
        # Final bar: volume spike (df volume default 1000 vs volume_sma_20=400 → 2.5x)
        frames = _make_frames(close, base_features)
        result = plugin.compute_full(frames)
        assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}: {result}"
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

    def test_no_signal_insufficient_persistence(self):
        """After only 2 bars of positive OFI, no signal fires."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        # Only call once — only 1 bar of history
        frames = _make_frames(close, {"ofi_ewma_20": 150.0, "ofi_ewma_5": 120.0, "atr_14": 2.0})
        result = plugin.compute_full(frames)
        assert result.get("direction") == 0, f"Expected 0, got {result.get('direction')}"

    def test_no_signal_when_ofi_ewma_missing(self):
        """Missing ofi_ewma_20 → no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {})
        result = plugin.compute_full(frames)
        assert result.get("direction") == 0

    def test_regime_type_is_trend(self):
        """plugin.regime_type must be 'trend'."""
        plugin = self._make_plugin()
        assert plugin.regime_type == "trend"

    def test_state_resets_on_direction_flip(self):
        """If OFI sign flips, count resets and no signal fires on first bar of new direction."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        # Build up positive OFI count
        for _ in range(5):
            plugin.compute_full(
                _make_frames(close, {"ofi_ewma_20": 150.0, "ofi_ewma_5": 120.0, "atr_14": 2.0})
            )
        # Flip to negative — count should reset
        result = plugin.compute_full(
            _make_frames(close, {"ofi_ewma_20": -150.0, "ofi_ewma_5": -120.0, "atr_14": 2.0})
        )
        assert result.get("direction") == 0  # count reset, only 1 bar in new direction

    def test_module_level_plugin_instance(self):
        """Module-level plugin instance must have correct name."""
        from src.intelligence.archive.trading_i7.ofi_continuation import plugin

        assert plugin.name == "trad_OFIContinuation"


# ─── OFIDivergence ────────────────────────────────────────────────────────────
# Phase 59: Redesigned — continuous z-score factor, 2-bar persistence, regime_type="any".
# Full coverage: tests/unit/intelligence/test_ofi_divergence.py


class TestOFIDivergence:
    def _make_plugin(self):
        from src.intelligence.archive.trading_i7.ofi_divergence import OFIDivergencePlugin

        return OFIDivergencePlugin()

    def _make_frames_n(self, close_arr, features=None, n=2, symbol="ES", tf="1m"):
        """Return list of n identical frame dicts for persistence warm-up."""
        return [_make_frames(close_arr, features, symbol, tf) for _ in range(n)]

    def test_fires_after_two_bars_bearish_divergence(self):
        """ofi_divergence = -1.8 for 2 bars → direction=-1 (price-discovery short)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        features = {
            "ofi_divergence": -1.8,
            "ofi_ewma_5": -0.5,
            "atr_14": 2.0,
            **_SPIKE_GATE_FEATURES,
        }
        frames = _make_frames(close, features)
        plugin.compute_full(frames)  # bar 1 — no fire
        result = plugin.compute_full(frames)  # bar 2 — should fire
        assert (
            result.get("direction") == -1
        ), f"Expected -1, got {result.get('direction')}: {result}"
        assert result.get("confidence", 0) > 0
        if result.get("direction") != 0:
            assert isinstance(result.get("stop_loss"), float)
            assert isinstance(result.get("targets"), list) and len(result["targets"]) > 0
            assert all(isinstance(t, float) for t in result["targets"])
            assert isinstance(result.get("regime_context"), str)

    def test_fires_after_two_bars_bullish_divergence(self):
        """ofi_divergence = 1.8 for 2 bars → direction=1 (price-discovery long)."""
        plugin = self._make_plugin()
        close = np.linspace(5010.0, 5000.0, 25)
        features = {"ofi_divergence": 1.8, "ofi_ewma_5": 0.5, "atr_14": 2.0, **_SPIKE_GATE_FEATURES}
        frames = _make_frames(close, features)
        plugin.compute_full(frames)  # bar 1
        result = plugin.compute_full(frames)  # bar 2
        assert result.get("direction") == 1, f"Expected 1, got {result.get('direction')}: {result}"

    def test_no_fire_single_bar(self):
        """Single bar above threshold does not fire — persistence requires >= 2 bars."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_divergence": -1.8, "atr_14": 2.0})
        result = plugin.compute_full(frames)
        assert result.get("direction", 0) == 0, "Must not fire on first bar"

    def test_no_signal_when_aligned(self):
        """ofi_divergence near 0 (aligned), no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_divergence": 0.5})
        result = plugin.compute_full(frames)
        assert result.get("direction") == 0

    def test_no_signal_below_threshold(self):
        """ofi_divergence = 1.2 (below 1.5 threshold), no signal even after persistence."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_divergence": 1.2})
        for _ in range(3):
            result = plugin.compute_full(frames)
        assert result.get("direction") == 0

    def test_regime_type_is_any(self):
        """Phase 59: regime_type must be 'any' — no aggregator suppression."""
        plugin = self._make_plugin()
        assert plugin.regime_type == "any"

    def test_no_signal_when_ofi_divergence_missing(self):
        """Missing ofi_divergence → no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(_make_frames(close, {}))
        assert result.get("direction") == 0

    def test_module_level_plugin_instance(self):
        from src.intelligence.archive.trading_i7.ofi_divergence import plugin

        assert plugin.name == "trad_OFIDivergence"


# ─── OFISpike ─────────────────────────────────────────────────────────────────


class TestOFISpike:
    def _make_plugin(self):
        from src.intelligence.archive.trading_i7.ofi_spike import OFISpikePlugin

        return OFISpikePlugin()

    def test_fires_when_ofi_spike_z_exceeds_2_positive(self):
        """ofi_spike_z = 2.5 fires with direction=1 (gate-passing HMM+CTF included)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_spike_z": 2.5, "atr_14": 2.0, **_SPIKE_GATE_FEATURES})
        result = plugin.compute_full(frames)
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

    def test_fires_when_ofi_spike_z_exceeds_2_negative(self):
        """ofi_spike_z = -2.5 fires with direction=-1 (gate-passing HMM+CTF included)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_spike_z": -2.5, "atr_14": 2.0, **_SPIKE_GATE_FEATURES})
        result = plugin.compute_full(frames)
        assert result.get("direction") == -1

    def test_no_signal_below_threshold(self):
        """ofi_spike_z = 1.0, no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_spike_z": 1.0})
        result = plugin.compute_full(frames)
        assert result.get("direction") == 0

    def test_no_signal_at_exactly_2(self):
        """ofi_spike_z = 2.0 (exactly at boundary), no signal (threshold is > 2.0)."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_spike_z": 2.0})
        result = plugin.compute_full(frames)
        assert result.get("direction") == 0

    def test_regime_type_is_any(self):
        """plugin.regime_type must be 'any'."""
        plugin = self._make_plugin()
        assert plugin.regime_type == "any"

    def test_stateless(self):
        """OFISpike plugin should not have _state as an instance attribute with content."""
        plugin = self._make_plugin()
        # Plugin is stateless — either no _state attribute, or empty dict at class level
        # The key is that calling compute_full multiple times works without state
        close = np.linspace(5000.0, 5010.0, 25)
        frames = _make_frames(close, {"ofi_spike_z": 2.5, "atr_14": 2.0, **_SPIKE_GATE_FEATURES})
        r1 = plugin.compute_full(frames)
        r2 = plugin.compute_full(frames)
        assert r1.get("direction") == r2.get("direction") == 1

    def test_no_signal_when_ofi_spike_z_missing(self):
        """Missing ofi_spike_z → no signal."""
        plugin = self._make_plugin()
        close = np.linspace(5000.0, 5010.0, 25)
        result = plugin.compute_full(_make_frames(close, {}))
        assert result.get("direction") == 0

    def test_module_level_plugin_instance(self):
        from src.intelligence.archive.trading_i7.ofi_spike import plugin

        assert plugin.name == "trad_OFISpike"
