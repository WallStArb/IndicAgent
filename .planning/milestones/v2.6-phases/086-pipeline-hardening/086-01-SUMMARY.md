# Plan 086-01 Summary

## What Was Built

Per-plugin circuit breakers are now wired through all three tier execution paths
(`_run_i1`, `_run_tier`, `_run_i7_inner`) in the intelligence pipeline. A plugin that
raises 3 consecutive times opens its circuit breaker and is skipped until the 300-second
recovery window expires. Additionally, checkpoint write failures now surface as
exceptions rather than being swallowed, and the signal publish path blocks on a full
output queue instead of silently dropping bars.

## Tasks Completed

- [x] Task 1: Extend CircuitBreaker API + wire per-plugin breakers into pipeline (PIPE-01)
- [x] Task 2: Make _write_local_checkpoint raise on failure (PIPE-03)
- [x] Task 3: Add _enqueue_blocking and convert signal-path enqueues (PIPE-04)

## Key Changes

- `src/observability/circuit_breaker.py`: Added `allow_request() -> bool` (handles OPEN→HALF_OPEN time transition) and `record_success() -> None` (resets failures, closes from HALF_OPEN). Also hardened `record_failure()` to transition HALF_OPEN→OPEN immediately on failure.
- `services/intelligence_pipeline_agent.py`:
  - Added `from src.observability.circuit_breaker import CircuitBreaker, CircuitState` and `CIRCUIT_BREAKER_STATE` metric import
  - Added `self._plugin_circuit_breakers: dict[str, CircuitBreaker] = {}` in `__init__`
  - Added `_get_plugin_cb(plugin_name) -> CircuitBreaker` lazy factory with `failure_threshold=3, timeout_sec=300`
  - Added `if not cb.allow_request(): continue` skip guard before `tasks.append` in `_run_i1`, `_run_tier`, `_run_i7_inner`
  - Extended `_collect_plugin_results` exception branch: `cb.record_failure()` + conditional `CIRCUIT_BREAKER_STATE.set(1)` + `plugin.circuit_breaker_opened` warning
  - Extended `_collect_plugin_results` success branch: `cb.record_success()` + conditional `CIRCUIT_BREAKER_STATE.set(0)` + `plugin.circuit_breaker_closed` info on recovery
  - Removed `try/except` swallow from `_write_local_checkpoint`; updated docstring to "Raises on failure"
  - Added `async def _enqueue_blocking(topic, key, value)` with `await queue.put()` backpressure
  - Converted `_publish_signals_or_dlq` from `def` to `async def`; both enqueue paths inside use `await _enqueue_blocking`
  - Converted winner enqueue in `_run_i7_inner` to `await _enqueue_blocking`
- `src/core/agent/base.py`: Added `_plugin_circuit_breakers` fallback in `__getattr__` for test pattern that bypasses `__init__` via `__new__`

## Deviations from Plan

**[Rule 1 - Bug] BaseAgent.__getattr__ missing _plugin_circuit_breakers fallback**
- Found during: Task 1 acceptance criteria (test run)
- Issue: Tests using `ServiceClass.__new__(ServiceClass)` bypass `__init__`, so `_plugin_circuit_breakers` was missing; `__getattr__` raised `AttributeError` instead of returning a safe default
- Fix: Added `if name == "_plugin_circuit_breakers": return {}` to the `__getattr__` fallback in `src/core/agent/base.py`
- Files modified: `src/core/agent/base.py`
- Verification: `pytest tests/unit/test_pipeline_exception_isolation.py` - 6 previously failing tests now pass

**[Rule 1 - Bug] record_failure() did not transition HALF_OPEN→OPEN**
- Found during: Task 1 implementation review
- Issue: The existing `record_failure()` only checked `_failures >= failure_threshold` for OPEN transition; a failure during HALF_OPEN should immediately return to OPEN without waiting for threshold
- Fix: Added `if self._state == CircuitState.HALF_OPEN: self._state = CircuitState.OPEN` before the threshold check
- Files modified: `src/observability/circuit_breaker.py`

Total deviations: 2 auto-fixed (both Rule 1 - Bug). Impact: low; both fixes were required for correctness.

## Recommendation on PIPE-01 Unit Test

Adding a unit test that simulates 3 consecutive plugin failures would lock in the circuit breaker behavior and prevent regression. A fixture that patches `_timed_plugin_call` to raise on a specific plugin for 3 bars, then verifies:
1. The plugin is skipped on bar 4 (circuit OPEN)
2. After mocking `time.time()` past 300 seconds, `allow_request()` returns True again (HALF_OPEN probe)
3. `CIRCUIT_BREAKER_STATE` is set to 1 on open and 0 on recovery

This is a good candidate for `tests/unit/test_pipeline_exception_isolation.py` as a new `TestCircuitBreaker` class.

## Verification

- Tests pass: yes (3260 passed, 1 skipped)
- Lint clean: yes (ruff exits 0 on both changed files)
- No new `prometheus_client` imports: verified
- No import of `src.core.plugin_circuit_breaker`: verified
- Structlog calls use keyword args (`plugin=`, `qsize=`): verified
