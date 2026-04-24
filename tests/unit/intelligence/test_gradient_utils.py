"""Unit tests for src/intelligence/utils/gradient_utils.py.

TDD RED phase: tests for 8 canonical gradient functions covering boundaries,
midpoints, edge cases (NaN, zero, negative), and gradient continuity.
"""

from __future__ import annotations

import math

import pytest

from src.intelligence.utils.gradient_utils import (
    freshness_decay,
    hmm_regime_weight,
    linear_ramp,
    session_progress,
    sigmoid_score,
    streak_score,
    threshold_decay,
    z_score_to_score,
)


# ---------------------------------------------------------------------------
# linear_ramp
# ---------------------------------------------------------------------------


class TestLinearRamp:
    """Tests for linear_ramp(x, lo, hi, out_lo=0.0, out_hi=1.0)."""

    @pytest.mark.parametrize(
        "x, lo, hi, expected",
        [
            (50, 30, 70, 0.5),   # midpoint
            (30, 30, 70, 0.0),   # at lo boundary
            (70, 30, 70, 1.0),   # at hi boundary
            (10, 30, 70, 0.0),   # below lo, clamped
            (90, 30, 70, 1.0),   # above hi, clamped
        ],
    )
    def test_boundary_and_midpoint(self, x, lo, hi, expected):
        assert linear_ramp(x, lo, hi) == pytest.approx(expected)

    def test_custom_output_range(self):
        """linear_ramp remaps to custom output range [out_lo, out_hi]."""
        result = linear_ramp(50, 30, 70, out_lo=0.3, out_hi=0.9)
        assert result == pytest.approx(0.6)  # midpoint of [0.3, 0.9]

    def test_mid_range_gradient_continuity(self):
        """Mid-range input produces output strictly between 0 and 1 (not binary)."""
        result = linear_ramp(45, 30, 70)
        assert 0.0 < result < 1.0

    def test_equal_bounds(self):
        """When lo == hi, output is out_hi (fully in range)."""
        assert linear_ramp(10, 10, 10) == 1.0
        assert linear_ramp(5, 10, 10) == 0.0

    def test_negative_range(self):
        """Works with negative input ranges."""
        assert linear_ramp(-5, -10, 0) == pytest.approx(0.5)

    def test_nan_input(self):
        """NaN input should not crash; returns out_lo (safe fallback)."""
        result = linear_ramp(float("nan"), 30, 70)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# threshold_decay
# ---------------------------------------------------------------------------


class TestThresholdDecay:
    """Tests for threshold_decay(x, center, width, peak=1.0, floor=0.0)."""

    def test_at_center(self):
        """Peaks at center."""
        assert threshold_decay(50, 50, 10) == pytest.approx(1.0)

    def test_far_from_center(self):
        """Floor when far from center."""
        assert threshold_decay(70, 50, 10) == pytest.approx(0.0)

    def test_mid_range_gradient(self):
        """Mid-range produces gradient between floor and peak."""
        result = threshold_decay(55, 50, 10)
        assert 0.0 < result < 1.0

    def test_at_edge_of_width(self):
        """At exactly center +/- width, decay is zero."""
        assert threshold_decay(60, 50, 10) == pytest.approx(0.0)
        assert threshold_decay(40, 50, 10) == pytest.approx(0.0)

    def test_custom_peak_and_floor(self):
        """Custom peak and floor values."""
        result = threshold_decay(50, 50, 10, peak=0.8, floor=0.2)
        assert result == pytest.approx(0.8)

    def test_half_width_gives_half_peak(self):
        """At half-width distance, decay is half the peak."""
        result = threshold_decay(55, 50, 10)
        assert result == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# sigmoid_score
# ---------------------------------------------------------------------------


