"""Circuit breaker for fault-tolerant stage execution."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from enum import Enum

import structlog

# Shadow-mode global override: set PLUGIN_CB_ENABLED=true to activate all plugin
# circuit breakers that were constructed with enabled=False (shadow mode).
# Read once at import — not per-call — to avoid scattered os.environ access.
_PLUGIN_CB_GLOBAL_ENABLE = os.environ.get("PLUGIN_CB_ENABLED", "false").lower() == "true"

# OTel gauge for circuit breaker state transitions.
# 0 = CLOSED, 1 = OPEN, 2 = HALF_OPEN.
# Using get_meter directly to avoid circular import with src.observability.metrics.
try:
    from opentelemetry.metrics import get_meter as _get_meter

    _cb_state_gauge = _get_meter("indicagent").create_gauge(
        "intelligence_pipeline_plugin_cb_state",
        description="Plugin circuit breaker state (0=closed, 1=open, 2=half_open)",
    )
except Exception:
    _cb_state_gauge = None  # type: ignore[assignment]

_STATE_VALUE = {
    "closed": 0,
    "open": 1,
    "half_open": 2,
}

_log = structlog.get_logger(__name__)


def _record_cb_state(name: str | None, state: CircuitState, enabled: bool) -> None:
    """Emit OTel gauge for circuit breaker state. No-op if OTel unavailable."""
    if _cb_state_gauge is None:
        return
    label = name or "unknown"
    try:
        _cb_state_gauge.set(_STATE_VALUE.get(state.value, 0), {"plugin": label})
    except Exception:
        pass


class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when circuit is OPEN and calls are rejected."""


@dataclass
class CircuitBreaker:
    """Circuit breaker with failure threshold and auto-recovery.

    State machine:
      CLOSED  → OPEN      : after failure_threshold consecutive failures
      OPEN    → HALF_OPEN : after timeout_sec has elapsed since last failure
      HALF_OPEN → CLOSED  : on a successful call
      HALF_OPEN → OPEN    : on a failed call

    Shadow mode (enabled=False):
      allow_request() always returns True (transparent passthrough) but still
      runs the full state machine so the breaker accumulates real failure data.
      record_success() / record_failure() run unconditionally in both modes —
      only the blocking effect of allow_request() is suppressed.

      Set PLUGIN_CB_ENABLED=true to force-activate all shadow-mode breakers.
    """

    failure_threshold: int = 5
    timeout_sec: int = 60
    name: str | None = None
    enabled: bool = True

    def __post_init__(self) -> None:
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()
        # Effective enablement: explicit arg OR global env-var override.
        # A breaker constructed with enabled=False stays shadow until
        # PLUGIN_CB_ENABLED=true is set; breakers with enabled=True (IBKR/LLM)
        # are always active regardless of the env var.
        self._enabled = self.enabled or _PLUGIN_CB_GLOBAL_ENABLE

    def _on_open_transition(self) -> None:
        """Emit structlog warning and OTel gauge when transitioning to OPEN."""
        _log.warning(
            "plugin.circuit_breaker_opened",
            breaker=self.name,
            enabled=self._enabled,
        )
        _record_cb_state(self.name, CircuitState.OPEN, self._enabled)

    async def call(self, func, *args, **kwargs):
        """Execute func with circuit breaker protection."""
        async with self._lock:
            # Transition OPEN → HALF_OPEN after timeout
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.timeout_sec:
                    self._state = CircuitState.HALF_OPEN
                    _record_cb_state(self.name, CircuitState.HALF_OPEN, self._enabled)
                else:
                    raise CircuitOpenError(f"Circuit is OPEN — reopens after {self.timeout_sec}s")

            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Success: reset failure count and close circuit
                self._failures = 0
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.CLOSED
                    _record_cb_state(self.name, CircuitState.CLOSED, self._enabled)

                return result

            except Exception:
                self._failures += 1
                self._last_failure_time = time.time()

                # HALF_OPEN failure → back to OPEN immediately
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                    self._on_open_transition()
                elif self._failures >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._on_open_transition()

                raise

    def allow_request(self) -> bool:
        """Return True if a request should be allowed.

        Runs the full state machine unconditionally (OPEN→HALF_OPEN on timeout).
        In shadow mode (not self._enabled), returns True even when OPEN so that
        live plugin routing is never blocked — while still allowing the state
        machine to run so shadow breakers accumulate failure data.
        """
        if self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
            return True
        # OPEN: check timeout and potentially transition to HALF_OPEN
        if time.time() - self._last_failure_time >= self.timeout_sec:
            self._state = CircuitState.HALF_OPEN
            _record_cb_state(self.name, CircuitState.HALF_OPEN, self._enabled)
            return True
        # State machine ran — OPEN and timeout not elapsed.
        # In shadow mode: transparent passthrough (return True).
        # In active mode: block the request (return False).
        if not self._enabled:
            return True
        return False

    def record_failure(self) -> None:
        """Manually record a failure (for use in try/except outside call()).

        Unconditional — runs in both shadow and active mode so shadow breakers
        accumulate real failure data for threshold analysis.
        """
        prev_state = self._state
        self._failures += 1
        self._last_failure_time = time.time()
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
        elif self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
        if self._state == CircuitState.OPEN and prev_state != CircuitState.OPEN:
            self._on_open_transition()

    def record_success(self) -> None:
        """Record a successful execution; resets failure count and closes from HALF_OPEN.

        Unconditional — runs in both shadow and active mode.
        """
        self._failures = 0
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            _record_cb_state(self.name, CircuitState.CLOSED, self._enabled)

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def failures(self) -> int:
        """Current consecutive failure count."""
        return self._failures
