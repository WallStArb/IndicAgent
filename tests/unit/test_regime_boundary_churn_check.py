from __future__ import annotations

import numpy as np

from scripts.analysis.regime_boundary_churn_check import (
    WINDOW_STEP_MULTIPLIER,
    classify_timestamp_adjacency,
    derive_boundary_window,
)


def test_derive_boundary_window_scales_with_median_step():
    # Diffs: [0.01, 0.03, 0.01, 0.03, 0.01] -> median of all 5 diffs = 0.01 (three 0.01s,
    # two 0.03s) -> window = 2.0 * 0.01 = 0.02.
    series = np.array([0.10, 0.11, 0.14, 0.15, 0.18, 0.19])
    window = derive_boundary_window(series, multiplier=2.0)
    assert abs(window - 0.02) < 1e-9


def test_derive_boundary_window_empty_or_singleton_is_zero():
    assert derive_boundary_window(np.array([])) == 0.0
    assert derive_boundary_window(np.array([0.5])) == 0.0


def test_derive_boundary_window_default_multiplier_constant():
    series = np.array([0.0, 0.02, 0.04, 0.06])
    assert derive_boundary_window(series) == 0.02 * WINDOW_STEP_MULTIPLIER


_TIERS1 = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
_TIERS2 = [("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))]


def test_classify_not_adjacent_when_far_from_any_boundary():
    result = classify_timestamp_adjacency(0.50, 0.50, _TIERS1, _TIERS2, window1=0.02, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert not result.axis1_adjacent
    assert not result.axis2_adjacent
    assert result.neighbor_labels == ()


def test_classify_single_axis_adjacent():
    # sig1=0.335 is within 0.02 of the 0.33 boundary; sig2=0.50 is far from both breadth cuts.
    result = classify_timestamp_adjacency(0.335, 0.50, _TIERS1, _TIERS2, window1=0.02, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert result.axis1_adjacent
    assert not result.axis2_adjacent
    assert result.neighbor_labels == ("low_neutral",)


def test_classify_corner_case_both_axes_adjacent():
    # sig1=0.335 near the low/mid vix cut; sig2=0.605 near the neutral/bull breadth cut.
    result = classify_timestamp_adjacency(
        0.335, 0.605, _TIERS1, _TIERS2, window1=0.02, window2=0.02
    )
    assert result.actual_label == "mid_bull"
    assert result.axis1_adjacent and result.axis2_adjacent
    assert set(result.neighbor_labels) == {"low_bull", "mid_neutral", "low_neutral"}


def test_classify_narrow_middle_tier_double_adjacency_on_one_axis():
    # sig1=0.50 sits in "mid" but within 0.20 of BOTH the 0.33 and 0.67 boundaries when
    # window1 is wide -- both neighbors on axis 1 must be reported, not just one.
    result = classify_timestamp_adjacency(0.50, 0.50, _TIERS1, _TIERS2, window1=0.20, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert result.axis1_adjacent
    assert set(result.neighbor_labels) == {"low_neutral", "high_neutral"}


from scripts.analysis.regime_boundary_churn_check import align_weight_vectors, score_bar


def test_align_weight_vectors_unions_and_zero_pads():
    a = {"momentum_z_fast": 0.6, "obv_z": 0.4}
    b = {"momentum_z_fast": 0.5, "range_pct": -0.5}
    aligned = align_weight_vectors(a, b)
    assert aligned.feature_names == ("momentum_z_fast", "obv_z", "range_pct")
    assert aligned.signed_weights_a.tolist() == [0.6, 0.4, 0.0]
    assert aligned.signed_weights_b.tolist() == [0.5, 0.0, -0.5]


def test_score_bar_matches_manual_dot_product():
    feature_values = {"momentum_z_fast": 2.0, "obv_z": -1.0, "range_pct": 0.5}
    feature_names = ("momentum_z_fast", "obv_z", "range_pct")
    signed_weights = np.array([0.6, 0.4, 0.0])
    score = score_bar(feature_values, feature_names, signed_weights)
    expected = 2.0 * 0.6 + -1.0 * 0.4 + 0.5 * 0.0
    # Tolerance, not ==: np.dot and plain Python arithmetic aren't guaranteed
    # bit-identical (e.g. FMA on some platforms).
    assert abs(score - expected) < 1e-9


def test_score_bar_treats_missing_and_non_finite_as_zero():
    feature_values = {"momentum_z_fast": float("nan"), "obv_z": -1.0}
    feature_names = ("momentum_z_fast", "obv_z", "range_pct")
    signed_weights = np.array([0.6, 0.4, -0.5])
    score = score_bar(feature_values, feature_names, signed_weights)
    expected = 0.0 * 0.6 + -1.0 * 0.4 + 0.0 * -0.5
    assert abs(score - expected) < 1e-9


from scripts.analysis.regime_boundary_churn_check import compute_cell_verdict


def test_verdict_passes_when_both_criteria_met():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="5m",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,  # 6% >= 5% gate
        effect_sizes=np.array([0.30, 0.32, 0.35, 0.40]),  # median 0.335
        clean_noise_floor=0.20,  # 0.335 >= 1.5 * 0.20 = 0.30
        n_untrained_neighbor_bars=5,
        n_scored_bars=595,
    )
    assert verdict.boundary_adjacent_fraction == 0.06
    assert verdict.criterion_1_pass is True
    assert verdict.criterion_2_pass is True
    assert verdict.overall_pass is True


def test_verdict_fails_on_low_boundary_fraction():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1d",
        n_boundary_adjacent_timestamps=10,
        n_total_timestamps=10_000,  # 0.1% < 5% gate
        effect_sizes=np.array([0.50, 0.55]),
        clean_noise_floor=0.10,
        n_untrained_neighbor_bars=0,
        n_scored_bars=10,
    )
    assert verdict.criterion_1_pass is False
    assert verdict.overall_pass is False


def test_verdict_fails_when_effect_indistinguishable_from_noise():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1h",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,
        effect_sizes=np.array([0.10, 0.11, 0.12]),  # median 0.11
        clean_noise_floor=0.20,  # 0.11 < 1.5 * 0.20 = 0.30
        n_untrained_neighbor_bars=0,
        n_scored_bars=600,
    )
    assert verdict.criterion_1_pass is True
    assert verdict.criterion_2_pass is False
    assert verdict.overall_pass is False


def test_verdict_handles_zero_noise_floor_without_dividing_by_zero():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1h",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,
        effect_sizes=np.array([0.10]),
        clean_noise_floor=0.0,
        n_untrained_neighbor_bars=0,
        n_scored_bars=600,
    )
    assert verdict.criterion_2_pass is False


def test_verdict_handles_no_boundary_adjacent_timestamps():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1d",
        n_boundary_adjacent_timestamps=0,
        n_total_timestamps=10_000,
        effect_sizes=np.array([]),
        clean_noise_floor=0.10,
        n_untrained_neighbor_bars=0,
        n_scored_bars=0,
    )
    assert verdict.median_effect_size == 0.0
    assert verdict.overall_pass is False
