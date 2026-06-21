"""Unit tests for trad_CVDDivergence — Phase 118 intrinsic gradient confidence refactor.

Tests cover:
- Threshold gate (now 1.0, not 0.002)
- Confirmation bar gate (now 5, not 3)
- Continuous magnitude gradient (regression guard for the broken 125.0+2.5 divisor)
- Dual divergence boost
- Slope alignment boost
- Missing cvd_slope_5bar neutral fallback
- shadow_only flag
"""

from __future__ import annotations

import numpy as np

from src.intelligence.archive.trading_i7.cvd_divergence import (
    _CONFIRMATION_BARS,
    _CVD_DIV_THRESHOLD,
    _CVD_DIV_UPPER_REF,
    CVDDivergencePlugin,
)
from tests.unit.intelligence.helpers import make_ohlcv

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_frames(
    cvd_divergence: float,
    count: int = 1,
    cvd_slope_5bar: float | None = -200.0,
    ofi_divergence: float = 0.0,
    atr: float = 2.0,
    symbol: str = "ES",
    tf: str = "1m",
) -> dict:
    """Build a frames dict that fires CVDDivergence after `count` calls."""
    n = 30
    closes = np.linspace(5000.0, 5010.0, n)
    df = make_ohlcv(closes)
    features: dict = {
        "cvd_divergence": cvd_divergence,
        "ofi_divergence": ofi_divergence,
        "atr_14": atr,
    }
    if cvd_slope_5bar is not None:
        features["cvd_slope_5bar"] = cvd_slope_5bar
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


def _fire_n(plugin: CVDDivergencePlugin, frames: dict, n: int) -> dict:
    """Call compute_full n times; return the last result."""
    result: dict = {}
    for _ in range(n):
        result = plugin.compute_full(frames)
    return result


