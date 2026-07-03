"""
Ensemble math library for Phase 139 Ensemble + Alpha Emission.

Pure functions only — Ring 1 domain module. No DB imports, no Kafka imports.

Public API:
    feature_selector.select_features_per_stratum
    covariance.compute_shrinkage_covariance
    weights.derive_weights
    weights.cluster_deflate_weights
    weights.mean_variance_weights
    weights.effective_n
    alpha_score.compute_alpha_score
"""

from __future__ import annotations

from src.intelligence.ensemble.alpha_score import compute_alpha_score
from src.intelligence.ensemble.covariance import compute_shrinkage_covariance
from src.intelligence.ensemble.feature_selector import select_features_per_stratum
from src.intelligence.ensemble.weights import (
    cluster_deflate_weights,
    derive_weights,
    effective_n,
    mean_variance_weights,
)

__all__ = [
    "select_features_per_stratum",
    "compute_shrinkage_covariance",
    "derive_weights",
    "cluster_deflate_weights",
    "mean_variance_weights",
    "effective_n",
    "compute_alpha_score",
]
