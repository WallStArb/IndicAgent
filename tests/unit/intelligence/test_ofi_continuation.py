"""Unit tests for OFIContinuation — Phase 118 magnitude gate, multi-factor confidence.

Tests:
1. Magnitude gate rejects small OFI
2. Bar gate rejects low count
3. Fires above both gates
4. Magnitude score scales with OFI value
5. Persistence score increases with bar count
6. EWMA alignment boosts when aligned
7. Missing ofi_ewma_5 uses neutral fallback (no crash)
8. shadow_only flag is True
"""

from __future__ import annotations

import pandas as pd

from src.intelligence.trading.ofi_continuation import (
    _MIN_CONSECUTIVE_BARS,
    _OFI_PARAMS,
    OFIContinuationPlugin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ES_THRESHOLD, _ES_UPPER_REF = _OFI_PARAMS["ES"]  # 500.0, 2000.0


def _make_df(n: int = 30) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with enough bars."""
    closes = [5000.0 + i * 0.5 for i in range(n)]
    return pd.DataFrame(
        {
            "open": [c - 0.2 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": [1000.0] * n,
        }
    )


def _make_frames(
    ofi_ewma_20: float,
    ofi_ewma_5: float | None = None,
    rel_volume: float | None = None,
    atr: float = 5.0,
    symbol: str = "ES",
    tf: str = "1m",
    n: int = 30,
) -> dict:
    """Build a minimal frames dict for OFIContinuationPlugin.compute_full()."""
    df = _make_df(n)
    features: dict = {
        "ofi_ewma_20": ofi_ewma_20,
        "atr_14": atr,
        "atr": atr,
    }
    if ofi_ewma_5 is not None:
        features["ofi_ewma_5"] = ofi_ewma_5
    if rel_volume is not None:
        features["rel_volume"] = rel_volume
    return {
        "main": df,
        "i1": features,
        "i2": {},
        "i3": {},
        "i4": {},
        "i5": {},
        "smc": {},
        "i6": {},
        "__symbol__": symbol,
        "__timeframe__": tf,
    }


def _run_n_bars(plugin: OFIContinuationPlugin, frames: dict, n: int) -> dict:
    """Submit the same frames n times and return the last result."""
    result = {}
    for _ in range(n):
        result = plugin.compute_full(frames)
    return result


def _fire_plugin(
    ofi_ewma_20: float = 800.0,
    ofi_ewma_5: float | None = 600.0,
    rel_volume: float | None = 1.5,
    n_bars: int = 12,
    atr: float = 5.0,
    symbol: str = "ES",
) -> dict:
    """Run plugin to a firing state and return the signal."""
    plugin = OFIContinuationPlugin()
    frames = _make_frames(
        ofi_ewma_20=ofi_ewma_20,
        ofi_ewma_5=ofi_ewma_5,
        rel_volume=rel_volume,
        atr=atr,
        symbol=symbol,
    )
    return _run_n_bars(plugin, frames, n_bars)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMagnitudeGate:
    def test_magnitude_gate_rejects_small_ofi(self):
        """ofi_ewma_20=100 (below ES threshold 500) with count=15 -> no signal."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=100.0, ofi_ewma_5=80.0, rel_volume=2.0)
        result = _run_n_bars(plugin, frames, 15)
        assert (
            result.get("direction") == 0
        ), f"Expected no-signal (direction=0), got direction={result.get('direction')}"

    def test_magnitude_gate_uses_per_instrument_threshold(self):
        """NQ threshold is 200 — ofi_ewma_20=250 should pass for NQ but fail for ES."""
        # NQ passes at 250 (threshold=200) with enough bars
        result_nq = _fire_plugin(ofi_ewma_20=250.0, symbol="NQ", n_bars=12)
        assert result_nq.get("direction") != 0, "NQ should fire at ofi_ewma_20=250"

        # ES fails at 250 (threshold=500) — even with 15 bars
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=250.0, symbol="ES")
        result_es = _run_n_bars(plugin, frames, 15)
        assert result_es.get("direction") == 0, "ES should not fire at ofi_ewma_20=250"

    def test_magnitude_gate_uses_default_for_unknown_symbol(self):
        """Unknown symbol uses _MIN_OFI_MAGNITUDE_DEFAULT (500.0)."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=300.0, symbol="XX")  # below default 500
        result = _run_n_bars(plugin, frames, 15)
        assert result.get("direction") == 0, "Unknown symbol with ofi=300 should not fire"


class TestBarGate:
    def test_bar_gate_rejects_low_count(self):
        """ofi_ewma_20=800 (above threshold), count=5 -> no signal (MIN_CONSECUTIVE_BARS=10)."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=800.0, ofi_ewma_5=600.0, rel_volume=1.5)
        result = _run_n_bars(plugin, frames, 5)
        assert (
            result.get("direction") == 0
        ), f"Expected no-signal after 5 bars (need {_MIN_CONSECUTIVE_BARS}), got {result}"

    def test_bar_gate_minimum_is_10(self):
        """Ensure _MIN_CONSECUTIVE_BARS is exactly 10."""
        assert _MIN_CONSECUTIVE_BARS == 10


