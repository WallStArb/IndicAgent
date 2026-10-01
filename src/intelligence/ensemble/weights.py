"""
Mean-variance combination and effective N for ensemble construction.

Pure functions only — no DB imports, no Kafka imports.

Two functions (derive_weights and cluster_deflate_weights were deleted in phase 186
plan 19 with the old ensemble chain):
    mean_variance_weights     — Sigma^-1 . ic_shrunk combination, condition-number gated
    effective_n               — inverse HHI of the final weight vector

All numeric thresholds that are APR-backed (condition_max) are accepted as function parameters — callers
load them from APR via ConfigService.get_sync(). The only numeric constants in
this module are:
    1e-10  — convergence epsilon (APR-exempt: mathematical tolerance)
    1.0    — renormalization target (APR-exempt: mathematical requirement)
"""

from __future__ import annotations

import numpy as np

from src.intelligence.statistics.ic_math import check_condition_number


def mean_variance_weights(
    cov_matrix: np.ndarray,
    ic_shrunk: np.ndarray,
    condition_max: float,
) -> tuple[np.ndarray | None, float]:
    """Compute w proportional to Sigma^-1 . ic_shrunk, gated on numerical stability.

    Source: Grinold & Kahn "Active Portfolio Management" signal-combination framework
    (textbook mean-variance optimal combination of correlated signals: w ∝ Σ⁻¹ μ).
    Numerical-stability guard is standard practice for any Σ⁻¹ computation on an
    estimated (not population) covariance matrix.

    Parameters
    ----------
    cov_matrix:
        Covariance matrix, shape [n_features, n_features] (typically the LW-shrunk
        covariance from compute_shrinkage_covariance()).
    ic_shrunk:
        Per-feature shrunk IC values, shape [n_features].
    condition_max:
        Maximum acceptable condition number (2-norm, np.linalg.cond default) before
        the Sigma^-1 solve is considered numerically unreliable. Loaded from APR key
        alpha.ensemble.mv_condition_max.

    Returns
    -------
    (weights, cond):
        weights: normalized (sum of abs == 1.0) raw weights, or None if the gate
            fails. Raw, uncapped, unsigned — the existing derive_weights-style
            per-feature cap and ic_sign application still run afterward, unchanged
            (D-08). Do not fold cap/sign logic into this function.
        cond: the computed condition number, always returned (even on gate failure)
            so callers can log the fallback reason.
    """
    cond_ok, cond = check_condition_number(cov_matrix, condition_max)
    if not cond_ok:
        return None, cond

    # solve(), not explicit inv() — standard numerical-linear-algebra practice,
    # avoids the extra rounding error of forming the inverse explicitly.
    raw = np.linalg.solve(cov_matrix, ic_shrunk)
    total = float(np.sum(np.abs(raw)))
    if total < 1e-10:
        return np.zeros_like(raw), cond
    return raw / total, cond


def effective_n(weights: np.ndarray) -> float:
    """Compute effective N (inverse HHI) of the weight vector.

    effective_N = 1 / sum(w^2)

    Applied to the post-cap, post-deflation, post-renorm weight vector.
    An ensemble with 10 equal-weight features has effective_N = 10.
    An ensemble where one feature has weight 0.80 has effective_N ≈ 1.47.

    Returns 0.0 if the sum of squares is zero (all-zero weight vector).

    Parameters
    ----------
    weights:
        Post-cap post-deflation renormalized weight vector.
    """
    sum_sq = float(np.sum(weights**2))
    if sum_sq < 1e-10:
        return 0.0
    return 1.0 / sum_sq
