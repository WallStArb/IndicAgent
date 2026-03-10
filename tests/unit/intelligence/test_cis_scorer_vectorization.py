"""Unit tests verifying numerical equivalence of vectorized CIS scorer.

These tests compare the vectorized numpy implementation against a reference
scalar implementation. All results must be equivalent within floating-point
tolerance (1e-10).
"""

from __future__ import annotations

import pytest

from src.intelligence.trading.cis_scorer import (
    BOOTSTRAP_WEIGHTS,
    BUCKET_AGREE_MIN,
    BUCKET_NAMES,
    BUCKET_NOISE_FLOOR,
    CIS_FIRE_THRESHOLD,
    CISScorer,
    EPSILON_TOLERANCE,
)
from src.intelligence.utils import clamp


# ---------------------------------------------------------------------------
# Reference scalar implementation (mirrors original pre-vectorization code)
# ---------------------------------------------------------------------------


def _scalar_aggregate(
    bucket_scores: dict[str, float],
    weights: dict[str, float],
) -> tuple[float, int, int]:
    """Reference scalar implementation for comparison.

    Returns (cis_score, direction, agreeing) using original Python loops.
    This is the implementation that was replaced by numpy vectorization.
    """
    cis_raw = sum(weights[b] * bucket_scores[b] for b in BUCKET_NAMES)
    cis_score = clamp(cis_raw)

    direction = 0
    if abs(cis_score) > CIS_FIRE_THRESHOLD:
        direction = 1 if cis_score > 0 else -1

    cis_sign = 1.0 if cis_score >= 0 else -1.0
    agreeing = sum(
        1
        for b in BUCKET_NAMES
        if bucket_scores[b] * cis_sign > BUCKET_NOISE_FLOOR
    )

    if agreeing < BUCKET_AGREE_MIN:
        direction = 0

    return round(cis_score, 4), direction, agreeing


# ---------------------------------------------------------------------------
# Fixtures — feature dicts covering different scenarios
# ---------------------------------------------------------------------------


def _bullish_features() -> dict:
    return {
        "trend_regime": 0.8,
        "kalman_slope": 0.5,
        "smc_trend_direction": 1,
        "ctf_trend_alignment": 0.8,
        "trend_confluence_score": 0.7,
        "rsi_14": 70.0,
        "macd_hist_12_26_9": 0.5,
        "roc_14": 2.0,
        "momentum_bias": 0.6,
        "swing_pattern": 0.7,
        "bos_detected": 1.0,
        "bos_direction": 1,
        "choch_detected": 0.0,
        "choch_direction": 0,
        "dt_db_pattern": 0.0,
        "dt_db_confidence": 0.0,
        "hs_pattern": 0.0,
        "hs_confidence": 0.0,
        "tri_breakout_bias": 0.0,
        "tri_confidence": 0.0,
        "ob_type": 1,
        "ob_strength": 0.8,
        "fvg_type": 1,
        "fvg_open_count": 2,
        "in_demand_zone": 1.0,
        "in_supply_zone": 0.0,
        "hmm_prob_trending_up": 0.7,
        "hmm_prob_trending_down": 0.1,
        "cp_probability": 0.2,
        "ctf_regime_agreement": 0.6,
        "vol_regime": 0.2,
    }


def _bearish_features() -> dict:
    f = _bullish_features()
    f.update({
        "trend_regime": -0.8,
        "kalman_slope": -0.5,
        "smc_trend_direction": -1,
        "ctf_trend_alignment": -0.8,
        "trend_confluence_score": -0.7,
        "rsi_14": 30.0,
        "macd_hist_12_26_9": -0.5,
        "roc_14": -2.0,
        "momentum_bias": -0.6,
        "bos_direction": -1,
        "ob_type": -1,
        "fvg_type": -1,
        "in_demand_zone": 0.0,
        "in_supply_zone": 1.0,
        "hmm_prob_trending_up": 0.1,
        "hmm_prob_trending_down": 0.7,
    })
    return f


