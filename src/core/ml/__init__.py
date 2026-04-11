"""ML core — training/inference shared types. No train/serve skew.

All FeatureVector fields defined once here, used identically at:
  - Training time: polars DataFrame row → FeatureVector
  - Inference time: IntelligenceEvent → FeatureVector
"""

from src.core.ml.extractor import FeatureExtractor
from src.core.ml.features import FeatureVector
from src.core.ml.registry import ModelRegistry
from src.core.ml.shadow import ShadowRecorder
from src.core.ml.training_data import TrainingDataQuery

__all__ = [
    "FeatureVector",
    "FeatureExtractor",
    "ShadowRecorder",
    "ModelRegistry",
    "TrainingDataQuery",
]
