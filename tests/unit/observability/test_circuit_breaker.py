"""Tests for CircuitBreaker fault-tolerance class.

Behavior tests:
  1. CircuitBreaker starts in CLOSED state
  2. After N failures (default 5), circuit opens
  3. When circuit is OPEN, call() immediately raises CircuitOpenError
  4. After timeout_sec (default 60), circuit half-opens on next call
  5. Successful call in half-open state closes circuit
  6. Failed call in half-open state reopens circuit
"""

from __future__ import annotations

import pytest

from src.observability.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


@pytest.mark.asyncio
async def test_circuit_breaker_starts_closed():
    """Test 1: CircuitBreaker starts in CLOSED state."""
    cb = CircuitBreaker()
    assert cb.state == CircuitState.CLOSED
    assert cb.failures == 0


@pytest.mark.asyncio
async def test_circuit_opens_after_n_failures():
    """Test 2: After N failures (default 5), circuit opens."""
    cb = CircuitBreaker(failure_threshold=5)

    async def fail():
        raise ValueError("test failure")

    # Should stay closed until threshold
    for i in range(4):
        with pytest.raises(ValueError):
            await cb.call(fail)
        assert cb.state == CircuitState.CLOSED, f"Circuit opened too early on failure {i+1}"

    # 5th failure should open it
    with pytest.raises(ValueError):
        await cb.call(fail)
    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_open_circuit_raises_circuit_open_error():
    """Test 3: When circuit is OPEN, call() immediately raises CircuitOpenError."""
    cb = CircuitBreaker(failure_threshold=3)

    async def fail():
        raise RuntimeError("error")

    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(fail)

    assert cb.state == CircuitState.OPEN

    # Now circuit is open — should raise CircuitOpenError without calling func
    called = []

    async def should_not_be_called():
        called.append(True)
        return "ok"

    with pytest.raises(CircuitOpenError):
        await cb.call(should_not_be_called)

    assert not called, "Function should not be called when circuit is open"


@pytest.mark.asyncio
async def test_circuit_half_opens_after_timeout():
    """Test 4: After timeout_sec (default 60), circuit half-opens on next call."""
    cb = CircuitBreaker(failure_threshold=2, timeout_sec=0)  # immediate timeout

    async def fail():
        raise ValueError("error")

    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail)

    assert cb.state == CircuitState.OPEN

    # With timeout=0, any call should transition to HALF_OPEN
    # We need a function that doesn't raise to confirm the transition happened
    results = []

    async def succeed():
        results.append(cb.state)  # capture state during call
        return "ok"

    await cb.call(succeed)
    # After success it closes again, but during the call it was half-open
    # Alternatively, check that we didn't get CircuitOpenError
    assert cb.state == CircuitState.CLOSED  # success in half-open closes it


@pytest.mark.asyncio
async def test_successful_call_in_half_open_closes_circuit():
    """Test 5: Successful call in half-open state closes circuit."""
    cb = CircuitBreaker(failure_threshold=2, timeout_sec=0)

    async def fail():
        raise ValueError("error")

    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail)

    assert cb.state == CircuitState.OPEN

    async def succeed():
        return "success"

    result = await cb.call(succeed)
    assert result == "success"
    assert cb.state == CircuitState.CLOSED
    assert cb.failures == 0


@pytest.mark.asyncio
async def test_failed_call_in_half_open_reopens_circuit():
    """Test 6: Failed call in half-open state reopens circuit."""
    cb = CircuitBreaker(failure_threshold=2, timeout_sec=0)

    async def fail():
        raise ValueError("error")

    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail)

    assert cb.state == CircuitState.OPEN

    # timeout=0, so first call transitions to HALF_OPEN then fails, reopening
    with pytest.raises(ValueError):
        await cb.call(fail)

    assert cb.state == CircuitState.OPEN