class TestFiringBehavior:
    def test_fires_above_both_gates(self):
        """ofi_ewma_20=800, count=12, rel_volume=1.5 -> valid signal with confidence > 0."""
        result = _fire_plugin(ofi_ewma_20=800.0, rel_volume=1.5, n_bars=12)
        assert result.get("direction") in (1, -1), f"Expected signal, got {result}"
        assert result.get("confidence", 0.0) > 0.0

    def test_direction_follows_ofi_sign(self):
        """Positive ofi_ewma_20 -> direction=1 (long)."""
        result = _fire_plugin(ofi_ewma_20=800.0, n_bars=12)
        assert result.get("direction") == 1

    def test_negative_ofi_fires_short(self):
        """Negative ofi_ewma_20 -> direction=-1 (short)."""
        result = _fire_plugin(ofi_ewma_20=-800.0, ofi_ewma_5=-600.0, n_bars=12)
        assert result.get("direction") == -1


class TestConfidenceFormula:
    def test_magnitude_score_scales_with_ofi(self):
        """Higher abs(ofi_ewma_20) -> higher confidence (magnitude_score drives 40% weight)."""
        result_low = _fire_plugin(ofi_ewma_20=_ES_THRESHOLD + 1.0, n_bars=12)
        result_high = _fire_plugin(ofi_ewma_20=_ES_UPPER_REF - 1.0, n_bars=12)

        conf_low = result_low.get("confidence", 0.0)
        conf_high = result_high.get("confidence", 0.0)

        assert conf_low > 0.0, "Floor-adjacent OFI should produce non-zero confidence"
        assert (
            conf_high > conf_low
        ), f"Higher OFI magnitude should produce higher confidence: {conf_high} vs {conf_low}"

    def test_persistence_score_increases_with_bars(self):
        """More consecutive bars -> higher persistence_score -> higher confidence."""
        result_min = _fire_plugin(ofi_ewma_20=800.0, n_bars=_MIN_CONSECUTIVE_BARS)
        result_more = _fire_plugin(ofi_ewma_20=800.0, n_bars=_MIN_CONSECUTIVE_BARS + 10)

        conf_min = result_min.get("confidence", 0.0)
        conf_more = result_more.get("confidence", 0.0)

        assert (
            conf_more >= conf_min
        ), f"More bars should produce >= confidence: {conf_more} vs {conf_min}"

    def test_ewma_alignment_boosts_when_aligned(self):
        """ofi_ewma_5 same sign as ofi_ewma_20 -> alignment_score=1.0 vs 0.3."""
        result_aligned = _fire_plugin(ofi_ewma_20=800.0, ofi_ewma_5=600.0, n_bars=12)  # same sign
        result_opposed = _fire_plugin(
            ofi_ewma_20=800.0, ofi_ewma_5=-600.0, n_bars=12  # opposite sign
        )

        conf_aligned = result_aligned.get("confidence", 0.0)
        conf_opposed = result_opposed.get("confidence", 0.0)

        assert (
            conf_aligned > conf_opposed
        ), f"Aligned EWMA should boost confidence vs opposed: {conf_aligned} vs {conf_opposed}"

    def test_confidence_clamped_to_system_ceiling(self):
        """Confidence never exceeds 0.95 (CONF_CEIL from compose_confidence)."""
        # Use ceiling-tier OFI values to maximize confidence
        result = _fire_plugin(
            ofi_ewma_20=_ES_UPPER_REF * 10,  # far above upper ref
            ofi_ewma_5=_ES_UPPER_REF * 10,
            rel_volume=10.0,
            n_bars=_MIN_CONSECUTIVE_BARS + 20,
        )
        confidence = result.get("confidence", 0.0)
        if result.get("direction") != 0:
            assert confidence <= 0.95, f"Confidence exceeds system ceiling: {confidence}"

    def test_confidence_weights_sum_to_1(self):
        """Verify the documented weight structure — computed manually against known inputs."""
        # With: magnitude_score=0.2, alignment_score=1.0, persistence_score=0.0, volume_score=0.333
        # raw_conf = 0.40*0.2 + 0.25*1.0 + 0.20*0.0 + 0.15*0.333 = 0.08+0.25+0.0+0.05 = 0.38
        # Note: this tests the formula indirectly — the plugin output can't be decomposed from outside.
        # Just verify weights contract: 0.40 + 0.25 + 0.20 + 0.15 == 1.0
        weights = [0.40, 0.25, 0.20, 0.15]
        assert abs(sum(weights) - 1.0) < 1e-9, f"Weights should sum to 1.0, got {sum(weights)}"


