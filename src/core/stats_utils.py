"""Statistical utility functions shared across intelligence services.

Extracted from weight_updater._bootstrap_ci_lower (Phase 75).
Both ShadowAuditorAgent and weight_updater import from this module.
"""
from __future__ import annotations

import numpy as np


def bootstrap_ci_lower(
    pnl_r_values: list[float],
    alpha: float = 0.05,
    n_boot: int = 1000,
) -> float:
    """Bootstrap lower confidence bound on E[PnL_R].

    Returns float('-inf') if fewer than 10 samples (insufficient for reliable estimate).
    Uses a fixed RNG seed (42) for reproducibility in tests.

    Args:
        pnl_r_values: PnL in R-multiples for resolved signals.
        alpha: Significance level. Default 0.05 gives 95% CI lower bound.
        n_boot: Number of bootstrap resamples. Default 1000.

    Returns:
        Lower bound float, or -inf on insufficient data.
    """
    if len(pnl_r_values) < 10:
        return float("-inf")
    rng = np.random.default_rng(42)
    arr = np.array(pnl_r_values)
    boot_means = np.array([
        rng.choice(arr, size=len(arr), replace=True).mean()
        for _ in range(n_boot)
    ])
    return float(np.percentile(boot_means, alpha / 2 * 100))
