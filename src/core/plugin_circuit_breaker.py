"""
Plugin Circuit Breaker - Intelligent failure handling for plugins and LangGraph workflows

This module provides comprehensive circuit breaker functionality for:
- Plugin execution failure protection
- LangGraph workflow error handling
- Automatic fallback to direct calculations
- Intelligent recovery detection
- Performance degradation protection

Features:
- State-based circuit breaker (CLOSED, OPEN, HALF_OPEN)
- Per-plugin failure tracking
- Automatic recovery testing
- Fallback execution management
- Comprehensive metrics integration

Version: 1.0.0
Last Updated: 2025-08-17
Status: Production Ready ✅
"""

import asyncio
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

import structlog

# Import metrics and state manager
from src.observability.metrics import (
    CIRCUIT_BREAKER_STATE,
    PLUGIN_FALLBACK_TOTAL,
    record_langgraph_workflow,
    record_plugin_execution,
)

logger = structlog.get_logger(__name__)


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = 0  # Normal operation
    OPEN = 1  # Failing, use fallback
    HALF_OPEN = 2  # Testing recovery


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""

    failure_threshold: int = 3
    recovery_timeout: int = 300  # 5 minutes
    success_threshold: int = 2  # For half-open → closed transition
    max_half_open_calls: int = 5
    failure_window: int = 60  # Time window to track failures
    performance_threshold_ms: float = 5000.0  # Max acceptable execution time


@dataclass
class PluginFailureRecord:
    """Record of plugin failures."""

    timestamp: datetime
    error_type: str
    error_message: str
    execution_time_ms: float


