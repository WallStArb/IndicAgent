from __future__ import annotations

import numpy as np

from scripts.analysis.regime_boundary_churn_check import (
    WINDOW_STEP_MULTIPLIER,
    derive_boundary_window,
)


def test_derive_boundary_window_scales_with_median_step():
    # Steps alternate 0.01, 0.03 -> median abs step = 0.02
    series = np.array([0.10, 0.11, 0.14, 0.15, 0.18, 0.19])
    window = derive_boundary_window(series, multiplier=2.0)
    assert window == 0.04


def test_derive_boundary_window_empty_or_singleton_is_zero():
    assert derive_boundary_window(np.array([])) == 0.0
    assert derive_boundary_window(np.array([0.5])) == 0.0


def test_derive_boundary_window_default_multiplier_constant():
    series = np.array([0.0, 0.02, 0.04, 0.06])
    assert derive_boundary_window(series) == 0.02 * WINDOW_STEP_MULTIPLIER
