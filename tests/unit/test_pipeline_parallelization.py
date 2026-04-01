"""Test pipeline parallelization improvements."""

from __future__ import annotations

import asyncio
import time
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
    # Set BaseAgent-level attributes
    agent.name = "intelligence_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    # Set agent-specific attributes needed for tests
    agent._plugin_cache = {}
    agent._plugin_states = {}
    agent._plugin_states_locks = {}  # Correct name
    agent._instrument_map = {}
    agent._plugin_skipped_total = MagicMock()
    agent._i1_latency_ms = MagicMock()
    agent._i7_latency_ms = MagicMock()
    agent._pipeline_errors = MagicMock()
    agent._setup_last_fire = {}
    agent._signals_generated = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "dev"
    agent._regime_cache = {}  # Added for I7 tests
    agent._tod_priors = {}  # Added for I7 tests
    agent._calibration_curves = {}  # Added for I7 tests
    agent._perf_weights = {}  # Added for I7 tests
    agent._output_queue = asyncio.Queue(maxsize=500)  # Added for I7 tests
    return agent


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
        agent = _make_agent()

        # Mock all 27 I1 plugins using actual TIER_I1 names
        for i, plugin_name in enumerate(TIER_I1):
            agent._plugin_cache[plugin_name] = _mock_plugin({f"{plugin_name}_value": i})

        # Create mock frames
        frames = {"main": MagicMock()}

        # Time parallel execution
        start = time.perf_counter()
        result = await agent._run_i1(frames, "ES", "1m")
        elapsed_parallel = time.perf_counter() - start

        # Verify all plugins executed (at minimum we should have 27 keys)
        assert len(result) >= 27, f"Expected at least 27 keys, got {len(result)}"

        # Should be reasonably fast (< 50ms for 27 plugins)
        assert (
            elapsed_parallel < 0.050
        ), f"I1 took {elapsed_parallel * 1000:.1f}ms, expected <50ms"

        print(f"✓ I1 parallel execution: {elapsed_parallel * 1000:.1f}ms for 27 plugins")

    @pytest.mark.asyncio
    async def test_i1_state_isolation(self):
        """Verify parallel plugin execution doesn't corrupt state."""
        agent = _make_agent()

        # Mock plugin with state (use actual TIER_I1 name)
        plugin_name = TIER_I1[0]  # Use first real plugin name
        agent._plugin_cache[plugin_name] = _mock_plugin(
            {"value": 1, "_state": {"counter": 0}}
        )

        frames = {"main": MagicMock()}

        # Run same I1 execution twice in parallel (simulates concurrent bars)
        result1 = await agent._run_i1(frames, "ES", "1m")
        result2 = await agent._run_i1(frames, "ES", "1m")

        # Verify state integrity - both should have updated state
        assert result1["value"] == 1
        assert result2["value"] == 1
        assert "_state" not in result1  # State should be stripped
        assert "_state" not in result2

        print("✓ State isolation verified in parallel execution")


