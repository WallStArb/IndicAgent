"""
Test Enhanced Monitoring Infrastructure

Tests for:
- Prometheus metrics integration
- Plugin state management
- Circuit breaker functionality
- LangGraph workflow monitoring

Version: 1.0.0
Last Updated: 2025-08-17
Status: Comprehensive Test Suite ✅
"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.core.plugin_circuit_breaker import CircuitBreakerConfig, CircuitState, PluginCircuitBreaker

# Import our enhanced monitoring components
from src.core.plugin_state_manager import PluginStateManager
from src.observability.metrics import (
    record_event_routing,
    record_langgraph_workflow,
    record_plugin_execution,
)


class TestPluginStateManager:
    """Test plugin state management functionality."""

    @pytest.fixture
    def mock_redis(self):
        """Mock Redis client."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)
        redis_mock.get = AsyncMock(return_value=None)
        redis_mock.delete = AsyncMock(return_value=1)
        redis_mock.keys = AsyncMock(return_value=[])
        return redis_mock

    @pytest.fixture
    def state_manager(self, mock_redis):
        """Create state manager with mock Redis."""
        return PluginStateManager(mock_redis, "test:")

    @pytest.mark.asyncio
    async def test_save_plugin_state(self, state_manager, mock_redis):
        """Test saving plugin state to Redis."""

        test_state = {"rsi_state": {"gain": 1.5, "loss": 0.8, "period": 14}, "bar_count": 100}

        result = await state_manager.save_plugin_state("RSI", "SPY", "1m", test_state)

        assert result is True
        mock_redis.set.assert_called_once()

        # Verify cache was updated
        cache_key = "RSI:SPY:1m:plugin"
        assert cache_key in state_manager.state_cache
        assert state_manager.state_cache[cache_key]["state"] == test_state

    @pytest.mark.asyncio
    async def test_restore_plugin_state_from_cache(self, state_manager):
        """Test restoring state from cache."""

        # Pre-populate cache
        test_state = {"cached": True}
        cache_key = "RSI:SPY:1m:plugin"
        state_manager.state_cache[cache_key] = {
            "state": test_state,
            "metadata": {},
            "cached_at": time.time(),
        }

        result = await state_manager.restore_plugin_state("RSI", "SPY", "1m")

        assert result == test_state
        assert state_manager.cache_hits == 1

    @pytest.mark.asyncio
    async def test_restore_plugin_state_from_redis(self, state_manager, mock_redis):
        """Test restoring state from Redis when cache miss."""

        test_state = {"from_redis": True}
        complete_state = {
            "metadata": {"size_bytes": 100},
            "state": test_state,
            "timestamp": datetime.now().isoformat(),
        }

        mock_redis.get.return_value = json.dumps(complete_state)

        result = await state_manager.restore_plugin_state("RSI", "SPY", "1m")

        assert result == test_state
        assert state_manager.cache_misses == 1

        # Verify cache was populated
        cache_key = "RSI:SPY:1m:plugin"
        assert cache_key in state_manager.state_cache

    @pytest.mark.asyncio
    async def test_langgraph_workflow_state(self, state_manager, mock_redis):
        """Test LangGraph workflow state management."""

        workflow_state = {
            "current_step": "pattern_detection",
            "symbols_processed": ["SPY", "QQQ"],
            "confidence_score": 0.85,
        }

        # Save workflow state
        result = await state_manager.save_langgraph_workflow_state(
            "confluence_analysis", "SPY", "15m", workflow_state
        )

        assert result is True

        # Verify it was saved with correct state type
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        saved_data = json.loads(call_args[0][1])
        assert saved_data["metadata"]["state_type"] == "langgraph_workflow"
        assert saved_data["state"] == workflow_state

    @pytest.mark.asyncio
    async def test_state_cleanup(self, state_manager, mock_redis):
        """Test automatic state cleanup."""

        # Populate cache beyond max entries
        state_manager.max_cache_entries = 5
        for i in range(10):
            cache_key = f"plugin_{i}:SPY:1m:plugin"
            state_manager.state_cache[cache_key] = {
                "state": {"test": i},
                "metadata": {},
                "cached_at": time.time() - (i * 10),  # Different ages
            }

        # Trigger cleanup
        await state_manager._periodic_cleanup()

        # Should have reduced to 80% of max (4 entries)
        assert len(state_manager.state_cache) == 4

        # Should keep the newest entries (highest cached_at values)
        remaining_keys = list(state_manager.state_cache.keys())
        assert "plugin_0:SPY:1m:plugin" in remaining_keys  # Newest (time.time() - 0)

    @pytest.mark.asyncio
    async def test_health_check(self, state_manager, mock_redis):
        """Test state manager health check."""

        # Mock the Redis operations for health check
        # get must return non-None so health_check sees Redis as reachable
        mock_redis.get = AsyncMock(return_value='{"test": true}')
        mock_redis.keys = AsyncMock(return_value=[])

        health = await state_manager.health_check()

        assert health["status"] == "healthy"
        assert health["redis_connectivity"] is True
        assert "roundtrip_time_ms" in health
        assert "summary" in health


