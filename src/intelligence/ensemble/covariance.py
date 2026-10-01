"""
Ledoit-Wolf shrinkage covariance estimator wrapper for ensemble construction.

Pure functions only — no DB imports, no Kafka imports.

The shrunk covariance feeds mean_variance_weights (weights.py), which downweights
collinear features through the inverse covariance.

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
