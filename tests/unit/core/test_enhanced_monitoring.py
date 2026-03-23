"""
Test Circuit Breaker Infrastructure

Tests for PluginCircuitBreaker functionality (state_manager dependency removed).

Version: 2.0.0
Last Updated: 2026-03-22
Status: Circuit Breaker Tests Only ✅
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from src.core.plugin_circuit_breaker import CircuitBreakerConfig, CircuitState, PluginCircuitBreaker


class TestPluginCircuitBreaker:
    """Test circuit breaker functionality (without state_manager dependency)."""

    @pytest.fixture
    def config(self):
        """Create test circuit breaker config."""
        return CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=60,
            success_threshold=1,
            performance_threshold_ms=1000.0,
        )

    @pytest.fixture
    def circuit_breaker(self, config):
        """Create circuit breaker with test config."""
        return PluginCircuitBreaker(config)

    @pytest.mark.asyncio
    async def test_successful_execution(self, circuit_breaker):
        """Test successful plugin execution."""

        async def mock_plugin():
            await asyncio.sleep(0.01)  # 10ms
            return {"result": "success"}

        async def mock_fallback():
            return {"result": "fallback"}

        result = await circuit_breaker.execute_with_fallback("RSI", mock_plugin, mock_fallback)

        assert result == {"result": "success"}

        # Verify state tracking
        plugin_state = circuit_breaker.plugin_states["RSI"]
        assert plugin_state.state == CircuitState.CLOSED
        assert plugin_state.success_count == 1
        assert plugin_state.total_calls == 1

    @pytest.mark.asyncio
    async def test_failure_and_fallback(self, circuit_breaker):
        """Test plugin failure triggers fallback."""

        async def mock_plugin():
            raise ValueError("Plugin failed")

        async def mock_fallback():
            return {"result": "fallback"}

        result = await circuit_breaker.execute_with_fallback("RSI", mock_plugin, mock_fallback)

        assert result == {"result": "fallback"}

        # Verify failure tracking
        plugin_state = circuit_breaker.plugin_states["RSI"]
        assert plugin_state.failure_count == 1
        assert len(plugin_state.recent_failures) == 1
        assert plugin_state.recent_failures[0].error_type == "ValueError"

    @pytest.mark.asyncio
    async def test_circuit_opens_after_failures(self, circuit_breaker):
        """Test circuit opens after threshold failures."""

        async def failing_plugin():
            raise Exception("Always fails")

        async def mock_fallback():
            return {"result": "fallback"}

        # Execute multiple times to trigger circuit opening
        for _ in range(3):  # threshold is 2, so 3rd should open circuit
            await circuit_breaker.execute_with_fallback("RSI", failing_plugin, mock_fallback)

        plugin_state = circuit_breaker.plugin_states["RSI"]
        assert plugin_state.state == CircuitState.OPEN

        # Next execution should use fallback immediately
        with patch.object(circuit_breaker, "_execute_fallback") as mock_fallback_exec:
            mock_fallback_exec.return_value = {"result": "immediate_fallback"}

            await circuit_breaker.execute_with_fallback("RSI", failing_plugin, mock_fallback)

            mock_fallback_exec.assert_called_once()

    @pytest.mark.asyncio
    async def test_circuit_recovery(self, circuit_breaker):
        """Test circuit breaker recovery mechanism."""

        # Force circuit to open
        plugin_state = circuit_breaker.plugin_states["RSI"]
        plugin_state.state = CircuitState.OPEN
        plugin_state.last_failure_time = datetime.now() - timedelta(
            seconds=70
        )  # Past recovery timeout

        async def recovering_plugin():
            return {"result": "recovered"}

        async def mock_fallback():
            return {"result": "fallback"}

        result = await circuit_breaker.execute_with_fallback(
            "RSI", recovering_plugin, mock_fallback
        )

        assert result == {"result": "recovered"}

        # Should transition to CLOSED after successful execution
        assert plugin_state.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_timeout_handling(self, circuit_breaker):
        """Test plugin timeout triggers fallback."""

        async def slow_plugin():
            await asyncio.sleep(2.0)  # Longer than 1s threshold
            return {"result": "slow"}

        async def mock_fallback():
            return {"result": "fallback"}

        result = await circuit_breaker.execute_with_fallback("RSI", slow_plugin, mock_fallback)

        assert result == {"result": "fallback"}

        # Verify timeout was recorded as failure
        plugin_state = circuit_breaker.plugin_states["RSI"]
        assert plugin_state.failure_count == 1
        assert plugin_state.recent_failures[0].error_type == "timeout"

    @pytest.mark.asyncio
    async def test_langgraph_workflow_monitoring(self, circuit_breaker):
        """Test LangGraph workflow execution monitoring."""

        async def mock_workflow():
            await asyncio.sleep(0.05)  # 50ms
            return {"workflow": "completed"}

        with patch("src.core.plugin_circuit_breaker.record_langgraph_workflow") as mock_record:
            result = await circuit_breaker.execute_workflow_with_monitoring(
                "confluence_analysis", mock_workflow
            )

            assert result == {"workflow": "completed"}
            mock_record.assert_called_once()

            # Verify call arguments
            call_args = mock_record.call_args[0]
            assert call_args[0] == "confluence_analysis"  # workflow_name
            assert call_args[1] > 0.04  # execution_time > 40ms
            assert call_args[2] == "success"  # status

    def test_get_plugin_stats(self, circuit_breaker):
        """Test plugin statistics generation."""

        # Set up some test data
        plugin_state = circuit_breaker.plugin_states["RSI"]
        plugin_state.total_calls = 10
        plugin_state.success_count = 8
        plugin_state.failure_count = 2

        circuit_breaker.performance_history["RSI"].extend([10.0, 15.0, 12.0, 8.0])
        circuit_breaker.total_executions = 10
        circuit_breaker.total_fallbacks = 2

        stats = circuit_breaker.get_plugin_stats()

        assert stats["global_stats"]["total_executions"] == 10
        assert stats["global_stats"]["total_fallbacks"] == 2
        assert stats["global_stats"]["fallback_rate_percent"] == 20.0

        rsi_stats = stats["plugin_stats"]["RSI"]
        assert rsi_stats["total_calls"] == 10
        assert rsi_stats["success_count"] == 8
        assert rsi_stats["failure_count"] == 2
        assert rsi_stats["avg_execution_time_ms"] == 11.25  # Average of performance history

    @pytest.mark.asyncio
    async def test_failure_recovery_cycle(self, circuit_breaker):
        """Test complete failure and recovery cycle."""

        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1, success_threshold=1)
        cb = PluginCircuitBreaker(config)

        # Failing plugin
        failure_count = 0

        async def unreliable_plugin():
            nonlocal failure_count
            failure_count += 1
            if failure_count <= 2:
                raise Exception(f"Failure {failure_count}")
            return {"result": "recovered"}

        async def fallback():
            return {"result": "fallback"}

        # Execute multiple times to trigger failure → open → recovery
        results = []

        # First two should fail and use fallback
        for _ in range(2):
            result = await cb.execute_with_fallback(
                "UNRELIABLE", unreliable_plugin, fallback
            )
            results.append(result)

        # Circuit should be open now
        assert cb.plugin_states["UNRELIABLE"].state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # Next execution should recover
        result = await cb.execute_with_fallback(
            "UNRELIABLE", unreliable_plugin, fallback
        )
        results.append(result)

        # Verify results
        assert results[0] == {"result": "fallback"}  # First failure
        assert results[1] == {"result": "fallback"}  # Second failure (circuit opens)
        assert results[2] == {"result": "recovered"}  # Recovery

        # Circuit should be closed again
        assert cb.plugin_states["UNRELIABLE"].state == CircuitState.CLOSED


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
