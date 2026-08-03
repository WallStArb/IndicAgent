"""
Ledoit-Wolf shrinkage covariance estimator wrapper for ensemble construction.

Pure functions only — no DB imports, no Kafka imports.

The primary use of the LW covariance in Phase 139 is cluster detection:
    1. Compute pairwise correlation from the shrunk covariance.
    2. Identify clusters of features with pairwise correlation > threshold.
    3. Cap total weight per cluster via cluster_deflate_weights (in weights.py).

This prevents double-counting of collinear features (e.g. momentum_z_fast,
momentum_z_mid, momentum_z_slow may all have pairwise corr > 0.80 and should
not each receive full IC-Sharpe weight).

LedoitWolf input: X shape [n_obs, n_features] — samples are rows, features are columns.
This matches the natural shape of feature_vectors data as used in ic_engine.py.
"""

from __future__ import annotations

import numpy as np
from sklearn.covariance import LedoitWolf


def compute_shrinkage_covariance(
    X: np.ndarray,
) -> tuple[np.ndarray, float]:
    """Compute Ledoit-Wolf shrinkage covariance estimate.

    Parameters
    ----------
    X:
        Feature matrix, shape [n_obs, n_features]. LedoitWolf centers internally.
        Must have at least 2 rows and at least 1 feature; degenerate inputs return
        a zero/identity covariance without raising.

    Returns
    -------
    (covariance, shrinkage):
        covariance: shape [n_features, n_features] shrunk covariance matrix.
        shrinkage: float in [0, 1] — the Ledoit-Wolf shrinkage coefficient.
                   0 means no shrinkage (pure sample covariance).
                   1 means full shrinkage to the scaled identity.
    """
    if X.ndim != 2 or X.shape[0] < 2 or X.shape[1] == 0:
        n_features = X.shape[1] if X.ndim == 2 and X.shape[1] > 0 else 0
        return np.zeros((n_features, n_features)), 0.0

    lw = LedoitWolf(store_precision=False, assume_centered=False)
    lw.fit(X)
    return lw.covariance_, float(lw.shrinkage_)


def covariance_to_correlation(cov_matrix: np.ndarray) -> np.ndarray:
    """Convert a covariance matrix to its correlation matrix, guarding zero/near-zero variance.

    Extracted from services/ensemble_trainer.py's own inline conversion (previously duplicated
    ad hoc at every call site) so cluster-detection callers share one implementation. Diagonal
    entries near-zero variance would otherwise divide to +-inf/NaN; those entries are set to 0.0
    (no reliable correlation signal) with the diagonal itself forced to 1.0 regardless.

    Parameters
    ----------
    cov_matrix:
        Covariance matrix, shape [n_features, n_features] (typically the LW-shrunk covariance
        from compute_shrinkage_covariance()).

    Returns
    -------
    np.ndarray
        Correlation matrix, same shape, diagonal exactly 1.0.
    """
    diag_var = np.diag(cov_matrix)
    with np.errstate(divide="ignore", invalid="ignore"):
        outer_std = np.sqrt(np.outer(diag_var, diag_var))
        corr_matrix = np.where(outer_std > 1e-10, cov_matrix / outer_std, 0.0)
        np.fill_diagonal(corr_matrix, 1.0)
    return corr_matrix