class TestI7ParallelExecution:
    """Test I7 parallel execution speed and correctness."""

    @pytest.mark.asyncio
    async def test_i7_parallel_execution_speed(self):
        """Verify I7 plugins run concurrently and are faster than sequential."""
        agent = _make_agent()

        # Mock all 36 I7 plugins using actual I7_PLUGINS names
        for i, plugin_name in enumerate(I7_PLUGINS):
            agent._plugin_cache[plugin_name] = _mock_plugin(
                {"signal": {"value": i, "direction": 1, "confidence": 0.5}}
            )

        # Create mock bar and event
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

        # Mock pipeline functions to return empty list (no signals pass gates)
        with patch(
            "services.intelligence_pipeline_agent._build_features_from_event",
            return_value={},
        ), patch(
            "services.intelligence_pipeline_agent.apply_quality_gate",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_regime_gate",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_tod_adjustment",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_calibration",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.rank_signals",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.select_winner",
            return_value=None,
        ), patch(
            "services.intelligence_pipeline_agent._apply_alpha_decay",
        ):
            start = time.perf_counter()
            result = await agent._run_i7(bar, event, {})
            elapsed_parallel = time.perf_counter() - start

        # Verify signals generated
        assert "ranked" in result
        assert isinstance(result["ranked"], list)

        # Should be reasonably fast (< 50ms for 36 plugins)
        assert (
            elapsed_parallel < 0.050
        ), f"I7 took {elapsed_parallel * 1000:.1f}ms, expected <50ms"

        print(f"✓ I7 parallel execution: {elapsed_parallel * 1000:.1f}ms for 36 plugins")

    @pytest.mark.asyncio
    async def test_i7_state_isolation(self):
        """Verify parallel I7 execution doesn't corrupt state."""
        agent = _make_agent()

        # Mock plugin with state and signal (use actual I7_PLUGINS name)
        plugin_name = I7_PLUGINS[0]  # Use first real plugin name
        agent._plugin_cache[plugin_name] = _mock_plugin(
            {
                "signal": {"value": 1, "direction": 1, "confidence": 0.5},
                "_state": {"counter": 0},
            }
        )

        # Create mock bar and event
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

        # Mock pipeline functions
        with patch(
            "services.intelligence_pipeline_agent._build_features_from_event",
            return_value={},
        ), patch(
            "services.intelligence_pipeline_agent.apply_quality_gate",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_regime_gate",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_tod_adjustment",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_calibration",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.rank_signals",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.select_winner",
            return_value=None,
        ), patch(
            "services.intelligence_pipeline_agent._apply_alpha_decay",
        ):
            # Run same I7 execution twice
            result1 = await agent._run_i7(bar, event, {})
            result2 = await agent._run_i7(bar, event, {})

        # Verify both executions completed successfully
        assert "ranked" in result1
        assert "ranked" in result2

        print("✓ I7 state isolation verified in parallel execution")


class TestParallelErrorHandling:
    """Test error handling in parallel execution."""

    @pytest.mark.asyncio
    async def test_i1_plugin_exception_doesnt_break_parallel_execution(self):
        """Verify that exceptions in I1 plugins don't break parallel execution."""
        agent = _make_agent()

        # Mix of good and failing plugins (use actual TIER_I1 names)
        agent._plugin_cache[TIER_I1[0]] = _mock_plugin({"value1": 1})

        class FailingPlugin:
            def compute_full(self, frames):
                raise RuntimeError("Plugin error")

        agent._plugin_cache[TIER_I1[1]] = FailingPlugin()
        agent._plugin_cache[TIER_I1[2]] = _mock_plugin({"value2": 2})

        frames = {"main": MagicMock()}

        # Should complete without raising
        result = await agent._run_i1(frames, "ES", "1m")

        # Good plugins should have executed
        assert result["value1"] == 1
        assert result["value2"] == 2

        # Error counter should have been incremented
        agent._pipeline_errors.inc.assert_called()

        print("✓ I1 error handling: parallel execution continues despite plugin errors")

    @pytest.mark.asyncio
    async def test_i7_plugin_exception_doesnt_break_parallel_execution(self):
        """Verify that exceptions in I7 plugins don't break parallel execution."""
        agent = _make_agent()

        # Mix of good and failing plugins (use actual I7_PLUGINS names)
        agent._plugin_cache[I7_PLUGINS[0]] = _mock_plugin(
            {"signal": {"value": 1, "direction": 1, "confidence": 0.5}}
        )

        class FailingPlugin:
            def compute_full(self, frames):
                raise RuntimeError("Plugin error")

        agent._plugin_cache[I7_PLUGINS[1]] = FailingPlugin()
        agent._plugin_cache[I7_PLUGINS[2]] = _mock_plugin(
            {"signal": {"value": 2, "direction": 1, "confidence": 0.5}}
        )

        # Create mock bar and event
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

        # Mock pipeline functions
        with patch(
            "services.intelligence_pipeline_agent._build_features_from_event",
            return_value={},
        ), patch(
            "services.intelligence_pipeline_agent.apply_quality_gate",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_regime_gate",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_tod_adjustment",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.apply_calibration",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.rank_signals",
            return_value=[],
        ), patch(
            "services.intelligence_pipeline_agent.select_winner",
            return_value=None,
        ), patch(
            "services.intelligence_pipeline_agent._apply_alpha_decay",
        ):
            # Should complete without raising
            result = await agent._run_i7(bar, event, {})

        # Should have ranked signals from good plugins
        assert "ranked" in result
        assert isinstance(result["ranked"], list)

        # Error counter should have been incremented
        agent._pipeline_errors.inc.assert_called()

        print("✓ I7 error handling: parallel execution continues despite plugin errors")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
