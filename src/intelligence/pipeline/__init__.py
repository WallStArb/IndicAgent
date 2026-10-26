"""The three v2.x pipeline primitives `services/feature_vector_pipeline.py` still runs on.

OutputQueue (bounded publish queue), PerKeyWorkerManager (one worker per symbol/tf key) and
PluginStateManager (checkpoint file). The I1-I7 executor and signal stages were removed with
todo 509; the archive is the local git tag `archive/v2x-ai-stack-2026-10`.
"""

from __future__ import annotations

from src.intelligence.pipeline.output_queue import OutputQueue
from src.intelligence.pipeline.per_key_worker_manager import PerKeyWorkerManager
from src.intelligence.pipeline.state_manager import PluginStateManager

__all__ = ["OutputQueue", "PerKeyWorkerManager", "PluginStateManager"]