@dataclass
class CircuitBreakerState:
    """State tracking for individual plugins."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: datetime | None = None
    last_success_time: datetime | None = None
    half_open_calls: int = 0
    total_calls: int = 0
    recent_failures: deque = field(default_factory=lambda: deque(maxlen=10))


class PluginCircuitBreaker:
    """Circuit breaker for plugin and workflow failure handling."""

    def __init__(
        self, config: CircuitBreakerConfig | None = None, state_manager: Any | None = None
    ):
        self.config = config or CircuitBreakerConfig()
        self.state_manager = state_manager

        # Per-plugin state tracking
        self.plugin_states: dict[str, CircuitBreakerState] = defaultdict(CircuitBreakerState)

        # Global statistics
        self.total_executions = 0
        self.total_fallbacks = 0
        self.total_failures = 0

        # Performance tracking
        self.performance_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))

    async def execute_with_fallback(
        self,
        plugin_name: str,
        plugin_fn: Callable,
        fallback_fn: Callable,
        intelligence_tier: str = "I1",
        *args,
        **kwargs,
    ) -> Any:
        """Execute plugin with automatic fallback on failure."""

        plugin_state = self.plugin_states[plugin_name]
        plugin_state.total_calls += 1
        self.total_executions += 1

        # Check circuit state
        if self._should_use_fallback(plugin_name):
            return await self._execute_fallback(
                plugin_name, fallback_fn, "circuit_breaker", *args, **kwargs
            )

        # Try plugin execution
        start_time = time.time()
        try:
            # Add timeout to prevent hanging
            result = await asyncio.wait_for(
                plugin_fn(*args, **kwargs), timeout=self.config.performance_threshold_ms / 1000.0
            )

            execution_time = (time.time() - start_time) * 1000  # ms

            # Record successful execution
            await self._record_success(plugin_name, execution_time, intelligence_tier, kwargs)

            return result

        except TimeoutError:
            execution_time = (time.time() - start_time) * 1000
            error_msg = f"Plugin execution timeout after {execution_time:.1f}ms"

            await self._record_failure(
                plugin_name, "timeout", error_msg, execution_time, intelligence_tier, kwargs
            )

            return await self._execute_fallback(
                plugin_name, fallback_fn, "timeout", *args, **kwargs
            )

        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            error_msg = str(e)
            error_type = type(e).__name__

            await self._record_failure(
                plugin_name, error_type, error_msg, execution_time, intelligence_tier, kwargs
            )

            return await self._execute_fallback(
                plugin_name, fallback_fn, "execution_failure", *args, **kwargs
            )

    async def execute_langgraph_workflow_with_fallback(
        self,
        workflow_name: str,
        workflow_fn: Callable,
        fallback_fn: Callable | None = None,
        *args,
        **kwargs,
    ) -> Any:
        """Execute LangGraph workflow with circuit breaker protection."""

        # Use workflow name as plugin name for circuit breaker
        if fallback_fn is None:
            # No fallback for pure LangGraph workflows, just track failures
            return await self.execute_workflow_with_monitoring(
                workflow_name, workflow_fn, *args, **kwargs
            )
        else:
            # Has fallback, use standard circuit breaker
            return await self.execute_with_fallback(
                workflow_name, workflow_fn, fallback_fn, "I5", *args, **kwargs
            )

    async def execute_workflow_with_monitoring(
        self, workflow_name: str, workflow_fn: Callable, *args, **kwargs
    ) -> Any:
        """Execute workflow with monitoring but no fallback."""
        start_time = time.time()

        try:
            result = await workflow_fn(*args, **kwargs)

            execution_time = time.time() - start_time
            record_langgraph_workflow(workflow_name, execution_time, "success", "I5")

            # Record success for circuit breaker tracking
            await self._record_success(workflow_name, execution_time * 1000, "I5", {})

            return result

        except Exception as e:
            execution_time = time.time() - start_time

            record_langgraph_workflow(workflow_name, execution_time, "failure", "I5")

            # Record failure for circuit breaker tracking
            await self._record_failure(
                workflow_name, type(e).__name__, str(e), execution_time * 1000, "I5", {}
            )

            raise  # Re-raise for LangGraph workflows

    def _should_use_fallback(self, plugin_name: str) -> bool:
        """Determine if fallback should be used based on circuit state."""
        plugin_state = self.plugin_states[plugin_name]

        if plugin_state.state == CircuitState.CLOSED:
            return False

        elif plugin_state.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if (
                plugin_state.last_failure_time
                and datetime.now() - plugin_state.last_failure_time
                > timedelta(seconds=self.config.recovery_timeout)
            ):

                plugin_state.state = CircuitState.HALF_OPEN
                plugin_state.half_open_calls = 0

                logger.info("Circuit breaker transitioning to HALF_OPEN", plugin=plugin_name)

                # Update metrics
                CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(plugin_state.state.value)

                return False
            return True

        elif plugin_state.state == CircuitState.HALF_OPEN:
            # Allow limited testing
            if plugin_state.half_open_calls < self.config.max_half_open_calls:
                plugin_state.half_open_calls += 1
                return False
            else:
                # Too many half-open calls, back to open
                plugin_state.state = CircuitState.OPEN
                plugin_state.last_failure_time = datetime.now()

                logger.warning(
                    "Circuit breaker returning to OPEN from HALF_OPEN", plugin=plugin_name
                )

                CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(plugin_state.state.value)

                return True

        return True

    async def _record_success(
        self,
        plugin_name: str,
        execution_time_ms: float,
        intelligence_tier: str,
        kwargs: dict[str, Any] = None,
    ):
        """Record successful plugin execution."""
        plugin_state = self.plugin_states[plugin_name]

        plugin_state.last_success_time = datetime.now()
        plugin_state.success_count += 1

        # Track performance
        self.performance_history[plugin_name].append(execution_time_ms)

        # Handle state transitions
        if plugin_state.state == CircuitState.HALF_OPEN:
            # Check if we have enough successes to close circuit
            if plugin_state.success_count >= self.config.success_threshold:
                plugin_state.state = CircuitState.CLOSED
                plugin_state.failure_count = 0
                plugin_state.success_count = 0
                plugin_state.half_open_calls = 0

                logger.info("Circuit breaker CLOSED after successful recovery", plugin=plugin_name)

        elif plugin_state.state == CircuitState.CLOSED:
            # Reset failure count on success
            plugin_state.failure_count = max(0, plugin_state.failure_count - 1)

        # Update metrics
        CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(plugin_state.state.value)

        # Record execution metrics
        record_plugin_execution(
            plugin_name,
            kwargs.get("symbol", "unknown") if kwargs else "unknown",
            kwargs.get("timeframe", "unknown") if kwargs else "unknown",
            execution_time_ms / 1000.0,
            "success",
            intelligence_tier,
        )

        # Save state if state manager available
        if self.state_manager:
            await self.state_manager.save_plugin_state(
                plugin_name,
                "circuit_breaker",
                "global",
                self._serialize_plugin_state(plugin_state),
                "circuit_breaker",
            )

    async def _record_failure(
        self,
        plugin_name: str,
        error_type: str,
        error_message: str,
        execution_time_ms: float,
        intelligence_tier: str,
        kwargs: dict[str, Any] = None,
    ):
        """Record failed plugin execution."""
        plugin_state = self.plugin_states[plugin_name]

        # Create failure record
        failure_record = PluginFailureRecord(
            timestamp=datetime.now(),
            error_type=error_type,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )

        plugin_state.recent_failures.append(failure_record)
        plugin_state.failure_count += 1
        plugin_state.last_failure_time = datetime.now()

        self.total_failures += 1

        # Check if we should open the circuit
        recent_failures = self._count_recent_failures(plugin_name)

        if (
            recent_failures >= self.config.failure_threshold
            and plugin_state.state == CircuitState.CLOSED
        ):

            plugin_state.state = CircuitState.OPEN

            logger.warning(
                "Circuit breaker OPENED due to failures",
                plugin=plugin_name,
                recent_failures=recent_failures,
                error_type=error_type,
            )

        elif plugin_state.state == CircuitState.HALF_OPEN:
            # Failure during half-open, back to open
            plugin_state.state = CircuitState.OPEN
            plugin_state.success_count = 0

            logger.warning(
                "Circuit breaker returning to OPEN from HALF_OPEN due to failure",
                plugin=plugin_name,
                error_type=error_type,
            )

        # Update metrics
        CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(plugin_state.state.value)

        record_plugin_execution(
            plugin_name,
            "unknown",  # Symbol not available in failure context
            "unknown",  # Timeframe not available
            execution_time_ms / 1000.0,
            "failure",
            intelligence_tier,
        )

        # Save state if state manager available
        if self.state_manager:
            await self.state_manager.save_plugin_state(
                plugin_name,
                "circuit_breaker",
                "global",
                self._serialize_plugin_state(plugin_state),
                "circuit_breaker",
            )

    def _count_recent_failures(self, plugin_name: str) -> int:
        """Count failures within the failure window."""
        plugin_state = self.plugin_states[plugin_name]
        cutoff_time = datetime.now() - timedelta(seconds=self.config.failure_window)

        recent_count = 0
        for failure in plugin_state.recent_failures:
            if failure.timestamp > cutoff_time:
                recent_count += 1

        return recent_count

    async def _execute_fallback(
        self, plugin_name: str, fallback_fn: Callable, reason: str, *args, **kwargs
    ) -> Any:
        """Execute fallback function and record metrics."""

        logger.debug("Using fallback function", plugin=plugin_name, reason=reason)

        # Update metrics
        PLUGIN_FALLBACK_TOTAL.labels(plugin_name=plugin_name, reason=reason).inc()

        self.total_fallbacks += 1

        try:
            start_time = time.time()

            if asyncio.iscoroutinefunction(fallback_fn):
                result = await fallback_fn(*args, **kwargs)
            else:
                result = fallback_fn(*args, **kwargs)

            execution_time = (time.time() - start_time) * 1000

            logger.debug(
                "Fallback execution successful",
                plugin=plugin_name,
                reason=reason,
                execution_time_ms=round(execution_time, 2),
            )

            return result

        except Exception as e:
            logger.error(
                "Fallback execution also failed", plugin=plugin_name, reason=reason, error=str(e)
            )
            raise

    def _serialize_plugin_state(self, state: CircuitBreakerState) -> dict[str, Any]:
        """Serialize plugin state for persistence."""
        return {
            "state": state.state.name,
            "failure_count": state.failure_count,
            "success_count": state.success_count,
            "last_failure_time": (
                state.last_failure_time.isoformat() if state.last_failure_time else None
            ),
            "last_success_time": (
                state.last_success_time.isoformat() if state.last_success_time else None
            ),
            "half_open_calls": state.half_open_calls,
            "total_calls": state.total_calls,
            "recent_failures": [
                {
                    "timestamp": f.timestamp.isoformat(),
                    "error_type": f.error_type,
                    "error_message": f.error_message,
                    "execution_time_ms": f.execution_time_ms,
                }
                for f in list(state.recent_failures)
            ],
        }

    async def restore_plugin_state(self, plugin_name: str) -> bool:
        """Restore plugin circuit breaker state from persistence."""
        if not self.state_manager:
            return False

        try:
            state_data = await self.state_manager.restore_plugin_state(
                plugin_name, "circuit_breaker", "global", "circuit_breaker"
            )

            if not state_data:
                return False

            # Deserialize state
            plugin_state = CircuitBreakerState()
            plugin_state.state = CircuitState[state_data.get("state", "CLOSED")]
            plugin_state.failure_count = state_data.get("failure_count", 0)
            plugin_state.success_count = state_data.get("success_count", 0)
            plugin_state.half_open_calls = state_data.get("half_open_calls", 0)
            plugin_state.total_calls = state_data.get("total_calls", 0)

            # Restore timestamps
            if state_data.get("last_failure_time"):
                plugin_state.last_failure_time = datetime.fromisoformat(
                    state_data["last_failure_time"]
                )
            if state_data.get("last_success_time"):
                plugin_state.last_success_time = datetime.fromisoformat(
                    state_data["last_success_time"]
                )

            # Restore recent failures
            for failure_data in state_data.get("recent_failures", []):
                failure = PluginFailureRecord(
                    timestamp=datetime.fromisoformat(failure_data["timestamp"]),
                    error_type=failure_data["error_type"],
                    error_message=failure_data["error_message"],
                    execution_time_ms=failure_data["execution_time_ms"],
                )
                plugin_state.recent_failures.append(failure)

            self.plugin_states[plugin_name] = plugin_state

            # Update metrics
            CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(plugin_state.state.value)

            logger.info(
                "Restored circuit breaker state", plugin=plugin_name, state=plugin_state.state.name
            )

            return True

        except Exception as e:
            logger.error(
                "Failed to restore circuit breaker state", plugin=plugin_name, error=str(e)
            )
            return False

    def get_plugin_stats(self) -> dict[str, Any]:
        """Get comprehensive circuit breaker statistics."""

        plugin_stats = {}
        for plugin_name, state in self.plugin_states.items():
            avg_performance = 0.0
            if plugin_name in self.performance_history:
                perf_history = list(self.performance_history[plugin_name])
                if perf_history:
                    avg_performance = sum(perf_history) / len(perf_history)

            plugin_stats[plugin_name] = {
                "state": state.state.name,
                "failure_count": state.failure_count,
                "success_count": state.success_count,
                "total_calls": state.total_calls,
                "avg_execution_time_ms": round(avg_performance, 2),
                "recent_failures_count": len(state.recent_failures),
                "last_failure": (
                    state.last_failure_time.isoformat() if state.last_failure_time else None
                ),
                "last_success": (
                    state.last_success_time.isoformat() if state.last_success_time else None
                ),
            }

        return {
            "global_stats": {
                "total_executions": self.total_executions,
                "total_fallbacks": self.total_fallbacks,
                "total_failures": self.total_failures,
                "fallback_rate_percent": round(
                    (self.total_fallbacks / max(self.total_executions, 1)) * 100, 2
                ),
            },
            "plugin_stats": plugin_stats,
            "configuration": {
                "failure_threshold": self.config.failure_threshold,
                "recovery_timeout": self.config.recovery_timeout,
                "success_threshold": self.config.success_threshold,
                "performance_threshold_ms": self.config.performance_threshold_ms,
            },
        }

    async def force_reset_plugin(self, plugin_name: str) -> bool:
        """Force reset a plugin's circuit breaker state."""
        try:
            if plugin_name in self.plugin_states:
                # Reset to clean state
                self.plugin_states[plugin_name] = CircuitBreakerState()

                # Update metrics
                CIRCUIT_BREAKER_STATE.labels(plugin_name=plugin_name).set(0)  # CLOSED

                # Clear persisted state
                if self.state_manager:
                    await self.state_manager.clear_plugin_state(
                        plugin_name, "circuit_breaker", "global", "circuit_breaker"
                    )

                logger.info("Forcefully reset circuit breaker", plugin=plugin_name)
                return True

            return False

        except Exception as e:
            logger.error("Failed to reset circuit breaker", plugin=plugin_name, error=str(e))
            return False