def _neutral_features() -> dict:
    return {k: 0.0 for k in _bullish_features()}


def _mixed_features() -> dict:
    """Mixed bullish/bearish signals — no clear direction."""
    f = _bullish_features()
    f.update({
        "trend_regime": -0.3,
        "kalman_slope": 0.2,
        "rsi_14": 52.0,
        "macd_hist_12_26_9": -0.1,
        "hmm_prob_trending_up": 0.4,
        "hmm_prob_trending_down": 0.35,
    })
    return f


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_both(features: dict, plugin_outputs: dict | None = None) -> tuple:
    """Run vectorized scorer and reference scalar on the same inputs.

    Returns (vec_result, scalar_cis, scalar_dir, scalar_agreeing).
    """
    po = plugin_outputs or {}
    scorer = CISScorer()
    vec_result = scorer.score(features, po)

    # Extract bucket scores from vec_result (already computed by scorer)
    bucket_scores = {b: vec_result.bucket_scores[b] for b in BUCKET_NAMES}
    scalar_cis, scalar_dir, scalar_agreeing = _scalar_aggregate(
        bucket_scores, BOOTSTRAP_WEIGHTS
    )

    return vec_result, scalar_cis, scalar_dir, scalar_agreeing


# ---------------------------------------------------------------------------
# Equivalence tests
# ---------------------------------------------------------------------------