class TestPluginCircuitBreaker:
    """Test circuit breaker functionality."""

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


class TestPrometheusMetrics:
    """Test Prometheus metrics integration."""

    def test_plugin_execution_recording(self):
        """Test recording plugin execution metrics."""

        # This is more of an integration test to ensure no exceptions
        try:
            record_plugin_execution("RSI", "SPY", "1m", 0.015, "success", "I1")
            # Should not raise any exceptions
            assert True
        except Exception as e:
            pytest.fail(f"Plugin execution recording failed: {e}")

    def test_langgraph_workflow_recording(self):
        """Test recording LangGraph workflow metrics."""

        try:
            record_langgraph_workflow("confluence_analysis", 0.125, "success", "I5")
            # Should not raise any exceptions
            assert True
        except Exception as e:
            pytest.fail(f"LangGraph workflow recording failed: {e}")

    def test_event_routing_recording(self):
        """Test recording event routing metrics."""

        try:
            record_event_routing(
                "market_intelligence", "rsi_calculation", "pattern_detection", "high_confidence"
            )
            # Should not raise any exceptions
            assert True
        except Exception as e:
            pytest.fail(f"Event routing recording failed: {e}")


class TestIntegration:
    """Integration tests for the complete monitoring system."""

    @pytest.mark.asyncio
    async def test_complete_plugin_lifecycle(self):
        """Test complete plugin execution lifecycle with monitoring."""

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=None)

        # Create components
        state_manager = PluginStateManager(mock_redis, "test:")
        circuit_breaker = PluginCircuitBreaker(state_manager=state_manager)

        # Mock plugin with state
        plugin_state = {"rsi_value": 65.5, "gain": 1.2, "loss": 0.8}

        async def stateful_plugin():
            # Simulate plugin that uses state
            await state_manager.restore_plugin_state("RSI", "SPY", "1m")

            # Calculate new values
            new_state = plugin_state.copy()
            new_state["rsi_value"] = 67.0

            # Save updated state
            await state_manager.save_plugin_state("RSI", "SPY", "1m", new_state)

            return {"rsi": new_state["rsi_value"]}

        async def direct_fallback():
            return {"rsi": 66.0}  # Direct calculation result

        # Execute plugin through circuit breaker
        result = await circuit_breaker.execute_with_fallback(
            "RSI", stateful_plugin, direct_fallback, "I1"
        )

        assert result == {"rsi": 67.0}

        # Verify state was saved
        mock_redis.set.assert_called()

        # Verify circuit breaker tracked success
        plugin_cb_state = circuit_breaker.plugin_states["RSI"]
        assert plugin_cb_state.success_count == 1
        assert plugin_cb_state.state == CircuitState.CLOSED

        # Verify state manager cached the state
        cache_key = "RSI:SPY:1m:plugin"
        assert cache_key in state_manager.state_cache

    @pytest.mark.asyncio
    async def test_failure_recovery_cycle(self):
        """Test complete failure and recovery cycle."""

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)

        state_manager = PluginStateManager(mock_redis, "test:")
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1, success_threshold=1)
        circuit_breaker = PluginCircuitBreaker(config, state_manager)

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
            result = await circuit_breaker.execute_with_fallback(
                "UNRELIABLE", unreliable_plugin, fallback
            )
            results.append(result)

        # Circuit should be open now
        assert circuit_breaker.plugin_states["UNRELIABLE"].state == CircuitState.OPEN

        # Wait for recovery timeout
        await asyncio.sleep(1.1)

        # Next execution should recover
        result = await circuit_breaker.execute_with_fallback(
            "UNRELIABLE", unreliable_plugin, fallback
        )
        results.append(result)

        # Verify results
        assert results[0] == {"result": "fallback"}  # First failure
        assert results[1] == {"result": "fallback"}  # Second failure (circuit opens)
        assert results[2] == {"result": "recovered"}  # Recovery

        # Circuit should be closed again
        assert circuit_breaker.plugin_states["UNRELIABLE"].state == CircuitState.CLOSED


if __name__ == "__main__":
    # Run tests with verbose output
    pytest.main([__file__, "-v", "-s"])
