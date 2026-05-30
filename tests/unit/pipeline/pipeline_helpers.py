"""Shared test helpers for intelligence pipeline unit tests.

Provides the __new__() agent factory and plugin stubs used across
test_pipeline_parallelization, test_pipeline_determinism, and
test_pipeline_exception_isolation.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock

from services.intelligence_pipeline import IntelligencePipeline
from src.core.bar_history import BarHistory
from src.intelligence.pipeline.cache_manager import CacheManager
from src.intelligence.pipeline.executor import PluginExecutor
from src.intelligence.pipeline.output_queue import OutputQueue
from src.intelligence.pipeline.signal_processor import SignalProcessor
from src.intelligence.pipeline.state_manager import PluginStateManager
from src.intelligence.trading.cis_scorer import CISScorer
from src.observability.plugin_observer import NoOpPluginObserver


def make_agent() -> IntelligencePipeline:
    """Create an IntelligencePipeline via __new__() with required attrs.

    Bypasses __init__ so tests can inject only the state they need without
    touching live Kafka, DB, or plugin registry.  Pattern from CLAUDE.md.

    Cache state is seeded via the public seed_* API on agent._cache_mgr.
    Never mutate agent._cache_mgr._* private attributes directly.
    """
    agent = IntelligencePipeline.__new__(IntelligencePipeline)
    agent.name = "intelligence_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    agent._plugin_cache = {}
    agent._state_mgr = PluginStateManager(
        checkpoint_path=pathlib.Path(tempfile.mkdtemp()) / "ckpt.json"
    )
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    agent._i1_latency_ms = MagicMock()
    agent._i7_latency_ms = MagicMock()
    agent._pipeline_latency = MagicMock()
    agent._pipeline_errors = MagicMock()
    agent.settings = MagicMock(env_name="dev")
    agent.settings.intelligence_thread_pool_workers = 0
    agent._bar_history = BarHistory(maxlen=200)
    # CacheManager with an async mock DB — queries return [] by default.
    # Seed cache state via the public seed_* API: agent._cache_mgr.seed_perf_weights({...})
    _db = AsyncMock()
    _db.execute_query = AsyncMock(return_value=[])
    agent._cache_mgr = CacheManager(db=_db, settings=agent.settings)
    agent._regime_cache = {}
    agent._out_queue = OutputQueue(producer=MagicMock(), maxsize=500)
    agent._transform_recorder = MagicMock()
    agent._regime_prob_min = 0.7
    agent._regime_prob_soft_max = 0.55
    agent._regime_dur_min = 12
    cpu_count = os.cpu_count() or 24
    # D-06: self._thread_pool is the underlying ThreadPoolExecutor;
    # self._executor is the PluginExecutor instance.
    agent._thread_pool = ThreadPoolExecutor(
        max_workers=cpu_count * 2,
        thread_name_prefix="test_intel_",
    )
    agent._executor = PluginExecutor(
        thread_pool=agent._thread_pool,
        plugin_cache=agent._plugin_cache,
        instrument_map=agent._instrument_map,
        circuit_breakers={},
        observer=NoOpPluginObserver(),
    )
    # SignalProcessor owns kalman_state, setup_last_fire, and the I7 signal pipeline stages.
    agent._sig_proc = SignalProcessor(
        cis_scorer=CISScorer(),
        settings=agent.settings,
        transform_recorder=None,
    )
    return agent


def deterministic_plugin(output_dict: dict):
    """Plugin that always returns a copy of output_dict — no side effects."""

    class _Plugin:
        supports_incremental = False

        def compute_full(self, frames, *, state=None):
            return dict(output_dict)

    return _Plugin()


def signal_plugin(plugin_name: str, direction: int = 1):
    """I7 plugin that always returns a fixed signal dict."""

    class _Plugin:
        supports_incremental = False

        def compute_full(self, frames, *, state=None):
            return {
                "direction": direction,
                "confidence": 0.75,
                "setup_plugin": plugin_name,
                "stop_distance_atr": 1.0,
                "entry_price": 100.0,
            }

    return _Plugin()
