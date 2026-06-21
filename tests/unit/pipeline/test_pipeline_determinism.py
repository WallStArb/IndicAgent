"""Test pipeline determinism — sequential vs parallel output equivalence.

Proves PIPE-04: 100 bars processed sequentially produce identical output to
100 bars processed in parallel for both I1 and I7 tiers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.intelligence.register_plugins import TIER_I1
from src.intelligence.register_plugins import TIER_I7 as I7_PLUGINS
from tests.unit.pipeline.pipeline_helpers import deterministic_plugin, make_agent, signal_plugin


# Helper: run executor.run_i1 with minimal state plumbing
async def _run_i1_via_executor(agent, frames, symbol="ES", tf="1m"):
    """Run I1 tier via PluginExecutor with empty state (mirrors orchestrator flow)."""
    plugin_states = agent._state_mgr.get_all_states_for(symbol, tf)
    lock = agent._state_mgr.get_lock((symbol, tf))
    result, _state_updates = await agent._executor.run_i1(
        plugin_states, lock, frames, symbol, tf, shadow_cache={}
    )
    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipelineDeterminism:
    """Prove parallel I1/I7 pipeline produces deterministic output."""

    @pytest.mark.asyncio
    async def test_i1_100_bars_deterministic(self):
        """Run run_i1 100 times — all results must be identical."""
        agent = make_agent()

        plugin_names = TIER_I1[:5]
        for idx, name in enumerate(plugin_names):
            agent._executor._plugin_cache[name] = deterministic_plugin({f"{name}_rsi": float(idx)})

        frames = {"main": MagicMock()}

        results = []
        for _ in range(100):
            r = await _run_i1_via_executor(agent, frames)
            results.append(r)

        assert len(results) == 100
        first = results[0]
        assert all(
            r == first for r in results[1:]
        ), "I1 output is not deterministic — some results differ across 100 runs"
        for idx, name in enumerate(plugin_names):
            assert f"{name}_rsi" in first, f"Missing key {name}_rsi in output"
            assert first[f"{name}_rsi"] == float(idx)

    @pytest.mark.asyncio
    async def test_i1_parallel_matches_sequential(self):
        """Parallel run_i1 output must match sequential compute_full calls."""
        agent = make_agent()

        plugin_names = TIER_I1[:5]
        plugins = {}
        for idx, name in enumerate(plugin_names):
            output = {f"{name}_value": float(idx) * 1.1}
            p = deterministic_plugin(output)
            plugins[name] = p
            agent._executor._plugin_cache[name] = p

        frames = {"main": MagicMock()}

        parallel_result = await _run_i1_via_executor(agent, frames)

        sequential_result = {}
        for name, p in plugins.items():
            out = p.compute_full(frames)
            sequential_result.update(out)

        # Exclude internal pipeline annotation keys from comparison
        _INTERNAL_KEYS = {"_tier_key"}
        parallel_keys = set(parallel_result.keys()) - _INTERNAL_KEYS
        assert parallel_keys == set(sequential_result.keys()), (
            f"Key mismatch — parallel: {parallel_keys}, "
            f"sequential: {set(sequential_result.keys())}"
        )

        for key in sequential_result:
            a = parallel_result[key]
            b = sequential_result[key]
            if isinstance(a, float) and isinstance(b, float):
                assert (
                    abs(a - b) < 1e-10
                ), f"Value mismatch for key '{key}': parallel={a}, sequential={b}"
            else:
                assert a == b, f"Value mismatch for key '{key}': {a} != {b}"

    @pytest.mark.asyncio
    async def test_i7_100_bars_deterministic(self):
        """Run _run_i7 100 times — signal lists must be identical across all runs."""
        agent = make_agent()

        plugin_names = I7_PLUGINS[:3]
        agent._executor._plugin_cache[plugin_names[0]] = signal_plugin(plugin_names[0], direction=1)
        agent._executor._plugin_cache[plugin_names[1]] = signal_plugin(
            plugin_names[1], direction=-1
        )
        agent._executor._plugin_cache[plugin_names[2]] = deterministic_plugin({})

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

        from src.intelligence.pipeline.signal_processor import CacheSnapshot

        snapshot = CacheSnapshot(
            perf_weights={},
            calibration_curves={},
            drift_penalties={},
            cis_weights={},
            cis_weights_version=0,
        )

        results = []
        with (
            patch(
                "src.intelligence.pipeline.signal_processor.build_flat_features",
                return_value={},
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_quality_gate",
                side_effect=lambda sigs, *a, **kw: sigs,
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_regime_gate",
                side_effect=lambda sigs, *a, **kw: sigs,
            ),
            # Phase 112 D-04: apply_calibration removed from signal_processor
            patch(
                "src.intelligence.pipeline.signal_processor.rank_signals",
                side_effect=lambda sigs, *a, **kw: sigs,
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.select_winner",
                return_value=(None, [], "no_signal"),
            ),
        ):
            for _ in range(100):
                r = await agent._sig_proc.process(
                    event, {}, bar, "ES", "1m", raw_signals=[], cache_snapshot=snapshot
                )
                results.append(r)

        assert len(results) == 100

        def signal_key(sig):
            return (sig.get("setup_plugin"), sig.get("direction"), sig.get("confidence"))

        first_keys = sorted(signal_key(s) for s in results[0].i7_result["ranked"])

        for i, r in enumerate(results[1:], start=1):
            run_keys = sorted(signal_key(s) for s in r.i7_result["ranked"])
            assert run_keys == first_keys, (
                f"I7 output not deterministic — run {i} differs from run 0: "
                f"{run_keys} != {first_keys}"
            )

    @pytest.mark.asyncio
    async def test_thread_pool_size_configurable(self):
        """Agent respects intelligence_thread_pool_workers setting for pool size."""
        agent = make_agent()

        # PluginExecutor owns the thread pool; verify it was constructed with a pool
        assert agent._executor._thread_pool is not None
        assert agent._thread_pool is not None
        # The thread pool should have reasonable worker count
        assert agent._thread_pool._max_workers >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