class TestSigmoidScore:
    """Tests for sigmoid_score(x, center, steepness=1.0)."""

    def test_at_center(self):
        """Inflection point returns 0.5."""
        assert sigmoid_score(50, 50) == pytest.approx(0.5)

    def test_below_center(self):
        """Below center produces value between 0 and 0.5."""
        result = sigmoid_score(49, 50)
        assert 0.0 < result < 0.5

    def test_above_center(self):
        """Above center produces value between 0.5 and 1.0."""
        result = sigmoid_score(51, 50)
        assert 0.5 < result < 1.0

    def test_mid_range_gradient_continuity(self):
        """Mid-range input is strictly not 0.0 or 1.0."""
        result = sigmoid_score(0, 0, steepness=1.0)
        assert 0.0 < result < 1.0

    def test_steepness_controls_sharpness(self):
        """Higher steepness compresses the sigmoid."""
        low_steep = sigmoid_score(1, 0, steepness=0.5)
        high_steep = sigmoid_score(1, 0, steepness=5.0)
        # High steepness should be closer to 1.0 at x=1
        assert high_steep > low_steep

    def test_extreme_positive(self):
        """Very large positive x approaches 1.0."""
        assert sigmoid_score(100, 0) == pytest.approx(1.0, abs=1e-10)

    def test_extreme_negative(self):
        """Very large negative x approaches 0.0."""
        assert sigmoid_score(-100, 0) == pytest.approx(0.0, abs=1e-10)


# ---------------------------------------------------------------------------
# z_score_to_score
# ---------------------------------------------------------------------------


