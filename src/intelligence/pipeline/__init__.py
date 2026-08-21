"""Intelligence pipeline pure function stages.

Each stage is a pure function with no Kafka, DB, or service dependencies.
State is injected as arguments; functions are synchronous and side-effect free.
"""

from __future__ import annotations

from src.intelligence.pipeline.cache_manager import CacheManager
from src.intelligence.pipeline.calibrator import apply_calibration
from src.intelligence.pipeline.executor import PluginExecutor
from src.intelligence.pipeline.output_queue import OutputQueue
from src.intelligence.pipeline.per_key_worker_manager import PerKeyWorkerManager
from src.intelligence.pipeline.quality_gate import apply_quality_gate
from src.intelligence.pipeline.ranker import rank_signals
from src.intelligence.pipeline.regime_gate import apply_regime_gate
from src.intelligence.pipeline.signal_processor import (
    CacheSnapshot,
    SignalProcessor,
    SignalProcessorResult,
)
from src.intelligence.pipeline.state_manager import PluginStateManager
from src.intelligence.pipeline.winner_selector import select_winner

__all__ = [
    "apply_quality_gate",
    "apply_regime_gate",
    "apply_calibration",
    "rank_signals",
    "select_winner",
    "CacheManager",
    "CacheSnapshot",
    "OutputQueue",
    "PerKeyWorkerManager",
    "PluginExecutor",
    "PluginStateManager",
    "SignalProcessor",
    "SignalProcessorResult",
]
