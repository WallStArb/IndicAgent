"""Circuit breaker for fault-tolerant stage execution."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum


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
    """

    failure_threshold: int = 5
    timeout_sec: int = 60

    def __post_init__(self) -> None:
        self._state = CircuitState.CLOSED
        self._failures = 0
        self._last_failure_time = 0.0
        self._lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        """Execute func with circuit breaker protection."""
        async with self._lock:
            # Transition OPEN → HALF_OPEN after timeout
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.timeout_sec:
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise CircuitOpenError(
                        f"Circuit is OPEN — reopens after {self.timeout_sec}s"
                    )

            try:
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)

                # Success: reset failure count and close circuit
                self._failures = 0
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.CLOSED

                return result

            except Exception:
                self._failures += 1
                self._last_failure_time = time.time()

                # HALF_OPEN failure → back to OPEN immediately
                if self._state == CircuitState.HALF_OPEN:
                    self._state = CircuitState.OPEN
                elif self._failures >= self.failure_threshold:
                    self._state = CircuitState.OPEN

                raise

    def record_failure(self) -> None:
        """Manually record a failure (for use in try/except outside call())."""
        self._failures += 1
        self._last_failure_time = time.time()
        if self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        return self._state

    @property
    def failures(self) -> int:
        """Current consecutive failure count."""
        return self._failures
