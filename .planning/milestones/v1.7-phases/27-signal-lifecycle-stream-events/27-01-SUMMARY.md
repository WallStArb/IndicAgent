---
phase: 27-signal-lifecycle-stream-events
plan: "01"
subsystem: signal-lifecycle
tags: [signal-lifecycle, redis-streams, terminal-events, tdd]
dependency_graph:
  requires: []
  provides: [_publish_terminal_event]
  affects: [signal_lifecycle_service, signals_aggregated_stream]
tech_stack:
  added: []
  patterns: [redis-xadd, direction=0-sentinel, async-helper-method]
key_files:
  created: []
  modified:
    - services/signal_lifecycle_service.py
    - tests/unit/service_tests/test_signal_lifecycle_service.py
decisions:
  - "Implementation already present in v1.6 monolith commit (0d8706f) — tests verified green, no code changes needed"
metrics:
  duration_minutes: 1
  completed_date: "2026-03-12"
  tasks_completed: 1
  files_modified: 0
requirements: [SLES-01]
---

# Phase 27 Plan 01: Terminal Event Publication Summary

One-liner: `_publish_terminal_event()` async helper publishes direction=0 sentinel to `signals:SYMBOL:TF:aggregated` Redis stream on every signal exit, with full unit test coverage.

## What Was Done

### Task 1: Implement _publish_terminal_event() helper method

**Status:** Pre-existing — verified passing.

The `_publish_terminal_event()` method was already implemented in `services/signal_lifecycle_service.py` as part of the v1.6 monolith commit (`0d8706f`). All unit tests in `TestPublishTerminalEvent` and `TestTerminalEventWiring` classes already existed and passed.

**Implementation (lines 187-222 of signal_lifecycle_service.py):**

- Method signature: `async def _publish_terminal_event(self, signal_id, symbol, timeframe, outcome, exit_price, bar_ts)`
- Builds stream key using `sk_signals_aggregated(self.env_prefix, symbol, timeframe)`
- Payload contains: `direction="0"`, `signal_id`, `status`, `outcome`, `exit_price` (empty string if None), `symbol`, `timeframe`, `timestamp`
- Calls `redis_client.xadd(stream_key, payload, maxlen=200, approximate=True)`
- Early-return guard when `redis_client is None`
- Warning log on exception (non-fatal)
- Called in both normal exit path (active → stopped/target/TTL) and shadow signal exit path (regime_suppressed)

**Test coverage (23 tests, all passing):**
- `TestPublishTerminalEvent::test_xadd_called_with_direction_zero` — direction sentinel verified
- `TestPublishTerminalEvent::test_stream_key_uses_env_prefix` — env-prefixed stream key
- `TestPublishTerminalEvent::test_exit_price_empty_string_when_none` — None handling
- `TestPublishTerminalEvent::test_no_xadd_when_redis_none` — early-return guard
- `TestTerminalEventWiring::test_terminal_event_fires_on_normal_exit` — wiring to exit path

**Verification:**
```
.venv/bin/pytest tests/unit/service_tests/test_signal_lifecycle_service.py -xvs
23 passed in 0.12s
```

Full unit suite: 1503 passed (no regressions).

## Commits

| Task | Description | Commit |
|------|-------------|--------|
| Pre-existing | Signal lifecycle service + terminal event method | 0d8706f |

## Deviations from Plan

None — plan executed exactly as written. Implementation was already present and fully tested from v1.6 development. TDD verification confirmed: all 5 behavior tests pass covering direction sentinel, stream key construction, env prefix, None exit_price handling, and early-return guard.

## Self-Check: PASSED

- [x] `services/signal_lifecycle_service.py` contains `_publish_terminal_event()` method (lines 187-222)
- [x] `tests/unit/service_tests/test_signal_lifecycle_service.py` contains `TestPublishTerminalEvent` class
- [x] 23 tests pass in test file
- [x] 1503 total unit tests pass
