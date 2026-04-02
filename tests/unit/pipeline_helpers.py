"""Shared test helpers for intelligence pipeline unit tests.

Provides the __new__() agent factory and plugin stubs used across
test_pipeline_parallelization, test_pipeline_determinism, and
test_pipeline_exception_isolation.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent


def make_agent() -> IntelligencePipelineComputeAgent:
    """Create an IntelligencePipelineComputeAgent via __new__() with required attrs.

    Bypasses __init__ so tests can inject only the state they need without
    touching live Kafka, DB, or plugin registry.  Pattern from CLAUDE.md.
    """
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    agent.name = "intelligence_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._plugin_cache = {}
    agent._plugin_states = {}
    agent._plugin_states_locks = {}
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    agent._i1_latency_ms = MagicMock()
    agent._i7_latency_ms = MagicMock()
    agent._pipeline_errors = MagicMock()
    agent._setup_last_fire = {}
    agent._signals_generated = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "dev"
    agent._settings.intelligence_thread_pool_workers = 0
    agent._settings.pipeline_metrics_port = 9125
    agent._regime_cache = {}
    agent._tod_priors = {}
    agent._calibration_curves = {}
    agent._perf_weights = {}
    agent._output_queue = asyncio.Queue(maxsize=500)
    cpu_count = os.cpu_count() or 24
    agent._executor = ThreadPoolExecutor(
        max_workers=cpu_count * 2,
        thread_name_prefix="test_intel_",
    )
    return agent


def deterministic_plugin(output_dict: dict):
    """Plugin that always returns a copy of output_dict — no side effects."""

    class _Plugin:
        def compute_full(self, frames):
            return dict(output_dict)

    return _Plugin()


def signal_plugin(plugin_name: str, direction: int = 1):
    """I7 plugin that always returns a fixed signal dict."""

    class _Plugin:
        def compute_full(self, frames):
            return {
                "signal": {
                    "direction": direction,
                    "confidence": 0.75,
                    "setup_plugin": plugin_name,
                    "stop_distance_atr": 1.0,
                    "entry_price": 100.0,
                }
            }

    return _Plugin()
