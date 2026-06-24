"""
IC Sharpe weight derivation, cluster deflation, and effective N for ensemble construction.

Pure functions only — no DB imports, no Kafka imports.

Three functions:
    derive_weights            — IC Sharpe → normalized weight vector with per-feature cap
    cluster_deflate_weights   — LW-correlation-based cluster detection and weight deflation
    effective_n               — inverse HHI of the final weight vector

All numeric thresholds that are APR-backed (max_weight, max_cluster_corr,
max_cluster_weight) are accepted as function parameters — callers load them from
APR via ConfigService.get_sync(). The only numeric constants in this module are:
    1e-10  — convergence epsilon (APR-exempt: mathematical tolerance)
    1.0    — renormalization target (APR-exempt: mathematical requirement)
"""

from __future__ import annotations

import numpy as np


def derive_weights(
    ic_sharpes: np.ndarray,
    max_weight: float,
) -> np.ndarray:
    """Derive normalized feature weights from IC Sharpe values with a per-feature cap.

    Parameters
    ----------
    ic_sharpes:
        Array of IC Sharpe values, one per feature. Non-finite values and values <= 0
        are treated as zero (features with non-positive IC Sharpe are excluded).
    max_weight:
        Per-feature weight cap. Loaded from APR key alpha.ensemble.max_feature_weight.
        Excess weight is redistributed proportionally to uncapped features via iterative
        proportional redistribution (up to 100 iterations, convergence at excess < 1e-10).

    Returns
    -------
    np.ndarray
        Normalized weight vector summing to 1.0 (within floating-point tolerance).
        Returns a zero vector of the same shape if no feature has a positive IC Sharpe.
    """
    # Zero out non-finite and non-positive IC Sharpe values
    w = np.where(np.isfinite(ic_sharpes) & (ic_sharpes > 0), ic_sharpes, 0.0)

    total = float(w.sum())
    if total < 1e-10:
        return np.zeros_like(ic_sharpes, dtype=float)

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
        return np.zeros_like(ic_sharpes, dtype=float)
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
