"""Tests for CIS weight updater."""

from __future__ import annotations

import json

from src.intelligence.trading.cis_scorer import BOOTSTRAP_WEIGHTS, BUCKET_NAMES
from src.intelligence.weight_updater import (
    MIN_SAMPLES_FULL,
    MIN_SAMPLES_TRAIN,
    compute_new_weights,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signal(
    quality: float,
    trend: float = 0.3,
    momentum: float = 0.2,
    structure: float = 0.1,
    pattern: float = 0.05,
    institutional: float = 0.25,
    regime: float = 0.1,
) -> dict:
    return {
        "bucket_scores": {
            "trend": trend,
            "momentum": momentum,
            "structure": structure,
            "pattern": pattern,
            "institutional": institutional,
            "regime": regime,
        },
        "signal_quality": quality,
    }


def _varied_signals(n: int) -> list[dict]:
    """Generate n signals with varied quality (cycles 0.0 / 0.5 / 1.0)."""
    return [_make_signal(float(i % 3) * 0.5) for i in range(n)]


# ---------------------------------------------------------------------------
# Tests: compute_new_weights
# ---------------------------------------------------------------------------


class TestComputeNewWeights:
    def test_returns_none_below_min_samples(self):
        """Under 50 samples → no retraining → None."""
        signals = _varied_signals(MIN_SAMPLES_TRAIN - 1)
        assert compute_new_weights(signals) is None

    def test_returns_none_with_zero_samples(self):
        assert compute_new_weights([]) is None

    def test_returns_blended_at_50_to_99_samples(self):
        """50-99 samples → blend mode."""
        signals = _varied_signals(75)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.weights_type == "blended"
        assert result.did_retrain is True

    def test_returns_blended_exactly_at_50(self):
        signals = _varied_signals(MIN_SAMPLES_TRAIN)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.weights_type == "blended"

    def test_returns_learned_at_100_plus_samples(self):
        """100+ samples → learned weights."""
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.weights_type == "learned"

    def test_returns_learned_exactly_at_100(self):
        signals = _varied_signals(MIN_SAMPLES_FULL)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.weights_type == "learned"

    def test_weights_sum_to_one_learned(self):
        """Learned weights must sum to 1.0 (within floating-point tolerance)."""
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 1e-6, f"Weights sum to {total}"

    def test_weights_sum_to_one_blended(self):
        """Blended weights must also sum to 1.0."""
        signals = _varied_signals(75)
        result = compute_new_weights(signals)
        assert result is not None
        total = sum(result.weights.values())
        assert abs(total - 1.0) < 1e-6, f"Weights sum to {total}"

    def test_all_weights_above_minimum_learned(self):
        """Each bucket weight >= 0.05 (MIN_WEIGHT)."""
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        for bucket, w in result.weights.items():
            assert w >= 0.05, f"Bucket {bucket} weight {w} below minimum 0.05"

    def test_all_weights_above_minimum_blended(self):
        signals = _varied_signals(75)
        result = compute_new_weights(signals)
        assert result is not None
        for bucket, w in result.weights.items():
            assert w >= 0.05, f"Bucket {bucket} weight {w} below minimum 0.05"

    def test_all_6_buckets_present(self):
        """Result must contain all BUCKET_NAMES keys."""
        signals = _varied_signals(120)
        result = compute_new_weights(signals)
        assert result is not None
        assert set(result.weights.keys()) == set(BUCKET_NAMES)

    def test_blended_contains_all_buckets(self):
        signals = _varied_signals(75)
        result = compute_new_weights(signals)
        assert result is not None
        assert set(result.weights.keys()) == set(BUCKET_NAMES)

    def test_n_resolved_correct(self):
        """n_resolved must equal count of valid input signals."""
        signals = _varied_signals(55)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.n_resolved == 55

    def test_n_resolved_correct_at_100(self):
        signals = _varied_signals(100)
        result = compute_new_weights(signals)
        assert result is not None
        assert result.n_resolved == 100

    def test_signal_quality_mean_computed(self):
        """signal_quality_mean should be the mean of all signal_quality values."""
        # All quality=1.0 but varied bucket scores to avoid degenerate target
        signals = []
        for i in range(60):
            quality = 1.0 if i % 2 == 0 else 0.0
            signals.append(_make_signal(quality=quality))
        result = compute_new_weights(signals)
        assert result is not None
        assert abs(result.signal_quality_mean - 0.5) < 1e-6

    def test_bucket_scores_as_json_string(self):
        """bucket_scores may arrive as a JSON string from asyncpg JSONB rows."""
        bs = json.dumps(
            {
                "trend": 0.4,
                "momentum": 0.3,
                "structure": 0.2,
                "pattern": 0.05,
                "institutional": 0.2,
                "regime": 0.15,
            }
        )
        signals_a = [{"bucket_scores": bs, "signal_quality": 1.5}] * 30
        signals_b = [{"bucket_scores": bs, "signal_quality": 0.2}] * 30
        result = compute_new_weights(signals_a + signals_b)
        # Should succeed (60 samples, non-degenerate due to two quality values)
        assert result is not None
        assert abs(sum(result.weights.values()) - 1.0) < 1e-6

    def test_returns_none_with_degenerate_target(self):
        """All identical quality → all below-mean or all above-mean → None."""
        # quality=1.0 for all: all >= mean(1.0) → y all 1 → degenerate
        signals = [_make_signal(quality=1.0) for _ in range(60)]
        result = compute_new_weights(signals)
        assert result is None

    def test_filters_rows_missing_signal_quality(self):
        """Rows without signal_quality are filtered out."""
        valid = _varied_signals(60)
        missing = [
            {
                "bucket_scores": {
                    "trend": 0.1,
                    "momentum": 0.1,
                    "structure": 0.1,
                    "pattern": 0.1,
                    "institutional": 0.1,
                    "regime": 0.1,
                }
            }
            for _ in range(20)
        ]
        result = compute_new_weights(valid + missing)
        # Only 60 valid rows — should retrain if non-degenerate
        if result is not None:
            assert result.n_resolved == 60

    def test_filters_rows_missing_bucket_scores(self):
        """Rows without bucket_scores are filtered out."""
        valid = _varied_signals(60)
        missing = [{"bucket_scores": None, "signal_quality": 0.5} for _ in range(20)]
        result = compute_new_weights(valid + missing)
        if result is not None:
            assert result.n_resolved == 60

    def test_returns_none_exactly_49_samples(self):
        """49 valid rows → below threshold → None."""
        assert compute_new_weights(_varied_signals(49)) is None

    def test_blended_weights_higher_than_minimum(self):
        """Blended weights: all >= 0.05 (clips applied after 70/30 blend)."""
        signals = [_make_signal(1.0 if i % 2 == 0 else 0.0) for i in range(75)]
        result = compute_new_weights(signals)
        assert result is not None and result.weights_type == "blended"
        for b in BUCKET_NAMES:
            assert result.weights[b] >= 0.05

    def test_bootstrap_weights_referenced_correctly(self):
        """BOOTSTRAP_WEIGHTS sum to 1.0 — sanity check for the designed fallback."""
        total = sum(BOOTSTRAP_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9
