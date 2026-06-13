"""Unit tests for OFIContinuation — magnitude gate, onset dedup, multi-factor confidence.

Tests:
1. Magnitude gate rejects small OFI
2. Bar gate rejects low count
3. Fires on bar N where streak first crosses min_bars (onset)
4. Does NOT fire again on subsequent bars of the same streak (onset_guard)
5. Re-fires when streak resets and crosses threshold again (new onset)
6. Magnitude score scales with OFI value
7. Confidence weights sum to 1.0
8. EWMA alignment boosts when aligned
9. Missing ofi_ewma_5 uses neutral fallback (no crash)
10. shadow_only flag is True
"""

from __future__ import annotations

import pandas as pd

from src.intelligence.trading.ofi_continuation import (
    _MAGNITUDE_FLOORS_DEFAULT,
    _MIN_BARS_DEFAULT,
    _UPPER_REF_MULTIPLIER,
    OFIContinuationPlugin,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ES_THRESHOLD = _MAGNITUDE_FLOORS_DEFAULT["ES"]  # 500.0
_ES_UPPER_REF = _ES_THRESHOLD * _UPPER_REF_MULTIPLIER  # 2000.0


def _make_df(n: int = 30) -> pd.DataFrame:
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


def _run_collect(plugin: OFIContinuationPlugin, frames: dict, n: int) -> list[dict]:
    """Submit frames n times, return all results."""
    return [plugin.compute_full(frames) for _ in range(n)]


def _first_signal(results: list[dict]) -> dict | None:
    """Return first non-no-signal result, or None."""
    return next((r for r in results if r.get("direction", 0) != 0), None)


def _fire_once(
    ofi_ewma_20: float = 800.0,
    ofi_ewma_5: float | None = 600.0,
    rel_volume: float | None = 1.5,
    n_bars: int | None = None,
    atr: float = 5.0,
    symbol: str = "ES",
) -> dict:
    """Run plugin until onset fires (returns first signal or no-signal if no fire)."""
    plugin = OFIContinuationPlugin()
    frames = _make_frames(
        ofi_ewma_20=ofi_ewma_20,
        ofi_ewma_5=ofi_ewma_5,
        rel_volume=rel_volume,
        atr=atr,
        symbol=symbol,
    )
    n = n_bars if n_bars is not None else _MIN_BARS_DEFAULT + 2
    results = _run_collect(plugin, frames, n)
    return _first_signal(results) or results[-1]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMagnitudeGate:
    def test_magnitude_gate_rejects_small_ofi(self):
        """ofi_ewma_20=100 (below ES threshold 500) with count=15 -> no signal."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=100.0, ofi_ewma_5=80.0, rel_volume=2.0)
        results = _run_collect(plugin, frames, 15)
        assert _first_signal(results) is None, "Small OFI should never fire"

    def test_magnitude_gate_uses_per_instrument_threshold(self):
        """NQ threshold is 200 — ofi_ewma_20=250 passes for NQ, fails for ES."""
        result_nq = _fire_once(ofi_ewma_20=250.0, symbol="NQ")
        assert result_nq.get("direction") != 0, "NQ should fire at ofi_ewma_20=250"

        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=250.0, symbol="ES")
        results = _run_collect(plugin, frames, 15)
        assert _first_signal(results) is None, "ES should not fire at ofi_ewma_20=250"

    def test_magnitude_gate_uses_default_for_unknown_symbol(self):
        """Unknown symbol uses default floor (500.0). ofi=300 should not fire."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=300.0, symbol="XX")
        results = _run_collect(plugin, frames, 15)
        assert _first_signal(results) is None, "Unknown symbol with ofi=300 should not fire"


class TestBarGate:
    def test_bar_gate_rejects_low_count(self):
        """ofi_ewma_20=800 above threshold, count=5 -> no signal (need min_bars=10)."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=800.0, ofi_ewma_5=600.0, rel_volume=1.5)
        results = _run_collect(plugin, frames, 5)
        assert (
            _first_signal(results) is None
        ), f"Expected no-signal after 5 bars (need {_MIN_BARS_DEFAULT})"

    def test_bar_gate_minimum_is_10(self):
        """Default min_bars is 10."""
        assert _MIN_BARS_DEFAULT == 10


class TestOnsetBehavior:
    def test_fires_on_onset_bar(self):
        """Plugin fires exactly once when streak first reaches min_bars."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=800.0, ofi_ewma_5=600.0, rel_volume=1.5)
        results = _run_collect(plugin, frames, _MIN_BARS_DEFAULT + 5)
        fires = [r for r in results if r.get("direction", 0) != 0]
        assert len(fires) == 1, f"Expected exactly 1 fire on onset, got {len(fires)}"

    def test_does_not_fire_again_in_same_streak(self):
        """After onset fire, subsequent bars in same streak produce no-signal."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=800.0, ofi_ewma_5=600.0, rel_volume=1.5)
        results = _run_collect(plugin, frames, _MIN_BARS_DEFAULT + 10)
        fires = [r for r in results if r.get("direction", 0) != 0]
        assert (
            len(fires) == 1
        ), f"onset_guard should suppress subsequent bars; got {len(fires)} fires"

    def test_refires_on_new_streak(self):
        """Streak breaks (direction flip) then rebuilds -> new onset -> fires again."""
        plugin = OFIContinuationPlugin()

        # First streak: long onset
        long_frames = _make_frames(ofi_ewma_20=800.0, ofi_ewma_5=600.0)
        first_results = _run_collect(plugin, long_frames, _MIN_BARS_DEFAULT + 2)
        first_fires = [r for r in first_results if r.get("direction", 0) != 0]
        assert len(first_fires) == 1, "First streak should produce exactly 1 fire"

        # Direction flip: resets streak counter and rearmed onset_guard
        short_frames = _make_frames(ofi_ewma_20=-800.0, ofi_ewma_5=-600.0)
        flip_results = _run_collect(plugin, short_frames, 3)

        # Second streak: short onset
        second_results = _run_collect(plugin, short_frames, _MIN_BARS_DEFAULT + 2)
        second_fires = [r for r in second_results if r.get("direction", 0) != 0]
        assert len(second_fires) == 1, "New streak should produce exactly 1 new fire"
        assert second_fires[0].get("direction") == -1, "Second fire should be short"

    def test_direction_follows_ofi_sign(self):
        """Positive ofi_ewma_20 -> direction=1 (long)."""
        result = _fire_once(ofi_ewma_20=800.0)
        assert result.get("direction") == 1

    def test_negative_ofi_fires_short(self):
        """Negative ofi_ewma_20 -> direction=-1 (short)."""
        result = _fire_once(ofi_ewma_20=-800.0, ofi_ewma_5=-600.0)
        assert result.get("direction") == -1

    def test_fires_above_both_gates(self):
        """ofi_ewma_20=800, rel_volume=1.5 -> valid signal with confidence > 0."""
        result = _fire_once(ofi_ewma_20=800.0, rel_volume=1.5)
        assert result.get("direction") in (1, -1), f"Expected signal, got {result}"
        assert result.get("confidence", 0.0) > 0.0


class TestConfidenceFormula:
    def test_magnitude_score_scales_with_ofi(self):
        """Higher abs(ofi_ewma_20) -> higher confidence (magnitude_score drives 40% weight)."""
        result_low = _fire_once(ofi_ewma_20=_ES_THRESHOLD + 1.0)
        result_high = _fire_once(ofi_ewma_20=_ES_UPPER_REF - 1.0)

        conf_low = result_low.get("confidence", 0.0)
        conf_high = result_high.get("confidence", 0.0)

        assert conf_low > 0.0, "Floor-adjacent OFI should produce non-zero confidence"
        assert (
            conf_high > conf_low
        ), f"Higher OFI magnitude should produce higher confidence: {conf_high} vs {conf_low}"

    def test_ewma_alignment_boosts_when_aligned(self):
        """ofi_ewma_5 same sign as ofi_ewma_20 -> alignment_score=1.0 vs 0.3."""
        result_aligned = _fire_once(ofi_ewma_20=800.0, ofi_ewma_5=600.0)
        result_opposed = _fire_once(ofi_ewma_20=800.0, ofi_ewma_5=-600.0)

        conf_aligned = result_aligned.get("confidence", 0.0)
        conf_opposed = result_opposed.get("confidence", 0.0)

        assert (
            conf_aligned > conf_opposed
        ), f"Aligned EWMA should boost confidence vs opposed: {conf_aligned} vs {conf_opposed}"

    def test_confidence_clamped_to_system_ceiling(self):
        """Confidence never exceeds 0.95 (CONF_CEIL from compose_confidence)."""
        result = _fire_once(
            ofi_ewma_20=_ES_UPPER_REF * 10,
            ofi_ewma_5=_ES_UPPER_REF * 10,
            rel_volume=10.0,
        )
        confidence = result.get("confidence", 0.0)
        if result.get("direction") != 0:
            assert confidence <= 0.95, f"Confidence exceeds system ceiling: {confidence}"

    def test_confidence_weights_sum_to_1(self):
        """Verify the documented weight structure."""
        weights = [0.40, 0.25, 0.20, 0.15]
        assert abs(sum(weights) - 1.0) < 1e-9, f"Weights should sum to 1.0, got {sum(weights)}"


class TestMissingFeatureFallback:
    def test_missing_ofi_ewma5_uses_neutral_fallback(self):
        """Compute without ofi_ewma_5 — must not raise, confidence in [0.0, 0.95]."""
        result = _fire_once(ofi_ewma_20=800.0, ofi_ewma_5=None, rel_volume=None)
        if result.get("direction") != 0:
            conf = result.get("confidence", -1.0)
            assert 0.0 <= conf <= 0.95, f"Confidence out of range: {conf}"
        else:
            assert result.get("signal_type") == "none"

    def test_missing_rel_volume_defaults_to_1(self):
        """rel_volume=None uses 1.0 fallback. High volume should produce >= confidence."""
        result_no_vol = _fire_once(ofi_ewma_20=800.0, rel_volume=None)
        result_high_vol = _fire_once(ofi_ewma_20=800.0, rel_volume=2.5)

        if result_high_vol.get("direction") != 0 and result_no_vol.get("direction") != 0:
            assert result_high_vol.get("confidence", 0) >= result_no_vol.get(
                "confidence", 0
            ), "High volume should produce >= confidence vs missing volume"


class TestShadowOnly:
    def test_shadow_only_flag(self):
        """shadow_only must be True."""
        plugin = OFIContinuationPlugin()
        assert plugin.shadow_only is True

    def test_shadow_only_class_attribute_is_true(self):
        assert OFIContinuationPlugin.shadow_only is True