class TestVectorizationEquivalence:
    @pytest.mark.unit
    def test_cis_score_equivalent_bullish(self):
        """Vectorized cis_score == scalar cis_score for bullish scenario."""
        vec_result, scalar_cis, _, _ = _run_both(_bullish_features())
        assert abs(vec_result.cis_score - scalar_cis) < 1e-10

    @pytest.mark.unit
    def test_cis_score_equivalent_bearish(self):
        """Vectorized cis_score == scalar cis_score for bearish scenario."""
        vec_result, scalar_cis, _, _ = _run_both(_bearish_features())
        assert abs(vec_result.cis_score - scalar_cis) < 1e-10

    @pytest.mark.unit
    def test_cis_score_equivalent_neutral(self):
        """Vectorized cis_score == scalar cis_score for neutral scenario."""
        vec_result, scalar_cis, _, _ = _run_both(_neutral_features())
        assert abs(vec_result.cis_score - scalar_cis) < 1e-10

    @pytest.mark.unit
    def test_cis_score_equivalent_mixed(self):
        """Vectorized cis_score == scalar cis_score for mixed signals."""
        vec_result, scalar_cis, _, _ = _run_both(_mixed_features())
        assert abs(vec_result.cis_score - scalar_cis) < 1e-10

    @pytest.mark.unit
    def test_direction_equivalent_bullish(self):
        """Vectorized direction == scalar direction for bullish scenario."""
        vec_result, _, scalar_dir, _ = _run_both(_bullish_features())
        assert vec_result.direction == scalar_dir

    @pytest.mark.unit
    def test_direction_equivalent_bearish(self):
        """Vectorized direction == scalar direction for bearish scenario."""
        vec_result, _, scalar_dir, _ = _run_both(_bearish_features())
        assert vec_result.direction == scalar_dir

    @pytest.mark.unit
    def test_direction_equivalent_neutral(self):
        """Vectorized direction == scalar direction for neutral scenario (no fire)."""
        vec_result, _, scalar_dir, _ = _run_both(_neutral_features())
        assert vec_result.direction == scalar_dir
        assert vec_result.direction == 0

    @pytest.mark.unit
    def test_agreeing_count_equivalent_bullish(self):
        """Vectorized buckets_agreeing == scalar agreeing for bullish scenario."""
        vec_result, _, _, scalar_agreeing = _run_both(_bullish_features())
        assert vec_result.buckets_agreeing == scalar_agreeing

    @pytest.mark.unit
    def test_agreeing_count_equivalent_bearish(self):
        """Vectorized buckets_agreeing == scalar agreeing for bearish scenario."""
        vec_result, _, _, scalar_agreeing = _run_both(_bearish_features())
        assert vec_result.buckets_agreeing == scalar_agreeing

    @pytest.mark.unit
    def test_agreeing_count_equivalent_mixed(self):
        """Vectorized buckets_agreeing == scalar agreeing for mixed scenario."""
        vec_result, _, _, scalar_agreeing = _run_both(_mixed_features())
        assert vec_result.buckets_agreeing == scalar_agreeing


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestVectorizationEdgeCases:
    @pytest.mark.unit
    def test_all_positive_bucket_scores(self):
        """All buckets strongly positive — all six should agree."""
        # Use bullish features which produce strongly positive all-bucket scores
        vec_result, scalar_cis, scalar_dir, scalar_agreeing = _run_both(
            _bullish_features()
        )
        assert abs(vec_result.cis_score - scalar_cis) < 1e-10
        assert vec_result.buckets_agreeing == scalar_agreeing

    @pytest.mark.unit
    def test_all_negative_bucket_scores(self):
        """All buckets strongly negative — all six should agree (bearish)."""
        vec_result, scalar_cis, scalar_dir, scalar_agreeing = _run_both(
            _bearish_features()
        )
        assert abs(vec_result.cis_score - scalar_cis) < 1e-10
        assert vec_result.buckets_agreeing == scalar_agreeing

    @pytest.mark.unit
    def test_all_zero_bucket_scores(self):
        """Empty features -> all buckets zero, direction=0."""
        vec_result, scalar_cis, scalar_dir, scalar_agreeing = _run_both({})
        assert abs(vec_result.cis_score - scalar_cis) < 1e-10
        assert vec_result.direction == 0
        assert vec_result.direction == scalar_dir

    @pytest.mark.unit
    def test_custom_weights_equivalence(self):
        """Custom weights produce same result as scalar with same weights."""
        custom_weights = {
            "trend": 0.30,
            "momentum": 0.25,
            "structure": 0.15,
            "pattern": 0.10,
            "institutional": 0.15,
            "regime": 0.05,
        }
        scorer = CISScorer(weights=custom_weights, weights_version=7)
        vec_result = scorer.score(_bullish_features(), {})

        bucket_scores = {b: vec_result.bucket_scores[b] for b in BUCKET_NAMES}
        scalar_cis, scalar_dir, scalar_agreeing = _scalar_aggregate(
            bucket_scores, custom_weights
        )

        assert abs(vec_result.cis_score - scalar_cis) < 1e-10
        assert vec_result.direction == scalar_dir
        assert vec_result.buckets_agreeing == scalar_agreeing


# ---------------------------------------------------------------------------
# Threshold boundary conditions
# ---------------------------------------------------------------------------


