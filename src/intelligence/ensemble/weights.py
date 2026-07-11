"""
IC Sharpe weight derivation, cluster deflation, mean-variance combination, and
effective N for ensemble construction.

Pure functions only — no DB imports, no Kafka imports.

Four functions:
    derive_weights            — IC Sharpe → normalized weight vector with per-feature cap
    cluster_deflate_weights   — LW-correlation-based cluster detection and weight deflation
    mean_variance_weights     — Sigma^-1 . ic_shrunk combination, condition-number gated
    effective_n               — inverse HHI of the final weight vector

All numeric thresholds that are APR-backed (max_weight, max_cluster_corr,
max_cluster_weight, condition_max) are accepted as function parameters — callers
load them from APR via ConfigService.get_sync(). The only numeric constants in
this module are:
    1e-10  — convergence epsilon (APR-exempt: mathematical tolerance)
    1.0    — renormalization target (APR-exempt: mathematical requirement)
"""

from __future__ import annotations

import numpy as np

from src.intelligence.statistics.ic_math import check_condition_number


def derive_weights(
    weight_inputs: np.ndarray,
    max_weight: float,
) -> np.ndarray:
    """Derive normalized feature weights from positive-magnitude-convention per-feature
    weight inputs, with a per-feature cap.

    NOTE (Component E, todo 094): despite the historical parameter name `ic_sharpes`
    (renamed to `weight_inputs` here), this function is NOT always fed a raw IC Sharpe
    array. Callers are responsible for arriving at a POSITIVE-MAGNITUDE-CONVENTION input
    before calling this function -- i.e. "this feature deserves weight" must already be
    encoded as a positive value, and sign/direction is applied separately downstream
    (`signed_weights = weights * ic_signs` at score time). Two call sites, two different
    positive-convention inputs:
      - ic_proportional path: `aged_quality_weights` from compute_quality_weight(), which
        is already sign-aware (ic_sign * nearest_ci_bound * ...) so contrarians arrive
        here already flipped positive.
      - mean_variance path (E2): `ic_signs * mv_raw` -- the OUTPUT of the unconstrained
        Sigma^-1.ic_shrunk solve, signed by each feature's own ic_sign AFTER the solve
        (never before -- see resolve_stratum_weights' BLOCKER 3 note), which similarly
        converts genuinely-contributing features (whether contrarian or not) to positive.

    Parameters
    ----------
    weight_inputs:
        Array of positive-magnitude-convention per-feature weight inputs (see above).
        Non-finite values and values <= 0 are treated as zero and excluded -- this is a
        real (not stale) filter: a value near/at or below zero means the caller's own
        sign-aware framing already judged this feature not worth weighting in this run,
        not that the function itself discriminates on a raw signed IC Sharpe.
    max_weight:
        Per-feature weight cap. Loaded from APR key alpha.ensemble.max_feature_weight.
        Excess weight is redistributed proportionally to uncapped features via iterative
        proportional redistribution (up to 100 iterations, convergence at excess < 1e-10).

    Returns
    -------
    np.ndarray
        Normalized weight vector summing to 1.0 (within floating-point tolerance).
        Returns a zero vector of the same shape if no feature has a positive weight input.
    """
    # Zero out non-finite and non-positive weight inputs (already sign-resolved by caller).
    w = np.where(np.isfinite(weight_inputs) & (weight_inputs > 0), weight_inputs, 0.0)

    total = float(w.sum())
    if total < 1e-10:
        return np.zeros_like(weight_inputs, dtype=float)

    # Normalize to sum 1
    w = w / total

    # Iterative proportional redistribution of excess above cap
    for _ in range(100):
        clipped = np.minimum(w, max_weight)
        excess = float(w.sum() - clipped.sum())
        if excess < 1e-10:
            w = clipped
            break
        uncapped_mask = w < max_weight
        if not uncapped_mask.any():
            w = clipped
            break
        w = clipped.copy()
        uncapped_sum = float(w[uncapped_mask].sum())
        if uncapped_sum < 1e-10:
            break
        w[uncapped_mask] += excess * (w[uncapped_mask] / uncapped_sum)

    # Final renorm for floating-point safety
    s = float(w.sum())
    if s < 1e-10:
        return np.zeros_like(weight_inputs, dtype=float)
    return w / s


def cluster_deflate_weights(
    weights: np.ndarray,
    corr_matrix: np.ndarray,
    max_cluster_corr: float,
    max_cluster_weight: float,
) -> np.ndarray:
    """Cap total weight for clusters of highly-correlated features.

    Finds all clusters of features where pairwise correlation > max_cluster_corr
    using a greedy union-find (any pair exceeding the threshold is merged into one
    cluster). For each cluster whose total weight exceeds max_cluster_weight, scales
    each member's weight down proportionally so the cluster sums to max_cluster_weight.

    This prevents double-counting of collinear features (e.g. momentum_z_fast,
    momentum_z_mid, momentum_z_slow may all have pairwise corr > 0.80 — they
    should not each receive full IC-Sharpe weight).

    Parameters
    ----------
    weights:
        Post-cap, post-renorm weight vector from derive_weights(), shape [n_features].
    corr_matrix:
        Pairwise correlation matrix, shape [n_features, n_features]. Typically computed
        from the Ledoit-Wolf shrunk covariance: corr[i,j] = cov[i,j] / sqrt(var[i]*var[j]).
    max_cluster_corr:
        Pairwise correlation threshold above which two features are merged into one cluster.
        Loaded from APR key alpha.ensemble.max_cluster_correlation.
    max_cluster_weight:
        Maximum total weight any single cluster may receive.
        Loaded from APR key alpha.ensemble.max_cluster_weight.

    Returns
    -------
    np.ndarray
        Weight vector after cluster deflation. Renormalized to sum to 1.0 (within
        floating-point tolerance), or a zero vector if all weights deflated to zero.
    """
    n = len(weights)
    if n == 0 or corr_matrix.shape != (n, n):
        return weights.copy()

    # Union-find: merge any pair (i, j) where abs(corr[i,j]) > max_cluster_corr
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(n):
        for j in range(i + 1, n):
            if abs(corr_matrix[i, j]) > max_cluster_corr:
                union(i, j)

    # Group features by cluster root
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        clusters.setdefault(root, []).append(i)

    w = weights.copy().astype(float)

    # For each cluster exceeding max_cluster_weight, scale members down proportionally
    for indices in clusters.values():
        if len(indices) <= 1:
            continue
        cluster_weight = float(sum(w[i] for i in indices))
        if cluster_weight > max_cluster_weight:
            scale = max_cluster_weight / cluster_weight
            for i in indices:
                w[i] *= scale

    # Renorm
    s = float(w.sum())
    if s < 1e-10:
        return np.zeros(n, dtype=float)
    return w / s


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
