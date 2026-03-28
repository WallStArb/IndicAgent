"""Backward-compatibility shim for feature_pipeline_service.

FeatureComputeAgent was previously named FeaturePipelineService in
feature_pipeline_service.py. This shim re-exports the class and helpers
so that existing tests continue to resolve without modification.

Phase 53.2 renamed the class to FeatureComputeAgent in feature_compute_agent.py.
This shim is retained for one release cycle to avoid touching external test files.
"""

from __future__ import annotations

from services.feature_compute_agent import (  # noqa: F401
    PRICE_SENSITIVE_PLUGINS,
    FeatureComputeAgent as FeaturePipelineService,
    _INSERT_OHLCV_SQL,
    _adjust_price_state,
)

__all__ = [
    "FeaturePipelineService",
    "PRICE_SENSITIVE_PLUGINS",
    "_INSERT_OHLCV_SQL",
    "_adjust_price_state",
]
