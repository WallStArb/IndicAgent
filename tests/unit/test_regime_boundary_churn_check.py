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