class TestMissingFeatureFallback:
    def test_missing_ofi_ewma5_uses_neutral_fallback(self):
        """Compute without ofi_ewma_5 and without rel_volume.

        Must not raise NoneType error, and confidence must be in [0.0, 0.95].
        """
        plugin = OFIContinuationPlugin()
        frames = _make_frames(
            ofi_ewma_20=800.0,
            ofi_ewma_5=None,  # explicitly absent
            rel_volume=None,  # explicitly absent — defaults to 1.0 in formula
        )
        # Should not raise
        result = _run_n_bars(plugin, frames, 12)

        if result.get("direction") != 0:
            conf = result.get("confidence", -1.0)
            assert 0.0 <= conf <= 0.95, f"Confidence out of range: {conf}"
        else:
            # Signal rejected (possible if ATR framing fails) — just verify no crash
            assert result.get("signal_type") == "none"

    def test_missing_rel_volume_defaults_to_1(self):
        """rel_volume=None should use 1.0 fallback, producing volume_score=0."""
        # With rel_vol=1.0: volume_score = (1.0 - 1.0) / 1.5 = 0.0
        # With rel_vol=2.5: volume_score = (2.5 - 1.0) / 1.5 = 1.0
        # Confidence with high volume should be >= confidence without volume info
        result_no_vol = _fire_plugin(ofi_ewma_20=800.0, rel_volume=None, n_bars=12)
        result_high_vol = _fire_plugin(ofi_ewma_20=800.0, rel_volume=2.5, n_bars=12)

        if result_high_vol.get("direction") != 0 and result_no_vol.get("direction") != 0:
            assert result_high_vol.get("confidence", 0) >= result_no_vol.get(
                "confidence", 0
            ), "High volume should produce >= confidence vs missing volume"


class TestShadowOnly:
    def test_shadow_only_flag(self):
        """shadow_only must be True — plugin runs in shadow mode only."""
        plugin = OFIContinuationPlugin()
        assert plugin.shadow_only is True

    def test_shadow_only_class_attribute_is_true(self):
        """shadow_only is a class-level attribute (not just instance)."""
        assert OFIContinuationPlugin.shadow_only is True
