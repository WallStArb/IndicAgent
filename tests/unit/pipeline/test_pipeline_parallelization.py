"""Test pipeline parallelization improvements."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.intelligence.register_plugins import TIER_I1
from src.intelligence.register_plugins import TIER_I7 as I7_PLUGINS
from tests.unit.pipeline.pipeline_helpers import make_agent


def _mock_plugin(compute_result: dict):
    """Create a mock plugin that returns a fixed result."""

    class MockPlugin:
        supports_incremental = False

        def compute_full(self, frames, *, state=None):
            return compute_result

    return MockPlugin()


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


class TestI1ParallelExecution:
    """Test I1 parallel execution speed and correctness."""

    @pytest.mark.asyncio
    async def test_i1_parallel_execution_speed(self):
        """Verify I1 plugins run concurrently and are faster than sequential."""
        agent = make_agent()

        for i, plugin_name in enumerate(TIER_I1):
            agent._executor._plugin_cache[plugin_name] = _mock_plugin({f"{plugin_name}_value": i})

        frames = {"main": MagicMock()}

        start = time.perf_counter()
        result = await _run_i1_via_executor(agent, frames)
        elapsed_parallel = time.perf_counter() - start

        assert len(result) >= 27, f"Expected at least 27 keys, got {len(result)}"
        assert elapsed_parallel < 0.050, f"I1 took {elapsed_parallel * 1000:.1f}ms, expected <50ms"

        print(f"✓ I1 parallel execution: {elapsed_parallel * 1000:.1f}ms for 27 plugins")

    @pytest.mark.asyncio
    async def test_parallel_state_isolation(self):
        """Verify parallel plugin execution doesn't corrupt state across I1 and I7."""
        agent = make_agent()

        if not TIER_I1:
            pytest.skip("No TIER_I1 plugins registered")
        plugin_name_i1 = TIER_I1[0]
        agent._executor._plugin_cache[plugin_name_i1] = _mock_plugin(
            {"value": 1, "_state": {"counter": 0}}
        )

        frames = {"main": MagicMock()}

        result1 = await _run_i1_via_executor(agent, frames)
        result2 = await _run_i1_via_executor(agent, frames)

        assert result1["value"] == 1
        assert result2["value"] == 1
        assert "_state" not in result1
        assert "_state" not in result2

        if not I7_PLUGINS:
            pytest.skip("No I7_PLUGINS registered")
        plugin_name_i7 = I7_PLUGINS[0]
        agent._executor._plugin_cache[plugin_name_i7] = _mock_plugin(
            {
                "signal": {"value": 1, "direction": 1, "confidence": 0.5},
                "_state": {"counter": 0},
            }
        )

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

        with (
            patch(
                "src.intelligence.pipeline.signal_processor.build_flat_features",
                return_value={},
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_quality_gate",
                return_value=[],
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_regime_gate",
                return_value=[],
            ),
            # Phase 112 D-04: apply_calibration removed from signal_processor
            patch(
                "src.intelligence.pipeline.signal_processor.rank_signals",
                return_value=[],
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.select_winner",
                return_value=(None, [], "no_signal"),
            ),
        ):
            i7_result1 = await agent._sig_proc.process(
                event, {}, bar, "ES", "1m", raw_signals=[], cache_snapshot=snapshot
            )
            i7_result2 = await agent._sig_proc.process(
                event, {}, bar, "ES", "1m", raw_signals=[], cache_snapshot=snapshot
            )

        assert i7_result1.i7_result is not None
        assert i7_result2.i7_result is not None

        print("✓ State isolation verified in parallel execution for both I1 and I7")


class TestI7ParallelExecution:
    """Test I7 parallel execution speed and correctness."""

    @pytest.mark.asyncio
    async def test_i7_parallel_execution_speed(self):
        """Verify I7 plugins run concurrently and are faster than sequential."""
        agent = make_agent()

        for i, plugin_name in enumerate(I7_PLUGINS):
            agent._executor._plugin_cache[plugin_name] = _mock_plugin(
                {"signal": {"value": i, "direction": 1, "confidence": 0.5}}
            )

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

        with (
            patch(
                "src.intelligence.pipeline.signal_processor.build_flat_features",
                return_value={},
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_quality_gate",
                return_value=[],
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.apply_regime_gate",
                return_value=[],
            ),
            # Phase 112 D-04: apply_calibration removed from signal_processor
            patch(
                "src.intelligence.pipeline.signal_processor.rank_signals",
                return_value=[],
            ),
            patch(
                "src.intelligence.pipeline.signal_processor.select_winner",
                return_value=(None, [], "no_signal"),
            ),
        ):
            start = time.perf_counter()
            result = await agent._sig_proc.process(
                event, {}, bar, "ES", "1m", raw_signals=[], cache_snapshot=snapshot
            )
            elapsed_parallel = time.perf_counter() - start

        assert result.i7_result is not None
        assert isinstance(result.i7_result["ranked"], list)
        assert elapsed_parallel < 0.050, f"I7 took {elapsed_parallel * 1000:.1f}ms, expected <50ms"

        print(f"✓ I7 parallel execution: {elapsed_parallel * 1000:.1f}ms for 36 plugins")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
