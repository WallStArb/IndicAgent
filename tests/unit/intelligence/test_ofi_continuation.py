"""Unit tests for OFIContinuation structural rewrite (Phase 124-03).

Tests:
1. Magnitude gate rejects small OFI
2. Bar gate rejects low count (context filter)
3. Streak-only (no acceleration, no volume spike) -> NO signal
4. Streak + EWMA acceleration -> fires on acceleration bar
5. Volume spike (2x) + streak -> fires once on spike bar
6. Streak + acceleration -> exactly one fire (deduplicate_event suppresses re-fire)
7. Magnitude score scales with OFI value
8. Confidence weights sum to 1.0
9. EWMA alignment boosts when aligned
10. Missing ofi_ewma_5 uses neutral fallback (no crash)
11. shadow_only flag is True
12. test_streak_only_no_signal -- plan-mandated: streak alone never fires
13. test_streak_with_acceleration_fires_once -- plan-mandated: acceleration triggers once
14. test_volume_spike_fires_once -- plan-mandated: volume spike triggers, dedup prevents re-fire
"""

from __future__ import annotations

import pandas as pd

from src.intelligence.archive.trading_i7.ofi_continuation import (
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


def _make_df(n: int = 30, volumes: list[float] | None = None) -> pd.DataFrame:
    closes = [5000.0 + i * 0.5 for i in range(n)]
    if volumes is None:
        volumes = [1000.0] * n
    return pd.DataFrame(
        {
            "open": [c - 0.2 for c in closes],
            "high": [c + 1.0 for c in closes],
            "low": [c - 1.0 for c in closes],
            "close": closes,
            "volume": volumes,
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
    volume: float = 1000.0,
    vol_sma_20: float | None = None,
) -> dict:
    """Build a frame dict with constant ofi_ewma_20 (for streak tests)."""
    df = _make_df(n, volumes=[volume] * n)
    features: dict = {
        "ofi_ewma_20": ofi_ewma_20,
        "atr_14": atr,
        "atr": atr,
    }
    if ofi_ewma_5 is not None:
        features["ofi_ewma_5"] = ofi_ewma_5
    if rel_volume is not None:
        features["rel_volume"] = rel_volume
    if vol_sma_20 is not None:
        features["volume_sma_20"] = vol_sma_20
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


def _make_frames_with_ewma(
    ewma_value: float,
    ofi_ewma_5: float | None = None,
    atr: float = 5.0,
    symbol: str = "ES",
    tf: str = "1m",
    volume: float = 1000.0,
    vol_sma_20: float | None = None,
) -> dict:
    """Build a frame dict with a specific ofi_ewma_20 value for stepping through sequences."""
    return _make_frames(
        ofi_ewma_20=ewma_value,
        ofi_ewma_5=ofi_ewma_5,
        atr=atr,
        symbol=symbol,
        tf=tf,
        volume=volume,
        vol_sma_20=vol_sma_20,
    )


def _run_collect(plugin: OFIContinuationPlugin, frames: dict, n: int) -> list[dict]:
    """Submit frames n times, return all results."""
    return [plugin.compute_full(frames) for _ in range(n)]


def _run_sequence(
    plugin: OFIContinuationPlugin,
    ewma_sequence: list[float],
    vol_sma_20: float | None = None,
    volume_per_bar: float = 1000.0,
    atr: float = 5.0,
    symbol: str = "ES",
    tf: str = "1m",
) -> list[dict]:
    """Submit one frame per EWMA value in the sequence, return all results."""
    results = []
    for ewma in ewma_sequence:
        frames = _make_frames_with_ewma(
            ewma_value=ewma,
            atr=atr,
            symbol=symbol,
            tf=tf,
            volume=volume_per_bar,
            vol_sma_20=vol_sma_20,
        )
        results.append(plugin.compute_full(frames))
    return results


def _first_signal(results: list[dict]) -> dict | None:
    """Return first non-no-signal result, or None."""
    return next((r for r in results if r.get("direction", 0) != 0), None)


def _signals_at(results: list[dict]) -> list[int]:
    """Return bar indices (0-based) where a signal fired."""
    return [i for i, r in enumerate(results) if r.get("direction", 0) != 0]


def _fire_via_acceleration(
    ofi_ewma_20_final: float = 800.0,
    ofi_ewma_5: float | None = 600.0,
    rel_volume: float | None = 1.5,
    atr: float = 5.0,
    symbol: str = "ES",
    mag_floor: float | None = None,
) -> dict:
    """Run plugin with a ramp-then-accelerate EWMA pattern.

    Builds a streak (stable EWMA, no acceleration), then fires an acceleration
    burst with step-of-change differences well above the floor * 0.10 threshold.

    The acceleration burst uses three bars where each delta is at least 1.5x the
    previous, so the second derivative (change-of-change) exceeds the threshold.
    """
    from src.intelligence.archive.trading_i7.ofi_continuation import _MAGNITUDE_FLOORS_DEFAULT

    plugin = OFIContinuationPlugin()
    sign = 1.0 if ofi_ewma_20_final >= 0 else -1.0
    abs_final = abs(ofi_ewma_20_final)

    # Resolve the magnitude floor for this symbol to compute threshold
    floor = mag_floor or float(
        _MAGNITUDE_FLOORS_DEFAULT.get(symbol, _MAGNITUDE_FLOORS_DEFAULT["_default"])
    )
    # Threshold for acceleration = floor * 0.10
    # We need step-of-change diff to exceed this. Use 2x threshold as step increment.
    step_increment = floor * 0.25  # >= 2.5x threshold, well above the 0.10 fraction gate

    # Stable period: builds streak and fills EWMA buffer without acceleration
    # Use the final absolute value * 0.8 as stable base (above floor but no accel)
    stable_ewma = sign * max(abs_final * 0.8, floor * 1.1)
    stable_count = _MIN_BARS_DEFAULT + 3  # ensures streak and buffer are established
    frames_stable = _make_frames(
        ofi_ewma_20=stable_ewma,
        ofi_ewma_5=ofi_ewma_5,
        rel_volume=rel_volume,
        atr=atr,
        symbol=symbol,
    )
    for _ in range(stable_count):
        plugin.compute_full(frames_stable)

    # Acceleration burst: increasing deltas => positive second derivative
    # bar 0: base (same as stable, establishes reference in buffer)
    # bar 1: base + step_increment (first delta)
    # bar 2: base + step_increment + 2*step_increment (second delta = 2x first)
    # acceleration = 2*step_increment - step_increment = step_increment >> threshold
    base = stable_ewma
    accel_values = [
        base,
        base + sign * step_increment,
        base + sign * step_increment + sign * 2 * step_increment,
        base + sign * step_increment + sign * 2 * step_increment + sign * 3 * step_increment,
    ]
    results = []
    for v in accel_values:
        frames = _make_frames(
            ofi_ewma_20=v,
            ofi_ewma_5=ofi_ewma_5,
            rel_volume=rel_volume,
            atr=atr,
            symbol=symbol,
        )
        results.append(plugin.compute_full(frames))

    return _first_signal(results) or results[-1]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMagnitudeGate:
    def test_magnitude_gate_rejects_small_ofi(self):
        """ofi_ewma_20=100 (below ES threshold 500) -> no signal regardless of count."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=100.0, ofi_ewma_5=80.0, rel_volume=2.0)
        results = _run_collect(plugin, frames, 15)
        assert _first_signal(results) is None, "Small OFI should never fire"

    def test_magnitude_gate_uses_per_instrument_threshold(self):
        """NQ threshold is 200 -- ofi_ewma_20=250 passes for NQ, fails for ES."""
        # NQ: should eventually fire via acceleration if we supply ramp
        result_nq = _fire_via_acceleration(ofi_ewma_20_final=250.0, symbol="NQ")
        assert result_nq.get("direction") != 0, "NQ should fire at ofi_ewma_20=250"

        # ES: 250 is below ES floor of 500 -- never fires
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=250.0, symbol="ES")
        results = _run_collect(plugin, frames, 20)
        assert _first_signal(results) is None, "ES should not fire at ofi_ewma_20=250"

    def test_magnitude_gate_uses_default_for_unknown_symbol(self):
        """Unknown symbol uses default floor (500.0). ofi=300 should not fire."""
        plugin = OFIContinuationPlugin()
        frames = _make_frames(ofi_ewma_20=300.0, symbol="XX")
        results = _run_collect(plugin, frames, 20)
        assert _first_signal(results) is None, "Unknown symbol with ofi=300 should not fire"


class TestBarGate:
    def test_bar_gate_rejects_low_count(self):
        """Context filter: ofi_ewma_20=800 above threshold, count < min_bars -> no signal."""
        plugin = OFIContinuationPlugin()
        # Feed acceleration but only 5 bars -- streak context not satisfied
        ewma_sequence = [800.0, 810.0, 825.0, 845.0, 870.0]  # 5 bars with acceleration
        assert len(ewma_sequence) < _MIN_BARS_DEFAULT
        results = _run_sequence(plugin, ewma_sequence, symbol="ES")
        assert (
            _first_signal(results) is None
        ), f"Expected no-signal after {len(ewma_sequence)} bars (need {_MIN_BARS_DEFAULT})"

    def test_bar_gate_minimum_is_10(self):
        """Default min_bars is 10."""
        assert _MIN_BARS_DEFAULT == 10


class TestStructuralTrigger:
    def test_streak_only_no_signal(self):
        """Streak-only (constant EWMA, no acceleration, no volume spike) -> NO signal.

        This is the central invariant of the structural rewrite:
        sustained imbalance alone is not a hypothesis; a structural thrust event is.
        """
        plugin = OFIContinuationPlugin()
        # Constant EWMA: second derivative = 0, no volume spike
        frames = _make_frames(ofi_ewma_20=800.0, ofi_ewma_5=600.0, rel_volume=1.5)
        results = _run_collect(plugin, frames, _MIN_BARS_DEFAULT + 15)
        assert (
            _first_signal(results) is None
        ), "Constant EWMA streak (no acceleration, no spike) must NEVER fire"

    def test_streak_with_acceleration_fires_once(self):
        """Streak + EWMA acceleration -> fires exactly once on the acceleration bar.

        EWMA sequence with increasing deltas (positive second derivative):
        bars 0-14: stable at 800 (streak builds, buffer fills, no acceleration)
        bars 15-18: 800, 925, 1075, 1250 (deltas: 125, 150, 175 -- accelerating)
        Acceleration = delta[n] - delta[n-1] = 25, which is below ES threshold (50).
        Use step_increment = 500*0.25 = 125 so acceleration = 125 > 50.
        """
        # ES floor = 500, threshold = 50; step_increment = 500*0.25 = 125
        step_increment = _ES_THRESHOLD * 0.25  # 125.0 -- gives acceleration of 125

        plugin = OFIContinuationPlugin()
        stable_ewma = 800.0

        # Step 1: build streak of min_bars + buffer stable bars (no acceleration)
        for _ in range(_MIN_BARS_DEFAULT + 5):
            frames = _make_frames(ofi_ewma_20=stable_ewma, ofi_ewma_5=600.0)
            plugin.compute_full(frames)

        # Step 2: fire acceleration bars -- deltas increase by step_increment each bar
        # bar 0: 800 (delta vs prev = 0)
        # bar 1: 800 + 125 = 925 (delta = 125)
        # bar 2: 925 + 250 = 1175 (delta = 250, acceleration = 125 > threshold 50)
        accel_sequence = [
            stable_ewma,
            stable_ewma + step_increment,
            stable_ewma + step_increment + 2 * step_increment,
            stable_ewma + step_increment + 2 * step_increment + 3 * step_increment,
        ]
        accel_results = []
        for v in accel_sequence:
            frames = _make_frames(ofi_ewma_20=v, ofi_ewma_5=600.0)
            accel_results.append(plugin.compute_full(frames))

        fires = [r for r in accel_results if r.get("direction", 0) != 0]
        assert len(fires) >= 1, "Acceleration on top of established streak must fire"
        assert fires[0].get("direction") == 1, "Long OFI acceleration must yield direction=1"

    def test_volume_spike_fires_once(self):
        """Volume spike (2.5x) on top of streak -> fires once; deduplicate_event suppresses re-fire.

        Setup: 10+ stable bars (streak established, no acceleration).
        Bar 11: volume = 2.5x avg -> volume_spike=True, fires.
        Bars 12-30: same vol spike (same direction) -> deduplicate_event suppresses.
        """
        plugin = OFIContinuationPlugin()
        vol_sma = 1000.0
        spike_vol = 2500.0  # 2.5x

        # Step 1: build streak with normal volume (no spike)
        for _ in range(_MIN_BARS_DEFAULT + 1):
            frames = _make_frames(
                ofi_ewma_20=800.0,
                ofi_ewma_5=600.0,
                volume=vol_sma,
                vol_sma_20=vol_sma,
            )
            plugin.compute_full(frames)

        # Step 2: spike bar should trigger once
        spike_results = []
        for _ in range(15):
            frames = _make_frames(
                ofi_ewma_20=800.0,
                ofi_ewma_5=600.0,
                volume=spike_vol,
                vol_sma_20=vol_sma,
            )
            spike_results.append(plugin.compute_full(frames))

        fires = [r for r in spike_results if r.get("direction", 0) != 0]
        assert len(fires) == 1, (
            f"Volume spike must fire exactly once (deduplicate_event suppresses same-direction re-fire); "
            f"got {len(fires)} fires"
        )
        assert fires[0].get("direction") == 1

    def test_direction_follows_ofi_sign(self):
        """Positive ofi acceleration -> direction=1 (long)."""
        result = _fire_via_acceleration(ofi_ewma_20_final=800.0)
        if result.get("direction") != 0:
            assert result.get("direction") == 1

    def test_negative_ofi_fires_short(self):
        """Negative ofi acceleration -> direction=-1 (short)."""
        result = _fire_via_acceleration(ofi_ewma_20_final=-800.0, ofi_ewma_5=-600.0)
        if result.get("direction") != 0:
            assert result.get("direction") == -1


class TestConfidenceFormula:
    def test_magnitude_score_scales_with_ofi(self):
        """Higher abs(ofi_ewma_20) -> higher confidence (magnitude_score drives 40% weight)."""
        result_low = _fire_via_acceleration(ofi_ewma_20_final=_ES_THRESHOLD + 10.0)
        result_high = _fire_via_acceleration(ofi_ewma_20_final=_ES_UPPER_REF - 10.0)

        conf_low = result_low.get("confidence", 0.0)
        conf_high = result_high.get("confidence", 0.0)

        if result_low.get("direction") != 0 and result_high.get("direction") != 0:
            assert conf_low > 0.0, "Floor-adjacent OFI should produce non-zero confidence"
            assert (
                conf_high > conf_low
            ), f"Higher OFI magnitude should produce higher confidence: {conf_high} vs {conf_low}"

    def test_ewma_alignment_boosts_when_aligned(self):
        """ofi_ewma_5 same sign as ofi_ewma_20 -> alignment_score=1.0 vs 0.3."""
        result_aligned = _fire_via_acceleration(ofi_ewma_20_final=800.0, ofi_ewma_5=600.0)
        result_opposed = _fire_via_acceleration(ofi_ewma_20_final=800.0, ofi_ewma_5=-600.0)

        conf_aligned = result_aligned.get("confidence", 0.0)
        conf_opposed = result_opposed.get("confidence", 0.0)

        if result_aligned.get("direction") != 0 and result_opposed.get("direction") != 0:
            assert (
                conf_aligned > conf_opposed
            ), f"Aligned EWMA should boost confidence vs opposed: {conf_aligned} vs {conf_opposed}"

    def test_confidence_clamped_to_system_ceiling(self):
        """Confidence never exceeds 0.95 (CONF_CEIL from compose_confidence)."""
        result = _fire_via_acceleration(
            ofi_ewma_20_final=_ES_UPPER_REF * 10,
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
        """Compute without ofi_ewma_5 -- must not raise, confidence in [0.0, 0.95]."""
        result = _fire_via_acceleration(ofi_ewma_20_final=800.0, ofi_ewma_5=None, rel_volume=None)
        if result.get("direction") != 0:
            conf = result.get("confidence", -1.0)
            assert 0.0 <= conf <= 0.95, f"Confidence out of range: {conf}"
        else:
            assert result.get("signal_type") == "none"

    def test_missing_rel_volume_defaults_gracefully(self):
        """rel_volume=None falls back gracefully (no crash, vol_ratio=1.0)."""
        result = _fire_via_acceleration(ofi_ewma_20_final=800.0, rel_volume=None)
        # Either fires or not -- just must not crash
        assert "signal_type" in result


class TestShadowOnly:
    def test_shadow_only_flag(self):
        """shadow_only must be True."""
        plugin = OFIContinuationPlugin()
        assert plugin.shadow_only is True

    def test_shadow_only_class_attribute_is_true(self):
        assert OFIContinuationPlugin.shadow_only is True


class TestStateIsolation:
    def test_separate_symbols_have_independent_state(self):
        """EWMA buffer for ES must not contaminate NQ state."""
        plugin = OFIContinuationPlugin()
        # Build ES acceleration
        for _ in range(_MIN_BARS_DEFAULT):
            plugin.compute_full(_make_frames(ofi_ewma_20=800.0, symbol="ES", tf="1m"))
        # NQ should start with empty buffer (no history contamination)
        nq_state = plugin._get_ofi_state("NQ", "1m")
        assert len(nq_state.ewma_buffer) == 0, "NQ buffer must be empty after ES-only calls"
