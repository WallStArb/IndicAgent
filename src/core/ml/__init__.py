"""ML core — training/inference shared types. No train/serve skew.

All FeatureVector fields defined once here, used identically at:
  - Training time: polars DataFrame row → FeatureVector
  - Inference time: IntelligenceEvent → FeatureVector
"""
from src.core.ml.features import FeatureVector

__all__ = ["FeatureVector"]