class TestZScoreToScore:
    """Tests for z_score_to_score(z, sigma_scale=2.0)."""

    def test_zero_z(self):
        """No deviation produces 0.0."""
        assert z_score_to_score(0.0) == pytest.approx(0.0)

    def test_extreme_clamped(self):
        """Extreme z-score clamped to 1.0."""
        assert z_score_to_score(4.0, sigma_scale=2.0) == pytest.approx(1.0)

    def test_mid_range_gradient(self):
        """Mid-range z-score produces gradient between 0 and 1."""
        result = z_score_to_score(2.5, sigma_scale=2.0)
        assert 0.0 < result < 1.0

    def test_negative_z_absolute(self):
        """Negative z-score uses absolute value."""
        assert z_score_to_score(-2.0, sigma_scale=2.0) == pytest.approx(1.0)

    def test_at_sigma_scale(self):
        """At exactly sigma_scale, returns 1.0."""
        assert z_score_to_score(2.0, sigma_scale=2.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# session_progress
# ---------------------------------------------------------------------------


class TestSessionProgress:
    """Tests for session_progress(elapsed_frac, start_frac, end_frac)."""

    def test_session_midpoint(self):
        """Midpoint of session returns 1.0."""
        assert session_progress(0.5, 0.0, 1.0) == pytest.approx(1.0)

    def test_session_start(self):
        """Session start returns 0.0."""
        assert session_progress(0.0, 0.0, 1.0) == pytest.approx(0.0)

    def test_session_end(self):
        """Session end returns 0.0."""
        assert session_progress(1.0, 0.0, 1.0) == pytest.approx(0.0)

    def test_quarter_through(self):
        """Quarter through session produces value between 0 and 1."""
        result = session_progress(0.25, 0.0, 1.0)
        assert 0.0 < result < 1.0

    def test_outside_window(self):
        """Outside the session window returns 0.0."""
        assert session_progress(-0.1, 0.0, 1.0) == pytest.approx(0.0)
        assert session_progress(1.1, 0.0, 1.0) == pytest.approx(0.0)

    def test_mid_range_gradient_continuity(self):
        """Quarter-through is gradient, not binary."""
        result = session_progress(0.25, 0.0, 1.0)
        assert 0.0 < result < 1.0


# ---------------------------------------------------------------------------
# hmm_regime_weight
# ---------------------------------------------------------------------------


class TestHmmRegimeWeight:
    """Tests for hmm_regime_weight(features, regime_direction)."""

    def test_trending_up(self):
        assert hmm_regime_weight({"hmm_prob_trending_up": 0.8}, "up") == pytest.approx(0.8)

    def test_ranging(self):
        assert hmm_regime_weight({"hmm_prob_ranging": 0.6}, "ranging") == pytest.approx(0.6)

    def test_trending_down(self):
        assert hmm_regime_weight({"hmm_prob_trending_down": 0.7}, "down") == pytest.approx(0.7)

    def test_missing_features_fallback(self):
        """Missing HMM features fall back to 0.5 (neutral)."""
        assert hmm_regime_weight({}, "up") == pytest.approx(0.5)

    def test_clamped_to_unit_range(self):
        """Values outside [0, 1] are clamped."""
        result = hmm_regime_weight({"hmm_prob_trending_up": 1.5}, "up")
        assert result == pytest.approx(1.0)
        result = hmm_regime_weight({"hmm_prob_trending_up": -0.3}, "up")
        assert result == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# freshness_decay
# ---------------------------------------------------------------------------


class TestFreshnessDecay:
    """Tests for freshness_decay(touch_count, k=0.5)."""

    def test_untouched(self):
        """Zero touches = fully fresh (1.0)."""
        assert freshness_decay(0) == pytest.approx(1.0)

    def test_one_touch(self):
        """One touch with k=0.5: exp(-0.5) approx 0.607."""
        assert freshness_decay(1, k=0.5) == pytest.approx(math.exp(-0.5))

    def test_many_touches_stale(self):
        """Many touches = nearly stale."""
        assert freshness_decay(5, k=0.5) < 0.1

    def test_mid_range_gradient_continuity(self):
        """Mid-range touch count produces output strictly between 0 and 1."""
        result = freshness_decay(2, k=0.5)
        assert 0.0 < result < 1.0

    def test_zero_decay_rate(self):
        """k=0 means no decay, always 1.0."""
        assert freshness_decay(10, k=0.0) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# streak_score
# ---------------------------------------------------------------------------


class TestStreakScore:
    """Tests for streak_score(streak_count, saturation=5)."""

    def test_no_streak(self):
        """Zero streak produces 0.0."""
        assert streak_score(0) == pytest.approx(0.0)

    def test_at_saturation(self):
        """At saturation, produces 1.0."""
        assert streak_score(5, saturation=5) == pytest.approx(1.0)

    def test_mid_range_gradient(self):
        """Mid-range streak produces output between 0 and 1."""
        result = streak_score(3, saturation=5)
        assert 0.0 < result < 1.0

    def test_beyond_saturation_clamped(self):
        """Beyond saturation, clamped to 1.0."""
        assert streak_score(10, saturation=5) == pytest.approx(1.0)

    def test_mid_range_not_binary(self):
        """Mid-range output is strictly not 0.0 or 1.0."""
        result = streak_score(2, saturation=5)
        assert 0.0 < result < 1.0


# ---------------------------------------------------------------------------
# Gradient continuity: no binary outputs for mid-range inputs
# ---------------------------------------------------------------------------


class TestGradientContinuity:
    """Assert that no function produces binary {0.0, 1.0} outputs for mid-range inputs.

    This is the Renaissance principle: never destroy gradient information.
    """

    def test_linear_ramp_continuity(self):
        result = linear_ramp(45, 30, 70)
        assert 0.0 < result < 1.0

    def test_threshold_decay_continuity(self):
        result = threshold_decay(54, 50, 10)
        assert 0.0 < result < 1.0

    def test_sigmoid_continuity(self):
        result = sigmoid_score(0.5, 0.0)
        assert 0.0 < result < 1.0

    def test_z_score_continuity(self):
        result = z_score_to_score(1.5, sigma_scale=2.0)
        assert 0.0 < result < 1.0

    def test_session_progress_continuity(self):
        result = session_progress(0.25, 0.0, 1.0)
        assert 0.0 < result < 1.0

    def test_freshness_continuity(self):
        result = freshness_decay(3, k=0.5)
        assert 0.0 < result < 1.0

    def test_streak_continuity(self):
        result = streak_score(2, saturation=5)
        assert 0.0 < result < 1.0
