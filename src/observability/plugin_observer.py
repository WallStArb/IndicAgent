"""PluginObserver — single recording surface for all plugin execution metrics.

Injected into PluginExecutor at construction. Decouples metric recording from
executor logic — executor calls observer methods, observer owns the OTel calls.

NoOpPluginObserver provides an identical interface with no-op methods for use
in tests and environments where metrics are not needed.
"""

from __future__ import annotations

from src.observability.metrics import (
    CIRCUIT_BREAKER_STATE,
    PLUGIN_CONFIDENCE_HISTOGRAM,
    PLUGIN_DURATION_MS,
    PLUGIN_ERRORS_TOTAL,
    PLUGIN_FALLBACK_TOTAL,
    PLUGIN_OUTPUT_NULL_TOTAL,
    PLUGIN_SIGNAL_EMIT_TOTAL,
    PLUGIN_STATE_VALIDATION_ERRORS_TOTAL,
    PLUGIN_WARMUP_SKIP_TOTAL,
)


class PluginObserver:
    """Records plugin execution metrics via OTel instruments.

    All methods accept labeled attributes and delegate directly to OTel counters,
    histograms, and gauges. No state is held beyond instrument references.
    """

    def __init__(self) -> None:
        self._duration_hist = PLUGIN_DURATION_MS
        self._errors_counter = PLUGIN_ERRORS_TOTAL
        self._fallback_counter = PLUGIN_FALLBACK_TOTAL
        self._warmup_skip_counter = PLUGIN_WARMUP_SKIP_TOTAL
        self._null_output_counter = PLUGIN_OUTPUT_NULL_TOTAL
        self._state_error_counter = PLUGIN_STATE_VALIDATION_ERRORS_TOTAL
        self._signal_emit_counter = PLUGIN_SIGNAL_EMIT_TOTAL
        self._confidence_hist = PLUGIN_CONFIDENCE_HISTOGRAM
        self._cb_state_gauge = CIRCUIT_BREAKER_STATE

    def record_result(
        self,
        plugin_name: str,
        tier: str,
        duration_ms: float,
        *,
        used_incremental: bool,
        null_count: int,
    ) -> None:
        """Record a successful plugin execution result.

        Args:
            plugin_name:     Plugin name label.
            tier:            Execution tier label (e.g. "i1", "i2", "i7").
            duration_ms:     Wall-clock execution time in milliseconds.
            used_incremental: True if compute_next() path was taken.
            null_count:      Number of null/NaN output values in this result.
        """
        attrs = {"plugin_name": plugin_name, "tier": tier}
        self._duration_hist.record(duration_ms, attrs)
        if not used_incremental:
            self._fallback_counter.add(1, attrs)
        if null_count > 0:
            self._null_output_counter.add(null_count, attrs)

    def record_error(self, plugin_name: str, tier: str, error: str) -> None:
        """Record a plugin execution error.

        Args:
            plugin_name: Plugin name label.
            tier:        Execution tier label.
            error:       Error message string.
        """
        self._errors_counter.add(1, {"plugin_name": plugin_name, "tier": tier})

    def record_circuit_breaker_change(self, plugin_name: str, new_state: str) -> None:
        """Record a circuit breaker state change.

        Args:
            plugin_name: Plugin name label.
            new_state:   New state string: "open", "half_open", or "closed".
        """
        state_value = {"open": 1, "half_open": 2, "closed": 0}.get(new_state, 0)
        self._cb_state_gauge.set(state_value, {"plugin_name": plugin_name})

    def record_warmup_skip(self, plugin_name: str, tier: str) -> None:
        """Record a plugin execution skipped due to insufficient warmup bars.

        Args:
            plugin_name: Plugin name label.
            tier:        Execution tier label.
        """
        self._warmup_skip_counter.add(1, {"plugin_name": plugin_name, "tier": tier})

    def record_state_error(self, plugin_name: str, error: str) -> None:
        """Record a plugin state validation error (missing _state key in incremental output).

        Args:
            plugin_name: Plugin name label.
            error:       Error description string.
        """
        self._state_error_counter.add(1, {"plugin_name": plugin_name})

    def record_i7_signal(self, plugin_name: str, confidence: float) -> None:
        """Record an I7 signal emission via emit_signal().

        Args:
            plugin_name: I7 plugin name label.
            confidence:  Signal confidence value (0.0–1.0).
        """
        attrs = {"plugin_name": plugin_name}
        self._signal_emit_counter.add(1, attrs)
        self._confidence_hist.record(confidence, attrs)


class NoOpPluginObserver:
    """No-op implementation of PluginObserver interface.

    Used in tests and lightweight executor instances where metrics collection
    is not needed. All methods accept the same arguments as PluginObserver
    but perform no operations.
    """

    def record_result(
        self,
        plugin_name: str,
        tier: str,
        duration_ms: float,
        *,
        used_incremental: bool,
        null_count: int,
    ) -> None:
        pass

    def record_error(self, plugin_name: str, tier: str, error: str) -> None:
        pass

    def record_circuit_breaker_change(self, plugin_name: str, new_state: str) -> None:
        pass

    def record_warmup_skip(self, plugin_name: str, tier: str) -> None:
        pass

    def record_state_error(self, plugin_name: str, error: str) -> None:
        pass

    def record_i7_signal(self, plugin_name: str, confidence: float) -> None:
        pass
