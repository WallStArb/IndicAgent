"""Unit tests for OFIDivergencePlugin — I7 price-discovery signal."""

from __future__ import annotations

import pandas as pd


def _make_frames(
    n: int = 30,
    ofi_divergence: float = 2.0,
    ofi_spike_z: float = 2.0,
    ofi_ewma_5: float = 0.5,
    ofi_ewma_20: float = 0.3,
    rel_volume: float = 1.8,
    hmm_regime: float = 0.0,
    atr: float = 2.0,
    symbol: str = "ES",
    tf: str = "1m",
    ctf_score: float = 0.5,
    hmm_prob_trending_up: float = 0.6,
    hmm_prob_trending_down: float = 0.3,
) -> dict:
    """Build a minimal frames dict for OFIDivergencePlugin.compute_full()."""
    closes = [5000.0 + i * 0.1 for i in range(n)]
    df = pd.DataFrame(
        {
            "open": [c - 0.05 for c in closes],
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )
    features = {
        "ofi_divergence": ofi_divergence,
        "ofi_spike_z": ofi_spike_z,
        "ofi_ewma_5": ofi_ewma_5,
        "ofi_ewma_20": ofi_ewma_20,
        "rel_volume": rel_volume,
        "hmm_regime": hmm_regime,
        "atr": atr,
        "atr_14": atr,
        # Phase 119: gate-passing values for dual gate
        "ctf_score": ctf_score,
        "hmm_prob_trending_up": hmm_prob_trending_up,
        "hmm_prob_trending_down": hmm_prob_trending_down,
    }
    return {
        "main": df,
        "i1": features,
        "i2": features,
        "i3": features,
        "i4": features,
        "i5": features,
        "smc": features,
        "i6": features,
        "__symbol__": symbol,
        "__timeframe__": tf,
    }


class TestOFIDivergencePlugin:
    def setup_method(self):
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

        self.plugin = OFIDivergencePlugin()

    def _fire_n_times(self, frames: dict, n: int) -> dict:
        """Call compute_full n times with same frames, return last result."""
        result = {}
        for _ in range(n):
            result = self.plugin.compute_full(frames)
        return result

    def test_no_fire_single_bar(self):
        """Does not fire on first bar — persistence requires >= 2 consecutive bars."""
        frames = _make_frames(ofi_divergence=2.5)
        result = self.plugin.compute_full(frames)
        assert result.get("direction", 0) == 0, "Must not fire on single bar"

    def test_fires_after_two_consecutive_bars(self):
        """Fires after 2 bars with same sign and abs >= 1.5."""
        frames = _make_frames(ofi_divergence=2.0)
        result = self._fire_n_times(frames, 2)
        assert result.get("direction") in (1, -1), f"Expected fire, got: {result}"

    def test_no_fire_below_threshold(self):
        """Does not fire when abs(ofi_divergence) < 1.5, even after persistence."""
        frames = _make_frames(ofi_divergence=1.2)
        result = self._fire_n_times(frames, 3)
        assert result.get("direction", 0) == 0, "Below threshold must not fire"

    def test_direction_follows_ofi_sign(self):
        """direction = sign(ofi_divergence): positive div → long (1), negative → short (-1)."""
        frames_long = _make_frames(ofi_divergence=2.0, ofi_ewma_5=0.5)
        self._fire_n_times(frames_long, 2)
        result = self.plugin.compute_full(frames_long)
        assert result.get("direction") == 1

        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

        plugin2 = OFIDivergencePlugin()
        frames_short = _make_frames(ofi_divergence=-2.0, ofi_ewma_5=-0.5)
        for _ in range(2):
            result2 = plugin2.compute_full(frames_short)
        assert result2.get("direction") == -1

    def test_state_resets_on_sign_flip(self):
        """After sign flip, persistence counter resets — must wait 2 bars again."""
        frames_pos = _make_frames(ofi_divergence=2.0)
        self._fire_n_times(frames_pos, 2)  # builds persistence

        frames_neg = _make_frames(ofi_divergence=-2.0, ofi_ewma_5=-0.5)
        result = self.plugin.compute_full(frames_neg)  # first bar of new sign
        assert result.get("direction", 0) == 0, "After sign flip, first bar must not fire"

    def test_peak_abs_used_in_confidence(self):
        """Higher peak divergence → higher confidence."""
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

        plugin_low = OFIDivergencePlugin()
        frames_low = _make_frames(ofi_divergence=1.6)
        for _ in range(2):
            r_low = plugin_low.compute_full(frames_low)

        plugin_high = OFIDivergencePlugin()
        frames_high = _make_frames(ofi_divergence=3.5)
        for _ in range(2):
            r_high = plugin_high.compute_full(frames_high)

        assert r_low.get("direction"), "Expected plugin to fire for low divergence"
        assert r_high.get("direction"), "Expected plugin to fire for high divergence"
        assert (
            r_high["confidence"] > r_low["confidence"]
        ), "Higher divergence magnitude must produce higher confidence"

    def test_ewma_agreement_boosts_confidence(self):
        """Fast EWMA agreeing with divergence direction boosts confidence."""
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

        plugin_agree = OFIDivergencePlugin()
        frames_agree = _make_frames(ofi_divergence=2.0, ofi_ewma_5=0.8)
        for _ in range(2):
            r_agree = plugin_agree.compute_full(frames_agree)

        plugin_disagree = OFIDivergencePlugin()
        frames_disagree = _make_frames(ofi_divergence=2.0, ofi_ewma_5=-0.5)
        for _ in range(2):
            r_disagree = plugin_disagree.compute_full(frames_disagree)

        assert r_agree.get("direction"), "Expected plugin to fire with agreeing EWMA"
        assert r_disagree.get("direction"), "Expected plugin to fire with disagreeing EWMA"
        assert (
            r_agree["confidence"] > r_disagree["confidence"]
        ), "EWMA agreement must boost confidence vs disagreement"

    def test_regime_type_is_any(self):
        """Plugin must declare regime_type='any' — no aggregator suppression."""
        from src.intelligence.trading.ofi_divergence import OFIDivergencePlugin

        assert OFIDivergencePlugin.regime_type == "any"  # type: ignore[attr-defined]

    def test_no_fire_when_ofi_divergence_missing(self):
        """Returns no_signal() when ofi_divergence not in features."""
        frames = _make_frames()
        frames["i1"].pop("ofi_divergence")
        result = self.plugin.compute_full(frames)
        assert result.get("direction", 0) == 0

    def test_supporting_factors_logged(self):
        """Supporting factors include ofi_divergence, peak_abs, bars_persistent."""
        frames = _make_frames(ofi_divergence=2.0)
        for _ in range(2):
            result = self.plugin.compute_full(frames)
        assert result.get("direction"), "Expected plugin to fire"
        factors = result.get("supporting_factors", [])
        factor_str = " ".join(factors)
        assert "ofi_divergence" in factor_str
        assert "peak_abs" in factor_str
        assert "bars_persistent" in factor_str

    def test_context_features_empty_from_plugin(self):
        """Phase 126-06: plugin body returns context_features={} (pipeline annotates after)."""
        frames = _make_frames(ofi_divergence=2.0)
        for _ in range(2):
            result = self.plugin.compute_full(frames)
        assert result.get("direction"), "Expected plugin to fire"
        assert "features_snapshot" not in result, "features_snapshot removed in Phase 126-06"
        assert result.get("context_features") == {}, "Plugin must return empty context_features"

    def test_plugin_module_export(self):
        """Module-level plugin singleton has correct name."""
        from src.intelligence.trading.ofi_divergence import plugin

        assert plugin.name == "trad_OFIDivergence"
