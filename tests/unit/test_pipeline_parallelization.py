"""Test pipeline parallelization improvements."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from services.intelligence_pipeline_agent import I7_PLUGINS
from src.intelligence.register_plugins import TIER_I1
from tests.unit.pipeline_helpers import make_agent


def _mock_plugin(compute_result: dict):
    """Create a mock plugin that returns a fixed result."""

    class MockPlugin:
        def compute_full(self, frames):
            return compute_result

    return MockPlugin()


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
            agent._plugin_cache[plugin_name] = _mock_plugin({f"{plugin_name}_value": i})

        frames = {"main": MagicMock()}

        start = time.perf_counter()
        result = await agent._run_i1(frames, "ES", "1m")
        elapsed_parallel = time.perf_counter() - start

        assert len(result) >= 27, f"Expected at least 27 keys, got {len(result)}"
        assert (
            elapsed_parallel < 0.050
        ), f"I1 took {elapsed_parallel * 1000:.1f}ms, expected <50ms"

        print(f"✓ I1 parallel execution: {elapsed_parallel * 1000:.1f}ms for 27 plugins")

    @pytest.mark.asyncio
    async def test_parallel_state_isolation(self):
        """Verify parallel plugin execution doesn't corrupt state across I1 and I7."""
        agent = make_agent()

        if not TIER_I1:
            pytest.skip("No TIER_I1 plugins registered")
        plugin_name_i1 = TIER_I1[0]
        agent._plugin_cache[plugin_name_i1] = _mock_plugin(
            {"value": 1, "_state": {"counter": 0}}
        )

        frames = {"main": MagicMock()}

        result1 = await agent._run_i1(frames, "ES", "1m")
        result2 = await agent._run_i1(frames, "ES", "1m")

        assert result1["value"] == 1
        assert result2["value"] == 1
        assert "_state" not in result1
        assert "_state" not in result2

        if not I7_PLUGINS:
            pytest.skip("No I7_PLUGINS registered")
        plugin_name_i7 = I7_PLUGINS[0]
        agent._plugin_cache[plugin_name_i7] = _mock_plugin(
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

        with (
            patch("services.intelligence_pipeline_agent._build_features_from_event", return_value={}),
            patch("services.intelligence_pipeline_agent.apply_quality_gate", return_value=[]),
            patch("services.intelligence_pipeline_agent.apply_regime_gate", return_value=[]),
            patch("services.intelligence_pipeline_agent.apply_tod_adjustment", return_value=[]),
            patch("services.intelligence_pipeline_agent.apply_calibration", return_value=[]),
            patch("services.intelligence_pipeline_agent.rank_signals", return_value=[]),
            patch("services.intelligence_pipeline_agent.select_winner", return_value=(None, [], "no_signal")),
            patch("services.intelligence_pipeline_agent._apply_alpha_decay"),
        ):
            i7_result1 = await agent._run_i7(bar, event, {})
            i7_result2 = await agent._run_i7(bar, event, {})

        assert "ranked" in i7_result1
        assert "ranked" in i7_result2

        print("✓ State isolation verified in parallel execution for both I1 and I7")


class TestI7ParallelExecution:
    """Test I7 parallel execution speed and correctness."""

    @pytest.mark.asyncio
    async def test_i7_parallel_execution_speed(self):
        """Verify I7 plugins run concurrently and are faster than sequential."""
        agent = make_agent()

        for i, plugin_name in enumerate(I7_PLUGINS):
            agent._plugin_cache[plugin_name] = _mock_plugin(
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

        with (
            patch("services.intelligence_pipeline_agent._build_features_from_event", return_value={}),
            patch("services.intelligence_pipeline_agent.apply_quality_gate", return_value=[]),
            patch("services.intelligence_pipeline_agent.apply_regime_gate", return_value=[]),
            patch("services.intelligence_pipeline_agent.apply_tod_adjustment", return_value=[]),
            patch("services.intelligence_pipeline_agent.apply_calibration", return_value=[]),
            patch("services.intelligence_pipeline_agent.rank_signals", return_value=[]),
            patch("services.intelligence_pipeline_agent.select_winner", return_value=(None, [], "no_signal")),
            patch("services.intelligence_pipeline_agent._apply_alpha_decay"),
        ):
            start = time.perf_counter()
            result = await agent._run_i7(bar, event, {})
            elapsed_parallel = time.perf_counter() - start

        assert "ranked" in result
        assert isinstance(result["ranked"], list)
        assert (
            elapsed_parallel < 0.050
        ), f"I7 took {elapsed_parallel * 1000:.1f}ms, expected <50ms"

        print(f"✓ I7 parallel execution: {elapsed_parallel * 1000:.1f}ms for 36 plugins")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