def _confidence_at(cvd_div: float) -> float:
    """Return confidence for a fired CVD divergence signal with given magnitude."""
    plugin = CVDDivergencePlugin()
    frames = _make_frames(cvd_divergence=cvd_div, cvd_slope_5bar=abs(cvd_div))
    result = _fire_n(plugin, frames, _CONFIRMATION_BARS)
    return result.get("confidence", 0.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestThresholdGate:
    """Verify the threshold gate at _CVD_DIV_THRESHOLD."""

    def test_threshold_gate_rejects_below_threshold(self):
        """cvd_divergence magnitude below _CVD_DIV_THRESHOLD must not fire."""
        below = _CVD_DIV_THRESHOLD * 0.5  # safely below
        plugin = CVDDivergencePlugin()
        frames = _make_frames(cvd_divergence=below)
        result = _fire_n(plugin, frames, _CONFIRMATION_BARS + 2)
        assert (
            result.get("direction", 0) == 0
        ), f"Expected no-signal for cvd_div={below} < threshold={_CVD_DIV_THRESHOLD}"

    def test_threshold_gate_accepts_above_threshold(self):
        """cvd_divergence magnitude above threshold with count >= 5 must fire."""
        above = _CVD_DIV_THRESHOLD + 0.1
        plugin = CVDDivergencePlugin()
        frames = _make_frames(cvd_divergence=above)
        result = _fire_n(plugin, frames, _CONFIRMATION_BARS)
        assert (
            result.get("direction", 0) != 0
        ), f"Expected signal for cvd_div={above} >= threshold={_CVD_DIV_THRESHOLD}"


class TestConfirmationBarGate:
    """Verify the confirmation bar gate at _CONFIRMATION_BARS=5."""

    def test_confirmation_bars_gate_rejects_low_count(self):
        """count = 3 (below raised bar requirement of 5) must not fire."""
        above = _CVD_DIV_THRESHOLD + 0.1
        plugin = CVDDivergencePlugin()
        frames = _make_frames(cvd_divergence=above)
        # 3 calls — old threshold but below new requirement of 5
        result = _fire_n(plugin, frames, 3)
        assert (
            result.get("direction", 0) == 0
        ), f"Expected no-signal at count=3 (bar gate is {_CONFIRMATION_BARS})"

    def test_confirmation_bars_gate_accepts_count_5(self):
        """count = 5 (exactly at threshold) must fire."""
        above = _CVD_DIV_THRESHOLD + 0.1
        plugin = CVDDivergencePlugin()
        frames = _make_frames(cvd_divergence=above)
        result = _fire_n(plugin, frames, _CONFIRMATION_BARS)
        assert result.get("direction", 0) != 0, f"Expected signal at count={_CONFIRMATION_BARS}"


class TestMagnitudeGradient:
    """Regression tests for the continuous magnitude gradient.

    The broken 125.0+2.5 divisor compressed all divergences to near-zero confidence.
    The corrected formula uses the empirical (threshold, upper_ref) range:
    div_mag_score = clamp01((abs(cvd_div) - threshold) / (upper_ref - threshold))
    """

    def test_magnitude_gradient_is_continuous_not_step(self):
        """Confidence must rise monotonically from threshold to upper_ref and beyond."""
        # Sample 4 magnitude points: at threshold, midpoint, upper_ref, above upper_ref
        magnitudes = [
            _CVD_DIV_THRESHOLD,  # div_mag_score = 0.0
            (_CVD_DIV_THRESHOLD + _CVD_DIV_UPPER_REF) / 2,  # midpoint
            _CVD_DIV_UPPER_REF,  # div_mag_score = 1.0 (capped)
            _CVD_DIV_UPPER_REF + 0.5,  # beyond upper_ref (still capped at 1.0)
        ]
        confidences = [_confidence_at(m) for m in magnitudes]

        # Must be non-decreasing
        for i in range(len(confidences) - 1):
            assert confidences[i] <= confidences[i + 1] + 1e-6, (
                f"Confidence not non-decreasing at index {i}: "
                f"{magnitudes[i]:.2f}->{confidences[i]:.4f} vs "
                f"{magnitudes[i+1]:.2f}->{confidences[i+1]:.4f}"
            )

        # At least two adjacent points must differ (proves gradient, not flat step)
        diffs = [confidences[i + 1] - confidences[i] for i in range(len(confidences) - 1)]
        assert any(d > 1e-4 for d in diffs), (
            f"No gradient found — all confidences flat: {confidences}. "
            "Regression: broken 125.0+2.5 divisor would cause this."
        )

    def test_confidence_at_threshold_is_minimum(self):
        """At exactly threshold magnitude, div_mag_score=0 so confidence should be minimum."""
        conf_at_threshold = _confidence_at(_CVD_DIV_THRESHOLD)
        conf_at_upper_ref = _confidence_at(_CVD_DIV_UPPER_REF)
        assert conf_at_upper_ref > conf_at_threshold, (
            f"confidence at upper_ref ({conf_at_upper_ref:.4f}) must exceed "
            f"confidence at threshold ({conf_at_threshold:.4f})"
        )

    def test_confidence_at_upper_ref_is_near_maximum(self):
        """At upper_ref magnitude, div_mag_score=1.0 — confidence must be clearly higher than threshold."""
        conf_at_upper_ref = _confidence_at(_CVD_DIV_UPPER_REF)
        conf_at_threshold = _confidence_at(_CVD_DIV_THRESHOLD)
        gap = conf_at_upper_ref - conf_at_threshold
        assert gap > 0.10, (
            f"Confidence gap between upper_ref and threshold is {gap:.4f} — too small. "
            "Expected > 0.10 (40% weight on div_mag factor)."
        )


class TestDualDivergence:
    """Verify dual divergence boosts confidence."""

    def test_dual_divergence_boosts_confidence(self):
        """dual_divergence=True vs False with same magnitude → dual case has higher confidence."""
        cvd_div = _CVD_DIV_UPPER_REF  # full divergence
        ofi_dual = _CVD_DIV_UPPER_REF  # both diverging (dual = True)
        ofi_none = 0.0  # OFI not diverging (dual = False)

        plugin_dual = CVDDivergencePlugin()
        plugin_no_dual = CVDDivergencePlugin()

        frames_dual = _make_frames(
            cvd_divergence=cvd_div, ofi_divergence=ofi_dual, cvd_slope_5bar=None
        )
        frames_no_dual = _make_frames(
            cvd_divergence=cvd_div, ofi_divergence=ofi_none, cvd_slope_5bar=None
        )

        result_dual = _fire_n(plugin_dual, frames_dual, _CONFIRMATION_BARS)
        result_no_dual = _fire_n(plugin_no_dual, frames_no_dual, _CONFIRMATION_BARS)

        assert result_dual.get("direction", 0) != 0, "dual case must fire"
        assert result_no_dual.get("direction", 0) != 0, "no-dual case must fire"
        assert result_dual["confidence"] > result_no_dual["confidence"], (
            f"dual({result_dual['confidence']:.4f}) must exceed "
            f"no-dual({result_no_dual['confidence']:.4f})"
        )


class TestSlopeAlignment:
    """Verify slope alignment affects confidence."""

    def test_slope_alignment_boosts_confidence(self):
        """Aligned slope vs opposing slope with same magnitude → aligned has higher confidence."""
        cvd_div = _CVD_DIV_UPPER_REF  # full divergence (positive)
        aligned_slope = 100.0  # same sign as cvd_div → slope_score=1.0
        opposing_slope = -100.0  # opposite sign → slope_score=0.2

        plugin_aligned = CVDDivergencePlugin()
        plugin_opposing = CVDDivergencePlugin()

        frames_aligned = _make_frames(cvd_divergence=cvd_div, cvd_slope_5bar=aligned_slope)
        frames_opposing = _make_frames(cvd_divergence=cvd_div, cvd_slope_5bar=opposing_slope)

        result_aligned = _fire_n(plugin_aligned, frames_aligned, _CONFIRMATION_BARS)
        result_opposing = _fire_n(plugin_opposing, frames_opposing, _CONFIRMATION_BARS)

        assert result_aligned.get("direction", 0) != 0, "aligned case must fire"
        assert result_opposing.get("direction", 0) != 0, "opposing case must fire"
        assert result_aligned["confidence"] > result_opposing["confidence"], (
            f"aligned({result_aligned['confidence']:.4f}) must exceed "
            f"opposing({result_opposing['confidence']:.4f})"
        )

    def test_missing_cvd_slope_uses_neutral_fallback(self):
        """cvd_slope_5bar absent from features → neutral 0.5 fallback, no crash, valid signal."""
        cvd_div = _CVD_DIV_UPPER_REF
        plugin = CVDDivergencePlugin()
        # cvd_slope_5bar=None → key omitted from features dict
        frames = _make_frames(cvd_divergence=cvd_div, cvd_slope_5bar=None)
        result = _fire_n(plugin, frames, _CONFIRMATION_BARS)

        assert result.get("direction", 0) != 0, "Must fire even with missing slope key"
        conf = result.get("confidence", 0.0)
        assert 0.0 < conf <= 0.95, f"Confidence must be in (0, 0.95], got {conf}"

    def test_missing_slope_confidence_between_aligned_and_opposing(self):
        """Neutral fallback (0.5) must produce confidence between aligned (1.0) and opposing (0.2)."""
        cvd_div = _CVD_DIV_UPPER_REF

        plugin_aligned = CVDDivergencePlugin()
        plugin_neutral = CVDDivergencePlugin()
        plugin_opposing = CVDDivergencePlugin()

        conf_aligned = _fire_n(
            plugin_aligned,
            _make_frames(cvd_divergence=cvd_div, cvd_slope_5bar=100.0),
            _CONFIRMATION_BARS,
        ).get("confidence", 0.0)
        conf_neutral = _fire_n(
            plugin_neutral,
            _make_frames(cvd_divergence=cvd_div, cvd_slope_5bar=None),
            _CONFIRMATION_BARS,
        ).get("confidence", 0.0)
        conf_opposing = _fire_n(
            plugin_opposing,
            _make_frames(cvd_divergence=cvd_div, cvd_slope_5bar=-100.0),
            _CONFIRMATION_BARS,
        ).get("confidence", 0.0)

        assert conf_opposing < conf_neutral < conf_aligned, (
            f"Expected opposing({conf_opposing:.4f}) < neutral({conf_neutral:.4f}) "
            f"< aligned({conf_aligned:.4f})"
        )


class TestShadowOnlyFlag:
    """Verify shadow_only is set on the plugin class."""

    def test_shadow_only_flag(self):
        """Plugin must have shadow_only=True (Phase 118: shadow mode until promotion)."""
        plugin = CVDDivergencePlugin()
        assert plugin.shadow_only is True, "CVDDivergencePlugin.shadow_only must be True"
