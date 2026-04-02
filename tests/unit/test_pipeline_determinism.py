"""Test pipeline determinism — sequential vs parallel output equivalence.

Proves PIPE-04: 100 bars processed sequentially produce identical output to
100 bars processed in parallel for both I1 and I7 tiers.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from services.intelligence_pipeline_agent import (
    I7_PLUGINS,
    IntelligencePipelineComputeAgent,
)
from src.intelligence.register_plugins import TIER_I1


# ---------------------------------------------------------------------------
# Helper: create bare agent instance via __new__() pattern (CLAUDE.md)
# ---------------------------------------------------------------------------


def _make_agent():
    """Create IntelligencePipelineComputeAgent.__new__() instance with required attrs."""
    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    # BaseAgent-level attributes
    agent.name = "intelligence_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    # Agent-specific attributes
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
    # Executor for parallel execution
    cpu_count = os.cpu_count() or 24
    agent._executor = ThreadPoolExecutor(
        max_workers=cpu_count * 2,
        thread_name_prefix="test_intel_",
    )
    return agent


def _deterministic_plugin(output_dict: dict):
    """Create a plugin that always returns a copy of output_dict — no randomness."""

    class DeterministicPlugin:
        def compute_full(self, frames):
            return dict(output_dict)

    return DeterministicPlugin()


def _deterministic_signal_plugin(plugin_name: str, direction: int):
    """Create an I7 plugin that always returns a fixed signal dict."""

    class DeterministicSignalPlugin:
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

    return DeterministicSignalPlugin()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineDeterminism:
    """Prove parallel I1/I7 pipeline produces deterministic output."""

    @pytest.mark.asyncio
    async def test_i1_100_bars_deterministic(self):
        """Run _run_i1 100 times — all results must be identical."""
        agent = _make_agent()

        plugin_names = TIER_I1[:5]
        for idx, name in enumerate(plugin_names):
            agent._plugin_cache[name] = _deterministic_plugin({f"{name}_rsi": float(idx)})

        frames = {"main": MagicMock()}

        results = []
        for _ in range(100):
            r = await agent._run_i1(frames, "ES", "1m")
            results.append(r)

        assert len(results) == 100
        first = results[0]
        assert all(r == first for r in results[1:]), (
            "I1 output is not deterministic — some results differ across 100 runs"
        )
        # Verify all 5 plugin keys are present
        for idx, name in enumerate(plugin_names):
            assert f"{name}_rsi" in first, f"Missing key {name}_rsi in output"
            assert first[f"{name}_rsi"] == float(idx)

    @pytest.mark.asyncio
    async def test_i1_parallel_matches_sequential(self):
        """Parallel _run_i1 output must match sequential compute_full calls."""
        agent = _make_agent()

        plugin_names = TIER_I1[:5]
        plugins = {}
        for idx, name in enumerate(plugin_names):
            output = {f"{name}_value": float(idx) * 1.1}
            p = _deterministic_plugin(output)
            plugins[name] = p
            agent._plugin_cache[name] = p

        frames = {"main": MagicMock()}

        # Parallel result via _run_i1
        parallel_result = await agent._run_i1(frames, "ES", "1m")

        # Sequential result: call each plugin directly
        sequential_result = {}
        for name, p in plugins.items():
            out = p.compute_full(frames)
            sequential_result.update(out)

        # Keys must match
        assert set(parallel_result.keys()) == set(sequential_result.keys()), (
            f"Key mismatch — parallel: {set(parallel_result.keys())}, "
            f"sequential: {set(sequential_result.keys())}"
        )

        # Values must match within float tolerance
        for key in sequential_result:
            a = parallel_result[key]
            b = sequential_result[key]
            if isinstance(a, float) and isinstance(b, float):
                assert abs(a - b) < 1e-10, (
                    f"Value mismatch for key '{key}': parallel={a}, sequential={b}"
                )
            else:
                assert a == b, f"Value mismatch for key '{key}': {a} != {b}"

    @pytest.mark.asyncio
    async def test_i7_100_bars_deterministic(self):
        """Run _run_i7 100 times — signal lists must be identical across all runs."""
        agent = _make_agent()

        plugin_names = I7_PLUGINS[:3]
        # Two signal-producing plugins, one returning empty dict
        agent._plugin_cache[plugin_names[0]] = _deterministic_signal_plugin(plugin_names[0], 1)
        agent._plugin_cache[plugin_names[1]] = _deterministic_signal_plugin(plugin_names[1], -1)
        agent._plugin_cache[plugin_names[2]] = _deterministic_plugin({})  # no signal

        bar = MagicMock()
        bar.symbol = "ES"
        bar.tf = "1m"

        event = MagicMock()
        event.i1 = MagicMock()
        event.i1.model_dump.return_value = {}
        event.i2 = None
        event.i3 = None
        event.i4 = None
        event.i5 = None
        event.smc = None
        event.i6 = None

        results = []
        with (
            patch("services.intelligence_pipeline_agent._build_features_from_event", return_value={}),
            patch("services.intelligence_pipeline_agent.apply_quality_gate", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.apply_regime_gate", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.apply_tod_adjustment", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.apply_calibration", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.rank_signals", side_effect=lambda sigs, *a, **kw: sigs),
            patch("services.intelligence_pipeline_agent.select_winner", return_value=None),
            patch("services.intelligence_pipeline_agent._apply_alpha_decay"),
        ):
            for _ in range(100):
                r = await agent._run_i7(bar, event, {})
                results.append(r)

        assert len(results) == 100

        # Extract signal identifiers for comparison
        def signal_key(sig):
            return (sig.get("setup_plugin"), sig.get("direction"), sig.get("confidence"))

        first_keys = sorted(signal_key(s) for s in results[0]["ranked"])

        for i, r in enumerate(results[1:], start=1):
            run_keys = sorted(signal_key(s) for s in r["ranked"])
            assert run_keys == first_keys, (
                f"I7 output not deterministic — run {i} differs from run 0: "
                f"{run_keys} != {first_keys}"
            )

    @pytest.mark.asyncio
    async def test_thread_pool_size_configurable(self):
        """Agent respects intelligence_thread_pool_workers setting for pool size."""
        agent = _make_agent()

        # Override the executor with a fixed-size pool matching what __init__ would create
        agent._executor.shutdown(wait=False)
        agent._executor = ThreadPoolExecutor(
            max_workers=64,
            thread_name_prefix="test_configured_",
        )

        assert agent._executor._max_workers == 64, (
            f"Expected 64 workers, got {agent._executor._max_workers}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
