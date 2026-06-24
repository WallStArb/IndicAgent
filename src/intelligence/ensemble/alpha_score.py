"""
Composite alpha score computation with analytic CI propagation.

Pure functions only — no DB imports, no Kafka imports.

CI bounds assume independence of feature IC estimation errors
(var = dot(weights**2, sigma_ic**2)). For correlated feature clusters,
actual CI width is wider than computed — cluster deflation (see
weights.cluster_deflate_weights) mitigates this at the weight level.
The ci_independence_assumption APR key acknowledges this approximation.
Full fix (var = w^T Sigma_IC w using full LW covariance of IC estimation
errors) is deferred pending corpus calibration.

The alpha score formula:
    alpha = sum(w_i * ic_sign_i * z_i)
    where z_i are already z-scored features from feature_vectors.

IMPORTANT (Pitfall 3 from RESEARCH.md): Do NOT z-score the composite again.
Feature values in feature_vectors are already z-scored. The composite is
expressed in natural z-score units because the inputs are z-scored — no
additional standardization of the composite itself. The emission threshold in
alpha.quant.threshold.* is in these same natural composite units.

Statistical constants (APR-exempt per CLAUDE.md — mathematical constants):
    1.96  — z-score for 95% CI margin (z_{0.975})
    3.92  — 2 × 1.96; the 95% CI has total width 3.92 sigma
"""

from __future__ import annotations

import math

import numpy as np


def compute_alpha_score(
    feature_values: np.ndarray,
    weights: np.ndarray,
    ic_signs: np.ndarray,
    ic_ci_lower: np.ndarray,
    ic_ci_upper: np.ndarray,
) -> tuple[float, float, float]:
    """Compute composite alpha score and 95% CI bounds for one bar.

    Parameters
    ----------
    feature_values:
        Shape [n_features]. Already z-scored (as stored in feature_vectors).
        Non-finite values are treated as 0 (feature does not contribute).
    weights:
        Shape [n_features]. Post-cap, post-deflation, renormalized weight vector.
    ic_signs:
        Shape [n_features]. +1 or -1 — the IC sign for each feature. Features
        with negative IC contribute inversely to their feature value sign: a high
        feature value in a negatively-IC-correlated feature is bearish.
    ic_ci_lower:
        Shape [n_features]. Lower bound of the feature's IC 95% CI.
        Used to estimate IC uncertainty contribution to the composite CI.
    ic_ci_upper:
        Shape [n_features]. Upper bound of the feature's IC 95% CI.

    Returns
    -------
    (alpha_score, ci_lower, ci_upper):
        alpha_score: weighted composite z-score, sign-adjusted by ic_signs.
        ci_lower: alpha_score - 1.96 * sqrt(var)
        ci_upper: alpha_score + 1.96 * sqrt(var)
        CI propagation assumes independent IC estimation errors across features.
        See module docstring for the acknowledged limitation.
    """
    # Sign-adjusted, NaN-safe dot product
    safe_vals = np.where(np.isfinite(feature_values), feature_values, 0.0)
    alpha = float(np.dot(weights, np.asarray(ic_signs, dtype=float) * safe_vals))

    # Analytic CI propagation: var = sum(w_i^2 * sigma_ic_i^2)
    # sigma_ic_i = (ci_upper_i - ci_lower_i) / 3.92 (95% CI width / 2z)
    ci_widths = np.where(
        np.isfinite(ic_ci_lower) & np.isfinite(ic_ci_upper),
        ic_ci_upper - ic_ci_lower,
        0.0,
    )
    ci_variances = (ci_widths / 3.92) ** 2
    alpha_var = float(np.dot(weights**2, ci_variances))
    margin = 1.96 * math.sqrt(alpha_var)

    return alpha, alpha - margin, alpha + margin