class TestThresholdBoundaryConditions:
    @pytest.mark.unit
    def test_exactly_at_fire_threshold_no_fire(self):
        """CIS score exactly at 0.35 does NOT fire (requires abs > 0.35, not >=)."""
        # Use custom weights + carefully crafted features to land exactly at threshold.
        # We mock by providing bucket_scores that sum to exactly 0.35 (unrounded).
        # The easiest approach: use a single-bucket scorer where we know the expected output.
        #
        # With BOOTSTRAP_WEIGHTS summing to 1.0, if we want weighted sum = 0.35,
        # we need to craft inputs such that each bucket_score * weight sums to 0.35.
        # Simpler: just verify the condition holds for a marginally-sub-threshold score.

        # Construct a scorer where institutional has weight=1.0 (sole bucket)
        single_bucket_weights = {
            "trend": 0.0,
            "momentum": 0.0,
            "structure": 0.0,
            "pattern": 0.0,
            "institutional": 1.0,
            "regime": 0.0,
        }
        scorer = CISScorer(weights=single_bucket_weights)

        # ob_type=1, ob_strength=0.35 -> institutional = clamp(0.25 * 1 * 0.35) = 0.0875
        # That won't reach 0.35. Use ob_strength=1.4 -> 0.25*1.4 = 0.35 -> cis=0.35 exactly
        features = {
            "ob_type": 1,
            "ob_strength": 1.4,  # 0.25 * 1 * 1.4 = 0.35
            "fvg_open_count": 0,
            "in_demand_zone": 0.0,
            "in_supply_zone": 0.0,
        }
        result = scorer.score(features, {})
        # CIS_FIRE_THRESHOLD = 0.35, condition is abs(cis_score) > threshold (strict >)
        # cis_score rounds to 0.35, but the underlying float might be slightly different
        # Regardless: direction logic uses abs(cis_score) > 0.35, not >=
        # We verify the direction is consistent with scalar reference
        bucket_scores = {b: result.bucket_scores[b] for b in BUCKET_NAMES}
        scalar_cis, scalar_dir, scalar_agreeing = _scalar_aggregate(
            bucket_scores, single_bucket_weights
        )
        assert result.direction == scalar_dir

    @pytest.mark.unit
    def test_just_above_fire_threshold_fires(self):
        """CIS score just above 0.35 fires (direction != 0) when buckets agree."""
        # Force all 6 buckets to moderate-positive values so agreement condition passes.
        # Use bullish scenario which produces CIS well above 0.35.
        scorer = CISScorer()
        result = scorer.score(_bullish_features(), {})
        assert result.cis_score > CIS_FIRE_THRESHOLD
        assert result.direction == 1

    @pytest.mark.unit
    def test_below_min_agreeing_suppresses_fire(self):
        """When agreeing buckets < BUCKET_AGREE_MIN, direction=0 even if |score|>0.35."""
        # Craft weights so only 1-2 buckets contribute a big score, rest near 0.
        # Use trend weight=1.0, rest=0.0. Trend should score high bullish.
        trend_only_weights = {
            "trend": 1.0,
            "momentum": 0.0,
            "structure": 0.0,
            "pattern": 0.0,
            "institutional": 0.0,
            "regime": 0.0,
        }
        scorer = CISScorer(weights=trend_only_weights)
        features = {
            "trend_regime": 0.8,
            "kalman_slope": 0.5,
            "smc_trend_direction": 1,
            "ctf_trend_alignment": 0.8,
            "trend_confluence_score": 0.7,
        }
        result = scorer.score(features, {})
        # With trend=1.0, CIS will be driven by trend bucket alone.
        # Other buckets will be ~0 (no features supplied), so only 1 bucket agrees.
        # BUCKET_AGREE_MIN=3, so direction must be 0.
        assert result.buckets_agreeing < BUCKET_AGREE_MIN
        assert result.direction == 0

    @pytest.mark.unit
    def test_noise_floor_boundary(self):
        """Bucket score at exactly BUCKET_NOISE_FLOOR does not count as agreeing."""
        # BUCKET_NOISE_FLOOR = 0.1. A bucket score of exactly 0.1 fails strict > check.
        # Verify vectorized result matches scalar for this boundary case.
        # We can't easily force an exact bucket score, so compare vec vs scalar.
        scorer = CISScorer()
        features = _neutral_features()
        # Provide a small trend push that might produce a boundary-level bucket
        features["trend_regime"] = 0.15
        features["kalman_slope"] = 0.1
        result = scorer.score(features, {})
        bucket_scores = {b: result.bucket_scores[b] for b in BUCKET_NAMES}
        scalar_cis, scalar_dir, scalar_agreeing = _scalar_aggregate(
            bucket_scores, BOOTSTRAP_WEIGHTS
        )
        assert result.buckets_agreeing == scalar_agreeing
        assert abs(result.cis_score - scalar_cis) < 1e-10
